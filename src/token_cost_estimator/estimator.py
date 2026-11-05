"""Token counting and cost estimation."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Protocol

from .errors import EstimatorError, InputTooLargeError
from .pricing import PricingTable

__all__ = ["DEFAULT_MAX_CHARS", "Estimate", "HeuristicTokenizer", "Tokenizer", "estimate"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFAULT_MAX_CHARS = 2_000_000

_MAX_CHARS_LIMIT = 10**9
_MAX_TOKENS = 10**12
_MAX_MESSAGES = 100_000
_QUANTUM = Decimal("0.000001")
_MILLION = Decimal(1_000_000)
_ZERO = Decimal(0)
_PRECISION = 80


class Tokenizer(Protocol):
    """Anything that can count the tokens of a text."""

    def count(self, text: str) -> int:
        """Return the number of tokens in ``text``."""
        ...


class HeuristicTokenizer:
    """Approximate tokenizer: ``ceil(code points / chars_per_token)``.

    This is an approximation only. It undercounts CJK text and source code, where tokens
    cover fewer characters than in English prose. Pass a real :class:`Tokenizer` to
    :func:`estimate` when accuracy matters.
    """

    def __init__(self, chars_per_token: int = 4) -> None:
        _check_int("chars_per_token", chars_per_token, 1, 10**6)
        self.chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        """Return ``ceil(len(text) / chars_per_token)`` counting Unicode code points."""
        return -(-len(text) // self.chars_per_token)


@dataclass(frozen=True)
class Estimate:
    """Result of :func:`estimate`; every cost is a ``Decimal`` rounded to six places."""

    input_tokens: int
    output_tokens: int
    input_cost: Decimal
    cached_cost: Decimal
    cache_write_cost: Decimal
    output_cost: Decimal
    total: Decimal
    currency: str
    table_version: str
    as_of: date
    exceeds_context: bool


def _invalid(message: str) -> EstimatorError:
    return EstimatorError("invalid_argument", message)


def _check_int(name: str, value: object, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _invalid(f"{name} must be an integer between {minimum} and {maximum}")


def _collect(messages: str | Sequence[str], max_chars: int) -> tuple[str, ...]:
    if isinstance(messages, str):
        items: Sequence[str] = (messages,)
    elif isinstance(messages, Sequence) and not isinstance(messages, (bytes, bytearray)):
        items = messages
    else:
        raise _invalid("messages must be a string or a sequence of strings")
    if len(items) > _MAX_MESSAGES:
        raise InputTooLargeError(f"more than {_MAX_MESSAGES} messages")
    total = 0
    for item in items:
        if not isinstance(item, str):
            raise _invalid("every message must be a string")
        total += len(item)
        if total > max_chars:
            raise InputTooLargeError(f"input exceeds max_chars={max_chars}")
    return tuple(items)


def _checked_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_TOKENS:
        raise _invalid("tokenizer returned an invalid token count")
    return value


def _cost(tokens: int, rate: Decimal) -> Decimal:
    with localcontext(Context(prec=_PRECISION)):
        return (Decimal(tokens) * rate / _MILLION).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def estimate(
    messages: str | Sequence[str],
    *,
    provider: str,
    model: str,
    table: PricingTable,
    expected_output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
    tokenizer: Tokenizer | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Estimate:
    """Estimate the token counts and cost of one request.

    Input tokens are counted per message and summed. Uncached input is
    ``input_tokens - cached_input_tokens - cache_write_tokens``; each token class is priced per
    million tokens, each component is quantized to six places with ``ROUND_HALF_EVEN`` and the
    total is the sum of the rounded components. Not modeled: long-context tiers, batch
    discounts, image or audio tokens and per-message overhead.

    Raises:
        InputTooLargeError: if the text exceeds ``max_chars`` characters.
        UnknownModelError: if the model is not in ``table``.
        EstimatorError: with code ``invalid_argument`` for bad arguments, cached plus
            cache-write tokens above the input size, or a missing cached/cache-write rate.
    """
    _check_int("max_chars", max_chars, 0, _MAX_CHARS_LIMIT)
    _check_int("expected_output_tokens", expected_output_tokens, 0, _MAX_TOKENS)
    _check_int("cached_input_tokens", cached_input_tokens, 0, _MAX_TOKENS)
    _check_int("cache_write_tokens", cache_write_tokens, 0, _MAX_TOKENS)
    texts = _collect(messages, max_chars)
    price = table.get(provider, model)
    counter = tokenizer if tokenizer is not None else HeuristicTokenizer()
    input_tokens = sum(_checked_count(counter.count(text)) for text in texts)
    if cached_input_tokens + cache_write_tokens > input_tokens:
        raise _invalid("cached and cache-write tokens must not exceed input tokens")
    cached_rate = price.cached_input_per_mtok
    write_rate = price.cache_write_per_mtok
    if cached_input_tokens and cached_rate is None:
        raise _invalid("model has no cached-input rate")
    if cache_write_tokens and write_rate is None:
        raise _invalid("model has no cache-write rate")
    uncached = input_tokens - cached_input_tokens - cache_write_tokens
    input_cost = _cost(uncached, price.input_per_mtok)
    cached_cost = _cost(cached_input_tokens, cached_rate or _ZERO)
    cache_write_cost = _cost(cache_write_tokens, write_rate or _ZERO)
    output_cost = _cost(expected_output_tokens, price.output_per_mtok)
    with localcontext(Context(prec=_PRECISION)):
        total = input_cost + cached_cost + cache_write_cost + output_cost
    logger.debug(
        "estimated provider=%s model=%s input_tokens=%d output_tokens=%d",
        provider,
        model,
        input_tokens,
        expected_output_tokens,
    )
    return Estimate(
        input_tokens=input_tokens,
        output_tokens=expected_output_tokens,
        input_cost=input_cost,
        cached_cost=cached_cost,
        cache_write_cost=cache_write_cost,
        output_cost=output_cost,
        total=total,
        currency=table.currency,
        table_version=table.version,
        as_of=table.as_of,
        exceeds_context=input_tokens + expected_output_tokens > price.context_window,
    )

"""Typed errors raised by ``token_cost_estimator``.

Every error derives from :class:`EstimatorError` and carries a stable, machine-readable
``code``. Messages are capped at 200 characters and never echo more than a short slice of
caller-supplied input.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

__all__ = [
    "ErrorCode",
    "EstimatorError",
    "InputTooLargeError",
    "PricingTableError",
    "UnknownModelError",
]

ErrorCode = Literal["unknown_model", "pricing_table", "input_too_large", "invalid_argument"]

_MAX_MESSAGE = 200


def clip_input(text: str, limit: int = 60) -> str:
    """Return ``text`` truncated to ``limit`` characters, for use inside messages."""
    return text if len(text) <= limit else text[:limit] + "..."


class EstimatorError(ValueError):
    """Base class of every error raised by this library.

    Attributes:
        code: stable machine-readable error code.
    """

    code: ErrorCode

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message[:_MAX_MESSAGE])
        self.code = code


class UnknownModelError(EstimatorError):
    """Raised when a provider/model pair is not present in the pricing table.

    Attributes:
        suggestions: up to three close model names from the table.
    """

    def __init__(self, provider: str, model: str, suggestions: Sequence[str] = ()) -> None:
        text = f"unknown model {clip_input(model)!r} for provider {clip_input(provider)!r}"
        if suggestions:
            text += "; did you mean: " + ", ".join(suggestions)
        super().__init__("unknown_model", text)
        self.suggestions: tuple[str, ...] = tuple(suggestions)


class PricingTableError(EstimatorError):
    """Raised when a pricing table is malformed, unreadable or too large.

    Attributes:
        field: dotted path of the offending field (for example ``models[0].input_per_mtok``),
            or ``None`` when the whole document is at fault.
    """

    def __init__(self, message: str, field: str | None = None) -> None:
        text = f"{field}: {message}" if field else message
        super().__init__("pricing_table", text)
        self.field = field


class InputTooLargeError(EstimatorError):
    """Raised when the text to estimate exceeds the configured size limit."""

    def __init__(self, message: str) -> None:
        super().__init__("input_too_large", message)

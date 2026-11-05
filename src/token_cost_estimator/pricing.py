"""Dated, versioned pricing tables.

Prices are :class:`~decimal.Decimal` values and never pass through ``float``: table JSON is
parsed with ``parse_float=Decimal`` and ``parse_int=Decimal``. Prices change often, so every
table carries a ``version`` and an ``as_of`` date and every row a ``source`` URL.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from .errors import PricingTableError, UnknownModelError, clip_input

__all__ = ["ModelPrice", "PricingTable"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_MAX_TABLE_BYTES = 1024 * 1024
_MAX_MODELS = 2000
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")
_MAX_PRICE = Decimal(10**9)
_MAX_WINDOW = 10**10
_MAX_TEXT = 500
_MAX_NUMBER_TEXT = 64


@dataclass(frozen=True)
class ModelPrice:
    """Per-million-token prices of one model.

    ``cached_input_per_mtok`` and ``cache_write_per_mtok`` are ``None`` when the model has no
    such rate.
    """

    provider: str
    model: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cached_input_per_mtok: Decimal | None
    cache_write_per_mtok: Decimal | None
    context_window: int
    source: str


@dataclass(frozen=True)
class PricingTable:
    """An immutable, dated collection of :class:`ModelPrice` rows."""

    version: str
    as_of: date
    currency: str
    models: tuple[ModelPrice, ...]
    _index: dict[tuple[str, str], ModelPrice] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        index: dict[tuple[str, str], ModelPrice] = {}
        for price in self.models:
            key = (price.provider, price.model)
            if key in index:
                raise PricingTableError("duplicate provider/model pair", "models")
            index[key] = price
        object.__setattr__(self, "_index", index)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> PricingTable:
        """Build a table from parsed JSON (schema 1).

        Prices may be ``Decimal``, ``int`` or ``str``; ``float`` is rejected so that prices
        never pass through binary floating point.

        Raises:
            PricingTableError: if the document is malformed (``field`` names the culprit).
        """
        if not isinstance(data, Mapping):
            raise PricingTableError("table must be a JSON object")
        schema = _integer(_require(data, "schema", ""), "schema", 1, 10**6)
        if schema != 1:
            raise PricingTableError("unsupported schema version", "schema")
        version = _text(_require(data, "version", ""), "version", 64)
        as_of = _parse_date(_require(data, "as_of", ""))
        currency = _require(data, "currency", "")
        if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
            raise PricingTableError("must be a three-letter upper-case code", "currency")
        raw_models = _require(data, "models", "")
        if not isinstance(raw_models, (list, tuple)) or len(raw_models) > _MAX_MODELS:
            raise PricingTableError(f"must be a list of at most {_MAX_MODELS} models", "models")
        models: list[ModelPrice] = []
        seen: set[tuple[str, str]] = set()
        for position, item in enumerate(raw_models):
            price = _parse_model(item, position)
            key = (price.provider, price.model)
            if key in seen:
                raise PricingTableError("duplicate provider/model pair", f"models[{position}].model")
            seen.add(key)
            models.append(price)
        return cls(version=version, as_of=as_of, currency=currency, models=tuple(models))

    @classmethod
    def load(cls, path: Path) -> PricingTable:
        """Load a table from a JSON file of at most 1 MiB.

        Raises:
            PricingTableError: if the file is unreadable, too large or malformed.
        """
        try:
            with Path(path).open("rb") as handle:
                raw = handle.read(_MAX_TABLE_BYTES + 1)
        except OSError as exc:
            raise PricingTableError("cannot read pricing table file", "file") from exc
        return cls._from_bytes(raw)

    @classmethod
    def bundled(cls) -> PricingTable:
        """Return the table shipped with the package.

        Prices change: verify them against each row's ``source`` or override the table.
        """
        return _bundled()

    @classmethod
    def _from_bytes(cls, raw: bytes) -> PricingTable:
        if len(raw) > _MAX_TABLE_BYTES:
            raise PricingTableError("pricing table exceeds 1 MiB", "file")
        try:
            text = raw.decode("utf-8")
            data = json.loads(
                text,
                parse_float=Decimal,
                parse_int=Decimal,
                parse_constant=_reject_constant,
            )
        except (ValueError, RecursionError) as exc:
            raise PricingTableError("pricing table is not valid UTF-8 JSON") from exc
        table = cls.from_json(data)
        logger.debug("loaded pricing table version=%s models=%d", table.version, len(table.models))
        return table

    def get(self, provider: str, model: str) -> ModelPrice:
        """Return the price row for ``provider``/``model``.

        Raises:
            UnknownModelError: if the pair is absent; ``suggestions`` lists close model names.
        """
        price = self._index.get((provider, model))
        if price is None:
            raise UnknownModelError(provider, model, self._suggest(provider, model))
        return price

    def _suggest(self, provider: str, model: str) -> tuple[str, ...]:
        names = sorted({name for prov, name in self._index if prov == provider})
        if not names:
            names = sorted({name for _, name in self._index})
        return tuple(difflib.get_close_matches(clip_input(model, 128), names, n=3, cutoff=0.6))


@lru_cache(maxsize=1)
def _bundled() -> PricingTable:
    resource = files("token_cost_estimator").joinpath("data").joinpath("pricing.json")
    return PricingTable._from_bytes(resource.read_bytes())


def _reject_constant(name: str) -> Decimal:
    raise ValueError(f"non-finite constant {name}")


def _require(mapping: Mapping[str, Any], key: str, prefix: str) -> Any:
    if key not in mapping:
        raise PricingTableError("missing required field", f"{prefix}{key}")
    return mapping[key]


def _text(value: object, field_name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise PricingTableError(f"must be a non-empty string of at most {limit} characters", field_name)
    return value


def _name(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise PricingTableError("must match [a-z0-9][a-z0-9._-]{0,63}", field_name)
    return value


def _parse_date(value: object) -> date:
    if isinstance(value, str) and _DATE_RE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise PricingTableError("must be an ISO date (YYYY-MM-DD)", "as_of")


def _decimal(value: object, field_name: str) -> Decimal:
    result: Decimal
    if isinstance(value, bool):
        raise PricingTableError("must be a decimal number", field_name)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str) and len(value) <= _MAX_NUMBER_TEXT:
        try:
            result = Decimal(value)
        except InvalidOperation:
            raise PricingTableError("must be a decimal number", field_name) from None
    else:
        raise PricingTableError("must be a decimal number, integer or string", field_name)
    if not result.is_finite() or result < 0 or result > _MAX_PRICE:
        raise PricingTableError("must be finite and between 0 and 1000000000", field_name)
    return result


def _optional_decimal(item: Mapping[str, Any], key: str, prefix: str) -> Decimal | None:
    value = item.get(key)
    if value is None:
        return None
    return _decimal(value, f"{prefix}{key}")


def _integer(value: object, field_name: str, minimum: int, maximum: int) -> int:
    result: int
    if isinstance(value, bool):
        raise PricingTableError("must be an integer", field_name)
    if isinstance(value, int):
        result = value
    elif (
        isinstance(value, Decimal)
        and value.is_finite()
        and value.copy_abs() <= _MAX_WINDOW
        and value == value.to_integral_value()
    ):
        result = int(value)
    else:
        raise PricingTableError("must be an integer", field_name)
    if not minimum <= result <= maximum:
        raise PricingTableError(f"must be between {minimum} and {maximum}", field_name)
    return result


def _parse_model(item: object, position: int) -> ModelPrice:
    if not isinstance(item, Mapping):
        raise PricingTableError("must be an object", f"models[{position}]")
    prefix = f"models[{position}]."
    return ModelPrice(
        provider=_name(_require(item, "provider", prefix), f"{prefix}provider"),
        model=_name(_require(item, "model", prefix), f"{prefix}model"),
        input_per_mtok=_decimal(_require(item, "input_per_mtok", prefix), f"{prefix}input_per_mtok"),
        output_per_mtok=_decimal(
            _require(item, "output_per_mtok", prefix), f"{prefix}output_per_mtok"
        ),
        cached_input_per_mtok=_optional_decimal(item, "cached_input_per_mtok", prefix),
        cache_write_per_mtok=_optional_decimal(item, "cache_write_per_mtok", prefix),
        context_window=_integer(
            _require(item, "context_window", prefix),
            f"{prefix}context_window",
            1,
            _MAX_WINDOW,
        ),
        source=_text(_require(item, "source", prefix), f"{prefix}source", _MAX_TEXT),
    )

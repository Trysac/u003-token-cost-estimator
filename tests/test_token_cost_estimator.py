"""Tests for the public library API of token_cost_estimator."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import fields
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from token_cost_estimator import (
    Estimate,
    EstimatorError,
    HeuristicTokenizer,
    InputTooLargeError,
    ModelPrice,
    PricingTable,
    PricingTableError,
    UnknownModelError,
    __version__,
    estimate,
)


def _model_json(
    name: str,
    inp: str,
    out: str,
    cached: str | None = None,
    write: str | None = None,
    window: int = 200000,
) -> str:
    parts = [
        f'"provider":"fx","model":"{name}"',
        f'"input_per_mtok":{inp},"output_per_mtok":{out}',
    ]
    if cached is not None:
        parts.append(f'"cached_input_per_mtok":{cached}')
    if write is not None:
        parts.append(f'"cache_write_per_mtok":{write}')
    parts.append(f'"context_window":{window},"source":"https://example.com/pricing"')
    return "{" + ",".join(parts) + "}"


_MODELS = [
    _model_json("m1", "3.00", "15.00", cached="0.30"),
    _model_json("gpt-4o-mini", "0.15", "0.60"),
    _model_json("full", "3", "15", cached="0.30", write="3.75"),
]
TABLE_TEXT = (
    '{"schema":1,"version":"t1","as_of":"2026-01-02","currency":"USD","models":['
    + ",".join(_MODELS)
    + "]}"
)


def table_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(TABLE_TEXT, parse_float=Decimal, parse_int=Decimal)
    return data


T = PricingTable.from_json(table_data())


class FixedTokenizer:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens
        self.calls: list[str] = []

    def count(self, text: str) -> int:
        self.calls.append(text)
        return self.tokens


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_acceptance_example() -> None:
    result = estimate(
        "a" * 4000,
        provider="fx",
        model="m1",
        table=T,
        expected_output_tokens=500,
        cached_input_tokens=200,
    )
    assert result.input_tokens == 1000
    assert result.output_tokens == 500
    assert result.input_cost == Decimal("0.002400")
    assert result.cached_cost == Decimal("0.000060")
    assert result.output_cost == Decimal("0.007500")
    assert result.cache_write_cost == Decimal("0.000000")
    assert result.total == Decimal("0.009960")
    assert result.currency == "USD"
    assert result.table_version == "t1"
    assert result.as_of == date(2026, 1, 2)
    assert result.exceeds_context is False


def test_cache_write_pricing_and_total_is_sum_of_components() -> None:
    result = estimate(
        "a" * 4000,
        provider="fx",
        model="full",
        table=T,
        expected_output_tokens=500,
        cached_input_tokens=100,
        cache_write_tokens=200,
    )
    assert result.input_cost == Decimal("0.002100")
    assert result.cached_cost == Decimal("0.000030")
    assert result.cache_write_cost == Decimal("0.000750")
    assert result.output_cost == Decimal("0.007500")
    parts = result.input_cost + result.cached_cost + result.cache_write_cost + result.output_cost
    assert result.total == parts == Decimal("0.010380")


def test_heuristic_tokenizer() -> None:
    assert HeuristicTokenizer().count("abcdefghi") == 3
    assert HeuristicTokenizer().count("") == 0
    assert HeuristicTokenizer(chars_per_token=1).count("abc") == 3
    assert HeuristicTokenizer().count(chr(0x1F600) * 8) == 2


@pytest.mark.parametrize("bad", [0, -1, True, "4", 2.5])
def test_heuristic_rejects_bad_chars_per_token(bad: Any) -> None:
    with pytest.raises(EstimatorError) as info:
        HeuristicTokenizer(chars_per_token=bad)
    assert info.value.code == "invalid_argument"


def test_custom_tokenizer_is_the_only_one_called(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: HeuristicTokenizer, text: str) -> int:
        raise AssertionError("default tokenizer must not be used")

    monkeypatch.setattr(HeuristicTokenizer, "count", boom)
    custom = FixedTokenizer(7)
    result = estimate("hello", provider="fx", model="m1", table=T, tokenizer=custom)
    assert result.input_tokens == 7
    assert custom.calls == ["hello"]


def test_multiple_messages_are_counted_and_summed() -> None:
    result = estimate(["abcd", "efghi"], provider="fx", model="m1", table=T)
    assert result.input_tokens == 3
    custom = FixedTokenizer(2)
    estimate(["a", "b"], provider="fx", model="m1", table=T, tokenizer=custom)
    assert custom.calls == ["a", "b"]


def _one_token_cost(price: str) -> Estimate:
    data = table_data()
    raw = _model_json("r", price, price)
    data["models"] = [json.loads(raw, parse_float=Decimal, parse_int=Decimal)]
    table = PricingTable.from_json(data)
    return estimate("x", provider="fx", model="r", table=table, tokenizer=FixedTokenizer(1))


def test_rounding_is_half_even_per_component() -> None:
    low = _one_token_cost("0.5")
    assert low.input_cost == Decimal("0.000000")
    assert str(low.input_cost) == "0.000000"
    assert _one_token_cost("1.5").input_cost == Decimal("0.000002")
    assert _one_token_cost("2.5").input_cost == Decimal("0.000002")
    assert _one_token_cost("3.5").input_cost == Decimal("0.000004")


def test_no_cost_field_is_float() -> None:
    result = estimate("a" * 40, provider="fx", model="m1", table=T, expected_output_tokens=3)
    for item in fields(Estimate):
        assert not isinstance(getattr(result, item.name), float)
    for name in ("input_cost", "cached_cost", "cache_write_cost", "output_cost", "total"):
        assert isinstance(getattr(result, name), Decimal)


def test_json_number_loads_as_exact_decimal(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    text = TABLE_TEXT.replace('"input_per_mtok":3.00', '"input_per_mtok":0.1')
    path.write_text(text, encoding="utf-8")
    price = PricingTable.load(path).get("fx", "m1")
    assert isinstance(price.input_per_mtok, Decimal)
    assert price.input_per_mtok == Decimal("0.1")
    assert isinstance(price.context_window, int)


def test_unknown_model_suggestions() -> None:
    data = table_data()
    data["models"] = [json.loads(_model_json("gpt-4o-mini", "1", "2"), parse_int=Decimal)]
    table = PricingTable.from_json(data)
    with pytest.raises(UnknownModelError) as info:
        table.get("fx", "gpt-4o-mnii")
    err = info.value
    assert err.code == "unknown_model"
    assert "gpt-4o-mini" in err.suggestions
    assert isinstance(err, EstimatorError)
    assert isinstance(err, ValueError)


def test_unknown_provider_suggests_from_all_models_and_may_be_empty() -> None:
    with pytest.raises(UnknownModelError) as info:
        T.get("zz", "gpt-4o-mnii")
    assert info.value.suggestions == ("gpt-4o-mini",)
    with pytest.raises(UnknownModelError) as other:
        T.get("fx", "qqqqqqqq")
    assert other.value.suggestions == ()


def test_unknown_model_message_is_bounded() -> None:
    huge = "x" * 10000
    with pytest.raises(UnknownModelError) as info:
        T.get(huge, huge)
    assert len(str(info.value)) <= 200
    assert huge not in str(info.value)


_DROP = object()
Mutator = Callable[[dict[str, Any]], None]


def _top(key: str, value: object = _DROP) -> Mutator:
    def mutate(data: dict[str, Any]) -> None:
        if value is _DROP:
            del data[key]
        else:
            data[key] = value

    return mutate


def _model_field(key: str, value: object = _DROP) -> Mutator:
    def mutate(data: dict[str, Any]) -> None:
        if value is _DROP:
            del data["models"][0][key]
        else:
            data["models"][0][key] = value

    return mutate


def _duplicate(data: dict[str, Any]) -> None:
    data["models"].append(data["models"][0])


BAD_TABLES: list[tuple[str, Mutator, str]] = [
    ("missing as_of", _top("as_of"), "as_of"),
    ("bad as_of month", _top("as_of", "2026-13-01"), "as_of"),
    ("compact as_of", _top("as_of", "20261105"), "as_of"),
    ("numeric as_of", _top("as_of", 5), "as_of"),
    ("missing schema", _top("schema"), "schema"),
    ("schema 2", _top("schema", Decimal(2)), "schema"),
    ("bool schema", _top("schema", True), "schema"),
    ("empty version", _top("version", ""), "version"),
    ("lower currency", _top("currency", "usd"), "currency"),
    ("models not list", _top("models", "x"), "models"),
    ("too many models", _top("models", [table_data()["models"][0]] * 2001), "models"),
    ("model not object", _top("models", ["x"]), "models[0]"),
    ("bad provider", _model_field("provider", "Bad"), "models[0].provider"),
    ("newline model", _model_field("model", "bad" + chr(10)), "models[0].model"),
    ("negative input", _model_field("input_per_mtok", Decimal("-1")), "models[0].input_per_mtok"),
    ("float input", _model_field("input_per_mtok", 0.1), "models[0].input_per_mtok"),
    ("text input", _model_field("input_per_mtok", "abc"), "models[0].input_per_mtok"),
    ("nan input", _model_field("input_per_mtok", Decimal("NaN")), "models[0].input_per_mtok"),
    ("huge input", _model_field("input_per_mtok", Decimal("1E+10")), "models[0].input_per_mtok"),
    ("bool input", _model_field("input_per_mtok", True), "models[0].input_per_mtok"),
    ("missing output", _model_field("output_per_mtok"), "models[0].output_per_mtok"),
    (
        "negative cached",
        _model_field("cached_input_per_mtok", Decimal("-0.1")),
        "models[0].cached_input_per_mtok",
    ),
    (
        "negative write",
        _model_field("cache_write_per_mtok", Decimal("-0.1")),
        "models[0].cache_write_per_mtok",
    ),
    ("zero window", _model_field("context_window", Decimal(0)), "models[0].context_window"),
    ("float window", _model_field("context_window", Decimal("1.5")), "models[0].context_window"),
    ("bool window", _model_field("context_window", True), "models[0].context_window"),
    ("huge window", _model_field("context_window", Decimal("1E+99")), "models[0].context_window"),
    ("empty source", _model_field("source", ""), "models[0].source"),
    ("duplicate model", _duplicate, "models[3].model"),
]


@pytest.mark.parametrize(("label", "mutate", "field"), BAD_TABLES, ids=[c[0] for c in BAD_TABLES])
def test_bad_tables_name_the_field(label: str, mutate: Mutator, field: str) -> None:
    data = table_data()
    mutate(data)
    with pytest.raises(PricingTableError) as info:
        PricingTable.from_json(data)
    assert info.value.code == "pricing_table"
    assert info.value.field == field
    assert len(str(info.value)) <= 200


def test_non_mapping_table_is_rejected() -> None:
    with pytest.raises(PricingTableError) as info:
        PricingTable.from_json([])  # type: ignore[arg-type]
    assert info.value.code == "pricing_table"
    assert info.value.field is None


def test_direct_construction_rejects_duplicates() -> None:
    price = T.get("fx", "m1")
    with pytest.raises(PricingTableError) as info:
        PricingTable(version="v", as_of=date(2026, 1, 1), currency="USD", models=(price, price))
    assert info.value.field == "models"


def test_price_formats_accepted() -> None:
    data = table_data()
    data["models"][0]["input_per_mtok"] = "3.5"
    data["models"][0]["output_per_mtok"] = 15
    data["models"][0]["cached_input_per_mtok"] = None
    data["models"][0]["context_window"] = 1000
    price = PricingTable.from_json(data).get("fx", "m1")
    assert isinstance(price, ModelPrice)
    assert price.input_per_mtok == Decimal("3.5")
    assert price.output_per_mtok == Decimal(15)
    assert price.cached_input_per_mtok is None
    assert price.context_window == 1000


def test_load_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "big.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(PricingTableError) as info:
        PricingTable.load(path)
    assert info.value.code == "pricing_table"


def test_load_accepts_file_of_exactly_one_mebibyte(tmp_path: Path) -> None:
    raw = TABLE_TEXT.encode()
    path = tmp_path / "edge.json"
    path.write_bytes(raw + b" " * (1024 * 1024 - len(raw)))
    assert PricingTable.load(path).version == "t1"


def test_load_reports_unreadable_and_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(PricingTableError):
        PricingTable.load(tmp_path / "missing.json")
    cases = {
        "garbage.json": b"{not json",
        "nan.json": b'{"schema": NaN}',
        "latin.json": b"\xff\xfe",
        "deep.json": b"[" * 200000,
    }
    for name, content in cases.items():
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(PricingTableError) as info:
            PricingTable.load(path)
        assert info.value.code == "pricing_table"


def test_bundled_table() -> None:
    table = PricingTable.bundled()
    assert {m.model for m in table.models} == {"claude-sonnet-4-5", "claude-haiku-4-5"}
    assert table.as_of == date(2026, 11, 5)
    assert table.version == "2026-11-05"
    assert table.currency == "USD"
    assert all(m.source.startswith("https://") for m in table.models)
    assert PricingTable.bundled() is table


def test_input_too_large() -> None:
    with pytest.raises(InputTooLargeError) as info:
        estimate("a" * 5, provider="fx", model="m1", table=T, max_chars=4)
    assert info.value.code == "input_too_large"
    assert estimate("a" * 4, provider="fx", model="m1", table=T, max_chars=4).input_tokens == 1
    with pytest.raises(InputTooLargeError):
        estimate(["aaa", "aaa"], provider="fx", model="m1", table=T, max_chars=5)
    with pytest.raises(InputTooLargeError):
        estimate("a" * 2_000_001, provider="fx", model="m1", table=T)
    with pytest.raises(InputTooLargeError):
        estimate([""] * 100_001, provider="fx", model="m1", table=T)


def test_cached_tokens_above_input_are_rejected() -> None:
    with pytest.raises(EstimatorError) as info:
        estimate("a" * 4000, provider="fx", model="m1", table=T, cached_input_tokens=1001)
    assert info.value.code == "invalid_argument"
    with pytest.raises(EstimatorError) as other:
        estimate(
            "a" * 4000,
            provider="fx",
            model="full",
            table=T,
            cached_input_tokens=600,
            cache_write_tokens=401,
        )
    assert other.value.code == "invalid_argument"


def test_missing_rates_are_rejected_when_tokens_are_used() -> None:
    with pytest.raises(EstimatorError) as info:
        estimate("a" * 40, provider="fx", model="gpt-4o-mini", table=T, cached_input_tokens=1)
    assert info.value.code == "invalid_argument"
    with pytest.raises(EstimatorError) as other:
        estimate("a" * 40, provider="fx", model="m1", table=T, cache_write_tokens=1)
    assert other.value.code == "invalid_argument"
    ok = estimate("a" * 40, provider="fx", model="gpt-4o-mini", table=T)
    assert ok.cached_cost == Decimal("0.000000")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_output_tokens": -1},
        {"cached_input_tokens": True},
        {"cache_write_tokens": 1.5},
        {"max_chars": -1},
        {"expected_output_tokens": 10**13},
    ],
)
def test_invalid_numeric_arguments(kwargs: dict[str, Any]) -> None:
    with pytest.raises(EstimatorError) as info:
        estimate("abcd", provider="fx", model="m1", table=T, **kwargs)
    assert info.value.code == "invalid_argument"


@pytest.mark.parametrize("messages", [b"abcd", ["a", 1], 5])
def test_invalid_messages(messages: Any) -> None:
    with pytest.raises(EstimatorError) as info:
        estimate(messages, provider="fx", model="m1", table=T)
    assert info.value.code == "invalid_argument"


@pytest.mark.parametrize("bad", [-1, True, "3", 10**13])
def test_invalid_tokenizer_counts(bad: Any) -> None:
    with pytest.raises(EstimatorError) as info:
        estimate("abcd", provider="fx", model="m1", table=T, tokenizer=FixedTokenizer(bad))
    assert info.value.code == "invalid_argument"


def test_exceeds_context() -> None:
    over = estimate(
        "a",
        provider="fx",
        model="m1",
        table=T,
        expected_output_tokens=1,
        tokenizer=FixedTokenizer(200000),
    )
    assert over.exceeds_context is True
    exact = estimate(
        "a",
        provider="fx",
        model="m1",
        table=T,
        expected_output_tokens=1,
        tokenizer=FixedTokenizer(199999),
    )
    assert exact.exceeds_context is False


def test_logging_never_contains_input_text(caplog: pytest.LogCaptureFixture) -> None:
    secret = "SUPER-SECRET-PROMPT"  # noqa: S105
    with caplog.at_level(logging.DEBUG, logger="token_cost_estimator"):
        estimate(secret, provider="fx", model="m1", table=T)
    assert caplog.records
    assert secret not in caplog.text

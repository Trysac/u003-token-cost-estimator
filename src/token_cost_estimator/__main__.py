"""Command line interface: ``token-cost-estimator estimate|models``.

Exit codes: 0 success, 1 the estimate exceeds ``--max-cost``, 2 usage, IO or parse errors.
Prices change: verify the bundled table or override it with ``--table``.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import EstimatorError, clip_input
from .estimator import DEFAULT_MAX_CHARS, Estimate, estimate
from .pricing import ModelPrice, PricingTable

__all__ = ["main"]


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return value


def _cost_limit(raw: str) -> Decimal:
    try:
        value = Decimal(raw) if len(raw) <= 64 else Decimal("NaN")
    except InvalidOperation:
        raise argparse.ArgumentTypeError("must be a non-negative decimal") from None
    if not value.is_finite() or value < 0:
        raise argparse.ArgumentTypeError("must be a non-negative decimal")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token-cost-estimator",
        description="Estimate tokens and cost of an LLM request from a dated pricing table.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    est = commands.add_parser("estimate", help="estimate tokens and cost of a request")
    est.add_argument("--provider", required=True)
    est.add_argument("--model", required=True)
    source = est.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="read the request text from this UTF-8 file")
    source.add_argument("--text", help="the request text")
    est.add_argument("--output-tokens", type=_non_negative_int, default=0)
    est.add_argument("--cached-tokens", type=_non_negative_int, default=0)
    est.add_argument("--cache-write-tokens", type=_non_negative_int, default=0)
    est.add_argument("--table", help="pricing table JSON overriding the bundled table")
    est.add_argument("--max-cost", type=_cost_limit, default=None, help="fail above this cost")
    listing = commands.add_parser("models", help="list the priced models")
    listing.add_argument("--table", help="pricing table JSON overriding the bundled table")
    return parser


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _optional(value: Decimal | None) -> str | None:
    return None if value is None else _fmt(value)


def _load_table(path: str | None) -> PricingTable:
    if path is None:
        return PricingTable.bundled()
    return PricingTable.load(Path(path))


def _read_input(args: argparse.Namespace) -> str:
    if args.text is not None:
        return str(args.text)
    with Path(args.file).open(encoding="utf-8") as handle:
        return handle.read(DEFAULT_MAX_CHARS + 1)


def _estimate_payload(provider: str, model: str, result: Estimate) -> dict[str, object]:
    return {
        "as_of": result.as_of.isoformat(),
        "cache_write_cost": _fmt(result.cache_write_cost),
        "cached_cost": _fmt(result.cached_cost),
        "currency": result.currency,
        "exceeds_context": result.exceeds_context,
        "input_cost": _fmt(result.input_cost),
        "input_tokens": result.input_tokens,
        "model": model,
        "output_cost": _fmt(result.output_cost),
        "output_tokens": result.output_tokens,
        "provider": provider,
        "table_version": result.table_version,
        "total": _fmt(result.total),
    }


def _model_payload(price: ModelPrice) -> dict[str, object]:
    return {
        "cache_write_per_mtok": _optional(price.cache_write_per_mtok),
        "cached_input_per_mtok": _optional(price.cached_input_per_mtok),
        "context_window": price.context_window,
        "input_per_mtok": _fmt(price.input_per_mtok),
        "model": price.model,
        "output_per_mtok": _fmt(price.output_per_mtok),
        "provider": price.provider,
        "source": price.source,
    }


def _cmd_estimate(args: argparse.Namespace) -> int:
    table = _load_table(args.table)
    text = _read_input(args)
    result = estimate(
        text,
        provider=args.provider,
        model=args.model,
        table=table,
        expected_output_tokens=args.output_tokens,
        cached_input_tokens=args.cached_tokens,
        cache_write_tokens=args.cache_write_tokens,
    )
    print(json.dumps(_estimate_payload(args.provider, args.model, result), sort_keys=True))
    if args.max_cost is not None and result.total > args.max_cost:
        return 1
    return 0


def _cmd_models(args: argparse.Namespace) -> int:
    table = _load_table(args.table)
    payload: dict[str, object] = {
        "as_of": table.as_of.isoformat(),
        "currency": table.currency,
        "models": [_model_payload(price) for price in table.models],
        "version": table.version,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code (0 ok, 1 over budget, 2 error)."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        if args.command == "models":
            return _cmd_models(args)
        return _cmd_estimate(args)
    except EstimatorError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
    except UnicodeDecodeError:
        print("error: io: input file is not valid UTF-8", file=sys.stderr)
    except OSError as exc:
        reason = clip_input(exc.strerror or type(exc).__name__, 80)
        print(f"error: io: cannot read input file: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

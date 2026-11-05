# Pricing tables

`token-cost-estimator` prices requests from a dated, versioned table. **Prices change often.**
The bundled table (`src/token_cost_estimator/data/pricing.json`, version `2026-11-05`, currency
`USD`) holds two Anthropic rows whose `source` is
<https://platform.claude.com/docs/en/about-claude/pricing> (checked 2026-11-05; the cache-write
rate is the 5-minute rate). Verify the prices against that source, or override the table with
`PricingTable.load(path)` or the CLI option `--table PATH`.

## Table format

```json
{
  "schema": 1,
  "version": "my-table-1",
  "as_of": "2026-01-02",
  "currency": "USD",
  "models": [
    {
      "provider": "acme",
      "model": "small-1",
      "input_per_mtok": 3.00,
      "output_per_mtok": 15.00,
      "cached_input_per_mtok": 0.30,
      "cache_write_per_mtok": 3.75,
      "context_window": 200000,
      "source": "https://example.com/pricing"
    }
  ]
}
```

Prices are read with `parse_float=Decimal`, so they never pass through `float`. A table is at most
1 MiB and 2000 models; `provider` and `model` match `^[a-z0-9][a-z0-9._-]{0,63}$`.

## How a cost is computed

Uncached input is `input_tokens - cached_input_tokens - cache_write_tokens`. Each token class is
priced per million tokens, each component is quantized to six places with `ROUND_HALF_EVEN` and
the total is the sum of the rounded components. Every `Estimate` carries the table `version`,
`as_of` date and `currency`.

## Not modeled

Long-context tiers, batch discounts, image or audio tokens and per-message overhead. The default
`HeuristicTokenizer` is `ceil(code points / chars_per_token)`, an approximation that undercounts
CJK text and code; pass a real tokenizer to `estimate` when accuracy matters.

## Errors

All errors derive from `EstimatorError` (a `ValueError`) and carry a stable `code`:
`unknown_model`, `pricing_table`, `input_too_large`, `invalid_argument`.

## CLI

```text
token-cost-estimator estimate --provider P --model M (--file PATH | --text T)
    [--output-tokens N] [--cached-tokens N] [--cache-write-tokens N]
    [--table PATH] [--max-cost USD]
token-cost-estimator models [--table PATH]
```

Exit codes: `0` ok, `1` the estimate exceeds `--max-cost` (the JSON is still printed), `2` usage,
IO or parse errors.

# Project record

## Objective

Estimate tokens and cost of an LLM request before sending it, from a dated, overridable pricing table with cached-input and cache-write rates, Decimal only

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 381861 / 71404 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.5459 |

## Factory run u003 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2744 | 58604 | 0 | 4246 | 0.2962 |
| fix-1 | claude-sonnet-5-5 | no | 10 | 2035 | 9630 | 79995 | 0.0524 |
| fix-2 | claude-sonnet-5-5 | no | 6 | 1377 | 8018 | 41302 | 0.0380 |
| fix-3 | claude-sonnet-5-5 | no | 12 | 1949 | 11542 | 99073 | 0.0583 |
| fix-4 | claude-sonnet-5-5 | no | 6 | 633 | 6631 | 40340 | 0.0270 |
| docs | claude-haiku-5-5 | no | 114127 | 6806 | 0 | 0 | 0.0741 |

Total: $0.5459. Prices: Anthropic list prices.

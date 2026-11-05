# Decimal-only pricing from a dated, dependency-free table

Status: accepted (generated, pending human review)

## Context

Teams learn what a prompt costs only from the invoice. Existing estimators such as tokencost need tiktoken and ship an undated table, so a user cannot tell how stale a price is. Prices differ per provider, model and token class (input, cached input, cache write, output), and float arithmetic would make totals irreproducible.

## Decision

Prices live in a versioned JSON table parsed with parse_float=Decimal and parse_int=Decimal, so no price ever becomes a float. Each estimate is stamped with the table version, as_of date and currency. Each token class is priced per million tokens, quantized to six places with ROUND_HALF_EVEN, and the total is the sum of the rounded components. Tokenization is a pluggable Protocol with a standard-library heuristic default (ceil of code points over chars per token), so the library has no runtime dependencies. Inputs are bounded: 1 MiB and 2000 models per table, 2,000,000 characters per text, bounded message count, and JSON depth failures are mapped to a typed error.

## Consequences

Estimates are reproducible and auditable, and callers can override the table without code changes. The default tokenizer is only an approximation and undercounts CJK text and code, so callers needing accuracy must inject a real tokenizer. Prices go stale: the bundled table is dated and must be verified or overridden. Long-context tiers, batch discounts, image or audio tokens and per-message overhead are not modeled.

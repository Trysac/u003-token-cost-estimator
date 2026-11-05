# token-cost-estimator

[![PyPI version](https://img.shields.io/pypi/v/trysac-token-cost-estimator)](https://pypi.org/project/trysac-token-cost-estimator/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-token-cost-estimator)](LICENSE)
[![CI](https://github.com/Trysac/u003-token-cost-estimator/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u003-token-cost-estimator/actions/workflows/ci.yml)

Estimate tokens and cost of an LLM request before sending it, from a dated, overridable pricing table with cached-input and cache-write rates, Decimal only

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-token-cost-estimator
# or
uv add trysac-token-cost-estimator
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import token_cost_estimator

# normalize() trims surrounding whitespace and lower-cases the text.
print(token_cost_estimator.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    token_cost_estimator.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez

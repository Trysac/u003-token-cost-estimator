"""Estimate tokens and cost of an LLM request from a dated, overridable pricing table.

Prices are Decimal values read from a versioned pricing table and every estimate is stamped
with the table version and date. Prices change often: verify the bundled table against the
``source`` URL of each row, or override it with ``PricingTable.load`` or the CLI ``--table``
option.

Not modeled: long-context pricing tiers, batch discounts, image or audio tokens and
per-message overhead. The default tokenizer is a heuristic approximation that undercounts CJK
text and code.
"""

from __future__ import annotations

from .errors import EstimatorError, InputTooLargeError, PricingTableError, UnknownModelError
from .estimator import Estimate, HeuristicTokenizer, Tokenizer, estimate
from .pricing import ModelPrice, PricingTable

__all__ = [
    "Estimate",
    "EstimatorError",
    "HeuristicTokenizer",
    "InputTooLargeError",
    "ModelPrice",
    "PricingTable",
    "PricingTableError",
    "Tokenizer",
    "UnknownModelError",
    "__version__",
    "estimate",
]

__version__ = "0.1.0"

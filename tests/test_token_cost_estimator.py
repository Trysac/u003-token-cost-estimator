"""Behavior tests for the public API of token_cost_estimator."""

from __future__ import annotations

import pytest

import token_cost_estimator


def test_normalize_trims_and_lowercases() -> None:
    assert token_cost_estimator.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        token_cost_estimator.normalize(value)


def test_version_is_semver() -> None:
    parts = token_cost_estimator.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)

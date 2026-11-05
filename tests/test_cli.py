"""Tests for the command line interface."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from token_cost_estimator.__main__ import main

TABLE_TEXT = (
    '{"schema":1,"version":"t1","as_of":"2026-01-02","currency":"USD","models":['
    '{"provider":"fx","model":"m1","input_per_mtok":3.00,"output_per_mtok":15.00,'
    '"cached_input_per_mtok":0.30,"context_window":200000,'
    '"source":"https://example.com/pricing"}'
    "]}"
)


def _write_table(tmp_path: Path) -> str:
    path = tmp_path / "table.json"
    path.write_text(TABLE_TEXT, encoding="utf-8")
    return str(path)


def _estimate_args(path: str, *extra: str) -> list[str]:
    base = ["estimate", "--provider", "fx", "--model", "m1", "--text", "abcd", "--table", path]
    return [*base, *extra]


def test_estimate_prints_sorted_json_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_table(tmp_path)
    code = main(
        ["estimate", "--provider", "fx", "--model", "m1", "--text", "abcd", "--table", path]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert '"total": "0.000003"' in out
    assert len(out.strip().splitlines()) == 1
    payload = json.loads(out)
    assert list(payload) == sorted(payload)
    assert payload["table_version"] == "t1"
    assert payload["as_of"] == "2026-01-02"
    assert payload["exceeds_context"] is False


def test_max_cost_exceeded_returns_one_and_still_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adding ['--max-cost', '0'] returns 1 and still prints, and '--model', 'nope' is separate."""
    path = _write_table(tmp_path)
    assert main(_estimate_args(path, "--max-cost", "0")) == 1
    assert '"total": "0.000003"' in capsys.readouterr().out
    assert main(_estimate_args(path, "--max-cost", "1")) == 0
    assert main(_estimate_args(path, "--max-cost", "0.000003")) == 0


def test_unknown_model_returns_two_with_message_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_table(tmp_path)
    code = main(
        ["estimate", "--provider", "fx", "--model", "nope", "--text", "abcd", "--table", path]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "nope" in captured.err
    assert "unknown_model" in captured.err


def test_token_options_and_file_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_table(tmp_path)
    source = tmp_path / "prompt.txt"
    source.write_text("a" * 4000, encoding="utf-8")
    code = main(
        [
            *["estimate", "--provider", "fx", "--model", "m1"],
            *["--file", str(source), "--table", path],
            *["--output-tokens", "500", "--cached-tokens", "200"],
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["total"] == "0.009960"


def test_cached_tokens_error_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_table(tmp_path)
    assert main(_estimate_args(path, "--cached-tokens", "5")) == 2
    assert "invalid_argument" in capsys.readouterr().err


def test_io_and_parse_errors_return_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_table(tmp_path)
    missing = str(tmp_path / "missing.txt")
    base = ["estimate", "--provider", "fx", "--model", "m1", "--table", path]
    assert main([*base, "--file", missing]) == 2
    assert "io" in capsys.readouterr().err
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"\xff\xfe\xfa")
    assert main([*base, "--file", str(binary)]) == 2
    assert "UTF-8" in capsys.readouterr().err
    huge = tmp_path / "huge.txt"
    huge.write_text("a" * 2_000_001, encoding="utf-8")
    assert main([*base, "--file", str(huge)]) == 2
    assert "input_too_large" in capsys.readouterr().err
    assert main(_estimate_args(str(tmp_path / "no-table.json"))) == 2
    assert "pricing_table" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert main(_estimate_args(str(bad))) == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--max-cost", "abc"],
        ["--max-cost", "-1"],
        ["--max-cost", "NaN"],
        ["--max-cost", "1" * 100],
        ["--output-tokens", "-1"],
        ["--output-tokens", "x"],
        ["--file", "also-a-file.txt"],
    ],
)
def test_usage_errors_return_two(tmp_path: Path, extra: list[str]) -> None:
    path = _write_table(tmp_path)
    assert main(_estimate_args(path, *extra)) == 2


def test_missing_command_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert main(["--help"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_models_command_lists_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_table(tmp_path)
    assert main(["models", "--table", path]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == "t1"
    assert payload["currency"] == "USD"
    [row] = payload["models"]
    assert row["model"] == "m1"
    assert row["input_per_mtok"] == "3.00"
    assert row["cache_write_per_mtok"] is None
    assert row["cached_input_per_mtok"] == "0.30"


def test_models_command_uses_bundled_table_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["models"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {row["model"] for row in payload["models"]} == {
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    }


def test_main_reads_sys_argv_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "models", "--table", _write_table(tmp_path)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["version"] == "t1"


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_module_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["token-cost-estimator", "models", "--table", _write_table(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as info:
        runpy.run_module("token_cost_estimator.__main__", run_name="__main__")
    assert info.value.code == 0
    assert "t1" in capsys.readouterr().out

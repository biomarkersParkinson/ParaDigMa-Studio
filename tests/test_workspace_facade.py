"""The compatibility guard rejects regrowth and requires budgets to shrink too."""

import json

import pytest

from scripts.check_workspace_facade import main


def budget(tmp_path, source, aliases, *, limit=None):
    facade, baseline = tmp_path / "compatibility.py", tmp_path / "budget.json"
    facade.write_text(source, encoding="utf-8")
    baseline.write_text(
        json.dumps(
            {"max_lines": len(source.splitlines()) if limit is None else limit, "aliases": aliases}
        ),
        encoding="utf-8",
    )
    return facade, baseline


def test_current_workspace_facade_matches_its_budget():
    assert main() == 0


def test_facade_guard_accepts_exact_budget_and_an_unterminated_final_line(tmp_path):
    paths = budget(tmp_path, "# Comment\n\n_PORTS = {'runs': object()}", ["runs"])
    assert main(*paths) == 0


def test_facade_guard_rejects_alias_replacement_even_without_line_growth(tmp_path, capsys):
    paths = budget(tmp_path, "_PORTS = {'runs': object()}\n", ["frame"])
    assert main(*paths) == 1
    assert "New or retired aliases are forbidden: runs" in capsys.readouterr().err


def test_facade_guard_rejects_comment_only_growth(tmp_path, capsys):
    paths = budget(tmp_path, "# Extra line\n_PORTS = {'runs': object()}\n", ["runs"], limit=1)
    assert main(*paths) == 1
    assert "grew to 2 lines (maximum 1)" in capsys.readouterr().err


def test_retirement_requires_lowering_both_name_and_line_budgets(tmp_path, capsys):
    source = "_PORTS = {'runs': object()}\n"
    facade, baseline = budget(tmp_path, source, ["frame", "runs"], limit=2)
    assert main(facade, baseline) == 1
    errors = capsys.readouterr().err
    assert "Remove retired aliases from the budget: frame" in errors
    assert "Lower the compatibility line budget from 2 to 1" in errors
    budget(tmp_path, source, ["runs"])
    assert main(facade, baseline) == 0


def test_facade_can_be_removed_after_its_budget_reaches_zero(tmp_path):
    facade, baseline = budget(tmp_path, "", [])
    facade.unlink()
    assert main(facade, baseline) == 0


@pytest.mark.parametrize(
    "source", ["_PORTS = dict(runs=1)", "_PORTS = {**other}", "_PORTS = {'runs': 1, 'runs': 2}"]
)
def test_facade_guard_rejects_implicit_or_duplicate_aliases(tmp_path, capsys, source):
    paths = budget(tmp_path, source, ["runs"])
    assert main(*paths) == 1
    assert "Invalid workspace facade" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value",
    [
        "not json",
        '{"max_lines": true, "aliases": []}',
        '{"max_lines": 0, "aliases": ["runs", "runs"]}',
    ],
)
def test_facade_guard_reports_invalid_budget(tmp_path, capsys, value):
    facade, baseline = budget(tmp_path, "_PORTS = {}\n", [])
    baseline.write_text(value, encoding="utf-8")
    assert main(facade, baseline) == 1
    assert "Invalid workspace facade or budget" in capsys.readouterr().err

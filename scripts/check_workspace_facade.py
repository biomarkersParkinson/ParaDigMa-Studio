"""Enforce the shrink-only budget for internal workspace driver ports."""

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACADE = ROOT / "src/paradigma_studio/ui/compatibility.py"
BUDGET = ROOT / "scripts/workspace_facade_budget.json"


def read_budget(path: Path) -> tuple[int, set[str]]:
    budget = json.loads(path.read_text(encoding="utf-8"))
    limit, aliases = budget["max_lines"], budget["aliases"]
    if type(limit) is not int or limit < 0:
        raise ValueError("max_lines must be a nonnegative integer")
    if not isinstance(aliases, list) or any(not isinstance(name, str) for name in aliases):
        raise ValueError("aliases must be a list of names")
    if len(set(aliases)) != len(aliases):
        raise ValueError("aliases must not contain duplicate names")
    return limit, set(aliases)


def facade_aliases(source: str) -> set[str]:
    tree = ast.parse(source)
    registry = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_PORTS" for target in node.targets
            )
        ),
        None,
    )
    if not isinstance(registry, ast.Dict):
        raise ValueError("_PORTS must be an explicit dictionary")
    names = []
    for key in registry.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValueError("_PORTS must contain explicit string keys")
        names.append(key.value)
    if len(set(names)) != len(names):
        raise ValueError("_PORTS must not contain duplicate aliases")
    return set(names)


def main(facade_path: Path = FACADE, budget_path: Path = BUDGET) -> int:
    try:
        limit, allowed = read_budget(budget_path)
        source = facade_path.read_text(encoding="utf-8") if facade_path.exists() else ""
        names = facade_aliases(source) if source else set()
    except (OSError, ValueError, TypeError, KeyError, SyntaxError) as exc:
        print(f"Invalid workspace facade or budget: {exc}", file=sys.stderr)
        return 1
    lines = source.count("\n") + int(bool(source) and not source.endswith("\n"))
    errors = []
    if names - allowed:
        errors.append("New or retired aliases are forbidden: " + ", ".join(sorted(names - allowed)))
    if allowed - names:
        errors.append(
            "Remove retired aliases from the budget: " + ", ".join(sorted(allowed - names))
        )
    if lines > limit:
        errors.append(f"Compatibility facade grew to {lines} lines (maximum {limit}).")
    elif lines < limit:
        errors.append(f"Lower the compatibility line budget from {limit} to {lines}.")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Workspace facade: {len(names)} remaining aliases, {lines} lines; budget matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

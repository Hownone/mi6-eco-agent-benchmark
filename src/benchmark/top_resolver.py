from __future__ import annotations

import ast
from pathlib import Path


def resolve_top_module(
    explicit_top: str | None,
    rtl_dir: Path | None = None,
    case_dir: Path | None = None,
    top_config: Path | None = None,
) -> str | None:
    if explicit_top:
        return explicit_top

    candidates: list[Path] = []
    if top_config:
        candidates.append(top_config)

    if case_dir:
        candidates.append(case_dir / "config.py")

    if rtl_dir:
        candidates.append(rtl_dir / "config.py")
        candidates.append(rtl_dir.parent / "config.py")

    seen: set[Path] = set()
    for path in candidates:
        p = path.resolve()
        if p in seen:
            continue
        seen.add(p)

        top = _read_design_top_from_config(p)
        if top:
            return top

    return None


def _read_design_top_from_config(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    source = path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(source, filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == "design_top":
                    val = _const_str(node.value)
                    if val:
                        return val

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "design_top":
                val = _const_str(node.value)
                if val:
                    return val

        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "design_top":
                    val = _const_str(kw.value)
                    if val:
                        return val

    return None


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip() or None
    return None

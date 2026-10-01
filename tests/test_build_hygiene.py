"""Automated build hygiene and dependency leak prevention tests.

Ensures that production runtime modules (gui/, core/, cli/, config/) never
import test framework libraries (unittest, unittest.mock, pytest) which
are excluded from the standalone portable frozen binary distribution.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_PACKAGES = ["core", "gui", "cli", "config"]
FORBIDDEN_ROOT_MODULES = {"unittest", "pytest"}


def get_production_python_files() -> list[Path]:
    """Collect all Python source files in production packages."""
    files: list[Path] = []
    for pkg in PRODUCTION_PACKAGES:
        pkg_path = REPO_ROOT / pkg
        if pkg_path.is_dir():
            files.extend(pkg_path.rglob("*.py"))
    return sorted(files)


@pytest.mark.parametrize("source_file", get_production_python_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_production_modules_do_not_import_test_frameworks(source_file: Path) -> None:
    """Verify that no production Python file imports unittest or pytest.
    
    This is an invariant guard: build_portable.spec excludes unittest from the
    frozen Windows bundle. If any production module imports unittest, the compiled
    executable crashes with ModuleNotFoundError at startup.
    """
    content = source_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(source_file))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in FORBIDDEN_ROOT_MODULES:
                    violations.append(f"Line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split(".")[0]
                if root_module in FORBIDDEN_ROOT_MODULES:
                    violations.append(f"Line {node.lineno}: from {node.module} import ...")

    assert not violations, (
        f"Production file {source_file.relative_to(REPO_ROOT)} imports forbidden test framework:\n"
        + "\n".join(violations)
    )


def test_no_is_callable_factory_hack_in_gui() -> None:
    """Verify that the temporary _is_callable_factory hack does not exist in gui/."""
    gui_dir = REPO_ROOT / "gui"
    for py_file in gui_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "_is_callable_factory" not in content, (
            f"Found _is_callable_factory in {py_file.name}. "
            "Use clean constructor dependency injection instead of mock introspection."
        )

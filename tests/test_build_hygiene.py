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


def test_no_ctkfont_instantiations_in_queue_manager() -> None:
    """Verify gui/queue_manager.py does not instantiate ctk.CTkFont.

    Instantiating CTkFont per queue row creates orphaned Tcl font objects on
    row destruction. When Python GC collects these objects on background worker
    threads, cross-thread Tcl calls can cause deadlocks on Windows.
    Queue rows must use immutable font tuples from gui.theme instead.
    """
    target = REPO_ROOT / "gui" / "queue_manager.py"
    content = target.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(target))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "CTkFont":
                violations.append(f"Line {node.lineno}: CTkFont(...) call")
            elif isinstance(func, ast.Attribute) and func.attr == "CTkFont":
                violations.append(f"Line {node.lineno}: CTkFont call")

    assert not violations, (
        f"Found CTkFont instantiations in {target.relative_to(REPO_ROOT)}:\n"
        + "\n".join(violations)
    )


def test_font_del_guard_thread_safety() -> None:
    """Verify that tkinter.font.Font.__del__ is guarded against non-main thread invocation."""
    import gui  # noqa: F401 - triggers gui/__init__.py patch
    import threading
    import tkinter.font as tkfont

    assert getattr(tkfont.Font.__del__, "_aksara_guarded", False) is True, (
        "tkinter.font.Font.__del__ is not protected by the thread-safety guard."
    )

    class DummyFont:
        def __init__(self, name: str):
            self.name = name
            self.delete_font = True
            self.calls: list[tuple] = []

        def _call(self, *args):
            self.calls.append(args)

    # 1. Calling from a background thread must NOT invoke Tcl _call
    worker_font = DummyFont("worker_font")
    worker_exc = None

    def _worker():
        nonlocal worker_exc
        try:
            tkfont.Font.__del__(worker_font)
        except Exception as exc:
            worker_exc = exc

    t = threading.Thread(target=_worker)
    t.start()
    t.join()

    assert worker_exc is None
    assert worker_font.calls == [], "Font.__del__ called Tcl from background thread!"

    # 2. Calling from the main thread DOES invoke Tcl _call
    main_font = DummyFont("main_font")
    tkfont.Font.__del__(main_font)
    assert main_font.calls == [("font", "delete", "main_font")], "Font.__del__ failed to call Tcl on main thread."

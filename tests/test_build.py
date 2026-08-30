"""Regression: the produced wheel must not contain duplicate zip entries.

The old pyproject.toml had a ``[tool.hatch.build.targets.wheel.force-include]``
section that re-included `data/` and `_fpforge/data/` already covered by
``packages = ["src/invisible_playwright"]``. Hatchling wrote every JSON twice
into the zip; PyPI rejects wheels with duplicate names.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pytest


@pytest.mark.slow
def test_built_wheel_has_no_duplicate_entries(tmp_path):
    """Build the wheel in a clean dir and assert no duplicate zip names."""
    root = Path(__file__).resolve().parent.parent
    out = tmp_path / "dist"
    r = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"build failed:\n{r.stderr}"

    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        dupes = {n: c for n, c in Counter(names).items() if c > 1}

    assert not dupes, f"wheel has duplicate entries (PyPI will reject): {dupes}"

    # ⛔ The sanity check used to ask for `.json` in the wheel, with the comment
    # "the Bayesian data files must still be packaged". That has been FALSE since
    # 2026-07-03: commit 76e41e2, which created invisible_core, moved that data
    # into the core, and this package no longer carries any of it. The assertion
    # kept asking for something that does not exist for six weeks without
    # anything flagging it, because the case is marked `slow` and the default
    # selection DESELECTS it: it never ran in CI, and a gate that never runs is
    # indistinguishable from one that passes.
    #
    # The right check for THIS package is that the module is actually there:
    # that is what breaks if `packages` stops pointing at the right place,
    # which is the same failure class the case was written for.
    modules = [n for n in names if n.startswith("invisible_playwright/")
               and n.endswith(".py")]
    assert modules, f"no package module in the wheel: {sorted(names)[:10]}"
    assert "invisible_playwright/__init__.py" in names, (
        "the wheel does not contain __init__.py: `packages` does not point at the source")

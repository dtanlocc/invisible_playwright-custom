"""A method that uses a name it never has: the NameError nobody ran into yet.

⛔ IT CAUGHT TWO REAL DEFECTS THE MOMENT IT WAS WRITTEN, both of the same shape
and both invisible to every other check in this repo:

* `Actions._set_checked` passed `frame_id` to its retry loop without ever
  taking it as a parameter, while `check()` and `uncheck()` accepted the
  argument and dropped it. Every `page.check()` on the Python transport died
  with `Page.check: name 'frame_id' is not defined` - and the transport judge
  reported it as an ENGINE defect, because the test that exercises it pins the
  transport itself and therefore fails identically on both arms.
* `Actions.drag_and_drop` did the same thing twice in one function.

⛔ WHY THE SUITE DID NOT SEE IT. A `NameError` inside a method is not a syntax
error and not an import error: the module loads, the class builds, the name
resolves at CALL time. So the whole file is green until somebody calls that one
method, and the two above sat in a package with 500 passing tests.

**What it does NOT do.** It does not type-check, it does not follow
`globals()`, `exec`, or a name injected by a decorator, and it deliberately
treats every module-level assignment and import as available. The question it
asks is the narrowest one that catches this: *does this function use a bare
name that is neither its parameter, nor assigned in it, nor defined at module
level?*

    python scripts/check_unresolved_names.py
    python scripts/check_unresolved_names.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import builtins
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: ⛔ `scripts/` IS IN THE PERIMETER SINCE 2026-08-29, and leaving it out was
#: not a scoping decision - it was a hole this gate exists to close. On that
#: date `upstream_baseline.py:_per_file` was found returning `1 if morti else
#: 0` with `morti` assigned nowhere: a guaranteed NameError, sitting in the
#: repository, while this gate reported "none in 102 file(s)". Pointed at that
#: one file by hand it named the fault correctly, so the LOGIC was never
#: wrong; only the perimeter was.
#:
#: And the argument for scanning `scripts/` is STRONGER than for the package,
#: not weaker. The reason this class of defect survives is that a NameError
#: inside a function is invisible until someone calls it - and the package has
#: 529 unit tests calling into it, while these scripts have none. `_per_file`
#: is reached only by `--per-file`, on the async arm, forty minutes into a run
#: nobody makes twice.
#:
#: Measured before widening: 22 files, zero findings besides the real one - so
#: this costs no false positives to keep.
SCANNED = [ROOT / "src" / "invisible_playwright", ROOT / "scripts"]
sys.stdout.reconfigure(encoding="utf-8")

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _module_names(tree: ast.AST) -> set:
    known = {n.name for n in ast.walk(tree)
             if isinstance(n, _FUNCTIONS + (ast.ClassDef,))}
    known |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name)}
    known |= {n.target.id for n in ast.walk(tree)
              if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    known |= {a.asname or a.name.split(".")[0]
              for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
              for a in n.names}
    # ⛔ THE MODULE DUNDERS, which are not builtins and are not imports:
    # Python puts them in the module namespace itself. They only became
    # reachable when this gate started walking module-level functions, and
    # `__file__` in a plain function is the commonest of them by far - it was
    # the first false positive the widening produced.
    known |= {"__file__", "__name__", "__doc__", "__package__", "__spec__",
              "__loader__", "__builtins__", "__path__"}
    return known | set(dir(builtins))


def _bound_in(fn: ast.AST) -> set:
    """Every name that exists inside this function by the time it runs.

    ⛔ Nested functions and lambdas contribute their PARAMETERS, because the
    outer body legitimately refers to them; comprehension targets and `except
    ... as` names too. Leaving any of those out turns ordinary code into a
    fault, and a check that cries wolf is switched off after the third time.
    """
    args = fn.args
    bound = {a.arg for a in list(args.args) + list(args.kwonlyargs)
             + list(getattr(args, "posonlyargs", []))}
    if args.vararg:
        bound.add(args.vararg.arg)
    if args.kwarg:
        bound.add(args.kwarg.arg)
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            bound.add(n.id)
        elif isinstance(n, _FUNCTIONS + (ast.Lambda,)) and n is not fn:
            inner = n.args
            for a in (list(inner.args) + list(inner.kwonlyargs)
                      + list(getattr(inner, "posonlyargs", []))):
                bound.add(a.arg)
            # ⛔ `*args` and `**kw` OF THE NESTED FUNCTION TOO. Leaving these
            # out is not a small gap: the first run of this checker over the
            # real package reported 10 faults and every one of them was this -
            # `def patched(**kw)` inside a wrapper, which is the single most
            # common shape in the file it was scanning. A checker that is
            # wrong ten times out of ten teaches people to ignore it, and the
            # two REAL defects it had just found would have been ignored with
            # the rest.
            if inner.vararg:
                bound.add(inner.vararg.arg)
            if inner.kwarg:
                bound.add(inner.kwarg.arg)
            if not isinstance(n, ast.Lambda):
                bound.add(n.name)
        elif isinstance(n, ast.comprehension):
            for t in ast.walk(n.target):
                if isinstance(t, ast.Name):
                    bound.add(t.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.Global):
            bound.update(n.names)
        elif isinstance(n, ast.Nonlocal):
            bound.update(n.names)
    return bound


def unresolved(source: str, where: str = "<source>") -> list:
    tree = ast.parse(source)
    known = _module_names(tree)
    out = []

    def scan(fn, owner):
        bound = _bound_in(fn)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id not in bound and n.id not in known:
                    out.append((where, owner, fn.name, n.id, n.lineno))

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, _FUNCTIONS)]:
            scan(fn, cls.name)
    # ⛔ MODULE-LEVEL FUNCTIONS TOO, and they were invisible until
    # 2026-08-29. This gate was written against a file of dispatcher classes,
    # so it walked classes and nothing else; a plain function was never looked
    # at. It cost a real defect the day a refactor moved seventeen leaf helpers
    # into two new modules with no classes at all: one of them used `json`
    # without importing it, this gate reported "none in 103 files", and the
    # failure surfaced as a NameError out of one test - which is the exact
    # shape it exists to catch before a caller does.
    for fn in [n for n in tree.body if isinstance(n, _FUNCTIONS)]:
        scan(fn, "<module>")
    return out


SELFTEST = [
    ("the defect itself: used, never taken",
     "class A:\n    def op(self, x):\n        return self.go(frame_id)\n", 1),
    ("a parameter is not a fault",
     "class A:\n    def op(self, frame_id):\n        return frame_id\n", 0),
    ("a keyword-only parameter is not a fault",
     "class A:\n    def op(self, *, frame_id=None):\n        return frame_id\n", 0),
    ("something assigned in the body is not a fault",
     "class A:\n    def op(self):\n        v = 1\n        return v\n", 0),
    ("a module-level name is not a fault",
     "H = 1\nclass A:\n    def op(self):\n        return H\n", 0),
    ("a MODULE-LEVEL FUNCTION using a name nobody imported",
     "def helper(x):\n    return json.dumps(x)\n", 1),
    ("the same module-level function with the import present",
     "import json\ndef helper(x):\n    return json.dumps(x)\n", 0),
    ("__file__ in a module-level function is not a fault",
     "def where():\n    return __file__\n", 0),
    ("an import is not a fault",
     "import json\nclass A:\n    def op(self):\n        return json\n", 0),
    ("a builtin is not a fault",
     "class A:\n    def op(self):\n        return len([])\n", 0),
    ("a nested function's parameter is not a fault",
     "class A:\n    def op(self):\n        def run(p):\n            return p\n"
     "        return run\n", 0),
    ("a comprehension target is not a fault",
     "class A:\n    def op(self):\n        return [i for i in range(3)]\n", 0),
    ("an except-as name is not a fault",
     "class A:\n    def op(self):\n        try:\n            pass\n"
     "        except ValueError as e:\n            return e\n", 0),
    ("two in one function are both reported",
     "class A:\n    def op(self):\n        return (a_missing, b_missing)\n", 2),
    # ⛔ The two below are the shape that produced 10 false alarms on the first
    # real run. They are here so the next person who tightens `_bound_in` finds
    # out immediately instead of from a wall of noise.
    ("a nested function's **kwargs is not a fault",
     "class A:\n    def op(self):\n        def patched(**kw):\n"
     "            return kw\n        return patched\n", 0),
    ("a lambda's *args is not a fault",
     "class A:\n    def op(self):\n        return lambda *args: args\n", 0),
]


def selftest() -> int:
    bad = 0
    for name, source, expected in SELFTEST:
        got = len(unresolved(source))
        ok = got == expected
        bad += 0 if ok else 1
        print("  %-48s %s (%d, expected %d)"
              % (name, "ok" if ok else "BROKEN", got, expected))
    print("selftest: %d cases, %d broken" % (len(SELFTEST), bad))
    return 1 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--selftest", action="store_true")
    p.add_argument("paths", nargs="*",
                   help="default: the package's own source, plus scripts/")
    a = p.parse_args()
    if a.selftest:
        return selftest()

    files = ([pathlib.Path(x) for x in a.paths]
             or sorted(f for root in SCANNED for f in root.rglob("*.py")))
    faults = []
    for f in files:
        try:
            faults += unresolved(f.read_text(encoding="utf-8"), str(f))
        except SyntaxError as bad:
            print("  %s: cannot be parsed (%s)" % (f, bad))
            return 2
    for where, cls, fn, name, line in faults:
        print("  %s :: %s.%s uses %r at line %d and never has it"
              % (pathlib.Path(where).name, cls, fn, name, line))
    if faults:
        print("UNRESOLVED NAMES: %d. Each one is a NameError waiting for the "
              "first caller of that method." % len(faults))
        return 1
    print("UNRESOLVED NAMES: none in %d file(s)." % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())

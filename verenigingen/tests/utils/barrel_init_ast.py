"""
Shared AST/runtime helpers for the barrel-`__init__.py`-self-import guards.

Used by verenigingen/services/billing/test_billing_package_init.py and
verenigingen/tests/utils/test_barrel_init_no_self_import.py (issue #396). A
package `__init__.py` that re-exports its own submodules
(`from .submodule import Name`) means every
`import verenigingen.<pkg>.<anything>` runs all of those imports first, which
under a threaded web worker can deadlock against a second thread that imports
a submodule of the same package directly: CPython takes the *submodule* lock
before the *package* lock, so one thread can hold the package lock inside the
barrel `__init__` while a second holds a submodule lock and waits on the
package - a cycle CPython reports as `_frozen_importlib._DeadlockError`.

Kept in one place because a copy-pasted static-analysis helper is exactly
the "fix one, the others keep the bug" trap: this file used to exist four
times over with drifting behaviour (one copy skipped function bodies, three
did not; none resolved `from ..pkg.sub import X` - a level-2 relative import
that circles back to the SAME package - as a self-import at all).
"""

import ast
import os
import subprocess
import sys
from pathlib import Path


def is_type_checking_guard(node) -> bool:
    """True for `if TYPE_CHECKING:` - those imports never run."""
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _resolve_relative(package_dotted: str, level: int, module: str | None) -> str:
    """Resolve a relative import to the absolute name it targets.

    `package_dotted` is the dotted name of the package whose `__init__.py` is
    being analysed. For an `__init__.py`, `__package__` is the package ITSELF
    (unlike a plain submodule, where `__package__` is the parent) - so
    `from . import x` (level 1) resolves relative to `package_dotted` itself,
    `from .. import x` (level 2) to its parent, and each further level strips
    one more trailing component. Getting this wrong is not academic: inside
    `verenigingen/services/chapter/__init__.py`,
    `from ..chapter.chapter_board_service import ChapterBoardService` is a
    level-2 import that still resolves right back inside this package - and a
    checker that treats "level >= 2" as "always an ancestor, never this
    package" misses it entirely.
    """
    parts = package_dotted.split(".")
    base = ".".join(parts[: len(parts) - (level - 1)])
    if module:
        return f"{base}.{module}" if base else module
    return base


def eager_imports(path: Path, package_dotted: str) -> list[str]:
    """Every module name imported at module-import time by `path`.

    Descends into everything EXCEPT function/async-function bodies: those are
    deferred until called, long after the module has finished initializing,
    so they cannot hold the package lock the way a module-level import does.
    (A decorator expression on a skipped function DOES run at def time, but
    no import statement can appear inside a decorator expression, so this
    does not create a blind spot.) Excludes TYPE_CHECKING-only imports, which
    never run at all.
    """
    names = []
    stack = list(ast.iter_child_nodes(ast.parse(path.read_text(), filename=str(path))))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.If) and is_type_checking_guard(node):
            stack.extend(node.orelse)  # the else branch does run
            continue
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    names.append(node.module)
            else:
                names.append(_resolve_relative(package_dotted, node.level, node.module))
        stack.extend(ast.iter_child_nodes(node))
    return [n for n in names if n]


def is_own_submodule(name: str, package_dotted: str) -> bool:
    # `verenigingen.services.billing_extra` shares the prefix but is a sibling
    return name == package_dotted or name.startswith(package_dotted + ".")


def runtime_own_names(package_dotted: str) -> list[str]:
    """The non-dunder names bound in `package_dotted`'s own module namespace
    after a fresh `import package_dotted`, in a subprocess.

    This is the property the AST check only approximates, and it catches some
    forms the AST walk cannot see - e.g. `x = importlib.import_module(...)` -
    PROVIDED the import's result is bound to a module-level name, which is
    what a barrel re-export is, by definition (`from .sub import Name` binds
    `Name`). It will NOT catch a PEP 562 module `__getattr__` that populates
    `__dict__` only lazily, on first attribute access: a bare `import
    package_dotted` never accesses an attribute, so it never fires.

    Filters out one thing that is NOT this bug: whenever ANY code anywhere
    imports one of this package's submodules, Python automatically binds
    that submodule onto its parent package's namespace under the submodule's
    own filename - regardless of whether this package's own __init__.py did
    anything (measured: verenigingen.utils, this package's PARENT, has its
    own separate, tracked instance of this issue - see
    verenigingen/tests/utils/test_barrel_init_no_self_import.py's allow-list
    - and importing THAT alone already leaves every one of this package's
    submodule names sitting in vars() here). A submodule's OWN filename can
    never be confused with an arbitrary re-exported name like
    `get_security_framework`, so excluding exactly those names (found by
    listing what's actually on disk, not by importing anything) leaves only
    what THIS package's own __init__.py explicitly bound: a `from .sub import
    Name` (the anti-pattern) or a name it legitimately defines itself (e.g. a
    small setup function - see FIXED_PACKAGES).

    An earlier version of this function compared against "what does importing
    the parent alone already load", modelled on the AST check's own
    parent-contamination concern - but that comparison is structurally blind
    here: importing the parent ALSO runs this package's entire __init__.py as
    a side effect (to reach the submodule the parent eagerly imports), so
    anything this package's own file does would appear in both sides of that
    comparison and never show up as a difference. Filtering by "is this a
    submodule's own name" instead of "did the parent already trigger this"
    does not have that blind spot.

    Runs in its own subprocess: sibling tests/imports in this process may
    have already imported this package, so vars() here would prove nothing.
    """
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    # This module lives at <app-root>/verenigingen/tests/utils/barrel_init_ast.py,
    # so parents[2] is the `verenigingen` package directory. Pin the probe to
    # THIS tree: PYTHONPATH loses to cwd inside apps/verenigingen, so a probe
    # run from the wrong place could silently import the installed app instead
    # of the worktree under test and report a stale (or wrong) result.
    expected_root = str(Path(__file__).resolve().parents[2])
    probe = (
        f"import {package_dotted} as _pkg, verenigingen, sys, json, pathlib, pkgutil;"
        "root = str(pathlib.Path(verenigingen.__file__).resolve().parent);"
        f"assert root == {expected_root!r}, (root, {expected_root!r});"
        "submodule_names = {m.name for m in pkgutil.iter_modules(_pkg.__path__)};"
        "own = sorted(k for k in vars(_pkg) if not k.startswith('__') and k not in submodule_names);"
        "print(json.dumps(own))"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"probe failed for {package_dotted!r}: {result.stderr}")
    return ast.literal_eval(result.stdout.strip())

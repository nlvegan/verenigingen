#!/usr/bin/env python3
"""Standalone entry point for the #561 savepoint-rollback-masking ratchet (#1189).

THE GAP THIS CLOSES
--------------------
``verenigingen/tests/unit/test_savepoint_rollback_cannot_mask_the_error.py`` holds an AST
ratchet (``TestEverySavepointRollbackInAnExcept``) that fails the build on any ``except``
handler that hand-writes a savepoint rollback instead of calling ``rollback_to_savepoint()``,
or that swallows a broad exception without an ``except NON_RESUMABLE_DB_ERRORS: raise`` above
it (see that module's docstring for the full mechanism -- a 1213 deadlock destroys the
savepoint, so a hand-written rollback raises 1305 from inside the handler and REPLACES the
error being handled). That test was never wired into pre-commit, pre-push, or any named CI
job -- it only ran as one test among thousands in the full sharded ``Tests`` job, so a
violation was invisible until a specific shard finished, sometimes over an hour after the
push (#1189; it tripped PR #1171 twice this way).

ONE IMPLEMENTATION, TWO ENTRY POINTS
-------------------------------------
This module is the extraction: every function below (``offenders``, ``hand_written_copies``,
``bare_savepoint_rollbacks``, ...) is the SAME code that used to live only as classmethods on
``TestEverySavepointRollbackInAnExcept``. That test class now imports these functions rather
than defining its own copies, so there is exactly one scanner, reachable two ways:

* as a fast, stdlib-only pre-commit/CLI check (this file), and
* as the bench-run assertion inside the full test suite (unchanged).

``PLANTED_OFFENDING_SHAPES`` and ``ACCEPTED_SHAPES`` below are the same fixture dictionaries
the bench test's positive-control test method asserts against, for the same reason: a second,
independently-maintained set of example shapes would drift the way the scanning logic itself
was at risk of drifting.

Scope is IDENTICAL to the original: every ``*.py`` under the ``verenigingen/`` package
directory, excluding ``tests/`` (see ``SKIP_DIRS``) and ``test_*.py`` files anywhere. This is
narrower than ``scripts/`` -- itself live code per this repo's CLAUDE.md -- but widening scope
is a behaviour change, not a wiring one, and is out of #1189's mandate; a grep at the time of
writing found zero savepoint-rollback shapes under ``scripts/`` (latent, not live).

USAGE
-----
    python scripts/validation/savepoint_rollback_validator.py            # whole-tree check
    python scripts/validation/savepoint_rollback_validator.py --stats    # print, exit 0
    python scripts/validation/savepoint_rollback_validator.py <files...> # pre-commit mode

No baseline: like ``vacuous_error_log_test_validator.py``, the population this gate tolerates
is zero (15 handlers were already fixed for #561; this stops the sixteenth), so a shrinking
baseline would be pure ratchet debt.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "verenigingen"
_THIS_DIR = Path(__file__).resolve().parent
_NON_RESUMABLE_AST_PATH = _THIS_DIR / "non_resumable_ast.py"


def _load_non_resumable_ast():
    """Load the sibling module by path, not by import, so this works regardless of sys.path
    or cwd -- and so nothing here needs `scripts.validation` to be an importable package (the
    stdlib-only CI job that runs this file directly, e.g. ``python scripts/validation/
    savepoint_rollback_validator.py``, puts this file's OWN directory on sys.path[0], not the
    repo root -- measured: a plain ``from scripts.validation.non_resumable_ast import ...``
    raises ``ModuleNotFoundError: No module named 'scripts'`` under those conditions). Same
    technique as ``production_divergence_scanner.py``'s ``_load_duplicate_helper_validator``.
    """
    spec = importlib.util.spec_from_file_location("non_resumable_ast", _NON_RESUMABLE_AST_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_nra = _load_non_resumable_ast()
catches_bare_exception = _nra.catches_bare_exception
reraises_non_resumable = _nra.reraises_non_resumable
reraises_unconditionally = _nra.reraises_unconditionally

SKIP_DIRS = ("/tests/", "/node_modules/", "/__pycache__/")

# Same convention as test_termination_non_resumable_errors: a handler that legitimately runs
# AFTER the failure (cleanup, error recovery) may say so on its own line.
EXEMPTION_MARKER = "non-resumable-ok:"

_SAVEPOINT_OPS = ("rollback", "release_savepoint")

# The raw-SQL spelling of the same three operations (#701) -- checked by leading literal text
# rather than attribute name, since all three go through `.sql(...)`.
_RAW_SQL_SAVEPOINT_PREFIXES = ("ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT", "SAVEPOINT ")

# A bare-name call to the canonical helper ITSELF (#701 follow-up review). A hand-written
# `try: rollback_to_savepoint(sp) except Exception: pass` is a copy of the same shape as
# reimplementing the SQL by hand: the helper already tolerates the one diagnosed cause and
# records anything else, so wrapping it in another swallow-all hides that record.
_CANONICAL_HELPER_NAMES = ("rollback_to_savepoint", "release_savepoint_if_present")


def _sql_call_leading_text(node):
    """The first argument's leading literal text for a ``frappe.db.sql(...)``-shaped call: a
    plain string, or the fixed prefix of an f-string before its first interpolation
    (``f"ROLLBACK TO SAVEPOINT {name}"`` -> ``"ROLLBACK TO SAVEPOINT "``). None for anything
    that is not a ``.sql(...)`` call, or whose query argument is not a literal.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sql"):
        return None
    if not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr) and arg.values and isinstance(arg.values[0], ast.Constant):
        return arg.values[0].value
    return None


def _is_raw_sql_savepoint_op(node, *prefixes):
    text = _sql_call_leading_text(node)
    return bool(text) and text.strip().upper().startswith(prefixes)


def bare_savepoint_rollbacks(handler):
    """``frappe.db.rollback(save_point=...)`` OR the raw-SQL spelling
    ``frappe.db.sql("ROLLBACK TO SAVEPOINT ...")`` -- written out by hand, rather than
    through the helper (#701: the raw-SQL spelling is a ``.sql(...)`` call, not a
    ``.rollback(save_point=...)`` call, so an earlier matcher never saw it).
    """
    return [
        node
        for node in ast.walk(handler)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "rollback"
            and any(k.arg == "save_point" for k in node.keywords)
        )
        or _is_raw_sql_savepoint_op(node, "ROLLBACK TO SAVEPOINT")
    ]


def rolls_back_a_savepoint(handler):
    """Either spelling. The swallow rule has to be gated on THIS, not on the by-hand spelling:
    gating it on the bare call made rule 2 unreachable the moment every site was converted to
    the helper, so a newly added swallowing handler that used the helper correctly was
    invisible.
    """
    helper_calls = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "rollback_to_savepoint"
    ]
    return bare_savepoint_rollbacks(handler) + helper_calls


def _is_savepoint_only(statements):
    """Every statement is a savepoint call (possibly under a plain `if`), nothing else."""
    if not statements:
        return False
    for stmt in statements:
        if isinstance(stmt, ast.If):
            if not _is_savepoint_only(stmt.body + stmt.orelse):
                return False
            continue
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            return False
        call = stmt.value
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in _SAVEPOINT_OPS:
            continue
        if isinstance(func, ast.Name) and func.id in _CANONICAL_HELPER_NAMES:
            continue
        if _is_raw_sql_savepoint_op(call, *_RAW_SQL_SAVEPOINT_PREFIXES):
            continue
        return False
    return True


def hand_written_copies(tree, lines):
    """A bare rollback wrapped in its OWN try/except is a copy of the helper.

    Rules 1 and 2 (in `offenders`) look only inside `except` handlers, which is a proxy for
    the real condition ("an exception is in flight"). A helper called FROM a handler defeats
    the proxy; this rule catches the shape instead of the position.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not node.handlers:
            continue
        # The copy signature is a try whose body does NOTHING BUT savepoint work. Requiring
        # "contains a rollback somewhere" instead matches every operation-wide try block that
        # happens to roll back on an early return.
        if not _is_savepoint_only(node.body):
            continue
        if EXEMPTION_MARKER in lines[node.handlers[0].lineno - 1]:
            continue
        yield node.lineno, "hand-written copy of rollback_to_savepoint()"


def offenders(source, tree):
    """Yield ``(lineno, why)`` for every offending shape in `tree` (parsed from `source`).

    Two rules, enforcing SHAPE only:

    1. a broad handler whose body rolls back to a savepoint must be preceded by
       ``except NON_RESUMABLE_DB_ERRORS:`` whose body is a bare ``raise``;
    2. the rollback itself must go through ``rollback_to_savepoint()`` -- rule 1 does not
       cover the nested-commit cause, which arrives as an ordinary exception.
    """
    lines = source.splitlines()
    yield from hand_written_copies(tree, lines)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for position, handler in enumerate(node.handlers):
            if not rolls_back_a_savepoint(handler):
                continue
            if EXEMPTION_MARKER in lines[handler.lineno - 1]:
                continue
            if bare_savepoint_rollbacks(handler):
                yield (
                    handler.lineno,
                    "writes a savepoint rollback by hand (frappe.db.rollback(save_point=...) or "
                    'raw frappe.db.sql("ROLLBACK TO SAVEPOINT ...")) instead of rollback_to_savepoint()',
                )
            if not catches_bare_exception(handler):
                continue
            # A catch-all that re-raises unconditionally cannot swallow anything, so it needs
            # no guard.
            if reraises_unconditionally(handler):
                continue
            # Python matches handlers in order, so a guard below the catch-all is dead.
            if any(reraises_non_resumable(e) for e in node.handlers[:position]):
                continue
            yield handler.lineno, "swallowing catch-all with no `except NON_RESUMABLE_DB_ERRORS: raise` above it"


def is_production_file(path):
    """Same predicate `production_files()` applies during its own walk, exposed so `scan()`
    can apply it uniformly to EXPLICITLY passed paths too. Without this, a co-located
    doctype test file (this app has several `test_<doctype>.py` next to their doctype,
    outside any `tests/` directory) matching pre-commit's broader `files:` regex would be
    scanned as if it were production code -- scope would then depend on which regex a hook
    happened to use rather than on this one predicate.
    """
    text = str(path)
    return not (any(part in text for part in SKIP_DIRS) or Path(path).name.startswith("test_"))


def production_files(root=APP_ROOT):
    for path in sorted(Path(root).rglob("*.py")):
        if is_production_file(path):
            yield path


def scan(paths=None):
    """Return a list of ``"path:lineno -- why"`` strings for every offender found.

    `paths` defaults to every production file under `APP_ROOT` (the original, whole-tree
    scope). Passed explicit files (as pre-commit does), each is still filtered through
    `is_production_file` -- a test file slipping through a hook's broader `files:` regex
    must not silently get scanned as production code.
    """
    findings = []
    if paths is None:
        file_list = list(production_files())
    else:
        file_list = [Path(p) for p in paths if is_production_file(Path(p))]
    for path in file_list:
        try:
            source = path.read_text()
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        for lineno, why in offenders(source, tree):
            try:
                rel = path.resolve().relative_to(REPO_ROOT)
            except ValueError:
                rel = path
            findings.append(f"{rel}:{lineno} -- {why}")
    return findings


# ---------------------------------------------------------------------------
# Shared fixtures (#1189): the SAME planted shapes the bench test's positive
# control (`test_the_ratchet_sees_the_shapes_the_app_no_longer_contains`) checks
# against `offenders()` directly. Kept here, not duplicated there, so the two
# entry points cannot drift on what they are proven to catch.
# ---------------------------------------------------------------------------

PLANTED_OFFENDING_SHAPES = {
    # re-raises, so only rule 1 fires -- one finding, not two
    "bare rollback in a re-raising catch-all": (
        "try:\n    f()\nexcept Exception:\n    frappe.db.rollback(save_point=sp)\n    raise\n",
        1,
    ),
    "a catch-all that swallows breaks both rules": (
        "try:\n    f()\nexcept Exception:\n    frappe.db.rollback(save_point=sp)\n    return None\n",
        2,
    ),
    "a raise that is not the LAST statement does not count": (
        "try:\n    f()\nexcept Exception:\n    try:\n        g()\n    except Exception:\n"
        "        raise\n    frappe.db.rollback(save_point=sp)\n    return None\n",
        2,
    ),
    "guard placed AFTER the catch-all is dead code": (
        "try:\n    f()\nexcept Exception:\n    frappe.db.rollback(save_point=sp)\n"
        "except NON_RESUMABLE_DB_ERRORS:\n    raise\n",
        2,
    ),
    "a guard that logs instead of re-raising does not count": (
        "try:\n    f()\nexcept NON_RESUMABLE_DB_ERRORS:\n    log()\n    return False\n"
        "except Exception:\n    frappe.db.rollback(save_point=sp)\n",
        2,
    ),
    # The hole that shipped: gating rule 2 on the by-hand spelling made it unreachable once
    # every site used the helper. Planted in a real file (dues_schedule_health_manager) it
    # ran 11/11 green.
    "helper + swallow + no guard is the sixteenth site": (
        "try:\n    f()\nexcept Exception:\n    rollback_to_savepoint(sp)\n    return None\n",
        1,
    ),
    "a guard below a helper-using catch-all is still dead code": (
        "try:\n    f()\nexcept Exception:\n    rollback_to_savepoint(sp)\n    return None\n"
        "except NON_RESUMABLE_DB_ERRORS:\n    raise\n",
        1,
    ),
    # `raise Wrapper(e)` IS #561's defect written by hand -- it replaces the exception, so a
    # guard keyed on the original type fails just as it does after a 1305.
    "re-raising a DIFFERENT exception does not count as re-raising": (
        "try:\n    f()\nexcept Exception as e:\n    rollback_to_savepoint(sp)\n"
        "    raise Wrapper(str(e))\n",
        1,
    ),
    "a conditional swallow before a trailing raise does not count": (
        "try:\n    f()\nexcept Exception:\n    rollback_to_savepoint(sp)\n"
        "    if not critical:\n        return None\n    raise\n",
        1,
    ),
    "a bare rollback wrapped in its own try/except is a copy of the helper": (
        "try:\n    frappe.db.rollback(save_point=sp)\nexcept Exception as e:\n    log(e)\n",
        1,
    ),
    "bare except is a catch-all too": (
        "try:\n    f()\nexcept:\n    frappe.db.rollback(save_point=sp)\n",
        2,
    ),
    "(ValueError, Exception) is a catch-all too": (
        "try:\n    f()\nexcept (ValueError, Exception):\n    frappe.db.rollback(save_point=sp)\n",
        2,
    ),
    # The raw-SQL spelling (#701): vip_import.py and member_import_service.py survived every
    # case above unscathed because they wrote frappe.db.sql("ROLLBACK TO SAVEPOINT ...")
    # instead of frappe.db.rollback(save_point=...).
    "raw-SQL rollback in a re-raising catch-all": (
        'try:\n    f()\nexcept Exception:\n    frappe.db.sql("ROLLBACK TO SAVEPOINT sp1")\n    raise\n',
        1,
    ),
    "raw-SQL rollback as an f-string in a swallowing catch-all": (
        "try:\n    f()\nexcept Exception:\n"
        '    frappe.db.sql(f"ROLLBACK TO SAVEPOINT {sp}")\n    return None\n',
        2,
    ),
    "raw-SQL rollback is still flagged for spelling even when properly guarded": (
        "try:\n    f()\nexcept NON_RESUMABLE_DB_ERRORS:\n    raise\n"
        'except Exception:\n    frappe.db.sql("ROLLBACK TO SAVEPOINT sp1")\n    raise\n',
        1,
    ),
    "raw-SQL rollback survives different case and surrounding whitespace": (
        "try:\n    f()\nexcept Exception:\n"
        '    frappe.db.sql("   rollback to savepoint sp1   ")\n    raise\n',
        1,
    ),
    "raw-SQL rollback spanning multiple lines is still detected": (
        "try:\n    f()\nexcept Exception:\n"
        '    frappe.db.sql("""\n        ROLLBACK TO SAVEPOINT sp1\n    """)\n    raise\n',
        1,
    ),
    "raw-SQL RELEASE-only hand-written copy in its own try/except": (
        'try:\n    if flag:\n        frappe.db.sql("RELEASE SAVEPOINT sp1")\n'
        "except Exception:\n    pass\n",
        1,
    ),
    # A wrapper AROUND the canonical helper itself (2nd #701 review round).
    "a canonical helper call wrapped in its own try/except is a copy too": (
        "try:\n    rollback_to_savepoint(sp)\nexcept Exception:\n    pass\n",
        1,
    ),
    "the other helper, release_savepoint_if_present, is caught the same way": (
        "try:\n    if flag:\n        release_savepoint_if_present(sp)\n"
        "except Exception:\n    pass\n",
        1,
    ),
}

ACCEPTED_SHAPES = {
    "guarded and using the helper": (
        "try:\n    f()\nexcept NON_RESUMABLE_DB_ERRORS:\n    raise\n"
        "except Exception:\n    rollback_to_savepoint(sp)\n    return None\n"
    ),
    "a re-raising catch-all needs no guard": (
        "try:\n    f()\nexcept Exception:\n    rollback_to_savepoint(sp)\n    raise\n"
    ),
    "the guard may be spelled as the two classes": (
        "try:\n    f()\n"
        "except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):\n    raise\n"
        "except Exception:\n    rollback_to_savepoint(sp)\n    return None\n"
    ),
    "the guard may be reached through a module alias": (
        "try:\n    f()\nexcept te.NON_RESUMABLE_DB_ERRORS:\n    raise\n"
        "except Exception:\n    rollback_to_savepoint(sp)\n    return None\n"
    ),
    "a narrow handler using the helper": ("try:\n    f()\nexcept ValueError:\n    rollback_to_savepoint(sp)\n"),
    "an exempted hand-written copy": (
        "try:\n    frappe.db.rollback(save_point=sp)\n"
        "except Exception as e:  # non-resumable-ok: deliberately swallows more\n    log(e)\n"
    ),
    "an exempted handler": (
        "try:\n    f()\nexcept Exception:  # non-resumable-ok: runs after the failure\n"
        "    frappe.db.rollback(save_point=sp)\n"
    ),
    "an exempted raw-SQL hand-written copy": (
        'try:\n    frappe.db.sql("ROLLBACK TO SAVEPOINT sp1")\n'
        "except Exception as e:  # non-resumable-ok: deliberately swallows more\n    log(e)\n"
    ),
    "an exempted raw-SQL handler": (
        "try:\n    f()\nexcept Exception:  # non-resumable-ok: runs after the failure\n"
        '    frappe.db.sql("ROLLBACK TO SAVEPOINT sp1")\n'
    ),
    "an exempted canonical-helper wrapper, migration_transaction's real shape": (
        "try:\n    release_savepoint_if_present(sp)\n"
        "except Exception:  # non-resumable-ok: logged, not silent (#701)\n    log(e)\n"
    ),
}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="files to check (default: whole verenigingen/ tree)")
    ap.add_argument("--stats", action="store_true", help="print findings and exit 0")
    args = ap.parse_args(argv[1:])

    whole_tree = not args.paths
    findings = scan(None if whole_tree else args.paths)

    if args.stats:
        print(f"savepoint-rollback offenders: {len(findings)}")
        for f in findings:
            print(f"  {f}")
        return 0

    if findings:
        print("\n\U0001f6d1 Savepoint rollbacks that can mask the error they are cleaning up after (#561)\n")
        for f in findings:
            print(f"  {f}")
        print(
            "\n  A 1213 (and any nested commit) destroys the savepoint, so these rollbacks raise"
            "\n  1305 from inside the handler and REPLACE the error being handled. Use"
            "\n  `rollback_to_savepoint()` from utils.transaction_errors, put"
            "\n  `except NON_RESUMABLE_DB_ERRORS: raise` above the catch-all, or mark the handler"
            f"\n  `# {EXEMPTION_MARKER} <reason>` if it runs after the failure."
        )
        return 1

    if whole_tree:
        print("\u2705 No savepoint-rollback offenders found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

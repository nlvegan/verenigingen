"""A savepoint rollback inside an `except` must never replace the error it is cleaning up after (#561).

``ROLLBACK TO SAVEPOINT`` raises 1305 when the savepoint is gone, and a raise from inside an
``except`` block *replaces* the exception being handled. Two things destroy a savepoint for
reasons unrelated to the failure being handled:

* **a 1213 deadlock** -- the server discards the entire transaction, savepoints included;
* **a nested commit** -- any commit clears the savepoint stack, so a helper that commits
  internally takes its caller's savepoint with it.

Either way the 1305 becomes the propagating exception, and every guard keyed on the original
error's TYPE evaluates False. That is how #481's ``except NON_RESUMABLE_DB_ERRORS: raise``
could be correctly placed on 50 endpoints and still never fire (#561), and it is why a
census found 15 production handlers whose FIRST statement was that rollback.

This module holds three different things, and they cover different amounts:

1. the helper's behaviour, against the REAL driver error rather than a stand-in;
2. one end-to-end site, proving a deadlock now arrives as a deadlock;
3. an AST ratchet over every such handler in the app -- which sees SHAPE only.
"""

import ast
import pathlib

import frappe

from verenigingen.tests.support.non_resumable_ast import (
    catches_bare_exception,
    reraises_non_resumable,
    reraises_unconditionally,
)
from verenigingen.tests.support.non_resumable_errors import deadlock, lock_wait_timeout
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint

APP_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Same convention as test_termination_non_resumable_errors: a handler that legitimately runs
# AFTER the failure (cleanup, error recovery) may say so on its own line.
EXEMPTION_MARKER = "non-resumable-ok:"


class TestRollbackToSavepoint(VereningingenTestCase):
    """The helper, against the real MySQLdb error rather than a hand-made one."""

    def _savepoint(self):
        name = f"sp_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(name)
        return name

    def test_it_really_rolls_the_write_back_when_the_savepoint_is_there(self):
        """The control, asserting the WRITE rather than the return value.

        Asserting only ``assertTrue(rollback_to_savepoint(...))`` does not discriminate:
        replacing the body with ``pass; return True`` leaves that green, so it would be
        equally consistent with the helper never rolling anything back at all.
        """
        tag = frappe.generate_hash(length=10)
        name = self._savepoint()
        frappe.db.set_value("DocType", "ToDo", "description", tag, update_modified=False)
        self.assertEqual(frappe.db.get_value("DocType", "ToDo", "description"), tag)

        self.assertTrue(rollback_to_savepoint(name), "a live savepoint must be rolled back")

        self.assertNotEqual(
            frappe.db.get_value("DocType", "ToDo", "description"),
            tag,
            "the write made after the savepoint must be gone",
        )

    def test_it_reports_a_savepoint_that_is_already_gone_instead_of_raising(self):
        """The real 1305, produced by the real driver.

        Releasing the savepoint reproduces what a 1213 and a nested commit both leave
        behind, without a ROLLBACK that would take the test's own fixtures with it.
        """
        name = self._savepoint()
        frappe.db.sql(f"RELEASE SAVEPOINT {name}")

        # Prove the premise rather than assuming it: this really does raise 1305 today.
        with self.assertRaises(Exception) as caught:
            frappe.db.rollback(save_point=name)
        self.assertIn("does not exist", str(caught.exception))

        self.assertFalse(
            rollback_to_savepoint(name), "a missing savepoint is reported, not raised"
        )

    def test_it_still_raises_anything_that_is_not_a_missing_savepoint(self):
        """It hides one diagnosed condition, not savepoint bugs in general."""
        original = frappe.local.db.rollback

        def _boom(*, save_point=None, chain=False):
            raise RuntimeError("connection went away")

        frappe.local.db.rollback = _boom
        self.addCleanup(frappe.local.db.__dict__.pop, "rollback", None)

        with self.assertRaises(RuntimeError):
            rollback_to_savepoint("whatever")

    def test_the_original_error_survives_the_cleanup(self):
        """The whole point, stated as the invariant rather than as a mechanism.

        Before #561 this block re-raised 1305 and the deadlock was gone.
        """
        name = self._savepoint()
        frappe.db.sql(f"RELEASE SAVEPOINT {name}")

        with self.assertRaises(Exception) as caught:
            try:
                raise deadlock()
            except Exception:
                rollback_to_savepoint(name)
                raise

        self.assertIsInstance(caught.exception, frappe.QueryDeadlockError)


class TestAPollingRowAbandonsOnANonResumableError(VereningingenTestCase):
    """One production site, driven for real. The ratchet below cannot see any of this.

    ``MijnRoodPollingService._row_savepoint`` wraps each row in its own savepoint so one
    bad row does not poison the table -- deliberate, documented, and right for an ordinary
    failure. On a 1205/1213 it was wrong twice over: the scan carried on against a
    transaction the server had discarded, and the 1305 from its own rollback replaced the
    error on the way out.
    """

    def _open_row_savepoint(self, stats):
        from verenigingen.mijnrood_sync.services.polling_service import MijnRoodPollingService

        return MijnRoodPollingService()._row_savepoint("row-1", "members", stats)

    def _capture_savepoint_names(self):
        taken = []
        real = frappe.local.db.savepoint

        def _recording(save_point):
            taken.append(save_point)
            return real(save_point)

        frappe.local.db.savepoint = _recording
        self.addCleanup(frappe.local.db.__dict__.pop, "savepoint", None)
        return taken

    def test_an_ordinary_row_failure_is_still_swallowed_so_the_batch_continues(self):
        """The control. Without it, the two tests below would also pass if per-row
        isolation had been removed altogether."""
        stats = {}
        with self._open_row_savepoint(stats):
            raise ValueError("one bad row")

        self.assertEqual(stats["errors"], 1, "an ordinary row failure is counted and skipped")

    def test_a_deadlock_abandons_the_scan_instead_of_counting_it_as_one_bad_row(self):
        stats = {}
        with self.assertRaises(frappe.QueryDeadlockError):
            with self._open_row_savepoint(stats):
                raise deadlock()

        self.assertEqual(
            stats.get("errors", 0),
            0,
            "a transaction the server discarded is not a row error to tally and move past",
        )

    def test_a_lock_timeout_abandons_the_scan_too(self):
        stats = {}
        with self.assertRaises(frappe.QueryTimeoutError):
            with self._open_row_savepoint(stats):
                raise lock_wait_timeout()

        self.assertEqual(stats.get("errors", 0), 0)

    def test_a_destroyed_savepoint_does_not_replace_the_row_error(self):
        """The masking half, at a real site.

        Releasing the savepoint reproduces what a 1213 and a nested commit both leave
        behind. Before #561 the handler's own ``rollback(save_point=...)`` raised 1305 out
        of the context manager, so a row failure the caller had chosen to tolerate became
        an unhandled error about a savepoint.
        """
        taken = self._capture_savepoint_names()
        stats = {}
        with self._open_row_savepoint(stats):
            frappe.db.sql(f"RELEASE SAVEPOINT {taken[-1]}")
            raise ValueError("one bad row, and the savepoint is gone")

        self.assertEqual(stats["errors"], 1, "the row failure is still what gets counted")


class TestEverySavepointRollbackInAnExcept(VereningingenTestCase):
    """The ratchet. 15 handlers were fixed; this is what stops the sixteenth.

    Scoped to every production handler in the app rather than one package, because the
    census for #561 read all of them -- a narrower scope would leave the rest exactly as
    they were when the same trap was documented in PR #169 and then recurred 15 times.

    Two rules, and it enforces SHAPE only:

    1. a broad handler whose body rolls back to a savepoint must be preceded by
       ``except NON_RESUMABLE_DB_ERRORS:`` whose body is a bare ``raise``;
    2. the rollback itself must go through ``rollback_to_savepoint()``, because rule 1
       does not cover the nested-commit cause -- that arrives as an ordinary exception.

    Both rules originally matched only ``frappe.db.rollback(save_point=...)``. Two sites
    (vip_import.py, member_import_service.py) instead hand-wrote the raw SQL --
    ``frappe.db.sql("ROLLBACK TO SAVEPOINT ...")`` -- which is a ``.sql(...)`` call, not a
    ``.rollback(save_point=...)`` call, so they survived this ratchet entirely despite its
    docstring's claim to cover "every such handler" (#701). ``_bare_savepoint_rollbacks``,
    ``_is_savepoint_only`` and ``_rolls_back_a_savepoint`` now match either spelling.

    **What it cannot see:** whether a guarded handler then reports the error usefully, and
    whether an exemption's stated reason is true. Both stay human claims. Read that before
    reading a green run here as coverage of behaviour.
    """

    SKIP_DIRS = ("/tests/", "/node_modules/", "/__pycache__/")

    @staticmethod
    def _sql_call_leading_text(node):
        """The first argument's leading literal text for a ``frappe.db.sql(...)``-shaped
        call: a plain string, or the fixed prefix of an f-string before its first
        interpolation (``f"ROLLBACK TO SAVEPOINT {name}"`` -> ``"ROLLBACK TO SAVEPOINT "``).
        None for anything that is not a ``.sql(...)`` call, or whose query argument is
        not a literal -- a query built entirely from a variable defeats this the same
        way it would defeat a human reviewer, which is out of scope here as it is for
        every other AST ratchet in this app.
        """
        if not (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sql"
        ):
            return None
        if not node.args:
            return None
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.JoinedStr) and arg.values and isinstance(arg.values[0], ast.Constant):
            return arg.values[0].value
        return None

    @classmethod
    def _is_raw_sql_savepoint_op(cls, node, *prefixes):
        text = cls._sql_call_leading_text(node)
        return bool(text) and text.strip().upper().startswith(prefixes)

    @classmethod
    def _bare_savepoint_rollbacks(cls, handler):
        """``frappe.db.rollback(save_point=...)`` OR the raw-SQL spelling
        ``frappe.db.sql("ROLLBACK TO SAVEPOINT ...")`` -- written out by hand, rather
        than through the helper.

        The raw-SQL spelling is what let vip_import.py and member_import_service.py
        survive this ratchet entirely (#701): the AST shape is a ``.sql(...)`` call,
        not a ``.rollback(save_point=...)`` call, so the original matcher -- whose
        docstring claimed to cover "every such handler" -- never saw it.
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
            or cls._is_raw_sql_savepoint_op(node, "ROLLBACK TO SAVEPOINT")
        ]

    @classmethod
    def _rolls_back_a_savepoint(cls, handler):
        """Either spelling. The swallow rule has to be gated on THIS, not on the by-hand
        spelling: gating it on the bare call made rule 2 unreachable the moment every site
        was converted to the helper, so a newly added swallowing handler that used the
        helper correctly was invisible. Measured by planting exactly that in
        dues_schedule_health_manager -- 11/11 green, on a ratchet whose docstring said it
        stopped the sixteenth site."""
        helper_calls = [
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "rollback_to_savepoint"
        ]
        return cls._bare_savepoint_rollbacks(handler) + helper_calls

    _SAVEPOINT_OPS = ("rollback", "release_savepoint")

    # The raw-SQL spelling of the same three operations (#701) -- checked by leading
    # literal text rather than attribute name, since all three go through `.sql(...)`.
    _RAW_SQL_SAVEPOINT_PREFIXES = ("ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT", "SAVEPOINT ")

    # A bare-name call to the canonical helper ITSELF (#701 follow-up review). A
    # hand-written `try: rollback_to_savepoint(sp) except Exception: pass` is a
    # copy of the same shape as reimplementing the SQL by hand: the helper
    # already tolerates the one diagnosed cause and records anything else, so
    # wrapping it in another swallow-all hides that record. This is exactly what
    # let migration_transaction's own `finally:` cleanup survive review
    # undetected -- neither `_hand_written_copies` nor `error_swallow_validator`
    # recognised a bare `ast.Name` call as a savepoint op.
    _CANONICAL_HELPER_NAMES = ("rollback_to_savepoint", "release_savepoint_if_present")

    @classmethod
    def _is_savepoint_only(cls, statements):
        """Every statement is a savepoint call (possibly under a plain `if`), nothing else."""
        if not statements:
            return False
        for stmt in statements:
            if isinstance(stmt, ast.If):
                if not cls._is_savepoint_only(stmt.body + stmt.orelse):
                    return False
                continue
            if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                return False
            call = stmt.value
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr in cls._SAVEPOINT_OPS:
                continue
            if isinstance(func, ast.Name) and func.id in cls._CANONICAL_HELPER_NAMES:
                continue
            if cls._is_raw_sql_savepoint_op(call, *cls._RAW_SQL_SAVEPOINT_PREFIXES):
                continue
            return False
        return True

    @classmethod
    def _hand_written_copies(cls, tree, lines):
        """A bare rollback wrapped in its OWN try/except is a copy of the helper.

        Rules 1 and 2 look only inside `except` handlers, which is a proxy for the real
        condition ("an exception is in flight"). A helper called FROM a handler defeats the
        proxy: termination_execution_service._rollback_savepoint is called at two sites
        that are inside `except` blocks, and neither rule can see it. This rule catches the
        shape instead of the position.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not node.handlers:
                continue
            # The copy signature is a try whose body does NOTHING BUT savepoint work.
            # Requiring "contains a rollback somewhere" instead matched every operation-wide
            # try block that happens to roll back on an early return -- 4 false positives on
            # the first attempt, which is how a ratchet trains people to add exemptions.
            if not cls._is_savepoint_only(node.body):
                continue
            if EXEMPTION_MARKER in lines[node.handlers[0].lineno - 1]:
                continue
            yield node.lineno, "hand-written copy of rollback_to_savepoint()"

    def _offenders(self, source, tree):
        lines = source.splitlines()
        yield from self._hand_written_copies(tree, lines)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for position, handler in enumerate(node.handlers):
                if not self._rolls_back_a_savepoint(handler):
                    continue
                if EXEMPTION_MARKER in lines[handler.lineno - 1]:
                    continue
                if self._bare_savepoint_rollbacks(handler):
                    yield (
                        handler.lineno,
                        "writes a savepoint rollback by hand (frappe.db.rollback(save_point=...) or "
                        'raw frappe.db.sql("ROLLBACK TO SAVEPOINT ...")) instead of rollback_to_savepoint()',
                    )
                if not catches_bare_exception(handler):
                    continue
                # A catch-all that re-raises unconditionally cannot swallow anything, so it
                # needs no guard: application_payments and the ING webhooks are that shape.
                if reraises_unconditionally(handler):
                    continue
                # Python matches handlers in order, so a guard below the catch-all is dead.
                if any(reraises_non_resumable(e) for e in node.handlers[:position]):
                    continue
                yield handler.lineno, "swallowing catch-all with no `except NON_RESUMABLE_DB_ERRORS: raise` above it"

    def _production_files(self):
        for path in sorted(APP_ROOT.rglob("*.py")):
            text = str(path)
            if any(part in text for part in self.SKIP_DIRS) or path.name.startswith("test_"):
                continue
            yield path

    def test_no_savepoint_rollback_can_mask_the_error_it_is_cleaning_up_after(self):
        offenders = []
        for path in self._production_files():
            source = path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for lineno, why in self._offenders(source, tree):
                offenders.append(f"{path.relative_to(APP_ROOT)}:{lineno} -- {why}")

        self.assertEqual(
            offenders,
            [],
            "a 1213 (and any nested commit) destroys the savepoint, so these rollbacks raise "
            "1305 from inside the handler and REPLACE the error being handled (#561). Use "
            "`rollback_to_savepoint()` from utils.transaction_errors, put "
            "`except NON_RESUMABLE_DB_ERRORS: raise` above the catch-all, or mark the handler "
            f"`# {EXEMPTION_MARKER} <reason>` if it runs after the failure:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_ratchet_sees_the_shapes_the_app_no_longer_contains(self):
        """A synthetic positive control. Once the app is clean the test above passes on an
        empty list -- which is also what a walker that silently matched nothing produces.
        Every branch below is unreachable from the real files."""
        planted = {
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
            # The hole that shipped: gating rule 2 on the by-hand spelling made it
            # unreachable once every site used the helper. Planted in a real file
            # (dues_schedule_health_manager) it ran 11/11 green.
            "helper + swallow + no guard is the sixteenth site": (
                "try:\n    f()\nexcept Exception:\n    rollback_to_savepoint(sp)\n    return None\n",
                1,
            ),
            "a guard below a helper-using catch-all is still dead code": (
                "try:\n    f()\nexcept Exception:\n    rollback_to_savepoint(sp)\n    return None\n"
                "except NON_RESUMABLE_DB_ERRORS:\n    raise\n",
                1,
            ),
            # `raise Wrapper(e)` IS #561's defect written by hand -- it replaces the
            # exception, so a guard keyed on the original type fails just as it does
            # after a 1305.
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
            # The raw-SQL spelling (#701): vip_import.py and member_import_service.py
            # survived every case above unscathed because they wrote
            # frappe.db.sql("ROLLBACK TO SAVEPOINT ...") instead of
            # frappe.db.rollback(save_point=...). These plant that shape directly so a
            # future refactor of _is_raw_sql_savepoint_op cannot silently stop seeing it.
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
            # A wrapper AROUND the canonical helper itself (2nd #701 review round):
            # migration_transaction's own `finally:` cleanup was exactly this shape --
            # a bare-name call to release_savepoint_if_present, in its own try/except,
            # invisible to every rule above because none of them recognised an
            # ast.Name call as a savepoint op.
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
        for label, (snippet, expected) in planted.items():
            with self.subTest(label):
                found = list(self._offenders(snippet, ast.parse(snippet)))
                self.assertEqual(
                    len(found), expected, f"{label}: expected {expected} findings, got {found}"
                )

        accepted = {
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
            "a narrow handler using the helper": (
                "try:\n    f()\nexcept ValueError:\n    rollback_to_savepoint(sp)\n"
            ),
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
        for label, snippet in accepted.items():
            with self.subTest(label):
                self.assertEqual(
                    list(self._offenders(snippet, ast.parse(snippet))), [], f"{label} must be accepted"
                )

    def test_the_two_error_classes_it_names_are_the_ones_that_exist(self):
        """Guards against the tuple being renamed out from under the ratchet's string match."""
        self.assertEqual(
            NON_RESUMABLE_DB_ERRORS, (frappe.QueryDeadlockError, frappe.QueryTimeoutError)
        )
        self.assertIsInstance(deadlock(), frappe.QueryDeadlockError)
        self.assertIsInstance(lock_wait_timeout(), frappe.QueryTimeoutError)

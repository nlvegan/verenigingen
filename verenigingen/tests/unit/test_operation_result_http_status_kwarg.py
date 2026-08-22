"""No call site may pass ``http_status_code=`` to an ``OperationResult`` builder (#481).

The field is ``http_status``. ``OperationResult.fail()`` / ``ok()`` / ``from_exception()``
all end their signature in ``**metadata``, so the near-miss name is not a ``TypeError`` --
it is silently absorbed::

    OperationResult.fail("nope", http_status_code=403).http_status  -> None
    OperationResult.fail("nope", http_status_code=403).metadata     -> {'http_status_code': 403}

Nine sites in ``api/payment_processing.py`` did this, and the reason it matters is not the
value being wrong today (nothing reads ``http_status`` yet -- see #481 part 2, the status
that never reaches ``frappe.local.response``). It is that the *next* change, the one that
wires ``http_status`` to the transport, would appear to work on every other endpoint and
silently do nothing on the payment ones. A partial fix that looks total is worse than the
original defect.

**What this test does NOT enforce.** It is a shape check over call sites, not a behavioural
one. It cannot tell you that a correctly-named ``http_status`` is the *right* status, that it
reaches the HTTP response (it does not, today), or that a builder reached through an alias
carries the field at all. It pins exactly one thing: that no caller spells the field with the
``_code`` suffix and loses it to ``**metadata``.
"""

import ast
import os
import tempfile

from verenigingen.tests.utils.base import VereningingenTestCase

BUILDERS = {"fail", "ok", "from_exception"}
WRONG = "http_status_code"


def _app_package_root():
    import verenigingen

    return os.path.dirname(os.path.abspath(verenigingen.__file__))


def _offending_call_sites(root):
    """Every ``<something>.fail/ok/from_exception(..., http_status_code=...)`` under ``root``.

    Returns ``(hits, files_scanned)``. The count is returned, not discarded, because a sweep
    that silently walks nothing is indistinguishable from a clean tree -- this repo has
    already shipped a discovery pass that reported "0 found" for every target *and* for its
    control, and the only reason that was caught was the control.

    Matched on the attribute name rather than on the receiver being literally
    ``OperationResult``: the builders are also reached through aliases and subclasses, and a
    receiver-name match would have missed those while looking thorough.
    """
    hits = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            if os.path.abspath(path) == os.path.abspath(__file__):
                # This module carries the known-bad spelling on purpose, in the
                # characterisation test below.
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            scanned += 1
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in BUILDERS:
                    continue
                if any(kw.arg == WRONG for kw in node.keywords):
                    hits.append(f"{os.path.relpath(path, root)}:{node.lineno}")
    return sorted(hits), scanned


class TestNoCallSiteLosesItsHttpStatusToMetadata(VereningingenTestCase):
    def test_no_operation_result_builder_is_called_with_http_status_code(self):
        offenders, scanned = _offending_call_sites(_app_package_root())

        self.assertGreater(scanned, 100, "the sweep walked almost nothing; it cannot have checked the app")
        self.assertEqual(
            [],
            offenders,
            "these call sites pass `http_status_code=`, which OperationResult absorbs into "
            "metadata and never reads; the field is `http_status`:\n  " + "\n  ".join(offenders),
        )

    def test_the_sweep_finds_a_planted_offender(self):
        """CONTROL, and it must drive the REAL sweep.

        The first version of this control re-implemented the matcher inline over a hardcoded
        snippet, so it never touched the file walk it exists to protect: breaking the root
        path so the ratchet scanned zero files left BOTH tests green. It now plants a file and
        makes ``_offending_call_sites`` walk to it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"))
            with open(os.path.join(tmp, "pkg", "bad.py"), "w", encoding="utf-8") as handle:
                handle.write("OperationResult.fail('x', http_status_code=403)\n")
            with open(os.path.join(tmp, "pkg", "good.py"), "w", encoding="utf-8") as handle:
                handle.write("OperationResult.fail('x', http_status=403)\n")

            offenders, scanned = _offending_call_sites(tmp)

        self.assertEqual(["pkg/bad.py:1"], offenders)
        self.assertEqual(2, scanned)


class TestWhyTheRatchetExists(VereningingenTestCase):
    """Characterisation of the absorption itself, so the reason above is executable rather
    than a comment that can drift away from the code."""

    def test_the_near_miss_name_lands_in_metadata_and_http_status_stays_none(self):
        from verenigingen.utils.operation_result import OperationResult

        result = OperationResult.fail("nope", http_status_code=403)

        self.assertIsNone(result.http_status)
        self.assertEqual({"http_status_code": 403}, result.metadata)

    def test_the_correct_name_is_carried(self):
        """CONTROL. Without this the test above is equally consistent with the field having
        been removed from OperationResult altogether."""
        from verenigingen.utils.operation_result import OperationResult

        result = OperationResult.fail("nope", http_status=403)

        self.assertEqual(403, result.http_status)
        self.assertEqual({}, result.metadata)

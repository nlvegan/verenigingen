"""Ratchet: an `/api/method/` call a shipped template or www page makes must
resolve to a whitelisted function.

Companion to test_shipped_links_resolve.py, which proves a page's ROUTE resolves.
That guard's own docstring says what it does NOT check: "that the page behind a
resolving route works... several routes certified there call backend methods that
do not exist." #430 found 22 such calls across nine pages -- test_page_dashboard's
two "Export"/"Save" buttons among them -- all invisible to the route guard because
a 404'd *page* and a page whose *button* silently does nothing are different
failures with the same green checkmark upstream of this file.

TWO WAYS A CALL CAN BE BROKEN, NOT ONE:

* MISSING -- the module or function was never defined (or was renamed/moved and
  the caller wasn't updated). Fix: implement it, repoint the call, or delete the
  page/button.
* NOT_WHITELISTED -- the function exists and resolves, but the resolved object is
  not the one Frappe's whitelist registry knows about. In this codebase that is
  almost always the decorator-order bug CLAUDE.md documents: @frappe.whitelist()
  is identity-based, so it must be the OUTERMOST decorator, or a later decorator's
  wrapper becomes the name Frappe serves while a different (inner) object sits in
  frappe.whitelisted.

These need different fixes, so the baseline records which one applies to each
entry: a MISSING call fixed by implementing it looks the same as one "fixed" by
deleting the button that referenced it (both leave the baseline), but a call that
flips from MISSING to NOT_WHITELISTED (e.g. someone adds the module back with the
decorator in the wrong order) must NOT silently read as still-broken-so-fine --
test_the_baseline_status_matches_the_tree below catches exactly that.
"""

import importlib
import re
from pathlib import Path

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

APP_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = (APP_ROOT / "templates" / "pages", APP_ROOT / "www")
BASELINE = Path(__file__).with_name("shipped_broken_api_calls.txt")

# A dotted Python path used as a frappe.call `method`, in any of three shapes
# seen in this app's shipped pages:
#   - a literal /api/method/ URL fragment, optionally with a query string
#     (donate.html's retry link: `/api/method/...retry_payment?donation_id=...`)
#   - the `method:` value passed to frappe.call() -- a bare key, as JS object
#     literals normally write it
#   - the same, but as a quoted JSON key -- admin_tools.py declares its entire
#     button catalogue as `"method": "dotted.path"` (41 distinct paths across
#     53 sites), which a bare `method:` match misses entirely
# Requires a full trailing segment (so `method: 'GET'` and a namespace built up
# via string concatenation, e.g. `verenigingen.api.foo.` + action, don't match)
# and a quote/`?`/`&` boundary right after the last segment, so a truncated
# prefix isn't mistaken for a real leaf method -- dues-invoice-debugger.html
# does exactly this: `'/api/method/verenigingen.api.dues_invoice_workflow.' +
# method`, where without that boundary check the regex would otherwise happily
# match the namespace up to (but not including) the trailing dot as if it were
# a complete path.
DOTTED_METHOD = re.compile(
    r"""(?:/api/method/|["']?method["']?\s*:\s*["'])"""
    r"""([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?=["'?&])"""
)

# frappe/erpnext core methods the pages call directly -- not this app's to fix.
CORE_PREFIXES = ("frappe.", "erpnext.")


def shipped_api_calls():
    calls = set()
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in (".html", ".py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                calls.update(DOTTED_METHOD.findall(text))
    return {c for c in calls if not c.startswith(CORE_PREFIXES)}


def classify(dotted_path):
    """Return ('OK', None) or (status, detail) for a dotted method path.

    status is 'MISSING' (module or function doesn't exist -- same fix path:
    define it, repoint the call, or remove it) or 'NOT_WHITELISTED' (it exists
    but frappe.whitelisted doesn't recognise the resolved object).
    """
    module_path, _, func_name = dotted_path.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except Exception as e:
        # Catches more than ImportError deliberately: this scan imports ~150+
        # arbitrary modules by dotted path, and a SyntaxError, AttributeError, or
        # Frappe exception raised at import time is just as much "this call is
        # broken" as a plain missing module -- narrowing to ImportError would
        # turn any of those into a hard test-collection error instead of a
        # reported MISSING finding.
        return "MISSING", f"module: {e}"

    func = getattr(module, func_name, None)
    if func is None:
        return "MISSING", "function not found on module"

    if func in frappe.whitelisted:
        return "OK", None
    return "NOT_WHITELISTED", None


def load_baseline():
    """Return {dotted_path: status} from the baseline file (comments/blank lines skipped)."""
    entries = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "\t" not in line:
            raise AssertionError(
                f"{BASELINE.name} line {line!r} has no tab between path and status -- "
                "the format is '<dotted.path>\\t<STATUS>'"
            )
        path, _, status = line.partition("\t")
        entries[path.strip()] = status.strip()
    return entries


class TestShippedApiCallsAreWhitelisted(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.calls = shipped_api_calls()
        self.baseline = load_baseline()

    def test_the_scan_finds_known_shipped_calls(self):
        """Control. A regex that matches nothing would pass every other test here --
        and one that only matches the plain `method: 'x'` shape did exactly that
        while missing 42 calls in the other two shapes below, undetected."""
        self.assertGreaterEqual(len(self.calls), 140, "no /api/method/ calls parsed from shipped pages")
        # `method: 'x.y.z'` -- a bare JS object key.
        self.assertIn("verenigingen.api.chapter_join.join_chapter", self.calls)
        # `"method": "x.y.z"` -- admin_tools.py's JSON-style button catalogue.
        self.assertIn(
            "verenigingen.services.billing.invoice_management.cleanup_orphaned_schedules", self.calls
        )
        # `/api/method/x.y.z?param=...` -- a literal URL with a query string.
        self.assertIn("verenigingen.templates.pages.donate.retry_payment", self.calls)

    def test_the_control_catches_a_broken_call(self):
        """Control in the other direction: classify() must actually flag a bad path,
        not just wave everything through."""
        status, _ = classify("verenigingen.api.this_module_does_not_exist.nope")
        self.assertEqual(status, "MISSING")

    def test_no_undeclared_broken_api_call(self):
        undeclared = {}
        for call in sorted(self.calls - set(self.baseline)):
            status, detail = classify(call)
            if status != "OK":
                undeclared[call] = (status, detail)

        self.assertEqual(
            undeclared,
            {},
            "these shipped /api/method/ calls are broken but not in "
            f"{BASELINE.name}: {undeclared}",
        )

    def test_the_baseline_has_not_gone_stale(self):
        """A baselined call that now resolves and is whitelisted must leave the baseline."""
        fixed = [path for path in self.baseline if classify(path)[0] == "OK"]

        self.assertEqual(
            fixed,
            [],
            f"these calls now resolve and are whitelisted; delete them from {BASELINE.name}: "
            + ", ".join(sorted(fixed)),
        )

    def test_the_baseline_status_matches_the_tree(self):
        """A call that changes FROM which broken state it's in (e.g. MISSING becomes
        NOT_WHITELISTED because the module reappeared with a decorator-order bug)
        must not silently read as "still broken, nothing to see" -- the baseline's
        recorded status has to track which fix it actually needs."""
        mismatched = {}
        for path, recorded_status in self.baseline.items():
            current_status, _ = classify(path)
            if current_status != "OK" and current_status != recorded_status:
                mismatched[path] = {"baseline": recorded_status, "now": current_status}

        self.assertEqual(
            mismatched,
            {},
            f"these calls changed which way they're broken; update {BASELINE.name}: {mismatched}",
        )

    def test_the_baseline_names_only_calls_the_pages_still_reference(self):
        orphaned = sorted(set(self.baseline) - self.calls)

        self.assertEqual(
            orphaned,
            [],
            f"{BASELINE.name} names calls no shipped page references any more: "
            + ", ".join(orphaned),
        )

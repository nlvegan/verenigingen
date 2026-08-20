"""Ratchet: the public application form must not read element ids the page lacks.

#201 was one instance of a class. `collectFormDataDirectly()` builds the entire
payload that `submit_application` receives, by reading element ids out of
/apply_for_membership. Nothing has ever checked that those ids exist, so a field
whose id is wrong does not raise, does not log, and does not fail a test — it
just transmits '' or false forever. Fourteen of the thirty-one fields were in
that state when this guard was written (#412).

The check that would have caught #201 is this one, not a better unit test of the
collector: it compares the two artifacts that have to agree.
"""

import re
from pathlib import Path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

APP_ROOT = Path(__file__).resolve().parents[3]
COLLECTOR_JS = APP_ROOT / "public" / "js" / "membership_application.js"
BASELINE = Path(__file__).with_name("application_form_missing_ids.txt")

# `$('#some_id')`, however the quotes and spacing fall.
ID_SELECTOR = re.compile(r"""\$\(\s*['"]#([A-Za-z0-9_-]+)['"]\s*\)""")
# `field_name:` opening one entry of the returned object literal.
PAYLOAD_KEY = re.compile(r"\s*([a-z_][a-z0-9_]*)\s*:", re.IGNORECASE)


def parse_collector_fields():
    """Map each payload field of collectFormDataDirectly() to the ids it reads.

    Keyed by field rather than by id because several fields read a fallback
    chain (`$('#a').val() || $('#b').val()`); such a field is only broken when
    *none* of its ids resolve.
    """
    source = COLLECTOR_JS.read_text(encoding="utf-8")
    start = source.find("\tcollectFormDataDirectly() {")
    if start == -1:
        # str.index would raise with the whole 4500-line file in the message.
        raise AssertionError(
            f"collectFormDataDirectly() not found in {COLLECTOR_JS.name}. If it was "
            "renamed or moved, point this parser at its new home — do not delete "
            "the guard."
        )
    literal = source.find("return {", start)
    end = source.find("\n\t}\n", literal)
    if literal == -1 or end == -1:
        raise AssertionError(
            "collectFormDataDirectly() no longer returns a single object literal; "
            "this parser needs updating to match."
        )

    fields = {}
    field = None
    for line in source[start:end].splitlines():
        key = PAYLOAD_KEY.match(line)
        if key:
            field = key.group(1)
            fields.setdefault(field, [])
        if field is not None:
            fields[field].extend(ID_SELECTOR.findall(line))

    return {name: sorted(set(ids)) for name, ids in fields.items() if ids}


def load_baseline():
    entries = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


class TestApplicationFormSelectorContract(EnhancedTestCase):
    """/apply_for_membership rendered, against the collector that reads it."""

    def setUp(self):
        super().setUp()
        self.fields = parse_collector_fields()
        self.baseline = load_baseline()
        self.rendered_ids = self._rendered_ids()

    def _rendered_ids(self):
        """Render as a real applicant sees it — Guest, not Administrator."""
        from frappe.website.serve import get_response_content

        with self.as_user("Guest"):
            html = get_response_content("apply_for_membership")
        return set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))

    def _broken(self):
        return {
            name for name, ids in self.fields.items() if not set(ids) & self.rendered_ids
        }

    def test_the_parser_and_the_page_are_both_alive(self):
        """Control. Without it, a parser returning {} passes every other test here.

        Reformatting the JS object literal, renaming the function, or rendering
        an error page instead of the form would all silently empty one side of
        the comparison and turn this file green.
        """
        self.assertGreaterEqual(len(self.fields), 25, "collector parse looks empty")
        self.assertIn("email", self.fields)
        self.assertIn("email", self.rendered_ids)
        self.assertIn("bank_account_name", self.fields)
        # A fallback chain must be read as one field with several ids.
        self.assertGreater(len(self.fields["bank_account_name"]), 1)

    def test_no_payload_field_reads_an_id_the_page_does_not_render(self):
        """A field not in the baseline must resolve to something on the page."""
        undeclared = sorted(self._broken() - self.baseline)

        self.assertEqual(
            undeclared,
            [],
            "these payload fields read ids /apply_for_membership does not render, so "
            "they transmit '' or false on every application: "
            + ", ".join(f"{name} (reads #{', #'.join(self.fields[name])})" for name in undeclared),
        )

    def test_the_baseline_has_not_gone_stale(self):
        """A baselined field that now works must leave the baseline.

        A ratchet that only ever checks one direction stops shrinking: the entry
        outlives the defect and the next reader believes the field is broken.
        """
        fixed = sorted(self.baseline & set(self.fields) - self._broken())

        self.assertEqual(
            fixed,
            [],
            "these fields now resolve on the page; delete them from "
            f"{BASELINE.name}: " + ", ".join(fixed),
        )

    def test_the_baseline_names_only_fields_that_still_exist(self):
        """Guards against a rename leaving a dead entry behind."""
        unknown = sorted(self.baseline - set(self.fields))

        self.assertEqual(
            unknown,
            [],
            f"{BASELINE.name} names payload fields collectFormDataDirectly() no "
            "longer has: " + ", ".join(unknown),
        )

"""Ratchet: the public application form must not read element ids the page lacks.

#201 was one instance of a class. The payload `submit_application` receives is built
by `getAllFormData()`, which merges `collectFormDataDirectly()` and then
`getAdditionalFormData()` — **second wins** — from element ids read out of
/apply_for_membership. Believing the first function was the whole payload is what
let #420 live: the two values carrying money sat in the other half. Nothing has ever checked that those ids exist, so a field
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


# Both halves of the submitted payload. `getAllFormData()` merges them in this
# order and the second one WINS, so guarding only the first left the two values
# that carry money — the payment method and the contribution amount —
# unguarded. That is where #420 lived.
COLLECTOR_FUNCTIONS = ("collectFormDataDirectly", "getAdditionalFormData")


def parse_collector_fields():
    """Map each payload field of the collector functions to the ids it reads.

    Keyed by field rather than by id because several fields read a fallback
    chain (`$('#a').val() || $('#b').val()`); such a field is only broken when
    *none* of its ids resolve.

    A field appearing in both functions has its ids unioned here, which does NOT
    match runtime — `Object.assign` makes `getAdditionalFormData` the sole source
    for such a field, so a union could report healthy while the page transmits ''.
    `test_no_field_is_declared_by_both_collectors` keeps that set empty, which is
    what makes the union safe.
    """
    fields = {}
    for function_name in COLLECTOR_FUNCTIONS:
        for name, ids in _parse_one(function_name).items():
            fields.setdefault(name, []).extend(ids)
    return {name: sorted(set(ids)) for name, ids in fields.items() if ids}


def _parse_one(function_name):
    source = COLLECTOR_JS.read_text(encoding="utf-8")
    start = source.find("\t%s() {" % function_name)
    if start == -1:
        # str.index would raise with the whole 4500-line file in the message.
        raise AssertionError(
            f"{function_name}() not found in {COLLECTOR_JS.name}. If it was renamed "
            "or moved, point this parser at its new home — do not delete the guard."
        )
    literal = source.find("return {", start)
    end = source.find("\n\t}\n", literal)
    if literal == -1 or end == -1:
        raise AssertionError(
            f"{function_name}() no longer returns a single object literal; this "
            "parser needs updating to match."
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

    return fields


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
        # A field only getAdditionalFormData declares — proves the second half is
        # parsed. Without this, dropping it from COLLECTOR_FUNCTIONS is silent.
        self.assertIn("selected_dues_schedule", self.fields)
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

    def test_no_field_is_declared_by_both_collectors(self):
        """Union-merging ids across the two functions is only safe while this holds.

        At runtime the second function wins outright. If a field ever read an id in
        both, and only the first one resolved, `_broken()` would call it healthy
        while the page transmitted ''.
        """
        both = sorted(
            set(_parse_one("collectFormDataDirectly")) & set(_parse_one("getAdditionalFormData"))
        )
        overlapping_ids = [
            name
            for name in both
            if _parse_one("collectFormDataDirectly")[name] and _parse_one("getAdditionalFormData")[name]
        ]

        self.assertEqual(
            overlapping_ids,
            [],
            "these fields read ids in both collectors; the union in "
            "parse_collector_fields() can now mask a break in the losing one: "
            + ", ".join(overlapping_ids),
        )

    def test_each_collector_is_defined_exactly_once(self):
        """`_parse_one` takes the FIRST match, and this file has duplicate method
        names across its classes (`getData` x6, `bindPaymentEvents` x2). A second
        definition of a collector would silently shadow the guard."""
        source = COLLECTOR_JS.read_text(encoding="utf-8")

        for function_name in COLLECTOR_FUNCTIONS:
            with self.subTest(function=function_name):
                self.assertEqual(source.count("\t%s() {" % function_name), 1)

    def test_the_baseline_names_only_fields_that_still_exist(self):
        """Guards against a rename leaving a dead entry behind."""
        unknown = sorted(self.baseline - set(self.fields))

        self.assertEqual(
            unknown,
            [],
            f"{BASELINE.name} names payload fields the collectors no longer have: "
            + ", ".join(unknown),
        )

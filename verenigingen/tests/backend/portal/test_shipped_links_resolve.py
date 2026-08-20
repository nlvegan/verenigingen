"""Ratchet: links this app ships must point at routes this app serves.

`fixtures/custom_html_block.json` carries the admin "Page Links" block — a
directory of every portal and tool page. Because it is a **fixture** it
re-imports on every `bench migrate`, so a link corrected in the desk is undone
by the next deploy: the file is the source of truth whether anyone treats it
that way or not.

Nothing has ever checked those links resolve. Eight were already dead when this
guard was written, and deleting a page is exactly the moment a ninth is created
— which is how this file came to exist, alongside the removal of the
`/membership_application` page whose submit endpoint had never existed.
"""

import json
import re
from pathlib import Path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

APP_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = APP_ROOT / "fixtures" / "custom_html_block.json"
BASELINE = Path(__file__).with_name("shipped_dead_links.txt")

# Internal hrefs only: no scheme, no fragment-only or query-only links.
INTERNAL_HREF = re.compile(r'href="(/[^"#?]*)"')


def shipped_links():
    blocks = json.loads(FIXTURE.read_text(encoding="utf-8"))
    links = set()
    for block in blocks:
        links.update(INTERNAL_HREF.findall(block.get("html") or ""))
    return links


def load_baseline():
    entries = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


class TestShippedLinksResolve(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.links = shipped_links()
        self.baseline = load_baseline()

    def _dead(self):
        from frappe.website.path_resolver import PathResolver

        dead = set()
        with self.as_user("Guest"):
            for link in self.links:
                _, renderer = PathResolver(link.strip("/")).resolve()
                if type(renderer).__name__ == "NotFoundPage":
                    dead.add(link)
        return dead

    def test_the_fixture_is_still_being_read(self):
        """Control. A regex that matches nothing would pass every other test here."""
        self.assertGreaterEqual(len(self.links), 40, "no links parsed from the fixture")
        self.assertIn("/apply_for_membership", self.links)

    def test_no_shipped_link_points_at_a_route_that_does_not_exist(self):
        undeclared = sorted(self._dead() - self.baseline)

        self.assertEqual(
            undeclared,
            [],
            "these links are shipped in custom_html_block.json but 404 for the "
            "people who click them: " + ", ".join(undeclared),
        )

    def test_the_baseline_has_not_gone_stale(self):
        """A baselined link that now resolves must leave the baseline."""
        revived = sorted(self.baseline - self._dead())

        self.assertEqual(
            revived,
            [],
            f"these links resolve again; delete them from {BASELINE.name}: " + ", ".join(revived),
        )

    def test_the_baseline_names_only_links_the_fixture_still_ships(self):
        orphaned = sorted(self.baseline - self.links)

        self.assertEqual(
            orphaned,
            [],
            f"{BASELINE.name} names links the fixture no longer contains: " + ", ".join(orphaned),
        )

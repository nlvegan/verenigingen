"""#2039: rows built through the VereningingenTestCase seat helpers must not outlive the test.

``create_test_member`` / ``create_test_volunteer`` delegate to ``CoreTestDataFactory``, which
builds further rows on its own (an auto Chapter + Region for a member with no chapter, a whole
extra Member + Customer when ``create_test_volunteer`` is not given ``member=``) and records
them only on ``factory.created_records``. Nothing drained that list. A test whose body COMMITS
(``MemberManager.request_to_join`` does, after its raw-SQL insert) put those rows beyond the
reach of the per-test rollback, so they stayed on the site for good.

The probe test below runs a throwaway ``VereningingenTestCase`` through the real flow and
compares the row NAMES of the affected doctypes before and after it finishes. It does not count
rows: the site carries thousands, and unrelated writers move the counts.
"""

import io
import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

# Doctypes the probe's seat builds are known to leave behind on develop (measured on
# test_site_9, row-name deltas after one run of the probe). Cost Center is deliberately NOT
# watched: Chapter.after_insert creates one that deleting the Chapter does not remove (nor is the
# Contact Volunteer creation makes for its User removed with it), which is
# a separate defect from the untracked factory rows this file is about.
WATCHED = ("Member", "Customer", "Chapter", "Region", "Volunteer")


def _names():
    return {dt: set(frappe.get_all(dt, pluck="name")) for dt in WATCHED}


class TestSeatHelperRowsAreDrained(unittest.TestCase):
    def _run_probe(self, probe_cls):
        stream = io.StringIO()
        before = _names()
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(probe_cls)
        )
        self.assertTrue(result.wasSuccessful(), stream.getvalue())
        after = _names()
        # setUpClass builds one class-level Chapter that is never tracked (a separate defect);
        # discount it so the probe reports only what the seat helpers left.
        after["Chapter"].discard(getattr(probe_cls, "_test_chapter_name", None))
        return {dt: sorted(after[dt] - before[dt]) for dt in WATCHED if after[dt] - before[dt]}

    def test_seat_plus_request_to_join_leaves_no_rows(self):
        class SeatProbe(VereningingenTestCase):
            def test_seat_then_request_to_join(self):
                chapter = self.create_test_chapter(
                    chapter_name=f"SeatProbe Chapter {frappe.generate_hash(length=6)}"
                )
                applicant = self.create_test_member(email=f"seatprobe.{frappe.generate_hash(length=6)}@test.invalid")
                board_member = self.create_test_member(
                    email=f"seatprobe.board.{frappe.generate_hash(length=6)}@test.invalid"
                )
                # The call shape every seat site uses: `member_name=`, which the core factory
                # does not recognise (it takes `member=`).
                self.create_test_volunteer(member_name=board_member.name)
                result = chapter.member_manager.request_to_join(applicant.name, notify=False)
                self.assertTrue(result["success"], result)

        # The probe is its own control: on develop the same call returns Member, Customer, Chapter
        # and Region rows (red), so an empty result here means the drain reached them.
        leaked = self._run_probe(SeatProbe)
        self.assertEqual(leaked, {}, "seat helpers left committed rows behind")

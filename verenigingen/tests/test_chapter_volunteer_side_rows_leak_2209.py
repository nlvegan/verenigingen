"""#2209: a Chapter's Cost Center/Department and a Volunteer's Account Creation Request/Contact must
not outlive the test that built them.

``Chapter.after_insert`` creates a Cost Center and a Department; creating a Volunteer queues an
Account Creation Request (and a Contact for its User). Deleting the parent removes none of them,
and ``VereningingenTestCase`` only drains what it TRACKED, so a test whose body COMMITS
(``MemberManager.request_to_join`` does) left them on the site for good. Production delete
behaviour is deliberately unchanged (whether a Chapter delete should take its Cost Center is a
product question); the harness drains remove them.

The probe runs a throwaway ``VereningingenTestCase`` and ``EnhancedTestCase`` through the real
flow and compares ROW NAMES before and after. Not counts: the site carries thousands of rows.
"""

import io
import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.region_fixtures import ensure_test_region
from verenigingen.tests.utils.base import VereningingenTestCase

WATCHED_2209 = ("Cost Center", "Department", "Account Creation Request", "Contact")


def _names_2209():
    return {dt: set(frappe.get_all(dt, pluck="name")) for dt in WATCHED_2209}


def _build_chapter_and_volunteer_2209(case):
    """Real flow: chapter, volunteer with its own Member, then a committing production call."""
    chapter = case.create_test_chapter(chapter_name=f"SideRows Chapter {frappe.generate_hash(length=6)}")
    applicant = case.create_test_member(email=f"siderows.{frappe.generate_hash(length=6)}@test.invalid")
    board_member = case.create_test_member(email=f"siderows.board.{frappe.generate_hash(length=6)}@test.invalid")
    case.create_test_volunteer(member_name=board_member.name)
    result = chapter.member_manager.request_to_join(applicant.name, notify=False)
    case.assertTrue(result["success"], result)
    return chapter


def _probe_classes_2209():
    """Built on demand, not at module level: the runner would otherwise also run them bare."""

    class SideRowsProbeBase2209(VereningingenTestCase):
        def test_chapter_and_volunteer_then_commit(self):
            _build_chapter_and_volunteer_2209(self)

    class SideRowsProbeEnhanced2209(EnhancedTestCase):
        def test_chapter_and_volunteer_then_commit(self):
            _build_chapter_and_volunteer_2209(self)

    return SideRowsProbeBase2209, SideRowsProbeEnhanced2209


class TestChapterVolunteerSideRowsAreDrained(unittest.TestCase):
    def _run_probe(self, probe_cls):
        stream = io.StringIO()
        ensure_test_region()
        before = _names_2209()
        # Mock justified: CI has no RQ workers, this bench does. A live worker picks the queued
        # Account Creation Request up within a second, holds its row lock while it creates the User
        # and Contact, and so makes the drain's outcome depend on worker timing. Swallowing the
        # enqueue reproduces CI's worker-free run (the request stays Queued) and nothing else.
        with patch("frappe.enqueue"):
            result = unittest.TextTestRunner(stream=stream, verbosity=0).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(probe_cls)
            )
        self.assertTrue(result.wasSuccessful(), stream.getvalue())
        after = _names_2209()
        leaked = {dt: sorted(after[dt] - before[dt]) for dt in WATCHED_2209 if after[dt] - before[dt]}
        # setUpClass of VereningingenTestCase builds one class-level Chapter that is never tracked
        # (a separate defect, see #2039's probe). Discount that Chapter's own Cost Center and
        # Department so this probe reports only what the PER-TEST rows left.
        class_chapter = getattr(probe_cls, "_test_chapter_name", None)
        if class_chapter:
            for dt in ("Cost Center", "Department"):
                leaked[dt] = [n for n in leaked.get(dt, []) if not n.startswith(f"{class_chapter} - ")]
        return {dt: names for dt, names in leaked.items() if names}

    def test_base_case_leaves_no_chapter_or_volunteer_side_rows(self):
        self.assertEqual(self._run_probe(_probe_classes_2209()[0]), {})

    def test_enhanced_case_leaves_no_chapter_or_volunteer_side_rows(self):
        self.assertEqual(self._run_probe(_probe_classes_2209()[1]), {})


class TestVolunteerContactIsDrained(VereningingenTestCase):
    """The Contact a Volunteer's User gets, which only exists once a worker has run the request.

    Probe shortcut: the Account Creation Request is pointed at the User by ``db.set_value``
    (``created_user``) instead of by a worker processing it, because CI has no worker and a live
    one here would make the outcome depend on timing. The User, its Contact and the Volunteer are real.
    """

    def _make_user_with_contact(self, label):
        email = f"contact2209.{label}.{frappe.generate_hash(length=6)}@test.invalid"
        user = frappe.get_doc(
            {"doctype": "User", "email": email, "first_name": "Contact2209", "send_welcome_email": 0}
        ).insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        # Frappe's User does not make the Contact; the app's account-creation pipeline does.
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Contact2209",
                "user": user.name,
                "email_ids": [{"email_id": email, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Contact", contact.name)
        return user.name, contact.name

    def test_contact_of_the_requests_user_goes_and_an_older_one_stays(self):
        older_user, older_contact = self._make_user_with_contact("older")
        # Mock justified: CI has no RQ worker; keeps the request Queued instead of racing one here.
        with patch("frappe.enqueue"):
            member = self.create_test_member(email=f"contact2209.m.{frappe.generate_hash(length=6)}@test.invalid")
            volunteer = self.create_test_volunteer(member_name=member.name)
            new_user, new_contact = self._make_user_with_contact("new")
        requests = frappe.get_all(
            "Account Creation Request", filters={"source_record": volunteer.name}, pluck="name"
        )
        self.assertTrue(requests, "volunteer creation queued no Account Creation Request")
        # The request names BOTH users: the older one's Contact predates the Volunteer.
        frappe.db.set_value("Account Creation Request", requests[0], "created_user", new_user)
        frappe.db.set_value("Volunteer", volunteer.name, "user", older_user, update_modified=False)

        self._cleanup_document_with_retry({"doctype": "Volunteer", "name": volunteer.name})

        self.assertFalse(frappe.db.exists("Volunteer", volunteer.name))
        self.assertFalse(frappe.db.exists("Account Creation Request", requests[0]))
        self.assertFalse(frappe.db.exists("Contact", new_contact), "the new User's Contact survived")
        self.assertTrue(frappe.db.exists("Contact", older_contact), "a Contact older than the Volunteer was taken")


class TestChapterSideRowsWithoutLinks(VereningingenTestCase):
    """A Department/Cost Center the Chapter no longer points at is still the Chapter's.

    Probe shortcut: the links are blanked by ``db.set_value``, standing in for the stale-object
    save that did it in ``test_member_manager`` (found there, 2026-11-27: a leftover Department
    whose Chapter's ``department`` read empty at delete time).
    """

    def test_unlinked_department_and_cost_center_are_removed_with_the_chapter(self):
        chapter = self.create_test_chapter(chapter_name=f"Unlinked2209 {frappe.generate_hash(length=6)}")
        cost_center, department = frappe.db.get_value("Chapter", chapter.name, ["cost_center", "department"])
        self.assertTrue(cost_center and department, "Chapter.after_insert built no Cost Center/Department")
        frappe.db.set_value("Chapter", chapter.name, {"cost_center": None, "department": None})

        self._cleanup_document_with_retry({"doctype": "Chapter", "name": chapter.name})

        self.assertFalse(frappe.db.exists("Chapter", chapter.name))
        self.assertFalse(frappe.db.exists("Cost Center", cost_center), "unlinked Cost Center survived")
        self.assertFalse(frappe.db.exists("Department", department), "unlinked Department survived")

    def test_class_level_drain_removes_the_side_rows_too(self):
        """The classmethod drain (``_cleanup_tracked_docs``) is a second delete site."""
        chapter = self.create_test_chapter(chapter_name=f"ClassDrain2209 {frappe.generate_hash(length=6)}")
        cost_center, department = frappe.db.get_value("Chapter", chapter.name, ["cost_center", "department"])
        self.assertTrue(cost_center and department)
        saved = list(type(self)._track_created_docs)
        type(self)._track_created_docs = [{"doctype": "Chapter", "name": chapter.name}]
        try:
            type(self)._cleanup_tracked_docs()
        finally:
            type(self)._track_created_docs = saved

        self.assertFalse(frappe.db.exists("Chapter", chapter.name))
        self.assertFalse(frappe.db.exists("Cost Center", cost_center))
        self.assertFalse(frappe.db.exists("Department", department))


class TestChapterSideRowsOverDeletion(VereningingenTestCase):
    """Rows that merely look like a Chapter's must survive its drain (reviewer finding, round 2)."""

    def _settings_company(self):
        from verenigingen.tests.utils.force_delete import _chapter_side_row_company

        return _chapter_side_row_company()

    def _other_company(self, settings_company):
        other = frappe.db.get_value("Company", {"name": ["!=", settings_company]}, "name")
        self.assertTrue(other, "this control needs a second Company on the site")
        return other

    def _department(self, name, company):
        doc = frappe.get_doc(
            {
                "doctype": "Department",
                "department_name": name,
                "parent_department": "All Departments",
                "company": company,
            }
        ).insert()
        self.track_doc("Department", doc.name)
        return doc.name

    def _cost_center(self, name, company):
        parent = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ["in", ["", None]]}
        )
        self.assertTrue(parent, f"no root Cost Center in {company}")
        doc = frappe.get_doc(
            {"doctype": "Cost Center", "cost_center_name": name, "parent_cost_center": parent, "company": company}
        ).insert()
        self.track_doc("Cost Center", doc.name)
        return doc.name

    def _drain_chapter_named(self, chapter_name):
        chapter = self.create_test_chapter(chapter_name=chapter_name)
        self._cleanup_document_with_retry({"doctype": "Chapter", "name": chapter.name})
        self.assertFalse(frappe.db.exists("Chapter", chapter.name))
        return chapter

    def test_same_named_rows_in_another_company_survive(self):
        company = self._settings_company()
        other = self._other_company(company)
        chapter_name = f"Ctl2209 {frappe.generate_hash(length=6)}"
        department = self._department(chapter_name, other)
        cost_center = self._cost_center(f"{chapter_name} - Chapter", other)
        self._drain_chapter_named(chapter_name)
        self.assertTrue(frappe.db.exists("Department", department), "another company's Department was deleted")
        self.assertTrue(frappe.db.exists("Cost Center", cost_center), "another company's Cost Center was deleted")

    def test_same_named_rows_in_another_company_made_after_the_chapter_survive(self):
        """Newer than the Chapter, so only the company scope (not the age check) can spare them."""
        company = self._settings_company()
        other = self._other_company(company)
        chapter_name = f"Newer2209 {frappe.generate_hash(length=6)}"
        chapter = self.create_test_chapter(chapter_name=chapter_name)
        department = self._department(chapter_name, other)
        cost_center = self._cost_center(f"{chapter_name} - Chapter", other)
        self._cleanup_document_with_retry({"doctype": "Chapter", "name": chapter.name})
        self.assertTrue(frappe.db.exists("Department", department), "another company's Department was deleted")
        self.assertTrue(frappe.db.exists("Cost Center", cost_center), "another company's Cost Center was deleted")

    def test_same_company_rows_older_than_the_chapter_survive(self):
        company = self._settings_company()
        chapter_name = f"Older2209 {frappe.generate_hash(length=6)}"
        department = self._department(chapter_name, company)
        cost_center = self._cost_center(f"{chapter_name} - Chapter", company)
        self._drain_chapter_named(chapter_name)
        self.assertTrue(frappe.db.exists("Department", department), "a pre-existing Department was deleted")
        self.assertTrue(frappe.db.exists("Cost Center", cost_center), "a pre-existing Cost Center was deleted")

    def test_a_fixture_department_survives_a_chapter_of_the_same_name(self):
        company = self._settings_company()
        fixture = frappe.db.get_value(
            "Department",
            {"company": company, "is_group": 0, "department_name": ["in", ["Sales", "Accounts", "Marketing"]]},
        )
        self.assertTrue(fixture, "this control needs a standard fixture Department in the settings company")
        fixture_name = frappe.db.get_value("Department", fixture, "department_name")
        self._drain_chapter_named(fixture_name)
        self.assertTrue(frappe.db.exists("Department", fixture), "a standard fixture Department was deleted")

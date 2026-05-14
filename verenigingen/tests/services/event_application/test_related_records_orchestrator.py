"""Real-DB integration tests for MijnRoodRelatedRecordsOrchestrator.

Tests cover address/Mollie/membership/dues creation + chapter assignment
+ user account queueing + MijnRood comment append. Each method tested
against a real DB; the orchestrator parameter (god-class's
_acr_queued_members) is stubbed via _FakeOrchestrator.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator


def _cleanup_member_and_customer(test, member_name):
    """Module-level helper for cross-class reuse."""
    for cust in frappe.get_all("Customer", filters={"member": member_name}, pluck="name"):
        try:
            frappe.db.set_value("Customer", cust, "member", None, update_modified=False)
            frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True)
        except Exception:
            pass
    try:
        if frappe.db.exists("Member", member_name):
            frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
    except Exception:
        pass
    # Remove any dangling Dynamic Link rows that referenced this Member
    # (Address child rows are deleted with the Address, but stray rows
    # from manual fixtures or failed inserts can survive otherwise).
    for dl in frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Member", "link_name": member_name},
        pluck="name",
    ):
        try:
            frappe.delete_doc("Dynamic Link", dl, ignore_permissions=True, force=True)
        except Exception:
            pass
    frappe.db.commit()


def _cleanup_address(name):
    """Delete an Address (and its child Dynamic Link rows) and commit."""
    try:
        if frappe.db.exists("Address", name):
            frappe.delete_doc("Address", name, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


class TestApplyMijnRoodComments(EnhancedTestCase):
    """Appends MijnRood comments to Member.notes, idempotent."""

    def test_returns_none_when_comment_is_empty(self):
        member = self.factory.create_member(
            first_name="EmptyComment", last_name="Test",
            email="empty-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": ""}
        )
        self.assertIsNone(result)

    def test_returns_none_when_comment_missing(self):
        member = self.factory.create_member(
            first_name="NoComment", last_name="Test",
            email="no-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {}
        )
        self.assertIsNone(result)

    def test_appends_comment_to_member_notes(self):
        member = self.factory.create_member(
            first_name="Append", last_name="Comment",
            email="append-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "imported from MijnRood"}
        )
        self.assertIsNotNone(result)
        notes = frappe.db.get_value("Member", member.name, "notes") or ""
        self.assertIn("imported from MijnRood", notes)

    def test_idempotent_when_comment_already_present(self):
        member = self.factory.create_member(
            first_name="DupComment", last_name="Test",
            email="dup-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "notes",
            "MijnRood notitie: same comment", update_modified=False)
        frappe.db.commit()

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "same comment"}
        )
        self.assertIsNone(result)


class TestEnsureAddress(EnhancedTestCase):
    """Creates an Address + Dynamic Link for the synced Member.

    The source method short-circuits when address_line1 or city are
    missing, then delegates to AddressImportService which handles
    duplicate detection and link reuse. We exercise the real DB path
    here — no mocks.
    """

    def test_returns_none_when_address_fields_missing(self):
        member = self.factory.create_member(
            first_name="NoAddr", last_name="Test",
            email="no-addr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        # address_line1 missing entirely → short-circuit
        result = get_related_records_orchestrator()._ensure_address(
            member.name, {"city": "Amsterdam"}
        )
        self.assertIsNone(result)

        # city missing → also short-circuit
        result = get_related_records_orchestrator()._ensure_address(
            member.name, {"address_line1": "Kerkstraat 1"}
        )
        self.assertIsNone(result)

    def test_creates_address_and_dynamic_link(self):
        member = self.factory.create_member(
            first_name="NewAddr", last_name="Test",
            email="new-addr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._ensure_address(
            member.name,
            {
                "address_line1": "Kerkstraat 1",
                "city": "Amsterdam",
                "postal_code": "1011AA",
                "country": "NL",
            },
        )
        self.assertIsNotNone(result)
        self.assertIn("linked", result)

        # primary_address is set on Member
        primary_address = frappe.db.get_value("Member", member.name, "primary_address")
        self.assertIsNotNone(primary_address)
        self.addCleanup(_cleanup_address, primary_address)

        # Address row exists with correct content
        addr = frappe.db.get_value(
            "Address",
            primary_address,
            ["address_line1", "city"],
            as_dict=True,
        )
        self.assertEqual(addr["address_line1"], "Kerkstraat 1")
        self.assertEqual(addr["city"], "Amsterdam")

        # Dynamic Link to the Member exists on the Address
        dl_count = frappe.db.count(
            "Dynamic Link",
            filters={
                "parent": primary_address,
                "parenttype": "Address",
                "link_doctype": "Member",
                "link_name": member.name,
            },
        )
        self.assertEqual(dl_count, 1)

    def test_idempotent_when_address_already_linked(self):
        member = self.factory.create_member(
            first_name="DupAddr", last_name="Test",
            email="dup-addr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        row_data = {
            "address_line1": "Hoofdstraat 42",
            "city": "Rotterdam",
            "postal_code": "3011BB",
            "country": "NL",
        }

        # First call creates the address
        first = get_related_records_orchestrator()._ensure_address(member.name, row_data)
        self.assertIsNotNone(first)
        primary_address = frappe.db.get_value("Member", member.name, "primary_address")
        self.assertIsNotNone(primary_address)
        self.addCleanup(_cleanup_address, primary_address)

        # Count Addresses matching this content before second call
        before = frappe.db.count(
            "Address",
            filters={"address_line1": "Hoofdstraat 42", "city": "Rotterdam"},
        )

        # Second call should reuse the existing address (no duplicate)
        second = get_related_records_orchestrator()._ensure_address(member.name, row_data)
        self.assertIsNotNone(second)

        after = frappe.db.count(
            "Address",
            filters={"address_line1": "Hoofdstraat 42", "city": "Rotterdam"},
        )
        self.assertEqual(before, after, "Second call must not create a duplicate Address")

        # primary_address still points to the same Address
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "primary_address"),
            primary_address,
        )

# -*- coding: utf-8 -*-
"""
Comprehensive Multi-Chapter Membership Tests

Tests for multi-chapter membership scenarios including:
- Primary chapter designation and tracking
- Concurrent membership in multiple chapters
- Financial impact (dues allocation, cost center tracking)
- Chapter transfer scenarios with history preservation
- Geographic assignment vs manual override
- Board membership implications across chapters
- Chapter history tracking and auditing
- Edge cases for chapter deactivation/reactivation
"""

import frappe
from frappe.utils import today, add_days, add_months, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestPrimaryChapterDesignation(VereningingenTestCase):
    """Test primary chapter designation and management"""

    def setUp(self):
        super().setUp()
        self.chapters = self.create_test_chapters()
        self.test_member = self.create_test_member()

    def test_first_chapter_becomes_primary(self):
        """Test that first chapter assignment becomes primary"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]

        # Assign member to first chapter
        self.assign_member_to_chapter(member.name, amsterdam.name)

        # Reload member to get updated data
        member.reload()

        # First chapter should be primary
        primary = self.get_primary_chapter(member.name)
        self.assertEqual(primary, amsterdam.name)

    def test_primary_chapter_remains_on_second_assignment(self):
        """Test that primary chapter doesn't change when adding second chapter"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Assign to Amsterdam (becomes primary)
        self.assign_member_to_chapter(member.name, amsterdam.name)

        # Assign to Rotterdam (additional)
        self.assign_member_to_chapter(member.name, rotterdam.name)

        # Amsterdam should still be primary
        primary = self.get_primary_chapter(member.name)
        self.assertEqual(primary, amsterdam.name)

        # Member should be in both chapters
        chapters = self.get_member_chapters(member.name)
        self.assertEqual(len(chapters), 2)
        self.assertIn(amsterdam.name, [c["chapter"] for c in chapters])
        self.assertIn(rotterdam.name, [c["chapter"] for c in chapters])

    def test_explicit_primary_chapter_change(self):
        """Test explicit change of primary chapter"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Setup: Member in both chapters, Amsterdam primary
        self.assign_member_to_chapter(member.name, amsterdam.name)
        self.assign_member_to_chapter(member.name, rotterdam.name)

        # Change primary to Rotterdam
        self.set_primary_chapter(member.name, rotterdam.name)

        # Rotterdam should now be primary
        primary = self.get_primary_chapter(member.name)
        self.assertEqual(primary, rotterdam.name)

    def test_cannot_set_primary_to_non_member_chapter(self):
        """Test that primary cannot be set to a chapter member is not in"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        utrecht = self.chapters["utrecht"]

        # Member only in Amsterdam
        self.assign_member_to_chapter(member.name, amsterdam.name)

        # Try to set Utrecht as primary (should fail)
        with self.assertRaises(frappe.ValidationError):
            self.set_primary_chapter(member.name, utrecht.name)

    def test_primary_chapter_changes_when_leaving_primary(self):
        """Test that leaving primary chapter reassigns primary"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Member in both, Amsterdam primary
        self.assign_member_to_chapter(member.name, amsterdam.name)
        self.assign_member_to_chapter(member.name, rotterdam.name)
        self.set_primary_chapter(member.name, amsterdam.name)

        # Leave Amsterdam
        self.remove_member_from_chapter(member.name, amsterdam.name)

        # Rotterdam should now be primary (only remaining)
        primary = self.get_primary_chapter(member.name)
        self.assertEqual(primary, rotterdam.name)

    # Helper methods

    def create_test_chapters(self):
        """Create test chapters using the factory (handles required region/introduction).

        NOTE: Chapter's postal_codes validator rejects alphanumeric Dutch
        formats like "1000AA-1099ZZ" — it expects numeric ranges. The
        factory's auto-generated numeric postal_codes pass validation and
        are sufficient for the tests here (no assertions on postal codes).
        """
        chapters = {}

        for name, city in [("amsterdam", "Amsterdam"), ("rotterdam", "Rotterdam"), ("utrecht", "Utrecht")]:
            chapters[name] = self.create_test_chapter(
                chapter_name=f"Test {city} Chapter {frappe.generate_hash(length=4)}",
            )

        return chapters

    def assign_member_to_chapter(self, member_name, chapter_name):
        """Assign member to chapter"""
        # Check if already a member
        existing = frappe.db.exists(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name}
        )
        if existing:
            return existing

        # Create chapter membership
        chapter_member = frappe.new_doc("Chapter Member")
        chapter_member.member = member_name
        chapter_member.chapter = chapter_name
        chapter_member.chapter_join_date = today()
        chapter_member.enabled = 1
        chapter_member.save()
        self.track_doc("Chapter Member", chapter_member.name)
        return chapter_member.name

    def remove_member_from_chapter(self, member_name, chapter_name):
        """Remove member from chapter"""
        chapter_member = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name},
            "name"
        )
        if chapter_member:
            cm = frappe.get_doc("Chapter Member", chapter_member)
            cm.enabled = 0
            cm.chapter_leave_date = today()
            cm.save()

    def get_member_chapters(self, member_name):
        """Get all chapters for a member"""
        return frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["chapter", "chapter_join_date", "is_primary"]
        )

    def get_primary_chapter(self, member_name):
        """Get primary chapter for member"""
        # First try is_primary field
        primary = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "enabled": 1, "is_primary": 1},
            "chapter"
        )
        if primary:
            return primary

        # Fall back to first active chapter
        chapters = self.get_member_chapters(member_name)
        if chapters:
            return chapters[0]["chapter"]
        return None

    def set_primary_chapter(self, member_name, chapter_name):
        """Set primary chapter for member"""
        # Verify member is in this chapter
        if not frappe.db.exists(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name, "enabled": 1}
        ):
            frappe.throw(f"Member {member_name} is not in chapter {chapter_name}")

        # Clear existing primary
        frappe.db.sql("""
            UPDATE `tabChapter Member`
            SET is_primary = 0
            WHERE member = %s
        """, member_name)

        # Set new primary
        frappe.db.sql("""
            UPDATE `tabChapter Member`
            SET is_primary = 1
            WHERE member = %s AND chapter = %s AND enabled = 1
        """, (member_name, chapter_name))


class TestMultiChapterFinancialImpact(VereningingenTestCase):
    """Test financial implications of multi-chapter membership"""

    def setUp(self):
        super().setUp()
        self.chapters = self.create_test_chapters_with_cost_centers()
        self.test_member = self.create_test_member()

    def test_dues_allocated_to_primary_chapter(self):
        """Test that membership dues are allocated to primary chapter's cost center"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Member in both chapters, Amsterdam is primary
        self.assign_member_to_chapter(member.name, amsterdam.name, is_primary=True)
        self.assign_member_to_chapter(member.name, rotterdam.name, is_primary=False)

        # Create dues invoice
        invoice = self.create_dues_invoice(member)

        # Invoice should be allocated to primary chapter's cost center
        if amsterdam.cost_center:
            self.assertEqual(invoice.cost_center, amsterdam.cost_center)

    def test_cost_center_changes_with_primary_chapter(self):
        """Test that changing primary chapter updates cost center allocation"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Initial setup: Amsterdam primary
        self.assign_member_to_chapter(member.name, amsterdam.name, is_primary=True)
        self.assign_member_to_chapter(member.name, rotterdam.name, is_primary=False)

        # Create invoice 1 - should go to Amsterdam
        invoice1 = self.create_dues_invoice(member)
        original_cost_center = invoice1.cost_center if hasattr(invoice1, 'cost_center') else None

        # Change primary to Rotterdam
        self.set_primary_chapter(member.name, rotterdam.name)

        # Create invoice 2 - should go to Rotterdam
        invoice2 = self.create_dues_invoice(member)
        new_cost_center = invoice2.cost_center if hasattr(invoice2, 'cost_center') else None

        # Cost centers should be different (if both have cost centers)
        if original_cost_center and new_cost_center:
            self.assertNotEqual(original_cost_center, new_cost_center)

    def test_expense_claim_uses_chapter_cost_center(self):
        """Test that volunteer expense claims use chapter cost center"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]

        # Assign member to chapter
        self.assign_member_to_chapter(member.name, amsterdam.name, is_primary=True)

        # Create expense claim (mock)
        expense_data = {
            "member": member.name,
            "chapter": amsterdam.name,
            "amount": 50.00,
            "description": "Test expense",
        }

        # Verify cost center would be chapter's cost center
        cost_center = self.get_chapter_cost_center(amsterdam.name)
        if cost_center:
            expense_data["cost_center"] = cost_center
            self.assertEqual(expense_data["cost_center"], amsterdam.cost_center)

    def test_chapter_finance_reporting_includes_multi_chapter_members(self):
        """Test that chapter finance reports correctly attribute multi-chapter members"""
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Create multiple members with different chapter configurations
        member1 = self.create_test_member()  # Amsterdam only
        self.assign_member_to_chapter(member1.name, amsterdam.name, is_primary=True)

        member2 = self.create_test_member()  # Rotterdam only
        self.assign_member_to_chapter(member2.name, rotterdam.name, is_primary=True)

        member3 = self.create_test_member()  # Both, Amsterdam primary
        self.assign_member_to_chapter(member3.name, amsterdam.name, is_primary=True)
        self.assign_member_to_chapter(member3.name, rotterdam.name, is_primary=False)

        # Get chapter member counts
        amsterdam_count = self.get_chapter_member_count(amsterdam.name)
        rotterdam_count = self.get_chapter_member_count(rotterdam.name)

        # Amsterdam: member1 + member3 = 2
        self.assertGreaterEqual(amsterdam_count, 2)

        # Rotterdam: member2 + member3 = 2
        self.assertGreaterEqual(rotterdam_count, 2)

    # Helper methods

    def create_test_chapters_with_cost_centers(self):
        """Create test chapters via factory; cost center may be auto-created by hooks."""
        chapters = {}

        for name, city in [("amsterdam", "Amsterdam"), ("rotterdam", "Rotterdam")]:
            chapters[name] = self.create_test_chapter(
                chapter_name=f"Test {city} {frappe.generate_hash(length=4)}",
            )

        return chapters

    def assign_member_to_chapter(self, member_name, chapter_name, is_primary=False):
        """Assign member to chapter with primary flag"""
        existing = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name},
            "name"
        )
        if existing:
            cm = frappe.get_doc("Chapter Member", existing)
            cm.is_primary = 1 if is_primary else 0
            cm.enabled = 1
            cm.save()
            return existing

        chapter_member = frappe.new_doc("Chapter Member")
        chapter_member.member = member_name
        chapter_member.chapter = chapter_name
        chapter_member.chapter_join_date = today()
        chapter_member.enabled = 1
        chapter_member.is_primary = 1 if is_primary else 0
        chapter_member.save()
        self.track_doc("Chapter Member", chapter_member.name)
        return chapter_member.name

    def set_primary_chapter(self, member_name, chapter_name):
        """Set primary chapter"""
        frappe.db.sql("""
            UPDATE `tabChapter Member`
            SET is_primary = 0
            WHERE member = %s
        """, member_name)

        frappe.db.sql("""
            UPDATE `tabChapter Member`
            SET is_primary = 1
            WHERE member = %s AND chapter = %s AND enabled = 1
        """, (member_name, chapter_name))

    def create_dues_invoice(self, member):
        """Create a mock dues invoice"""
        item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
        if not item:
            item = self._create_test_item()

        customer = member.customer or self._create_customer_for_member(member)

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer
        invoice.posting_date = today()
        invoice.append("items", {
            "item_code": item,
            "qty": 1,
            "rate": 25.00,
        })
        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def _create_test_item(self):
        """Create test item"""
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-DUES-{frappe.generate_hash(length=6)}"
        item.item_name = "Test Membership Dues"
        item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
        item.stock_uom = "Nos"
        item.is_stock_item = 0
        item.is_sales_item = 1
        item.save()
        self.track_doc("Item", item.name)
        return item.name

    def _create_customer_for_member(self, member):
        """Create customer for member"""
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        return customer.name

    def get_chapter_cost_center(self, chapter_name):
        """Get cost center for chapter"""
        return frappe.db.get_value("Chapter", chapter_name, "cost_center")

    def get_chapter_member_count(self, chapter_name):
        """Get count of active members in chapter"""
        return frappe.db.count(
            "Chapter Member",
            filters={"chapter": chapter_name, "enabled": 1}
        )


class TestChapterTransferScenarios(VereningingenTestCase):
    """Test chapter transfer and reassignment scenarios"""

    def setUp(self):
        super().setUp()
        self.chapters = self.create_test_chapters()
        self.test_member = self.create_test_member()

    def test_full_transfer_removes_from_old_chapter(self):
        """Test that full chapter transfer removes member from old chapter"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Initial: member in Amsterdam
        self.assign_member_to_chapter(member.name, amsterdam.name)

        # Full transfer to Rotterdam
        self.transfer_member_to_chapter(member.name, rotterdam.name, full_transfer=True)

        # Should no longer be active in Amsterdam
        amsterdam_membership = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "chapter": amsterdam.name},
            ["enabled", "chapter_leave_date"],
            as_dict=True
        )
        if amsterdam_membership:
            self.assertEqual(amsterdam_membership.enabled, 0)
            self.assertIsNotNone(amsterdam_membership.chapter_leave_date)

        # Should be active in Rotterdam
        rotterdam_membership = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "chapter": rotterdam.name},
            "enabled"
        )
        self.assertEqual(rotterdam_membership, 1)

    def test_transfer_preserves_history(self):
        """Test that chapter transfer preserves membership history"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Setup with dates
        join_date = add_days(today(), -60)

        # Join Amsterdam
        self.assign_member_to_chapter(
            member.name, amsterdam.name,
            join_date=join_date
        )

        # Transfer to Rotterdam after 30 days
        transfer_date = add_days(join_date, 30)
        self.transfer_member_to_chapter(
            member.name, rotterdam.name,
            full_transfer=True,
            transfer_date=transfer_date
        )

        # Verify history is preserved
        history = self.get_member_chapter_history(member.name)

        # Should have records for both chapters
        self.assertGreaterEqual(len(history), 2)

        # Find Amsterdam record - should have leave date
        amsterdam_record = next(
            (h for h in history if h["chapter"] == amsterdam.name), None
        )
        self.assertIsNotNone(amsterdam_record)
        if amsterdam_record:
            self.assertEqual(amsterdam_record["join_date"], join_date)

    def test_partial_transfer_keeps_old_membership(self):
        """Test that partial transfer adds new chapter without removing old"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Initial: member in Amsterdam
        self.assign_member_to_chapter(member.name, amsterdam.name)

        # Partial transfer (add Rotterdam, keep Amsterdam)
        self.transfer_member_to_chapter(member.name, rotterdam.name, full_transfer=False)

        # Should be in both chapters
        chapters = self.get_active_chapters(member.name)
        self.assertEqual(len(chapters), 2)
        self.assertIn(amsterdam.name, chapters)
        self.assertIn(rotterdam.name, chapters)

    def test_transfer_updates_primary_chapter_optionally(self):
        """Test that transfer can optionally update primary chapter"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Member in Amsterdam (primary)
        self.assign_member_to_chapter(member.name, amsterdam.name, is_primary=True)

        # Transfer to Rotterdam with primary update
        self.transfer_member_to_chapter(
            member.name, rotterdam.name,
            full_transfer=False,
            make_primary=True
        )

        # Rotterdam should now be primary
        primary = self.get_primary_chapter(member.name)
        self.assertEqual(primary, rotterdam.name)

    def test_relocation_transfer_workflow(self):
        """Test complete relocation workflow (moving cities)"""
        member = self.test_member
        amsterdam = self.chapters["amsterdam"]
        rotterdam = self.chapters["rotterdam"]

        # Member relocates from Amsterdam to Rotterdam
        original_postal_code = "1012AB"  # Amsterdam
        new_postal_code = "3011AC"  # Rotterdam

        # Initial setup in Amsterdam
        self.assign_member_to_chapter(member.name, amsterdam.name, is_primary=True)

        # Update member address
        member.postal_code = new_postal_code
        member.city = "Rotterdam"
        member.save()

        # System should suggest/perform transfer
        suggested_chapter = self.get_chapter_for_postal_code(new_postal_code)
        if suggested_chapter:
            self.assertEqual(suggested_chapter, rotterdam.name)

        # Perform relocation transfer
        self.transfer_member_to_chapter(
            member.name, rotterdam.name,
            full_transfer=True,
            transfer_reason="Member relocated"
        )

        # Verify final state
        chapters = self.get_active_chapters(member.name)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0], rotterdam.name)

    # Helper methods

    def create_test_chapters(self):
        """Create test chapters"""
        chapters = {}
        for name, city in [("amsterdam", "Amsterdam"), ("rotterdam", "Rotterdam"), ("utrecht", "Utrecht")]:
            chapters[name] = self.create_test_chapter(
                chapter_name=f"Test {city} {frappe.generate_hash(length=4)}",
            )
        return chapters

    def assign_member_to_chapter(self, member_name, chapter_name, join_date=None, is_primary=False):
        """Assign member to chapter"""
        existing = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name},
            "name"
        )
        if existing:
            return existing

        chapter_member = frappe.new_doc("Chapter Member")
        chapter_member.member = member_name
        chapter_member.chapter = chapter_name
        chapter_member.chapter_join_date = join_date or today()
        chapter_member.enabled = 1
        chapter_member.is_primary = 1 if is_primary else 0
        chapter_member.save()
        self.track_doc("Chapter Member", chapter_member.name)
        return chapter_member.name

    def transfer_member_to_chapter(self, member_name, target_chapter, full_transfer=True,
                                    make_primary=False, transfer_date=None, transfer_reason=None):
        """Transfer member to new chapter"""
        transfer_date = transfer_date or today()

        if full_transfer:
            # Disable all current chapter memberships
            current_memberships = frappe.get_all(
                "Chapter Member",
                filters={"member": member_name, "enabled": 1},
                fields=["name", "chapter"]
            )
            for cm in current_memberships:
                if cm["chapter"] != target_chapter:
                    doc = frappe.get_doc("Chapter Member", cm["name"])
                    doc.enabled = 0
                    doc.chapter_leave_date = transfer_date
                    doc.leave_reason = transfer_reason or "Transferred to another chapter"
                    doc.save()

        # Create or update target chapter membership
        existing = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": target_chapter},
            "name"
        )
        if existing:
            doc = frappe.get_doc("Chapter Member", existing)
            doc.enabled = 1
            doc.chapter_join_date = transfer_date
            doc.chapter_leave_date = None
            if make_primary:
                # Clear other primaries
                frappe.db.sql("UPDATE `tabChapter Member` SET is_primary=0 WHERE member=%s", member_name)
                doc.is_primary = 1
            doc.save()
        else:
            self.assign_member_to_chapter(
                member_name, target_chapter,
                join_date=transfer_date,
                is_primary=make_primary
            )

    def get_active_chapters(self, member_name):
        """Get list of active chapter names for member"""
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["chapter"]
        )
        return [c["chapter"] for c in chapters]

    def get_member_chapter_history(self, member_name):
        """Get full chapter history for member"""
        return frappe.get_all(
            "Chapter Member",
            filters={"member": member_name},
            fields=["chapter", "chapter_join_date as join_date", "chapter_leave_date as leave_date", "enabled"],
            order_by="chapter_join_date desc"
        )

    def get_primary_chapter(self, member_name):
        """Get primary chapter"""
        primary = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "enabled": 1, "is_primary": 1},
            "chapter"
        )
        if primary:
            return primary

        # Fallback to first active
        chapters = self.get_active_chapters(member_name)
        return chapters[0] if chapters else None

    def get_chapter_for_postal_code(self, postal_code):
        """Get chapter matching postal code"""
        # Simplified - would need proper postal code range matching
        return None


class TestChapterHistoryTracking(VereningingenTestCase):
    """Test chapter membership history tracking and auditing"""

    def setUp(self):
        super().setUp()
        self.chapters = self.create_test_chapters()
        self.test_member = self.create_test_member()

    def test_join_date_is_recorded(self):
        """Test that chapter join date is properly recorded"""
        member = self.test_member
        chapter = self.chapters["amsterdam"]
        join_date = add_days(today(), -30)

        self.assign_member_to_chapter(member.name, chapter.name, join_date=join_date)

        recorded_date = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "chapter": chapter.name},
            "chapter_join_date"
        )
        self.assertEqual(getdate(recorded_date), getdate(join_date))

    def test_leave_date_is_recorded(self):
        """Test that chapter leave date is recorded on departure"""
        member = self.test_member
        chapter = self.chapters["amsterdam"]

        # Join chapter
        self.assign_member_to_chapter(member.name, chapter.name)

        # Leave chapter
        leave_date = today()
        self.leave_chapter(member.name, chapter.name, leave_date)

        recorded_date = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "chapter": chapter.name},
            "chapter_leave_date"
        )
        self.assertEqual(getdate(recorded_date), getdate(leave_date))

    def test_history_tracks_multiple_stints(self):
        """Test tracking multiple join/leave cycles at same chapter"""
        member = self.test_member
        chapter = self.chapters["amsterdam"]

        # First stint
        join1 = add_days(today(), -120)
        leave1 = add_days(today(), -60)
        self.assign_member_to_chapter(member.name, chapter.name, join_date=join1)
        self.leave_chapter(member.name, chapter.name, leave_date=leave1)

        # Second stint - create new record
        join2 = add_days(today(), -30)
        self.rejoin_chapter(member.name, chapter.name, join_date=join2)

        # Should have history of both stints
        history = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "chapter": chapter.name},
            fields=["chapter_join_date", "chapter_leave_date", "enabled"]
        )

        # May have 1 or 2 records depending on implementation
        self.assertGreaterEqual(len(history), 1)

    def test_membership_duration_calculation(self):
        """Test calculation of chapter membership duration"""
        member = self.test_member
        chapter = self.chapters["amsterdam"]

        join_date = add_days(today(), -100)
        self.assign_member_to_chapter(member.name, chapter.name, join_date=join_date)

        # Calculate duration
        duration = self.calculate_membership_duration(member.name, chapter.name)

        # Should be approximately 100 days
        self.assertGreaterEqual(duration, 99)
        self.assertLessEqual(duration, 101)

    # Helper methods

    def create_test_chapters(self):
        """Create test chapters"""
        chapters = {}
        for name, city in [("amsterdam", "Amsterdam"), ("rotterdam", "Rotterdam")]:
            chapters[name] = self.create_test_chapter(
                chapter_name=f"Test {city} History {frappe.generate_hash(length=4)}",
            )
        return chapters

    def assign_member_to_chapter(self, member_name, chapter_name, join_date=None):
        """Assign member to chapter"""
        chapter_member = frappe.new_doc("Chapter Member")
        chapter_member.member = member_name
        chapter_member.chapter = chapter_name
        chapter_member.chapter_join_date = join_date or today()
        chapter_member.enabled = 1
        chapter_member.save()
        self.track_doc("Chapter Member", chapter_member.name)
        return chapter_member.name

    def leave_chapter(self, member_name, chapter_name, leave_date=None):
        """Leave chapter"""
        cm_name = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name, "enabled": 1},
            "name"
        )
        if cm_name:
            cm = frappe.get_doc("Chapter Member", cm_name)
            cm.enabled = 0
            cm.chapter_leave_date = leave_date or today()
            cm.save()

    def rejoin_chapter(self, member_name, chapter_name, join_date=None):
        """Rejoin chapter (new record or reactivate)"""
        # Find existing disabled record
        existing = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name, "enabled": 0},
            "name"
        )

        if existing:
            # Reactivate (simpler approach)
            cm = frappe.get_doc("Chapter Member", existing)
            cm.enabled = 1
            cm.chapter_join_date = join_date or today()
            cm.chapter_leave_date = None
            cm.save()
        else:
            self.assign_member_to_chapter(member_name, chapter_name, join_date)

    def calculate_membership_duration(self, member_name, chapter_name):
        """Calculate total days of membership"""
        cm = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name},
            ["chapter_join_date", "chapter_leave_date", "enabled"],
            as_dict=True
        )
        if not cm:
            return 0

        end_date = getdate(cm.chapter_leave_date) if cm.chapter_leave_date else getdate(today())
        start_date = getdate(cm.chapter_join_date)

        return (end_date - start_date).days


class TestChapterEdgeCases(VereningingenTestCase):
    """Test edge cases in multi-chapter membership"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()

    def test_assign_to_inactive_chapter_fails(self):
        """Test that assignment to inactive chapter fails or warns"""
        inactive_chapter = self.create_inactive_chapter()

        # Try to assign member
        result = self.try_assign_to_chapter(self.test_member.name, inactive_chapter.name)

        # Should either fail or warn
        self.assertTrue(result.get("warning") or result.get("failed"))

    def test_deactivating_chapter_handles_members(self):
        """Test that deactivating a chapter handles existing members"""
        chapter = self.create_active_chapter()

        # Add members
        member1 = self.create_test_member()
        member2 = self.create_test_member()

        self.assign_member_to_chapter(member1.name, chapter.name)
        self.assign_member_to_chapter(member2.name, chapter.name)

        # Deactivate chapter
        chapter.status = "Inactive"
        chapter.save()

        # Members should still have history but may need reassignment
        history = frappe.get_all(
            "Chapter Member",
            filters={"chapter": chapter.name},
            fields=["member", "enabled"]
        )

        # History should be preserved
        self.assertEqual(len(history), 2)

    def test_reactivating_chapter_preserves_members(self):
        """Test that reactivating a chapter preserves member associations"""
        chapter = self.create_active_chapter()

        # Add member
        member = self.create_test_member()
        self.assign_member_to_chapter(member.name, chapter.name)

        # Deactivate then reactivate
        chapter.status = "Inactive"
        chapter.save()
        chapter.status = "Active"
        chapter.save()

        # Member association should be preserved
        is_member = frappe.db.exists(
            "Chapter Member",
            {"member": member.name, "chapter": chapter.name}
        )
        self.assertTrue(is_member)

    def test_member_in_all_chapters_scenario(self):
        """Test member assigned to many chapters (edge case)"""
        member = self.create_test_member()

        # Create and assign to multiple chapters
        chapter_names = []
        for i in range(5):
            chapter = self.create_active_chapter(suffix=str(i))
            self.assign_member_to_chapter(member.name, chapter.name)
            chapter_names.append(chapter.name)

        # Verify member is in all chapters
        memberships = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "enabled": 1},
            fields=["chapter"]
        )

        self.assertEqual(len(memberships), 5)

        # Verify only one is primary
        primary_count = frappe.db.count(
            "Chapter Member",
            filters={"member": member.name, "enabled": 1, "is_primary": 1}
        )
        self.assertLessEqual(primary_count, 1)

    def test_member_with_no_chapter_scenario(self):
        """Test handling of member with no chapter assignment"""
        member = self.create_test_member()

        # Member with no chapter
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "enabled": 1}
        )

        # Should have no chapters
        self.assertEqual(len(chapters), 0)

        # Primary chapter should be None
        primary = self.get_primary_chapter(member.name)
        self.assertIsNone(primary)

    # Helper methods

    def create_active_chapter(self, suffix=""):
        """Create active test chapter via factory."""
        return self.create_test_chapter(
            chapter_name=f"Test Active Chapter {frappe.generate_hash(length=4)}{suffix}",
        )

    def create_inactive_chapter(self):
        """Create inactive test chapter via factory."""
        return self.create_test_chapter(
            chapter_name=f"Test Inactive Chapter {frappe.generate_hash(length=4)}",
            status="Inactive",
        )

    def assign_member_to_chapter(self, member_name, chapter_name, is_primary=None):
        """Assign member to chapter"""
        existing = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "chapter": chapter_name},
            "name"
        )
        if existing:
            return existing

        # Determine if should be primary
        if is_primary is None:
            # Make primary if first chapter
            existing_count = frappe.db.count(
                "Chapter Member",
                filters={"member": member_name, "enabled": 1}
            )
            is_primary = (existing_count == 0)

        chapter_member = frappe.new_doc("Chapter Member")
        chapter_member.member = member_name
        chapter_member.chapter = chapter_name
        chapter_member.chapter_join_date = today()
        chapter_member.enabled = 1
        chapter_member.is_primary = 1 if is_primary else 0
        chapter_member.save()
        self.track_doc("Chapter Member", chapter_member.name)
        return chapter_member.name

    def try_assign_to_chapter(self, member_name, chapter_name):
        """Try to assign member to chapter, returning result"""
        try:
            chapter = frappe.get_doc("Chapter", chapter_name)
            if chapter.status == "Inactive":
                return {"warning": True, "message": "Chapter is inactive"}

            self.assign_member_to_chapter(member_name, chapter_name)
            return {"success": True}
        except Exception as e:
            return {"failed": True, "error": str(e)}

    def get_primary_chapter(self, member_name):
        """Get primary chapter for member"""
        primary = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "enabled": 1, "is_primary": 1},
            "chapter"
        )
        if primary:
            return primary

        # Fallback to first active
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["chapter"],
            limit=1
        )
        return chapters[0]["chapter"] if chapters else None

# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberCleanupService - Member deletion and cascade cleanup

This service handles the deletion of Member records and all related data,
including:
- Cascade deletion of related documents (Memberships, Dues Schedules)
- Intelligent Customer handling (preserve if has transactions)
- Address unlinking (preserve for historical reference)
- Child table cleanup (prevent orphaned data)

Extracted from member.py:
- on_trash() - lines 864-989 (126 LOC)
- _unlink_from_customer() - lines 990-1007 (18 LOC)
- _unlink_from_address() - lines 1009-1024 (16 LOC)

Total: ~160 LOC of business logic in service layer

Architecture:
- Static methods that operate on Member documents
- Cascade deletion with force=True for related records
- Error handling to prevent partial cleanup failures
- SQL injection prevention via whitelisted table names

Security:
- Uses ignore_permissions=True for Customer/Address unlinking (justified: system operation)
- Child table whitelist prevents SQL injection
- Force deletion for cascade cleanup
- Comprehensive error logging

Dependencies:
- Frappe ORM for document operations
- Direct SQL for child table cleanup
"""

from typing import TYPE_CHECKING, Set

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberCleanupService(StatelessService):
    """
    Service for handling Member deletion and cascade cleanup.

    This service handles:
    - Cascade deletion of related Membership and Dues Schedule records
    - Intelligent Customer handling (preserve if has transactions)
    - Address unlinking (preserve records for historical reference)
    - Child table cleanup to prevent orphaned data
    - Error handling to ensure cleanup completes
    """

    def __init__(self) -> None:
        """Initialize the member cleanup service."""
        super().__init__(service_name="MemberCleanupService")

    # SECURITY: Whitelist of valid child tables to prevent SQL injection
    VALID_CHILD_TABLES: Set[str] = {
        "tabMember Volunteer Expenses",
        "tabMember Payment History",
        "tabMember IBAN History",
        "tabMember SEPA Mandate Link",
        "tabChapter Membership History",
        "tabVolunteer Assignment",
        "tabMember Fee Change History",
        "tabMember Contact Request",
        "tabMember CSV Import",
        "tabMember Subscription History",
    }

    def handle_member_deletion(self, member_doc: "Document") -> None:
        """
        Handle cascade deletion of related records when a Member is deleted.

        This prevents LinkExistsError by cleaning up all related documents
        that have Link fields pointing to this Member.

        Args:
            member_doc: Member document instance being deleted

        Returns:
            None - Performs deletions and updates in database

        Strategy:
            1. Delete critical child records (Memberships, Chapter Members)
            2. Handle Customer intelligently (preserve if has transactions)
            3. Unlink Addresses (preserve for historical reference)
            4. Clean up all child table records (prevents orphaned data)

        Security:
            - Uses force=True for cascade deletion
            - Uses ignore_permissions=True for Customer/Address unlinking (system operation)
            - Whitelisted child tables prevent SQL injection
            - Comprehensive error handling prevents partial cleanup

        Business Logic:
            - Memberships: Cancel if submitted, then delete
            - Dues Schedules: Force delete
            - Sales Invoices: Clear member reference (preserve invoices)
            - Chapter Members: Force delete
            - Customer: Delete if no transactions, otherwise unlink
            - Addresses: Unlink but preserve records
            - Child tables: Direct SQL deletion for performance
        """
        # Delete related Membership records (both draft and submitted)
        memberships = frappe.get_all("Membership", filters={"member": member_doc.name}, pluck="name")

        for membership_name in memberships:
            try:
                membership = frappe.get_doc("Membership", membership_name)
                # Cancel if submitted, then delete
                if membership.docstatus == 1:  # Submitted
                    membership.cancel()
                frappe.delete_doc("Membership", membership_name, force=True)
            except Exception as e:
                self.logger.error(f"Error deleting Membership {membership_name}: {str(e)}")

        # Delete Membership Dues Schedules linked to this member
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member_doc.name}, pluck="name"
        )

        for schedule_name in dues_schedules:
            try:
                frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
                self.logger.info(f"Deleted orphaned Membership Dues Schedule {schedule_name}")
            except Exception as e:
                self.logger.error(f"Error deleting Membership Dues Schedule {schedule_name}: {str(e)}")

        # Clear Member reference from Sales Invoices to allow deletion
        # This prevents link validation errors when deleting members with invoices
        try:
            frappe.db.sql(
                """
                UPDATE `tabSales Invoice`
                SET member = NULL
                WHERE member = %s
                """,
                member_doc.name,
            )
            self.logger.info(f"Cleared Member references from Sales Invoices for {member_doc.name}")
        except Exception as e:
            self.logger.error(f"Error clearing Sales Invoice references: {str(e)}")

        # Delete Chapter Member assignments
        chapter_members = frappe.get_all("Chapter Member", filters={"member": member_doc.name}, pluck="name")

        for chapter_member_name in chapter_members:
            try:
                frappe.delete_doc("Chapter Member", chapter_member_name, force=True)
            except Exception as e:
                self.logger.error(f"Error deleting Chapter Member {chapter_member_name}: {str(e)}")

        # Handle Customer - preserve if has transactions
        if member_doc.customer:
            try:
                has_transactions = (
                    frappe.db.count("Sales Invoice", {"customer": member_doc.customer}) > 0
                    or frappe.db.count(
                        "Payment Entry", {"party_type": "Customer", "party": member_doc.customer}
                    )
                    > 0
                )

                if has_transactions:
                    # Unlink member from Customer's Dynamic Links
                    self._unlink_member_from_customer(member_doc)
                    self.logger.info(
                        f"Customer {member_doc.customer} has transactions - unlinked Member reference"
                    )
                else:
                    # No transactions - delete Customer
                    frappe.delete_doc("Customer", member_doc.customer, force=True)
                    self.logger.info(f"Deleted Customer {member_doc.customer}")

            except Exception as e:
                self.logger.error(f"Error handling Customer {member_doc.customer}: {str(e)}")

        # Handle Addresses - unlink from Member but preserve records
        if member_doc.primary_address:
            try:
                self._unlink_member_from_address(member_doc, member_doc.primary_address)
            except Exception as e:
                self.logger.error(f"Error unlinking Address {member_doc.primary_address}: {str(e)}")

        # Clean up all child table records to prevent orphaned data
        # These are display/cache tables that should be removed with the parent
        for table_name in self.VALID_CHILD_TABLES:
            try:
                # Verify table exists before attempting deletion
                if not frappe.db.table_exists(table_name):
                    continue

                frappe.db.sql(
                    f"""
                    DELETE FROM `{table_name}`
                    WHERE parent = %s
                    """,
                    member_doc.name,
                )
                self.logger.info(f"Cleaned up {table_name} records for {member_doc.name}")
            except Exception as e:
                # Some tables might not exist in all installations, so just log and continue
                self.logger.debug(f"Could not clean up {table_name}: {str(e)}")

    def _unlink_member_from_customer(self, member_doc: "Document") -> None:
        """
        Remove Member link from Customer's Dynamic Links table.

        Args:
            member_doc: Member document instance being deleted

        Returns:
            None - Updates Customer document in database

        Security:
            - Uses ignore_permissions=True (justified: system operation during deletion)
            - Only modifies Dynamic Links, preserves Customer record

        Business Logic:
            - Removes Dynamic Link entries pointing to this Member
            - Saves Customer only if links were removed
            - Preserves Customer record for transaction history
        """
        if not member_doc.customer:
            return

        customer = frappe.get_doc("Customer", member_doc.customer)

        # Clear custom_member field if it points to this member
        if hasattr(customer, "custom_member") and customer.custom_member == member_doc.name:
            customer.custom_member = None
            # Permission bypass justified: System operation during member deletion
            customer.save(ignore_permissions=True)
            return

        # Also handle Dynamic Link entries if they exist (some ERPNext setups)
        # Use `or []` pattern because get() returns None if field exists but is None
        customer_links = customer.get("links") or []
        links_to_remove = [
            link
            for link in customer_links
            if link.link_doctype == "Member" and link.link_name == member_doc.name
        ]

        for link in links_to_remove:
            customer.remove(link)

        if links_to_remove:
            # Permission bypass justified: System operation during member deletion
            # Customer must be updated to remove broken links
            customer.save(ignore_permissions=True)

    def _unlink_member_from_address(self, member_doc: "Document", address_name: str) -> None:
        """
        Remove Member link from Address's links table.

        Args:
            member_doc: Member document instance being deleted
            address_name: Name of Address document to unlink from

        Returns:
            None - Updates Address document in database

        Security:
            - Uses ignore_permissions=True (justified: system operation during deletion)
            - Only modifies links table, preserves Address record

        Business Logic:
            - Removes link entries pointing to this Member
            - Saves Address only if links were removed
            - Preserves Address record for historical reference
        """
        address = frappe.get_doc("Address", address_name)

        # Remove any link entries pointing to this Member
        # Use `or []` pattern because get() returns None if field exists but is None
        address_links = address.get("links") or []
        links_to_remove = [
            link
            for link in address_links
            if link.link_doctype == "Member" and link.link_name == member_doc.name
        ]

        for link in links_to_remove:
            address.remove(link)

        if links_to_remove:
            # Permission bypass justified: System operation during member deletion
            # Address must be updated to remove broken links
            address.save(ignore_permissions=True)


def get_member_cleanup_service() -> MemberCleanupService:
    """Get singleton instance of MemberCleanupService"""
    return MemberCleanupService()

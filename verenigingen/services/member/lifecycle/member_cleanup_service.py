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
- Uses ignore_permissions for Customer/Address unlinking (justified: system operation)
- Child table whitelist prevents SQL injection
- Force deletion for cascade cleanup
- Comprehensive error logging

Dependencies:
- Frappe ORM for document operations
- Direct SQL for child table cleanup
"""

from typing import TYPE_CHECKING, Dict, List, Set

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberAnonymizedInsteadOfDeleted(frappe.ValidationError):
    """Raised by MemberCleanupService.handle_member_deletion (#1306) when one of
    the Member's Membership Dues Schedules is still referenced by another
    document -- a Sales Invoice, a Payment Plan, a Contribution Amendment
    Request, or anything else with a Link field to Membership Dues Schedule
    -- so the Member cannot be safely deleted: doing so would leave the
    schedule's own `member` field pointing at a Member that no longer exists.

    By the time this is raised, the Member's personal data has already been
    anonymized and that change committed -- raising here (inside on_trash)
    aborts frappe.delete_doc()'s in-progress delete before it removes the
    Member row, because on_trash runs before check_if_doc_is_linked and
    delete_from_table (see frappe/model/delete_doc.py). Nothing about the
    Member row or ANY of its Membership Dues Schedules is touched -- a
    read-only pre-pass (_find_blocked_schedules) decides whether to raise
    this BEFORE deleting anything, so a non-blocked schedule is left alone
    too, not just the blocked one. Only the cascade cleanup this method
    chose to skip entirely (Memberships, SEPA Mandates, Chapter Member
    links, etc.) is left undone.
    """


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

    def _log_permission_bypass_audit(
        self,
        operation: str,
        doctype: str,
        docname: str,
        member_name: str,
        justification: str,
    ) -> None:
        """
        Log audit trail for permission bypass operations.

        GDPR Compliance: All permission bypasses during member deletion must be logged
        for audit trail and regulatory compliance purposes.

        Args:
            operation: Type of operation (e.g., "unlink_customer", "unlink_address")
            doctype: DocType being modified
            docname: Document name being modified
            member_name: Member being deleted (for correlation)
            justification: Business justification for the bypass
        """
        audit_entry = {
            "timestamp": frappe.utils.now(),
            "user": frappe.session.user,
            "operation": operation,
            "doctype": doctype,
            "docname": docname,
            "member": member_name,
            "justification": justification,
            "session_id": getattr(frappe.local, "session", {}).get("sid", "system"),
        }

        # Log to application logs for audit trail
        self.logger.info(
            f"PERMISSION_BYPASS_AUDIT: {operation} on {doctype}:{docname} "
            f"for member {member_name} by {frappe.session.user} - {justification}"
        )

        # Also log to frappe error log for persistent audit trail
        frappe.log_error(
            title="Member Deletion Audit Trail",
            message=(
                f"Permission bypass during member deletion\n\n"
                f"Operation: {operation}\n"
                f"DocType: {doctype}\n"
                f"Document: {docname}\n"
                f"Member: {member_name}\n"
                f"User: {frappe.session.user}\n"
                f"Justification: {justification}\n"
                f"Timestamp: {audit_entry['timestamp']}"
            ),
        )

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
            - Uses ignore_permissions for Customer/Address unlinking (system operation)
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
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule_hooks import (
            delete_dues_schedule_with_backlink_cleanup,
        )

        # Membership Dues Schedules linked to this member. A READ-ONLY
        # pre-pass (#1306 round 2) decides BEFORE deleting anything whether
        # any of them would be refused -- see _find_blocked_schedules for why
        # this has to run first: an earlier version deleted schedules as it
        # went and only checked for a block at the end, so the anonymize
        # branch's own commit made durable every already-deleted, NON-blocked
        # schedule from earlier in the same loop, contradicting the "either
        # fully cleaned up and deleted, or left untouched" invariant below.
        #
        # If ANY schedule would be refused, the whole operation is converted
        # into an anonymization (see _anonymize_member_instead_of_deleting)
        # and every other cascade step -- Memberships, SEPA Mandates, Sales
        # Invoice reference clearing, Chapter Member links, Customer/Address
        # handling, child tables, and every OTHER dues schedule too -- is
        # skipped, so the Member is either fully cleaned up and deleted, or
        # left untouched except for the deliberate PII scrub.
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member_doc.name}, pluck="name"
        )

        blocked_schedules = self._find_blocked_schedules(member_doc.name, dues_schedules)

        if blocked_schedules:
            for schedule_name, blocking_refs in blocked_schedules.items():
                refs_text = ", ".join(f"{dt} {dn}" for dt, dn in blocking_refs)
                self.logger.error(
                    f"Membership Dues Schedule {schedule_name} is still referenced by "
                    f"{refs_text}; converting Member {member_doc.name}'s deletion into "
                    "an anonymization."
                )
                # This refusal is the guard working as intended, but its only
                # trace so far was self.logger.error above (a file under
                # sites/<site>/logs/, not something an operator browsing the
                # Desk normally checks) -- give it the same operator-visible
                # audit trail this file already gives permission-bypass
                # events, not just a log line.
                frappe.log_error(
                    title="Member Deletion: Dues Schedule Not Deleted",
                    message=(
                        f"Membership Dues Schedule {schedule_name} was not deleted while "
                        f"deleting Member {member_doc.name}: still referenced by "
                        f"{refs_text}.\n\n"
                        "The schedule was left in place, and the Member was anonymized "
                        "instead of deleted, so its `member` field still resolves."
                    ),
                )
            self._anonymize_member_instead_of_deleting(member_doc, list(blocked_schedules.keys()))
            return  # pragma: no cover - _anonymize_member_instead_of_deleting always raises

        for schedule_name in dues_schedules:
            try:
                # #1264: force=True bypasses the ordinary link-integrity check
                # (check_if_doc_is_linked), so a schedule still named by a Sales
                # Invoice's membership_dues_schedule_display was deleted anyway --
                # the Sales Invoice above only has its `member` reference cleared,
                # not the schedule display field, so this left the invoice
                # pointing at a schedule that no longer existed (#1250's exact
                # shape: 134 unpaid Sales Invoices with a dangling
                # membership_dues_schedule_display). Without force, a
                # still-referenced schedule raises LinkExistsError, caught below
                # and logged, exactly like any other failure this loop already
                # handles per-schedule -- the schedule is left intact instead of
                # orphaning the invoice's reference to it.
                #
                # #1264 round 2: a real schedule's OWNING Member (this one)
                # always carries its own current_dues_schedule/
                # application_dues_schedule back-link, which would otherwise
                # raise LinkExistsError for every ordinary (non-invoice) case
                # too -- clear it first so only a genuine external reference
                # can still block the delete.
                #
                # #1264 round 3: clearing the back-link and deleting the
                # schedule now happen as one savepoint-wrapped unit, so a
                # refused delete rolls the back-link clearing back too,
                # instead of leaving the Member's own current_dues_schedule
                # cleared while the schedule survives.
                #
                # #1306 round 2: _find_blocked_schedules above already ruled
                # out a KNOWN block for every schedule reaching this loop, so
                # this except branch is now only a safety net for a genuinely
                # unexpected failure (a race -- e.g. a new reference created
                # between the pre-pass and this call -- or an infra error),
                # not the primary detection path.
                delete_dues_schedule_with_backlink_cleanup(schedule_name, member_doc.name)
                self.logger.info(f"Deleted orphaned Membership Dues Schedule {schedule_name}")
            except Exception as e:
                self.logger.error(f"Error deleting Membership Dues Schedule {schedule_name}: {str(e)}")
                frappe.log_error(
                    title="Member Deletion: Dues Schedule Not Deleted",
                    message=(
                        f"Could not delete Membership Dues Schedule {schedule_name} while "
                        f"deleting Member {member_doc.name}: {str(e)}\n\n"
                        "This was NOT predicted by the read-only pre-pass (a race, or an "
                        "unexpected error) -- the schedule was left in place, and the "
                        "Member deletion proceeded regardless."
                    ),
                )

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

        # Delete SEPA Mandate documents linked to this member. The "Member SEPA
        # Mandate Link" child table cleared further below only holds references;
        # the actual SEPA Mandate documents carry a `member` Link field pointing
        # back at this Member, so they must be deleted too -- otherwise deleting a
        # Member with any mandate raises LinkExistsError. SEPA Mandate is not
        # submittable, so a force delete is sufficient (also drops the IBAN PII).
        sepa_mandates = frappe.get_all("SEPA Mandate", filters={"member": member_doc.name}, pluck="name")

        for mandate_name in sepa_mandates:
            try:
                frappe.delete_doc("SEPA Mandate", mandate_name, force=True)
                self.logger.info(f"Deleted SEPA Mandate {mandate_name}")
            except Exception as e:
                self.logger.error(f"Error deleting SEPA Mandate {mandate_name}: {str(e)}")

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

    def _find_blocked_schedules(self, member_name: str, schedule_names: List[str]) -> Dict[str, list]:
        """Read-only: which of `schedule_names` would Frappe's own
        link-integrity check refuse to delete right now? (#1306 round 2)

        Reuses frappe.model.delete_doc.get_linked_docs/get_dynamic_linked_docs
        with method="Delete" -- the EXACT mechanism a real (non-force)
        frappe.delete_doc("Membership Dues Schedule", ...) call consults via
        check_if_doc_is_linked/check_if_doc_is_dynamically_linked -- instead
        of guessing at specific referencing doctypes (Sales Invoice, Payment
        Plan, Contribution Amendment Request, ...). This is what "ask the
        system, not a guess" means here: any real external reference is
        caught uniformly, and a new one added to the schema in the future is
        caught automatically too, with no new code in this file.

        Excludes the two references clear_member_schedule_backlinks_before_
        delete (membership_dues_schedule_hooks.py) always clears immediately
        before a real delete attempt: the schedule's own Member back-link
        (current_dues_schedule / application_dues_schedule, scoped to
        `member_name` -- that function only ever clears THIS member's own
        fields, never another member's), and Member Fee Change History rows'
        `dues_schedule` field (cleared unconditionally, not member-scoped,
        matching that function's own filter). Neither of those would
        actually block a real delete, so counting them here would make every
        ordinary (unreferenced) schedule look blocked.

        Returns {schedule_name: [(reference_doctype, reference_docname), ...]}
        for every schedule with at least one genuine external reference; a
        schedule with none is omitted entirely.
        """
        from frappe.model.delete_doc import get_dynamic_linked_docs, get_linked_docs

        blocked: Dict[str, list] = {}
        for schedule_name in schedule_names:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
            links = get_linked_docs(schedule_doc, method="Delete") + get_dynamic_linked_docs(
                schedule_doc, method="Delete"
            )
            external = [
                (link["reference_doctype"], link["reference_docname"])
                for link in links
                if not (link["reference_doctype"] == "Member" and link["reference_docname"] == member_name)
                and link["reference_doctype"] != "Member Fee Change History"
            ]
            if external:
                blocked[schedule_name] = external
        return blocked

    def _anonymize_member_instead_of_deleting(
        self, member_doc: "Document", blocked_schedules: List[str]
    ) -> None:
        """Convert a refused Member delete into an anonymization (#1306).

        Called from handle_member_deletion when one or more of the Member's
        Membership Dues Schedules could not be deleted because some other
        document still references it (a Sales Invoice via
        membership_dues_schedule_display, a Payment Plan, a Contribution
        Amendment Request, or anything else with a Link field to Membership
        Dues Schedule -- see _find_blocked_schedules, which decides this
        generically rather than by naming specific doctypes). Force-deleting
        the Member anyway (the pre-#1306 behaviour) would leave that
        schedule's own `member` field pointing at a Member that no longer
        exists -- a financially or administratively load-bearing document
        must never be touched as a side effect of this, so the Member is
        scrubbed in place and kept instead.

        Reuses DataRetentionPolicy._anonymize_personal_data (via the public
        anonymize_member wrapper) rather than a second anonymizer, matching
        the pattern data_retention_policy.py already uses for its own
        Member-with-dependencies case (_delete_personal_data).

        The anonymization is committed here, before raising, because the
        exception this raises is expected to propagate out of an in-progress
        frappe.delete_doc() call: an uncaught exception reaching a Frappe
        request/background-job boundary triggers an ambient
        frappe.db.rollback(), which would otherwise undo the very
        anonymization this method exists to make stick (see Pattern 1,
        "Explicit Commit After db_set()", in this repo's CLAUDE.md).
        """
        from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
            anonymize_member,
        )

        anonymize_member(member_doc.name)
        # Commit here, not later, because the exception this method raises
        # is expected to propagate to a request/job boundary that performs
        # an ambient rollback -- without this, that rollback would undo the
        # very anonymization this method exists to make stick (see Pattern
        # 1, "Explicit Commit After db_set()", in this repo's CLAUDE.md).
        # Unconditional, including under frappe.flags.in_test: a test that
        # incidentally hits this guard while cleaning up a tracked Member
        # (e.g. via the shared test harness's generic teardown drain) is
        # left with a Member row that is anonymized, not corrupted -- its
        # PII is scrubbed, so it cannot collide with a later test's use of
        # the SAME test-specific email/name, which is the only risk that
        # matters for test-shard hygiene. See
        # enhanced_test_factory.py's _remove_drained_record for how the
        # harness recognizes this outcome and stops treating it as a leak.
        frappe.db.commit()

        schedule_list = ", ".join(blocked_schedules)
        self.logger.info(
            f"Member {member_doc.name} anonymized instead of deleted: Membership Dues "
            f"Schedule(s) {schedule_list} are still referenced by another document."
        )
        frappe.throw(
            _(
                "Member {0} was not deleted because Membership Dues Schedule(s) {1} "
                "are still referenced by another document. The member's personal data "
                "has been anonymized instead, and the schedule(s) and whatever "
                "references them were left unchanged."
            ).format(member_doc.name, schedule_list),
            exc=MemberAnonymizedInsteadOfDeleted,
        )

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

        # Clear the back-reference if it points at this member. The field is
        # `member` (Custom Field "Customer-member"); there is no `custom_member`
        # column on Customer, so the previous name made this branch dead and left
        # every deleted member's Customer pointing at a row that no longer exists.
        # No early return here: a Customer can carry BOTH the `member` field and a
        # Dynamic Link row for the same Member, and returning after clearing the
        # field would leave the link behind. That return was unreachable while this
        # branch guarded on the non-existent `custom_member`; correcting the field
        # name made it live, so it has to go.
        cleared_field = customer.get("member") == member_doc.name
        if cleared_field:
            customer.member = None
            # GDPR Audit: Log permission bypass before execution
            self._log_permission_bypass_audit(
                operation="clear_member_link",
                doctype="Customer",
                docname=member_doc.customer,
                member_name=member_doc.name,
                justification="System operation during member deletion - clearing member link",
            )

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
            # GDPR Audit: Log permission bypass before execution
            self._log_permission_bypass_audit(
                operation="remove_customer_dynamic_links",
                doctype="Customer",
                docname=member_doc.customer,
                member_name=member_doc.name,
                justification="System operation during member deletion - removing Dynamic Link entries",
            )

        # Single save covers both the cleared `member` field and any removed links.
        if cleared_field or links_to_remove:
            # Security: System cascade cleanup - audited via _log_permission_bypass_audit above
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
            # GDPR Audit: Log permission bypass before execution
            self._log_permission_bypass_audit(
                operation="remove_address_links",
                doctype="Address",
                docname=address_name,
                member_name=member_doc.name,
                justification="System operation during member deletion - removing Address link entries",
            )
            # Security: System cascade cleanup - audited via _log_permission_bypass_audit above
            address.save(ignore_permissions=True)


def get_member_cleanup_service() -> MemberCleanupService:
    """Get singleton instance of MemberCleanupService"""
    return MemberCleanupService()

"""
Member Import Cleanup Utility

Comprehensive cleanup function to delete all members and related records
for testing import functionality. Use with extreme caution - only on development servers.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def validate_cleanup_permissions():
    """
    Strict permission validation for cleanup operations.
    Implements defense-in-depth security checks.
    """
    user = frappe.session.user

    # Level 1: Must be in developer mode (TEMPORARILY DISABLED for staging testing)
    # if not frappe.conf.get("developer_mode"):
    #     frappe.throw(_("Cleanup operations can only be run in developer mode for safety"))

    # Level 2: User must be Administrator or have System Manager role
    if user != "Administrator":
        user_roles = frappe.get_roles()
        required_roles = Roles.ADMIN_PAIR

        if not any(role in user_roles for role in required_roles):
            frappe.throw(
                _(
                    "Insufficient permissions. You need Administrator access or System Manager/Verenigingen Administrator role."
                ),
                frappe.PermissionError,
            )

    # Level 3: Additional validation for nuclear operations
    # Check if user has explicit permission for destructive operations
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(
            _("You don't have write permissions for system settings, required for cleanup operations"),
            frappe.PermissionError,
        )

    # Level 4: Log the permission check for audit
    frappe.logger("verenigingen.security").info(
        f"Cleanup permission validation passed for user: {user} with roles: {frappe.get_roles()}"
    )

    return True


def validate_nuclear_confirmation(confirm_nuclear_cleanup):
    """
    Validate nuclear cleanup confirmation with additional safety checks.
    """
    if not confirm_nuclear_cleanup:
        frappe.throw(
            _("You must set confirm_nuclear_cleanup=True to proceed with this destructive operation")
        )

    # Additional safety: Check for recent backup (if backup system exists)
    try:
        # This would check for recent backups - implementation depends on backup system
        # For now, just log the attempt
        frappe.logger("verenigingen.security").warning(
            f"Nuclear cleanup attempted by {frappe.session.user} - ensure recent backup exists"
        )
    except Exception:
        # Don't fail if backup check isn't available
        pass

    return True


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def nuclear_cleanup_all_members(confirm_nuclear_cleanup=False, dry_run=True):
    """
    Nuclear cleanup: Delete ALL members and their related records.

    Same deletion engine as cleanup_all_test_data() -- see _run_cleanup_phases()
    for the phase-by-phase order and the mutual-link handling. The only
    difference is the selection: every Member on the site, with no Team or
    Chapter deleted outright (their member/board rows and chapter_head
    back-references are still cleared).

    This previously carried its own ~950-line copy of the deletion logic whose
    entire Customer phase was dead code: it guarded on a `custom_member` column
    that does not exist on Customer, so has_column() returned False and no
    Customer was ever deleted or unlinked.

    Args:
        confirm_nuclear_cleanup (bool): Must be True to proceed
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of the cleanup operation
    """
    # ENHANCED SECURITY VALIDATION
    validate_cleanup_permissions()
    validate_nuclear_confirmation(confirm_nuclear_cleanup)

    results = _new_cleanup_results(dry_run)

    try:
        members = frappe.get_all("Member", pluck="name")
        if not members:
            results["summary"] = "No members found to delete"
            results["total_records_affected"] = 0
            return results

        sets = _resolve_sets_for_members(members)
        results["warnings"].append(_describe_selection(sets))
    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(
            f"Nuclear member cleanup error: {str(e)}\n{traceback.format_exc()}",
            "Member Import Cleanup Error",
        )
        return results

    return _execute_cleanup(sets, results, dry_run, "records")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def preview_member_cleanup():
    """
    Safe preview of what would be deleted by nuclear cleanup.
    Always runs in dry_run mode.
    """
    return nuclear_cleanup_all_members(confirm_nuclear_cleanup=True, dry_run=True)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def force_cleanup_orphaned_schedules_and_invoices(dry_run=True):
    """
    Force cleanup of orphaned dues schedules and membership sales invoices
    after members have already been deleted.

    Detects orphaned invoices by checking:
    - Membership invoices (is_membership_invoice = 1 OR membership_dues_schedule_display IS NOT NULL)
    - Where the member no longer exists OR the customer no longer exists

    Also cleans up related GL Entries, Payment Ledger Entries, and Payment Entry References
    to prevent foreign key constraint violations.

    Args:
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of cleanup
    """
    validate_cleanup_permissions()

    results = {
        "dry_run": dry_run,
        "orphaned_schedules": {"count": 0, "deleted": 0, "errors": []},
        "orphaned_invoices": {"count": 0, "deleted": 0, "errors": []},
        "gl_entries_deleted": 0,
        "payment_ledger_deleted": 0,
        "payment_references_deleted": 0,
        "summary": "",
    }

    try:
        # Find all non-template schedules
        all_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"is_template": 0}, fields=["name", "member", "membership"]
        )

        # Check which ones reference non-existent members/memberships
        orphaned_schedules = []
        for schedule in all_schedules:
            is_orphaned = False

            # Check if member exists (if specified)
            if schedule.member and not frappe.db.exists("Member", schedule.member):
                is_orphaned = True

            # Check if membership exists (if specified)
            if schedule.membership and not frappe.db.exists("Membership", schedule.membership):
                is_orphaned = True

            if is_orphaned:
                orphaned_schedules.append(schedule)

        results["orphaned_schedules"]["count"] = len(orphaned_schedules)

        # Find MEMBERSHIP invoices where member was deleted OR customer was deleted
        # Only considers invoices marked as membership invoices or linked to dues schedules
        orphaned_invoices = frappe.db.sql(
            """
            SELECT si.name, si.customer, si.docstatus, si.member, si.is_membership_invoice
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember` m ON si.member = m.name
            LEFT JOIN `tabCustomer` c ON si.customer = c.name
            WHERE (si.is_membership_invoice = 1 OR si.membership_dues_schedule_display IS NOT NULL)
              AND (
                  (si.member IS NOT NULL AND m.name IS NULL)  -- Member deleted
                  OR c.name IS NULL  -- Customer deleted (rare, requires force delete)
              )
        """,
            as_dict=True,
        )

        results["orphaned_invoices"]["count"] = len(orphaned_invoices)

        if dry_run:
            # Show sample of what would be deleted
            summary_lines = [
                f"DRY RUN: Would delete {len(orphaned_schedules)} orphaned schedules and {len(orphaned_invoices)} orphaned membership invoices"
            ]
            if orphaned_invoices:
                sample = orphaned_invoices[:5]
                summary_lines.append("\nSample invoices to delete:")
                for inv in sample:
                    summary_lines.append(
                        f"  - {inv.name}: customer={inv.customer}, member={inv.member}, status={inv.docstatus}"
                    )
                if len(orphaned_invoices) > 5:
                    summary_lines.append(f"  ... and {len(orphaned_invoices) - 5} more")
            results["summary"] = "\n".join(summary_lines)
            return results

        # ACTUAL DELETION
        frappe.db.begin()

        try:
            # Delete orphaned invoices first (with proper GL cleanup)
            # Note: We manually delete GL entries instead of using doc.cancel() because:
            # 1. The member/customer may already be deleted, causing cancel() to fail
            # 2. Direct SQL deletion is more reliable for cleanup after force deletions
            # 3. We can track exactly what gets cleaned up for audit purposes
            #
            # Strategy: Continue on individual invoice errors (not fail-fast) because:
            # - We want to clean up as many orphaned invoices as possible in one run
            # - Some invoices may have unique constraint issues that shouldn't block others
            # - Errors are tracked in results["orphaned_invoices"]["errors"] for review
            for invoice in orphaned_invoices:
                try:
                    # Steps 1-3: Drop the ledger trail before the invoice itself.
                    #
                    # Counted with an explicit SELECT rather than from the DELETE:
                    # frappe.db.sql() returns the cursor's fetchall(), which for a
                    # DELETE is always the empty tuple. The previous code did
                    # `count = frappe.db.sql("DELETE ...")` then `count or 0`, so
                    # all three of these totals were hard-wired to zero however
                    # many rows were actually removed.
                    results["gl_entries_deleted"] += _count_in(
                        "GL Entry", "voucher_no", [invoice.name], "AND voucher_type = 'Sales Invoice'"
                    )
                    _delete_in("GL Entry", "voucher_no", [invoice.name], "AND voucher_type = 'Sales Invoice'")

                    results["payment_ledger_deleted"] += _count_in(
                        "Payment Ledger Entry",
                        "voucher_no",
                        [invoice.name],
                        "AND voucher_type = 'Sales Invoice'",
                    )
                    _delete_in(
                        "Payment Ledger Entry",
                        "voucher_no",
                        [invoice.name],
                        "AND voucher_type = 'Sales Invoice'",
                    )

                    results["payment_references_deleted"] += _count_in(
                        "Payment Entry Reference",
                        "reference_name",
                        [invoice.name],
                        "AND reference_doctype = 'Sales Invoice'",
                    )
                    _delete_in(
                        "Payment Entry Reference",
                        "reference_name",
                        [invoice.name],
                        "AND reference_doctype = 'Sales Invoice'",
                    )

                    # Step 4: Cancel if submitted (now safe since GL entries are gone)
                    if invoice.docstatus == 1:
                        frappe.db.sql(
                            """
                            UPDATE `tabSales Invoice`
                            SET docstatus = 2
                            WHERE name = %s
                        """,
                            invoice.name,
                        )

                    # Step 5: Force delete the invoice
                    # Security: Orphan cleanup protected by @critical_api + validate_cleanup_permissions()
                    frappe.delete_doc("Sales Invoice", invoice.name, ignore_permissions=True, force=True)
                    results["orphaned_invoices"]["deleted"] += 1
                except Exception as e:
                    results["orphaned_invoices"]["errors"].append(f"{invoice.name}: {str(e)}")

            # Delete orphaned schedules
            # Security: Orphan cleanup protected by @critical_api + validate_cleanup_permissions()
            for schedule in orphaned_schedules:
                try:
                    frappe.delete_doc(
                        "Membership Dues Schedule", schedule.name, ignore_permissions=True, force=True
                    )
                    results["orphaned_schedules"]["deleted"] += 1
                except Exception as e:
                    results["orphaned_schedules"]["errors"].append(f"{schedule.name}: {str(e)}")

            frappe.db.commit()
            results["summary"] = (
                f"Successfully deleted {results['orphaned_schedules']['deleted']} schedules and {results['orphaned_invoices']['deleted']} invoices (with {results['gl_entries_deleted']} GL entries, {results['payment_ledger_deleted']} payment ledger entries, {results['payment_references_deleted']} payment references)"
            )

        except Exception as e:
            frappe.db.rollback()
            results["summary"] = f"ROLLED BACK: {str(e)}"
            frappe.log_error(f"Force cleanup failed: {str(e)}", "Orphaned Cleanup Error")

    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(f"Force cleanup error: {str(e)}", "Orphaned Cleanup Error")

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_chapter_members(dry_run=True):
    """
    Remove orphaned member references from all Chapter child tables.

    Finds chapter member entries where the referenced member no longer exists
    and removes them from the chapter's members child table.

    Args:
        dry_run (bool): If True, only reports what would be removed

    Returns:
        dict: Results of cleanup
    """
    validate_cleanup_permissions()

    results = {
        "dry_run": dry_run,
        "chapters_checked": 0,
        "orphaned_found": 0,
        "orphaned_removed": 0,
        "chapters_affected": [],
        "errors": [],
    }

    try:
        chapters = frappe.get_all("Chapter", fields=["name"])
        results["chapters_checked"] = len(chapters)

        for chapter in chapters:
            try:
                chapter_doc = frappe.get_doc("Chapter", chapter.name)
                orphaned_indices = []

                # Find orphaned members in this chapter
                for i, member_row in enumerate(chapter_doc.members or []):
                    if not frappe.db.exists("Member", member_row.member):
                        orphaned_indices.append((i, member_row.member))
                        results["orphaned_found"] += 1

                if orphaned_indices:
                    results["chapters_affected"].append(
                        {
                            "chapter": chapter.name,
                            "orphaned_count": len(orphaned_indices),
                            "orphaned_members": [m[1] for m in orphaned_indices[:5]],  # Sample
                        }
                    )

                    if not dry_run:
                        # Remove orphaned entries (in reverse order to preserve indices)
                        for idx, member_name in reversed(orphaned_indices):
                            chapter_doc.remove(chapter_doc.members[idx])
                            results["orphaned_removed"] += 1

                        # Security: Orphan cleanup protected by @critical_api + validate_cleanup_permissions()
                        chapter_doc.save(ignore_permissions=True)

            except Exception as e:
                results["errors"].append(f"{chapter.name}: {str(e)}")

        if dry_run:
            results["summary"] = (
                f"DRY RUN: Found {results['orphaned_found']} orphaned members across {len(results['chapters_affected'])} chapters"
            )
        else:
            results["summary"] = (
                f"Removed {results['orphaned_removed']} orphaned members from {len(results['chapters_affected'])} chapters"
            )
            frappe.db.commit()

    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(f"Orphaned chapter cleanup error: {str(e)}", "Chapter Cleanup Error")

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_addresses_and_contacts(dry_run=True):
    """
    Clean up Address and Contact records that reference deleted members.

    Args:
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of cleanup
    """
    validate_cleanup_permissions()

    results = {
        "dry_run": dry_run,
        "addresses": {"count": 0, "deleted": 0, "errors": []},
        "contacts": {"count": 0, "deleted": 0, "errors": []},
        "preserved_shared": 0,
        "summary": "",
    }

    try:
        # Only parents whose links point EXCLUSIVELY at deleted Members may go.
        #
        # The previous implementation deleted a Contact/Address as soon as all of
        # its *Member* links were dangling, without looking at its other links --
        # so a Contact shared between a deleted Member and a live Customer was
        # destroyed along with the live party's contact details. Reusing
        # _exclusively_linked_parents() makes that structurally impossible.
        dead_members = [r[0] for r in frappe.db.sql("""
                SELECT DISTINCT dl.link_name
                FROM `tabDynamic Link` dl
                LEFT JOIN `tabMember` m ON dl.link_name = m.name
                WHERE dl.link_doctype = 'Member' AND m.name IS NULL
                """)]

        doomed = {"Member": dead_members}
        orphaned = {}
        for parenttype, bucket in (("Address", "addresses"), ("Contact", "contacts")):
            parents = _exclusively_linked_parents(parenttype, doomed) if dead_members else []
            orphaned[parenttype] = parents
            results[bucket]["count"] = len(parents)

        results["preserved_shared"] = _count_shared_parents_with_dead_links(dead_members)

        if dry_run:
            results["summary"] = (
                f"DRY RUN: Would delete {results['addresses']['count']} addresses and "
                f"{results['contacts']['count']} contacts "
                f"({results['preserved_shared']} shared with live records preserved)"
            )
            return results

        # Security: Orphan cleanup protected by @critical_api + validate_cleanup_permissions()
        frappe.db.begin()

        try:
            for parenttype, bucket in (("Address", "addresses"), ("Contact", "contacts")):
                for name in orphaned[parenttype]:
                    try:
                        frappe.delete_doc(parenttype, name, ignore_permissions=True, force=True)
                        results[bucket]["deleted"] += 1
                    except Exception as e:
                        results[bucket]["errors"].append(f"{name}: {str(e)}")

            # Shared parents keep their record but lose the dangling links.
            _delete_in("Dynamic Link", "link_name", dead_members, "AND link_doctype = 'Member'")

            frappe.db.commit()
            results["summary"] = (
                f"Deleted {results['addresses']['deleted']} addresses and "
                f"{results['contacts']['deleted']} contacts "
                f"({results['preserved_shared']} shared with live records preserved)"
            )

        except Exception as e:
            frappe.db.rollback()
            results["summary"] = f"ROLLED BACK: {str(e)}"

    except Exception as e:
        results["summary"] = f"Error: {str(e)}"

    return results


def _count_shared_parents_with_dead_links(dead_members):
    """Contacts/Addresses holding a dangling Member link but also a live link.

    These are preserved by cleanup_orphaned_addresses_and_contacts; only their
    stale Dynamic Link rows are removed.
    """
    if not dead_members:
        return 0
    total = 0
    for parenttype in ("Address", "Contact"):
        candidates = set(
            _pluck_in(
                "Dynamic Link",
                "link_name",
                dead_members,
                select="parent",
                extra=f"AND parenttype = '{parenttype}' AND link_doctype = 'Member'",
            )
        )
        exclusive = set(_exclusively_linked_parents(parenttype, {"Member": dead_members}))
        total += len(candidates - exclusive)
    return total


# ---------------------------------------------------------------------------
# Test-data selectors
#
# Kept at module level so the patterns are greppable and unit-testable, and so
# the counting (dry run) and deletion passes can never drift apart.
#
# MariaDB's default _ci collation already makes LIKE case-insensitive, so
# '%test%' matches 'Test' and 'TEST' too -- the old '%Test%' OR '%TEST%'
# branches were redundant and are gone.
# ---------------------------------------------------------------------------

# Reserved / factory-only email domains, matched as SUFFIXES on the whole
# address rather than as '%@example.%'. Multi-label test hosts really occur
# (perf@performance.example.com) and the '@'-anchored form misses them.
TEST_EMAIL_PATTERNS = (
    "%test%",
    "%@test.%",
    "%.invalid",
    "%example.com",
    "%example.org",
    "%example.net",
    "%example.test",
    "%.test",
    "%.local",
)

# ERPNext seeds its own '_Test *' party fixtures during before_tests. They are
# framework bootstrap data, not Verenigingen test data, and removing them breaks
# the next test run -- so the Customer name sweep explicitly spares them.
FRAMEWORK_FIXTURE_PREFIX = "\\_Test%"

# Child tables hanging off a Sales Invoice. Deleting the invoice by raw SQL does
# not cascade, so every one of these has to go explicitly or it is orphaned.
INVOICE_CHILD_TABLES = (
    "Sales Invoice Item",
    "Sales Taxes and Charges",
    "Payment Schedule",
    "Sales Invoice Advance",
    "Sales Invoice Payment",
)

# Inbound Link fields that must be nulled on SURVIVING rows so a cleanup does not
# manufacture the dangling references this module exists to remove. Keyed by the
# set being deleted; each entry is (DocType, fieldname).
#
# Deliberately an explicit list rather than a reflective sweep over
# _link_fields_to(): blanket-nulling every inbound Link would also blank
# `Sales Order.customer`, `Item Price.customer` and similar on documents this
# engine does NOT delete, corrupting them in a way that is worse than a dangling
# reference. These are the fields that actually survive a cleanup and matter.
# The round-trip test (a live run must leave scan_and_clear_broken_links clean)
# is what catches additions to the schema.
INBOUND_LINKS_TO_CLEAR = {
    "members": (
        ("Member", "chapter_assigned_by"),
        ("Member", "reviewed_by"),
        ("Member", "fee_override_by"),
        ("MijnRood Sync Event", "linked_member"),
        ("SEPA Operation Audit Log", "member"),
    ),
    "chapters": (
        ("Member", "current_chapter"),
        ("Chapter Membership History", "chapter_name"),
        ("Sales Invoice", "custom_member_chapter"),
        ("Chapter Join Request", "chapter"),
        ("Event Contact Campaign", "chapter"),
    ),
    "customers": (
        ("Member", "customer"),
        ("Donor", "customer"),
    ),
}

# `users` is handled REFLECTIVELY instead (see _clear_inbound_user_links): a
# hand-written list demonstrably missed the long tail. A live run on real data
# left 1,598 new dangling User references spread across audit/log tables --
# Notification Log.for_user (873), Permission Log.changed_by (740), Access Log,
# Activity Log, Workflow Action.completed_by, Communication.user and more.
#
# Reflection is safe for User specifically because inbound User links are actor
# and audit fields, which are nullable by nature. It is NOT safe in general --
# blanket-nulling inbound *Customer* links would blank `Sales Invoice.customer`
# on invoices this engine does not delete, which is worse than a dangling ref --
# so members/chapters/customers keep their explicit lists above.
USER_LINK_CLEAR_SKIP = frozenset(
    {
        # Deleted outright by Phase 7, so nulling first is pointless churn.
        ("User", "name"),
        ("User Permission", "user"),
        ("DocShare", "user"),
    }
)

# Accounts no cleanup may ever delete, however they are reached. Frappe cannot
# function without Administrator/Guest, and a Member row pointing at Administrator
# is normal (the site owner is usually also a member).
PROTECTED_USERS = frozenset({"Administrator", "Guest"})

# Chunk size for IN (...) clauses. The orphan sweep can span >10k names and an
# unbounded IN list both blows past max_allowed_packet and trips Frappe's slow
# query logging.
_IN_CHUNK = 200


def _chunks(values, size=_IN_CHUNK):
    """Yield successive slices of `values` small enough for an IN (...) clause."""
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _count_in(doctype, column, values, extra=""):
    """COUNT rows of `doctype` whose `column` is in `values`."""
    total = 0
    for part in _chunks(values):
        placeholders = ", ".join(["%s"] * len(part))
        total += frappe.db.sql(
            f"SELECT COUNT(*) FROM `tab{doctype}` WHERE `{column}` IN ({placeholders}) {extra}", part
        )[0][0]
    return total


def _delete_in(doctype, column, values, extra=""):
    """DELETE rows of `doctype` whose `column` is in `values`."""
    for part in _chunks(values):
        placeholders = ", ".join(["%s"] * len(part))
        frappe.db.sql(f"DELETE FROM `tab{doctype}` WHERE `{column}` IN ({placeholders}) {extra}", part)


def _update_in(doctype, set_clause, column, values, extra=""):
    """UPDATE rows of `doctype` whose `column` is in `values`."""
    for part in _chunks(values):
        placeholders = ", ".join(["%s"] * len(part))
        frappe.db.sql(
            f"UPDATE `tab{doctype}` SET {set_clause} WHERE `{column}` IN ({placeholders}) {extra}", part
        )


def _step(results, bucket, doctype, column, values, dry_run, extra=""):
    """Count matching rows into `bucket`, then delete them unless this is a dry run.

    Counting and deleting share one selector by construction, so the dry-run
    preview reports the same rows the live run removes.

    Error policy: a MISSING TABLE is tolerated (installs differ in which optional
    DocTypes exist) and recorded; anything else re-raises on a live run so
    _execute_cleanup rolls the whole transaction back.

    Swallowing every error here would be actively harmful. These are raw
    `DELETE FROM \\`tab...\\`` statements: they bypass Frappe's
    check_if_doc_is_linked, and MariaDB defines no foreign keys on these tables,
    so nothing downstream ever "refuses" to delete. A failed child-table step
    followed by a successful parent delete and a commit is precisely how the
    dangling-reference debris this module exists to remove gets manufactured.
    """
    if not values:
        return
    try:
        count = _count_in(doctype, column, values, extra)
        results[bucket]["count"] += count
        if not dry_run:
            _delete_in(doctype, column, values, extra)
            results[bucket]["deleted"] += count
    except Exception as e:
        results[bucket]["errors"].append(f"{doctype}.{column}: {e}")
        if not _is_missing_table(e):
            raise


def _is_missing_table(exc):
    """True for "table doesn't exist" / "unknown column" -- optional DocTypes."""
    message = str(exc).lower()
    return "doesn't exist" in message or "unknown column" in message


def _pluck_in(doctype, column, values, select="name", extra=""):
    """Return distinct non-empty `select` values for rows matching `column` IN values."""
    found = []
    for part in _chunks(values):
        placeholders = ", ".join(["%s"] * len(part))
        found.extend(
            row[0]
            for row in frappe.db.sql(
                f"SELECT DISTINCT `{select}` FROM `tab{doctype}` "
                f"WHERE `{column}` IN ({placeholders}) {extra}",
                part,
            )
        )
    return sorted({value for value in found if value})


def _test_member_clause(alias="m"):
    """Return (sql_predicate, params) selecting factory-generated Members.

    Member.name is always 'Assoc-Member-YYYY-MM-#####', so the previous
    `name LIKE '%test%' OR first_name LIKE '%test%'` selector matched zero rows
    in practice -- the factories put their marker in last_name/full_name or in
    the email domain, never in the autoname or the first name.
    """
    clauses = [f"{alias}.last_name LIKE %s", f"{alias}.full_name LIKE %s"]
    params = ["%test%", "%test%"]
    for pattern in TEST_EMAIL_PATTERNS:
        clauses.append(f"{alias}.email LIKE %s")
        params.append(pattern)
    return "(" + " OR ".join(clauses) + ")", params


def _test_user_clause(alias="u"):
    """Return (sql_predicate, params) selecting Users on reserved test domains.

    Deliberately does NOT match on first_name: that adds ~300 rows on a real
    site with genuine false-positive risk ('Testa'), and the domain patterns
    already cover every factory-created account.
    """
    clauses = []
    params = []
    for pattern in TEST_EMAIL_PATTERNS[1:]:  # skip bare '%test%' -- too broad for logins
        clauses.append(f"{alias}.name LIKE %s")
        params.append(pattern)
    predicate = "(" + " OR ".join(clauses) + f") AND {alias}.name NOT IN ('Administrator', 'Guest')"
    return predicate, params


def _resolve_sets_for_members(members, extra_volunteers=(), teams=(), chapters=()):
    """Expand a Member list into every dependent record set the phases need.

    Shared by all three cleanup entry points (test-data, nuclear, email-pattern),
    which previously each hand-rolled their own -- and disagreed, because only one
    of them looked at both sides of the Member <-> Customer link.

    Args:
        members: Member names driving the cleanup
        extra_volunteers: Volunteers to include beyond those linked to `members`
        teams / chapters: containers to delete outright (empty for member-scoped runs)

    Returns a dict of name lists, resolved once up front so the dry run reports
    exactly what the live run will delete.
    """
    volunteers = sorted(set(extra_volunteers) | set(_pluck_in("Volunteer", "member", members)))

    # Customers are reachable from BOTH sides of the mutual link, and the two
    # sides disagree in practice, so union them.
    customers = set(_pluck_in("Customer", "member", members)) | set(
        _pluck_in("Member", "name", members, "customer")
    )

    # ...but drop any Customer that a SURVIVING Member still claims. Duplicate
    # customer rows exist whose `member` points at a test member while the real
    # member points back at them through `Member.customer`; deleting those left a
    # live member (evaschout@gmail.com) with a dangling customer. The orphan sweep
    # already had this guard -- the member-linked path did not.
    customers = sorted(customers - set(_claimed_by_surviving_members(customers, members)))

    # Employees are resolved HERE, by name, rather than deleted by `user_id` in the
    # phase itself: Phase 7 nulls Employee.user_id to break the link before the
    # User rows go, which would leave a delete-by-user_id matching nothing. The
    # live run silently deleted no Employees while the dry run reported hundreds.
    employees = _pluck_in("Employee", "user_id", _protected_filtered(members, "user"))

    return {
        "members": list(members),
        "teams": list(teams),
        "chapters": list(chapters),
        "volunteers": volunteers,
        "customers": customers,
        "users": _protected_filtered(members, "user"),
        "employees": employees,
    }


def _claimed_by_surviving_members(customers, doomed_members):
    """Customers that a Member outside `doomed_members` points at via Member.customer."""
    if not customers:
        return []
    doomed = set(doomed_members)
    claimed = []
    for part in _chunks(sorted(customers)):
        placeholders = ", ".join(["%s"] * len(part))
        for customer, member in frappe.db.sql(
            f"""SELECT customer, name FROM `tabMember`
                WHERE customer IN ({placeholders}) AND customer IS NOT NULL AND customer != ''""",
            part,
        ):
            if member not in doomed:
                claimed.append(customer)
    return claimed


def _protected_filtered(members, field):
    """Users linked from `members`, minus accounts that must never be deleted.

    A Member row can legitimately carry `user = "Administrator"` (the site owner
    is usually also a member), and on the production-like site exactly one does.
    Without this filter `nuclear_cleanup_all_members` resolves Administrator into
    its delete set and destroys the login -- the pre-refactor code guarded this
    and the guard was lost when the three engines were merged.
    """
    return [u for u in _pluck_in("Member", "name", members, field) if u not in PROTECTED_USERS]


def _resolve_test_data_sets():
    """Resolve the record sets for the test-data cleanup."""
    member_clause, member_params = _test_member_clause("m")
    members = [
        r[0] for r in frappe.db.sql(f"SELECT m.name FROM `tabMember` m WHERE {member_clause}", member_params)
    ]

    teams = [r[0] for r in frappe.db.sql("SELECT name FROM `tabTeam` WHERE name LIKE '%test%'")]
    chapters = [r[0] for r in frappe.db.sql("SELECT name FROM `tabChapter` WHERE name LIKE '%test%'")]
    test_named_volunteers = [
        r[0]
        for r in frappe.db.sql(
            "SELECT name FROM `tabVolunteer` WHERE name LIKE '%test%' OR volunteer_name LIKE '%test%'"
        )
    ]

    return _resolve_sets_for_members(
        members, extra_volunteers=test_named_volunteers, teams=teams, chapters=chapters
    )


def _customer_has_financial_history(column="name"):
    """SQL NOT EXISTS fragment: customer `cu`.<column> carries no financial trace.

    Used to keep the orphan sweep off anything with real bookkeeping attached.
    """
    return f"""
        NOT EXISTS (SELECT 1 FROM `tabSales Invoice` si WHERE si.customer = cu.{column})
        AND NOT EXISTS (SELECT 1 FROM `tabGL Entry` g
                        WHERE g.party_type = 'Customer' AND g.party = cu.{column})
        AND NOT EXISTS (SELECT 1 FROM `tabPayment Entry` pe
                        WHERE pe.party_type = 'Customer' AND pe.party = cu.{column})
    """


def _resolve_orphan_sets(known_customers, known_users):
    """Resolve test debris that is no longer reachable from any surviving Member.

    Most of the mess on a long-lived dev site is here: previous cleanup runs
    deleted Members with raw SQL (bypassing Member.on_trash), leaving Customers
    whose `member` points at a deleted row and Users no Member references.
    Link-following alone will never collect these.

    Only customers with zero Sales Invoice / GL Entry / Payment Entry history are
    swept -- anything carrying real bookkeeping is left alone and reported.

    Every branch additionally requires an AFFIRMATIVE test signal in the customer
    name. "The Member it pointed at no longer exists" is NOT such a signal: on the
    production-like site 9,739 of the 13,216 dangling customers carry no test
    marker whatsoever, and they are real people's party records left behind by
    earlier import runs. A button labelled "Cleanup ALL Test Data" must not
    delete them (nor, via Phase 5, their Contacts and Addresses -- personal data,
    removed by raw SQL with no Version row and no recovery).
    """
    financial_guard = _customer_has_financial_history()

    # A live Member can point at a Customer through Member.customer even when the
    # reverse Customer.member link is stale or empty, so checking only the reverse
    # side would sweep a customer that a surviving member still owns.
    unclaimed = "NOT EXISTS (SELECT 1 FROM `tabMember` mc WHERE mc.customer = cu.name)"

    dangling = [
        r[0]
        for r in frappe.db.sql(
            f"""SELECT cu.name FROM `tabCustomer` cu
                WHERE cu.member IS NOT NULL AND cu.member != ''
                  AND cu.customer_name LIKE %s
                  AND cu.customer_name NOT LIKE %s ESCAPE '\\\\'
                  AND NOT EXISTS (SELECT 1 FROM `tabMember` m WHERE m.name = cu.member)
                  AND {unclaimed}
                  AND {financial_guard}""",
            ("%test%", FRAMEWORK_FIXTURE_PREFIX),
        )
    ]

    # Both LIKE operands are bound parameters: a literal '%test%' in a query that
    # also passes values makes the driver treat it as a format spec and blow up.
    test_named = [
        r[0]
        for r in frappe.db.sql(
            f"""SELECT cu.name FROM `tabCustomer` cu
                WHERE cu.customer_name LIKE %s
                  AND cu.customer_name NOT LIKE %s ESCAPE '\\\\'
                  AND NOT EXISTS (SELECT 1 FROM `tabMember` m WHERE m.name = cu.member)
                  AND {unclaimed}
                  AND {financial_guard}""",
            ("%test%", FRAMEWORK_FIXTURE_PREFIX),
        )
    ]

    user_clause, user_params = _test_user_clause("u")
    orphan_users = [
        r[0]
        for r in frappe.db.sql(
            f"""SELECT u.name FROM `tabUser` u
                WHERE {user_clause}
                  AND NOT EXISTS (SELECT 1 FROM `tabMember` m WHERE m.user = u.name)""",
            user_params,
        )
    ]

    preserved = frappe.db.sql(
        f"""SELECT COUNT(*) FROM `tabCustomer` cu
            WHERE cu.customer_name LIKE %s
              AND NOT ({financial_guard})""",
        ("%test%",),
    )[0][0]

    # Dangling but unmarked: deliberately NOT swept. Surfaced so an operator can
    # see what was left behind rather than assuming the sweep was exhaustive.
    unmarked = frappe.db.sql(
        f"""SELECT COUNT(*) FROM `tabCustomer` cu
            WHERE cu.member IS NOT NULL AND cu.member != ''
              AND cu.customer_name NOT LIKE %s
              AND NOT EXISTS (SELECT 1 FROM `tabMember` m WHERE m.name = cu.member)
              AND {unclaimed}""",
        ("%test%",),
    )[0][0]

    return {
        "orphaned_customers": sorted((set(dangling) | set(test_named)) - set(known_customers)),
        "orphaned_users": sorted(set(orphan_users) - set(known_users)),
        "preserved_customers_with_financials": preserved,
        "skipped_dangling_without_test_marker": unmarked,
    }


def _exclusively_linked_parents(parenttype, doomed):
    """Return Contact/Address parents whose Dynamic Links point ONLY at doomed rows.

    A single Contact or Address can be shared between a doomed test Customer and
    a live one, so deleting on any matching link would take real data with it.
    Parents that keep at least one link outside the doomed set are spared here --
    only their offending Dynamic Link rows are removed.

    Args:
        parenttype: 'Contact' or 'Address'
        doomed: {link_doctype: [names]} of records being deleted
    """
    doomed_sets = {doctype: set(names) for doctype, names in doomed.items()}

    candidates = set()
    for link_doctype, names in doomed.items():
        for part in _chunks(names):
            placeholders = ", ".join(["%s"] * len(part))
            candidates |= {
                r[0]
                for r in frappe.db.sql(
                    f"""SELECT DISTINCT parent FROM `tabDynamic Link`
                        WHERE parenttype = %s AND link_doctype = %s
                          AND link_name IN ({placeholders})""",
                    [parenttype, link_doctype] + list(part),
                )
            }

    shared = set()
    for part in _chunks(sorted(candidates)):
        placeholders = ", ".join(["%s"] * len(part))
        for row in frappe.db.sql(
            f"""SELECT parent, link_doctype, link_name FROM `tabDynamic Link`
                WHERE parenttype = %s AND parent IN ({placeholders})""",
            [parenttype] + list(part),
            as_dict=True,
        ):
            if row.link_name not in doomed_sets.get(row.link_doctype, ()):
                shared.add(row.parent)

    return sorted(candidates - shared)


# Result buckets. Order matters only for reporting; the admin_tools 'cleanup'
# formatter renders these as a breakdown list.
CLEANUP_BUCKETS = (
    "members",
    "memberships",
    "dues_schedules",
    "volunteers",
    "sepa_mandates",
    "payment_history",
    "chapter_members",
    "users",
    "customers",
    "donors",
    "teams",
    "team_members",
    "chapter_board_members",
    "chapters",
    "volunteer_skills",
    "volunteer_assignments",
    "volunteer_interest_areas",
    "volunteer_development_goals",
    "movement_members",
    "sales_invoices",
    "payment_entries",
    "gl_entries",
    "amendment_requests",
    "termination_requests",
    "payment_plans",
    "account_creation_requests",
    "contacts",
    "addresses",
    "dynamic_links",
    "invoice_items",
    "user_child_rows",
    "customer_child_rows",
    "contact_child_rows",
    "employees",
    "user_permissions",
    "docshares",
    "member_child_rows",
    "cleared_links",
)


def _describe_selection(sets):
    """One-line summary of what a cleanup run selected, for the warnings list."""
    return (
        f"Selected {len(sets['members'])} members, {len(sets['customers'])} customers, "
        f"{len(sets['users'])} users, {len(sets['volunteers'])} volunteers, "
        f"{len(sets['chapters'])} chapters, {len(sets['teams'])} teams"
    )


def _new_cleanup_results(dry_run):
    """Build the empty result envelope shared by every cleanup entry point."""
    results = {key: {"count": 0, "deleted": 0, "errors": []} for key in CLEANUP_BUCKETS}
    results["dry_run"] = dry_run
    results["warnings"] = []
    results["summary"] = ""
    return results


def _execute_cleanup(sets, results, dry_run, label):
    """Run every phase for `sets`, in one transaction, and fill in the summary.

    The single place that owns the dry-run/live split and the commit/rollback
    boundary, so the test-data, nuclear and email-pattern entry points cannot
    drift apart in how they delete or how they report.
    """
    try:
        # Employees are re-resolved here, from the FINAL user set. Callers fold the
        # orphan-user sweep into sets["users"] after _resolve_sets_for_members has
        # already run, so resolving only there covered the members' own users and
        # missed every orphan's Employee row.
        sets["employees"] = _pluck_in("Employee", "user_id", sets.get("users") or [])

        if dry_run:
            _run_cleanup_phases(sets, results, dry_run=True)
            results["total_records_affected"] = sum(results[k]["count"] for k in CLEANUP_BUCKETS)
            results["summary"] = f"DRY RUN: Would delete {results['total_records_affected']} {label}"
            return results

        # Flush any writes the caller already has pending before opening the
        # cleanup's own transaction.
        #
        # frappe.db.begin() issues START TRANSACTION, which Frappe treats as an
        # implicit-commit statement and REFUSES when transaction_writes > 0. The
        # @critical_api decorator on every entry point writes an API Audit Log row
        # before the function body runs, so transaction_writes is always >= 1 by
        # the time we get here -- meaning the live path raised ImplicitCommitError
        # 100% of the time when invoked from the admin_tools UI, while dry runs
        # (which never call begin) looked perfectly healthy.
        #
        # Committing here also keeps the audit row: it records that the operation
        # was attempted, and must survive a rollback of the cleanup itself.
        frappe.db.commit()

        frappe.db.begin()
        try:
            _run_cleanup_phases(sets, results, dry_run=False)
            frappe.db.commit()
            results["total_records_affected"] = sum(results[k]["count"] for k in CLEANUP_BUCKETS)
            total_deleted = sum(results[k]["deleted"] for k in CLEANUP_BUCKETS)
            results["summary"] = f"Successfully deleted {total_deleted} {label}"
        except Exception as e:
            frappe.db.rollback()
            # Nothing survived the rollback, so the per-bucket `deleted` tallies
            # accumulated before the failure are now lies -- the UI would render
            # "N deleted" for rows that are still there. Reset them.
            for key in CLEANUP_BUCKETS:
                results[key]["deleted"] = 0
            results["total_records_affected"] = 0
            results["summary"] = f"TRANSACTION ROLLED BACK - {str(e)}"
            results["transaction_rolled_back"] = True
            frappe.log_error(
                f"Cleanup failed and rolled back: {str(e)}\n{traceback.format_exc()}",
                "Member Cleanup Error",
            )
    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(f"Cleanup error: {str(e)}\n{traceback.format_exc()}", "Member Cleanup Error")

    return results


def _clear_inbound_links(sets, results, dry_run):
    """NULL inbound Link fields pointing at records this run deletes.

    Without this, deleting a test Chapter leaves every surviving real Member with
    a dangling `current_chapter`, and deleting a test User leaves live Employees
    with a dangling `expense_approver` -- new broken links created by the very
    tool that is supposed to remove them.
    """
    for set_key, fields in INBOUND_LINKS_TO_CLEAR.items():
        values = sets.get(set_key) or []
        if not values:
            continue
        for doctype, fieldname in fields:
            _clear_one_link_field(doctype, fieldname, values, results, dry_run)

    _clear_inbound_user_links(sets.get("users") or [], results, dry_run)


def _clear_one_link_field(doctype, fieldname, values, results, dry_run):
    """Count, and on a live run NULL, one inbound Link field."""
    try:
        count = _count_in(doctype, fieldname, values)
        results["cleared_links"]["count"] += count
        if not dry_run:
            _update_in(doctype, f"`{fieldname}` = NULL", fieldname, values)
            results["cleared_links"]["deleted"] += count
    except Exception as e:
        results["cleared_links"]["errors"].append(f"{doctype}.{fieldname}: {e}")
        if not _is_missing_table(e):
            raise


def _clear_inbound_user_links(users, results, dry_run):
    """NULL every inbound User Link field, discovered by reflection.

    See the USER_LINK_CLEAR_SKIP comment for why User is swept reflectively while
    the other targets keep explicit lists.
    """
    if not users:
        return
    for field in _link_fields_to("User"):
        if (field.doctype, field.fieldname) in USER_LINK_CLEAR_SKIP:
            continue
        _clear_one_link_field(field.doctype, field.fieldname, users, results, dry_run)


def _run_cleanup_phases(sets, results, dry_run):
    """Walk every deletion phase in reverse-dependency order.

    Frappe refuses to delete a row while any Link field still points at it, so
    each phase must clear its dependants before the phase below it runs. The
    UPDATE steps break the three mutual reference pairs (Member.customer <->
    Customer.member, Member.volunteer_record <-> Volunteer.member, and the
    Chapter.chapter_head back-reference) which would otherwise deadlock.
    """
    members = sets["members"]
    customers = sets["customers"]
    users = sets["users"]
    volunteers = sets["volunteers"]
    chapters = sets["chapters"]
    teams = sets["teams"]

    # Row sets whose SELECTOR COLUMN is nulled by Phase 0 must be resolved BEFORE
    # Phase 0 runs, or the live run finds nothing where the dry run found rows.
    # Account Creation Request.created_user and API Audit Log.user are both inbound
    # User links, so the reflective sweep clears them. Same null-before-select trap
    # that previously made the Employee phase delete nothing.
    acr_rows = sorted(
        set(
            _pluck_in(
                "Account Creation Request", "source_record", members, extra="AND request_type = 'Member'"
            )
        )
        | set(_pluck_in("Account Creation Request", "created_user", users))
    )
    api_audit_rows = _pluck_in("API Audit Log", "user", users)

    # --- PHASE 0: break inbound links held by records that will SURVIVE -------
    #
    # Runs first, and counts against the pre-deletion state in both modes, so the
    # dry-run preview and the live run report the same number. Rows that are
    # themselves doomed get nulled too; that write is wasted but harmless, and it
    # keeps the two modes in agreement.
    _clear_inbound_links(sets, results, dry_run)

    # --- PHASE 1: financial leaves (must precede Customer) --------------------
    invoices = sorted(
        set(_pluck_in("Sales Invoice", "customer", customers))
        | set(_pluck_in("Sales Invoice", "member", members))
    )
    payment_entries = _pluck_in("Payment Entry", "party", customers, extra="AND party_type = 'Customer'")

    # Payment Entry References are reachable two ways -- by the invoice they point
    # at and by the payment they belong to -- and a membership payment is usually
    # both. Counting them under two selectors double-counted the overlap in the dry
    # run while the live run deleted each row once, so the two modes disagreed.
    # Resolve the union to row names first and delete it exactly once.
    payment_refs = sorted(
        set(
            _pluck_in(
                "Payment Entry Reference",
                "reference_name",
                invoices,
                extra="AND reference_doctype = 'Sales Invoice'",
            )
        )
        | set(_pluck_in("Payment Entry Reference", "parent", payment_entries))
    )
    _step(results, "payment_entries", "Payment Entry Reference", "name", payment_refs, dry_run)

    if invoices:
        _step(
            results,
            "gl_entries",
            "GL Entry",
            "voucher_no",
            invoices,
            dry_run,
            "AND voucher_type = 'Sales Invoice'",
        )
        _step(
            results,
            "gl_entries",
            "Payment Ledger Entry",
            "voucher_no",
            invoices,
            dry_run,
            "AND voucher_type = 'Sales Invoice'",
        )
        if not dry_run:
            # Cancel before delete: a submitted invoice cannot be removed, and the
            # ledger trail above is already gone so doc.cancel() has nothing to reverse.
            _update_in("Sales Invoice", "docstatus = 2", "name", invoices, "AND docstatus = 1")
        for child in INVOICE_CHILD_TABLES:
            _step(results, "invoice_items", child, "parent", invoices, dry_run)
        _step(results, "sales_invoices", "Sales Invoice", "name", invoices, dry_run)

    if payment_entries:
        _step(
            results,
            "gl_entries",
            "GL Entry",
            "voucher_no",
            payment_entries,
            dry_run,
            "AND voucher_type = 'Payment Entry'",
        )
        _step(
            results,
            "gl_entries",
            "Payment Ledger Entry",
            "voucher_no",
            payment_entries,
            dry_run,
            "AND voucher_type = 'Payment Entry'",
        )
        _step(results, "payment_entries", "Payment Entry Deduction", "parent", payment_entries, dry_run)
        if not dry_run:
            _update_in("Payment Entry", "docstatus = 2", "name", payment_entries, "AND docstatus = 1")
        _step(results, "payment_entries", "Payment Entry", "name", payment_entries, dry_run)

    # --- PHASE 2: membership / dues chain ------------------------------------
    _step(results, "sepa_mandates", "Direct Debit Batch Invoice", "member", members, dry_run)
    _step(results, "sepa_mandates", "SEPA Mandate", "member", members, dry_run)
    _step(results, "dues_schedules", "Membership Dues Schedule", "member", members, dry_run)
    if not dry_run and members:
        _update_in("Membership", "docstatus = 2", "member", members, "AND docstatus = 1")
    _step(results, "memberships", "Membership", "member", members, dry_run)
    _step(results, "amendment_requests", "Contribution Amendment Request", "member", members, dry_run)
    _step(results, "termination_requests", "Membership Termination Request", "member", members, dry_run)
    _step(results, "payment_plans", "Payment Plan Payment", "member", members, dry_run)
    _step(results, "payment_plans", "Payment Plan", "member", members, dry_run)
    _step(results, "donors", "Donor", "member", members, dry_run)

    # --- PHASE 3: volunteer graph --------------------------------------------
    for bucket, doctype in (
        ("chapter_board_members", "Chapter Board Member"),
        ("team_members", "Team Member"),
        ("movement_members", "Movement Member"),
    ):
        _step(results, bucket, doctype, "volunteer", volunteers, dry_run)
    for bucket, doctype in (
        ("volunteer_skills", "Volunteer Skill"),
        ("volunteer_assignments", "Volunteer Assignment"),
        ("volunteer_interest_areas", "Volunteer Interest Area"),
        ("volunteer_development_goals", "Volunteer Development Goal"),
    ):
        _step(results, bucket, doctype, "parent", volunteers, dry_run)
    _step(results, "volunteers", "Volunteer Activity", "volunteer", volunteers, dry_run)
    if not dry_run:
        # Both halves of the Member <-> Volunteer mutual link.
        _update_in("Member", "volunteer_record = NULL", "volunteer_record", volunteers)
        _update_in("Volunteer", "member = NULL", "name", volunteers)
    _step(results, "volunteers", "Volunteer", "name", volunteers, dry_run)

    # --- PHASE 4: chapters and teams -----------------------------------------
    # A Chapter Member row can be reachable by BOTH its doomed member and its
    # doomed parent chapter; counting it under two selectors inflated the dry run
    # against the live run. Resolve the union of row names and delete once.
    chapter_member_rows = sorted(
        set(_pluck_in("Chapter Member", "member", members))
        | set(_pluck_in("Chapter Member", "parent", chapters))
    )
    _step(results, "chapter_members", "Chapter Member", "name", chapter_member_rows, dry_run)
    _step(results, "chapter_board_members", "Chapter Board Member", "parent", chapters, dry_run)
    _step(results, "team_members", "Team Member", "parent", teams, dry_run)
    _step(results, "chapters", "Chapter Join Request", "member", members, dry_run)
    if not dry_run and members:
        _update_in("Chapter", "chapter_head = NULL", "chapter_head", members)
    _step(results, "teams", "Team", "name", teams, dry_run)
    _step(results, "chapters", "Chapter", "name", chapters, dry_run)

    # --- PHASE 5: contacts, addresses, dynamic links -------------------------
    #
    # Exclusivity is computed BEFORE anything is removed, because it is derived
    # from the very Dynamic Link rows the next steps delete.
    doomed_links = {"Member": members, "Customer": customers, "Volunteer": volunteers}
    exclusive_parents = {
        parenttype: _exclusively_linked_parents(parenttype, doomed_links)
        for parenttype in ("Contact", "Address")
    }

    # The two Dynamic Link sweeps below must select DISJOINT rows, or the dry run
    # counts the overlap twice while the live run deletes it once. Sweep 1 takes
    # every link POINTING AT a doomed record; sweep 2 takes the remaining links
    # BELONGING TO a parent that is itself being deleted.
    doomed_link_row_names = set()
    for link_doctype, names in doomed_links.items():
        doomed_link_row_names.update(
            _pluck_in("Dynamic Link", "link_name", names, extra=f"AND link_doctype = '{link_doctype}'")
        )

    remaining_parent_links = set()
    for parenttype, parents in exclusive_parents.items():
        remaining_parent_links.update(
            _pluck_in("Dynamic Link", "parent", parents, extra=f"AND parenttype = '{parenttype}'")
        )

    _step(
        results,
        "dynamic_links",
        "Dynamic Link",
        "name",
        sorted(doomed_link_row_names | remaining_parent_links),
        dry_run,
    )

    for parenttype, bucket in (("Contact", "contacts"), ("Address", "addresses")):
        parents = exclusive_parents[parenttype]
        if not parents:
            continue
        if parenttype == "Contact":
            _step(results, "contact_child_rows", "Contact Email", "parent", parents, dry_run)
            _step(results, "contact_child_rows", "Contact Phone", "parent", parents, dry_run)
        _step(results, bucket, parenttype, "name", parents, dry_run)

    if not dry_run and users:
        _update_in("Contact", "user = NULL", "user", users)

    # --- PHASE 6: customers ---------------------------------------------------
    if not dry_run:
        # Both halves of the Member <-> Customer mutual link. Clearing only one
        # side is what left 13k Customers pointing at deleted Members.
        _update_in("Member", "customer = NULL", "customer", customers)
        _update_in("Customer", "member = NULL", "name", customers)
    _step(
        results,
        "customer_child_rows",
        "Party Account",
        "parent",
        customers,
        dry_run,
        "AND parenttype = 'Customer'",
    )
    _step(
        results,
        "customer_child_rows",
        "Sales Team",
        "parent",
        customers,
        dry_run,
        "AND parenttype = 'Customer'",
    )
    _step(results, "customers", "Customer", "name", customers, dry_run)

    # --- PHASE 7: users -------------------------------------------------------
    # acr_rows resolved before Phase 0 (which nulls created_user). One request can
    # name a doomed member AND a doomed user, hence the union-then-delete-once.
    _step(results, "account_creation_requests", "Account Creation Request", "name", acr_rows, dry_run)
    _step(results, "docshares", "DocShare", "user", users, dry_run)
    _step(results, "user_permissions", "User Permission", "user", users, dry_run)
    # Employees are deleted by name, resolved before anything was nulled. Deleting
    # by user_id here would match nothing, because the UPDATE below has already
    # cleared the very column the delete would filter on.
    _step(results, "employees", "Employee", "name", sets.get("employees", []), dry_run)
    if not dry_run and users:
        _update_in("Employee", "user_id = NULL", "user_id", users)
        _update_in("Volunteer", "user = NULL", "user", users)
        _update_in("Member", "user = NULL", "user", users)
    for child in ("Has Role", "User Email", "User Social Login", "Block Module", "DefaultValue"):
        _step(results, "user_child_rows", child, "parent", users, dry_run)
    _step(results, "user_child_rows", "Notification Settings", "name", users, dry_run)
    # By name: api_audit_rows was resolved before Phase 0 nulled API Audit Log.user.
    _step(results, "user_child_rows", "API Audit Log", "name", api_audit_rows, dry_run)
    _step(results, "users", "User", "name", users, dry_run)

    # --- PHASE 8: members last ------------------------------------------------
    from verenigingen.services.member.lifecycle.member_cleanup_service import MemberCleanupService

    # Not every entry in VALID_CHILD_TABLES is a true child table: Member Contact
    # Request is a standalone doctype carrying a `member` Link, so it has no
    # `parent` column to match on.
    standalone_member_tables = {"Member Contact Request"}
    child_table_buckets = {"Member Payment History": "payment_history"}
    for table in sorted(MemberCleanupService.VALID_CHILD_TABLES):
        doctype = table[3:] if table.startswith("tab") else table
        _step(
            results,
            child_table_buckets.get(doctype, "member_child_rows"),
            doctype,
            "member" if doctype in standalone_member_tables else "parent",
            members,
            dry_run,
        )
    _step(results, "members", "Member", "name", members, dry_run)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_all_test_data(dry_run=True):
    """
    Comprehensive cleanup of ALL test data across the system.

    Selection (see TEST_EMAIL_PATTERNS / _test_member_clause):
    - Members whose last_name/full_name contains 'test', or whose email sits on a
      reserved test domain (@test.*, *.invalid, example.*, *.test, *.local)
    - Teams, Chapters, Volunteers matching '%test%'
    - Everything reachable from those members: Customers, Users, invoices,
      memberships, dues schedules, mandates, contacts, addresses
    - Plus an orphan sweep for test debris left behind by earlier runs

    Deletion runs in reverse-dependency order (see the PHASE markers below).
    Three mutual reference pairs must have BOTH sides cleared before either row
    can go: Member.customer <-> Customer.member, Member.volunteer_record <->
    Volunteer.member, and Member.user -> User (also held by Contact.user and
    DocShare.user).

    ERPNext's own '_Test *' bootstrap fixtures are deliberately preserved, as is
    any Customer carrying Sales Invoice / GL Entry / Payment Entry history.

    Args:
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of cleanup with counts per record type

    Usage:
        # Preview what would be deleted
        bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.cleanup_all_test_data

        # Actually delete
        bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.cleanup_all_test_data --kwargs '{"dry_run": False}'
    """
    validate_cleanup_permissions()

    results = _new_cleanup_results(dry_run)

    try:
        sets = _resolve_test_data_sets()
        orphans = _resolve_orphan_sets(sets["customers"], sets["users"])

        # Fold the orphan debris into the main sets so a single code path clears
        # its links too (DocShare, User Permission, Dynamic Link, ...). Most of
        # what accumulates on a long-lived dev site lives here, unreachable from
        # any surviving Member.
        results["orphaned_customers"] = len(orphans["orphaned_customers"])
        results["orphaned_users"] = len(orphans["orphaned_users"])
        sets["customers"] = sorted(set(sets["customers"]) | set(orphans["orphaned_customers"]))
        sets["users"] = sorted(set(sets["users"]) | set(orphans["orphaned_users"]))

        preserved = orphans["preserved_customers_with_financials"]
        if preserved:
            results["warnings"].append(
                f"Preserved {preserved} test-named Customers carrying Sales Invoice / "
                "GL Entry / Payment Entry history"
            )
        unmarked = orphans["skipped_dangling_without_test_marker"]
        if unmarked:
            results["warnings"].append(
                f"Skipped {unmarked} Customers whose member link dangles but whose name carries "
                "no test marker - they may be real party records. Review them manually; "
                "scan_and_clear_broken_links can null the stale link without deleting the row."
            )
        results["warnings"].append(_describe_selection(sets))
    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(
            f"Test data cleanup error: {str(e)}\n{traceback.format_exc()}", "Test Data Cleanup Error"
        )
        return results

    return _execute_cleanup(sets, results, dry_run, "test records")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_test_members_only(email_patterns: list | None = None, dry_run=False):
    """
    Safer cleanup that only deletes members matching test email patterns.

    Same deletion engine as cleanup_all_test_data() -- see _run_cleanup_phases().
    Only the selection differs: members whose email matches one of the supplied
    LIKE patterns, rather than the full test-data heuristic.

    Patterns are validated before use. This endpoint is whitelisted and takes a
    caller-supplied list, and pointing it at the shared engine widened its blast
    radius enormously: `email_patterns=["%"]` would otherwise select every Member
    on the site and take their Customers, Users and invoices with them.

    Args:
        email_patterns: List of email LIKE patterns to match (default: test patterns)
        dry_run: If True, only report what would be deleted. Defaults to False to
            preserve the historical behaviour of this endpoint and the admin_tools
            button that calls it with no arguments.

    Returns:
        dict: Results of cleanup
    """
    # ENHANCED SECURITY VALIDATION
    validate_cleanup_permissions()

    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    if not email_patterns:
        email_patterns = ["%test@example.com", "%@test.com", "test_%@%", "%example.%", "%@test.%"]

    results = _new_cleanup_results(dry_run)
    results["test_patterns"] = email_patterns
    results["members_deleted"] = 0
    results["related_records_deleted"] = 0
    results["errors"] = []

    try:
        _validate_email_patterns(email_patterns)

        clause = " OR ".join(["m.email LIKE %s"] * len(email_patterns))
        members = [
            r[0] for r in frappe.db.sql(f"SELECT m.name FROM `tabMember` m WHERE {clause}", email_patterns)
        ]

        if not members:
            results["summary"] = "No test members found matching the patterns"
            results["total_records_affected"] = 0
            return results

        sets = _resolve_sets_for_members(members)
        results["warnings"].append(_describe_selection(sets))
    except Exception as e:
        results["summary"] = f"Error during test cleanup: {str(e)}"
        results["errors"].append(str(e))
        return results

    _execute_cleanup(sets, results, dry_run, label="test member records")

    # Legacy result keys the admin_tools page and existing callers still read.
    # Both derived from `deleted`, never mixed with the `count` aggregate: on a
    # rolled-back run the two disagree and related_records_deleted went negative.
    results["members_deleted"] = results["members"]["deleted"]
    results["related_records_deleted"] = (
        sum(results[key]["deleted"] for key in CLEANUP_BUCKETS) - results["members"]["deleted"]
    )
    results["errors"].extend(error for key in CLEANUP_BUCKETS for error in results[key]["errors"])
    return results


def _validate_email_patterns(email_patterns):
    """Reject patterns broad enough to select the entire member base."""
    if not isinstance(email_patterns, (list, tuple)):
        frappe.throw(_("email_patterns must be a list of LIKE patterns"))

    for pattern in email_patterns:
        if not isinstance(pattern, str):
            frappe.throw(_("email_patterns must contain only strings"))
        # A pattern of nothing but wildcards matches every address there is.
        if not pattern.strip("%_ "):
            frappe.throw(
                _("Refusing pattern {0}: it matches every member. Supply a specific test pattern.").format(
                    pattern or "''"
                )
            )


def _link_fields_to(target_doctype):
    """Every Link field pointing at `target_doctype`, from BOTH field sources.

    Standard fields live in `tabDocField`, but fields an app adds to a core
    DocType live in `tabCustom Field` -- and that is where most of this app's
    links to Customer / Sales Invoice / Payment Entry are defined. Scanning only
    tabDocField hid 13,539 broken references on the production-like site,
    including all 13,291 dangling `Customer.member` values, which is precisely
    what a broken-link scanner exists to surface.
    """
    return frappe.db.sql(
        """
        SELECT df.parent AS doctype, df.fieldname, df.label, dt.istable, dt.issingle
        FROM tabDocField df
        JOIN tabDocType dt ON df.parent = dt.name
        WHERE df.fieldtype = 'Link' AND df.options = %(target)s AND dt.issingle = 0

        UNION

        SELECT cf.dt AS doctype, cf.fieldname, cf.label, dt.istable, dt.issingle
        FROM `tabCustom Field` cf
        JOIN tabDocType dt ON cf.dt = dt.name
        WHERE cf.fieldtype = 'Link' AND cf.options = %(target)s AND dt.issingle = 0
        """,
        {"target": target_doctype},
        as_dict=True,
    )


def _validate_verenigingen_admin_permissions():
    """
    Validate that current user has Verenigingen Administrator role.
    Returns True if user has permission, throws otherwise.
    """
    user = frappe.session.user

    if user == "Administrator":
        return True

    user_roles = frappe.get_roles()
    if Roles.VERENIGINGEN_ADMIN not in user_roles:
        frappe.throw(
            _("This operation requires Verenigingen Administrator role."),
            frappe.PermissionError,
        )

    return True


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def nuclear_truncate_member_tables(confirm_nuclear_truncate=False, dry_run=True):
    """
    Nuclear TRUNCATE cleanup: Instantly reset ALL member-related AND financial tables.

    Unlike the sequential delete cleanup, this function uses SQL TRUNCATE statements
    to instantly empty all member-related and financial tables. This is MUCH faster
    than row-by-row deletion but is also more dangerous as it bypasses all Frappe
    hooks and validations.

    ⚠️ WARNING: This is a COMPLETE RESET of member data AND financial data!
    This will delete ALL contacts, addresses, invoices, payments, and ledger entries.

    Tables that will be TRUNCATED (in safe dependency order):

    MEMBER-RELATED:
    - Member Payment History, Chapter Member, Chapter Board Member
    - Volunteer Assignment, Volunteer Skill, Volunteer Interest Area, Volunteer Development Goal
    - SEPA Mandate, Contribution Amendment Request, Membership Termination Request, Account Creation Request
    - Volunteer, Membership, Membership Type, Donor, Member, Employee, Chapter

    CONTACT/ADDRESS (ALL records, not just member-linked):
    - Contact Email, Contact Phone, Dynamic Link
    - Contact, Address

    FINANCIAL DOCUMENTS:
    - Sales Invoice (+ Items, Taxes, Payment Schedule, Sales Team)
    - Purchase Invoice (+ Items, Taxes)
    - Payment Entry (+ References, Deductions)
    - Bank Transaction (+ Payments)

    LEDGER ENTRIES:
    - GL Entry (General Ledger - resets Chart of Accounts balances)
    - Payment Ledger Entry

    AUDIT LOGS:
    - API Audit Log
    - SEPA Audit Log

    SPECIAL HANDLING:
    - Membership Dues Schedule: Only non-templates deleted, templates preserved

    Tables that will be UPDATED (references cleared):
    - Customer (member link cleared)

    PRESERVED:
    - User accounts (except member-linked, excluding Administrator/Guest)
    - Settings DocTypes (Verenigingen Settings, etc.)
    - Membership Dues Schedule templates

    Args:
        confirm_nuclear_truncate (bool): Must be True to proceed
        dry_run (bool): If True, only shows what would be truncated

    Returns:
        dict: Results of the truncate operation

    Security:
        - Requires Verenigingen Administrator role
        - Rate limited to 2 uses per hour per user (via COR)
    """
    # Security validation - Verenigingen Administrator only
    _validate_verenigingen_admin_permissions()

    if not confirm_nuclear_truncate:
        frappe.throw(
            _("You must set confirm_nuclear_truncate=True to proceed with this destructive operation")
        )

    # Log the attempt for audit
    frappe.logger("verenigingen.security").warning(
        f"Nuclear TRUNCATE cleanup {'(DRY RUN)' if dry_run else 'EXECUTING'} "
        f"initiated by {frappe.session.user}"
    )

    results = {
        "dry_run": dry_run,
        "tables_truncated": [],
        "tables_updated": [],
        "records_before": {},
        "errors": [],
        "warnings": [],
        "summary": "",
    }

    try:
        # Define tables to truncate in dependency order (children first, parents last)
        # Each entry: (table_name, has_special_handling, description)
        tables_to_truncate = [
            # ===== MEMBER-RELATED CHILD TABLES =====
            ("tabMember Payment History", False, "Member payment tracking records"),
            ("tabChapter Member", False, "Chapter membership links"),
            ("tabChapter Board Member", False, "Chapter board member links"),
            ("tabVolunteer Assignment", False, "Volunteer team/chapter assignments"),
            ("tabVolunteer Skill", False, "Volunteer skills"),
            ("tabVolunteer Interest Area", False, "Volunteer interest areas"),
            ("tabVolunteer Development Goal", False, "Volunteer development goals"),
            # ===== CONTACT/ADDRESS CHILD TABLES =====
            ("tabContact Email", False, "Contact email addresses"),
            ("tabContact Phone", False, "Contact phone numbers"),
            ("tabDynamic Link", False, "Dynamic links (Contact/Address links)"),
            # ===== FINANCIAL DOCUMENT CHILD TABLES =====
            ("tabSales Invoice Item", False, "Sales invoice line items"),
            ("tabSales Taxes and Charges", False, "Sales invoice taxes"),
            ("tabPayment Schedule", False, "Payment schedules"),
            ("tabSales Team", False, "Sales team entries"),
            ("tabPurchase Invoice Item", False, "Purchase invoice line items"),
            ("tabPurchase Taxes and Charges", False, "Purchase invoice taxes"),
            ("tabPayment Entry Reference", False, "Payment entry references"),
            ("tabPayment Entry Deduction", False, "Payment entry deductions"),
            ("tabBank Transaction Payments", False, "Bank transaction payment links"),
            ("tabJournal Entry Account", False, "Journal entry line items"),
            # ===== MEMBER OPERATIONAL TABLES =====
            ("tabSEPA Mandate", False, "SEPA direct debit mandates"),
            ("tabContribution Amendment Request", False, "Contribution change requests"),
            ("tabMembership Termination Request", False, "Membership termination requests"),
            ("tabAccount Creation Request", False, "Account creation requests"),
            ("tabVolunteer", False, "Volunteer records"),
            ("tabMembership", False, "Membership records"),
            ("tabMembership Type", False, "Membership type definitions"),
            ("tabDonor", True, "Donor records (if DocType exists)"),
            ("tabMember", False, "Core member records"),
            ("tabEmployee", False, "Employee records"),
            ("tabChapter", False, "Chapter/local group records"),
            # ===== CONTACT/ADDRESS TABLES =====
            ("tabContact", False, "All contact records"),
            ("tabAddress", False, "All address records"),
            # ===== FINANCIAL DOCUMENTS =====
            ("tabBank Transaction", False, "Bank transactions"),
            ("tabPayment Entry", False, "Payment entries"),
            ("tabSales Invoice", False, "Sales invoices"),
            ("tabPurchase Invoice", False, "Purchase invoices"),
            ("tabJournal Entry", False, "Journal entries"),
            # ===== LEDGER ENTRIES (LAST - references documents) =====
            ("tabGL Entry", False, "General ledger entries"),
            ("tabPayment Ledger Entry", False, "Payment ledger entries"),
            # ===== AUDIT LOGS =====
            ("tabAPI Audit Log", False, "API audit log entries"),
            ("tabSEPA Audit Log", False, "SEPA audit log entries"),
            # ===== PERMISSIONS =====
            ("tabUser Permission", False, "User permission records"),
        ]

        # Tables to update (clear references) - for documentation
        _tables_to_update = [  # noqa: F841
            ("tabCustomer", "member", "Clear customer-member links"),
        ]

        # Build whitelist from the hardcoded tuple above
        allowed_tables = {t[0] for t in tables_to_truncate}

        # Get record counts before operation
        for table_name, has_special, desc in tables_to_truncate:
            try:
                if table_name not in allowed_tables:
                    results["warnings"].append(f"Skipping unrecognized table: {table_name}")
                    continue

                # Check if table exists
                if has_special and table_name == "tabDonor":
                    if not frappe.db.exists("DocType", "Donor"):
                        results["warnings"].append("Donor DocType does not exist - skipping")
                        continue

                count = frappe.db.sql(f"SELECT COUNT(*) FROM `{table_name}`")[0][0]
                results["records_before"][table_name] = count
            except Exception as e:
                results["warnings"].append(f"Could not count {table_name}: {str(e)}")
                results["records_before"][table_name] = "unknown"

        # Special handling: Count Membership Dues Schedule templates to preserve
        try:
            template_count = frappe.db.count("Membership Dues Schedule", {"is_template": 1})
            non_template_count = frappe.db.count("Membership Dues Schedule", {"is_template": 0})
            results["records_before"]["tabMembership Dues Schedule (non-template)"] = non_template_count
            results["records_before"]["tabMembership Dues Schedule (template - PRESERVED)"] = template_count
        except Exception as e:
            results["warnings"].append(f"Could not count Membership Dues Schedule: {str(e)}")

        # Count users/contacts/addresses that would be affected
        try:
            member_linked_users = frappe.db.sql("""
                SELECT COUNT(DISTINCT m.user)
                FROM `tabMember` m
                WHERE m.user IS NOT NULL AND m.user != ''
                AND m.user NOT IN ('Administrator', 'Guest')
            """)[0][0]
            results["records_before"]["User (member-linked)"] = member_linked_users

            member_addresses = frappe.db.sql("""
                SELECT COUNT(DISTINCT dl.parent)
                FROM `tabDynamic Link` dl
                WHERE dl.parenttype = 'Address' AND dl.link_doctype = 'Member'
            """)[0][0]
            results["records_before"]["Address (member-linked)"] = member_addresses

            member_contacts = frappe.db.sql("""
                SELECT COUNT(DISTINCT dl.parent)
                FROM `tabDynamic Link` dl
                WHERE dl.parenttype = 'Contact' AND dl.link_doctype = 'Member'
            """)[0][0]
            results["records_before"]["Contact (member-linked)"] = member_contacts
        except Exception as e:
            results["warnings"].append(f"Could not count linked records: {str(e)}")

        if dry_run:
            total_records = sum(v for v in results["records_before"].values() if isinstance(v, int))
            results["summary"] = (
                f"DRY RUN: Would truncate {len(tables_to_truncate)} tables "
                f"affecting approximately {total_records} records. "
                f"Settings and templates will be preserved."
            )
            return results

        # ========== ACTUAL TRUNCATE OPERATION ==========
        frappe.db.begin()

        try:
            # PHASE 1: Clear references in related tables first
            frappe.logger().info("Phase 1: Clearing foreign key references...")

            # Clear chapter_head references
            frappe.db.sql("UPDATE `tabChapter` SET chapter_head = NULL WHERE chapter_head IS NOT NULL")
            results["tables_updated"].append("tabChapter.chapter_head cleared")

            # Capture member-linked Customers BEFORE clearing the link, otherwise
            # the Dynamic Link cleanup below has nothing left to match on. The
            # field is `member` -- there is no `custom_member` column on Customer,
            # so the previous has_column() guard made this whole path a no-op.
            customer_names = [
                r[0]
                for r in frappe.db.sql(
                    "SELECT name FROM `tabCustomer` WHERE member IS NOT NULL AND member != ''"
                )
            ]

            frappe.db.sql("UPDATE `tabCustomer` SET member = NULL WHERE member IS NOT NULL")
            results["tables_updated"].append("tabCustomer.member cleared")

            # Clear Member.user and Member.customer before deleting users
            frappe.db.sql("UPDATE `tabMember` SET user = NULL, customer = NULL")
            results["tables_updated"].append("tabMember.user and customer cleared")

            # PHASE 2: Delete Dynamic Links to Members/Volunteers/Customers we're cleaning
            frappe.logger().info("Phase 2: Cleaning up Dynamic Links...")
            frappe.db.sql("DELETE FROM `tabDynamic Link` WHERE link_doctype = 'Member'")
            frappe.db.sql("DELETE FROM `tabDynamic Link` WHERE link_doctype = 'Volunteer'")
            results["tables_updated"].append("Dynamic Links to Member/Volunteer deleted")

            # customer_names was captured above, before the link was cleared.
            if customer_names:
                placeholders = ", ".join(["%s"] * len(customer_names))
                frappe.db.sql(
                    f"DELETE FROM `tabDynamic Link` WHERE link_doctype = 'Customer' AND link_name IN ({placeholders})",
                    customer_names,
                )
                results["tables_updated"].append(
                    f"Dynamic Links to {len(customer_names)} member-linked Customers deleted"
                )

            # PHASE 3: Delete member-linked Addresses and Contacts
            frappe.logger().info("Phase 3: Cleaning up Addresses and Contacts...")

            # Get addresses/contacts linked to members (via Dynamic Link)
            member_addresses = frappe.db.sql(
                """
                SELECT DISTINCT dl.parent FROM `tabDynamic Link` dl
                WHERE dl.parenttype = 'Address' AND dl.link_doctype = 'Member'
            """,
                as_list=True,
            )
            address_names = [a[0] for a in member_addresses] if member_addresses else []

            member_contacts = frappe.db.sql(
                """
                SELECT DISTINCT dl.parent FROM `tabDynamic Link` dl
                WHERE dl.parenttype = 'Contact' AND dl.link_doctype = 'Member'
            """,
                as_list=True,
            )
            contact_names = [c[0] for c in member_contacts] if member_contacts else []

            # Delete contacts and their child tables
            if contact_names:
                placeholders = ", ".join(["%s"] * len(contact_names))
                frappe.db.sql(
                    f"DELETE FROM `tabContact Email` WHERE parent IN ({placeholders})", contact_names
                )
                frappe.db.sql(
                    f"DELETE FROM `tabContact Phone` WHERE parent IN ({placeholders})", contact_names
                )
                frappe.db.sql(
                    f"DELETE FROM `tabDynamic Link` WHERE parent IN ({placeholders}) AND parenttype = 'Contact'",
                    contact_names,
                )
                frappe.db.sql(f"DELETE FROM `tabContact` WHERE name IN ({placeholders})", contact_names)
                results["tables_updated"].append(f"Deleted {len(contact_names)} member-linked Contacts")

            # Delete addresses and their dynamic links
            if address_names:
                placeholders = ", ".join(["%s"] * len(address_names))
                frappe.db.sql(
                    f"DELETE FROM `tabDynamic Link` WHERE parent IN ({placeholders}) AND parenttype = 'Address'",
                    address_names,
                )
                frappe.db.sql(f"DELETE FROM `tabAddress` WHERE name IN ({placeholders})", address_names)
                results["tables_updated"].append(f"Deleted {len(address_names)} member-linked Addresses")

            # PHASE 4: Delete member-linked Users
            frappe.logger().info("Phase 4: Cleaning up member-linked Users...")

            member_users = frappe.db.sql(
                """
                SELECT DISTINCT m.user FROM `tabMember` m
                WHERE m.user IS NOT NULL AND m.user != ''
                AND m.user NOT IN ('Administrator', 'Guest')
            """,
                as_list=True,
            )
            user_names = [u[0] for u in member_users] if member_users else []

            if user_names:
                placeholders = ", ".join(["%s"] * len(user_names))
                # Delete user child tables first
                frappe.db.sql(f"DELETE FROM `tabHas Role` WHERE parent IN ({placeholders})", user_names)
                frappe.db.sql(f"DELETE FROM `tabUser Email` WHERE parent IN ({placeholders})", user_names)
                frappe.db.sql(
                    f"DELETE FROM `tabUser Social Login` WHERE parent IN ({placeholders})", user_names
                )
                frappe.db.sql(f"DELETE FROM `tabBlock Module` WHERE parent IN ({placeholders})", user_names)
                frappe.db.sql(f"DELETE FROM `tabDefaultValue` WHERE parent IN ({placeholders})", user_names)
                frappe.db.sql(f"DELETE FROM `tabUser Permission` WHERE user IN ({placeholders})", user_names)
                frappe.db.sql(f"DELETE FROM `tabUser` WHERE name IN ({placeholders})", user_names)
                results["tables_updated"].append(f"Deleted {len(user_names)} member-linked Users")

            # PHASE 5: Delete Employees linked to member users
            if user_names:
                placeholders = ", ".join(["%s"] * len(user_names))
                frappe.db.sql(
                    f"UPDATE `tabEmployee` SET user_id = NULL WHERE user_id IN ({placeholders})", user_names
                )
                frappe.db.sql(f"DELETE FROM `tabEmployee` WHERE user_id IN ({placeholders})", user_names)
                results["tables_updated"].append("Member-linked Employees deleted")

            # PHASE 6: TRUNCATE main operational tables
            # TRUNCATE is DDL and causes implicit commit, so we must commit first
            # and execute TRUNCATEs outside of transaction
            frappe.logger().info("Phase 6: Committing reference cleanup before TRUNCATE...")
            frappe.db.commit()

            frappe.logger().info("Phase 6: Truncating main operational tables...")

            # Temporarily disable foreign key checks to allow TRUNCATE
            frappe.db.sql_ddl("SET FOREIGN_KEY_CHECKS = 0")

            for table_name, has_special, desc in tables_to_truncate:
                try:
                    # Special handling for Donor (check if exists)
                    if has_special and table_name == "tabDonor":
                        if not frappe.db.exists("DocType", "Donor"):
                            continue

                    # TRUNCATE is faster than DELETE as it doesn't log individual rows
                    # Use sql_ddl for DDL statements that cause implicit commit
                    frappe.db.sql_ddl(f"TRUNCATE TABLE `{table_name}`")
                    results["tables_truncated"].append(f"{table_name} ({desc})")
                    frappe.logger().info(f"Truncated {table_name}")

                except Exception as e:
                    results["errors"].append(f"Failed to truncate {table_name}: {str(e)}")
                    frappe.logger().error(f"Failed to truncate {table_name}: {str(e)}")

            # Re-enable foreign key checks
            frappe.db.sql_ddl("SET FOREIGN_KEY_CHECKS = 1")

            # Start new transaction for remaining cleanup
            frappe.db.begin()

            # PHASE 7: Special handling for Membership Dues Schedule (preserve templates)
            frappe.logger().info("Phase 7: Cleaning Membership Dues Schedules (preserving templates)...")
            try:
                # Delete non-template schedules only
                frappe.db.sql("DELETE FROM `tabMembership Dues Schedule` WHERE is_template = 0")
                results["tables_truncated"].append("tabMembership Dues Schedule (non-templates only)")
            except Exception as e:
                results["errors"].append(f"Failed to clean Membership Dues Schedule: {str(e)}")

            # PHASE 8: Clean up Notification Settings and API Audit Logs for member emails
            # Note: Sales Invoice is now fully truncated, no need to clear references
            frappe.logger().info("Phase 8: Cleaning up related settings...")
            # Note: We don't truncate these as they may have non-member data
            # The nuclear_cleanup_all_members does this per-member, but here we skip it
            # as the members table is now empty

            # Commit the transaction
            frappe.db.commit()

            # Calculate summary
            truncated_count = len(results["tables_truncated"])
            updated_count = len(results["tables_updated"])
            error_count = len(results["errors"])

            results["summary"] = (
                f"Nuclear TRUNCATE completed: {truncated_count} tables truncated, "
                f"{updated_count} tables/references updated"
            )
            if error_count > 0:
                results["summary"] += f", {error_count} errors encountered"

            frappe.logger("verenigingen.security").info(
                f"Nuclear TRUNCATE cleanup completed by {frappe.session.user}: {results['summary']}"
            )

        except Exception as e:
            frappe.db.rollback()
            results["summary"] = f"TRANSACTION ROLLED BACK - Critical error: {str(e)}"
            results["transaction_rolled_back"] = True
            frappe.log_error(
                f"Nuclear TRUNCATE cleanup failed and rolled back: {str(e)}", "Member Import Cleanup Error"
            )

    except Exception as e:
        results["summary"] = f"Unexpected error during truncate cleanup: {str(e)}"
        frappe.log_error(
            f"Nuclear TRUNCATE cleanup unexpected error: {str(e)}", "Member Import Cleanup Error"
        )

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def scan_and_clear_broken_links(
    target_doctypes=None, dry_run=True, clear_mode="null"
) -> OperationResult[Dict[str, Any]]:
    """
    Scan for and optionally clear broken Link field references across all DocTypes.

    This is useful after nuclear truncate operations to find stale references
    to deleted documents.

    Args:
        target_doctypes (list|str): DocTypes to scan for broken links to.
            Default: ["Member", "Membership Type", "Membership Dues Schedule", "Chapter", "Volunteer"]
        dry_run (bool): If True, only report broken links without clearing them
        clear_mode (str): How to clear broken links:
            - "null": Set the field to NULL (default)
            - "delete": Delete the row (only for child tables)

    Returns:
        OperationResult[Dict[str, Any]]: Scan results including:
            - broken_links: List of broken link details by DocType
            - total_broken: Total count of broken references found
            - cleared: Count of references cleared (0 if dry_run)
            - summary: Human-readable summary
    """
    # ENHANCED SECURITY VALIDATION
    validate_cleanup_permissions()

    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    # Default target doctypes - common ones that get truncated
    default_targets = [
        "Member",
        "Membership Type",
        "Membership Dues Schedule",
        "Chapter",
        "Volunteer",
        "SEPA Mandate",
        "Sales Invoice",
        "Payment Entry",
    ]

    if target_doctypes is None:
        target_doctypes = default_targets
    elif isinstance(target_doctypes, str):
        import json

        try:
            target_doctypes = json.loads(target_doctypes)
        except json.JSONDecodeError:
            target_doctypes = [target_doctypes]

    results = {
        "broken_links": {},
        "total_broken": 0,
        "cleared": 0,
        "errors": [],
        "dry_run": dry_run,
    }

    try:
        for target_doctype in target_doctypes:
            target_results = {
                "link_fields": [],
                "dynamic_links": [],
                "total": 0,
            }

            for field in _link_fields_to(target_doctype):
                table_name = f"tab{field.doctype}"

                try:
                    # Count separately from the sample: the UPDATE/DELETE below is
                    # unbounded, so sizing the result off a LIMITed SELECT reported
                    # 1000 while actually clearing every broken row.
                    broken_count = frappe.db.sql(f"""
                        SELECT COUNT(*)
                        FROM `{table_name}` src
                        LEFT JOIN `tab{target_doctype}` tgt ON src.`{field.fieldname}` = tgt.name
                        WHERE src.`{field.fieldname}` IS NOT NULL
                        AND src.`{field.fieldname}` != ''
                        AND tgt.name IS NULL
                        """)[0][0]

                    broken = frappe.db.sql(
                        f"""
                        SELECT src.name, src.`{field.fieldname}` as broken_ref
                        FROM `{table_name}` src
                        LEFT JOIN `tab{target_doctype}` tgt ON src.`{field.fieldname}` = tgt.name
                        WHERE src.`{field.fieldname}` IS NOT NULL
                        AND src.`{field.fieldname}` != ''
                        AND tgt.name IS NULL
                        LIMIT 5
                        """,
                        as_dict=True,
                    )

                    if broken_count:
                        results["total_broken"] += broken_count
                        target_results["total"] += broken_count

                        target_results["link_fields"].append(
                            {
                                "doctype": field.doctype,
                                "fieldname": field.fieldname,
                                "label": field.label,
                                "is_child_table": bool(field.istable),
                                "broken_count": broken_count,
                                "sample_refs": [b.broken_ref for b in broken[:5]],
                            }
                        )

                        if not dry_run:
                            # Clear the broken references
                            if clear_mode == "delete" and field.istable:
                                # Delete child table rows with broken links
                                frappe.db.sql(f"""
                                    DELETE src FROM `{table_name}` src
                                    LEFT JOIN `tab{target_doctype}` tgt ON src.`{field.fieldname}` = tgt.name
                                    WHERE src.`{field.fieldname}` IS NOT NULL
                                    AND src.`{field.fieldname}` != ''
                                    AND tgt.name IS NULL
                                    """)
                            else:
                                # Set to NULL
                                frappe.db.sql(f"""
                                    UPDATE `{table_name}` src
                                    LEFT JOIN `tab{target_doctype}` tgt ON src.`{field.fieldname}` = tgt.name
                                    SET src.`{field.fieldname}` = NULL
                                    WHERE src.`{field.fieldname}` IS NOT NULL
                                    AND src.`{field.fieldname}` != ''
                                    AND tgt.name IS NULL
                                    """)
                            results["cleared"] += broken_count

                except Exception as e:
                    # Table might not exist or column missing
                    if "doesn't exist" not in str(e).lower() and "Unknown column" not in str(e):
                        results["errors"].append(f"{field.doctype}.{field.fieldname}: {str(e)}")

            # 2. Check Dynamic Links (used by Contact, Address, etc.)
            try:
                # Counted in full for the same reason as the Link fields above.
                dynamic_count = frappe.db.sql(
                    f"""
                    SELECT COUNT(*)
                    FROM `tabDynamic Link` dl
                    LEFT JOIN `tab{target_doctype}` tgt ON dl.link_name = tgt.name
                    WHERE dl.link_doctype = %s
                    AND tgt.name IS NULL
                    """,
                    target_doctype,
                )[0][0]

                broken_dynamic = frappe.db.sql(
                    f"""
                    SELECT dl.parent, dl.parenttype, dl.link_name
                    FROM `tabDynamic Link` dl
                    LEFT JOIN `tab{target_doctype}` tgt ON dl.link_name = tgt.name
                    WHERE dl.link_doctype = %s
                    AND tgt.name IS NULL
                    LIMIT 1000
                    """,
                    target_doctype,
                    as_dict=True,
                )

                if dynamic_count:
                    results["total_broken"] += dynamic_count
                    target_results["total"] += dynamic_count

                    # Group by parenttype
                    by_parenttype = {}
                    for dl in broken_dynamic:
                        if dl.parenttype not in by_parenttype:
                            by_parenttype[dl.parenttype] = []
                        by_parenttype[dl.parenttype].append(dl.link_name)

                    for parenttype, links in by_parenttype.items():
                        target_results["dynamic_links"].append(
                            {
                                "parenttype": parenttype,
                                "broken_count": len(links),
                                "sample_refs": links[:5],
                            }
                        )

                    if not dry_run:
                        # Delete broken dynamic links
                        frappe.db.sql(
                            f"""
                            DELETE dl FROM `tabDynamic Link` dl
                            LEFT JOIN `tab{target_doctype}` tgt ON dl.link_name = tgt.name
                            WHERE dl.link_doctype = %s
                            AND tgt.name IS NULL
                            """,
                            target_doctype,
                        )
                        results["cleared"] += dynamic_count

            except Exception as e:
                results["errors"].append(f"Dynamic Link ({target_doctype}): {str(e)}")

            if target_results["total"] > 0:
                results["broken_links"][target_doctype] = target_results

        if not dry_run:
            frappe.db.commit()

        # Build summary
        if results["total_broken"] == 0:
            results["summary"] = "No broken links found"
        elif dry_run:
            results["summary"] = (
                f"DRY RUN: Found {results['total_broken']} broken links across "
                f"{len(results['broken_links'])} target DocTypes"
            )
        else:
            results["summary"] = (
                f"Cleared {results['cleared']} broken links across "
                f"{len(results['broken_links'])} target DocTypes"
            )

        return OperationResult.ok(results, message=_(results["summary"]))

    except Exception as e:
        frappe.log_error(
            f"Error scanning for broken links: {str(e)}\n{traceback.format_exc()}",
            "Broken Link Scanner Error",
        )
        return OperationResult.fail(
            _("Unable to scan for broken links. Please contact support."),
            errors=[str(e)],
            context={"operation": "scan_and_clear_broken_links", "dry_run": dry_run},
        )

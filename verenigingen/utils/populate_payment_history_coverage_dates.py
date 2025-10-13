"""
Populate coverage dates in existing Member Payment History records.

This script updates existing payment history entries to include coverage_start_date
and coverage_end_date from their linked Sales Invoices.

Usage:
    bench --site [sitename] execute verenigingen.scripts.migration.populate_payment_history_coverage_dates.populate_coverage_dates

Options:
    - Pass dry_run=True to see what would be updated without making changes
    - Pass limit=N to process only N members (for testing)
"""

import frappe
from frappe.utils import getdate


def populate_coverage_dates(dry_run=False, limit=None):
    """
    Populate coverage dates in Member Payment History from Sales Invoices.

    Args:
        dry_run: If True, only report what would be changed without saving
        limit: Optional limit on number of members to process
    """

    # Get all members with payment history
    members_query = """
        SELECT DISTINCT m.name, m.customer
        FROM `tabMember` m
        INNER JOIN `tabMember Payment History` mph ON mph.parent = m.name
        WHERE m.customer IS NOT NULL
        AND mph.invoice IS NOT NULL
        ORDER BY m.name
    """

    if limit:
        members_query += f" LIMIT {int(limit)}"

    members = frappe.db.sql(members_query, as_dict=True)

    total_members = len(members)
    updated_count = 0
    skipped_count = 0
    error_count = 0

    print(f"\n{'DRY RUN: ' if dry_run else ''}Processing {total_members} members with payment history...")

    for idx, member_data in enumerate(members, 1):
        member_name = member_data.name

        try:
            # Get member document
            member = frappe.get_doc("Member", member_name)

            if not hasattr(member, "payment_history") or not member.payment_history:
                skipped_count += 1
                continue

            member_updated = False

            # Process each payment history entry
            for entry in member.payment_history:
                if not entry.invoice:
                    continue

                # Check if coverage dates are already populated
                if entry.coverage_start_date and entry.coverage_end_date:
                    continue  # Skip entries that already have coverage dates

                # Fetch coverage dates from the Sales Invoice
                try:
                    invoice_data = frappe.db.get_value(
                        "Sales Invoice",
                        entry.invoice,
                        ["custom_coverage_start_date", "custom_coverage_end_date"],
                        as_dict=True,
                    )

                    if invoice_data and (
                        invoice_data.custom_coverage_start_date or invoice_data.custom_coverage_end_date
                    ):
                        # Update the entry
                        if invoice_data.custom_coverage_start_date:
                            entry.coverage_start_date = invoice_data.custom_coverage_start_date
                        if invoice_data.custom_coverage_end_date:
                            entry.coverage_end_date = invoice_data.custom_coverage_end_date

                        member_updated = True

                        if dry_run:
                            print(
                                f"  Would update {member_name} - Invoice {entry.invoice}: "
                                f"{invoice_data.custom_coverage_start_date or 'None'} to "
                                f"{invoice_data.custom_coverage_end_date or 'None'}"
                            )

                except frappe.DoesNotExistError:
                    # Invoice no longer exists, skip
                    continue
                except Exception as e:
                    print(f"  Error fetching invoice {entry.invoice}: {str(e)}")
                    continue

            # Save the member if any entries were updated
            if member_updated and not dry_run:
                try:
                    # Use flags to reduce activity logging
                    member.flags.ignore_version = True
                    member.flags.ignore_links = True
                    member.flags.ignore_validate_update_after_submit = True

                    # Save using update_child_table for efficiency
                    member.update_child_table("payment_history")
                    frappe.db.commit()

                    updated_count += 1

                    if idx % 10 == 0:
                        print(f"Progress: {idx}/{total_members} members processed, {updated_count} updated")

                except Exception as e:
                    error_count += 1
                    print(f"  Error saving member {member_name}: {str(e)}")
                    frappe.db.rollback()

        except Exception as e:
            error_count += 1
            print(f"Error processing member {member_name}: {str(e)}")
            continue

    print(f"\n{'DRY RUN ' if dry_run else ''}Results:")
    print(f"  Total members processed: {total_members}")
    print(f"  Members updated: {updated_count}")
    print(f"  Members skipped: {skipped_count}")
    print(f"  Errors: {error_count}")

    if dry_run:
        print("\nThis was a DRY RUN. No changes were saved.")
        print("Run again with dry_run=False to apply changes.")

    return {
        "total": total_members,
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": error_count,
        "dry_run": dry_run,
    }


def populate_single_member(member_name, dry_run=False):
    """
    Populate coverage dates for a single member (useful for testing).

    Args:
        member_name: Name of the Member document
        dry_run: If True, only report what would be changed
    """
    result = populate_coverage_dates(dry_run=dry_run, limit=None)
    return result

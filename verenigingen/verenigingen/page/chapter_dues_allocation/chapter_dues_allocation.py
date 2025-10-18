"""
Chapter Dues Allocation Page Backend

Server-side methods for generating journal entries to allocate dues income
between chapter and national accounts.
"""

from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.verenigingen.domain.chapter_dues import DuesAllocationService
from verenigingen.verenigingen.domain.chapter_dues_validation import DuesAllocationValidator


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_allocation_preview(
    from_date: str, to_date: str, chapter: Optional[str] = None, company: Optional[str] = None
) -> Dict:
    """
    Get preview of allocation amounts before generating journal entries.

    Args:
        from_date: Start date for invoice filtering
        to_date: End date for invoice filtering
        chapter: Optional chapter filter
        company: Optional company filter

    Returns:
        Dictionary with allocation preview data
    """
    # Validate inputs using centralized validator
    validator = DuesAllocationValidator()

    try:
        from_date = getdate(from_date)
        to_date = getdate(to_date)
    except Exception:
        frappe.throw(_("Invalid date format"))

    validator.validate_date_range(from_date, to_date)
    validator.validate_chapter_exists(chapter)
    validator.validate_company_exists(company)

    # Get settings for account configuration
    settings = frappe.get_single("Verenigingen Settings")

    # Build query conditions
    conditions = ["si.docstatus = 1", "si.custom_member_chapter IS NOT NULL"]
    filters = {"from_date": from_date, "to_date": to_date}

    if chapter:
        conditions.append("si.custom_member_chapter = %(chapter)s")
        filters["chapter"] = chapter
    if company:
        conditions.append("si.company = %(company)s")
        filters["company"] = company

    where_clause = " AND ".join(conditions)

    # Query chapter totals
    query = f"""
        SELECT
            si.custom_member_chapter as chapter,
            si.company,
            COUNT(si.name) as invoice_count,
            SUM(si.grand_total) as total_amount
        FROM `tabSales Invoice` si
        WHERE {where_clause}
            AND si.posting_date >= %(from_date)s
            AND si.posting_date <= %(to_date)s
        GROUP BY si.custom_member_chapter, si.company
        ORDER BY si.custom_member_chapter
    """

    chapter_data = frappe.db.sql(query, filters, as_dict=True)

    # Use domain service for calculations (avoids N+1 queries)
    allocation_service = DuesAllocationService()

    # Prepare batch input
    chapter_amounts = {row["chapter"]: flt(row["total_amount"]) for row in chapter_data}

    # Batch calculate all allocations (single query for all chapter configs)
    allocations_map = allocation_service.batch_calculate(chapter_amounts)

    # Build response
    allocations = []
    total_chapter_amount = 0
    total_national_amount = 0

    for row in chapter_data:
        chapter_name = row["chapter"]
        allocation = allocations_map[chapter_name]

        allocations.append(
            {
                "chapter": chapter_name,
                "company": row["company"],
                "invoice_count": row["invoice_count"],
                **allocation.to_dict(),
            }
        )

        total_chapter_amount += float(allocation.chapter_amount)
        total_national_amount += float(allocation.national_amount)

    return {
        "allocations": allocations,
        "summary": {
            "total_chapter_amount": round(total_chapter_amount, 2),
            "total_national_amount": round(total_national_amount, 2),
            "grand_total": round(total_chapter_amount + total_national_amount, 2),
        },
        "accounts": {
            "chapter_account": settings.chapter_dues_income_account,
            "national_account": settings.national_dues_income_account,
            "source_account": settings.dues_income_account,
        },
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def generate_allocation_journal_entries(
    from_date: str,
    to_date: str,
    posting_date: Optional[str] = None,
    chapter: Optional[str] = None,
    company: Optional[str] = None,
) -> Dict:
    """
    Generate Journal Entries to allocate dues income between chapter and national accounts.

    Args:
        from_date: Start date for invoice filtering
        to_date: End date for invoice filtering
        posting_date: Posting date for journal entries (defaults to today)
        chapter: Optional chapter filter
        company: Optional company filter

    Returns:
        List of created Journal Entry names
    """
    # Validate inputs using centralized validator
    validator = DuesAllocationValidator()

    try:
        from_date = getdate(from_date)
        to_date = getdate(to_date)
        if posting_date:
            posting_date = getdate(posting_date)
        else:
            posting_date = nowdate()
    except Exception:
        frappe.throw(_("Invalid date format"))

    validator.validate_date_range(from_date, to_date)
    validator.validate_chapter_exists(chapter)
    validator.validate_company_exists(company)

    # Check for idempotency - prevent duplicate allocations
    # Build allocation period key for tracking
    allocation_period_key = f"{from_date}|{to_date}|{chapter or 'ALL'}|{company or 'ALL'}"

    existing_entries = frappe.get_all(
        "Journal Entry",
        filters={
            "custom_dues_allocation_period": allocation_period_key,
            "docstatus": ["!=", 2],  # Not cancelled
        },
        fields=["name", "docstatus"],
    )

    if existing_entries:
        entry_list = ", ".join([e.name for e in existing_entries])
        frappe.throw(
            _(
                "Allocation journal entries already exist for period {0} to {1}: {2}. "
                "Please cancel existing entries before creating new ones."
            ).format(from_date, to_date, entry_list),
            title=_("Duplicate Allocation Detected"),
        )

    # Get allocation preview
    preview = get_allocation_preview(from_date, to_date, chapter, company)

    if not preview["allocations"]:
        frappe.throw(_("No dues invoices found for the selected period and filters"))

    # Validate account configuration using centralized validator
    validator.validate_account_configuration()

    # Get settings for account access
    settings = frappe.get_single("Verenigingen Settings")

    created_entries = []

    # Wrap journal entry creation in try-except for proper rollback on partial failure
    try:
        # Create one Journal Entry per company
        for company_name in set([a["company"] for a in preview["allocations"]]):
            company_allocations = [a for a in preview["allocations"] if a["company"] == company_name]

            # Calculate company totals
            company_chapter_total = sum([a["chapter_amount"] for a in company_allocations])
            company_national_total = sum([a["national_amount"] for a in company_allocations])
            company_grand_total = company_chapter_total + company_national_total

            # Create Journal Entry
            #
            # Accounting Logic:
            # -----------------
            # This journal entry redistributes dues income from a single source account
            # into separate chapter and national accounts based on configured split percentages.
            #
            # Double-Entry Structure:
            # 1. Debit (Dr) Dues Income Account:     Total amount (reverses original income)
            # 2. Credit (Cr) Chapter Income Account: Chapter portion (records split income)
            # 3. Credit (Cr) National Income Account: National portion (records split income)
            #
            # Example for €100 dues with 60/40 split:
            # Dr Dues Income Account        €100
            #    Cr Chapter Income Account           €60
            #    Cr National Income Account          €40
            #
            # This maintains the accounting equation: Assets = Liabilities + Equity
            # The total income remains unchanged, only its classification is adjusted.
            # Build allocation period key for this company
            company_allocation_key = f"{from_date}|{to_date}|{chapter or 'ALL'}|{company_name}"

            je = frappe.get_doc(
                {
                    "doctype": "Journal Entry",
                    "voucher_type": "Journal Entry",
                    "company": company_name,
                    "posting_date": posting_date,
                    "user_remark": f"Allocation of membership dues income for period {from_date} to {to_date}",
                    "custom_dues_allocation_period": company_allocation_key,
                    "accounts": [
                        {
                            "account": settings.dues_income_account,
                            "debit_in_account_currency": company_grand_total,
                            "credit_in_account_currency": 0,
                            "user_remark": f"Reverse total dues income",
                        },
                        {
                            "account": settings.chapter_dues_income_account,
                            "debit_in_account_currency": 0,
                            "credit_in_account_currency": company_chapter_total,
                            "user_remark": f"Allocate chapter portion ({len(company_allocations)} chapters)",
                        },
                        {
                            "account": settings.national_dues_income_account,
                            "debit_in_account_currency": 0,
                            "credit_in_account_currency": company_national_total,
                            "user_remark": f"Allocate national portion",
                        },
                    ],
                }
            )

            # Validate accounting entries balance
            total_debits = sum([acc.get("debit_in_account_currency", 0) for acc in je.accounts])
            total_credits = sum([acc.get("credit_in_account_currency", 0) for acc in je.accounts])

            if round(total_debits, 2) != round(total_credits, 2):
                frappe.throw(
                    _("Journal Entry accounting error for {0}: Debits ({1}) != Credits ({2})").format(
                        company_name, total_debits, total_credits
                    )
                )

            je.insert()
            created_entries.append(je.name)

            frappe.msgprint(
                _("Created Journal Entry {0} for {1}").format(frappe.bold(je.name), frappe.bold(company_name))
            )

    except Exception as e:
        # Rollback all changes if any journal entry creation fails
        frappe.db.rollback()
        frappe.log_error(
            title=_("Journal Entry Creation Failed"),
            message=f"Failed to create journal entries for period {from_date} to {to_date}. "
            f"Created {len(created_entries)} entries before failure. Error: {str(e)}",
        )
        frappe.throw(
            _(
                "Journal entry creation failed after creating {0} of {1} entries. "
                "All changes have been rolled back. Error: {2}"
            ).format(len(created_entries), len(set([a["company"] for a in preview["allocations"]])), str(e)),
            title=_("Transaction Rolled Back"),
        )

    # Frappe will auto-commit when API request completes successfully
    # Manual commit removed to allow proper rollback on errors

    return {
        "success": True,
        "journal_entries": created_entries,
        "message": _("Successfully created {0} Journal Entry(s)").format(len(created_entries)),
    }

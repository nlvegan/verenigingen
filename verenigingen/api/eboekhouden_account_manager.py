import frappe

from verenigingen.api.check_eboekhouden_accounts import (
    check_eboekhouden_accounts,
    debug_cleanup_eboekhouden_accounts,
)


@frappe.whitelist()
def get_eboekhouden_accounts_summary():
    """
    Get a summary of all E-Boekhouden accounts in the system.
    This is a wrapper for the UI to call check_eboekhouden_accounts.
    """
    return check_eboekhouden_accounts()


@frappe.whitelist()
def cleanup_eboekhouden_accounts_with_confirmation(company, confirmed=False):
    """
    Clean up E-Boekhouden accounts with confirmation step.

    Args:
        company: Company to clean up accounts for
        confirmed: Whether the user has confirmed the cleanup
    """
    if not confirmed:
        # First call - do a dry run and return confirmation request
        dry_run_result = debug_cleanup_eboekhouden_accounts(company, dry_run=True)

        if dry_run_result.get("total_accounts", 0) == 0:
            return {
                "success": True,
                "confirmed": True,
                "message": "No E-Boekhouden accounts found to clean up",
            }

        return {
            "success": True,
            "confirmed": False,
            "requires_confirmation": True,
            "dry_run_result": dry_run_result,
            "confirmation_message": f"This will delete {dry_run_result.get('total_accounts', 0)} E-Boekhouden accounts. Are you sure you want to proceed?",
        }
    else:
        # Second call - user confirmed, do the actual cleanup
        return debug_cleanup_eboekhouden_accounts(company, dry_run=False)


@frappe.whitelist()
def get_account_cleanup_status(company):
    """
    Get the current status of E-Boekhouden accounts for a company.
    Useful for showing in dashboards or reports.
    """
    try:
        # Get accounts for specific company
        accounts = frappe.get_all(
            "Account",
            filters={"company": company, "eboekhouden_grootboek_nummer": ["!=", ""]},
            fields=["name", "is_group", "account_name"],
        )

        # Count accounts with GL entries
        accounts_with_entries = 0
        for account in accounts:
            if frappe.db.exists("GL Entry", {"account": account.name}):
                accounts_with_entries += 1

        # Get last migration info if available
        last_migration = frappe.get_all(
            "E-Boekhouden Migration",
            filters={"company": company},
            fields=["name", "status", "migration_date", "total_accounts"],
            order_by="creation desc",
            limit=1,
        )

        return {
            "success": True,
            "company": company,
            "total_eboekhouden_accounts": len(accounts),
            "accounts_with_gl_entries": accounts_with_entries,
            "accounts_without_gl_entries": len(accounts) - accounts_with_entries,
            "last_migration": last_migration[0] if last_migration else None,
            "can_cleanup": len(accounts) > 0,
        }

    except Exception as e:
        frappe.log_error(f"Error getting account cleanup status: {str(e)}")
        return {"success": False, "error": str(e)}

import frappe


def get_context(context):
    # Check permissions
    if not frappe.has_permission("E-Boekhouden Migration", "read"):
        frappe.throw("You don't have permission to access this page", frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = False

    # Add page title
    context.title = "E-Boekhouden Account Review"

    # Get the default company
    settings = frappe.get_single("E-Boekhouden Settings")
    context.default_company = settings.default_company if settings else None

    # Get account types for dropdown - these must match ERPNext's valid account types
    context.account_types = [
        "",
        "Accumulated Depreciation",
        "Asset Received But Not Billed",
        "Bank",
        "Capital Work in Progress",
        "Cash",
        "Chargeable",
        "Cost of Goods Sold",
        "Current Asset",
        "Current Liability",
        "Depreciation",
        "Direct Expense",
        "Direct Income",
        "Equity",
        "Expense Account",
        "Expenses Included In Asset Valuation",
        "Expenses Included In Valuation",
        "Fixed Asset",
        "Income Account",
        "Indirect Expense",
        "Indirect Income",
        "Payable",
        "Receivable",
        "Round Off",
        "Round Off for Opening",
        "Stock",
        "Stock Adjustment",
        "Stock Received But Not Billed",
        "Service Received But Not Billed",
        "Tax",
        "Temporary",
    ]

    return context

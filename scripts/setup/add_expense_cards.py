#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def add_expense_number_cards():
    """Add expense-related Number Cards to the dashboard"""

    try:
        # Create Number Cards for expenses
        cards_created = []

        # Card 1: Filed Expense Claims
        if not frappe.db.exists("Number Card", "Filed Expense Claims"):
            filed_card = frappe.get_doc(
                {
                    "doctype": "Number Card",
                    "label": "Filed Expense Claims",
                    "method": "verenigingen.api.chapter_dashboard_api.get_filed_expense_claims_count",
                    "type": "Custom",
                    "is_public": 1,
                    "show_percentage_stats": 0,
                    "color": "#f39c12",
                    "module": "Verenigingen",
                }
            )
            filed_card.insert()
            cards_created.append("Filed Expense Claims")

        # Card 2: Approved Expense Claims
        if not frappe.db.exists("Number Card", "Approved Expense Claims"):
            approved_card = frappe.get_doc(
                {
                    "doctype": "Number Card",
                    "label": "Approved Expense Claims",
                    "method": "verenigingen.api.chapter_dashboard_api.get_approved_expense_claims_count",
                    "type": "Custom",
                    "is_public": 1,
                    "show_percentage_stats": 0,
                    "color": "#27ae60",
                    "module": "Verenigingen",
                }
            )
            approved_card.insert()
            cards_created.append("Approved Expense Claims")

        # Card 3: Volunteer Expenses
        if not frappe.db.exists("Number Card", "Volunteer Expenses"):
            volunteer_card = frappe.get_doc(
                {
                    "doctype": "Number Card",
                    "label": "Volunteer Expenses",
                    "method": "verenigingen.api.chapter_dashboard_api.get_volunteer_expenses_count",
                    "type": "Custom",
                    "is_public": 1,
                    "show_percentage_stats": 0,
                    "color": "#9b59b6",
                    "module": "Verenigingen",
                }
            )
            volunteer_card.insert()
            cards_created.append("Volunteer Expenses")

        # Add cards to dashboard
        dashboard = frappe.get_doc("Dashboard", "Chapter Board Dashboard")

        for card_name in cards_created:
            dashboard.append("cards", {"card": card_name, "width": "Half"})

        dashboard.save()

        return {
            "success": True,
            "message": "Added expense Number Cards to dashboard",
            "cards_created": cards_created,
            "expected_values": {"filed_claims": 1, "approved_claims": 1, "volunteer_expenses": 1},
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = add_expense_number_cards()
    print("Result:", result)

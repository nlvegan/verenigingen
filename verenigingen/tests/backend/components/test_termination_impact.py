#!/usr/bin/env python3


def test_termination_impact():
    """Test the termination impact detection for specific member"""

    import frappe

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    member_name = "Assoc-Member-2025-05-0001"
    print(f"Testing termination impact detection for: {member_name}")

    try:
        # Test the main API function
        from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
            get_termination_impact_preview,
        )

        impact_data = get_termination_impact_preview(member_name)
        print("\nTermination Impact Results:")
        print(f"- Active Memberships: {impact_data.get('active_memberships', 0)}")
        print(f"- SEPA Mandates: {impact_data.get('sepa_mandates', 0)}")
        print(f"- Board Positions: {impact_data.get('board_positions', 0)}")
        print(f"- Outstanding Invoices: {impact_data.get('outstanding_invoices', 0)}")
        print(f"- Active Subscriptions: {impact_data.get('subscriptions', 0)}")
        print(f"- Customer Linked: {impact_data.get('customer_linked', False)}")

        # Let's also manually check what we can find for this member
        print(f"\nManual checks for {member_name}:")

        # Check memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "status": ["in", ["Active", "Pending"]], "docstatus": 1},
            fields=["name", "status", "membership_type"],
        )
        print(f"- Found {len(memberships)} active memberships:")
        for m in memberships:
            print(f"  * {m.name} ({m.status}) - {m.membership_type}")

        # Check SEPA mandates
        sepa_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member_name, "status": "Active", "is_active": 1},
            fields=["name", "mandate_id", "status"],
        )
        print(f"- Found {len(sepa_mandates)} active SEPA mandates:")
        for s in sepa_mandates:
            print(f"  * {s.name} ({s.mandate_id}) - {s.status}")

        # Check board positions via volunteer
        volunteers = frappe.get_all("Volunteer", filters={"member": member_name}, fields=["name"])
        print(f"- Found {len(volunteers)} volunteer records:")

        total_board_positions = 0
        for volunteer in volunteers:
            board_positions = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer.name, "is_active": 1},
                fields=["name", "role", "chapter"],
            )
            total_board_positions += len(board_positions)
            print(f"  * Volunteer {volunteer.name}: {len(board_positions)} board positions")
            for bp in board_positions:
                print(f"    - {bp.name}: {bp.role} at {bp.chapter}")

        # Check direct board positions (if member field exists)
        try:
            direct_positions = frappe.get_all(
                "Chapter Board Member",
                filters={"member": member_name, "is_active": 1},
                fields=["name", "role", "chapter"],
            )
            total_board_positions += len(direct_positions)
            print(f"- Found {len(direct_positions)} direct board positions:")
            for bp in direct_positions:
                print(f"  * {bp.name}: {bp.role} at {bp.chapter}")
        except Exception as e:
            print(f"- No direct board positions field or error: {e}")

        print(f"- Total board positions: {total_board_positions}")

        # Check customer and related records
        member_doc = frappe.get_doc("Member", member_name)
        if member_doc.customer:
            print(f"- Customer: {member_doc.customer}")

            # Check subscriptions
            subscriptions = frappe.get_all(
                "Subscription",
                filters={
                    "party_type": "Customer",
                    "party": member_doc.customer,
                    "status": ["in", ["Active", "Past Due"]]},
                fields=["name", "status"],
            )
            print(f"- Found {len(subscriptions)} active subscriptions:")
            for sub in subscriptions:
                print(f"  * {sub.name} - {sub.status}")

            # Check invoices
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "customer": member_doc.customer,
                    "docstatus": 1,
                    "status": ["in", ["Unpaid", "Overdue", "Partially Paid"]]},
                fields=["name", "status", "outstanding_amount"],
            )
            print(f"- Found {len(invoices)} outstanding invoices:")
            for inv in invoices:
                print(f"  * {inv.name} - {inv.status} (Outstanding: {inv.outstanding_amount})")
        else:
            print("- No customer linked")

        print("\nTest completed successfully!")
        return True

    except Exception as e:
        print(f"Error during test: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_termination_impact()

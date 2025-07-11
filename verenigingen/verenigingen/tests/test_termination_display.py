#!/usr/bin/env python3

import frappe


def test_termination_display():
    """Test the termination status display functionality."""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("Testing termination status display functionality...")

    # Check if termination_status_html field exists in Member DocType
    try:
        member_meta = frappe.get_meta("Member")
        html_field = None
        for field in member_meta.fields:
            if field.fieldname == "termination_status_html":
                html_field = field
                break

        if html_field:
            print("✓ termination_status_html field found in Member doctype")
            print(f"  Field type: {html_field.fieldtype}")
            print(f"  Field label: {html_field.label}")
        else:
            print("✗ termination_status_html field NOT found in Member doctype")
            return False
    except Exception as e:
        print(f"✗ Error checking Member doctype: {str(e)}")
        return False

    # Test the API function
    try:
        from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
            get_member_termination_status,
        )

        print("✓ get_member_termination_status function imported successfully")

        # Find a test member
        members = frappe.get_all("Member", limit=1, fields=["name", "full_name"])
        if members:
            member_name = members[0].name
            member_full_name = members[0].full_name
            print(f"Testing with member: {member_name} ({member_full_name})")

            status = get_member_termination_status(member_name)
            print(f"✓ API call successful, result type: {type(status)}")

            if isinstance(status, dict):
                print(f"  Keys in result: {list(status.keys())}")
                print(f"  Is terminated: {status.get('is_terminated', False)}")
                print(f"  Has active termination: {status.get('has_active_termination', False)}")
                print(f"  Pending requests: {len(status.get('pending_requests', []))}")
                print(f"  Executed requests: {len(status.get('executed_requests', []))}")

                # Test HTML field update functionality
                print("\nTesting HTML field update...")
                member_doc = frappe.get_doc("Member", member_name)

                # Check if the HTML field exists in the document
                if hasattr(member_doc, "termination_status_html"):
                    print("✓ termination_status_html field exists in member document")

                    # Simulate the HTML update that would happen in JavaScript
                    html_content = generate_termination_status_html(status)
                    print(f"✓ Generated HTML content ({len(html_content)} characters)")

                    # Test setting the field (don't save, just test the assignment)
                    member_doc.termination_status_html = html_content
                    print("✓ HTML field can be set successfully")

                else:
                    print("✗ termination_status_html field does not exist in member document")
                    return False

            else:
                print(f"✗ Unexpected result type: {type(status)}")
                return False
        else:
            print("✗ No members found for testing")
            return False

    except Exception as e:
        print(f"✗ Error testing get_member_termination_status: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ All termination status display tests passed!")
    return True


def generate_termination_status_html(status):
    """Generate HTML content for termination status display"""
    html = '<div class="termination-status-display">'

    if status.get("is_terminated") and status.get("executed_requests"):
        term_data = status["executed_requests"][0]
        html += f"""
            <div class="alert alert-danger">
                <h5><i class="fa fa-exclamation-triangle"></i> Membership Terminated</h5>
                <p><strong>Termination Type:</strong> {term_data.get('termination_type', 'Unknown')}</p>
                <p><strong>Execution Date:</strong> {term_data.get('execution_date', 'Unknown')}</p>
                <p><strong>Request:</strong> <a href="/app/membership-termination-request/{term_data.get('name', '')}">{term_data.get('name', '')}</a></p>
            </div>
        """
    elif status.get("pending_requests"):
        pending = status["pending_requests"][0]
        html += f"""
            <div class="alert alert-warning">
                <h5><i class="fa fa-clock-o"></i> Termination Request Pending</h5>
                <p><strong>Status:</strong> {pending.get('status', 'Unknown')}</p>
                <p><strong>Type:</strong> {pending.get('termination_type', 'Unknown')}</p>
                <p><strong>Request Date:</strong> {pending.get('request_date', 'Unknown')}</p>
                <p><strong>Request:</strong> <a href="/app/membership-termination-request/{pending.get('name', '')}">{pending.get('name', '')}</a></p>
            </div>
        """
    else:
        html += """
            <div class="alert alert-success">
                <h6><i class="fa fa-check-circle"></i> Active Membership</h6>
                <p>No termination requests or actions on record.</p>
            </div>
        """

    html += "</div>"
    return html


if __name__ == "__main__":
    test_termination_display()

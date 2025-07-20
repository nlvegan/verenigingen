"""
Customer to Member Navigation Enhancement

Adds navigation links from Customer to Member records
"""

import frappe
from frappe import _


def add_customer_to_member_link():
    """Add Member link to Customer dashboard"""
    try:
        # Check if the link already exists
        existing_links = frappe.get_all(
            "DocType Link", filters={"parent": "Customer", "parenttype": "DocType", "link_doctype": "Member"}
        )

        if existing_links:
            return {"message": "Link already exists", "success": True}

        # Get Customer doctype
        customer_doc = frappe.get_doc("DocType", "Customer")

        # Add Member link
        customer_doc.append(
            "links",
            {"link_doctype": "Member", "link_fieldname": "customer", "group": "Membership", "hidden": 0},
        )

        customer_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {"message": "Customer to Member link added successfully", "success": True}

    except Exception as e:
        frappe.log_error(f"Error adding customer to member link: {str(e)}")
        return {"message": f"Error: {str(e)}", "success": False}


@frappe.whitelist()
def get_member_from_customer(customer):
    """Get member associated with a customer"""
    # First try the new direct customer.member field
    member_name = frappe.db.get_value("Customer", customer, "member")
    if member_name:
        member = frappe.db.get_value("Member", member_name, ["name", "full_name", "status"], as_dict=True)
        if member:
            return member

    # Fallback to old method: search Member table for customer field
    member = frappe.db.get_value(
        "Member", {"customer": customer}, ["name", "full_name", "status"], as_dict=True
    )
    if member:
        return member
    return None


@frappe.whitelist()
def create_customer_member_button():
    """Add a custom button to Customer form to navigate to Member"""
    return """
    frappe.ui.form.on('Customer', {
        refresh: function(frm) {
            if (!frm.is_new()) {
                frappe.call({
                    method: 'verenigingen.api.customer_member_link.get_member_from_customer',
                    args: {
                        customer: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.add_custom_button(__('View Member'), function() {
                                frappe.set_route('Form', 'Member', r.message.name);
                            }, __('Actions'));

                            // Also show member status in dashboard
                            frm.dashboard.add_indicator(__('Member: ') + r.message.full_name + ' (' + r.message.status + ')',
                                r.message.status === 'Active' ? 'green' : 'orange');
                        }
                    }
                });
            }
        }
    });
    """

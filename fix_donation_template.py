#!/usr/bin/env python3

import frappe


def fix_donation_template():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        template = frappe.get_doc("Email Template", "donation_payment_confirmation")

        print("Current subject:", template.subject)
        print("Current response (first 200 chars):", template.response[:200])

        # Fix the template to use correct variable names
        new_response = template.response.replace("{{ doc.name }}", "{{ donation_id }}")
        new_response = new_response.replace("{{ doc.amount }}", "{{ amount }}")

        new_subject = template.subject.replace("{{ doc.name }}", "{{ donation_id }}")

        template.response = new_response
        template.subject = new_subject
        template.save()

        print("\nTemplate fixed successfully!")
        print("New subject:", template.subject)

    except frappe.DoesNotExistError:
        print("Template 'donation_payment_confirmation' not found")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        frappe.destroy()


if __name__ == "__main__":
    fix_donation_template()

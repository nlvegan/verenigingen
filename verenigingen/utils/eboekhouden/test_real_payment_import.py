"""
Test enhanced payment import with real E-Boekhouden data.
"""

import json

import frappe
from frappe import _


@frappe.whitelist()
def test_payment_import_from_api(mutation_id=5473):
    """
    Test payment import using a real mutation from E-Boekhouden API.

    Default mutation 5473 is a multi-invoice supplier payment.
    """
    from verenigingen.utils.eboekhouden.eboekhouden_rest_client import EBoekhoudenRESTClient
    from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import _process_single_mutation

    company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
    cost_center = frappe.db.get_single_value("Company", company, "cost_center")
    debug_info = []

    try:
        # Get mutation from API
        client = EBoekhoudenRESTClient()
        mutation = client.get_mutation_by_id(mutation_id)

        if not mutation:
            return {"success": False, "error": f"Mutation {mutation_id} not found in E-Boekhouden"}

        # Check if it's a payment mutation
        if mutation.get("type") not in [3, 4]:
            return {
                "success": False,
                "error": f"Mutation {mutation_id} is type {mutation.get('type')}, not a payment (3 or 4)",
            }

        # Process the mutation
        result = _process_single_mutation(mutation, company, cost_center, debug_info, None)  # batch_status

        # Analyze results
        payment_created = False
        payment_name = None
        bank_account = None

        for log in debug_info:
            if "Created Payment Entry" in log:
                payment_created = True
                # Extract payment name
                parts = log.split()
                payment_name = parts[-1]
            elif "Enhanced payment creation failed" in log:
                payment_created = False

        if payment_name and frappe.db.exists("Payment Entry", payment_name):
            pe = frappe.get_doc("Payment Entry", payment_name)
            bank_account = pe.paid_to if pe.payment_type == "Receive" else pe.paid_from

            analysis = {
                "payment_entry": payment_name,
                "payment_type": pe.payment_type,
                "amount": pe.paid_amount or pe.received_amount,
                "bank_account": bank_account,
                "party": pe.party,
                "reference": pe.reference_no,
                "references_count": len(pe.references),
                "is_hardcoded_kas": "Kas" in bank_account,
            }
        else:
            analysis = {"error": "Payment not created"}

        return {
            "success": payment_created,
            "mutation_data": {
                "id": mutation.get("id"),
                "type": mutation.get("type"),
                "amount": mutation.get("amount"),
                "ledgerId": mutation.get("ledgerId"),
                "invoiceNumber": mutation.get("invoiceNumber"),
                "rows": len(mutation.get("rows", [])),
            },
            "analysis": analysis,
            "debug_log": debug_info[-10:],  # Last 10 entries
        }

    except Exception as e:
        return {"success": False, "error": str(e), "debug_log": debug_info}


@frappe.whitelist()
def compare_old_vs_new_payment():
    """
    Compare a payment created with old logic vs new logic.
    """
    # Find a recent payment created with hardcoded Kas
    old_payment = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.eboekhouden_mutation_nr,
            pe.paid_to,
            pe.paid_from,
            pe.payment_type,
            pe.party,
            pe.reference_no,
            COUNT(per.name) as ref_count
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        WHERE (pe.paid_to = '10000 - Kas - NVV' OR pe.paid_from = '10000 - Kas - NVV')
        AND pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        GROUP BY pe.name
        ORDER BY pe.creation DESC
        LIMIT 1
    """,
        as_dict=True,
    )

    if not old_payment:
        return {"error": "No payments found with hardcoded Kas account"}

    old = old_payment[0]
    mutation_id = old.eboekhouden_mutation_nr

    # Test with new handler
    from verenigingen.utils.eboekhouden.eboekhouden_rest_client import EBoekhoudenRESTClient
    from verenigingen.utils.eboekhouden.payment_processing import PaymentEntryHandler

    try:
        # Get mutation data
        client = EBoekhoudenRESTClient()
        mutation = client.get_mutation_by_id(int(mutation_id))

        if not mutation:
            return {"error": f"Could not fetch mutation {mutation_id} from API"}

        # Process with new handler
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        handler = PaymentEntryHandler(company)

        # Just test bank account determination
        new_bank = handler._determine_bank_account(mutation.get("ledgerId"), old.payment_type)

        comparison = {
            "mutation_id": mutation_id,
            "old_payment": {
                "name": old.name,
                "bank_account": old.paid_to if old.payment_type == "Receive" else old.paid_from,
                "references": old.ref_count,
                "reference_no": old.reference_no,
            },
            "new_logic": {
                "would_use_bank": new_bank,
                "is_improvement": new_bank and "Kas" not in new_bank,
                "invoices_parsed": len(handler._parse_invoice_numbers(mutation.get("invoiceNumber", ""))),
            },
            "mutation_details": {
                "type": mutation.get("type"),
                "ledgerId": mutation.get("ledgerId"),
                "invoiceNumber": mutation.get("invoiceNumber"),
            },
        }

        return comparison

    except Exception as e:
        return {"error": str(e), "mutation_id": mutation_id}


@frappe.whitelist()
def enable_enhanced_payment_processing():
    """Enable enhanced payment processing in settings."""
    try:
        # Check if setting exists
        if not frappe.db.has_column("E-Boekhouden Settings", "use_enhanced_payment_processing"):
            # Add the column
            frappe.db.sql(
                """
                ALTER TABLE `tabE-Boekhouden Settings`
                ADD COLUMN use_enhanced_payment_processing INT(1) DEFAULT 1
            """
            )
            frappe.db.commit()

        # Set to enabled
        frappe.db.set_single_value("E-Boekhouden Settings", "use_enhanced_payment_processing", 1)

        return {"success": True, "message": "Enhanced payment processing enabled"}
    except Exception as e:
        return {"success": False, "error": str(e)}

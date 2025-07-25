"""
Create unreconciled Payment Entries for E-Boekhouden payments without matching invoices
"""

import frappe
from pymysql.err import IntegrityError


def create_unreconciled_payment_entry(mutation, company, cost_center, payment_type="Customer"):
    """
    Create an unreconciled Payment Entry when invoice cannot be found

    Args:
        mutation: E-Boekhouden mutation data
        company: Company name
        cost_center: Cost center
        payment_type: "Customer" or "Supplier"

    Returns:
        dict with success status and created Payment Entry name or error
    """
    try:
        from .eboekhouden_payment_naming import enhance_payment_entry_fields, get_payment_entry_title
        from .eboekhouden_soap_migration import (
            get_bank_account,
            get_or_create_customer,
            get_or_create_supplier,
            parse_date,
        )

        # Check if payment already exists for this mutation
        mutation_nr = mutation.get("MutatieNr")
        if mutation_nr:
            # Check both reference_no AND eboekhouden_mutation_nr fields
            existing_payment = frappe.db.exists(
                "Payment Entry", [["reference_no", "=", mutation_nr], ["docstatus", "!=", 2]]  # Not cancelled
            )

            if not existing_payment:
                # Also check the custom field if it exists
                existing_payment = frappe.db.exists(
                    "Payment Entry",
                    [["eboekhouden_mutation_nr", "=", mutation_nr], ["docstatus", "!=", 2]],  # Not cancelled
                )

            if existing_payment:
                # Payment already exists for this mutation, return success
                return {"success": True, "payment_entry": existing_payment, "already_exists": True}

        # Create payment entry
        pe = frappe.new_doc("Payment Entry")

        # Basic settings based on payment type
        if payment_type == "Customer":
            pe.payment_type = "Receive"
            pe.party_type = "Customer"

            # Try to identify customer from description or create generic one
            relation_code = mutation.get("RelatieCode")
            description = mutation.get("Omschrijving", "")

            if relation_code:
                pe.party = get_or_create_customer(relation_code, description, relation_data=None)
            else:
                # Try to extract party info from description
                # For SEPA transfers, the description often contains the party name
                if description and len(description) > 10:
                    # Import the SEPA extraction function
                    from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

                    # Try to extract meaningful name from SEPA description
                    extractor = EBoekhoudenPartyExtractor()
                    extracted_name = extractor._extract_party_name_from_description(description)

                    MAX_CUSTOMER_NAME_LENGTH = 140
                    prefix = "Unmatched Payment - "

                    if extracted_name:
                        # Use the extracted name
                        base_name = extracted_name
                    else:
                        # Fallback to truncated description
                        max_desc_length = MAX_CUSTOMER_NAME_LENGTH - len(prefix) - 3
                        base_name = (
                            description[:max_desc_length] + "..."
                            if len(description) > max_desc_length
                            else description
                        )

                    customer_name = f"{prefix}{base_name}"

                    # Final truncation check
                    if len(customer_name) > MAX_CUSTOMER_NAME_LENGTH:
                        customer_name = customer_name[: MAX_CUSTOMER_NAME_LENGTH - 3] + "..."

                    # Check if this customer already exists
                    existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
                    if existing:
                        pe.party = existing
                    else:
                        # Create new customer
                        customer = frappe.new_doc("Customer")
                        customer.customer_name = customer_name
                        customer.customer_group = (
                            frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
                            or "All Customer Groups"
                        )
                        customer.territory = (
                            frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
                        )

                        # Store full SEPA description if it was truncated
                        if len(description) > 50:
                            customer.customer_details = f"SEPA Payment Description:\n{description}"

                        customer.insert(ignore_permissions=True)
                        pe.party = customer.name
                else:
                    pe.party = get_or_create_customer(
                        "UNMATCHED", "Unmatched Customer Payment", relation_data=None
                    )

        else:  # Supplier
            pe.payment_type = "Pay"
            pe.party_type = "Supplier"

            # Try to identify supplier
            relation_code = mutation.get("RelatieCode")
            description = mutation.get("Omschrijving", "")

            if relation_code:
                # Ensure supplier exists before creating payment
                supplier = get_or_create_supplier(relation_code, description, relation_data=None)
                if not supplier:
                    return {"success": False, "error": f"Could not create supplier for code {relation_code}"}
                pe.party = supplier
            else:
                # Try to extract party info from description
                if description and len(description) > 10:
                    # Import the SEPA extraction function
                    from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

                    # Try to extract meaningful name from SEPA description
                    extractor = EBoekhoudenPartyExtractor()
                    extracted_name = extractor._extract_party_name_from_description(description)

                    MAX_SUPPLIER_NAME_LENGTH = 140
                    prefix = "Unmatched Payment - "

                    if extracted_name:
                        # Use the extracted name
                        # base_name = extracted_name
                        supplier_name = f"{prefix}{extracted_name}"
                    else:
                        # Fallback to truncated description
                        max_desc_length = MAX_SUPPLIER_NAME_LENGTH - len(prefix) - 3
                        base_name = (
                            description[:max_desc_length] + "..."
                            if len(description) > max_desc_length
                            else description
                        )
                        supplier_name = f"{prefix}{base_name}"

                    # Final truncation check
                    if len(supplier_name) > MAX_SUPPLIER_NAME_LENGTH:
                        supplier_name = supplier_name[: MAX_SUPPLIER_NAME_LENGTH - 3] + "..."

                    # Check if this supplier already exists
                    existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
                    if existing:
                        pe.party = existing
                    else:
                        # Create new supplier
                        supplier = frappe.new_doc("Supplier")
                        supplier.supplier_name = supplier_name
                        supplier.supplier_group = (
                            frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
                            or "All Supplier Groups"
                        )

                        # Store full SEPA description if it was truncated
                        if len(description) > 50:
                            supplier.supplier_details = f"SEPA Payment Description:\n{description}"

                        supplier.insert(ignore_permissions=True)
                        pe.party = supplier.name
                else:
                    pe.party = get_or_create_supplier(
                        "UNMATCHED", "Unmatched Supplier Payment", relation_data=None
                    )

        # Common fields
        pe.company = company
        pe.posting_date = parse_date(mutation.get("Datum"))
        pe.cost_center = cost_center

        # Set title with clear indication that it's unreconciled
        original_title = get_payment_entry_title(mutation, pe.party, pe.payment_type, relation_data=None)
        if hasattr(pe, "title"):
            pe.title = f"[UNRECONCILED] {original_title}"

        # Enhance with E-Boekhouden data
        pe = enhance_payment_entry_fields(pe, mutation)

        # Get amount from mutation lines
        total_amount = 0
        for regel in mutation.get("MutatieRegels", []):
            # Try different amount fields
            amount = float(
                regel.get("BedragInclBTW", 0) or regel.get("BedragInvoer", 0) or regel.get("BedragExclBTW", 0)
            )
            total_amount += abs(amount)

        if total_amount == 0:
            return {"success": False, "error": "No amount found in mutation"}

        pe.paid_amount = total_amount
        pe.received_amount = total_amount

        # Set reference information
        pe.reference_no = mutation.get("MutatieNr")
        pe.reference_date = pe.posting_date

        # Import naming functions and set enhanced title
        from .eboekhouden_payment_naming import enhance_payment_entry_fields, get_payment_entry_title

        pe.title = get_payment_entry_title(mutation, pe.party, pe.payment_type)

        # Enhance payment entry fields (this handles remarks with all details)
        enhance_payment_entry_fields(pe, mutation)

        # Add unreconciled invoice information to remarks
        invoice_no = mutation.get("Factuurnummer")
        if invoice_no:
            additional_remarks = f"\n\nUnreconciled Invoice: {invoice_no}"
            if pe.remarks:
                pe.remarks += additional_remarks
            else:
                pe.remarks = additional_remarks

        # Set bank accounts
        bank_code = mutation.get("Rekening")
        bank_account = get_bank_account(bank_code, company)

        if pe.payment_type == "Receive":
            pe.paid_to = bank_account
            # Set default receivable account
            default_receivable = frappe.db.get_value("Company", company, "default_receivable_account")
            if not default_receivable:
                # Find any receivable account
                default_receivable = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
                )
            pe.paid_from = default_receivable
        else:  # Pay
            pe.paid_from = bank_account
            # Set default payable account
            default_payable = frappe.db.get_value("Company", company, "default_payable_account")
            if not default_payable:
                # Find any payable account
                default_payable = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Payable", "is_group": 0}, "name"
                )
            pe.paid_to = default_payable

        # Set mode of payment (optional)
        default_mode = frappe.db.get_value("Mode of Payment", {"type": "Bank"}, "name")
        if default_mode:
            pe.mode_of_payment = default_mode

        # Insert and submit
        try:
            pe.insert(ignore_permissions=True)
            pe.submit()
            return {"success": True, "payment_entry": pe.name}
        except IntegrityError as ie:
            if "Duplicate entry" in str(ie) and "eboekhouden_mutation_nr" in str(ie):
                # This payment was already created (race condition or retry)
                frappe.db.rollback()
                # Try to find the existing payment
                existing = frappe.db.get_value(
                    "Payment Entry",
                    {"eboekhouden_mutation_nr": mutation.get("MutatieNr"), "docstatus": ["!=", 2]},
                    "name",
                )
                if existing:
                    return {"success": True, "payment_entry": existing, "already_exists": True}
                else:
                    return {"success": False, "error": "Duplicate payment exists but could not be found"}
            else:
                # Re-raise other integrity errors
                raise

    except IntegrityError as ie:
        if "Duplicate entry" in str(ie) and "eboekhouden_mutation_nr" in str(ie):
            # This payment was already created, treat as success
            frappe.db.rollback()
            return {"success": True, "payment_entry": None, "already_exists": True}
        else:
            # Truncate error message for title (max 140 chars)
            error_msg = str(ie)
            title = f"Failed to create unreconciled payment: {error_msg}"[:140]
            frappe.log_error(error_msg, title)
            return {"success": False, "error": error_msg}
    except Exception as e:
        # Truncate error message for title (max 140 chars)
        error_msg = str(e)
        title = f"Failed to create unreconciled payment: {error_msg}"[:140]
        frappe.log_error(error_msg, title)
        return {"success": False, "error": error_msg}

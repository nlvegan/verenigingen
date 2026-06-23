"""
E-Boekhouden Transaction Processing Utilities

Conservative refactor: These transaction processing methods were moved from the main
migration file for better organization. All original logic is preserved exactly as-is.
"""

import json

import frappe
from frappe.utils import flt, getdate

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.utils.secure_operations import secure_document_operation


def create_customer_impl(migration_doc, customer_data):
    """Create customer from E-Boekhouden data"""
    try:
        # Extract customer information
        company_name = customer_data.get("Bedrijf", "").strip()
        contact_name = customer_data.get("Contactpersoon", "").strip()

        # Determine customer name
        if company_name and contact_name:
            customer_name = f"{company_name} ({contact_name})"
        elif company_name:
            customer_name = company_name
        elif contact_name:
            customer_name = contact_name
        else:
            customer_name = f"Customer {customer_data.get('ID', 'Unknown')}"

        # Check if customer already exists
        existing_customer = frappe.db.exists("Customer", {"customer_name": customer_name})
        if existing_customer:
            return {"success": True, "customer": existing_customer, "created": False}

        # Create new customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Company" if company_name else "Individual"
        # Resolve a leaf Customer Group (the previous logic would happily
        # fall back to "All Customer Groups", a group node that ERPNext's
        # validate_customer_group rejects with "Cannot select a Group type
        # Customer Group" - same bug as the membership flow had pre-PR #54).
        customer.customer_group = resolve_non_group_customer_group()
        customer.territory = migration_doc.get_proper_territory_for_customer(customer_data)
        customer.company = migration_doc.company

        # Save customer
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=customer,
            justification=f"Create customer '{customer_name}' from E-Boekhouden import - accounting integration for customer synchronization",
            required_permissions=["Customer:create"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to create customer from E-Boekhouden: {'; '.join(result.errors)}",
                "E-Boekhouden Customer Security",
            )
            return {"success": False, "error": f"Failed to create customer: {'; '.join(result.errors)}"}

        # Create contact and address
        migration_doc.create_contact_for_customer(customer.name, customer_data)
        migration_doc.create_address_for_customer(customer.name, customer_data)

        return {"success": True, "customer": customer.name, "created": True}

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_supplier_impl(migration_doc, supplier_data):
    """Create supplier from E-Boekhouden data"""
    try:
        # Extract supplier information
        company_name = supplier_data.get("Bedrijf", "").strip()
        contact_name = supplier_data.get("Contactpersoon", "").strip()

        # Determine supplier name
        if company_name and contact_name:
            supplier_name = f"{company_name} ({contact_name})"
        elif company_name:
            supplier_name = company_name
        elif contact_name:
            supplier_name = contact_name
        else:
            supplier_name = f"Supplier {supplier_data.get('ID', 'Unknown')}"

        # Check if supplier already exists
        existing_supplier = frappe.db.exists("Supplier", {"supplier_name": supplier_name})
        if existing_supplier:
            return {"success": True, "supplier": existing_supplier, "created": False}

        # Create new supplier
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_type = "Company" if company_name else "Individual"
        supplier.supplier_group = (
            frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"
        )
        supplier.company = migration_doc.company

        # Save supplier
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=supplier,
            justification=f"Create supplier '{supplier_name}' from E-Boekhouden import - accounting integration for supplier synchronization",
            required_permissions=["Supplier:create"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to create supplier from E-Boekhouden: {'; '.join(result.errors)}",
                "E-Boekhouden Supplier Security",
            )
            return {"success": False, "error": f"Failed to create supplier: {'; '.join(result.errors)}"}

        # Create contact and address
        migration_doc.create_contact_for_supplier(supplier.name, supplier_data)
        migration_doc.create_address_for_supplier(supplier.name, supplier_data)

        return {"success": True, "supplier": supplier.name, "created": True}

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_journal_entry_impl(migration_doc, transaction_data):
    """Create journal entry from E-Boekhouden transaction data"""
    try:
        # Extract transaction details
        posting_date = getdate(transaction_data.get("Datum"))
        reference = transaction_data.get("Omschrijving", "")

        # Create journal entry
        je = frappe.new_doc("Journal Entry")
        je.posting_date = posting_date
        je.voucher_type = "Journal Entry"
        je.company = migration_doc.company
        je.user_remark = reference
        je.eboekhouden_mutation_nr = transaction_data.get("MutatieNr")

        total_debit = 0
        total_credit = 0

        # Process transaction lines
        for line in transaction_data.get("Regels", []):
            account_code = line.get("TegenrekeningCode")
            amount = flt(line.get("BedragExclBTW", 0))
            description = line.get("Omschrijving", reference)

            # Get ERPNext account from mapping
            erpnext_account = migration_doc.get_mapped_account(account_code)
            if not erpnext_account:
                erpnext_account = migration_doc.get_suspense_account(migration_doc.company)

            # Add journal entry account line.
            # NB: do NOT set reference_type/reference_name to point at this JE
            # itself - the parent name is empty at append time (doc unsaved) and
            # ERPNext's validate_against_jv rejects a reference document on any
            # *debited* account ("you can select reference document only if
            # account gets credited"), which aborted every import with a debit
            # line. These are plain GL postings, not payments against a voucher.
            je_account = je.append("accounts")
            je_account.account = erpnext_account

            if amount > 0:
                je_account.debit_in_account_currency = amount
                total_debit += amount
            else:
                je_account.credit_in_account_currency = abs(amount)
                total_credit += abs(amount)

            je_account.user_remark = description

        # Ensure balanced entry
        if abs(total_debit - total_credit) > 0.01:
            # Add balancing entry to suspense account
            suspense_account = migration_doc.get_suspense_account(migration_doc.company)
            balance_amount = total_debit - total_credit

            je_account = je.append("accounts")
            je_account.account = suspense_account
            je_account.user_remark = "Balancing entry for E-Boekhouden import"

            if balance_amount < 0:
                je_account.debit_in_account_currency = abs(balance_amount)
            else:
                je_account.credit_in_account_currency = balance_amount

        # Save and submit journal entry
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=je,
            justification="Create journal entry from E-Boekhouden import - accounting integration for financial data synchronization",
            required_permissions=["Journal Entry:create"],
        )

        if not result.success:
            frappe.log_error(
                "Failed to save journal entry from E-Boekhouden: " + "; ".join(result.errors),
                "E-Boekhouden JE Security",
            )
            return {"success": False, "error": f"Failed to save journal entry: {'; '.join(result.errors)}"}

        je.submit()

        return {"success": True, "journal_entry": je.name}

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_sales_invoice_impl(migration_doc, invoice_data):
    """Create sales invoice from E-Boekhouden data"""
    try:
        # Extract invoice details
        posting_date = getdate(invoice_data.get("Datum"))
        # Safely extract customer relation data
        relatie_data = invoice_data.get("Relatie")
        if not relatie_data or not isinstance(relatie_data, dict):
            frappe.throw("Invalid invoice data: missing or invalid Relatie information")
        customer_id = relatie_data.get("ID")
        if not customer_id:
            frappe.throw("Invalid invoice data: missing customer ID in Relatie information")

        # Get or create customer
        customer_result = migration_doc.create_customer(invoice_data.get("Relatie", {}))
        if not customer_result["success"]:
            return customer_result

        # Create sales invoice
        si = frappe.new_doc("Sales Invoice")
        si.posting_date = posting_date
        si.due_date = posting_date  # Will be updated based on payment terms
        si.customer = customer_result["customer"]
        si.company = migration_doc.company
        si.eboekhouden_invoice_number = invoice_data.get("Factuurnummer")
        si.eboekhouden_relation_id = customer_id

        # Check for credit notes and handle negative amounts (same logic as main migration)
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            _detect_credit_note_improved,
        )

        is_credit_note, effective_total_amount = _detect_credit_note_improved(invoice_data, [])
        si.is_return = is_credit_note

        # Process invoice lines
        for line in invoice_data.get("Regels", []):
            item_description = line.get("Omschrijving", "Service Item")

            # Handle quantities properly for credit notes
            raw_quantity = line.get("Aantal", 1)
            if is_credit_note and raw_quantity > 0:
                # For Sales Invoice credit notes, ERPNext expects negative quantities
                quantity = -abs(flt(raw_quantity))
            else:
                # Preserve negative quantities if already negative, or use positive for normal invoices
                quantity = flt(raw_quantity) if raw_quantity >= 0 else raw_quantity

            rate = abs(flt(line.get("PrijsExclBTW", 0)))  # Always positive for ERPNext

            # Get or create item using intelligent creation
            from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import (
                get_or_create_item_improved,
            )
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                _get_ledger_code_from_id,
            )

            # Resolve ledger ID to account code for proper mapping
            raw_tegenrekening = line.get("TegenrekeningCode", "")
            debug_info = []
            account_code = _get_ledger_code_from_id(raw_tegenrekening, debug_info)

            item_code = get_or_create_item_improved(
                account_code=account_code,
                company=migration_doc.company,
                transaction_type="Sales",
                description=item_description,
            )

            # Add invoice item
            si_item = si.append("items")
            si_item.item_code = item_code
            si_item.item_name = item_description
            si_item.description = item_description
            si_item.qty = quantity
            si_item.rate = rate
            si_item.amount = quantity * rate

            # Set income account
            income_account = migration_doc.get_mapped_account(line.get("TegenrekeningCode"))
            if income_account:
                si_item.income_account = income_account

        # Add taxes if present
        btw_amount = flt(invoice_data.get("BTWBedrag", 0))
        if btw_amount > 0:
            tax_account = migration_doc.get_mapped_account("1520")  # Default BTW account
            if tax_account:
                tax_row = si.append("taxes")
                tax_row.charge_type = "Actual"
                tax_row.account_head = tax_account
                tax_row.tax_amount = btw_amount
                tax_row.description = "BTW"

        # Save and submit
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=si,
            justification="Create sales invoice from E-Boekhouden import - accounting integration for sales data synchronization",
            required_permissions=["Sales Invoice:create"],
        )

        if not result.success:
            frappe.log_error(
                "Failed to save sales invoice from E-Boekhouden: " + "; ".join(result.errors),
                "E-Boekhouden SI Security",
            )
            return {"success": False, "error": f"Failed to save sales invoice: {'; '.join(result.errors)}"}

        si.submit()

        return {"success": True, "sales_invoice": si.name}

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_purchase_invoice_impl(migration_doc, invoice_data):
    """Create purchase invoice from E-Boekhouden data"""
    try:
        # Extract invoice details
        posting_date = getdate(invoice_data.get("Datum"))
        # Safely extract supplier relation data
        relatie_data = invoice_data.get("Relatie")
        if not relatie_data or not isinstance(relatie_data, dict):
            frappe.throw("Invalid invoice data: missing or invalid Relatie information")
        supplier_id = relatie_data.get("ID")
        if not supplier_id:
            frappe.throw("Invalid invoice data: missing supplier ID in Relatie information")

        # Get or create supplier
        supplier_result = migration_doc.create_supplier(invoice_data.get("Relatie", {}))
        if not supplier_result["success"]:
            return supplier_result

        # Create purchase invoice
        pi = frappe.new_doc("Purchase Invoice")
        pi.posting_date = posting_date
        pi.due_date = posting_date  # Will be updated based on payment terms
        pi.supplier = supplier_result["supplier"]
        pi.company = migration_doc.company
        pi.eboekhouden_invoice_number = invoice_data.get("Factuurnummer")
        pi.eboekhouden_relation_id = supplier_id

        # Check for credit notes and handle negative amounts (same logic as main migration)
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            _detect_credit_note_improved,
        )

        is_credit_note, effective_total_amount = _detect_credit_note_improved(invoice_data, [])
        pi.is_return = is_credit_note

        # Process invoice lines
        for line in invoice_data.get("Regels", []):
            item_description = line.get("Omschrijving", "Service Item")

            # Handle quantities properly for credit notes
            raw_quantity = line.get("Aantal", 1)
            if is_credit_note and raw_quantity > 0:
                # For Purchase Invoice credit notes, ERPNext expects negative quantities
                quantity = -abs(flt(raw_quantity))
            else:
                # Preserve negative quantities if already negative, or use positive for normal invoices
                quantity = flt(raw_quantity) if raw_quantity >= 0 else raw_quantity

            rate = abs(flt(line.get("PrijsExclBTW", 0)))  # Always positive for ERPNext

            # Get or create item using intelligent creation
            from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import (
                get_or_create_item_improved,
            )
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                _get_ledger_code_from_id,
            )

            # Resolve ledger ID to account code for proper mapping
            raw_tegenrekening = line.get("TegenrekeningCode", "")
            debug_info = []
            account_code = _get_ledger_code_from_id(raw_tegenrekening, debug_info)

            item_code = get_or_create_item_improved(
                account_code=account_code,
                company=migration_doc.company,
                transaction_type="Purchase",
                description=item_description,
            )

            # Add invoice item
            pi_item = pi.append("items")
            pi_item.item_code = item_code
            pi_item.item_name = item_description
            pi_item.description = item_description
            pi_item.qty = quantity
            pi_item.rate = rate
            pi_item.amount = quantity * rate

            # Set expense account
            expense_account = migration_doc.get_mapped_account(line.get("TegenrekeningCode"))
            if expense_account:
                pi_item.expense_account = expense_account

        # Add taxes if present
        btw_amount = flt(invoice_data.get("BTWBedrag", 0))
        if btw_amount > 0:
            tax_account = migration_doc.get_mapped_account("1520")  # Default BTW account
            if tax_account:
                tax_row = pi.append("taxes")
                tax_row.charge_type = "Actual"
                tax_row.account_head = tax_account
                tax_row.tax_amount = btw_amount
                tax_row.description = "BTW"

        # Save and submit
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=pi,
            justification="Create purchase invoice from E-Boekhouden import - accounting integration for purchase data synchronization",
            required_permissions=["Purchase Invoice:create"],
        )

        if not result.success:
            frappe.log_error(
                "Failed to save purchase invoice from E-Boekhouden: " + "; ".join(result.errors),
                "E-Boekhouden PI Security",
            )
            return {"success": False, "error": f"Failed to save purchase invoice: {'; '.join(result.errors)}"}

        pi.submit()

        return {"success": True, "purchase_invoice": pi.name}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_mapped_account_impl(migration_doc, eboekhouden_code):
    """Get ERPNext account mapped to E-Boekhouden code"""
    try:
        # Check for existing mapping
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_code": eboekhouden_code}, "erpnext_account"
        )

        if mapping:
            return mapping

        # Try to find account by E-Boekhouden code - multiple lookup methods
        # 1. First try eboekhouden_grootboek_nummer (custom field)
        account = frappe.db.get_value(
            "Account",
            {"company": migration_doc.company, "eboekhouden_grootboek_nummer": eboekhouden_code},
            "name",
        )

        # 2. If not found, try account_number (standard field from CoA import)
        if not account:
            account = frappe.db.get_value(
                "Account",
                {"company": migration_doc.company, "account_number": eboekhouden_code},
                "name",
            )

        # 3. If still not found, try by name pattern
        if not account:
            company_abbr = frappe.db.get_value("Company", migration_doc.company, "abbr")
            if company_abbr:
                name_pattern = f"{eboekhouden_code} - % - {company_abbr}"
                account = frappe.db.get_value(
                    "Account",
                    {"company": migration_doc.company, "name": ("like", name_pattern)},
                    "name",
                )

        return account

    except Exception:
        return None


def get_suspense_account_impl(migration_doc, company):
    """Get or create suspense account for unbalanced entries"""
    try:
        # Check if suspense account exists
        suspense_account = frappe.db.get_value(
            "Account", {"company": company, "account_name": "E-Boekhouden Suspense"}, "name"
        )

        if suspense_account:
            return suspense_account

        # Create suspense account
        suspense = frappe.new_doc("Account")
        suspense.account_name = "E-Boekhouden Suspense"
        suspense.company = company
        suspense.account_type = "Temporary"
        suspense.is_group = 0
        suspense.parent_account = migration_doc.get_parent_account("Temporary", "Asset", company)

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=suspense,
            justification=f"Create E-Boekhouden suspense account for company {company} - accounting integration for transaction processing",
            required_permissions=["Account:create"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to create E-Boekhouden suspense account: {'; '.join(result.errors)}",
                "E-Boekhouden Account Security",
            )
            frappe.throw(f"Failed to create suspense account: {'; '.join(result.errors)}")

        return suspense.name

    except Exception as e:
        frappe.logger().error(f"Failed to get/create suspense account: {str(e)}")
        return None

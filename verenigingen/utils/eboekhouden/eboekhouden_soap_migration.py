"""
E-Boekhouden SOAP-based migration

⚠️ DEPRECATED - DO NOT USE THIS MODULE ⚠️
========================================
This SOAP-based migration is DEPRECATED and should NOT be used.
The SOAP API is limited to only 500 most recent transactions!

✅ USE eboekhouden_rest_full_migration.py INSTEAD ✅
The REST API migration provides:
- Access to complete transaction history
- No 500 transaction limit
- Better performance
- More reliable data import

This file is maintained only for backward compatibility.
========================================

Uses the SOAP API to get complete mutation data including descriptions and transaction types
"""

from collections import defaultdict

import frappe
from pymysql.err import IntegrityError


def migrate_using_soap(migration_doc, settings, use_account_mappings=True):
    """
    Main migration function using hybrid SOAP/REST approach:
    - SOAP for Chart of Accounts and Relations
    - REST for Mutations (to overcome 500-record limitation)

    Args:
        migration_doc: The migration document
        settings: E-Boekhouden settings
        use_account_mappings: Whether to use account mappings for document type determination
    """
    from .eboekhouden_soap_api import EBoekhoudenSOAPAPI

    # Pre-migration fixes
    try:
        # Fix known cost center issues
        cost_centers = frappe.db.get_all(
            "Cost Center",
            filters={"cost_center_name": ["like", "%maanden - NVV%"]},
            fields=["name", "is_group"],
        )

        for cc in cost_centers:
            if not cc.is_group:
                frappe.db.set_value("Cost Center", cc.name, "is_group", 1)
                frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Cost center fix error: {str(e)}", "E-Boekhouden Pre-Migration")

    try:
        api = EBoekhoudenSOAPAPI(settings)
        company = settings.default_company

        if not company:
            return {"success": False, "error": "No default company set"}

        # Get cost center - try multiple approaches
        cost_center = None

        # First try to get Main cost center (non-group)
        cost_center = frappe.db.get_value(
            "Cost Center", {"company": company, "cost_center_name": "Main", "is_group": 0}, "name"
        )

        # If still not found, try company abbreviation pattern
        if not cost_center:
            abbr = frappe.db.get_value("Company", company, "abbr")
            if abbr:
                cost_center = f"{company} - {abbr}"
                if not frappe.db.exists("Cost Center", cost_center):
                    cost_center = None

        # If still not found, try to get Main cost center
        if not cost_center:
            cost_center = frappe.db.get_value(
                "Cost Center", {"company": company, "cost_center_name": "Main", "is_group": 0}, "name"
            )

        # If still not found, get any non-group cost center
        if not cost_center:
            cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        if not cost_center:
            return {"success": False, "error": "No main cost center found"}

        # Pre-process: Fix account types before migration
        fix_account_types_for_migration(company)

        # Get mutations via SOAP API (limited to 500 most recent)
        frappe.publish_realtime(
            "migration_progress",
            {"message": "Fetching mutations via SOAP API (limited to 500 most recent)..."},
            user=frappe.session.user,
        )

        # Get all available mutations (will be max 500 most recent)
        result = api.get_mutations()

        if not result["success"]:
            return {
                "success": False,
                "error": f"Failed to fetch mutations: {result.get('error', 'Unknown error')}",
            }

        all_mutations = result.get("mutations", [])

        # Get highest mutation number
        mutation_numbers = []
        for mut in all_mutations:
            nr = mut.get("MutatieNr")
            if nr:
                try:
                    mutation_numbers.append(int(nr))
                except Exception:
                    pass

        highest_mutation_nr = max(mutation_numbers) if mutation_numbers else 0

        # Log the actual range we got
        if mutation_numbers:
            min_mutation = min(mutation_numbers)
            max_mutation = max(mutation_numbers)
            frappe.publish_realtime(
                "migration_progress",
                {
                    "message": f"Retrieved {len(all_mutations)} mutations (range: {min_mutation} to {max_mutation})"
                },
                user=frappe.session.user,  # noqa: E225
            )
        else:
            frappe.publish_realtime(
                "migration_progress",
                {"message": f"Retrieved {len(all_mutations)} mutations"},
                user=frappe.session.user,  # noqa: E225
            )

        # Log what we actually got
        mutation_numbers = []
        for mut in all_mutations:
            nr = mut.get("MutatieNr")
            if nr:
                mutation_numbers.append(int(nr))

        if mutation_numbers:
            min_mutation = min(mutation_numbers)
            max_mutation = max(mutation_numbers)
            frappe.publish_realtime(
                "migration_progress",
                {
                    "message": f"Fetched {len(all_mutations)} mutations (range: {min_mutation} to {max_mutation})"
                },
                user=frappe.session.user,  # noqa: E225
            )
        else:
            frappe.publish_realtime(
                "migration_progress",
                {"message": f"Fetched {len(all_mutations)} mutations"},
                user=frappe.session.user,  # noqa: E225
            )

        # Load relations data for enhanced customer/supplier names
        frappe.publish_realtime(
            "migration_progress",
            {"message": "Loading relations data for enhanced naming..."},
            user=frappe.session.user,
        )

        relations_result = api.get_relaties()
        relations_data = {}
        if relations_result["success"]:
            for relation in relations_result.get("relations", []):
                code = relation.get("Code") or relation.get("ID")
                if code:
                    relations_data[str(code)] = relation
            migration_doc.log_error(f"Loaded {len(relations_data)} relation records for enhanced naming")
        else:
            migration_doc.log_error(
                f"Failed to load relations: {relations_result.get('error', 'Unknown error')}"
            )

        # Store relations data for use throughout migration
        # Use a proper attribute name without underscore prefix
        migration_doc.relations_data = relations_data

        # Update progress
        frappe.publish_realtime(
            "migration_progress",
            {"message": f"Retrieved {len(all_mutations)} mutations. Processing..."},
            user=frappe.session.user,
        )

        # Process mutations by type
        stats = {
            "total_mutations": len(all_mutations),
            "invoices_created": 0,
            "payments_processed": 0,
            "journal_entries_created": 0,
            "errors": [],
            "highest_mutation_number": highest_mutation_nr,
        }

        # Group mutations by type for processing
        from .normalize_mutation_types import normalize_mutation_type

        mutations_by_type = defaultdict(list)
        for mut in all_mutations:
            soort = mut.get("Soort", "Unknown")
            # Normalize the mutation type to handle abbreviations
            normalized_soort = normalize_mutation_type(soort)
            mutations_by_type[normalized_soort].append(mut)

        # Log mutation type distribution
        mutation_distribution = {k: len(v) for k, v in mutations_by_type.items()}
        # Log to the migration summary instead of error log to avoid title length issues
        distribution_summary = (
            f"Mutation types found: {', '.join([f'{k}({v})' for k, v in mutation_distribution.items()])}"
        )
        frappe.logger().info(f"E-Boekhouden Migration {migration_doc.name}: {distribution_summary}")

        # Store in migration document if needed
        if hasattr(migration_doc, "migration_summary"):
            migration_doc.migration_summary = (
                distribution_summary + "\n" + (migration_doc.migration_summary or "")
            )

        # Process each type
        unhandled_mutations = 0
        all_skip_reasons = {}
        all_skipped = 0

        for soort, muts in mutations_by_type.items():
            if soort == "FactuurVerstuurd":
                # Sales invoices
                relations_data = getattr(migration_doc, "relations_data", {})
                result = process_sales_invoices(muts, company, cost_center, migration_doc, relations_data)
                stats["invoices_created"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count

            elif soort == "FactuurOntvangen":
                # Purchase invoices
                if use_account_mappings:
                    from .eboekhouden_mapping_migration import process_purchase_invoices_with_mapping

                    result = process_purchase_invoices_with_mapping(muts, company, cost_center, migration_doc)
                    stats["invoices_created"] += result.get("created_purchase_invoices", 0)
                    stats["journal_entries_created"] += result.get("created_journal_entries", 0)
                else:
                    relations_data = getattr(migration_doc, "relations_data", {})
                    result = process_purchase_invoices(
                        muts, company, cost_center, migration_doc, relations_data
                    )
                    stats["invoices_created"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count

            elif soort == "FactuurbetalingOntvangen":
                # Customer payments
                relations_data = getattr(migration_doc, "_relations_data", {})
                result = process_customer_payments(muts, company, cost_center, migration_doc, relations_data)
                stats["payments_processed"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count

            elif soort == "FactuurbetalingVerstuurd":
                # Supplier payments
                relations_data = getattr(migration_doc, "_relations_data", {})
                result = process_supplier_payments(muts, company, cost_center, migration_doc, relations_data)
                stats["payments_processed"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count

            elif soort in ["GeldOntvangen", "GeldUitgegeven"]:
                # Direct bank transactions
                result = process_bank_transactions(muts, company, cost_center, migration_doc, soort)
                stats["journal_entries_created"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count

            elif soort == "Memoriaal":
                # Manual journal entries
                result = process_memorial_entries(muts, company, cost_center, migration_doc)
                stats["journal_entries_created"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count

            elif soort == "BeginBalans":
                # Opening balance entries
                result = process_beginbalans_entries(muts, company, cost_center, migration_doc)
                stats["journal_entries_created"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

                # Track skipped mutations
                if "skipped" in result:
                    all_skipped += result["skipped"]
                    for reason, count in result.get("skip_reasons", {}).items():
                        all_skip_reasons[reason] = all_skip_reasons.get(reason, 0) + count
            else:
                # Unhandled mutation type
                unhandled_mutations += len(muts)
                # Log the first few as examples
                if unhandled_mutations <= 10:
                    for mut in muts[:3]:  # Log up to 3 examples
                        migration_doc.log_error(
                            f"Unhandled mutation type '{soort}': MutatieNr={mut.get('MutatieNr')}, Omschrijving={mut.get('Omschrijving', '')[:50]}",
                            "unhandled_type",
                            mut,
                        )

        # Add unhandled count to stats
        stats["unhandled_mutations"] = unhandled_mutations
        stats["skipped_mutations"] = all_skipped
        stats["skip_reasons"] = all_skip_reasons

        # Log final summary
        if all_skipped > 0:
            skip_summary = ", ".join([f"{reason}: {count}" for reason, count in all_skip_reasons.items()])
            frappe.logger().info(
                f"Migration {migration_doc.name} - Total skipped: {all_skipped} ({skip_summary})"
            )

        # Use improved categorization
        from .eboekhouden_migration_categorizer import categorize_migration_results

        categorized = categorize_migration_results(stats, all_skip_reasons, stats["errors"])

        # Store categorized results
        stats["categorized_results"] = categorized

        return {"success": True, "stats": stats, "message": categorized["improved_message"]}

    except Exception as e:
        import traceback

        error_details = f"SOAP migration error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        frappe.log_error(error_details, "E-Boekhouden Migration")

        # Better error message for debugging
        error_msg = str(e)
        if "missing_customer" in error_msg:
            error_msg = (
                f"Error accessing data: {error_msg}. This might be a code issue with dictionary access."
            )

        return {"success": False, "error": error_msg}


def process_sales_invoices(mutations, company, cost_center, migration_doc, relation_data_map=None):
    """Process FactuurVerstuurd (sales invoices)"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    for mut in mutations:
        try:
            # Skip if already imported
            invoice_no = mut.get("Factuurnummer")
            if not invoice_no:
                skipped += 1
                skip_reasons["no_invoice_number"] = skip_reasons.get("no_invoice_number", 0) + 1
                continue

            if frappe.db.exists("Sales Invoice", {"eboekhouden_invoice_number": invoice_no}):
                skipped += 1
                skip_reasons["already_imported"] = skip_reasons.get("already_imported", 0) + 1
                continue

            # Parse mutation data
            posting_date = parse_date(mut.get("Datum"))
            customer_code = mut.get("RelatieCode")
            description = mut.get("Omschrijving", "")

            # Get or create customer with relation data
            relation_data = (
                migration_doc.relations_data.get(str(customer_code))
                if hasattr(migration_doc, "relations_data")
                else None
            )
            customer = get_or_create_customer(customer_code, description, relation_data, mut.get("MutatieNr"))

            # Create sales invoice
            si = frappe.new_doc("Sales Invoice")
            si.company = company
            si.customer = customer
            si.posting_date = posting_date
            si.eboekhouden_invoice_number = invoice_no
            si.remarks = description

            # Calculate and set due date
            try:
                payment_terms = int(mut.get("Betalingstermijn", 30))
            except (ValueError, TypeError):
                payment_terms = 30

            # Ensure payment terms is positive
            if payment_terms < 0:
                payment_terms = 0

            # Set due date - ensure it's not before posting date
            calculated_due_date = frappe.utils.add_days(posting_date, payment_terms)
            if frappe.utils.getdate(calculated_due_date) < frappe.utils.getdate(posting_date):
                si.due_date = posting_date
            else:
                si.due_date = calculated_due_date

            # Set the debit to account from E-Boekhouden mutation
            rekening_code = mut.get("Rekening")
            if rekening_code:
                # Get the account by code
                debit_account = get_account_by_code(rekening_code, company)
                if debit_account:
                    # Ensure it's marked as receivable
                    current_type = frappe.db.get_value("Account", debit_account, "account_type")
                    if current_type != "Receivable":
                        frappe.db.set_value("Account", debit_account, "account_type", "Receivable")
                        frappe.db.commit()
                    si.debit_to = debit_account
                else:
                    # Fallback to default
                    default_receivable = frappe.db.get_value("Company", company, "default_receivable_account")
                    if default_receivable:
                        si.debit_to = default_receivable
            else:
                # Use default if no Rekening specified
                default_receivable = frappe.db.get_value("Company", company, "default_receivable_account")
                if default_receivable:
                    si.debit_to = default_receivable

            # Set cost center
            si.cost_center = cost_center

            # Add line items from MutatieRegels
            for regel in mut.get("MutatieRegels", []):
                amount = float(regel.get("BedragExclBTW", 0))
                if amount > 0:
                    from verenigingen.utils.smart_tegenrekening_mapper import (
                        create_invoice_line_for_tegenrekening,
                    )

                    line_dict = create_invoice_line_for_tegenrekening(
                        tegenrekening_code=regel.get("TegenrekeningCode"),
                        amount=amount,
                        description=regel.get("Omschrijving", "") or mut.get("Omschrijving", ""),
                        transaction_type="sales",
                    )
                    si.append("items", line_dict)

            si.insert(ignore_permissions=True)
            si.submit()
            created += 1

        except Exception as e:
            errors.append(f"Invoice {mut.get('Factuurnummer')}: {str(e)}")

    # Log summary for this batch
    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"Sales invoices - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


def process_customer_payments(mutations, company, cost_center, migration_doc, relation_data_map=None):
    """Process FactuurbetalingOntvangen (customer payments)"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    for mut in mutations:
        try:
            invoice_no = mut.get("Factuurnummer")
            if not invoice_no:
                skipped += 1
                skip_reasons["no_invoice_number"] = skip_reasons.get("no_invoice_number", 0) + 1
                continue

            # Check if payment already exists
            mutation_nr = mut.get("MutatieNr")
            if frappe.db.exists(
                "Payment Entry", [["reference_no", "=", mutation_nr], ["docstatus", "!=", 2]]
            ):
                skipped += 1
                skip_reasons["already_imported"] = skip_reasons.get("already_imported", 0) + 1
                continue

            # Find the related sales invoice
            si_name = frappe.db.get_value("Sales Invoice", {"eboekhouden_invoice_number": invoice_no}, "name")

            if not si_name:
                skipped += 1
                skip_reasons["invoice_not_found"] = skip_reasons.get("invoice_not_found", 0) + 1
                # Invoice not found, create unreconciled payment entry
                from .create_unreconciled_payment import create_unreconciled_payment_entry

                result = create_unreconciled_payment_entry(mut, company, cost_center, "Customer")
                if result["success"]:
                    created += 1
                else:
                    errors.append(f"Unreconciled payment {mut.get('MutatieNr')}: {result['error']}")
                continue

            # Create payment entry
            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Receive"
            pe.company = company
            pe.posting_date = parse_date(mut.get("Datum"))
            pe.party_type = "Customer"
            pe.party = frappe.db.get_value("Sales Invoice", si_name, "customer")

            # Set descriptive title
            from .eboekhouden_payment_naming import enhance_payment_entry_fields, get_payment_entry_title

            # Get relation data for this customer
            customer_code = mut.get("RelatieCode")
            relation_data = (
                relation_data_map.get(customer_code) if relation_data_map and customer_code else None
            )
            pe.title = get_payment_entry_title(mut, pe.party, "Receive", relation_data)
            pe = enhance_payment_entry_fields(pe, mut)
            pe.reference_no = mutation_nr  # Track mutation number

            # Get amount from mutation lines
            total_amount = 0
            for regel in mut.get("MutatieRegels", []):
                total_amount += float(regel.get("BedragInclBTW", 0))

            pe.paid_amount = total_amount
            pe.received_amount = total_amount

            # Link to invoice
            pe.append(
                "references",
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": si_name,
                    "allocated_amount": total_amount,
                },
            )

            # Set accounts
            bank_account = get_bank_account(mut.get("Rekening"), company)
            pe.paid_to = bank_account

            pe.insert(ignore_permissions=True)
            pe.submit()
            created += 1

        except Exception as e:
            errors.append(f"Payment {mut.get('MutatieNr')}: {str(e)}")

    # Log summary for this batch
    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"Customer payments - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


def process_bank_transactions(mutations, company, cost_center, migration_doc, transaction_type):
    """Process GeldOntvangen and GeldUitgegeven (direct bank transactions)"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    # Get already processed mutations
    processed = get_processed_mutation_numbers(company)

    for mut in mutations:
        try:
            # Skip if already processed
            mutation_nr = mut.get("MutatieNr")
            if mutation_nr and is_mutation_processed(mutation_nr, processed):
                skipped += 1
                skip_reasons["already_imported"] = skip_reasons.get("already_imported", 0) + 1
                continue

            # Create journal entry
            je = frappe.new_doc("Journal Entry")
            je.company = company
            je.posting_date = parse_date(mut.get("Datum"))
            je.eboekhouden_mutation_nr = mutation_nr

            # Set descriptive title and enhanced remarks
            from .eboekhouden_payment_naming import enhance_journal_entry_fields, get_journal_entry_title

            je.title = get_journal_entry_title(mut, transaction_type)
            je = enhance_journal_entry_fields(je, mut, "Bank Transaction")

            # Get amount
            total_amount = 0
            for regel in mut.get("MutatieRegels", []):
                total_amount += float(regel.get("BedragInclBTW", 0))

            if total_amount == 0:
                skipped += 1
                skip_reasons["zero_amount"] = skip_reasons.get("zero_amount", 0) + 1
                continue

            # Bank account
            bank_account = get_bank_account(mut.get("Rekening"), company)

            if transaction_type == "GeldOntvangen":
                # Money received - debit bank, credit income
                je.append(
                    "accounts",
                    {
                        "account": bank_account,
                        "debit_in_account_currency": total_amount,
                        "cost_center": cost_center,
                    },
                )

                # Try to determine income account from description
                income_account = determine_income_account(mut.get("Omschrijving", ""), company)
                je.append(
                    "accounts",
                    {
                        "account": income_account,
                        "credit_in_account_currency": total_amount,
                        "cost_center": cost_center,
                    },
                )
            else:
                # Money spent - credit bank, debit expense
                je.append(
                    "accounts",
                    {
                        "account": bank_account,
                        "credit_in_account_currency": total_amount,
                        "cost_center": cost_center,
                    },
                )

                # Try to determine expense account from description
                expense_account = determine_expense_account(mut.get("Omschrijving", ""), company)
                je.append(
                    "accounts",
                    {
                        "account": expense_account,
                        "debit_in_account_currency": total_amount,
                        "cost_center": cost_center,
                    },
                )

            je.insert(ignore_permissions=True)
            je.submit()
            created += 1

        except Exception as e:
            errors.append(f"Bank transaction {mut.get('MutatieNr')}: {str(e)}")

    # Log summary for this batch
    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"Bank transactions ({transaction_type}) - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


# Helper functions


def parse_date(date_str):
    """Parse date from E-Boekhouden format"""
    if not date_str:
        return frappe.utils.today()

    if "T" in date_str:
        return date_str.split("T")[0]  # Return string format YYYY-MM-DD
    else:
        return date_str  # Already in correct format


def get_or_create_customer(code, description="", relation_data=None, mutation_nr=None):
    """Get or create customer based on code, description, and relation data"""
    if not code:
        # Try to extract from description
        if description and description.strip():
            return create_customer_from_description(description, mutation_nr)
        return "E-Boekhouden Import Customer"

    # Check if customer exists with this code
    customer = frappe.db.get_value("Customer", {"eboekhouden_relation_code": code}, "name")
    if customer:
        return customer

    # Create meaningful customer name
    customer_name = get_meaningful_customer_name(code, description, relation_data, mutation_nr)

    # Create new customer
    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name
    customer.eboekhouden_relation_code = code
    customer.customer_group = (
        frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
    )

    # Use proper territory selection (avoid "Rest Of The World")
    territory = get_proper_territory(relation_data)
    customer.territory = territory

    customer.insert(ignore_permissions=True)

    return customer.name


def get_meaningful_customer_name(code, description, relation_data, mutation_nr=None):
    """Create a meaningful customer name from available data"""
    # Maximum length for customer name in ERPNext (reserve space for mutation reference if needed)
    MAX_CUSTOMER_NAME_LENGTH = 140
    MUTATION_REF_SPACE = 15  # Space for " (EBH-123456)"

    def truncate_name(name, include_mutation_ref=False):
        """Truncate name to max length with ellipsis if needed"""
        max_length = MAX_CUSTOMER_NAME_LENGTH
        if include_mutation_ref and mutation_nr:
            max_length -= MUTATION_REF_SPACE

        if len(name) <= max_length:
            result = name
        else:
            result = name[: max_length - 3] + "..."

        # Add mutation reference if provided
        if include_mutation_ref and mutation_nr:
            result += f" (EBH-{mutation_nr})"

        return result

    # Try to get actual customer name from relation data
    if relation_data:
        # Check for company name (fix typo: "Bedrij" -> "Bedrijf")
        if relation_data.get("Bedrijf") and relation_data["Bedrijf"].strip():
            return truncate_name(relation_data["Bedrijf"].strip(), include_mutation_ref=True)

        # Check for contact name
        if relation_data.get("Contactpersoon") and relation_data["Contactpersoon"].strip():
            return truncate_name(relation_data["Contactpersoon"].strip(), include_mutation_ref=True)

        # Check for name field
        if relation_data.get("Naam") and relation_data["Naam"].strip():
            return truncate_name(relation_data["Naam"].strip(), include_mutation_ref=True)

    # Fall back to description if meaningful
    if description and description.strip() and description.strip() != code:
        # First try to extract name from SEPA description
        extracted_name = extract_name_from_sepa_description(description.strip())
        if extracted_name:
            return truncate_name(extracted_name, include_mutation_ref=True)

        # Otherwise use cleaned description
        clean_desc = description.strip()
        # Avoid generic descriptions
        if not any(word in clean_desc.lower() for word in ["customer", "klant", "debtor", "debiteur"]):
            return truncate_name(clean_desc, include_mutation_ref=True)

    # Last resort: use code with prefix
    return truncate_name(f"Customer {code}", include_mutation_ref=True)


def create_customer_from_description(description, mutation_nr=None):
    """Create customer from description when no code is available"""
    MAX_CUSTOMER_NAME_LENGTH = 140
    MUTATION_REF_SPACE = 15  # Space for " (EBH-123456)"
    full_description = description.strip()

    # Try to extract a meaningful name from SEPA description
    extracted_name = extract_name_from_sepa_description(full_description)

    if extracted_name:
        customer_name = extracted_name
    else:
        # Fallback to truncated description
        customer_name = full_description

    # Ensure name fits within limit, reserving space for mutation reference
    max_length = MAX_CUSTOMER_NAME_LENGTH
    if mutation_nr:
        max_length -= MUTATION_REF_SPACE

    if len(customer_name) > max_length:
        customer_name = customer_name[: max_length - 3] + "..."

    # Add mutation reference if provided
    if mutation_nr:
        customer_name += f" (EBH-{mutation_nr})"

    # Check if this customer already exists
    existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
    if existing:
        return existing

    # Create new customer
    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name
    customer.customer_group = (
        frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
    )
    customer.territory = get_proper_territory()

    # Store the full SEPA description in customer_details field
    if len(full_description) > MAX_CUSTOMER_NAME_LENGTH:
        customer.customer_details = f"SEPA Payment Description:\n{full_description}"

    customer.insert(ignore_permissions=True)

    return customer.name


def get_proper_territory(relation_data=None):
    """Get appropriate territory, avoiding 'Rest Of The World'"""
    # Try to determine territory from relation data
    if relation_data:
        country = relation_data.get("Land", "").strip()
        if country:
            # Check if territory exists for this country
            territory = frappe.db.get_value("Territory", {"territory_name": country}, "name")
            if territory:
                return territory

    # Get the company's home country territory
    default_country = frappe.db.get_default("country")
    if default_country:
        home_territory = frappe.db.get_value("Territory", {"territory_name": default_country}, "name")
        if home_territory:
            return home_territory

    # Get territories, preferring specific ones over "Rest Of The World"
    territories = frappe.get_all(
        "Territory", filters={"is_group": 0}, fields=["name", "territory_name"], order_by="territory_name"
    )

    # Filter out "Rest Of The World" and similar generic territories
    preferred_territories = [
        t
        for t in territories
        if not any(word in t.territory_name.lower() for word in ["rest", "world", "other", "misc", "unknown"])
    ]

    if preferred_territories:
        return preferred_territories[0].name

    # Fall back to any territory if needed
    return territories[0].name if territories else "All Territories"


def get_or_create_supplier(code, description="", relation_data=None, mutation_nr=None):
    """Get or create supplier based on code, description, and relation data"""
    if not code:
        # Try to extract from description
        if description and description.strip():
            return create_supplier_from_description(description, mutation_nr)
        return "E-Boekhouden Import Supplier"

    # First check if supplier exists with code as the name (for backward compatibility)
    if frappe.db.exists("Supplier", code):
        return code

    # Check if supplier exists with this code
    supplier = frappe.db.get_value("Supplier", {"eboekhouden_relation_code": code}, "name")
    if supplier:
        return supplier

    # Create meaningful supplier name
    supplier_name = get_meaningful_supplier_name(code, description, relation_data, mutation_nr)

    # Create new supplier
    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = supplier_name
    supplier.eboekhouden_relation_code = code
    supplier.supplier_group = (
        frappe.db.get_value("Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups"
    )
    supplier.insert(ignore_permissions=True)

    return supplier.name


def ensure_supplier_compatibility(supplier_name, code):
    """Ensure supplier can be found by both name and code"""
    # If the supplier name is different from code, we need to handle lookups by code
    if supplier_name and supplier_name != code and code:
        # Store mapping for quick lookup
        cache_key = f"supplier_code_map_{code}"
        frappe.cache().set_value(cache_key, supplier_name, expires_in_sec=3600)
    return supplier_name


def get_meaningful_supplier_name(code, description, relation_data, mutation_nr=None):
    """Create a meaningful supplier name from available data"""
    # Maximum length for supplier name in ERPNext (reserve space for mutation reference if needed)
    MAX_SUPPLIER_NAME_LENGTH = 140
    MUTATION_REF_SPACE = 15  # Space for " (EBH-123456)"

    def truncate_name(name, include_mutation_ref=False):
        """Truncate name to max length with ellipsis if needed"""
        max_length = MAX_SUPPLIER_NAME_LENGTH
        if include_mutation_ref and mutation_nr:
            max_length -= MUTATION_REF_SPACE

        if len(name) <= max_length:
            result = name
        else:
            result = name[: max_length - 3] + "..."

        # Add mutation reference if provided
        if include_mutation_ref and mutation_nr:
            result += f" (EBH-{mutation_nr})"

        return result

    # Try to get actual supplier name from relation data
    if relation_data:
        # Check for company name (fix typo: "Bedrij" -> "Bedrijf")
        if relation_data.get("Bedrijf") and relation_data["Bedrijf"].strip():
            return truncate_name(relation_data["Bedrijf"].strip(), include_mutation_ref=True)

        # Check for contact name
        if relation_data.get("Contactpersoon") and relation_data["Contactpersoon"].strip():
            return truncate_name(relation_data["Contactpersoon"].strip(), include_mutation_ref=True)

        # Check for name field
        if relation_data.get("Naam") and relation_data["Naam"].strip():
            return truncate_name(relation_data["Naam"].strip(), include_mutation_ref=True)

    # Fall back to description if meaningful
    if description and description.strip() and description.strip() != code:
        # First try to extract name from SEPA description
        extracted_name = extract_name_from_sepa_description(description.strip())
        if extracted_name:
            return truncate_name(extracted_name, include_mutation_ref=True)

        # Otherwise use cleaned description
        clean_desc = description.strip()
        # Avoid generic descriptions
        if not any(
            word in clean_desc.lower() for word in ["supplier", "leverancier", "creditor", "crediteur"]
        ):
            return truncate_name(clean_desc, include_mutation_ref=True)

    # Last resort: use code with prefix
    return truncate_name(f"Supplier {code}", include_mutation_ref=True)


def extract_name_from_sepa_description(description):
    """Extract meaningful name from SEPA payment description

    Uses the same logic as the MT940 import and payment naming utilities
    to extract counterparty names from SEPA descriptions.

    SEPA descriptions often follow patterns like:
    - IBAN BIC Beneficiary Name REFERENCE Invoice# etc.
    - NL10ABNA0432630856 ABNANL2A Filmtheater de Uitkijk ER EF 20250605224311TRIONL2UXXXE000040836 Factuurnummer 250304
    """
    import re

    # First try specific Dutch bank payment patterns
    # Look for company names that come after BIC codes and before transaction references
    dutch_bank_pattern = r"[A-Z]{2}\d{2}[A-Z0-9]{4,30}\s+[A-Z]{6}[A-Z0-9]{2,5}\s+([A-Za-z][A-Za-z\s&\.\-]{3,40}?)\s+(?:ER\s+EF|[A-Z]{2}\s+[A-Z]{2}|\d{14})"
    match = re.search(dutch_bank_pattern, description)
    if match:
        extracted_name = match.group(1).strip()
        # Clean up any trailing single letters or short codes
        extracted_name = re.sub(r"\s+[A-Z]\s*$", "", extracted_name).strip()
        if len(extracted_name) > 3:
            return extracted_name

    # Try the enhanced payment naming logic from eboekhouden_payment_naming
    # Look for patterns like "Payment from ABC Company" or "Betaling van XYZ"
    patterns = [
        r"(?:van|from|to|naar)\s+([A-Za-z][A-Za-z\s&\.\-]{2,30})",
        r"([A-Za-z][A-Za-z\s&\.\-]{3,30})\s+(?:payment|betaling|invoice|factuur)",
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            extracted_name = match.group(1).strip()
            # Avoid generic terms
            if not any(
                word in extracted_name.lower()
                for word in ["payment", "betaling", "invoice", "factuur", "customer", "supplier"]
            ):
                return extracted_name

    # SEPA field extraction logic similar to MT940 import
    # Common SEPA/payment reference patterns to remove
    iban_pattern = r"^[A-Z]{2}\d{2}[A-Z0-9]{4,30}\s+"
    bic_pattern = r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?\s+"

    # SEPA reference patterns based on MT940 SEPA fields
    sepa_reference_patterns = [
        r"\s+ER\s+EF\s+\d{14}[A-Z0-9]+.*$",  # ER EF timestamps (must come before general patterns)
        r"\s+\d{2}-\d{2}-\d{2,4}.*$",  # Date patterns like "24-06-21" or "24-06-2021"
        r"\s+\d{4}-\d{2}-\d{2}.*$",  # Date patterns like "2021-06-24"
        r"\s+\d{2}/\d{2}/\d{2,4}.*$",  # Date patterns like "24/06/21"
        r"\s+\d{1,2}:\d{2}.*$",  # Time patterns like "14:38"
        r"\s+\d{10,20}.*$",  # Long transaction numbers
        r"\s+[Oo]rdernummer.*$",  # Order numbers
        r"\s+[Tt]ransactienummer.*$",  # Transaction numbers
        r"\s+[Jj]e order.*$",  # "Je order nr"
        r"\s+EREF\s+[A-Z0-9\-]+",  # End-to-end reference
        r"\s+MREF\s+[A-Z0-9\-]+",  # Mandate reference
        r"\s+CRED\s+[A-Z0-9\-]+",  # Creditor reference
        r"\s+SVWZ\s+.*$",  # Payment purpose
        r"\s+Factuurnummer\s+\d+.*$",  # Invoice numbers
        r"\s+Invoice\s*#?\s*\d+.*$",
        r"\s+Ref\s*[:=]\s*.*$",
        r"\s+Reference\s*[:=]\s*.*$",
        r"\s+Kenmerk\s*[:=]\s*.*$",
    ]

    # Start with the full description
    name = description.strip()

    # Remove IBAN if at the beginning
    name = re.sub(iban_pattern, "", name)

    # Remove BIC code if at the beginning after IBAN
    name = re.sub(bic_pattern, "", name)

    # Check if this might be an ABWA (counterparty) field
    # In SEPA, this comes after IBAN/BIC and before references

    # Extract the name part (usually comes after IBAN/BIC and before references)
    # Look for common reference starters
    for pattern in sepa_reference_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            name = name[: match.start()].strip()
            break

    # Clean up any remaining reference-like patterns
    # Remove long alphanumeric sequences that look like references
    name = re.sub(r"\s+[A-Z0-9]{20,}", "", name)

    # Handle "via" patterns (like "Tupak via ICEPAY") - keep the company name with payment provider
    via_match = re.match(
        r"^([A-Za-z][A-Za-z\s&\.\-]{2,30})\s+via\s+([A-Za-z][A-Za-z\s&\.\-]{2,20})", name, re.IGNORECASE
    )
    if via_match:
        company_name = via_match.group(1).strip()
        payment_provider = via_match.group(2).strip()
        # Include payment provider if it's meaningful (not just a code)
        if len(payment_provider) > 2 and payment_provider.isalpha():
            name = f"{company_name} via {payment_provider}"
        else:
            name = company_name

    # If we still have a very long name, it might contain additional info
    # Try to extract just the company/person name part
    elif len(name) > 50:
        # Common separators in payment descriptions
        for separator in [" - ", " / ", " | ", "  "]:
            if separator in name:
                parts = name.split(separator)
                # Take the first meaningful part
                name = parts[0].strip()
                break

    # Final cleanup - remove common redundant phrases (from payment naming)
    cleanup_patterns = [
        r"^(Payment|Betaling|Invoice|Factuur)\s+(from|van|to|naar)\s+",
        r"\s+\(.*\)$",  # Remove trailing parentheses
        r"^Mutatie\s+\d+:\s*",  # Remove mutation number prefix
    ]

    for pattern in cleanup_patterns:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()

    # Final cleanup
    name = " ".join(name.split())  # Normalize whitespace

    # If we couldn't extract anything meaningful, return None
    if not name or len(name) < 3:
        return None

    return name


@frappe.whitelist()
def test_supplier_name_fixes():
    """Test the supplier name extraction fixes"""
    # Test case from the actual error log
    problematic_description = "NL10ABNA0432630856 ABNANL2A Filmtheater de Uitkijk ER EF 20250605224311TRIONL2UXXXE000040836 Factuurnummer 250304, excuus voor trage betaling."

    # Test SEPA extraction
    extracted_name = extract_name_from_sepa_description(problematic_description)

    # Test supplier name creation with mutation reference
    supplier_name = get_meaningful_supplier_name("1248", problematic_description, None, "7430")

    return {
        "success": True,
        "original_description": problematic_description,
        "original_length": len(problematic_description),
        "extracted_company_name": extracted_name,
        "final_supplier_name": supplier_name,
        "final_length": len(supplier_name) if supplier_name else 0,
        "within_limit": len(supplier_name) <= 140 if supplier_name else False,
    }


@frappe.whitelist()
def test_sepa_name_extraction(description=None):
    """Test function for SEPA name extraction"""
    test_cases = [
        "Tupak via ICEPAY 24-06-21 14:38 0030007305208628 Ordernummer tupam50995 Transactienummer 0030007305208628 24-06-21 14:38 Je order nr 5099",
        "NL10ABNA0432630856 ABNANL2A Filmtheater de Uitkijk ER EF 20250605224311TRIONL2UXXXE000040836 Factuurnummer 250304",
        "McDonald's Nederland 15-03-21 12:45 Order 123456789",
        "Albert Heijn via iDEAL 01-01-21 Transaction 987654321",
    ]

    if description:
        test_cases = [description]

    results = []
    for desc in test_cases:
        extracted = extract_name_from_sepa_description(desc)
        results.append(
            {
                "original": desc,
                "extracted": extracted,
                "length_original": len(desc),
                "length_extracted": len(extracted) if extracted else 0,
            }
        )

    return {"success": True, "test_results": results}


def create_supplier_from_description(description, mutation_nr=None):
    """Create supplier from description when no code is available"""
    MAX_SUPPLIER_NAME_LENGTH = 140
    MUTATION_REF_SPACE = 15  # Space for " (EBH-123456)"
    full_description = description.strip()

    # Try to extract a meaningful name from SEPA description
    extracted_name = extract_name_from_sepa_description(full_description)

    if extracted_name:
        supplier_name = extracted_name
    else:
        # Fallback to truncated description
        supplier_name = full_description

    # Ensure name fits within limit, reserving space for mutation reference
    max_length = MAX_SUPPLIER_NAME_LENGTH
    if mutation_nr:
        max_length -= MUTATION_REF_SPACE

    if len(supplier_name) > max_length:
        supplier_name = supplier_name[: max_length - 3] + "..."

    # Add mutation reference if provided
    if mutation_nr:
        supplier_name += f" (EBH-{mutation_nr})"

    # Check if this supplier already exists
    existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
    if existing:
        return existing

    # Create new supplier
    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = supplier_name
    supplier.supplier_group = (
        frappe.db.get_value("Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups"
    )

    # Store the full SEPA description in supplier_details field
    if len(full_description) > MAX_SUPPLIER_NAME_LENGTH:
        supplier.supplier_details = f"SEPA Payment Description:\n{full_description}"

    supplier.insert(ignore_permissions=True)

    return supplier.name


def get_or_create_item(code, company=None, transaction_type="Both", description=None):
    """Get or create item for invoice line with improved naming"""
    # Use the improved item naming logic
    from .eboekhouden_improved_item_naming import get_or_create_item_improved

    return get_or_create_item_improved(code, company, transaction_type, description)


def get_account_by_code(code, company):
    """Get account by E-Boekhouden code with improved matching"""
    if not code:
        # Return None instead of a default - let caller decide default
        return None

    # Create a cache key
    cache_key = f"eboekhouden_account_{company}_{code}"
    cached_account = frappe.cache().get_value(cache_key)
    if cached_account:
        return cached_account

    # Strategy 1: Exact match by account_number
    account = frappe.db.get_value(
        "Account", {"account_number": code, "company": company, "disabled": 0}, "name"
    )
    if account:
        frappe.cache().set_value(cache_key, account, expires_in_sec=3600)
        return account

    # Strategy 2: Match by standardized account number format
    # E.g., "10000" might be stored as "1000" or "10000 - Cash"
    normalized_code = code.lstrip("0")  # Remove leading zeros
    if normalized_code != code:
        account = frappe.db.get_value(
            "Account", {"account_number": normalized_code, "company": company, "disabled": 0}, "name"
        )
        if account:
            frappe.cache().set_value(cache_key, account, expires_in_sec=3600)
            return account

    # Strategy 3: Intelligent name matching
    # Look for account where code appears at the beginning of the name
    account = frappe.db.sql(
        """
        SELECT name
        FROM `tabAccount`
        WHERE company = %s
        AND disabled = 0
        AND (
            account_name LIKE %s  -- Starts with code
            OR account_name LIKE %s  -- Code after space
        )
        ORDER BY
            CASE
                WHEN account_number = %s THEN 1
                WHEN account_name LIKE %s THEN 2
                ELSE 3
            END,
            LENGTH(account_name)  -- Prefer shorter names (less likely to be wrong)
        LIMIT 1
    """,
        (
            company,
            "{code} -%",  # e.g., "10000 - Cash"
            "% {code} -%",  # e.g., "NL 10000 - Cash"
            code,
            "{code}%",
        ),
        as_dict=True,
    )

    if account:
        frappe.cache().set_value(cache_key, account[0].name, expires_in_sec=3600)
        return account[0].name

    # Log unmapped account for manual review
    frappe.logger().warning(
        "Could not find account mapping for eBoekhouden code '{code}' in company '{company}'"
    )

    return None


def get_bank_account(code, company):
    """Get bank account by code"""
    if code:
        account = frappe.db.get_value("Account", {"company": company, "account_number": code}, "name")
        if account:
            return account

    # Return default bank account
    return frappe.db.get_value("Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name")


def determine_income_account(description, company):
    """Try to determine income account from description"""
    desc_lower = description.lower()

    # Check for donation keywords
    if any(word in desc_lower for word in ["donatie", "gift", "donation"]):
        return frappe.db.get_value(
            "Account", {"company": company, "account_name": ["like", "%Donation%"], "is_group": 0}, "name"
        ) or get_default_income_account(company)

    return get_default_income_account(company)


def determine_expense_account(description, company):
    """Try to determine expense account from description"""
    desc_lower = description.lower()

    # Check for specific expense types
    if any(word in desc_lower for word in ["bank", "kosten", "fee"]):
        return frappe.db.get_value(
            "Account", {"company": company, "account_name": ["like", "%Bank Charges%"], "is_group": 0}, "name"
        ) or get_default_expense_account(company)

    return get_default_expense_account(company)


def get_expense_account_by_code(code, company):
    """Get expense account by code"""
    if not code:
        # Return default expense account
        return get_default_expense_account(company)

    account = frappe.db.get_value("Account", {"company": company, "account_number": code}, "name")

    if account:
        return account

    # Return default expense account
    return get_default_expense_account(company)


def get_default_income_account(company):
    """Get default income account"""
    return frappe.db.get_value(
        "Account", {"company": company, "account_type": "Income Account", "is_group": 0}, "name"
    )


def get_default_expense_account(company):
    """Get default expense account"""
    return frappe.db.get_value(
        "Account", {"company": company, "account_type": "Expense Account", "is_group": 0}, "name"
    )


def create_payment_journal_entry(mut, company, cost_center, party_type, migration_doc=None):
    """Create journal entry for payment when invoice is not found"""
    try:
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = parse_date(mut.get("Datum"))
        je.eboekhouden_mutation_nr = mut.get("MutatieNr")
        je.eboekhouden_invoice_number = mut.get("Factuurnummer")

        # Set descriptive title and enhanced remarks
        from .eboekhouden_payment_naming import enhance_journal_entry_fields, get_journal_entry_title

        mutation_type = mut.get("Soort", "Payment")
        je.title = get_journal_entry_title(mut, mutation_type)
        je = enhance_journal_entry_fields(je, mut, "{party_type} Payment - Invoice Not Found")

        # Get amount
        total_amount = 0
        for regel in mut.get("MutatieRegels", []):
            total_amount += float(regel.get("BedragInclBTW", 0) or regel.get("BedragInvoer", 0))

        if total_amount == 0:
            return {"success": False, "error": "No amount found"}

        # Get bank account
        bank_account = get_bank_account(mut.get("Rekening"), company)

        # Get default receivable/payable account
        if party_type == "Customer":
            party_account = frappe.db.get_value("Company", company, "default_receivable_account")
            # Money received
            je.append(
                "accounts",
                {
                    "account": bank_account,
                    "debit_in_account_currency": abs(total_amount),
                    "cost_center": cost_center,
                },
            )
            je.append(
                "accounts",
                {
                    "account": party_account,
                    "credit_in_account_currency": abs(total_amount),
                    "cost_center": cost_center,
                    "party_type": party_type,
                    "party": get_or_create_customer(
                        mut.get("RelatieCode"),
                        mut.get("Omschrijving", ""),
                        migration_doc._relations_data.get(str(mut.get("RelatieCode")))
                        if hasattr(migration_doc, "_relations_data")
                        else None,
                        mut.get("MutatieNr"),
                    ),
                },
            )
        else:
            party_account = frappe.db.get_value("Company", company, "default_payable_account")
            # Money paid
            je.append(
                "accounts",
                {
                    "account": party_account,
                    "debit_in_account_currency": abs(total_amount),
                    "cost_center": cost_center,
                    "party_type": party_type,
                    "party": get_or_create_supplier(
                        mut.get("RelatieCode"),
                        mut.get("Omschrijving", ""),
                        migration_doc._relations_data.get(str(mut.get("RelatieCode")))
                        if hasattr(migration_doc, "_relations_data")
                        else None,
                        mut.get("MutatieNr"),
                    ),
                },
            )
            je.append(
                "accounts",
                {
                    "account": bank_account,
                    "credit_in_account_currency": abs(total_amount),
                    "cost_center": cost_center,
                },
            )

        je.insert(ignore_permissions=True)
        je.submit()

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Add custom fields for tracking
@frappe.whitelist()
def add_eboekhouden_custom_fields():
    """Add custom fields for E-Boekhouden tracking"""

    # Sales Invoice
    if not frappe.db.has_column("Sales Invoice", "eboekhouden_invoice_number"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Sales Invoice",
                "fieldname": "eboekhouden_invoice_number",
                "fieldtype": "Data",
                "label": "E-Boekhouden Invoice Number",
                "unique": 1,
                "no_copy": 1,
            }
        ).insert(ignore_permissions=True)

    # Customer
    if not frappe.db.has_column("Customer", "eboekhouden_relation_code"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Customer",
                "fieldname": "eboekhouden_relation_code",
                "fieldtype": "Data",
                "label": "E-Boekhouden Relation Code",
                "unique": 1,
            }
        ).insert(ignore_permissions=True)

    # Journal Entry
    if not frappe.db.has_column("Journal Entry", "eboekhouden_mutation_nr"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Journal Entry",
                "fieldname": "eboekhouden_mutation_nr",
                "fieldtype": "Data",
                "label": "E-Boekhouden Mutation Nr",
                "unique": 1,
                "no_copy": 1,
            }
        ).insert(ignore_permissions=True)

    return {"success": True, "message": "Custom fields added"}


def fix_account_types_for_migration(company):
    """Fix account types based on actual usage in E-Boekhouden data"""

    # Instead of relying on account numbers, analyze actual usage from mutations
    # This is more reliable as it reflects how accounts are actually used

    # Get a sample of recent mutations to understand account usage
    from .eboekhouden_soap_api import EBoekhoudenSOAPAPI

    settings = frappe.get_single("E-Boekhouden Settings")
    api = EBoekhoudenSOAPAPI(settings)

    # Get last 3 months of data to understand account usage
    date_to = frappe.utils.today()
    date_from = frappe.utils.add_months(date_to, -3)

    result = api.get_mutations(date_from=date_from, date_to=date_to)

    if result["success"]:
        receivable_accounts = set()
        payable_accounts = set()

        for mut in result["mutations"]:
            mutation_type = mut.get("Soort")

            # Collect receivable accounts from sales invoices
            if mutation_type == "FactuurVerstuurd":
                account_code = mut.get("Rekening")
                if account_code:
                    receivable_accounts.add(account_code)

            # Collect payable accounts from purchase invoices
            elif mutation_type == "FactuurOntvangen":
                account_code = mut.get("Rekening")
                if account_code:
                    payable_accounts.add(account_code)

        # Now fix the account types based on actual usage
        for account_code in receivable_accounts:
            fix_account_type(account_code, company, "Receivable")

        for account_code in payable_accounts:
            fix_account_type(account_code, company, "Payable")

    # Also check account names for common patterns (language-agnostic approach)
    common_receivable_keywords = [
        "debtor",
        "debiteur",
        "receivable",
        "te ontvangen",
        "vordering",
        "customer",
        "klant",
        "afnemer",
    ]

    common_payable_keywords = [
        "creditor",
        "crediteur",
        "payable",
        "te betalen",
        "schuld",
        "supplier",
        "leverancier",
        "vendor",
    ]

    tax_keywords = ["btw", "vat", "tax", "belasting", "omzetbelasting"]

    # Check all accounts by name
    accounts = frappe.db.get_all(
        "Account", {"company": company, "is_group": 0}, ["name", "account_name", "account_type"]
    )

    for account in accounts:
        account_name_lower = account.account_name.lower()

        # Skip if it's a tax account
        if any(keyword in account_name_lower for keyword in tax_keywords):
            if account.account_type != "Tax":
                frappe.db.set_value("Account", account.name, "account_type", "Tax")
            continue

        # Check for receivable patterns
        if any(keyword in account_name_lower for keyword in common_receivable_keywords):
            if account.account_type not in ["Receivable", "Bank", "Cash"]:
                frappe.db.set_value("Account", account.name, "account_type", "Receivable")

        # Check for payable patterns
        elif any(keyword in account_name_lower for keyword in common_payable_keywords):
            if account.account_type != "Payable":
                frappe.db.set_value("Account", account.name, "account_type", "Payable")

    frappe.db.commit()


def fix_account_type(account_code, company, target_type):
    """Fix a specific account to have the target account type"""
    # Try to find account by number
    account = frappe.db.get_value(
        "Account",
        {"account_number": account_code, "company": company},
        ["name", "account_type"],
        as_dict=True,
    )

    if not account:
        # Try by name pattern
        account = frappe.db.get_value(
            "Account",
            {"name": ["like", "{account_code}%"], "company": company},
            ["name", "account_type"],
            as_dict=True,
        )

    if account and account.account_type != target_type:
        frappe.db.set_value("Account", account.name, "account_type", target_type)


def process_purchase_invoices(mutations, company, cost_center, migration_doc, relation_data_map=None):
    """Process FactuurOntvangen (purchase invoices)"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    for mut in mutations:
        try:
            # Skip if already imported
            invoice_no = mut.get("Factuurnummer")
            if not invoice_no:
                skipped += 1
                skip_reasons["no_invoice_number"] = skip_reasons.get("no_invoice_number", 0) + 1
                continue

            if frappe.db.exists("Purchase Invoice", {"eboekhouden_invoice_number": invoice_no}):
                skipped += 1
                skip_reasons["already_imported"] = skip_reasons.get("already_imported", 0) + 1
                continue

            # Parse mutation data
            posting_date = parse_date(mut.get("Datum"))
            supplier_code = mut.get("RelatieCode")
            description = mut.get("Omschrijving", "")

            # Get or create supplier with relation data for meaningful names
            relation_data = relation_data_map.get(supplier_code) if supplier_code else None
            supplier = get_or_create_supplier(supplier_code, description, relation_data, mut.get("MutatieNr"))

            # Create purchase invoice
            pi = frappe.new_doc("Purchase Invoice")
            pi.company = company
            pi.supplier = supplier
            pi.posting_date = posting_date
            pi.bill_date = posting_date  # Set bill_date same as posting_date
            pi.eboekhouden_invoice_number = invoice_no
            pi.remarks = description

            # Calculate and set due date
            try:
                payment_terms = int(mut.get("Betalingstermijn", 30))
            except (ValueError, TypeError):
                payment_terms = 30

            # Ensure payment terms is positive
            if payment_terms < 0:
                payment_terms = 0

            # Set due date - ensure it's not before posting date
            calculated_due_date = frappe.utils.add_days(posting_date, payment_terms)

            if frappe.utils.getdate(calculated_due_date) < frappe.utils.getdate(posting_date):
                pi.due_date = posting_date
            else:
                pi.due_date = calculated_due_date

            # Set the credit to account from E-Boekhouden mutation
            rekening_code = mut.get("Rekening")
            if rekening_code:
                # Get the account by code
                credit_account = get_account_by_code(rekening_code, company)
                if credit_account:
                    # Ensure it's marked as payable
                    current_type = frappe.db.get_value("Account", credit_account, "account_type")
                    if current_type != "Payable":
                        frappe.db.set_value("Account", credit_account, "account_type", "Payable")
                        frappe.db.commit()
                    pi.credit_to = credit_account
                else:
                    # Fallback to default
                    default_payable = frappe.db.get_value("Company", company, "default_payable_account")
                    if default_payable:
                        pi.credit_to = default_payable
            else:
                # Use default if no Rekening specified
                default_payable = frappe.db.get_value("Company", company, "default_payable_account")
                if default_payable:
                    pi.credit_to = default_payable

            # Set cost center
            pi.cost_center = cost_center

            # Add line items from MutatieRegels
            for regel in mut.get("MutatieRegels", []):
                amount = float(regel.get("BedragExclBTW", 0))
                if amount > 0:
                    from verenigingen.utils.smart_tegenrekening_mapper import (
                        create_invoice_line_for_tegenrekening,
                    )

                    line_dict = create_invoice_line_for_tegenrekening(
                        tegenrekening_code=regel.get("TegenrekeningCode"),
                        amount=amount,
                        description=regel.get("Omschrijving", "") or mut.get("Omschrijving", ""),
                        transaction_type="purchase",
                    )
                    pi.append("items", line_dict)

            pi.insert(ignore_permissions=True)
            pi.submit()
            created += 1

        except Exception as e:
            errors.append(f"Purchase Invoice {mut.get('Factuurnummer')}: {str(e)}")
            migration_doc.log_error(
                f"Failed to create purchase invoice {invoice_no}: {str(e)}", "purchase_invoice", mut
            )

    # Log summary for this batch
    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"Purchase invoices - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


def process_supplier_payments(mutations, company, cost_center, migration_doc, relation_data_map=None):
    """Process FactuurbetalingVerstuurd (supplier payments)"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    for mut in mutations:
        try:
            invoice_no = mut.get("Factuurnummer")
            if not invoice_no:
                skipped += 1
                skip_reasons["no_invoice_number"] = skip_reasons.get("no_invoice_number", 0) + 1
                continue

            # Find the related purchase invoice
            pi_name = frappe.db.get_value(
                "Purchase Invoice", {"eboekhouden_invoice_number": invoice_no}, "name"
            )

            if not pi_name:
                skipped += 1
                skip_reasons["invoice_not_found"] = skip_reasons.get("invoice_not_found", 0) + 1
                # Invoice not found, create unreconciled payment entry
                from .create_unreconciled_payment import create_unreconciled_payment_entry

                result = create_unreconciled_payment_entry(mut, company, cost_center, "Supplier")
                if result["success"]:
                    created += 1
                else:
                    errors.append(f"Unreconciled payment {mut.get('MutatieNr')}: {result['error']}")
                continue

            # Check if payment already exists for this mutation
            mutation_nr = mut.get("MutatieNr")

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
                # Payment already exists for this mutation, skip
                skipped += 1
                skip_reasons["already_imported"] = skip_reasons.get("already_imported", 0) + 1
                continue

            # Get the purchase invoice
            pi = frappe.get_doc("Purchase Invoice", pi_name)

            # Check if already paid
            if pi.outstanding_amount <= 0:
                # Invoice is already paid, skip this payment
                skipped += 1
                skip_reasons["already_paid"] = skip_reasons.get("already_paid", 0) + 1
                continue

            # Ensure supplier exists before creating payment
            if not frappe.db.exists("Supplier", pi.supplier):
                # Try to create supplier based on relation code
                supplier_code = mut.get("RelatieCode")
                if supplier_code:
                    relation_data = relation_data_map.get(supplier_code) if relation_data_map else None
                    new_supplier = get_or_create_supplier(
                        supplier_code, mut.get("Omschrijving", ""), relation_data, mut.get("MutatieNr")
                    )
                    # Update the invoice's supplier if needed
                    if new_supplier and new_supplier != pi.supplier:
                        frappe.db.set_value("Purchase Invoice", pi.name, "supplier", new_supplier)
                        pi.supplier = new_supplier
                else:
                    # Cannot create payment without valid supplier
                    errors.append(
                        "Payment for Invoice {mut.get('Factuurnummer')}: Supplier '{pi.supplier}' not found and no relation code available"
                    )
                    migration_doc.log_error(
                        "Supplier '{pi.supplier}' not found for invoice {invoice_no}",
                        "supplier_payment",
                        mut,
                    )
                    continue

            # Create payment entry
            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Pay"
            pe.company = company
            pe.posting_date = parse_date(mut.get("Datum"))
            pe.party_type = "Supplier"
            pe.party = pi.supplier

            # Set descriptive title
            from .eboekhouden_payment_naming import enhance_payment_entry_fields, get_payment_entry_title

            # Get relation data for this supplier
            supplier_code = mut.get("RelatieCode")
            relation_data = (
                relation_data_map.get(supplier_code) if relation_data_map and supplier_code else None
            )
            pe.title = get_payment_entry_title(mut, pe.party, "Pay", relation_data)
            pe = enhance_payment_entry_fields(pe, mut)

            # Get amount from MutatieRegels
            amount = 0
            for regel in mut.get("MutatieRegels", []):
                # Try different amount fields
                regel_amount = float(
                    regel.get("BedragInvoer", 0)
                    or regel.get("BedragInclBTW", 0)
                    or regel.get("BedragExclBTW", 0)
                )
                amount += abs(regel_amount)  # Use absolute value to handle negative amounts

            if amount <= 0:
                # Skip if no amount
                continue

            # Ensure payment amount doesn't exceed outstanding amount
            if amount > pi.outstanding_amount:
                amount = pi.outstanding_amount

            pe.paid_amount = amount
            pe.received_amount = pe.paid_amount
            pe.reference_no = mut.get("MutatieNr")
            pe.reference_date = pe.posting_date

            # Set bank account
            bank_code = mut.get("Rekening")
            if bank_code:
                bank_account = get_bank_account(bank_code, company)
                pe.paid_from = bank_account
            else:
                # Get default bank account
                default_bank = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
                )
                pe.paid_from = default_bank

            # Set payable account from invoice
            pe.paid_to = pi.credit_to

            # Add reference to the invoice
            pe.append(
                "references",
                {
                    "reference_doctype": "Purchase Invoice",
                    "reference_name": pi_name,
                    "allocated_amount": min(
                        pe.paid_amount, pi.outstanding_amount
                    ),  # Ensure allocated amount doesn't exceed outstanding
                },
            )

            try:
                pe.insert(ignore_permissions=True)
                pe.submit()
                created += 1
            except IntegrityError as ie:
                if "Duplicate entry" in str(ie) and "eboekhouden_mutation_nr" in str(ie):
                    # This payment was already created (race condition or retry), skip it
                    frappe.db.rollback()
                    continue
                else:
                    # Re-raise other integrity errors
                    raise

        except IntegrityError as ie:
            if "Duplicate entry" in str(ie) and "eboekhouden_mutation_nr" in str(ie):
                # This payment was already created (race condition or retry), skip it
                skipped += 1
                skip_reasons["duplicate_entry"] = skip_reasons.get("duplicate_entry", 0) + 1
                continue
            else:
                errors.append(
                    f"Payment for Invoice {mut.get('Factuurnummer')}: Database integrity error - {str(ie)}"
                )
                migration_doc.log_error(
                    "Failed to create supplier payment for invoice {invoice_no}: {str(ie)}",
                    "supplier_payment",
                    mut,
                )
        except Exception as e:
            errors.append(f"Payment for Invoice {mut.get('Factuurnummer')}: {str(e)}")
            migration_doc.log_error(
                f"Failed to create supplier payment for invoice {invoice_no}: {str(e)}",
                "supplier_payment",
                mut,
            )

    # Log summary for this batch
    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"Supplier payments - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


def process_memorial_entries(mutations, company, cost_center, migration_doc):
    """Process Memoriaal entries (manual journal entries)"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    for mut in mutations:
        try:
            # Check if already processed
            mutation_nr = mut.get("MutatieNr")
            if mutation_nr:
                existing_je = frappe.db.exists(
                    "Journal Entry",
                    {"eboekhouden_mutation_nr": mutation_nr, "docstatus": ["!=", 2]},  # Not cancelled
                )
                if existing_je:
                    skipped += 1
                    skip_reasons["already_imported"] = skip_reasons.get("already_imported", 0) + 1
                    continue

            # Create journal entry
            je = frappe.new_doc("Journal Entry")
            je.company = company
            je.posting_date = parse_date(mut.get("Datum"))
            je.eboekhouden_mutation_nr = mutation_nr
            je.eboekhouden_invoice_number = mut.get("Factuurnummer")

            # Set descriptive title and remarks
            from .eboekhouden_payment_naming import enhance_journal_entry_fields, get_journal_entry_title

            je.title = get_journal_entry_title(mut, "Memoriaal")
            je = enhance_journal_entry_fields(je, mut, "Manual Entry")

            # Process mutation lines
            for regel in mut.get("MutatieRegels", []):
                account_code = regel.get("TegenrekeningCode")
                if not account_code:
                    continue

                # Get the account
                account = get_account_by_code(account_code, company)
                if not account:
                    # Skip if account not found
                    continue

                # Get amount - try different fields
                amount = float(
                    regel.get("BedragInclBTW", 0)
                    or regel.get("BedragExclBTW", 0)
                    or regel.get("BedragInvoer", 0)
                )
                if amount == 0:
                    continue

                # Determine debit or credit based on amount sign
                if amount > 0:
                    je.append(
                        "accounts",
                        {"account": account, "debit_in_account_currency": amount, "cost_center": cost_center},
                    )
                else:
                    je.append(
                        "accounts",
                        {
                            "account": account,
                            "credit_in_account_currency": abs(amount),
                            "cost_center": cost_center,
                        },
                    )

            # Validate that we have entries
            if len(je.accounts) < 2:
                # Journal entry needs at least 2 lines
                errors.append(f"Memorial {mutation_nr}: Not enough account entries")
                continue

            # Check if balanced
            total_debit = sum(row.debit_in_account_currency for row in je.accounts)
            total_credit = sum(row.credit_in_account_currency for row in je.accounts)

            if abs(total_debit - total_credit) > 0.01:
                # Not balanced, try to add balancing entry
                diff = total_debit - total_credit

                # Get a default clearing account
                clearing_account = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Temporary", "is_group": 0}, "name"
                )

                if not clearing_account:
                    # Try to find any suitable account
                    clearing_account = frappe.db.get_value(
                        "Account",
                        {"company": company, "is_group": 0, "account_name": ["like", "%clearing%"]},
                        "name",
                    )

                if clearing_account:
                    if diff > 0:
                        je.append(
                            "accounts",
                            {
                                "account": clearing_account,
                                "credit_in_account_currency": diff,
                                "cost_center": cost_center,
                            },
                        )
                    else:
                        je.append(
                            "accounts",
                            {
                                "account": clearing_account,
                                "debit_in_account_currency": abs(diff),
                                "cost_center": cost_center,
                            },
                        )

            # Insert and submit
            try:
                je.insert(ignore_permissions=True)
                je.submit()
                created += 1
            except IntegrityError as ie:
                if "Duplicate entry" in str(ie) and "eboekhouden_mutation_nr" in str(ie):
                    # Already exists, skip
                    frappe.db.rollback()
                    skipped += 1
                    skip_reasons["duplicate_entry"] = skip_reasons.get("duplicate_entry", 0) + 1
                    continue
                else:
                    raise

        except Exception as e:
            errors.append(f"Memorial {mut.get('MutatieNr')}: {str(e)}")
            migration_doc.log_error(
                f"Failed to create memorial entry {mutation_nr}: {str(e)}", "memorial", mut
            )

    # Log summary for this batch
    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"Memorial entries - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


def process_beginbalans_entries(mutations, company, cost_center, migration_doc):
    """Process BeginBalans (opening balance) entries"""
    created = 0
    errors = []
    skipped = 0
    skip_reasons = {}

    frappe.logger().info(f"Processing {len(mutations)} BeginBalans entries")

    # Check if opening balance already exists
    existing_opening_balance = frappe.db.exists(
        "Journal Entry",
        {"company": company, "user_remark": ["like", "%Opening Balance%"], "docstatus": ["!=", 2]},
    )

    if existing_opening_balance:
        skip_reasons["opening_balance_exists"] = len(mutations)
        skipped = len(mutations)
        frappe.logger().info(f"Opening balance already exists: {existing_opening_balance}")
        return {"created": 0, "errors": [], "skipped": skipped, "skip_reasons": skip_reasons}

    # Group all BeginBalans entries into a single journal entry
    je = frappe.new_doc("Journal Entry")
    je.posting_date = "2019-01-01"  # Default opening date
    je.company = company
    je.user_remark = "Opening Balance - E-Boekhouden BeginBalans"

    for mut in mutations:
        try:
            mutation_dict = mut

            # Get account code and amount
            account_code = mutation_dict.get("Rekening", "")
            debit_amount = float(mutation_dict.get("BedragDebet", 0) or 0)
            credit_amount = float(mutation_dict.get("BedragCredit", 0) or 0)
            description = mutation_dict.get("Omschrijving", "")

            if not account_code:
                errors.append(f"BeginBalans entry without account code: {mutation_dict}")
                continue

            # Find the ERPNext account
            account = frappe.db.get_value(
                "Account", {"account_number": account_code, "company": company}, "name"
            )

            if not account:
                # Try without company filter
                account = frappe.db.get_value("Account", {"account_number": account_code}, "name")

            if not account:
                errors.append(f"Account not found for code {account_code}: {description}")
                continue

            # Add to journal entry
            je.append(
                "accounts",
                {
                    "account": account,
                    "debit_in_account_currency": debit_amount,
                    "credit_in_account_currency": credit_amount,
                    "user_remark": description or "Opening balance for {account_code}",
                    "cost_center": cost_center,
                },
            )

        except Exception as e:
            errors.append(f"Error processing BeginBalans {mutation_dict}: {str(e)}")

    # Save the journal entry if it has entries and is balanced
    if len(je.accounts) >= 2:
        try:
            total_debit = sum(acc.debit_in_account_currency for acc in je.accounts)
            total_credit = sum(acc.credit_in_account_currency for acc in je.accounts)

            if abs(total_debit - total_credit) < 0.01:
                je.insert(ignore_permissions=True)
                je.submit()
                created = 1
                frappe.logger().info(f"Created opening balance journal entry {je.name}")
            else:
                errors.append(f"Opening balance not balanced. Debit: {total_debit}, Credit: {total_credit}")
                skipped = len(mutations)
                skip_reasons["unbalanced"] = len(mutations)
        except Exception as e:
            errors.append(f"Error creating opening balance journal entry: {str(e)}")
            skipped = len(mutations)
            skip_reasons["creation_error"] = len(mutations)
    else:
        skipped = len(mutations)
        skip_reasons["insufficient_accounts"] = len(mutations)

    if skipped > 0:
        skip_summary = ", ".join([f"{reason}: {count}" for reason, count in skip_reasons.items()])
        frappe.logger().info(
            f"BeginBalans entries - Created: {created}, Skipped: {skipped} ({skip_summary}), Failed: {len(errors)}"
        )

    return {"created": created, "errors": errors, "skipped": skipped, "skip_reasons": skip_reasons}


def get_processed_mutation_numbers(company):
    """Get list of already processed mutation numbers to avoid duplicates"""
    processed = set()

    # Check journal entries
    je_mutations = frappe.db.sql(
        """
        SELECT DISTINCT eboekhouden_mutation_nr
        FROM `tabJournal Entry`
        WHERE company = %s
        AND eboekhouden_mutation_nr IS NOT NULL
        AND eboekhouden_mutation_nr != ''
    """,
        company,
        as_dict=True,
    )

    for je in je_mutations:
        processed.add(str(je.eboekhouden_mutation_nr))

    # Check payment entries - both eboekhouden_mutation_nr and reference_no
    pe_mutations = frappe.db.sql(
        """
        SELECT DISTINCT eboekhouden_mutation_nr
        FROM `tabPayment Entry`
        WHERE company = %s
        AND eboekhouden_mutation_nr IS NOT NULL
        AND eboekhouden_mutation_nr != ''
    """,
        company,
        as_dict=True,
    )

    for pe in pe_mutations:
        processed.add(str(pe.eboekhouden_mutation_nr))

    # Also check reference_no for payment entries (could contain mutation numbers)
    pe_references = frappe.db.sql(
        """
        SELECT DISTINCT reference_no
        FROM `tabPayment Entry`
        WHERE company = %s
        AND reference_no REGEXP '^[0-9]+$'
        AND reference_no != ''
    """,
        company,
        as_dict=True,
    )

    for pe in pe_references:
        processed.add(str(pe.reference_no))

    return processed


def is_mutation_processed(mutation_nr, processed_set):
    """Check if a mutation has already been processed"""
    return str(mutation_nr) in processed_set


def get_last_processed_mutation_number(company):
    """Get the highest mutation number that has been processed"""
    last_processed = 0

    # Check journal entries
    last_je = frappe.db.sql(
        """
        SELECT MAX(CAST(eboekhouden_mutation_nr AS UNSIGNED)) as last_nr
        FROM `tabJournal Entry`
        WHERE company = %s
        AND eboekhouden_mutation_nr IS NOT NULL
        AND eboekhouden_mutation_nr != ''
        AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
    """,
        company,
        as_dict=True,
    )

    if last_je and last_je[0].get("last_nr"):
        last_processed = max(last_processed, int(last_je[0]["last_nr"]))

    return last_processed


@frappe.whitelist()
def resume_migration(migration_doc_name=None):
    """Resume migration from where it left of"""
    if migration_doc_name:
        # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_doc_name)
        pass
    else:
        # Get the latest migration doc
        # migration_doc = frappe.get_last_doc("E-Boekhouden Migration")
        pass

    settings = frappe.get_single("E-Boekhouden Settings")
    company = settings.default_company

    if not company:
        return {"success": False, "error": "No default company set"}

    # Get the last processed mutation number
    last_processed = get_last_processed_mutation_number(company)

    if last_processed > 0:
        frappe.msgprint(f"Resuming migration from mutation number {last_processed + 1}")
        # Update the migration logic to start from last_processed + 1
        migration_doc.resume_from_mutation = last_processed + 1

    # Run the migration
    return migrate_using_soap(migration_doc, settings)

"""
E-Boekhouden REST API Full Migration
Fetches ALL mutations by iterating through IDs and caches them
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate


@frappe.whitelist()
def export_unprocessed_mutations_csv(export_path="/tmp/unprocessed_mutations.csv"):
    """Export unprocessed mutations to CSV for easy analysis"""
    try:
        # Get unprocessed data (reuse logic from JSON export)
        result = export_unprocessed_mutations("/tmp/temp_unprocessed.json")
        if not result["success"]:
            return result

        # Read the temp JSON file
        with open("/tmp/temp_unprocessed.json", "r") as f:
            data = json.load(f)

        unprocessed = data["unprocessed_mutations"]

        # Create CSV data
        import csv

        with open(export_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "mutation_id",
                "mutation_type",
                "mutation_date",
                "invoice_number",
                "description",
                "amount",
                "relation_id",
                "ledger_id",
                "issues",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for mutation in unprocessed:
                writer.writerow(
                    {
                        "mutation_id": mutation.get("mutation_id", ""),
                        "mutation_type": mutation.get("mutation_type", ""),
                        "mutation_date": mutation.get("mutation_date", ""),
                        "invoice_number": mutation.get("invoice_number", ""),
                        "description": mutation.get("description", "")[:100],  # Truncate for CSV
                        "amount": mutation.get("amount", ""),
                        "relation_id": mutation.get("relation_id", ""),
                        "ledger_id": mutation.get("ledger_id", ""),
                        "issues": "; ".join(mutation.get("issues", [])),
                    }
                )

        # Clean up temp file
        import os

        if os.path.exists("/tmp/temp_unprocessed.json"):
            os.remove("/tmp/temp_unprocessed.json")

        return {
            "success": True,
            "export_path": export_path,
            "total_unprocessed": len(unprocessed),
            "file_size_kb": round(os.path.getsize(export_path) / 1024, 2),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def export_unprocessed_mutations(export_path="/tmp/unprocessed_mutations.json"):
    """Export all unprocessed mutations to a local file for analysis"""
    try:
        # Get all cached mutations
        cached_mutations = frappe.get_all(
            "EBoekhouden REST Mutation Cache",
            fields=["mutation_id", "mutation_data", "mutation_type", "mutation_date"],
            limit_page_length=0,
            order_by="mutation_id",
        )

        # Get all successfully imported mutation IDs
        imported_journal_entries = frappe.get_all(
            "Journal Entry",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        imported_payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        imported_sales_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        imported_purchase_invoices = frappe.get_all(
            "Purchase Invoice",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        # Create set of imported IDs for fast lookup
        imported_ids = set()
        for doc_list in [
            imported_journal_entries,
            imported_payment_entries,
            imported_sales_invoices,
            imported_purchase_invoices,
        ]:
            for doc in doc_list:
                if doc.get("eboekhouden_mutation_nr"):
                    imported_ids.add(int(doc["eboekhouden_mutation_nr"]))

        # Find unprocessed mutations
        unprocessed_mutations = []

        for cached in cached_mutations:
            mutation_id = cached.get("mutation_id")
            if mutation_id and int(mutation_id) not in imported_ids:
                # Parse mutation data to extract key fields
                try:
                    mutation_data = json.loads(cached.get("mutation_data", "{}"))
                    unprocessed_mutations.append(
                        {
                            "mutation_id": mutation_id,
                            "mutation_type": mutation_data.get("type"),
                            "mutation_date": mutation_data.get("date"),
                            "invoice_number": mutation_data.get("invoiceNumber"),
                            "description": mutation_data.get("description", "")[:200],  # Truncate
                            "amount": mutation_data.get("amount"),
                            "relation_id": mutation_data.get("relationId"),
                            "ledger_id": mutation_data.get("ledgerId"),
                            "row_count": len(mutation_data.get("rows", [])),
                            "issues": [],  # Can be populated with specific issues later
                        }
                    )
                except Exception as e:
                    unprocessed_mutations.append(
                        {
                            "mutation_id": mutation_id,
                            "mutation_type": "UNKNOWN",
                            "issues": [f"Failed to parse cached data: {str(e)}"],
                        }
                    )

        # Create summary data
        export_data = {
            "export_timestamp": frappe.utils.now_datetime().isoformat(),
            "total_cached": len(cached_mutations),
            "total_imported": len(imported_ids),
            "total_unprocessed": len(unprocessed_mutations),
            "unprocessed_mutations": unprocessed_mutations,
            "summary": {
                "by_type": {},
                "by_month": {},
                "with_issues": len([m for m in unprocessed_mutations if m.get("issues")]),
            },
        }

        # Add type and month analysis
        for mutation in unprocessed_mutations:
            mut_type = mutation.get("mutation_type", "UNKNOWN")
            export_data["summary"]["by_type"][mut_type] = (
                export_data["summary"]["by_type"].get(mut_type, 0) + 1
            )

            mut_date = mutation.get("mutation_date", "")
            if mut_date:
                try:
                    month_key = mut_date[:7]  # YYYY-MM
                    export_data["summary"]["by_month"][month_key] = (
                        export_data["summary"]["by_month"].get(month_key, 0) + 1
                    )
                except:
                    pass

        # Write to file
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        # Calculate file size
        import os

        file_size_kb = round(os.path.getsize(export_path) / 1024, 2)

        return {
            "success": True,
            "export_path": export_path,
            "total_cached": len(cached_mutations),
            "total_imported": len(imported_ids),
            "total_unprocessed": len(unprocessed_mutations),
            "file_size_kb": file_size_kb,
            "summary": export_data["summary"],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def migration_status_summary(company=None):
    """Get a summary of migration status across all data types"""
    try:
        if not company:
            # Get default company from settings
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified and no default company in settings"}

        summary = {"company": company, "data_types": {}}

        # Accounts
        account_count = frappe.db.count("Account", {"company": company, "is_group": 0})
        eb_account_count = frappe.db.count(
            "Account", {"company": company, "is_group": 0, "eboekhouden_grootboek_nummer": ["!=", ""]}
        )
        summary["data_types"]["accounts"] = {
            "total": account_count,
            "from_eboekhouden": eb_account_count,
            "percentage": round((eb_account_count / account_count * 100) if account_count > 0 else 0, 1),
        }

        # Cost Centers
        cc_count = frappe.db.count("Cost Center", {"company": company, "is_group": 0})
        eb_cc_count = frappe.db.count(
            "Cost Center", {"company": company, "is_group": 0, "eboekhouden_kostenplaats_id": ["!=", ""]}
        )
        summary["data_types"]["cost_centers"] = {
            "total": cc_count,
            "from_eboekhouden": eb_cc_count,
            "percentage": round((eb_cc_count / cc_count * 100) if cc_count > 0 else 0, 1),
        }

        # Transactions (Journal Entries from eBoekhouden)
        je_count = frappe.db.count("Journal Entry", {"company": company})
        eb_je_count = frappe.db.count(
            "Journal Entry", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["journal_entries"] = {
            "total": je_count,
            "from_eboekhouden": eb_je_count,
            "percentage": round((eb_je_count / je_count * 100) if je_count > 0 else 0, 1),
        }

        # Payment Entries
        pe_count = frappe.db.count("Payment Entry", {"company": company})
        eb_pe_count = frappe.db.count(
            "Payment Entry", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["payment_entries"] = {
            "total": pe_count,
            "from_eboekhouden": eb_pe_count,
            "percentage": round((eb_pe_count / pe_count * 100) if pe_count > 0 else 0, 1),
        }

        # Sales Invoices
        si_count = frappe.db.count("Sales Invoice", {"company": company})
        eb_si_count = frappe.db.count(
            "Sales Invoice", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["sales_invoices"] = {
            "total": si_count,
            "from_eboekhouden": eb_si_count,
            "percentage": round((eb_si_count / si_count * 100) if si_count > 0 else 0, 1),
        }

        # Purchase Invoices
        pi_count = frappe.db.count("Purchase Invoice", {"company": company})
        eb_pi_count = frappe.db.count(
            "Purchase Invoice", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["purchase_invoices"] = {
            "total": pi_count,
            "from_eboekhouden": eb_pi_count,
            "percentage": round((eb_pi_count / pi_count * 100) if pi_count > 0 else 0, 1),
        }

        # Cache status
        cache_count = frappe.db.count("EBoekhouden REST Mutation Cache")
        summary["cache_status"] = {"total_mutations_cached": cache_count}

        # Calculate overall migration percentage
        total_eb_records = (
            eb_account_count + eb_cc_count + eb_je_count + eb_pe_count + eb_si_count + eb_pi_count
        )
        total_records = account_count + cc_count + je_count + pe_count + si_count + pi_count
        summary["overall_percentage"] = round(
            (total_eb_records / total_records * 100) if total_records > 0 else 0, 1
        )

        return {"success": True, "summary": summary}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _check_if_already_imported(mutation_id, doctype):
    """Check if a mutation has already been imported"""
    existing = frappe.db.get_value(doctype, {"eboekhouden_mutation_nr": str(mutation_id)}, "name")
    return existing is not None


def create_invoice_line_for_tegenrekening(
    tegenrekening_code=None, amount=0, description="", transaction_type="purchase"
):
    """
    Enhanced invoice line creation with smart tegenrekening account mapping
    """
    # Default accounts based on transaction type
    default_accounts = {
        "purchase": "44009 - Onvoorziene kosten - NVV",  # Unforeseen costs for purchases
        "sales": "41199 - Overige opbrengsten - NVV",  # Other revenues for sales
    }

    # Try to map tegenrekening code to an account if provided
    if tegenrekening_code and str(tegenrekening_code).strip():
        # Check if we have a mapping for this tegenrekening
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_id": str(tegenrekening_code)}, "erpnext_account"
        )

        if mapping:
            account = mapping
        else:
            # Check if there's an account with this number
            account_with_number = frappe.db.get_value(
                "Account", {"account_number": str(tegenrekening_code)}, "name"
            )

            if account_with_number:
                account = account_with_number
            else:
                # Use default account
                account = default_accounts.get(transaction_type, default_accounts["purchase"])
    else:
        # No tegenrekening provided, use default
        account = default_accounts.get(transaction_type, default_accounts["purchase"])

    # Create the line dict
    line_dict = {
        "expense_account" if transaction_type == "purchase" else "income_account": account,
        "description": description or "eBoekhouden Transaction",
        "qty": 1,
        "rate": abs(amount),
        "amount": abs(amount),
    }

    return line_dict


@frappe.whitelist()
def full_rest_migration_all_mutations(
    migration_name, company=None, cost_center=None, max_mutations=None, date_from=None, date_to=None
):
    """
    Full migration using REST API to fetch ALL mutations by iterating through IDs
    """
    try:
        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.rest_api_token:
            return {
                "success": False,
                "error": "REST API token not configured in E-Boekhouden Settings",
            }

        if not company:
            company = settings.default_company
        if not company:
            return {"success": False, "error": "No company specified"}

        # Cache ALL mutations first
        total_cached, total_new = _cache_all_mutations(settings)

        # Get cached mutations for migration
        cache_filter = {}
        if date_from:
            cache_filter["mutation_date"] = [">=", date_from]
        if date_to:
            if "mutation_date" in cache_filter:
                cache_filter["mutation_date"] = ["between", [date_from, date_to]]
            else:
                cache_filter["mutation_date"] = ["<=", date_to]

        cached_mutations = frappe.get_all(
            "EBoekhouden REST Mutation Cache",
            filters=cache_filter,
            fields=["mutation_id", "mutation_data", "mutation_type", "mutation_date"],
            order_by="mutation_id",
            limit_page_length=max_mutations if max_mutations else 0,
        )

        if not cached_mutations:
            return {
                "success": False,
                "error": "No cached mutations found for the specified criteria",
                "total_cached": total_cached,
                "total_new": total_new,
            }

        # Parse mutations and import in batches
        mutations = []
        for cached in cached_mutations:
            try:
                mutation_data = json.loads(cached.get("mutation_data", "{}"))
                mutations.append(mutation_data)
            except Exception as e:
                frappe.logger().error(
                    f"Failed to parse cached mutation {cached.get('mutation_id')}: {str(e)}"
                )

        # Import in batches
        batch_size = 50
        total_imported = 0
        total_failed = 0
        all_errors = []

        for i in range(0, len(mutations), batch_size):
            batch = mutations[i : i + batch_size]
            result = _import_rest_mutations_batch(migration_name, batch, settings)

            total_imported += result.get("imported", 0)
            total_failed += result.get("failed", 0)
            all_errors.extend(result.get("errors", []))

            # Progress update
            frappe.publish_realtime(
                "migration_progress",
                {
                    "migration_name": migration_name,
                    "current_operation": "Imported {total_imported} mutations",
                    "progress_percentage": min(
                        90, (i + batch_size) / len(mutations) * 80
                    ),  # Leave 20% for cleanup
                },
                user=frappe.session.user,
            )

        return {
            "success": True,
            "total_cached": total_cached,
            "total_new": total_new,
            "total_found": len(cached_mutations),
            "total_imported": total_imported,
            "total_failed": total_failed,
            "errors": all_errors[:50],  # Limit error list size
            "company": company,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _cache_all_mutations(settings):
    """Cache all mutations from eBoekhouden REST API by iterating through IDs"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Try to get highest mutation ID to determine range
        # We'll iterate from 1 up to a reasonable limit or until we hit consecutive failures
        max_id = 50000  # Conservative upper bound
        batch_size = 100
        consecutive_failures = 0
        max_consecutive_failures = 50  # Stop after 50 consecutive failures

        total_cached = 0
        total_new = 0

        # Get existing cached IDs for quick lookup
        existing_ids = set()
        existing_cache = frappe.get_all(
            "EBoekhouden REST Mutation Cache", fields=["mutation_id"], limit_page_length=0
        )
        for cache in existing_cache:
            existing_ids.add(int(cache["mutation_id"]))

        for start_id in range(1, max_id + 1, batch_size):
            end_id = min(start_id + batch_size - 1, max_id)
            batch_new = 0
            batch_failures = 0

            for mutation_id in range(start_id, end_id + 1):
                # Skip if already cached
                if mutation_id in existing_ids:
                    total_cached += 1
                    continue

                # Fetch from API
                result = api.make_request("v1/mutation/{mutation_id}")

                if result and result.get("success") and result.get("status_code") == 200:
                    # Parse mutation data
                    try:
                        mutation_data = json.loads(result.get("data", "{}"))

                        # Create cache entry
                        cache_doc = frappe.new_doc("EBoekhouden REST Mutation Cache")
                        cache_doc.mutation_id = str(mutation_id)
                        cache_doc.mutation_data = result.get("data")
                        cache_doc.mutation_type = mutation_data.get("type", 0)
                        cache_doc.mutation_date = mutation_data.get("date")
                        cache_doc.save()

                        batch_new += 1
                        total_new += 1
                        consecutive_failures = 0

                    except Exception as e:
                        frappe.logger().error(f"Failed to cache mutation {mutation_id}: {str(e)}")
                        batch_failures += 1
                        consecutive_failures += 1
                else:
                    batch_failures += 1
                    consecutive_failures += 1

                # Stop if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    frappe.logger().info(
                        f"Stopping cache process at mutation {mutation_id} due to {consecutive_failures} consecutive failures"
                    )
                    break

            # Commit batch
            if batch_new > 0:
                frappe.db.commit()

            # Progress update
            frappe.publish_realtime(
                "cache_progress",
                {
                    "operation": "Caching mutations from eBoekhouden",
                    "progress_percentage": min(80, (end_id / max_id) * 80),  # Leave 20% for processing
                    "current_id": end_id,
                    "total_new": total_new,
                    "total_cached": total_cached,
                },
                user=frappe.session.user,
            )

            # Break if we've hit too many consecutive failures
            if consecutive_failures >= max_consecutive_failures:
                break

        return total_cached, total_new

    except Exception as e:
        frappe.logger().error(f"Error in _cache_all_mutations: {str(e)}")
        return 0, 0


@frappe.whitelist()
def get_progress_info():
    """Get real-time progress information for the migration"""
    # This will be called by frontend to get progress updates
    return {"status": "running", "message": "Migration in progress..."}


@frappe.whitelist()
def test_single_mutation_import(mutation_id):
    """Test importing a single mutation for debugging"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Fetch specific mutation
        result = api.make_request("v1/mutation/{mutation_id}")

        if result and result.get("success") and result.get("status_code") == 200:
            mutation_data = json.loads(result.get("data", "{}"))

            # Try to import it
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company
            cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

            if not cost_center:
                return {"success": False, "error": "No cost center found"}

            # Import single mutation
            result = _import_rest_mutations_batch("TEST", [mutation_data], settings)

            return {
                "success": True,
                "mutation_data": mutation_data,
                "import_result": result,
                "company": company,
                "cost_center": cost_center,
            }
        else:
            return {"success": False, "error": "Failed to fetch mutation {mutation_id} from API"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _import_rest_mutations_batch(migration_name, mutations, settings):
    """Import a batch of REST API mutations with smart tegenrekening mapping"""
    imported = 0
    errors = []
    debug_info = []
    opening_balances_imported = False

    debug_info.append(f"Starting import with {len(mutations) if mutations else 0} mutations")

    if not mutations:
        debug_info.append("No mutations provided, returning early")
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info), "REST Batch Debug")
        return {"imported": 0, "failed": 0, "errors": []}

    # # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)  # Not needed for batch processing
    company = settings.default_company
    debug_info.append(f"Company: {company}")

    # Get cost center
    cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

    debug_info.append(f"Cost center found: {cost_center}")

    if not cost_center:
        errors.append("No cost center found")
        debug_info.append("ERROR - No cost center found")
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info), "REST Batch Debug")
        return {"imported": 0, "failed": len(mutations), "errors": errors}

    for i, mutation in enumerate(mutations):
        try:
            # Skip if already imported
            mutation_id = mutation.get("id")
            if not mutation_id:
                errors.append("Mutation missing ID, skipping")
                debug_info.append("ERROR - Mutation missing ID")
                continue

            # Check for existing documents
            existing_je = _check_if_already_imported(mutation_id, "Journal Entry")
            existing_pe = _check_if_already_imported(mutation_id, "Payment Entry")
            existing_si = _check_if_already_imported(mutation_id, "Sales Invoice")
            existing_pi = _check_if_already_imported(mutation_id, "Purchase Invoice")

            if existing_je or existing_pe or existing_si or existing_pi:
                debug_info.append(f"Mutation {mutation_id} already imported, skipping")
                continue

            mutation_type = mutation.get("type", 0)
            description = mutation.get("description", "eBoekhouden Import {mutation_id}")
            amount = frappe.utils.flt(mutation.get("amount", 0), 2)
            relation_id = mutation.get("relationId")
            invoice_number = mutation.get("invoiceNumber")
            ledger_id = mutation.get("ledgerId")
            rows = mutation.get("rows", [])

            debug_info.append(
                f"Processing mutation {mutation_id}: type={mutation_type}, amount={amount}, ledger={ledger_id}, rows={len(rows)}"
            )

            # Special handling for opening balances (type 0)
            if mutation_type == 0 and not opening_balances_imported:
                debug_info.append(
                    "Skipping opening balance mutation - should be imported via separate process"
                )
                continue

            # Skip if no amount and no rows (empty transaction)
            if amount == 0 and len(rows) == 0:
                debug_info.append(f"Skipping empty mutation {mutation_id}")
                continue

            # Handle different mutation types
            if mutation_type == 1:  # Sales Invoice
                debug_info.append("Type 1 (Sales Invoice) - creating Sales Invoice")

                # Create Sales Invoice
                si = frappe.new_doc("Sales Invoice")
                si.company = company
                si.posting_date = mutation.get("date")
                si.customer = relation_id if relation_id else "Guest Customer"
                si.eboekhouden_mutation_nr = str(mutation_id)

                # Set invoice number from eBoekhouden
                if invoice_number:
                    si.name = invoice_number

                # Create invoice line
                line_dict = create_invoice_line_for_tegenrekening(
                    tegenrekening_code=ledger_id,
                    amount=amount,
                    description=description,
                    transaction_type="sales",
                )

                si.append(
                    "items",
                    {
                        "item_code": "Service Item",  # Default service item
                        "description": line_dict["description"],
                        "qty": line_dict["qty"],
                        "rate": line_dict["rate"],
                        "amount": line_dict["amount"],
                        "income_account": line_dict["income_account"],
                        "cost_center": cost_center,
                    },
                )

                si.save()
                si.submit()
                imported += 1
                debug_info.append(f"Successfully created Sales Invoice {si.name}")
                continue

            elif mutation_type == 2:  # Purchase Invoice
                debug_info.append("Type 2 (Purchase Invoice) - creating Purchase Invoice")

                # Create Purchase Invoice
                pi = frappe.new_doc("Purchase Invoice")
                pi.company = company
                pi.posting_date = mutation.get("date")
                pi.supplier = relation_id if relation_id else "Default Supplier"
                pi.eboekhouden_mutation_nr = str(mutation_id)

                # Set bill number from eBoekhouden
                if invoice_number:
                    pi.bill_no = invoice_number

                # Create invoice line
                line_dict = create_invoice_line_for_tegenrekening(
                    tegenrekening_code=ledger_id,
                    amount=amount,
                    description=description,
                    transaction_type="purchase",
                )

                pi.append(
                    "items",
                    {
                        "item_code": "Service Item",  # Default service item
                        "description": line_dict["description"],
                        "qty": line_dict["qty"],
                        "rate": line_dict["rate"],
                        "amount": line_dict["amount"],
                        "expense_account": line_dict["expense_account"],
                        "cost_center": cost_center,
                    },
                )

                pi.save()
                pi.submit()
                imported += 1
                debug_info.append(f"Successfully created Purchase Invoice {pi.name}")
                continue

            elif mutation_type in [3, 4]:  # Payment types
                debug_info.append(f"Type {mutation_type} (Payment) - creating Payment Entry")

                # Determine payment type
                payment_type = "Receive" if mutation_type == 3 else "Pay"

                # Create Payment Entry
                pe = frappe.new_doc("Payment Entry")
                pe.company = company
                pe.posting_date = mutation.get("date")
                pe.payment_type = payment_type
                pe.eboekhouden_mutation_nr = str(mutation_id)

                # Set accounts based on payment type
                if payment_type == "Receive":
                    pe.paid_to = "10000 - Kas - NVV"  # Default cash account
                    pe.received_amount = amount
                    if relation_id:
                        pe.party_type = "Customer"
                        pe.party = relation_id
                        pe.paid_from = frappe.db.get_value(
                            "Account", {"account_type": "Receivable", "company": company}, "name"
                        )
                else:
                    pe.paid_from = "10000 - Kas - NVV"  # Default cash account
                    pe.paid_amount = amount
                    if relation_id:
                        pe.party_type = "Supplier"
                        pe.party = relation_id
                        pe.paid_to = frappe.db.get_value(
                            "Account", {"account_type": "Payable", "company": company}, "name"
                        )

                pe.reference_no = invoice_number if invoice_number else "EB-{mutation_id}"
                pe.reference_date = mutation.get("date")

                pe.save()
                pe.submit()
                imported += 1
                debug_info.append(f"Successfully created Payment Entry {pe.name}")
                continue

            # For other types or complex mutations, create Journal Entry
            if len(rows) > 0:
                debug_info.append(
                    "Creating Journal Entry for mutation type {mutation_type} with {len(rows)} rows"
                )

                # For Type 7 (memorial bookings), check if this should be a Purchase Debit Note
                if mutation_type == 7 and len(rows) == 1 and relation_id:
                    row = rows[0]
                    row_ledger_id = row.get("ledgerId")
                    row_amount = frappe.utils.flt(row.get("amount", 0), 2)

                    # Check if the row ledger maps to an expense account and has a supplier
                    if row_ledger_id:
                        mapping_result = frappe.db.sql(
                            """SELECT erpnext_account
                               FROM `tabE-Boekhouden Ledger Mapping`
                               WHERE ledger_id = %s
                               LIMIT 1""",
                            row_ledger_id,
                        )

                        if mapping_result:
                            row_account = mapping_result[0][0]
                            account_type = frappe.db.get_value("Account", row_account, "account_type")
                            root_type = frappe.db.get_value("Account", row_account, "root_type")

                            if root_type == "Expense" and row_amount > 0:
                                debug_info.append(
                                    "Creating Purchase Debit Note for Type 7 mutation with expense account"
                                )

                                # Create Purchase Invoice (Debit Note)
                                pi = frappe.new_doc("Purchase Invoice")
                                pi.company = company
                                pi.posting_date = mutation.get("date")
                                pi.supplier = relation_id
                                pi.eboekhouden_mutation_nr = str(mutation_id)
                                pi.is_return = 1  # Mark as debit note

                                if invoice_number:
                                    pi.bill_no = invoice_number

                                # Create invoice line
                                pi.append(
                                    "items",
                                    {
                                        "item_code": "Service Item",
                                        "description": description,
                                        "qty": 1,
                                        "rate": row_amount,
                                        "amount": row_amount,
                                        "expense_account": row_account,
                                        "cost_center": cost_center,
                                    },
                                )

                                try:
                                    pi.save()
                                    pi.submit()
                                    imported += 1
                                    debug_info.append(
                                        "Successfully created Purchase Debit Note for Type 7 mutation {mutation_id}"
                                    )
                                    continue  # Skip journal entry creation
                                except Exception as e:
                                    debug_info.append(
                                        f"Failed to create Purchase Debit Note for mutation {mutation_id}: {str(e)}"
                                    )
                                    # Fall through to create journal entry instead

                    je = frappe.new_doc("Journal Entry")
                    je.company = company
                    je.posting_date = mutation.get("date")
                    je.voucher_type = "Journal Entry"

                    # Set descriptive name and title immediately
                    invoice_number = mutation.get("invoiceNumber")
                    if invoice_number:
                        # Clean invoice number for use in name (remove special characters)
                        clean_invoice = (
                            str(invoice_number).replace("/", "-").replace("\\", "-").replace(" ", "-")
                        )
                        je.name = f"EBH-{clean_invoice}"
                        je.title = "eBoekhouden {invoice_number}"
                    else:
                        # Give more descriptive names based on mutation type
                        type_names = {
                            0: "Opening Balance",
                            5: "Money Received",
                            6: "Money Paid",
                            7: "Memorial Booking",
                            8: "Bank Import",
                            9: "Manual Entry",
                            10: "Stock Mutation",
                        }
                        type_name = type_names.get(mutation_type, "Type {mutation_type}")
                        je.name = f"EBH-{type_name}-{mutation_id}"
                        je.title = f"eBoekhouden {type_name} #{mutation_id}"

                    je.eboekhouden_mutation_nr = str(mutation_id)
                    je.eboekhouden_main_ledger_id = str(ledger_id) if ledger_id else ""
                    je.user_remark = description

                    # Check if this is a multi-line journal entry
                    if len(rows) > 1:
                        # Multi-line journal entry - process each row separately
                        debug_info.append(f"Multi-line journal entry with {len(rows)} rows")
                        total_debit = 0
                        total_credit = 0
                        processed_ledgers = set()  # Track which ledgers we've processed

                        for row_index, row in enumerate(rows):
                            row_amount = frappe.utils.flt(row.get("amount", 0), 2)
                            row_ledger_id = row.get("ledgerId")
                            row_description = row.get("description", description)

                            # Memorial bookings (type 7) use simple paired entries approach:
                            # Each row creates a direct pair with the main ledger
                            # No complex balancing - just direct transactions
                            is_memorial_booking = mutation_type == 7
                            if is_memorial_booking:
                                debug_info.append(
                                    "Memorial booking row: amount {row_amount}, ledger {row_ledger_id}"
                                )

                            # Track processed ledgers to identify the source account
                            if row_ledger_id:
                                processed_ledgers.add(str(row_ledger_id))

                            # Get account mapping for this row
                            row_account = None
                            row_party_type = None
                            row_party = None

                            if row_ledger_id:
                                # Check ledger mapping - use the ledger_id field to find the mapping
                                mapping_result = frappe.db.sql(
                                    """SELECT erpnext_account
                                       FROM `tabE-Boekhouden Ledger Mapping`
                                       WHERE ledger_id = %s
                                       LIMIT 1""",
                                    row_ledger_id,
                                )

                                if mapping_result:
                                    row_account = mapping_result[0][0]

                                    # Check if it's a receivable/payable account
                                    account_type = frappe.db.get_value("Account", row_account, "account_type")

                                    if account_type == "Receivable":
                                        row_party_type = "Customer"
                                        # For memorial entries (type 7), use company as party for internal transactions
                                        if mutation_type == 7:
                                            # Use company as customer for internal receivable transactions
                                            row_party = _get_or_create_company_as_customer(
                                                company, debug_info
                                            )
                                            debug_info.append(
                                                "Using company as customer for memorial receivable entry"
                                            )
                                        elif relation_id:
                                            row_party = _get_or_create_customer(relation_id, debug_info)
                                        else:
                                            # Create generic customer for receivable without relation
                                            row_party = _get_or_create_generic_customer(
                                                row_description, debug_info
                                            )

                                        # Check if party creation failed
                                        if not row_party:
                                            debug_info.append(
                                                "WARNING: Failed to create customer for receivable account {row_account}, skipping party assignment"
                                            )
                                            row_party_type = None
                                    elif account_type == "Payable":
                                        row_party_type = "Supplier"
                                        # For memorial entries (type 7), use company as party for internal transactions
                                        if mutation_type == 7:
                                            # Use company as supplier for internal payable transactions
                                            row_party = _get_or_create_company_as_supplier(
                                                company, debug_info
                                            )
                                            debug_info.append(
                                                "Using company as supplier for memorial payable entry"
                                            )
                                        elif relation_id:
                                            row_party = _get_or_create_supplier(
                                                relation_id, row_description, debug_info
                                            )
                                        else:
                                            # Create generic supplier for payable without relation
                                            row_party = _get_or_create_generic_supplier(
                                                row_description, debug_info
                                            )

                                        # Check if party creation failed
                                        if not row_party:
                                            debug_info.append(
                                                "WARNING: Failed to create supplier for payable account {row_account}, skipping party assignment"
                                            )
                                            row_party_type = None

                            # If no account found, use smart mapping
                            if not row_account:
                                line_dict = create_invoice_line_for_tegenrekening(
                                    tegenrekening_code=str(row_ledger_id) if row_ledger_id else None,
                                    amount=abs(row_amount),
                                    description=row_description,
                                    transaction_type="purchase",
                                )
                                row_account = (
                                    line_dict.get("expense_account") or "44009 - Onvoorziene kosten - NVV"
                                )

                            # Skip rows with zero amounts to avoid "Both Debit and Credit values cannot be zero" error
                            if row_amount == 0:
                                debug_info.append(
                                    "Skipping row with zero amount: ledger {row_ledger_id}, account {row_account}"
                                )
                                continue

                            # For memorial bookings, create paired entries
                            if is_memorial_booking and ledger_id:
                                # Get main ledger account first
                                main_mapping_result = frappe.db.sql(
                                    """SELECT erpnext_account
                                       FROM `tabE-Boekhouden Ledger Mapping`
                                       WHERE ledger_id = %s
                                       LIMIT 1""",
                                    ledger_id,
                                )

                                if main_mapping_result:
                                    main_account = main_mapping_result[0][0]
                                    abs_amount = abs(row_amount)

                                    if row_amount > 0:
                                        # Positive row amount: Main ledger provides (debit), Row ledger receives (credit)
                                        main_debit = abs_amount
                                        main_credit = 0
                                        row_debit = 0
                                        row_credit = abs_amount
                                        debug_info.append(
                                            "Memorial: €{abs_amount} FROM {main_account} TO {row_account}"
                                        )
                                    else:
                                        # Negative row amount: Main ledger receives (credit), Row ledger provides (debit)
                                        main_debit = 0
                                        main_credit = abs_amount
                                        row_debit = abs_amount
                                        row_credit = 0
                                        debug_info.append(
                                            "Memorial: €{abs_amount} FROM {row_account} TO {main_account}"
                                        )

                                    # Add main ledger entry
                                    main_line = {
                                        "account": main_account,
                                        "debit_in_account_currency": frappe.utils.flt(main_debit, 2),
                                        "credit_in_account_currency": frappe.utils.flt(main_credit, 2),
                                        "cost_center": cost_center,
                                        "user_remark": "Memorial booking main ledger: {description}",
                                    }

                                    # Add main ledger party details if needed
                                    main_account_type = frappe.db.get_value(
                                        "Account", main_account, "account_type"
                                    )
                                    if main_account_type == "Receivable":
                                        main_line["party_type"] = "Customer"
                                        main_line["party"] = _get_or_create_company_as_customer(
                                            company, debug_info
                                        )
                                    elif main_account_type == "Payable":
                                        main_line["party_type"] = "Supplier"
                                        main_line["party"] = _get_or_create_company_as_supplier(
                                            company, debug_info
                                        )

                                    je.append("accounts", main_line)
                                    total_debit += main_line["debit_in_account_currency"]
                                    total_credit += main_line["credit_in_account_currency"]

                                    # Create row ledger entry
                                    entry_line = {
                                        "account": row_account,
                                        "debit_in_account_currency": frappe.utils.flt(row_debit, 2),
                                        "credit_in_account_currency": frappe.utils.flt(row_credit, 2),
                                        "cost_center": cost_center,
                                        "user_remark": row_description,
                                    }
                                else:
                                    frappe.throw(
                                        "Memorial booking {mutation_id}: No mapping found for main ledger {ledger_id}. "
                                        "This ledger must be mapped to create a proper memorial booking."
                                    )
                            else:
                                # Non-memorial booking: use original logic
                                entry_line = {
                                    "account": row_account,
                                    "debit_in_account_currency": frappe.utils.flt(
                                        row_amount if row_amount > 0 else 0, 2
                                    ),
                                    "credit_in_account_currency": frappe.utils.flt(
                                        -row_amount if row_amount < 0 else 0, 2
                                    ),
                                    "cost_center": cost_center,
                                    "user_remark": row_description,
                                }

                            # Add party details if needed
                            if row_party_type and row_party:
                                entry_line["party_type"] = row_party_type
                                entry_line["party"] = row_party

                                # Try to link to specific invoice for reconciliation
                                if invoice_number and row_party_type in ["Customer", "Supplier"]:
                                    invoice_doctype = (
                                        "Sales Invoice"
                                        if row_party_type == "Customer"
                                        else "Purchase Invoice"
                                    )
                                    invoice_field = "name" if row_party_type == "Customer" else "bill_no"

                                    matching_invoice = frappe.db.get_value(
                                        invoice_doctype,
                                        {
                                            invoice_field: invoice_number,
                                            "customer"
                                            if row_party_type == "Customer"
                                            else "supplier": row_party,
                                        },
                                        "name",
                                    )

                                    if matching_invoice:
                                        entry_line["reference_type"] = invoice_doctype
                                        entry_line["reference_name"] = matching_invoice
                                        debug_info.append(
                                            f"Linked journal entry line to {invoice_doctype} {matching_invoice}"
                                        )

                            je.append("accounts", entry_line)

                            # Track totals for balance validation
                            total_debit += entry_line["debit_in_account_currency"]
                            total_credit += entry_line["credit_in_account_currency"]

                        # Memorial bookings are now handled inline with paired entries
                        # No additional balancing needed since each row creates a complete transaction

                        # Final balance check
                        debug_info.append(
                            "Final totals - Total debit: {total_debit}, Total credit: {total_credit}"
                        )
                        if abs(total_debit - total_credit) > 0.01:
                            debug_info.append(
                                "WARNING: Journal entry still not balanced! Difference: {total_debit - total_credit}"
                            )

                    else:
                        # Single line entry - create a two-line entry using BOTH the row ledger and main ledger
                        # This handles cases like mutation 4595 where:
                        # - Main ledger: Income account (99998)
                        # - Row ledger: Equity account (05000)
                        # - Need to transfer from income TO equity

                        # Get the row account (from the single row)
                        row_account = None
                        row_party_type = None
                        row_party = None
                        row_amount = frappe.utils.flt(rows[0].get("amount", 0), 2)
                        row_ledger_id = rows[0].get("ledgerId")

                        if row_ledger_id:
                            # Get row account mapping
                            mapping_result = frappe.db.sql(
                                """SELECT erpnext_account
                                   FROM `tabE-Boekhouden Ledger Mapping`
                                   WHERE ledger_id = %s
                                   LIMIT 1""",
                                row_ledger_id,
                            )

                            if mapping_result:
                                row_account = mapping_result[0][0]

                                # Check if it's a receivable/payable account
                                account_type = frappe.db.get_value("Account", row_account, "account_type")
                                debug_info.append(f"Row account {row_account} has type: {account_type}")

                                if account_type == "Receivable":
                                    row_party_type = "Customer"
                                    if mutation_type == 7:
                                        row_party = _get_or_create_company_as_customer(company, debug_info)
                                    else:
                                        row_party = _get_or_create_customer(relation_id, debug_info)
                                elif account_type == "Payable":
                                    row_party_type = "Supplier"
                                    if mutation_type == 7:
                                        row_party = _get_or_create_company_as_supplier(company, debug_info)
                                    else:
                                        row_party = _get_or_create_supplier(
                                            relation_id, description, debug_info
                                        )

                        # Get the main ledger account (contra account)
                        main_account = None
                        main_party_type = None
                        main_party = None

                        if ledger_id:
                            # Get main account mapping
                            mapping_result = frappe.db.sql(
                                """SELECT erpnext_account
                                   FROM `tabE-Boekhouden Ledger Mapping`
                                   WHERE ledger_id = %s
                                   LIMIT 1""",
                                ledger_id,
                            )

                            if mapping_result:
                                main_account = mapping_result[0][0]

                                # Check if it's a receivable/payable account
                                account_type = frappe.db.get_value("Account", main_account, "account_type")
                                debug_info.append(f"Main account {main_account} has type: {account_type}")

                                if account_type == "Receivable":
                                    main_party_type = "Customer"
                                    if mutation_type == 7:
                                        main_party = _get_or_create_company_as_customer(company, debug_info)
                                    else:
                                        main_party = _get_or_create_customer(relation_id, debug_info)
                                elif account_type == "Payable":
                                    main_party_type = "Supplier"
                                    if mutation_type == 7:
                                        main_party = _get_or_create_company_as_supplier(company, debug_info)
                                    else:
                                        main_party = _get_or_create_supplier(
                                            relation_id, description, debug_info
                                        )

                        # Create the first entry (row ledger)
                        if row_account:
                            entry_line = {
                                "account": row_account,
                                "debit_in_account_currency": frappe.utils.flt(
                                    row_amount if row_amount > 0 else 0, 2
                                ),
                                "credit_in_account_currency": frappe.utils.flt(
                                    -row_amount if row_amount < 0 else 0, 2
                                ),
                                "cost_center": cost_center,
                                "user_remark": description,
                            }

                            # Add party details if needed
                            if row_party_type and row_party:
                                entry_line["party_type"] = row_party_type
                                entry_line["party"] = row_party

                            je.append("accounts", entry_line)
                            debug_info.append(
                                "Added row entry: {row_account}, Debit: {entry_line['debit_in_account_currency']}, Credit: {entry_line['credit_in_account_currency']}"
                            )

                        # Create the balancing entry (main ledger)
                        if main_account:
                            # Reverse the amounts for the main ledger entry to balance
                            main_entry = {
                                "account": main_account,
                                "debit_in_account_currency": frappe.utils.flt(
                                    -row_amount if row_amount < 0 else 0, 2
                                ),
                                "credit_in_account_currency": frappe.utils.flt(
                                    row_amount if row_amount > 0 else 0, 2
                                ),
                                "cost_center": cost_center,
                                "user_remark": "Contra entry for {description}",
                            }

                            # Add party details if needed
                            if main_party_type and main_party:
                                main_entry["party_type"] = main_party_type
                                main_entry["party"] = main_party

                            je.append("accounts", main_entry)
                            debug_info.append(
                                "Added main entry: {main_account}, Debit: {main_entry['debit_in_account_currency']}, Credit: {main_entry['credit_in_account_currency']}"
                            )

                    # Try to save and submit the Journal Entry
                    try:
                        je.save()
                        je.submit()
                        imported += 1
                        debug_info.append(f"Successfully created Journal Entry {je.name}")
                    except Exception as e:
                        error_msg = f"Failed to save Journal Entry for mutation {mutation_id}: {str(e)}"
                        errors.append(error_msg)
                        debug_info.append(f"ERROR - {error_msg}")
                        continue

            else:
                # Simple journal entry with just the main amount
                debug_info.append(f"Creating simple Journal Entry for mutation type {mutation_type}")

                je = frappe.new_doc("Journal Entry")
                je.company = company
                je.posting_date = mutation.get("date")
                je.voucher_type = "Journal Entry"
                je.eboekhouden_mutation_nr = str(mutation_id)
                je.user_remark = description

                # Get account mapping for main ledger
                main_account = None
                if ledger_id:
                    mapping_result = frappe.db.sql(
                        """SELECT erpnext_account
                           FROM `tabE-Boekhouden Ledger Mapping`
                           WHERE ledger_id = %s
                           LIMIT 1""",
                        ledger_id,
                    )

                    if mapping_result:
                        main_account = mapping_result[0][0]

                if not main_account:
                    # Use smart mapping
                    line_dict = create_invoice_line_for_tegenrekening(
                        tegenrekening_code=str(ledger_id) if ledger_id else None,
                        amount=abs(amount),
                        description=description,
                        transaction_type="purchase",
                    )
                    main_account = line_dict.get("expense_account") or "44009 - Onvoorziene kosten - NVV"

                # Create entry
                je.append(
                    "accounts",
                    {
                        "account": main_account,
                        "debit_in_account_currency": frappe.utils.flt(amount if amount > 0 else 0, 2),
                        "credit_in_account_currency": frappe.utils.flt(-amount if amount < 0 else 0, 2),
                        "cost_center": cost_center,
                        "user_remark": description,
                    },
                )

                # Add balancing entry
                balancing_account = "9999 - Verrekeningen - NVV"  # Default balancing account
                je.append(
                    "accounts",
                    {
                        "account": balancing_account,
                        "debit_in_account_currency": frappe.utils.flt(-amount if amount < 0 else 0, 2),
                        "credit_in_account_currency": frappe.utils.flt(amount if amount > 0 else 0, 2),
                        "cost_center": cost_center,
                        "user_remark": "Balancing entry for {description}",
                    },
                )

                try:
                    je.save()
                    je.submit()
                    imported += 1
                    debug_info.append(f"Successfully created simple Journal Entry {je.name}")
                except Exception as e:
                    error_msg = f"Failed to save simple Journal Entry for mutation {mutation_id}: {str(e)}"
                    errors.append(error_msg)
                    debug_info.append(f"ERROR - {error_msg}")

        except Exception as e:
            error_msg = f"Error processing mutation {mutation.get('id', 'UNKNOWN')}: {str(e)}"
            errors.append(error_msg)
            debug_info.append(f"ERROR - {error_msg}")
            continue

    # Log debug info for troubleshooting
    if debug_info:
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info[-100:]), "REST Batch Debug")  # Last 100 lines

    return {"imported": imported, "failed": len(mutations) - imported, "errors": errors}


def _process_money_transfer_mutation(
    mutation, company, cost_center, from_account_mapping, to_account_mapping, debug_info
):
    """Process a money transfer mutation (type 5 or 6)"""
    mutation_id = mutation.get("id")
    description = mutation.get("description", "Money Transfer {mutation_id}")
    amount = abs(frappe.utils.flt(mutation.get("amount", 0), 2))
    mutation_type = mutation.get("type", 5)

    debug_info.append(f"Processing money transfer: ID={mutation_id}, Type={mutation_type}, Amount={amount}")

    # Create Journal Entry for money transfer
    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Bank Entry"  # More appropriate for money transfers
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.user_remark = description

    # Set descriptive name and title
    type_name = "Money Received" if mutation_type == 5 else "Money Paid"
    je.name = f"EBH-{type_name}-{mutation_id}"
    je.title = f"eBoekhouden {type_name} #{mutation_id}"

    from_account = from_account_mapping["erpnext_account"]
    to_account = to_account_mapping["erpnext_account"]

    debug_info.append(f"Transfer: {amount} from {from_account} to {to_account}")

    # From account (credit - money going out)
    je.append(
        "accounts",
        {
            "account": from_account,
            "credit_in_account_currency": amount,
            "cost_center": cost_center,
            "user_remark": "{description} - From",
        },
    )

    # To account (debit - money coming in)
    je.append(
        "accounts",
        {
            "account": to_account,
            "debit_in_account_currency": amount,
            "cost_center": cost_center,
            "user_remark": "{description} - To",
        },
    )

    try:
        je.save()
        je.submit()
        debug_info.append(f"Successfully created money transfer Journal Entry {je.name}")
        return je
    except Exception as e:
        debug_info.append(f"Failed to create money transfer Journal Entry: {str(e)}")
        raise


def _get_or_create_customer(relation_id, debug_info):
    """Get or create customer from eBoekhouden relation ID"""
    try:
        # Check if customer already exists
        existing_customer = frappe.db.get_value(
            "Customer", {"eboekhouden_relation_id": str(relation_id)}, "name"
        )
        if existing_customer:
            debug_info.append(f"Found existing customer: {existing_customer}")
            return existing_customer

        # Try to fetch customer data from eBoekhouden
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()
        result = api.make_request("v1/relation/{relation_id}")

        if result and result.get("success") and result.get("status_code") == 200:
            relation_data = json.loads(result.get("data", "{}"))

            # Create new customer
            customer = frappe.new_doc("Customer")
            customer.customer_name = (
                relation_data.get("bedrijfsnaam")
                or "{relation_data.get('voornaam', '')} {relation_data.get('achternaam', '')}".strip()
                or "Customer {relation_id}"
            )
            customer.eboekhouden_relation_id = str(relation_id)
            customer.customer_type = "Company" if relation_data.get("bedrijfsnaam") else "Individual"

            # Add contact information if available
            if relation_data.get("email"):
                customer.email_id = relation_data["email"]
            if relation_data.get("telefoon"):
                customer.mobile_no = relation_data["telefoon"]

            customer.save()
            debug_info.append(f"Created new customer: {customer.name}")
            return customer.name
        else:
            debug_info.append(
                "Failed to fetch relation {relation_id} from eBoekhouden, creating generic customer"
            )
            # Create generic customer if API fails
            customer = frappe.new_doc("Customer")
            customer.customer_name = "eBoekhouden Customer {relation_id}"
            customer.eboekhouden_relation_id = str(relation_id)
            customer.save()
            debug_info.append(f"Created generic customer: {customer.name}")
            return customer.name

    except Exception as e:
        debug_info.append(f"Error creating customer for relation {relation_id}: {str(e)}")
        return None


def _get_or_create_supplier(relation_id, description, debug_info):
    """Get or create supplier from eBoekhouden relation ID"""
    try:
        # Check if supplier already exists
        existing_supplier = frappe.db.get_value(
            "Supplier", {"eboekhouden_relation_id": str(relation_id)}, "name"
        )
        if existing_supplier:
            debug_info.append(f"Found existing supplier: {existing_supplier}")
            return existing_supplier

        # Try to fetch supplier data from eBoekhouden
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()
        result = api.make_request("v1/relation/{relation_id}")

        if result and result.get("success") and result.get("status_code") == 200:
            relation_data = json.loads(result.get("data", "{}"))

            # Create new supplier
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = (
                relation_data.get("bedrijfsnaam")
                or "{relation_data.get('voornaam', '')} {relation_data.get('achternaam', '')}".strip()
                or "Supplier {relation_id}"
            )
            supplier.eboekhouden_relation_id = str(relation_id)
            supplier.supplier_type = "Company" if relation_data.get("bedrijfsnaam") else "Individual"

            # Add contact information if available
            if relation_data.get("email"):
                supplier.email_id = relation_data["email"]
            if relation_data.get("telefoon"):
                supplier.mobile_no = relation_data["telefoon"]

            supplier.save()
            debug_info.append(f"Created new supplier: {supplier.name}")
            return supplier.name
        else:
            debug_info.append(
                "Failed to fetch relation {relation_id} from eBoekhouden, creating generic supplier"
            )
            # Create generic supplier if API fails
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = "eBoekhouden Supplier {relation_id}"
            supplier.eboekhouden_relation_id = str(relation_id)
            supplier.save()
            debug_info.append(f"Created generic supplier: {supplier.name}")
            return supplier.name

    except Exception as e:
        debug_info.append(f"Error creating supplier for relation {relation_id}: {str(e)}")
        return None


def _get_or_create_generic_customer(description, debug_info):
    """Create a generic customer based on description"""
    try:
        # Extract a meaningful name from description
        customer_name = description[:50] if description else "Generic Customer"
        if len(customer_name) < 5:
            customer_name = "Generic Customer"

        # Check if this generic customer already exists
        existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
        if existing:
            debug_info.append(f"Found existing generic customer: {existing}")
            return existing

        # Create new generic customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.save()
        debug_info.append(f"Created generic customer: {customer.name}")
        return customer.name

    except Exception as e:
        debug_info.append(f"Error creating generic customer: {str(e)}")
        return None


def _get_or_create_generic_supplier(description, debug_info):
    """Create a generic supplier based on description"""
    try:
        # Extract a meaningful name from description
        supplier_name = description[:50] if description else "Generic Supplier"
        if len(supplier_name) < 5:
            supplier_name = "Generic Supplier"

        # Check if this generic supplier already exists
        existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
        if existing:
            debug_info.append(f"Found existing generic supplier: {existing}")
            return existing

        # Create new generic supplier
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_type = "Individual"
        supplier.save()
        debug_info.append(f"Created generic supplier: {supplier.name}")
        return supplier.name

    except Exception as e:
        debug_info.append(f"Error creating generic supplier: {str(e)}")
        return None


def _get_or_create_company_as_customer(company, debug_info):
    """Get or create the company as a customer for internal transactions"""
    try:
        # Use the company name as customer name
        customer_name = "{company} (Internal)"

        # Check if this customer already exists
        existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
        if existing:
            debug_info.append(f"Found existing company customer: {existing}")
            return existing

        # Create company as customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Company"
        customer.save()
        debug_info.append(f"Created company customer: {customer.name}")
        return customer.name

    except Exception as e:
        debug_info.append(f"Error creating company customer: {str(e)}")
        return None


def _get_or_create_company_as_supplier(company, debug_info):
    """Get or create the company as a supplier for internal transactions"""
    try:
        # Use the company name as supplier name
        supplier_name = "{company} (Internal)"

        # Check if this supplier already exists
        existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
        if existing:
            debug_info.append(f"Found existing company supplier: {existing}")
            return existing

        # Create company as supplier
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_type = "Company"
        supplier.save()
        debug_info.append(f"Created company supplier: {supplier.name}")
        return supplier.name

    except Exception as e:
        debug_info.append(f"Error creating company supplier: {str(e)}")
        return None


@frappe.whitelist()
def get_mutation_gap_report():
    """Generate a report of missing mutations in the sequence"""
    try:
        # Get all imported mutation IDs
        journal_mutations = frappe.db.sql(
            """
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabJournal Entry`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            ORDER BY mutation_id
        """,
            as_dict=True,
        )

        payment_mutations = frappe.db.sql(
            """
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabPayment Entry`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            ORDER BY mutation_id
        """,
            as_dict=True,
        )

        invoice_mutations = frappe.db.sql(
            """
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabSales Invoice`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            UNION
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabPurchase Invoice`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            ORDER BY mutation_id
        """,
            as_dict=True,
        )

        # Combine all mutation IDs
        all_imported = set()
        for mutations_list in [journal_mutations, payment_mutations, invoice_mutations]:
            for mut in mutations_list:
                all_imported.add(mut["mutation_id"])

        if not all_imported:
            return {"success": True, "gaps": [], "message": "No mutations found"}

        # Find gaps in the sequence
        min_id = min(all_imported)
        max_id = max(all_imported)
        gaps = []

        for i in range(min_id, max_id + 1):
            if i not in all_imported:
                gaps.append(i)

        return {
            "success": True,
            "gaps": gaps,
            "total_imported": len(all_imported),
            "min_mutation": min_id,
            "max_mutation": max_id,
            "total_gaps": len(gaps),
            "coverage_percentage": round(
                ((max_id - min_id + 1 - len(gaps)) / (max_id - min_id + 1)) * 100, 2
            ),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _import_opening_balances(company, cost_center, debug_info):
    """Import opening balances from eBoekhouden using REST API"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Get opening balances from eBoekhouden
        result = api.make_request("v1/mutation", {"type": 0})

        if not result or not result.get("success") or result.get("status_code") != 200:
            return {
                "success": False,
                "error": "Failed to fetch opening balances: {result.get('error', 'Unknown error')}",
            }

        mutations_data = json.loads(result.get("data", "[]"))
        debug_info.append(f"Found {len(mutations_data)} opening balance mutations")

        if not mutations_data:
            return {"success": True, "message": "No opening balances found", "journal_entry": None}

        # Create a single journal entry for all opening balances
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = "2018-01-01"  # Opening balance date
        je.voucher_type = "Opening Entry"
        je.title = "eBoekhouden Opening Balances"
        je.user_remark = "Opening balances imported from eBoekhouden"

        total_debit = 0
        total_credit = 0
        processed_accounts = set()

        for mutation in mutations_data:
            mutation_id = mutation.get("id")
            ledger_id = mutation.get("ledgerId")
            amount = frappe.utils.flt(mutation.get("amount", 0), 2)
            # description = mutation.get("description", "Opening Balance")

            debug_info.append(
                f"Processing opening balance: ID={mutation_id}, Ledger={ledger_id}, Amount={amount}"
            )

            if amount == 0:
                debug_info.append(f"Skipping zero amount opening balance for ledger {ledger_id}")
                continue

            # Get account mapping
            account = None
            if ledger_id:
                mapping_result = frappe.db.sql(
                    """SELECT erpnext_account
                       FROM `tabE-Boekhouden Ledger Mapping`
                       WHERE ledger_id = %s
                       LIMIT 1""",
                    ledger_id,
                )

                if mapping_result:
                    account = mapping_result[0][0]

            if not account:
                debug_info.append(f"No mapping found for ledger {ledger_id}, skipping")
                continue

            # Skip if we've already processed this account (avoid duplicates)
            if account in processed_accounts:
                debug_info.append(f"Account {account} already processed, skipping duplicate")
                continue

            processed_accounts.add(account)

            # Check account type to determine if it's allowed in opening entries
            account_doc = frappe.get_doc("Account", account)
            root_type = account_doc.root_type

            # Skip P&L accounts (Income and Expense) - only Balance Sheet accounts are allowed
            if root_type in ["Income", "Expense"]:
                debug_info.append(f"Skipping P&L account {account} (type: {root_type})")
                continue

            # Determine if this account needs a party
            party_type = None
            party = None
            if account_doc.account_type == "Receivable":
                party_type = "Customer"
                party = _get_or_create_company_as_customer(company, debug_info)
            elif account_doc.account_type == "Payable":
                party_type = "Supplier"
                party = _get_or_create_company_as_supplier(company, debug_info)

            # Create journal entry line
            entry_line = {
                "account": account,
                "debit_in_account_currency": frappe.utils.flt(amount if amount > 0 else 0, 2),
                "credit_in_account_currency": frappe.utils.flt(-amount if amount < 0 else 0, 2),
                "cost_center": cost_center,
                "user_remark": "Opening balance: {description}",
            }

            # Add party if needed
            if party_type and party:
                entry_line["party_type"] = party_type
                entry_line["party"] = party

            je.append("accounts", entry_line)

            total_debit += entry_line["debit_in_account_currency"]
            total_credit += entry_line["credit_in_account_currency"]

            debug_info.append(
                "Added opening balance entry: {account}, Debit: {entry_line['debit_in_account_currency']}, Credit: {entry_line['credit_in_account_currency']}"
            )

        # Add balancing entry if needed
        balance_difference = total_debit - total_credit
        if abs(balance_difference) > 0.01:
            debug_info.append(f"Adding balancing entry for difference: {balance_difference}")

            # Use Temporary Opening account for balancing
            balancing_account = None

            # Try to find existing Temporary Opening account
            temp_opening_accounts = frappe.get_all(
                "Account",
                filters={"company": company, "account_name": ["like", "%Temporary Opening%"]},
                fields=["name", "is_group"],
            )

            for acc in temp_opening_accounts:
                if not acc.is_group:  # Must be a ledger account
                    balancing_account = acc.name
                    break

            # If no Temporary Opening account found, use Verrekeningen
            if not balancing_account:
                verrekeningen_accounts = frappe.get_all(
                    "Account",
                    filters={"company": company, "account_name": ["like", "%Verrekeningen%"], "is_group": 0},
                    fields=["name"],
                )

                if verrekeningen_accounts:
                    balancing_account = verrekeningen_accounts[0].name
                else:
                    # Create the Verrekeningen account if it doesn't exist
                    # Find or create the parent account
                    parent_account = frappe.db.get_value(
                        "Account", {"company": company, "root_type": "Equity", "is_group": 1}, "name"
                    )

                    if not parent_account:
                        debug_info.append("No Equity parent account found, using company default")
                        parent_account = company

                    balancing_acc = frappe.new_doc("Account")
                    balancing_acc.account_name = "Verrekeningen"
                    balancing_acc.parent_account = parent_account
                    balancing_acc.company = company
                    balancing_acc.account_type = "Equity"
                    balancing_acc.root_type = "Equity"
                    balancing_acc.account_number = "9999"
                    balancing_acc.save()
                    balancing_account = balancing_acc.name
                    debug_info.append(f"Created balancing account: {balancing_account}")

            # Add balancing entry
            balancing_line = {
                "account": balancing_account,
                "debit_in_account_currency": frappe.utils.flt(
                    -balance_difference if balance_difference < 0 else 0, 2
                ),
                "credit_in_account_currency": frappe.utils.flt(
                    balance_difference if balance_difference > 0 else 0, 2
                ),
                "cost_center": cost_center,
                "user_remark": "Automatic balancing entry for opening balances",
            }

            je.append("accounts", balancing_line)
            debug_info.append(f"Added balancing entry: {balancing_account}, difference: {balance_difference}")

        # Save and submit journal entry
        try:
            je.save()
            je.submit()
            debug_info.append(f"Successfully created opening balance journal entry: {je.name}")
            return {
                "success": True,
                "journal_entry": je.name,
                "message": "Opening balances imported successfully",
            }
        except Exception as e:
            debug_info.append(f"Failed to save opening balance journal entry: {str(e)}")
            return {"success": False, "error": "Failed to create journal entry: {str(e)}"}

    except Exception as e:
        debug_info.append(f"Error in _import_opening_balances: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def import_opening_balances_only(migration_name):
    """Import only opening balances via REST API"""
    try:
        # Get migration record
        frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Get cost center
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        if not cost_center:
            return {"success": False, "error": "No cost center found for company"}

        debug_info = []
        result = _import_opening_balances(company, cost_center, debug_info)

        return {"success": True, "result": result, "company": company, "cost_center": cost_center}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def _process_single_mutation(mutation, company, cost_center, debug_info):
    """Process a single mutation and return the created document"""
    try:
        mutation_id = mutation.get("id")
        mutation_type = mutation.get("type", 0)
        # mutation.get("description", "eBoekhouden Import {mutation_id}")
        amount = frappe.utils.flt(mutation.get("amount", 0), 2)
        # mutation.get("relationId")
        # mutation.get("invoiceNumber")
        # mutation.get("ledgerId")
        # mutation.get("rows", [])

        debug_info.append(f"Processing single mutation {mutation_id}: type={mutation_type}, amount={amount}")

        # Check if already imported
        existing_je = _check_if_already_imported(mutation_id, "Journal Entry")
        existing_pe = _check_if_already_imported(mutation_id, "Payment Entry")
        existing_si = _check_if_already_imported(mutation_id, "Sales Invoice")
        existing_pi = _check_if_already_imported(mutation_id, "Purchase Invoice")

        if existing_je or existing_pe or existing_si or existing_pi:
            existing_doc = existing_je or existing_pe or existing_si or existing_pi
            debug_info.append(f"Mutation {mutation_id} already imported as {existing_doc}")
            return frappe.get_doc(
                "Journal Entry"
                if existing_je
                else "Payment Entry"
                if existing_pe
                else "Sales Invoice"
                if existing_si
                else "Purchase Invoice",
                existing_doc,
            )

        # Handle different mutation types
        if mutation_type == 1:  # Sales Invoice
            return _create_sales_invoice(mutation, company, cost_center, debug_info)
        elif mutation_type == 2:  # Purchase Invoice
            return _create_purchase_invoice(mutation, company, cost_center, debug_info)
        elif mutation_type in [3, 4]:  # Payment types
            return _create_payment_entry(mutation, company, cost_center, debug_info)
        else:
            # Create Journal Entry for other types
            return _create_journal_entry(mutation, company, cost_center, debug_info)

    except Exception as e:
        debug_info.append(f"Error processing single mutation {mutation.get('id')}: {str(e)}")
        raise


def _create_sales_invoice(mutation, company, cost_center, debug_info):
    """Create Sales Invoice from mutation"""
    mutation_id = mutation.get("id")
    description = mutation.get("description", "eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    ledger_id = mutation.get("ledgerId")

    si = frappe.new_doc("Sales Invoice")
    si.company = company
    si.posting_date = mutation.get("date")
    si.customer = relation_id if relation_id else "Guest Customer"
    si.eboekhouden_mutation_nr = str(mutation_id)

    if invoice_number:
        si.name = invoice_number

    line_dict = create_invoice_line_for_tegenrekening(
        tegenrekening_code=ledger_id, amount=amount, description=description, transaction_type="sales"
    )

    si.append(
        "items",
        {
            "item_code": "Service Item",
            "description": line_dict["description"],
            "qty": line_dict["qty"],
            "rate": line_dict["rate"],
            "amount": line_dict["amount"],
            "income_account": line_dict["income_account"],
            "cost_center": cost_center,
        },
    )

    si.save()
    si.submit()
    debug_info.append(f"Created Sales Invoice {si.name}")
    return si


def _create_purchase_invoice(mutation, company, cost_center, debug_info):
    """Create Purchase Invoice from mutation"""
    mutation_id = mutation.get("id")
    description = mutation.get("description", "eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    ledger_id = mutation.get("ledgerId")

    pi = frappe.new_doc("Purchase Invoice")
    pi.company = company
    pi.posting_date = mutation.get("date")
    pi.supplier = relation_id if relation_id else "Default Supplier"
    pi.eboekhouden_mutation_nr = str(mutation_id)

    if invoice_number:
        pi.bill_no = invoice_number

    line_dict = create_invoice_line_for_tegenrekening(
        tegenrekening_code=ledger_id, amount=amount, description=description, transaction_type="purchase"
    )

    pi.append(
        "items",
        {
            "item_code": "Service Item",
            "description": line_dict["description"],
            "qty": line_dict["qty"],
            "rate": line_dict["rate"],
            "amount": line_dict["amount"],
            "expense_account": line_dict["expense_account"],
            "cost_center": cost_center,
        },
    )

    pi.save()
    pi.submit()
    debug_info.append(f"Created Purchase Invoice {pi.name}")
    return pi


def _create_payment_entry(mutation, company, cost_center, debug_info):
    """Create Payment Entry from mutation"""
    mutation_id = mutation.get("id")
    # mutation.get("description", "eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    mutation_type = mutation.get("type", 3)

    payment_type = "Receive" if mutation_type == 3 else "Pay"

    pe = frappe.new_doc("Payment Entry")
    pe.company = company
    pe.posting_date = mutation.get("date")
    pe.payment_type = payment_type
    pe.eboekhouden_mutation_nr = str(mutation_id)

    if payment_type == "Receive":
        pe.paid_to = "10000 - Kas - NVV"
        pe.received_amount = amount
        if relation_id:
            pe.party_type = "Customer"
            pe.party = relation_id
            pe.paid_from = frappe.db.get_value(
                "Account", {"account_type": "Receivable", "company": company}, "name"
            )
    else:
        pe.paid_from = "10000 - Kas - NVV"
        pe.paid_amount = amount
        if relation_id:
            pe.party_type = "Supplier"
            pe.party = relation_id
            pe.paid_to = frappe.db.get_value(
                "Account", {"account_type": "Payable", "company": company}, "name"
            )

    pe.reference_no = invoice_number if invoice_number else "EB-{mutation_id}"
    pe.reference_date = mutation.get("date")

    pe.save()
    pe.submit()
    debug_info.append(f"Created Payment Entry {pe.name}")
    return pe


def _create_journal_entry(mutation, company, cost_center, debug_info):
    """Create Journal Entry from mutation"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", "eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    ledger_id = mutation.get("ledgerId")
    rows = mutation.get("rows", [])

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Journal Entry"
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.eboekhouden_main_ledger_id = str(ledger_id) if ledger_id else ""
    je.user_remark = description

    # Set descriptive name and title
    if invoice_number:
        clean_invoice = str(invoice_number).replace("/", "-").replace("\\", "-").replace(" ", "-")
        je.name = f"EBH-{clean_invoice}"
        je.title = f"eBoekhouden {invoice_number}"
    else:
        type_names = {
            0: "Opening Balance",
            5: "Money Received",
            6: "Money Paid",
            7: "Memorial Booking",
            8: "Bank Import",
            9: "Manual Entry",
            10: "Stock Mutation",
        }
        type_name = type_names.get(mutation_type, "Type {mutation_type}")
        je.name = f"EBH-{type_name}-{mutation_id}"
        je.title = f"eBoekhouden {type_name} #{mutation_id}"

    if len(rows) > 0:
        # Multi-line journal entry
        total_debit = 0
        total_credit = 0
        is_memorial_booking = mutation_type == 7

        for row in rows:
            row_amount = frappe.utils.flt(row.get("amount", 0), 2)
            row_ledger_id = row.get("ledgerId")
            row_description = row.get("description", description)

            if row_amount == 0:
                continue

            # Get row account mapping
            row_account = None
            if row_ledger_id:
                mapping_result = frappe.db.sql(
                    """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                    row_ledger_id,
                )
                if mapping_result:
                    row_account = mapping_result[0][0]

            if not row_account:
                line_dict = create_invoice_line_for_tegenrekening(
                    tegenrekening_code=str(row_ledger_id) if row_ledger_id else None,
                    amount=abs(row_amount),
                    description=row_description,
                    transaction_type="purchase",
                )
                row_account = line_dict.get("expense_account") or "44009 - Onvoorziene kosten - NVV"

            # For memorial bookings, create paired entries
            if is_memorial_booking and ledger_id:
                main_mapping_result = frappe.db.sql(
                    """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                    ledger_id,
                )

                if main_mapping_result:
                    main_account = main_mapping_result[0][0]
                    abs_amount = abs(row_amount)

                    if row_amount > 0:
                        # Positive: Main provides, Row receives
                        main_debit, main_credit = abs_amount, 0
                        row_debit, row_credit = 0, abs_amount
                        debug_info.append(f"Memorial: €{abs_amount} FROM {main_account} TO {row_account}")
                    else:
                        # Negative: Row provides, Main receives
                        main_debit, main_credit = 0, abs_amount
                        row_debit, row_credit = abs_amount, 0
                        debug_info.append(f"Memorial: €{abs_amount} FROM {row_account} TO {main_account}")

                    # Add main ledger entry
                    main_line = {
                        "account": main_account,
                        "debit_in_account_currency": frappe.utils.flt(main_debit, 2),
                        "credit_in_account_currency": frappe.utils.flt(main_credit, 2),
                        "cost_center": cost_center,
                        "user_remark": "Memorial booking main ledger: {description}",
                    }

                    # Add party for main account if needed
                    main_account_type = frappe.db.get_value("Account", main_account, "account_type")
                    if main_account_type == "Receivable":
                        main_line["party_type"] = "Customer"
                        main_line["party"] = _get_or_create_company_as_customer(company, debug_info)
                    elif main_account_type == "Payable":
                        main_line["party_type"] = "Supplier"
                        main_line["party"] = _get_or_create_company_as_supplier(company, debug_info)

                    je.append("accounts", main_line)
                    total_debit += main_line["debit_in_account_currency"]
                    total_credit += main_line["credit_in_account_currency"]

                    # Add row ledger entry
                    entry_line = {
                        "account": row_account,
                        "debit_in_account_currency": frappe.utils.flt(row_debit, 2),
                        "credit_in_account_currency": frappe.utils.flt(row_credit, 2),
                        "cost_center": cost_center,
                        "user_remark": row_description,
                    }
                else:
                    frappe.throw(
                        "Memorial booking {mutation_id}: No mapping found for main ledger {ledger_id}"
                    )
            else:
                # Non-memorial booking
                entry_line = {
                    "account": row_account,
                    "debit_in_account_currency": frappe.utils.flt(row_amount if row_amount > 0 else 0, 2),
                    "credit_in_account_currency": frappe.utils.flt(-row_amount if row_amount < 0 else 0, 2),
                    "cost_center": cost_center,
                    "user_remark": row_description,
                }

            # Add row account party if needed
            row_account_type = frappe.db.get_value("Account", row_account, "account_type")
            if row_account_type == "Receivable":
                entry_line["party_type"] = "Customer"
                if mutation_type == 7:
                    entry_line["party"] = _get_or_create_company_as_customer(company, debug_info)
                elif relation_id:
                    entry_line["party"] = _get_or_create_customer(relation_id, debug_info)
            elif row_account_type == "Payable":
                entry_line["party_type"] = "Supplier"
                if mutation_type == 7:
                    entry_line["party"] = _get_or_create_company_as_supplier(company, debug_info)
                elif relation_id:
                    entry_line["party"] = _get_or_create_supplier(relation_id, description, debug_info)

            je.append("accounts", entry_line)
            total_debit += entry_line["debit_in_account_currency"]
            total_credit += entry_line["credit_in_account_currency"]

    else:
        # Simple journal entry with main amount
        main_account = None
        if ledger_id:
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                ledger_id,
            )
            if mapping_result:
                main_account = mapping_result[0][0]

        if not main_account:
            line_dict = create_invoice_line_for_tegenrekening(
                tegenrekening_code=str(ledger_id) if ledger_id else None,
                amount=abs(amount),
                description=description,
                transaction_type="purchase",
            )
            main_account = line_dict.get("expense_account") or "44009 - Onvoorziene kosten - NVV"

        je.append(
            "accounts",
            {
                "account": main_account,
                "debit_in_account_currency": frappe.utils.flt(amount if amount > 0 else 0, 2),
                "credit_in_account_currency": frappe.utils.flt(-amount if amount < 0 else 0, 2),
                "cost_center": cost_center,
                "user_remark": description,
            },
        )

        # Add balancing entry
        balancing_account = "9999 - Verrekeningen - NVV"
        je.append(
            "accounts",
            {
                "account": balancing_account,
                "debit_in_account_currency": frappe.utils.flt(-amount if amount < 0 else 0, 2),
                "credit_in_account_currency": frappe.utils.flt(amount if amount > 0 else 0, 2),
                "cost_center": cost_center,
                "user_remark": "Balancing entry for {description}",
            },
        )

    je.save()
    je.submit()
    debug_info.append(f"Created Journal Entry {je.name}")
    return je

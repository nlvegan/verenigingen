"""
E-Boekhouden REST API Full Migration
Fetches ALL mutations by iterating through IDs and caches them
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.e_boekhouden.utils.eboekhouden_payment_naming import (
    enhance_journal_entry_fields,
    get_journal_entry_title,
)


def get_default_cost_center(company):
    """Get the most appropriate default cost center for the company"""
    # Try multiple approaches to find the best cost center

    # 1. Try to get company's default cost center from Company doctype
    company_doc = frappe.get_doc("Company", company)
    if hasattr(company_doc, "cost_center") and company_doc.cost_center:
        return company_doc.cost_center

    # 2. Try to find "Main" cost center (common default name)
    main_cost_center = frappe.db.get_value(
        "Cost Center", {"company": company, "cost_center_name": "Main", "is_group": 0}, "name"
    )
    if main_cost_center:
        return main_cost_center

    # 3. Try to find cost center with company name
    company_cost_center = frappe.db.get_value(
        "Cost Center", {"company": company, "cost_center_name": company, "is_group": 0}, "name"
    )
    if company_cost_center:
        return company_cost_center

    # 4. Get the first non-group cost center (excluding specific ones we want to avoid)
    exclude_patterns = ["magazine", "Magazine", "MAGAZINE"]

    all_cost_centers = frappe.get_all(
        "Cost Center",
        filters={"company": company, "is_group": 0},
        fields=["name", "cost_center_name"],
        order_by="creation",
    )

    for cc in all_cost_centers:
        # Skip cost centers with unwanted names
        if not any(pattern.lower() in cc.cost_center_name.lower() for pattern in exclude_patterns):
            return cc.name

    # 5. Last resort: get any non-group cost center
    fallback_cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

    return fallback_cost_center


def get_party_account(party, party_type, company):
    """
    Get the correct party account, preferring party-specific accounts over company defaults.
    NEVER uses random accounts like Vraagposten as fallback.
    """
    # Try to get party's default account first
    if party_type == "Customer":
        party_account = frappe.db.sql(
            """
            SELECT pa.account
            FROM `tabParty Account` pa
            WHERE pa.parent = %s AND pa.parenttype = 'Customer'
            AND pa.company = %s
            LIMIT 1
        """,
            (party, company),
        )
        if party_account:
            return party_account[0][0]
    else:
        party_account = frappe.db.sql(
            """
            SELECT pa.account
            FROM `tabParty Account` pa
            WHERE pa.parent = %s AND pa.parenttype = 'Supplier'
            AND pa.company = %s
            LIMIT 1
        """,
            (party, company),
        )
        if party_account:
            return party_account[0][0]

    # PRIORITY 2: Get company's default receivable/payable account from Company settings
    account_type = "Receivable" if party_type == "Customer" else "Payable"

    # Try to get default from Company doctype first
    if party_type == "Customer":
        company_default = frappe.db.get_value("Company", company, "default_receivable_account")
        if company_default:
            return company_default
    else:
        company_default = frappe.db.get_value("Company", company, "default_payable_account")
        if company_default:
            return company_default

    # PRIORITY 3: Look for DEFAULT account of the correct type
    # Use account that has 'default' in name or is most generic
    default_account = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE account_type = %s
        AND company = %s
        AND is_group = 0
        ORDER BY
            CASE
                WHEN account_name LIKE '%%Default%%' OR account_name LIKE '%%General%%' THEN 1
                WHEN account_name LIKE '%%Algemeen%%' THEN 2
                WHEN account_name NOT LIKE '%%Vraagposten%%' AND account_name NOT LIKE '%%Specific%%' THEN 3
                ELSE 4
            END,
            account_name
        LIMIT 1
    """,
        (account_type, company),
        as_dict=True,
    )

    if default_account:
        return default_account[0].name

    # PRIORITY 4: If still no account found, get ANY account but avoid known specific accounts
    any_account = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE account_type = %s
        AND company = %s
        AND is_group = 0
        AND account_name NOT LIKE '%%Vraagposten%%'
        AND account_name NOT LIKE '%%Specific%%'
        ORDER BY account_name
        LIMIT 1
    """,
        (account_type, company),
        as_dict=True,
    )

    if any_account:
        return any_account[0].name

    # ABSOLUTE LAST RESORT: Return any account of the correct type (this should never happen)
    fallback = frappe.db.get_value("Account", {"account_type": account_type, "company": company}, "name")
    if fallback:
        frappe.logger().warning(
            f"Using fallback account {fallback} for {party_type} {party} - consider setting up proper defaults"
        )

    return fallback


# Removed unused get_appropriate_cash_account() and create_basic_cash_account() functions
# All payment processing now uses the mapping-aware _get_appropriate_payment_account()


def should_skip_mutation(mutation, debug_info=None):
    """Check if a mutation should be skipped (e.g., system notifications, zero-amount automations)"""
    if debug_info is None:
        debug_info = []

    mutation_id = mutation.get("id")
    amount = float(mutation.get("amount", 0) or 0)
    description = mutation.get("description", "").lower()
    mutation_type = mutation.get("type", 0)

    # Only skip automated system imports and notifications
    # Allow all zero-amount invoices to be imported (they're valid in ERPNext)
    if mutation_type in [1, 2]:  # Sales Invoice or Purchase Invoice
        # Only skip automated system imports that are clearly not real invoices
        # Note: WooCommerce invoices are legitimate customer transactions and should be imported
        system_patterns = [
            "system notification",
            "status update",
        ]

        for pattern in system_patterns:
            if pattern in description:
                debug_info.append(f"Skipping mutation {mutation_id}: Automated system import ({pattern})")
                return True

    # Log zero-amount transactions for monitoring
    if amount == 0:
        debug_info.append(
            f"Processing zero-amount transaction (mutation {mutation_id}, type {mutation_type}): {description[:100]}"
        )

    return False


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
    return existing


def _check_if_invoice_number_exists(invoice_number, doctype):
    """Check if an invoice number already exists in the specified doctype"""
    if not invoice_number:
        return None

    existing = frappe.db.get_value(doctype, {"eboekhouden_invoice_number": str(invoice_number)}, "name")
    return existing


# Removed: _check_if_invoice_number_exists_for_party - E-Boekhouden handles duplicate detection


def create_invoice_line_for_tegenrekening(
    tegenrekening_code=None, amount=0, description="", transaction_type="purchase"
):
    """
    Enhanced invoice line creation with smart tegenrekening account mapping
    """
    # Use the smart tegenrekening mapper which now raises errors instead of using fallbacks
    from verenigingen.utils.smart_tegenrekening_mapper import (
        create_invoice_line_for_tegenrekening as smart_create_line,
    )

    # Delegate to the smart mapper
    return smart_create_line(tegenrekening_code, amount, description, transaction_type)


def _cache_all_mutations(settings):
    """Cache all mutations from eBoekhouden REST API by iterating through IDs"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

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
                result = api.make_request(f"v1/mutation/{mutation_id}")

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


def _import_rest_mutations_batch(migration_name, mutations, settings, opening_balances_imported=False):
    """Import a batch of REST API mutations with smart tegenrekening mapping"""
    imported = 0
    skipped = 0
    errors = []
    debug_info = []

    debug_info.append(f"Starting import with {len(mutations) if mutations else 0} mutations")

    if not mutations:
        debug_info.append("No mutations provided, returning early")
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info), "REST Batch Debug")
        return {"imported": 0, "failed": 0, "skipped": 0, "errors": []}

    # # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)  # Not needed for batch processing
    company = settings.default_company
    debug_info.append(f"Company: {company}")

    # Get cost center
    cost_center = get_default_cost_center(company)

    debug_info.append(f"Cost center found: {cost_center}")

    if not cost_center:
        errors.append("No cost center found")
        debug_info.append("ERROR - No cost center found")
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info), "REST Batch Debug")
        return {"imported": 0, "failed": len(mutations), "skipped": 0, "errors": errors}

    for i, mutation in enumerate(mutations):
        try:
            # Skip if already imported
            mutation_id = mutation.get("id")
            mutation_type = mutation.get("type", 0)

            if not mutation_id:
                errors.append("Mutation missing ID, skipping")
                debug_info.append("ERROR - Mutation missing ID")
                failed += 1
                continue

            # Check for existing documents
            existing_je = _check_if_already_imported(mutation_id, "Journal Entry")
            existing_pe = _check_if_already_imported(mutation_id, "Payment Entry")
            existing_si = _check_if_already_imported(mutation_id, "Sales Invoice")
            existing_pi = _check_if_already_imported(mutation_id, "Purchase Invoice")

            if existing_je or existing_pe or existing_si or existing_pi:
                skipped += 1
                continue

            # Check if this mutation should be skipped (e.g., zero-amount system notifications)
            if should_skip_mutation(mutation, debug_info):
                skipped += 1
                continue

            mutation_type = mutation.get("type", 0)
            amount = frappe.utils.flt(mutation.get("amount", 0), 2)
            ledger_id = mutation.get("ledgerId")
            rows = mutation.get("rows", [])

            debug_info.append(
                f"Processing mutation {mutation_id}: type={mutation_type}, amount={amount}, ledger={ledger_id}, rows={len(rows)}"
            )

            # Skip if no amount and no rows (empty transaction)
            if amount == 0 and len(rows) == 0:
                debug_info.append(f"Skipping empty mutation {mutation_id}")
                skipped += 1
                continue

            # Process using enhanced single mutation processor
            try:
                doc = _process_single_mutation(mutation, company, cost_center, debug_info)
                if doc:
                    imported += 1
                    debug_info.append(
                        f"Successfully processed mutation {mutation_id} as {doc.doctype} {doc.name}"
                    )
                elif doc is None:
                    # None means it was skipped (duplicate), not failed
                    debug_info.append(f"Skipped mutation {mutation_id} - duplicate detected")
                else:
                    debug_info.append(f"Failed to process mutation {mutation_id} - no document returned")
            except Exception as e:
                error_msg = f"Error processing mutation {mutation_id}: {str(e)}"
                errors.append(error_msg)
                debug_info.append(f"ERROR - {error_msg}")
                failed += 1
                continue

        except Exception as e:
            error_msg = f"Error processing mutation {mutation.get('id', 'UNKNOWN')}: {str(e)}"
            errors.append(error_msg)
            debug_info.append(f"ERROR - {error_msg}")
    # Log debug info for troubleshooting
    if debug_info:
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info[-100:]), "REST Batch Debug")  # Last 100 lines

    return {
        "imported": imported,
        "failed": len(mutations) - imported - skipped,
        "skipped": skipped,
        "errors": errors,
    }


# Removed _process_money_transfer_with_mapping - types 5 & 6 now handled directly by _create_journal_entry


def _resolve_account_mapping(ledger_id, debug_info):
    """Resolve account mapping from eBoekhouden ledger ID"""
    if not ledger_id:
        return None

    mapping_result = frappe.db.sql(
        """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping`
           WHERE ledger_id = %s LIMIT 1""",
        ledger_id,
    )

    if mapping_result:
        return {
            "erpnext_account": mapping_result[0][0],
            "ledger_id": ledger_id,
        }

    debug_info.append(f"No mapping found for ledger ID {ledger_id}")
    return None


def _resolve_money_source_account(mutation, company, debug_info):
    """Resolve source account for money received (Type 5)"""
    # For money received, we need to determine where the money came from
    # This could be from various sources like cash, other banks, income, etc.

    # Check if there's a relation (customer/supplier) that suggests the source
    relation_id = mutation.get("relationId")
    if relation_id:
        # Money from a customer or external party - use appropriate receivable/income account
        return _get_appropriate_income_account(company, debug_info)

    # No relation - likely internal transfer from cash or other bank account
    return _get_appropriate_payment_account(company, debug_info)


def _resolve_money_destination_account(mutation, company, debug_info):
    """Resolve destination account for money paid (Type 6)"""
    # For money paid, we need to determine where the money went
    # This could be to cash, other banks, expenses, etc.

    # Check if there's a relation (supplier) that suggests the destination
    relation_id = mutation.get("relationId")
    if relation_id:
        # Money to a supplier or external party - use appropriate payable/expense account
        return _get_appropriate_expense_account(company, debug_info)

    # No relation - likely internal transfer to cash or other bank account
    return _get_appropriate_payment_account(company, debug_info)


def _get_appropriate_income_account(company, debug_info):
    """Get appropriate income account from explicit payment mappings"""
    # Import here to avoid circular imports
    from .eboekhouden_payment_mapping import get_payment_account_mappings

    try:
        payment_mappings = get_payment_account_mappings(company)

        # Check for explicit income account mapping
        if "income_account" in payment_mappings:
            account_name = payment_mappings["income_account"]
            debug_info.append(f"Using configured income account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Income"}

        # Check for sales income mapping as fallback
        if "sales_income_account" in payment_mappings:
            account_name = payment_mappings["sales_income_account"]
            debug_info.append(f"Using sales income account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Income"}

    except Exception as e:
        debug_info.append(f"Error accessing payment mappings: {str(e)}")

    frappe.throw(
        f"Income account must be explicitly configured in payment mappings for company {company}. "
        "Implicit account lookup by type has been disabled for data safety."
    )


def _get_appropriate_expense_account(company, debug_info):
    """Get appropriate expense account from explicit payment mappings"""
    # Import here to avoid circular imports
    from .eboekhouden_payment_mapping import get_payment_account_mappings

    try:
        payment_mappings = get_payment_account_mappings(company)

        # Check for explicit expense account mapping
        if "expense_account" in payment_mappings:
            account_name = payment_mappings["expense_account"]
            debug_info.append(f"Using configured expense account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Expense"}

        # Check for general expense mapping as fallback
        if "general_expense_account" in payment_mappings:
            account_name = payment_mappings["general_expense_account"]
            debug_info.append(f"Using general expense account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Expense"}

    except Exception as e:
        debug_info.append(f"Error accessing payment mappings: {str(e)}")

    frappe.throw(
        f"Expense account must be explicitly configured in payment mappings for company {company}. "
        "Implicit account lookup by type has been disabled for data safety."
    )


def _get_appropriate_payment_account(company, debug_info):
    """Get appropriate payment account (cash or bank) from explicit payment mappings"""
    # Import here to avoid circular imports
    from .eboekhouden_payment_mapping import get_payment_account_mappings

    try:
        payment_mappings = get_payment_account_mappings(company)

        # Check for explicit cash account mapping
        if "cash_account" in payment_mappings:
            account_name = payment_mappings["cash_account"]
            debug_info.append(f"Using configured cash account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Cash"}

        # Check for bank account mapping as fallback
        if "bank_account" in payment_mappings:
            account_name = payment_mappings["bank_account"]
            debug_info.append(f"Using bank account as cash fallback: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Bank"}

    except Exception as e:
        debug_info.append(f"Error accessing payment mappings: {str(e)}")

    frappe.throw(
        f"Cash/Bank account must be explicitly configured in payment mappings for company {company}. "
        "Implicit account lookup by type has been disabled for data safety."
    )


def _process_money_transfer_mutation(
    mutation, company, cost_center, from_account_mapping, to_account_mapping, debug_info
):
    """Process a money transfer mutation (type 5 or 6) with enhanced party extraction"""
    mutation_id = mutation.get("id")
    description = mutation.get("description", f"Money Transfer {mutation_id}")

    # Always calculate amount from rows (rows are source of truth)
    top_level_amount = abs(frappe.utils.flt(mutation.get("amount", 0), 2))

    if mutation.get("rows"):
        row_amounts = [abs(frappe.utils.flt(row.get("amount", 0), 2)) for row in mutation.get("rows", [])]
        amount = sum(row_amounts)
        debug_info.append(
            f"Money transfer calculated amount {amount} from {len(mutation.get('rows', []))} rows"
        )

        # Validate top-level amount matches rows (if non-zero)
        if top_level_amount > 0 and abs(top_level_amount - amount) > 0.01:
            debug_info.append(
                f"WARNING: Money transfer top-level amount ({top_level_amount}) doesn't match row total ({amount})"
            )
    else:
        # Fallback to top-level amount only if no rows exist
        amount = top_level_amount
        debug_info.append(f"Money transfer no rows found, using top-level amount: {amount}")

    mutation_type = mutation.get("type", 5)
    debug_info.append(f"Processing money transfer: ID={mutation_id}, Type={mutation_type}, Amount={amount}")

    # Extract party information from mutation description
    try:
        from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

        party_extractor = EBoekhoudenPartyExtractor(company)
        party_info = party_extractor.extract_party_from_mutation(mutation)

        if party_info:
            debug_info.append(
                f"Extracted party: {party_info['party_name']} ({party_info['party_type']}) via {party_info['extraction_method']}"
            )
        else:
            debug_info.append("No party information extracted from mutation")

    except Exception as e:
        debug_info.append(f"Party extraction failed: {str(e)}")
        party_info = None
        party_extractor = None

    # Create Journal Entry for money transfer
    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Bank Entry"  # More appropriate for money transfers
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.user_remark = description

    # Set descriptive name and title using enhanced naming functions
    type_name = "Money Received" if mutation_type == 5 else "Money Paid"
    je.name = f"EBH-{type_name}-{mutation_id}"
    je.title = get_journal_entry_title(mutation, mutation_type)

    # Enhance journal entry fields for better identification
    je = enhance_journal_entry_fields(je, mutation, type_name)

    from_account = from_account_mapping["erpnext_account"]
    to_account = to_account_mapping["erpnext_account"]

    debug_info.append(f"Transfer: {amount} from {from_account} to {to_account}")

    # From account (credit - money going out) with party assignment
    from_entry = {
        "account": from_account,
        "credit_in_account_currency": amount,
        "cost_center": cost_center,
        "user_remark": f"{description} - From",
    }

    # Try to assign party to from_account if appropriate
    if party_extractor and party_info:
        party_assignment = party_extractor.resolve_party_for_journal_entry(party_info, from_account)
        if party_assignment:
            from_entry["party_type"] = party_assignment[0]
            from_entry["party"] = party_assignment[1]
            debug_info.append(
                f"Assigned {party_assignment[0]} '{party_assignment[1]}' to from_account {from_account}"
            )

    je.append("accounts", from_entry)

    # To account (debit - money coming in) with party assignment
    to_entry = {
        "account": to_account,
        "debit_in_account_currency": amount,
        "cost_center": cost_center,
        "user_remark": f"{description} - To",
    }

    # Try to assign party to to_account if appropriate
    if party_extractor and party_info:
        party_assignment = party_extractor.resolve_party_for_journal_entry(party_info, to_account)
        if party_assignment:
            to_entry["party_type"] = party_assignment[0]
            to_entry["party"] = party_assignment[1]
            debug_info.append(
                f"Assigned {party_assignment[0]} '{party_assignment[1]}' to to_account {to_account}"
            )

    je.append("accounts", to_entry)

    try:
        je.save()
        je.submit()
        debug_info.append(f"Successfully created money transfer Journal Entry {je.name}")
        return je
    except Exception as e:
        debug_info.append(f"Failed to create money transfer Journal Entry: {str(e)}")
        raise


def _get_or_create_customer(relation_id, debug_info):
    """Get or create customer from eBoekhouden relation ID using party resolver"""
    try:
        # Use the robust party resolver instead of custom logic
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        customer_name = resolver.resolve_customer(relation_id, debug_info)

        if customer_name:
            debug_info.append(f"Party resolver returned customer: {customer_name}")
            return customer_name
        else:
            debug_info.append(f"Party resolver failed for relation {relation_id}")
            return None

    except Exception as e:
        debug_info.append(f"Error resolving customer for relation {relation_id}: {str(e)}")
        return None


def _get_or_create_supplier(relation_id, description, debug_info):
    """Get or create supplier from eBoekhouden relation ID using party resolver"""
    try:
        # Use the robust party resolver instead of custom logic
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        supplier_name = resolver.resolve_supplier(relation_id, debug_info)

        if supplier_name:
            debug_info.append(f"Party resolver returned supplier: {supplier_name}")
            return supplier_name
        else:
            debug_info.append(f"Party resolver failed for relation {relation_id}")
            return None

    except Exception as e:
        debug_info.append(f"Error resolving supplier for relation {relation_id}: {str(e)}")
        return None

    except Exception as e:
        debug_info.append(f"Error creating supplier for relation {relation_id}: {str(e)}")
        return None


def _get_or_create_generic_customer(description, debug_info):
    """Create customer with improved description-based naming"""
    try:
        from .eboekhouden_payment_naming import get_meaningful_description

        # Clean and improve the description
        clean_description = get_meaningful_description(description) if description else ""

        # Create meaningful customer name
        if clean_description and len(clean_description) >= 5:
            # Use cleaned description but make it clear it's imported
            customer_name = f"{clean_description[:40]} (eBoekhouden Import)"
        else:
            customer_name = "eBoekhouden Import Customer"

        # Check if this customer already exists
        existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
        if existing:
            debug_info.append(f"Found existing import customer: {existing}")
            return existing

        # Create new customer with better defaults
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"

        # Mark as import customer for later review
        customer.custom_import_source = "eBoekhouden"
        customer.custom_needs_review = 1

        customer.save()
        debug_info.append(f"Created improved import customer: {customer.name} ({customer_name})")
        return customer.name

    except Exception as e:
        debug_info.append(f"Error creating import customer: {str(e)}")
        # Last resort fallback
        return "Default Customer"


def _get_or_create_generic_supplier(description, debug_info):
    """Create supplier with improved description-based naming"""
    try:
        from .eboekhouden_payment_naming import get_meaningful_description

        # Clean and improve the description
        clean_description = get_meaningful_description(description) if description else ""

        # Create meaningful supplier name
        if clean_description and len(clean_description) >= 5:
            # Use cleaned description but make it clear it's imported
            supplier_name = f"{clean_description[:40]} (eBoekhouden Import)"
        else:
            supplier_name = "eBoekhouden Import Supplier"

        # Check if this supplier already exists
        existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
        if existing:
            debug_info.append(f"Found existing import supplier: {existing}")
            return existing

        # Create new supplier with better defaults
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_type = "Individual"
        supplier.supplier_group = "All Supplier Groups"

        # Mark as import supplier for later review
        supplier.custom_import_source = "eBoekhouden"
        supplier.custom_needs_review = 1

        supplier.save()
        debug_info.append(f"Created improved import supplier: {supplier.name} ({supplier_name})")
        return supplier.name

    except Exception as e:
        debug_info.append(f"Error creating import supplier: {str(e)}")
        # Last resort fallback
        return "Default Supplier"


def _get_or_create_company_as_customer(company, debug_info):
    """Get or create the company as a customer for internal transactions"""
    try:
        # Use the company name as customer name
        customer_name = f"{company} (Internal)"

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
        supplier_name = f"{company} (Internal)"

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
def analyze_import_failures():
    """Analyze recent import failures and categorize them"""
    try:
        # Get recent error logs
        errors = frappe.db.sql(
            """
            SELECT error FROM `tabError Log`
            WHERE creation > '2025-08-05 06:00:00'
            AND error LIKE '%Books have been closed%'
            LIMIT 3
        """,
            as_dict=True,
        )

        results = {"closed_book_errors": len(errors), "sample_errors": []}

        for error in errors:
            # Extract mutation data from error
            error_text = error["error"]
            if '"date":' in error_text:
                import re

                date_match = re.search(r'"date": "([^"]+)"', error_text)
                id_match = re.search(r'"id": (\d+)', error_text)
                type_match = re.search(r'"type": (\d+)', error_text)

                results["sample_errors"].append(
                    {
                        "date": date_match.group(1) if date_match else "unknown",
                        "id": id_match.group(1) if id_match else "unknown",
                        "type": type_match.group(1) if type_match else "unknown",
                    }
                )

        return results

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def debug_single_mutation(mutation_id):
    """Debug a single mutation by ID - useful for investigating import failures"""
    try:
        # Get company and cost center
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.company
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        if not cost_center:
            return {"success": False, "error": "No cost center found"}

        # Fetch the mutation from cache or API
        mutation_cache = frappe.cache().get_value("eboekhouden_mutations")
        if not mutation_cache:
            return {"success": False, "error": "No mutations cached. Run a full import first."}

        # Find the specific mutation
        mutation = None
        for cached_mutation in mutation_cache:
            if cached_mutation.get("id") == int(mutation_id):
                mutation = cached_mutation
                break

        if not mutation:
            return {"success": False, "error": f"Mutation {mutation_id} not in cache"}

        # Process the single mutation
        debug_info = []
        try:
            result = _process_single_mutation(mutation, company, cost_center, debug_info)
            return {
                "success": True,
                "mutation": mutation,
                "result": result.name if result else None,
                "debug_info": debug_info,
            }
        except Exception as e:
            return {"success": False, "mutation": mutation, "error": str(e), "debug_info": debug_info}

    except Exception as e:
        return {"success": False, "error": str(e)}


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


def _import_opening_balances(company, cost_center, debug_info, dry_run=False):
    """Import opening balances from eBoekhouden using REST API"""
    try:
        # Check if opening balances have already been imported
        existing_opening_balance = frappe.db.exists(
            "Journal Entry",
            {
                "company": company,
                "eboekhouden_mutation_nr": "OPENING_BALANCE",
                "voucher_type": "Opening Entry",
            },
        )

        if existing_opening_balance:
            # Opening balances already imported
            return {
                "success": True,
                "message": "Opening balances already imported",
                "journal_entry": existing_opening_balance,
            }

        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Get opening balances from eBoekhouden
        result = api.make_request("v1/mutation", method="GET", params={"type": 0})

        if not result or not result.get("success") or result.get("status_code") != 200:
            return {
                "success": False,
                "error": f"Failed to fetch opening balances: {result.get('error', 'Unknown error')}",
            }

        mutations_data = json.loads(result.get("data", "[]"))

        # Debug: Check data structure
        debug_info.append(f"mutations_data type: {type(mutations_data)}")

        # Handle if mutations_data is a dict instead of list
        if isinstance(mutations_data, dict):
            debug_info.append(f"mutations_data is dict with keys: {list(mutations_data.keys())[:5]}")
            # If it has 'items' key, use that (standard API response format)
            if "items" in mutations_data:
                mutations_data = mutations_data["items"]
            else:
                # Otherwise convert dict values to list
                mutations_data = list(mutations_data.values())

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
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"  # Mark as opening balance import

        total_debit = 0
        total_credit = 0
        processed_accounts = set()
        skipped_accounts = {"stock": [], "pnl": [], "errors": []}

        for mutation in mutations_data:
            # Handle if mutation is a list instead of dict (some APIs return arrays)
            if isinstance(mutation, list):
                debug_info.append(f"WARNING: Mutation is a list, not dict: {mutation}")
                continue

            mutation_id = mutation.get("id")
            ledger_id = mutation.get("ledgerId")
            amount = frappe.utils.flt(mutation.get("amount", 0), 2)
            description = mutation.get("description", "Opening Balance")

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
            try:
                account_doc = frappe.get_doc("Account", account)
                root_type = account_doc.root_type
                account_type = account_doc.account_type
            except frappe.DoesNotExistError:
                debug_info.append(f"Account {account} was not found, skipping")
                continue
            except Exception as e:
                debug_info.append(f"Error accessing account {account}: {str(e)}, skipping")
                continue

            # Skip P&L accounts (Income and Expense) - only Balance Sheet accounts are allowed
            if root_type in ["Income", "Expense"]:
                debug_info.append(f"Skipping P&L account {account} (type: {root_type})")
                if "skipped_accounts" in locals():
                    skipped_accounts["pnl"].append({"account": account, "type": root_type})
                continue

            # Handle Stock accounts via Stock Reconciliation instead of Journal Entry
            if account_type == "Stock":
                debug_info.append(f"Stock account {account} will be handled via Stock Reconciliation")
                if "skipped_accounts" in locals():
                    skipped_accounts["stock"].append({"account": account, "balance": amount})
                continue

            # Determine if this account needs a party
            party_type = None
            party = None
            if account_type == "Receivable":
                party_type = "Customer"
                party = _get_or_create_company_as_customer(company, debug_info)
            elif account_type == "Payable":
                party_type = "Supplier"
                party = _get_or_create_company_as_supplier(company, debug_info)

            # Create journal entry line with proper debit/credit based on account type
            # For balance sheet accounts, respect the natural balance:
            # - Asset accounts: positive balance = debit, negative balance = credit
            # - Liability/Equity accounts: positive balance = credit, negative balance = debit
            if root_type == "Asset":
                # Assets have natural debit balance
                debit_amount = frappe.utils.flt(amount if amount > 0 else 0, 2)
                credit_amount = frappe.utils.flt(-amount if amount < 0 else 0, 2)
            else:  # Liability or Equity
                # Liabilities and Equity have natural credit balance
                debit_amount = frappe.utils.flt(-amount if amount < 0 else 0, 2)
                credit_amount = frappe.utils.flt(amount if amount > 0 else 0, 2)

            entry_line = {
                "account": account,
                "debit_in_account_currency": debit_amount,
                "credit_in_account_currency": credit_amount,
                "cost_center": cost_center,
                "user_remark": f"Opening balance: {description}",
            }

            # Add party if needed
            if party_type and party:
                entry_line["party_type"] = party_type
                entry_line["party"] = party

            je.append("accounts", entry_line)

            total_debit += entry_line["debit_in_account_currency"]
            total_credit += entry_line["credit_in_account_currency"]

            debug_info.append(
                f"Added opening balance entry: {account}, Debit: {entry_line['debit_in_account_currency']}, Credit: {entry_line['credit_in_account_currency']}"
            )

        # Check if entries balance - add balancing entry if needed
        balance_difference = total_debit - total_credit
        if abs(balance_difference) > 0.01:
            debug_info.append(f"Balancing entry required: {balance_difference}")

            # Get or create temporary difference account
            temp_diff_account = _get_or_create_temporary_diff_account(company, debug_info)

            if balance_difference > 0:
                # Need credit to balance
                balancing_entry = {
                    "account": temp_diff_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": balance_difference,
                    "cost_center": cost_center,
                    "user_remark": "Balancing entry for opening balances",
                }
            else:
                # Need debit to balance
                balancing_entry = {
                    "account": temp_diff_account,
                    "debit_in_account_currency": abs(balance_difference),
                    "credit_in_account_currency": 0,
                    "cost_center": cost_center,
                    "user_remark": "Balancing entry for opening balances",
                }

            je.append("accounts", balancing_entry)
            debug_info.append(f"Added balancing entry: {temp_diff_account} = {balance_difference}")

            # Update totals
            total_debit += balancing_entry["debit_in_account_currency"]
            total_credit += balancing_entry["credit_in_account_currency"]

        # Save and submit journal entry (unless dry run)
        if dry_run:
            debug_info.append("DRY RUN: Would create opening balance journal entry")
            debug_info.append(f"Total debit: {total_debit}")
            debug_info.append(f"Total credit: {total_credit}")
            debug_info.append(f"Number of accounts: {len(je.accounts)}")
            return {
                "success": True,
                "journal_entry": "DRY-RUN-PREVIEW",
                "message": "Opening balances preview completed (no changes made)",
            }
        else:
            try:
                je.save()
                je.submit()
                debug_info.append(f"Successfully created opening balance journal entry: {je.name}")

                # Handle stock accounts via Stock Reconciliation
                stock_reconciliations = []
                if skipped_accounts["stock"]:
                    debug_info.append(
                        f"Creating Stock Reconciliations for {len(skipped_accounts['stock'])} stock accounts"
                    )

                    try:
                        from verenigingen.e_boekhouden.utils.stock_opening_balance_handler import (
                            create_stock_reconciliation_for_opening_balance,
                        )

                        stock_result = create_stock_reconciliation_for_opening_balance(
                            skipped_accounts["stock"], company, debug_info
                        )

                        if stock_result.get("success"):
                            stock_reconciliations = stock_result.get("created_reconciliations", [])
                            debug_info.append(
                                f"Created {len(stock_reconciliations)} Stock Reconciliation entries"
                            )
                        else:
                            debug_info.append(
                                f"Stock reconciliation failed: {stock_result.get('error', 'Unknown error')}"
                            )

                    except Exception as e:
                        debug_info.append(f"Error importing stock reconciliations: {str(e)}")

                # Add summary of what was processed
                total_skipped = len(skipped_accounts["pnl"]) + len(skipped_accounts["errors"])
                total_stock_processed = len(stock_reconciliations)

                if total_skipped > 0 or total_stock_processed > 0:
                    summary_parts = []
                    if total_stock_processed > 0:
                        summary_parts.append(
                            f"{total_stock_processed} stock accounts via Stock Reconciliation"
                        )
                    if len(skipped_accounts["pnl"]) > 0:
                        summary_parts.append(f"{len(skipped_accounts['pnl'])} P&L accounts skipped")
                    if len(skipped_accounts["errors"]) > 0:
                        summary_parts.append(f"{len(skipped_accounts['errors'])} error accounts skipped")

                    debug_info.append(f"Additional processing: {', '.join(summary_parts)}")

                return {
                    "success": True,
                    "journal_entry": je.name,
                    "stock_reconciliations": stock_reconciliations,
                    "message": "Opening balances imported successfully",
                    "skipped_accounts": skipped_accounts,
                    "accounts_processed": len(processed_accounts),
                }
            except Exception as e:
                debug_info.append(f"Failed to save opening balance journal entry: {str(e)}")
                return {"success": False, "error": f"Failed to create journal entry: {str(e)}"}

    except Exception as e:
        import traceback

        debug_info.append(f"Error in _import_opening_balances: {str(e)}")
        debug_info.append(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}


def _import_opening_balances_from_data(mutations_data, company, cost_center, debug_info, dry_run=False):
    """
    Import opening balances from provided data (used by stock account handler)
    This function processes pre-filtered mutation data for opening balances
    """
    try:
        # Check if opening balances have already been imported
        existing_opening_balance = frappe.db.exists(
            "Journal Entry",
            {
                "company": company,
                "eboekhouden_mutation_nr": "OPENING_BALANCE",
                "voucher_type": "Opening Entry",
            },
        )

        if existing_opening_balance:
            # Opening balances already imported
            return {
                "success": True,
                "message": "Opening balances already imported",
                "journal_entry": existing_opening_balance,
            }

        if not mutations_data:
            return {"success": True, "message": "No opening balances found", "journal_entry": None}

        # Create a single journal entry for all opening balances
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = "2018-01-01"  # Opening balance date
        je.voucher_type = "Opening Entry"
        je.title = "eBoekhouden Opening Balances (Stock Filtered)"
        je.user_remark = "Opening balances imported from eBoekhouden with stock account filtering"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"  # Mark as opening balance import

        total_debit = 0
        total_credit = 0
        processed_accounts = set()

        for mutation in mutations_data:
            # Handle if mutation is a list instead of dict (some APIs return arrays)
            if isinstance(mutation, list):
                debug_info.append(f"WARNING: Mutation is a list, not dict: {mutation}")
                continue

            mutation_id = mutation.get("id")
            ledger_id = mutation.get("ledgerId")
            amount = frappe.utils.flt(mutation.get("balance", 0), 2)  # Use balance for opening balances
            description = mutation.get("description", "Opening Balance")

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
            try:
                account_doc = frappe.get_doc("Account", account)
                root_type = account_doc.root_type
                account_type = account_doc.account_type
            except frappe.DoesNotExistError:
                debug_info.append(f"Account {account} was not found, skipping")
                continue
            except Exception as e:
                debug_info.append(f"Error accessing account {account}: {str(e)}, skipping")
                continue

            # Skip P&L accounts (Income and Expense) - only Balance Sheet accounts are allowed
            if root_type in ["Income", "Expense"]:
                debug_info.append(f"Skipping P&L account {account} (type: {root_type})")
                if "skipped_accounts" in locals():
                    skipped_accounts["pnl"].append({"account": account, "type": root_type})
                continue

            # Handle Stock accounts via Stock Reconciliation instead of Journal Entry
            if account_type == "Stock":
                debug_info.append(f"Stock account {account} will be handled via Stock Reconciliation")
                if "skipped_accounts" in locals():
                    skipped_accounts["stock"].append({"account": account, "balance": amount})
                continue

            # Determine if this account needs a party
            party_type = None
            party = None
            if account_type == "Receivable":
                party_type = "Customer"
                party = _get_or_create_company_as_customer(company, debug_info)
            elif account_type == "Payable":
                party_type = "Supplier"
                party = _get_or_create_company_as_supplier(company, debug_info)

            # Create journal entry line with proper debit/credit based on account type
            if root_type == "Asset":
                # Assets have natural debit balance
                debit_amount = frappe.utils.flt(amount if amount > 0 else 0, 2)
                credit_amount = frappe.utils.flt(-amount if amount < 0 else 0, 2)
            else:  # Liability or Equity
                # Liabilities and Equity have natural credit balance
                debit_amount = frappe.utils.flt(-amount if amount < 0 else 0, 2)
                credit_amount = frappe.utils.flt(amount if amount > 0 else 0, 2)

            entry_line = {
                "account": account,
                "debit_in_account_currency": debit_amount,
                "credit_in_account_currency": credit_amount,
                "cost_center": cost_center,
                "user_remark": description,
            }

            # Add party information if needed
            if party_type and party:
                entry_line["party_type"] = party_type
                entry_line["party"] = party

            je.append("accounts", entry_line)
            total_debit += debit_amount
            total_credit += credit_amount

            debug_info.append(
                f"Added opening balance line: {account} = Debit: {debit_amount}, Credit: {credit_amount}"
            )

        # Check if we have any entries to process
        if not je.accounts:
            debug_info.append("No valid opening balance entries found after filtering")
            return {
                "success": True,
                "message": "No valid opening balance entries found",
                "journal_entry": None,
            }

        # Add balancing entry if needed
        balance_diff = total_debit - total_credit
        if abs(balance_diff) > 0.01:  # Allow small rounding differences
            debug_info.append(f"Balancing entry required: {balance_diff}")

            # Get or create temporary difference account
            temp_diff_account = _get_or_create_temporary_diff_account(company, debug_info)

            if balance_diff > 0:
                # Need credit to balance
                balancing_entry = {
                    "account": temp_diff_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": balance_diff,
                    "cost_center": cost_center,
                    "user_remark": "Balancing entry for opening balances",
                }
            else:
                # Need debit to balance
                balancing_entry = {
                    "account": temp_diff_account,
                    "debit_in_account_currency": abs(balance_diff),
                    "credit_in_account_currency": 0,
                    "cost_center": cost_center,
                    "user_remark": "Balancing entry for opening balances",
                }

            je.append("accounts", balancing_entry)
            debug_info.append(f"Added balancing entry: {temp_diff_account} = {balance_diff}")

        if dry_run:
            debug_info.append("Dry run mode - not saving journal entry")
            return {
                "success": True,
                "message": "Opening balances validated (dry run)",
                "journal_entry": None,
                "accounts_processed": len(processed_accounts),
            }

        # Save and submit the journal entry
        try:
            je.save()
            je.submit()
            debug_info.append(f"Created and submitted Journal Entry {je.name}")
            return {
                "success": True,
                "journal_entry": je.name,
                "message": "Opening balances imported successfully",
                "accounts_processed": len(processed_accounts),
            }
        except Exception as e:
            debug_info.append(f"Failed to save opening balance journal entry: {str(e)}")
            return {"success": False, "error": f"Failed to create journal entry: {str(e)}"}

    except Exception as e:
        import traceback

        debug_info.append(f"Error in _import_opening_balances_from_data: {str(e)}")
        debug_info.append(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}


def _get_or_create_temporary_diff_account(company, debug_info):
    """Get or create a temporary difference account for balancing opening balances"""

    # PRIORITY 1: Look for existing temporary accounts instead of creating new ones
    # First check if there's already a "Temporary Differences" account for this company
    existing_temp_accounts = frappe.db.sql(
        """
        SELECT name, account_name
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Temporary'
        AND root_type = 'Equity'
        AND (account_name = 'Temporary Differences'
             OR account_name LIKE '%%Temporary%%Difference%%'
             OR account_name LIKE '%%Difference%%')
        ORDER BY
            CASE WHEN account_name = 'Temporary Differences' THEN 1 ELSE 2 END,
            name
        LIMIT 1
    """,
        company,
        as_dict=True,
    )

    if existing_temp_accounts:
        account_name = existing_temp_accounts[0].name
        debug_info.append(f"Using existing temporary account: {account_name}")
        return account_name

    # PRIORITY 2: Look for any temporary account under Equity
    any_equity_temp = frappe.db.sql(
        """
        SELECT name, account_name
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Temporary'
        AND root_type = 'Equity'
        ORDER BY name
        LIMIT 1
    """,
        company,
        as_dict=True,
    )

    if any_equity_temp:
        account_name = any_equity_temp[0].name
        debug_info.append(f"Using existing equity temporary account: {account_name}")
        return account_name

    # PRIORITY 3: Look for any temporary account (regardless of root type)
    any_temp = frappe.db.sql(
        """
        SELECT name, account_name, root_type
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Temporary'
        ORDER BY
            CASE WHEN root_type = 'Equity' THEN 1 ELSE 2 END,
            name
        LIMIT 1
    """,
        company,
        as_dict=True,
    )

    if any_temp:
        account_name = any_temp[0].name
        debug_info.append(f"Using existing temporary account (root: {any_temp[0].root_type}): {account_name}")
        return account_name

    # PRIORITY 4: Only try to create if no temporary accounts exist at all
    account_name = f"Temporary Differences - {company}"
    if frappe.db.exists("Account", account_name):
        return account_name

    # Create the account under Equity as last resort
    try:
        # Find equity parent account
        equity_accounts = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s
               AND root_type = 'Equity'
               AND is_group = 1
               LIMIT 1""",
            company,
        )

        if equity_accounts:
            parent_account = equity_accounts[0][0]
        else:
            parent_account = f"Capital Stock - {company}"

        account = frappe.new_doc("Account")
        account.account_name = "Temporary Differences"
        account.parent_account = parent_account
        account.company = company
        account.account_type = "Temporary"  # Use Temporary account type
        account.root_type = "Equity"
        account.is_group = 0
        account.insert()

        debug_info.append(f"Created temporary difference account: {account.name}")
        return account.name

    except Exception as e:
        debug_info.append(f"Failed to create temporary difference account: {str(e)}")

        # FINAL FALLBACK: Find any account that can be used for balancing
        # Look for any Equity account that's not a group
        fallback_equity = frappe.db.sql(
            """
            SELECT name FROM `tabAccount`
            WHERE company = %s
            AND root_type = 'Equity'
            AND is_group = 0
            ORDER BY
                CASE WHEN account_type = 'Temporary' THEN 1
                     WHEN account_name LIKE '%%Capital%%' THEN 2
                     WHEN account_name LIKE '%%Reserve%%' THEN 3
                     ELSE 4 END,
                name
            LIMIT 1
        """,
            company,
            as_dict=True,
        )

        if fallback_equity:
            fallback_account = fallback_equity[0].name
            debug_info.append(f"FALLBACK: Using equity account for balancing: {fallback_account}")
            return fallback_account

        # Absolute last resort - this should never happen in a properly configured system
        debug_info.append("ERROR: No suitable account found for opening balance balancing")
        raise Exception("No temporary or equity accounts available for opening balance balancing")


def _get_or_create_stock_temporary_account(company, debug_info):
    """Get or create a temporary account for stock balances during opening balance import"""
    account_name = f"Stock Opening Balance (Temporary) - {company}"

    if frappe.db.exists("Account", account_name):
        return account_name

    # Create the account under Assets
    try:
        # Find current assets parent account
        current_assets_accounts = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s
               AND root_type = 'Asset'
               AND is_group = 1
               AND account_name LIKE '%Current%'
               LIMIT 1""",
            company,
        )

        if current_assets_accounts:
            parent_account = current_assets_accounts[0][0]
        else:
            # Fallback to any Asset group
            asset_accounts = frappe.db.sql(
                """SELECT name FROM `tabAccount`
                   WHERE company = %s
                   AND root_type = 'Asset'
                   AND is_group = 1
                   LIMIT 1""",
                company,
            )
            parent_account = (
                asset_accounts[0][0] if asset_accounts else f"Application of Funds (Assets) - {company}"
            )

        account = frappe.new_doc("Account")
        account.account_name = "Stock Opening Balance (Temporary)"
        account.parent_account = parent_account
        account.company = company
        account.account_type = "Temporary"  # Use Temporary account type
        account.root_type = "Asset"
        account.is_group = 0
        account.insert()

        debug_info.append(f"Created temporary stock account: {account.name}")
        return account.name

    except Exception as e:
        debug_info.append(f"Failed to create temporary stock account: {str(e)}")
        # Fallback to general temporary account
        return _get_or_create_temporary_diff_account(company, debug_info)


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
        cost_center = get_default_cost_center(company)

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
            # Mutation already imported
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

        # CRITICAL: Fetch full mutation details for complete data
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        mutation_detail = iterator.fetch_mutation_detail(mutation_id)
        if not mutation_detail:
            debug_info.append(f"Could not fetch detailed data for mutation {mutation_id}, using summary data")
            mutation_detail = mutation  # Fallback to summary data
        else:
            # Count line items from both possible fields
            regels_count = len(mutation_detail.get("Regels", []))
            rows_count = len(mutation_detail.get("rows", []))
            total_items = regels_count or rows_count
            debug_info.append(
                f"Fetched detailed data for mutation {mutation_id} with {total_items} line items (Regels: {regels_count}, rows: {rows_count})"
            )

        # REMOVED: Duplicate detection - E-Boekhouden already enforces this perfectly

        # Handle different mutation types with detailed data
        if mutation_type == 1:  # Purchase Invoice (Invoice received)
            return _create_purchase_invoice(mutation_detail, company, cost_center, debug_info)
        elif mutation_type == 2:  # Sales Invoice (Invoice sent)
            return _create_sales_invoice(mutation_detail, company, cost_center, debug_info)
        elif mutation_type in [3, 4]:  # Customer/Supplier Payment types
            return _create_payment_entry(mutation_detail, company, cost_center, debug_info)
        elif mutation_type in [5, 6]:  # Money Received/Money Paid - better as Payment Entries
            return _create_money_transfer_payment_entry(mutation_detail, company, cost_center, debug_info)
        else:
            # Create Journal Entry for other types (0, 7, 8, 9, 10, etc.)
            return _create_journal_entry(mutation_detail, company, cost_center, debug_info)

    except Exception as e:
        debug_info.append(f"Error processing single mutation {mutation.get('id')}: {str(e)}")
        raise


def _create_sales_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Sales Invoice with ALL available fields from detailed mutation data"""
    from frappe.utils import add_days, now

    from .invoice_helpers import (
        add_tax_lines,
        create_single_line_fallback,
        get_or_create_payment_terms,
        process_line_items,
        resolve_customer,
    )

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    relation_id = mutation_detail.get("relationId")
    invoice_number = mutation_detail.get("invoiceNumber")

    debug_info.append(f"Creating Sales Invoice for mutation {mutation_id}")

    si = frappe.new_doc("Sales Invoice")

    # Basic fields
    si.company = company
    si.posting_date = mutation_detail.get("date")
    si.set_posting_time = 1

    # Customer - properly resolved
    customer = resolve_customer(relation_id, debug_info)
    si.customer = customer

    # Currency
    si.currency = "EUR"
    si.conversion_rate = 1.0

    # Payment terms and due date
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    if payment_days:
        try:
            payment_terms = get_or_create_payment_terms(payment_days)
            if payment_terms:
                si.payment_terms_template = payment_terms
                si.due_date = add_days(si.posting_date, payment_days)
            else:
                # Fallback: just set due date without payment terms template
                si.due_date = add_days(si.posting_date, payment_days)
        except Exception as e:
            debug_info.append(f"Warning: Failed to create payment terms for {payment_days} days: {str(e)}")
            # Fallback: just set due date without payment terms template
            si.due_date = add_days(si.posting_date, payment_days)

    # References
    if mutation_detail.get("Referentie"):
        si.po_no = mutation_detail.get("Referentie")

    # Description
    si.remarks = description

    # Check for credit notes and handle negative amounts (improved detection)
    is_credit_note, effective_total_amount = _detect_credit_note_improved(mutation_detail, debug_info)
    si.is_return = is_credit_note

    if is_credit_note:
        debug_info.append(
            f"Processing as credit note (effective amount: {effective_total_amount}), will convert amounts to positive"
        )

    # Set receivable account based on eBoekhouden ledgerID (proper SSoT approach)
    ledger_id = mutation_detail.get("ledgerId")
    if ledger_id:
        # Check if description contains WooCommerce or FactuurSturen - these should use "Te Ontvangen Bedragen"
        description_lower = description.lower()
        if "woocommerce" in description_lower or "factuursturen" in description_lower:
            debug_info.append(
                "Found WooCommerce/FactuurSturen in description, using Te Ontvangen Bedragen account"
            )
            # Look for "Te Ontvangen Bedragen" account specifically
            te_ontvangen_bedragen_account = frappe.db.get_value(
                "Account",
                {"account_name": ["like", "%Te Ontvangen Bedragen%"], "company": company, "is_group": 0},
                "name",
            )
            if te_ontvangen_bedragen_account:
                si.debit_to = te_ontvangen_bedragen_account
                debug_info.append(f"Set receivable account to: {te_ontvangen_bedragen_account}")
            else:
                debug_info.append(
                    "WARNING: Te Ontvangen Bedragen account not found, falling back to ledger mapping"
                )
                # Fallback to standard ledger mapping
                account_mapping = _resolve_account_mapping(ledger_id, debug_info)
                if account_mapping and account_mapping.get("erpnext_account"):
                    si.debit_to = account_mapping["erpnext_account"]
                    debug_info.append(
                        f"Set receivable account from ledger mapping: {account_mapping['erpnext_account']}"
                    )
        else:
            # Use standard ledger mapping for non-WooCommerce/FactuurSturen invoices
            account_mapping = _resolve_account_mapping(ledger_id, debug_info)
            if account_mapping and account_mapping.get("erpnext_account"):
                si.debit_to = account_mapping["erpnext_account"]
                debug_info.append(
                    f"Set receivable account from ledger mapping: {account_mapping['erpnext_account']}"
                )
            else:
                debug_info.append(f"WARNING: No account mapping found for ledger ID {ledger_id}")
    else:
        debug_info.append(
            "WARNING: No ledgerID found in mutation data, ERPNext will use default receivable account selection"
        )

    # Custom tracking fields
    si.eboekhouden_mutation_nr = str(mutation_id)
    if invoice_number:
        si.eboekhouden_invoice_number = invoice_number

    # CRITICAL: Process line items from Regels or rows
    regels = mutation_detail.get("Regels", []) or mutation_detail.get("rows", [])
    if regels:
        # For credit notes, we need to process amounts as positive values and quantities as negative
        if is_credit_note:
            regels = _convert_regels_for_sales_credit_note(regels, debug_info)

        success = process_line_items(si, regels, "sales", cost_center, debug_info)
        if success:
            add_tax_lines(si, regels, "sales", debug_info)
        else:
            # Fallback to single line
            create_single_line_fallback(si, mutation_detail, cost_center, debug_info)
    else:
        # No line items available, create fallback
        debug_info.append("No Regels found, creating single line fallback")
        # For credit notes, convert the mutation detail amount
        if is_credit_note:
            mutation_detail = _convert_mutation_detail_amount(mutation_detail, debug_info)
        create_single_line_fallback(si, mutation_detail, cost_center, debug_info)

    # Enhanced Sales Invoice naming to include invoice number for better identification
    _enhance_sales_invoice_title(si, invoice_number, description, debug_info)

    si.save()
    si.submit()
    debug_info.append(f"Created enhanced Sales Invoice {si.name} with {len(si.items)} line items")
    return si


def _enhance_sales_invoice_title(sales_invoice, invoice_number, description, debug_info):
    """
    Enhance Sales Invoice title to include invoice number for better identification

    Args:
        sales_invoice: The Sales Invoice document
        invoice_number: The eBoekhouden invoice number (factuurnummer)
        description: The transaction description
        debug_info: List to append debug messages to
    """
    if not invoice_number:
        debug_info.append("No invoice number available for title enhancement")
        return

    try:
        # Extract customer name for context
        customer_name = sales_invoice.customer_name or sales_invoice.customer

        # For all invoices, use clean format: Customer - Factuur Number
        invoice_num = str(invoice_number).replace("/", "-").replace("\\", "-")
        sales_invoice.title = f"{customer_name} - Factuur {invoice_num}"
        debug_info.append(f"Enhanced sales invoice title: {sales_invoice.title}")

    except Exception as e:
        debug_info.append(f"Warning: Failed to enhance sales invoice title: {str(e)}")


def _detect_credit_note_improved(mutation_detail, debug_info):
    """
    Improved credit note detection that checks both main amount and line item amounts.

    Returns tuple: (is_credit_note, effective_total_amount)
    """
    # First check main amount field
    main_amount = frappe.utils.flt(mutation_detail.get("amount", 0))

    # If main amount is negative, it's definitely a credit note
    if main_amount < 0:
        debug_info.append(f"Credit note detected from main amount: {main_amount}")
        return True, main_amount

    # If main amount is positive and non-zero, it's definitely not a credit note
    if main_amount > 0:
        debug_info.append(f"Not a credit note - main amount is positive: {main_amount}")
        return False, main_amount

    # Main amount is 0 or None - check line items
    regels = mutation_detail.get("Regels", []) or mutation_detail.get("rows", [])
    if not regels:
        debug_info.append("No line items to check for credit note detection")
        return False, main_amount

    # Calculate total from line items
    line_item_total = 0
    negative_items = 0
    positive_items = 0

    for regel in regels:
        # Handle both Dutch (SOAP) and English (REST) field names
        amount_field = "amount" if "amount" in regel else "Prijs"
        quantity_field = "quantity" if "quantity" in regel else "Aantal"

        item_amount = frappe.utils.flt(regel.get(amount_field, 0))
        item_quantity = frappe.utils.flt(regel.get(quantity_field, 1))

        # Calculate total amount for this line item
        total_item_amount = item_amount * item_quantity
        line_item_total += total_item_amount

        if total_item_amount < 0:
            negative_items += 1
        elif total_item_amount > 0:
            positive_items += 1

    debug_info.append(
        f"Line item analysis: total={line_item_total}, negative_items={negative_items}, positive_items={positive_items}"
    )

    # Determine if it's a credit note based on line item analysis
    if line_item_total < 0:
        debug_info.append(f"Credit note detected from line item total: {line_item_total}")
        return True, line_item_total
    elif negative_items > 0 and positive_items == 0:
        # All items are negative (even if total rounds to 0)
        debug_info.append(f"Credit note detected - all {negative_items} line items are negative")
        return True, line_item_total
    else:
        debug_info.append("Not a credit note based on line item analysis")
        return False, line_item_total


def _convert_negative_amounts_to_positive(regels, debug_info):
    """Convert negative amounts in line items to positive values for credit notes (Purchase Invoices)"""
    return _convert_regels_for_credit_note(regels, "purchase", debug_info)


def _convert_regels_for_sales_credit_note(regels, debug_info):
    """Convert line items for Sales Invoice credit notes - amounts positive, quantities negative"""
    return _convert_regels_for_credit_note(regels, "sales", debug_info)


def _convert_regels_for_credit_note(regels, invoice_type, debug_info):
    """
    Convert line items for credit notes with proper quantity/amount handling.

    For Sales Returns (Sales Invoices with is_return=True):
    - Amounts: Convert to positive (ERPNext handles the math)
    - Quantities: Keep negative (ERPNext requirement)

    For Purchase Returns (Purchase Invoices with is_return=True):
    - Amounts: Convert to positive
    - Quantities: Convert to positive
    """
    if not regels:
        return regels

    converted_regels = []
    for regel in regels:
        converted_regel = regel.copy()  # Create a copy to avoid modifying original

        # Handle both Dutch (SOAP) and English (REST) field names
        amount_field = "amount" if "amount" in regel else "Prijs"
        quantity_field = "quantity" if "quantity" in regel else "Aantal"

        # Convert amounts to positive (both sales and purchase)
        if amount_field in regel:
            original_amount = frappe.utils.flt(regel[amount_field])
            if original_amount < 0:
                converted_regel[amount_field] = abs(original_amount)
                debug_info.append(
                    f"Converted negative amount {original_amount} to positive {abs(original_amount)}"
                )

        # Handle quantities based on invoice type
        # For eBoekhouden data, quantity field might not exist, defaulting to 1
        if quantity_field in regel:
            original_quantity = frappe.utils.flt(regel[quantity_field])
        else:
            # Default quantity when field doesn't exist
            original_quantity = 1.0

        if original_quantity != 0:
            if invoice_type == "sales":
                # For Sales Returns, quantities must be negative
                if original_quantity > 0:
                    converted_regel[quantity_field] = -abs(original_quantity)
                    debug_info.append(
                        f"Sales credit note: converted positive quantity {original_quantity} to negative {-abs(original_quantity)}"
                    )
                else:
                    # Already negative, keep it
                    converted_regel[quantity_field] = original_quantity
                    debug_info.append(f"Sales credit note: kept negative quantity {original_quantity}")
            else:
                # For Purchase Returns, quantities should be positive
                if original_quantity < 0:
                    converted_regel[quantity_field] = abs(original_quantity)
                    debug_info.append(
                        f"Purchase credit note: converted negative quantity {original_quantity} to positive {abs(original_quantity)}"
                    )
                else:
                    # Set positive quantity
                    converted_regel[quantity_field] = abs(original_quantity)

        converted_regels.append(converted_regel)

    return converted_regels


def _convert_mutation_detail_amount(mutation_detail, debug_info):
    """Convert negative amount in mutation detail to positive for credit notes"""
    if not mutation_detail:
        return mutation_detail

    converted_detail = mutation_detail.copy()

    # Handle both Dutch (SOAP) and English (REST) field names
    amount_field = "amount" if "amount" in mutation_detail else "Bedrag"

    if amount_field in mutation_detail:
        original_amount = frappe.utils.flt(mutation_detail[amount_field])
        if original_amount < 0:
            converted_detail[amount_field] = abs(original_amount)
            debug_info.append(
                f"Converted mutation detail amount {original_amount} to positive {abs(original_amount)}"
            )

    return converted_detail


def _create_purchase_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Purchase Invoice with ALL available fields from detailed mutation data"""
    from frappe.utils import add_days, now

    from .invoice_helpers import (
        add_tax_lines,
        create_single_line_fallback,
        get_or_create_payment_terms,
        process_line_items,
        resolve_supplier,
    )

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    relation_id = mutation_detail.get("relationId")
    invoice_number = mutation_detail.get("invoiceNumber")

    debug_info.append(f"Creating Purchase Invoice for mutation {mutation_id}")

    pi = frappe.new_doc("Purchase Invoice")

    # Basic fields
    pi.company = company
    pi.posting_date = mutation_detail.get("date")
    pi.set_posting_time = 1

    # Supplier - properly resolved
    supplier = resolve_supplier(relation_id, debug_info)
    pi.supplier = supplier

    # Currency
    pi.currency = "EUR"
    pi.conversion_rate = 1.0

    # Payment terms and due date
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    if payment_days:
        try:
            payment_terms = get_or_create_payment_terms(payment_days)
            if payment_terms:
                pi.payment_terms_template = payment_terms
                pi.due_date = add_days(pi.posting_date, payment_days)
            else:
                # Fallback: just set due date without payment terms template
                pi.due_date = add_days(pi.posting_date, payment_days)
        except Exception as e:
            debug_info.append(f"Warning: Failed to create payment terms for {payment_days} days: {str(e)}")
            # Fallback: just set due date without payment terms template
            pi.due_date = add_days(pi.posting_date, payment_days)

    # Bill number and references
    if invoice_number:
        pi.bill_no = invoice_number
    if mutation_detail.get("Referentie"):
        pi.supplier_invoice_no = mutation_detail.get("Referentie")

    # Description
    pi.remarks = description

    # Check for credit notes and handle negative amounts (improved detection)
    is_credit_note, effective_total_amount = _detect_credit_note_improved(mutation_detail, debug_info)
    pi.is_return = is_credit_note

    if is_credit_note:
        debug_info.append(
            f"Processing as credit note (effective amount: {effective_total_amount}), will convert amounts to positive"
        )

    # Set payable account based on eBoekhouden ledgerID (proper SSoT approach)
    ledger_id = mutation_detail.get("ledgerId")
    if ledger_id:
        account_mapping = _resolve_account_mapping(ledger_id, debug_info)
        if account_mapping and account_mapping.get("erpnext_account"):
            pi.credit_to = account_mapping["erpnext_account"]
            debug_info.append(
                f"Set payable account from ledger mapping: {account_mapping['erpnext_account']}"
            )
        else:
            debug_info.append(f"WARNING: No account mapping found for ledger ID {ledger_id}")
    else:
        debug_info.append(
            "WARNING: No ledgerID found in mutation data, ERPNext will use default payable account selection"
        )

    # Custom tracking fields
    pi.eboekhouden_mutation_nr = str(mutation_id)
    if invoice_number:
        pi.eboekhouden_invoice_number = invoice_number

    # CRITICAL: Process line items from Regels or rows
    regels = mutation_detail.get("Regels", []) or mutation_detail.get("rows", [])
    if regels:
        # For credit notes, we need to process amounts as positive values
        if is_credit_note:
            regels = _convert_negative_amounts_to_positive(regels, debug_info)

        success = process_line_items(pi, regels, "purchase", cost_center, debug_info)
        if success:
            add_tax_lines(pi, regels, "purchase", debug_info)
        else:
            # Fallback to single line
            create_single_line_fallback(pi, mutation_detail, cost_center, debug_info)
    else:
        # No line items available, create fallback
        debug_info.append("No Regels found, creating single line fallback")
        # For credit notes, convert the mutation detail amount
        if is_credit_note:
            mutation_detail = _convert_mutation_detail_amount(mutation_detail, debug_info)
        create_single_line_fallback(pi, mutation_detail, cost_center, debug_info)

    pi.save()
    pi.submit()
    debug_info.append(f"Created enhanced Purchase Invoice {pi.name} with {len(pi.items)} line items")
    return pi


def _create_payment_entry(mutation, company, cost_center, debug_info):
    """
    Create Payment Entry from mutation.

    This function now uses the enhanced PaymentEntryHandler for:
    - Proper bank account mapping from ledger IDs
    - Multi-invoice payment support
    - Automatic payment reconciliation
    """
    # Use enhanced payment handler (single code path)
    from verenigingen.e_boekhouden.utils.eboekhouden_payment_import import create_payment_entry

    payment_name = create_payment_entry(mutation, company, cost_center, debug_info)
    if payment_name:
        return frappe.get_doc("Payment Entry", payment_name)
    else:
        # Enhanced handler failed - this is a critical error that should be investigated
        error_msg = f"Enhanced payment handler failed for mutation {mutation.get('id')}. Check debug logs for details."
        debug_info.append(f"ERROR: {error_msg}")
        raise frappe.ValidationError(error_msg)


def _create_zero_amount_payment_entry(mutation, company, cost_center, debug_info):
    """Create a Payment Entry for zero-amount transactions"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", f"eBoekhouden Zero-Amount Import {mutation_id}")
    ledger_id = mutation.get("ledgerId")

    try:
        # Create Payment Entry with minimal amount (0.01) to satisfy ERPNext validation
        pe = frappe.new_doc("Payment Entry")
        pe.company = company
        pe.posting_date = mutation.get("date")
        pe.eboekhouden_mutation_nr = str(mutation_id)
        pe.custom_eboekhouden_main_ledger_id = str(ledger_id) if ledger_id else ""
        pe.reference_no = f"EBH-Zero-{mutation_id}"
        pe.reference_date = mutation.get("date")

        # Set payment type based on mutation type
        if mutation_type == 5:  # Money Received
            pe.payment_type = "Receive"
            pe.mode_of_payment = "Bank Transfer"
        elif mutation_type == 6:  # Money Paid
            pe.payment_type = "Pay"
            pe.mode_of_payment = "Bank Transfer"
        elif mutation_type == 3:  # Customer Payment
            pe.payment_type = "Receive"
            pe.mode_of_payment = "Bank Transfer"
        elif mutation_type == 4:  # Supplier Payment
            pe.payment_type = "Pay"
            pe.mode_of_payment = "Bank Transfer"
        else:
            pe.payment_type = "Internal Transfer"

        # Get bank account from main ledger
        bank_account = None
        if ledger_id:
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                ledger_id,
            )
            if mapping_result:
                bank_account = mapping_result[0][0]

        # Fallback to default bank account
        if not bank_account:
            bank_account = _get_appropriate_payment_account(company, debug_info)

        # Set accounts properly for Payment Entry
        if pe.payment_type == "Receive":
            # Money coming in: from customer/bank to our bank account
            pe.paid_from = bank_account  # Source account
            pe.paid_to = bank_account  # Our bank account
        elif pe.payment_type == "Pay":
            # Money going out: from our bank to supplier/bank
            pe.paid_from = bank_account  # Our bank account
            pe.paid_to = bank_account  # Destination account
        else:  # Internal Transfer
            pe.paid_from = bank_account
            pe.paid_to = bank_account

        # Set minimal amount (0.01) to satisfy validation, but mark as zero-amount
        pe.paid_amount = 0.01
        pe.received_amount = 0.01
        pe.remarks = f"Zero-amount transaction from eBoekhouden. Original amount: €0.00. {description}"

        # Add reference to original zero-amount nature
        pe.user_remark = f"ZERO-AMOUNT IMPORT: {description}"

        # Save the payment entry
        pe.save()
        pe.submit()

        debug_info.append(f"Created zero-amount Payment Entry {pe.name} for mutation {mutation_id}")
        return pe

    except Exception as e:
        debug_info.append(f"Failed to create zero-amount Payment Entry: {str(e)}")
        # If Payment Entry fails, create a simple log entry instead
        return _create_import_log_entry(mutation, company, debug_info)


def _create_import_log_entry(mutation, company, debug_info):
    """Create a comprehensive log entry for zero-amount transactions that can't be imported as financial documents"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", f"eBoekhouden Import {mutation_id}")
    posting_date = mutation.get("date")
    ledger_id = mutation.get("ledgerId")
    rows = mutation.get("rows", [])

    # Build detailed log content
    type_names = {
        1: "Sales Invoice",
        2: "Purchase Invoice",
        3: "Customer Payment",
        4: "Supplier Payment",
        5: "Money Received",
        6: "Money Paid",
        7: "Memorial Booking",
    }
    type_name = type_names.get(mutation_type, f"Type {mutation_type}")

    log_content = f"""ZERO-AMOUNT EBOEKHOUDEN TRANSACTION IMPORTED

Mutation ID: {mutation_id}
Type: {type_name} ({mutation_type})
Date: {posting_date}
Description: {description}
Main Ledger ID: {ledger_id}

This transaction had zero financial impact and was logged for audit purposes only.
No ERPNext financial document was created due to zero amount.

Row Details:"""

    for i, row in enumerate(rows):
        row_amount = frappe.utils.flt(row.get("amount", 0), 2)
        row_ledger = row.get("ledgerId")
        row_desc = row.get("description", "")
        log_content += f"\n  Row {i + 1}: Amount €{row_amount}, Ledger {row_ledger}, {row_desc}"

    try:
        # Create error log entry for better tracking
        error_log = frappe.new_doc("Error Log")
        error_log.method = "eBoekhouden Zero-Amount Import"
        error_log.error = log_content
        error_log.save()

        debug_info.append(
            f"Created comprehensive log entry {error_log.name} for zero-amount mutation {mutation_id}"
        )

        # Return the Error Log document directly so it has .doctype and .name attributes
        return error_log

    except Exception as e:
        debug_info.append(f"Failed to create log entry: {str(e)}")
        # Fallback to simple comment
        try:
            comment = frappe.new_doc("Comment")
            comment.comment_type = "Info"
            comment.reference_doctype = "Company"
            comment.reference_name = company
            comment.content = f"Zero-amount eBoekhouden transaction {mutation_id}: {description}"
            comment.save()

            debug_info.append(f"Created fallback comment {comment.name} for mutation {mutation_id}")
            return comment
        except Exception as e2:
            debug_info.append(f"Both log entry and comment creation failed: {str(e2)}")
            # Return None to indicate failure
            return None


def _create_money_transfer_payment_entry(mutation, company, cost_center, debug_info):
    """Create Payment Entry for Money Received (type 5) or Money Paid (type 6)"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", f"eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    ledger_id = mutation.get("ledgerId")

    # Handle both detailed data format ("Regels") and summary data format ("rows")
    rows = mutation.get("Regels", []) or mutation.get("rows", [])

    # If main amount is zero, try to get amount from rows
    if amount == 0 and rows:
        row_amounts = [abs(frappe.utils.flt(row.get("amount", 0), 2)) for row in rows]
        amount = sum(row_amounts)
        debug_info.append(f"Main amount was 0, calculated {amount} from {len(rows)} rows")

    debug_info.append(
        f"Creating money transfer Payment Entry: ID={mutation_id}, Type={mutation_type}, Amount={amount}"
    )

    # Get bank account from main ledgerId
    bank_account = None
    if ledger_id:
        mapping_result = frappe.db.sql(
            """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
            ledger_id,
        )
        if mapping_result:
            bank_account = mapping_result[0][0]
            debug_info.append(f"Mapped main ledger {ledger_id} to bank account: {bank_account}")

    if not bank_account:
        # Fallback to default payment account
        bank_account = _get_appropriate_payment_account(company, debug_info)["erpnext_account"]
        debug_info.append(f"Using fallback bank account: {bank_account}")

    # Get income/expense account from rows
    target_account = None
    if rows and len(rows) > 0:
        row_ledger_id = rows[0].get("ledgerId")
        if row_ledger_id:
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                row_ledger_id,
            )
            if mapping_result:
                target_account = mapping_result[0][0]
                debug_info.append(f"Mapped row ledger {row_ledger_id} to target account: {target_account}")

    if not target_account:
        # Create appropriate account based on mutation type
        if mutation_type == 5:  # Money Received - need income account
            line_dict = create_invoice_line_for_tegenrekening(
                tegenrekening_code=str(rows[0].get("ledgerId")) if rows else None,
                amount=abs(amount),
                description=description,
                transaction_type="sales",
            )
            target_account = line_dict.get("income_account")
        else:  # Money Paid - need expense account
            line_dict = create_invoice_line_for_tegenrekening(
                tegenrekening_code=str(rows[0].get("ledgerId")) if rows else None,
                amount=abs(amount),
                description=description,
                transaction_type="purchase",
            )
            target_account = line_dict.get("expense_account")

        debug_info.append(f"Created/mapped target account: {target_account}")

    # Check account types to determine if we need parties
    bank_account_type = frappe.db.get_value("Account", bank_account, "account_type")
    target_account_type = frappe.db.get_value("Account", target_account, "account_type")

    # If either account requires a party (Receivable/Payable), create Payment Entry with party
    # Otherwise, fall back to Journal Entry as Payment Entry requires party for bank transfers
    if bank_account_type in ["Receivable", "Payable"] or target_account_type in ["Receivable", "Payable"]:
        debug_info.append(
            "Account requires party - this should use existing Payment Entry logic for types 3/4"
        )
        # This case should be handled by the existing payment entry logic, not this function
        raise ValueError(f"Party required for account types {bank_account_type}/{target_account_type}")

    # For direct bank-to-P&L transfers, Payment Entry without party doesn't work well in ERPNext
    # Fall back to Journal Entry but with proper account mapping
    debug_info.append("Creating Journal Entry instead of Payment Entry (no party required)")

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Journal Entry"  # Use standard voucher type
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.user_remark = description
    # Set both reference fields if using Bank Entry type
    je.cheque_no = f"EB-{mutation_id}"
    je.cheque_date = mutation.get("date")

    if mutation_type == 5:  # Money Received
        # Bank account debited (money comes in)
        je.append(
            "accounts",
            {
                "account": bank_account,
                "debit_in_account_currency": abs(amount),
                "credit_in_account_currency": 0,
                "cost_center": cost_center,
                "user_remark": f"Money received - {description}",
            },
        )
        # Income account credited
        je.append(
            "accounts",
            {
                "account": target_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": abs(amount),
                "cost_center": cost_center,
                "user_remark": f"Income - {description}",
            },
        )
        debug_info.append(
            f"Money Received: Bank {bank_account} debited, Income {target_account} credited: {abs(amount)}"
        )
    else:  # Money Paid (type 6)
        # Bank account credited (money goes out)
        je.append(
            "accounts",
            {
                "account": bank_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": abs(amount),
                "cost_center": cost_center,
                "user_remark": f"Money paid - {description}",
            },
        )
        # Expense account debited
        je.append(
            "accounts",
            {
                "account": target_account,
                "debit_in_account_currency": abs(amount),
                "credit_in_account_currency": 0,
                "cost_center": cost_center,
                "user_remark": f"Expense - {description}",
            },
        )
        debug_info.append(
            f"Money Paid: Bank {bank_account} credited, Expense {target_account} debited: {abs(amount)}"
        )

    try:
        je.insert()
        je.submit()
        debug_info.append(f"Created and submitted Journal Entry {je.name}")
        return je
    except Exception as e:
        debug_info.append(f"Failed to create Journal Entry: {str(e)}")
        raise


def _create_journal_entry(mutation, company, cost_center, debug_info):
    """Create Journal Entry from mutation"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", "eBoekhouden Import {mutation_id}")
    amount = frappe.utils.flt(mutation.get("amount", 0), 2)
    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    ledger_id = mutation.get("ledgerId")
    # Handle both detailed data format ("Regels") and summary data format ("rows")
    rows = mutation.get("Regels", []) or mutation.get("rows", [])

    # Check if this is a zero-amount transaction
    row_amounts = [abs(frappe.utils.flt(row.get("amount", 0), 2)) for row in rows]
    total_row_amount = sum(row_amounts)
    is_zero_amount = total_row_amount == 0 and abs(amount) == 0

    # For zero-amount transactions, create a log entry instead of Journal Entry
    # This avoids ERPNext's validation that prevents zero-amount Journal Entry rows
    if is_zero_amount:
        debug_info.append(
            f"Zero-amount transaction detected for mutation {mutation_id}, creating log entry instead of financial document"
        )
        return _create_import_log_entry(mutation, company, debug_info)

    # Continue with regular Journal Entry creation for non-zero amounts

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Journal Entry"
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.custom_eboekhouden_main_ledger_id = str(ledger_id) if ledger_id else ""
    je.user_remark = description

    # Set descriptive name and title using enhanced naming functions
    if invoice_number:
        clean_invoice = str(invoice_number).replace("/", "-").replace("\\", "-").replace(" ", "-")
        je.name = f"EBH-{clean_invoice}"
        je.title = get_journal_entry_title(mutation, mutation_type)
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
        type_name = type_names.get(mutation_type, f"Type {mutation_type}")
        je.name = f"EBH-{type_name}-{mutation_id}"
        je.title = get_journal_entry_title(mutation, mutation_type)

    # Enhance journal entry fields for better identification
    je = enhance_journal_entry_fields(je, mutation, type_name if "type_name" in locals() else None)

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
                row_account = line_dict.get("expense_account")
                if not row_account:
                    raise ValueError(
                        f"No expense account mapping found for mutation {mutation.get('ID', 'unknown')} row with ledger_id {row_ledger_id}. Account mapping required for proper financial reporting."
                    )

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
            main_account = line_dict.get("expense_account")
            if not main_account:
                raise ValueError(
                    f"No expense account mapping found for mutation {mutation.get('ID', 'unknown')} with ledger_id {ledger_id}. Account mapping required for proper financial reporting."
                )

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

        # No automatic balancing - let journal entry validation handle unbalanced entries

    # Note: Types 5 & 6 (Money Received/Paid) should probably be Payment Entries, not Journal Entries
    # Journal Entries require manual balancing, but Payment Entries handle bank transfers automatically

    # Check for stock accounts before saving
    stock_accounts_found = []
    for account_entry in je.accounts:
        if account_entry.account:
            account_type = frappe.db.get_value("Account", account_entry.account, "account_type")
            if account_type == "Stock":
                stock_accounts_found.append(account_entry.account)

    if stock_accounts_found:
        error_msg = f"Cannot create Journal Entry: Stock accounts {', '.join(stock_accounts_found)} can only be updated via Stock Transactions"
        debug_info.append(error_msg)
        debug_info.append(
            "Skipping this mutation as it involves stock accounts which require Stock Entry instead of Journal Entry"
        )
        raise Exception(error_msg)

    try:
        je.save()
        je.submit()
        debug_info.append(f"Created Journal Entry {je.name}")
        return je
    except Exception as e:
        error_msg = f"Failed to create Journal Entry: {str(e)}"
        debug_info.append(error_msg)
        debug_info.append("This may indicate unbalanced entries or other data issues.")
        raise Exception(error_msg)


def _get_memorial_booking_amounts(row_ledger_id, main_ledger_id, row_amount, debug_info):
    """
    Calculate proper debit/credit amounts for memorial bookings based on E-Boekhouden account categories.

    This function fixes the memorial booking debit/credit logic by using E-Boekhouden account categories
    instead of simple amount-based rules that were causing inverted postings.

    Args:
        row_ledger_id: E-Boekhouden ledger ID for the row account
        main_ledger_id: E-Boekhouden ledger ID for the main account
        row_amount: Amount from E-Boekhouden (positive or negative)
        debug_info: List to append debug messages to

    Returns:
        tuple: (row_debit, row_credit, main_debit, main_credit)
    """
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        # Get E-Boekhouden account categories
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        row_category = None
        main_category = None

        # Fetch row account category
        if row_ledger_id:
            try:
                result = api.make_request(f"v1/ledger/{row_ledger_id}")
                if result["success"]:
                    ledger_data = json.loads(result["data"])
                    row_category = ledger_data.get("category")
            except Exception as e:
                debug_info.append(f"Failed to get row ledger category: {str(e)}")

        # Fetch main account category
        if main_ledger_id:
            try:
                result = api.make_request(f"v1/ledger/{main_ledger_id}")
                if result["success"]:
                    ledger_data = json.loads(result["data"])
                    main_category = ledger_data.get("category")
            except Exception as e:
                debug_info.append(f"Failed to get main ledger category: {str(e)}")

        abs_amount = abs(row_amount)
        debug_info.append(
            f"Memorial booking logic: row_category={row_category}, main_category={main_category}, amount={row_amount}"
        )

        # Apply proper debit/credit logic based on E-Boekhouden categories and amount direction
        if row_amount > 0:
            # Positive amount: Row account receives (increases), Main account provides (decreases)
            if _should_debit_increase(row_category):
                # Row account increases with debit (assets, expenses)
                row_debit, row_credit = abs_amount, 0
            else:
                # Row account increases with credit (liabilities, equity, income)
                row_debit, row_credit = 0, abs_amount

            if _should_debit_increase(main_category):
                # Main account decreases with credit (assets, expenses)
                main_debit, main_credit = 0, abs_amount
            else:
                # Main account decreases with debit (liabilities, equity, income)
                main_debit, main_credit = abs_amount, 0

        else:
            # Negative amount: Row account provides (decreases), Main account receives (increases)
            if _should_debit_increase(row_category):
                # Row account decreases with credit (assets, expenses)
                row_debit, row_credit = 0, abs_amount
            else:
                # Row account decreases with debit (liabilities, equity, income)
                row_debit, row_credit = abs_amount, 0

            if _should_debit_increase(main_category):
                # Main account increases with debit (assets, expenses)
                main_debit, main_credit = abs_amount, 0
            else:
                # Main account increases with credit (liabilities, equity, income)
                main_debit, main_credit = 0, abs_amount

        debug_info.append(
            f"Calculated amounts - Row: Dr {row_debit}, Cr {row_credit} | Main: Dr {main_debit}, Cr {main_credit}"
        )
        return row_debit, row_credit, main_debit, main_credit

    except Exception as e:
        debug_info.append(f"Error in memorial booking calculation: {str(e)}")
        # Fallback to original logic if category lookup fails
        if row_amount > 0:
            return row_amount, 0, 0, row_amount
        else:
            return 0, -row_amount, -row_amount, 0


def _should_debit_increase(eboekhouden_category, ledger_id=None):
    """
    Determine if an account with the given E-Boekhouden category increases with debits.

    This function uses both category and specific ledger knowledge to determine proper debit/credit behavior.
    Based on analysis of actual memorial bookings, we know specific account behaviors.

    Args:
        eboekhouden_category: The category from E-Boekhouden API
        ledger_id: The specific E-Boekhouden ledger ID for more precise logic

    Returns:
        bool: True if account increases with debits, False if increases with credits
    """
    if not eboekhouden_category:
        return True  # Default to debit increases for unknown categories

    # Specific ledger overrides based on known account behaviors
    if ledger_id:
        # Known equity/result accounts that increase with credits
        equity_result_ledgers = {
            13201865,  # 05000 - Vrij besteedbaar eigen vermogen (Equity)
            16167827,  # 99998 - Eindresultaat (Result account)
        }

        # Known asset accounts that increase with debits
        asset_ledgers = {
            13201861,  # 02400 - Apparatuur en toebehoren (Equipment)
            13201870,  # 10470 - PayPal (Bank/Financial)
            14526213,  # 10001 - Kruisposten (Clearing account)
            13849374,  # 14700 - Overlopende Posten (Accruals)
        }

        # Known expense accounts that increase with debits
        expense_ledgers = {
            13201953,  # 48010 - Afschrijving Inventaris (Depreciation expense)
        }

        if ledger_id in equity_result_ledgers:
            return False  # Equity/result accounts increase with credits
        elif ledger_id in asset_ledgers or ledger_id in expense_ledgers:
            return True  # Asset/expense accounts increase with debits

    # Category-based logic
    if eboekhouden_category == "VW":  # Verlies & Winst (P&L)
        # P&L accounts: expenses increase with debits, income increases with credits
        # Default to expense behavior unless we know it's an income/result account
        if ledger_id == 16167827:  # Specific result account
            return False
        return True  # Most P&L accounts are expenses

    elif eboekhouden_category == "BAL":  # Balans (Balance Sheet)
        # Balance Sheet: assets increase with debits, liabilities/equity increase with credits
        # Use specific ledger knowledge or default to asset behavior
        if ledger_id == 13201865:  # Specific equity account
            return False
        return True  # Most balance sheet accounts we deal with are assets

    elif eboekhouden_category == "FIN":  # Financial accounts
        return True  # Financial accounts (banks, cash) are assets - increase with debits

    elif eboekhouden_category == "DEB":  # Debiteuren (Receivables)
        return True  # Receivables are assets - increase with debits

    elif eboekhouden_category == "CRED":  # Crediteuren (Payables)
        return False  # Payables are liabilities - increase with credits

    # Default fallback
    return True


def start_full_rest_import(migration_name):
    """
    Start full REST import for a migration document.

    This function was restored from git history to fix the missing import error.
    Uses the simpler REST iterator approach with enhanced error handling for new fields.

    Args:
        migration_name: Name of the E-Boekhouden Migration document

    Returns:
        dict: Migration result with success status and stats
    """
    try:
        # Get the migration document to extract parameters
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.get_password("api_token"):
            return {
                "success": False,
                "error": "REST API token not configured in E-Boekhouden Settings",
            }

        # Extract migration parameters with defaults
        company = getattr(migration_doc, "company", None) or settings.default_company
        date_from = getattr(migration_doc, "date_from", None)
        date_to = getattr(migration_doc, "date_to", None)
        migrate_transactions = getattr(migration_doc, "migrate_transactions", 1)

        if not company:
            return {"success": False, "error": "No company specified"}

        # Update migration document with progress
        migration_doc.db_set("current_operation", "Starting REST API import...")
        migration_doc.db_set("progress_percentage", 5)
        frappe.db.commit()

        # Use the simpler REST iterator approach
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Import all mutation types (Sales, Purchase, Payments, Money Transfers, Memorial)
        mutation_types = [1, 2, 3, 4, 5, 6, 7]

        # Add opening balances (type 0) if this is a full migration
        # Opening balances should be imported when:
        # 1. No date_from is specified (import all transactions)
        # 2. date_from is set to 2019-01-01 or earlier (includes 2018-12-31 opening balances)
        # getdate already imported at top of file

        is_full_import = migrate_transactions and (
            not date_from
            or (
                date_from and getdate(date_from) <= getdate("2019-01-01")
            )  # Cutoff for "full" import (includes 2018-12-31 opening balances)
        )

        if is_full_import:
            mutation_types.insert(0, 0)  # Add type 0 at the beginning
            frappe.log_error(
                f"Including opening balances (type 0) in migration. Date from: {date_from}",
                "eBoekhouden Import",
            )
        total_imported = 0
        total_failed = 0
        total_skipped = 0
        errors = []

        for i, mutation_type in enumerate(mutation_types):
            try:
                # Update progress dynamically based on total mutation types
                total_types = len(mutation_types)
                progress_step = (
                    80 / total_types
                )  # Use 80% for mutation processing (10% for setup, 10% for completion)
                progress = 10 + (i * progress_step)  # Start at 10%, increment dynamically

                # Get descriptive type name
                type_names = {
                    0: "Opening Balances",
                    1: "Purchase Invoices",
                    2: "Sales Invoices",
                    3: "Customer Payments",
                    4: "Supplier Payments",
                    5: "Money Received",
                    6: "Money Paid",
                    7: "Memorial Bookings",
                }
                type_name = type_names.get(mutation_type, f"Type {mutation_type}")

                migration_doc.db_set("current_operation", f"Processing {type_name} (type {mutation_type})...")
                migration_doc.db_set("progress_percentage", int(progress))
                frappe.db.commit()

                # Fetch all mutations of this type
                mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=500)

                # Filter by date if specified (but not for opening balances - type 0)
                if (date_from or date_to) and mutation_type != 0:
                    filtered_mutations = []
                    for mutation in mutations:
                        mutation_date = mutation.get("date")
                        if mutation_date:
                            mut_date = getdate(mutation_date)
                            include = True

                            if date_from and mut_date < getdate(date_from):
                                include = False
                            if date_to and mut_date > getdate(date_to):
                                include = False

                            if include:
                                filtered_mutations.append(mutation)
                    mutations = filtered_mutations

                if mutations:
                    # Special handling for opening balances (type 0)
                    if mutation_type == 0:
                        # Use the specialized opening balance import function
                        debug_info = []
                        company = settings.default_company
                        cost_center = get_default_cost_center(company)

                        # Call the advanced opening balance import function
                        result = _import_opening_balances(company, cost_center, debug_info, dry_run=False)

                        # Convert result to batch result format
                        if result.get("success"):
                            batch_result = {
                                "imported": 1 if result.get("journal_entry") else 0,
                                "failed": 0,
                                "skipped": 0,
                                "errors": [],
                            }
                        else:
                            batch_result = {
                                "imported": 0,
                                "failed": len(mutations),  # All mutations failed
                                "skipped": 0,
                                "errors": [result.get("error", "Opening balance import failed")],
                            }

                        # Create summary log for opening balances
                        summary_title = "eBoekhouden REST Import - Opening Balances Complete"
                        summary_content = "BATCH SUMMARY for Opening Balances:\n"
                        summary_content += f"• Processed: {len(mutations)} mutations\n"
                        summary_content += f"• Imported: {batch_result['imported']}\n"
                        summary_content += f"• Failed: {batch_result['failed']}\n"
                        summary_content += f"• Skipped: {batch_result['skipped']}\n"
                        summary_content += f"• Total Errors: {len(batch_result['errors'])}\n"
                        frappe.log_error(summary_content, summary_title)

                        # Log detailed error information for opening balances when there are failures
                        if batch_result["errors"]:
                            detailed_error_content = "DETAILED ERROR REPORT for Opening Balances:\n\n"
                            for i, error in enumerate(batch_result["errors"], 1):
                                detailed_error_content += f"{i}. {error}\n\n"

                            detailed_title = "eBoekhouden REST Import - Opening Balances - Detailed Errors"
                            frappe.log_error(detailed_error_content, detailed_title)
                    else:
                        # Process other mutations using the batch import with enhanced error handling
                        batch_result = _import_rest_mutations_batch_enhanced(
                            migration_name, mutations, settings, mutation_type
                        )

                    total_imported += batch_result.get("imported", 0)
                    total_failed += batch_result.get("failed", 0)
                    total_skipped += batch_result.get("skipped", 0)
                    errors.extend(batch_result.get("errors", []))
                else:
                    # Create summary log even when no mutations found
                    type_names = {
                        0: "Opening Balances",
                        1: "Purchase Invoices",
                        2: "Sales Invoices",
                        3: "Customer Payments",
                        4: "Supplier Payments",
                        5: "Money Received",
                        6: "Money Paid",
                        7: "Memorial Bookings",
                    }
                    type_name = type_names.get(mutation_type, f"Type {mutation_type}")

                    debug_info = [f"No {type_name.lower()} mutations found in the specified date range"]
                    frappe.log_error(
                        "ENHANCED BATCH Log:\n" + "\n".join(debug_info),
                        f"eBoekhouden Import - {type_name} - No Data Found",
                    )

                    # Update running totals in the migration document
                    current_total = total_imported + total_failed + total_skipped
                    migration_doc.db_set("imported_records", total_imported)
                    migration_doc.db_set("failed_records", total_failed)
                    migration_doc.db_set("total_records", current_total)
                    frappe.db.commit()

            except Exception as e:
                errors.append(f"Error importing mutation type {mutation_type}: {str(e)}")
                total_failed += 1

        # Final progress update
        total_records = total_imported + total_failed + total_skipped
        migration_doc.db_set("current_operation", "Import completed")
        migration_doc.db_set("progress_percentage", 100)
        migration_doc.db_set("imported_records", total_imported)
        migration_doc.db_set("failed_records", total_failed)
        migration_doc.db_set("total_records", total_records)
        frappe.db.commit()

        # Return results in expected format
        return {
            "success": True,
            "stats": {
                "total_mutations": total_imported + total_failed + total_skipped,
                "invoices_created": total_imported,  # Simplified - actual breakdown would need more detail
                "payments_processed": 0,  # Would need to track separately
                "journal_entries_created": 0,  # Would need to track separately
                "skipped_existing": total_skipped,
                "errors": errors,
            },
        }

    except Exception as e:
        frappe.log_error(f"Error in start_full_rest_import: {str(e)}", "E-Boekhouden Migration")
        return {"success": False, "error": str(e)}


def _import_rest_mutations_batch_enhanced(migration_name, mutations, settings, mutation_type=None):
    """
    Enhanced batch import that handles new fields gracefully.

    This version includes better error handling for newly added fields like payment_terms
    that might not exist in all mutations or might cause processing issues.
    """
    imported = 0
    failed = 0
    skipped = 0
    errors = []
    debug_info = []

    # Get descriptive mutation type name
    mutation_type_names = {
        0: "Opening Balances",
        1: "Purchase Invoices",
        2: "Sales Invoices",
        3: "Customer Payments",
        4: "Supplier Payments",
        5: "Money Received",
        6: "Money Paid",
        7: "Memorial Bookings",
    }
    type_name = (
        mutation_type_names.get(mutation_type, f"Type {mutation_type}") if mutation_type else "Mixed Types"
    )

    debug_info.append(
        f"Starting enhanced batch import with {len(mutations) if mutations else 0} mutations of {type_name}"
    )

    if not mutations:
        debug_info.append("No mutations provided, returning early")
        frappe.log_error(
            "ENHANCED BATCH Log:\n" + "\n".join(debug_info),
            f"eBoekhouden Import - {type_name} - No Mutations",
        )
        return {"imported": 0, "failed": 0, "skipped": 0, "errors": []}

    company = settings.default_company
    debug_info.append(f"Company: {company}")

    # Get cost center
    cost_center = get_default_cost_center(company)
    debug_info.append(f"Cost center found: {cost_center}")

    if not cost_center:
        errors.append("No cost center found")
        debug_info.append("ERROR - No cost center found")
        frappe.log_error(
            "ENHANCED BATCH Log:\n" + "\n".join(debug_info),
            f"eBoekhouden Import - {type_name} - Cost Center Error",
        )
        return {"imported": 0, "failed": len(mutations), "skipped": 0, "errors": errors}

    for i, mutation in enumerate(mutations):
        try:
            # Skip if already imported
            mutation_id = mutation.get("id")
            mutation_type = mutation.get("type", 0)

            if not mutation_id:
                errors.append("Mutation missing ID, skipping")
                debug_info.append("ERROR - Mutation missing ID")
                failed += 1
                continue

            # Check for existing documents
            existing_je = _check_if_already_imported(mutation_id, "Journal Entry")
            existing_pe = _check_if_already_imported(mutation_id, "Payment Entry")
            existing_si = _check_if_already_imported(mutation_id, "Sales Invoice")
            existing_pi = _check_if_already_imported(mutation_id, "Purchase Invoice")

            if existing_je or existing_pe or existing_si or existing_pi:
                skipped += 1
                continue

            # Check if this mutation should be skipped (e.g., zero-amount system notifications)
            if should_skip_mutation(mutation, debug_info):
                skipped += 1
                continue

            # Process the mutation with enhanced error handling
            try:
                debug_info.append(f"Processing mutation {mutation_id}")
                doc = _process_single_mutation(mutation, company, cost_center, debug_info)

                if doc:
                    imported += 1
                    debug_info.append(
                        f"Successfully imported mutation {mutation_id} as {doc.doctype} {doc.name}"
                    )
                else:
                    # doc is False or None means it failed
                    failed += 1
                    debug_info.append(f"Failed to process mutation {mutation_id} - no document returned")

            except Exception as processing_error:
                error_str = str(processing_error)

                # Handle stock account errors more gracefully
                if (
                    "Stock accounts" in error_str
                    and "can only be updated via Stock Transactions" in error_str
                ):
                    skipped += 1
                    error_msg = f"Skipped mutation {mutation_id}: {error_str}"
                    debug_info.append(f"STOCK ACCOUNT SKIP - {error_msg}")
                else:
                    failed += 1
                    error_msg = f"Error processing mutation {mutation_id}: {error_str}"
                    errors.append(error_msg)
                    debug_info.append(f"PROCESSING ERROR - {error_msg}")

                # Error details collected in batch summary

        except Exception as e:
            failed += 1
            error_msg = f"Error in batch processing loop for mutation {i}: {str(e)}"
            errors.append(error_msg)
            debug_info.append(f"LOOP ERROR - {error_msg}")

    # Group errors by category
    error_categories = {}
    for error in errors:
        if "Stock accounts" in error and "can only be updated via Stock Transactions" in error:
            category = "Stock Account Updates (Fixed - now creates Stock Reconciliations)"
        elif "already been fully paid" in error or "cannot be greater than outstanding amount" in error:
            category = "Payment Allocation Issues"
        elif "Could not find" in error:
            category = "Missing References"
        elif "already exists" in error:
            category = "Duplicate Entries"
        else:
            category = "Other Errors"

        if category not in error_categories:
            error_categories[category] = []
        error_categories[category].append(error)

    # Log comprehensive debug info with more descriptive title
    summary_title = f"eBoekhouden REST Import - {type_name} Complete"
    summary_content = f"BATCH SUMMARY for {type_name}:\n"
    summary_content += f"• Processed: {len(mutations) if mutations else 0} mutations\n"
    summary_content += f"• Imported: {imported}\n"
    summary_content += f"• Failed: {failed}\n"
    summary_content += f"• Skipped: {skipped}\n"
    summary_content += f"• Total Errors: {len(errors)}\n\n"

    if error_categories:
        summary_content += "ERROR CATEGORIES:\n"
        for category, category_errors in error_categories.items():
            summary_content += f"\n{category} ({len(category_errors)} errors):\n"
            # Show first 5 errors of each category
            for error in category_errors[:5]:
                # Extract just mutation ID from error message
                if "mutation" in error:
                    import re

                    mutation_match = re.search(r"mutation (\d+)", error)
                    if mutation_match:
                        summary_content += f"  - Mutation {mutation_match.group(1)}\n"
                    else:
                        summary_content += f"  - {error[:100]}...\n" if len(error) > 100 else f"  - {error}\n"
                else:
                    summary_content += f"  - {error[:100]}...\n" if len(error) > 100 else f"  - {error}\n"
            if len(category_errors) > 5:
                summary_content += f"  ... and {len(category_errors) - 5} more\n"

    frappe.log_error(summary_content, summary_title)

    # Log detailed error information when there are failures
    if errors:
        detailed_error_content = f"DETAILED ERROR REPORT for {type_name}:\n\n"

        for category, category_errors in error_categories.items():
            detailed_error_content += f"{category} ({len(category_errors)} errors):\n"
            for i, error in enumerate(category_errors, 1):
                detailed_error_content += f"\n{i}. {error}\n"
            detailed_error_content += "\n" + "=" * 80 + "\n\n"

        # Log detailed errors separately for easy access
        detailed_title = f"eBoekhouden REST Import - {type_name} - Detailed Errors"
        frappe.log_error(detailed_error_content, detailed_title)

    return {"imported": imported, "failed": failed, "skipped": skipped, "errors": errors}

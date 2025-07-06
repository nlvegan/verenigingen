"""
E-Boekhouden REST API Full Migration
Fetches ALL mutations by iterating through IDs and caches them
"""

import json

import frappe
from frappe import _


@frappe.whitelist()
def fetch_and_cache_all_mutations(start_id=None, end_id=None, batch_size=100):
    """
    Fetch and cache all mutations from REST API

    Args:
        start_id: Starting mutation ID (defaults to estimated lowest)
        end_id: Ending mutation ID (defaults to estimated highest)
        batch_size: Number of mutations to process before committing

    Returns:
        Dict with success status and statistics
    """
    from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    try:
        iterator = EBoekhoudenRESTIterator()

        # If no range specified, estimate it
        if not start_id or not end_id:
            frappe.publish_realtime(
                "eboekhouden_migration_progress", {"message": "Estimating mutation ID range..."}
            )

            range_result = iterator.estimate_id_range()
            if not range_result["success"]:
                return {"success": False, "error": "Could not estimate mutation range"}

            start_id = start_id or range_result["lowest_id"]
            end_id = end_id or range_result["highest_id"]

        frappe.publish_realtime(
            "eboekhouden_migration_progress",
            {"message": f"Starting to fetch mutations from ID {start_id} to {end_id}..."},
        )

        # Statistics
        total_fetched = 0
        total_cached = 0
        already_cached = 0
        errors = []
        current_batch = []

        # Progress callback
        def update_progress(info):
            frappe.publish_realtime(
                "eboekhouden_migration_progress",
                {
                    "message": f"Checking ID {info['current_id']} - Found: {info['found']}, Not found: {info['not_found']}",
                    "progress": (info["current_id"] - start_id) / (end_id - start_id) * 100,
                },
            )

        # Iterate through IDs
        for mutation_id in range(start_id, end_id + 1):
            # Check if already cached
            existing_cache = frappe.db.get_value(
                "EBoekhouden REST Mutation Cache", {"mutation_id": mutation_id}, "name"
            )
            if existing_cache:
                already_cached += 1
                continue

            # Try to fetch the mutation
            try:
                # First try detail endpoint (more complete data)
                mutation_data = iterator.fetch_mutation_detail(mutation_id)

                if mutation_data:
                    total_fetched += 1

                    # Create cache entry
                    cache_doc = frappe.new_doc("EBoekhouden REST Mutation Cache")
                    cache_doc.mutation_id = mutation_id
                    cache_doc.mutation_data = json.dumps(mutation_data)
                    cache_doc.mutation_type = mutation_data.get("type")
                    cache_doc.mutation_date = mutation_data.get("date")
                    cache_doc.amount = abs(float(mutation_data.get("amount", 0)))
                    cache_doc.ledger_id = mutation_data.get("ledgerId")
                    cache_doc.relation_id = mutation_data.get("relationId")
                    cache_doc.invoice_number = mutation_data.get("invoiceNumber")
                    cache_doc.entry_number = mutation_data.get("entryNumber")
                    cache_doc.description = mutation_data.get("description", "")[:140]  # Truncate for field

                    current_batch.append(cache_doc)

                    # Commit batch
                    if len(current_batch) >= batch_size:
                        _save_batch(current_batch)
                        total_cached += len(current_batch)
                        current_batch = []

                        frappe.publish_realtime(
                            "eboekhouden_migration_progress",
                            {
                                "message": f"Cached {total_cached} mutations so far...",
                                "progress": (mutation_id - start_id) / (end_id - start_id) * 100,
                            },
                        )

            except Exception as e:
                errors.append({"mutation_id": mutation_id, "error": str(e)})

            # Progress update every 50 IDs
            if mutation_id % 50 == 0:
                update_progress(
                    {
                        "current_id": mutation_id,
                        "found": total_fetched,
                        "not_found": mutation_id - start_id - total_fetched - already_cached,
                        "total_checked": mutation_id - start_id + 1,
                    }
                )

        # Save remaining batch
        if current_batch:
            _save_batch(current_batch)
            total_cached += len(current_batch)

        # Final statistics
        result = {
            "success": True,
            "statistics": {
                "range_checked": f"{start_id} to {end_id}",
                "total_ids_checked": end_id - start_id + 1,
                "total_fetched": total_fetched,
                "total_cached": total_cached,
                "already_cached": already_cached,
                "not_found": end_id - start_id + 1 - total_fetched - already_cached,
                "errors": len(errors),
            },
        }

        frappe.publish_realtime(
            "eboekhouden_migration_progress",
            {
                "message": f"Completed! Fetched {total_fetched} mutations, cached {total_cached} new entries.",
                "progress": 100,
            },
        )

        return result

    except Exception as e:
        frappe.log_error(f"REST mutation fetch error: {str(e)}", "E-Boekhouden REST Migration")
        return {"success": False, "error": str(e)}


def _save_batch(batch):
    """Save a batch of cache documents"""
    for doc in batch:
        try:
            doc.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                f"Failed to cache mutation {doc.mutation_id}: {str(e)}", "E-Boekhouden Cache Error"
            )
    frappe.db.commit()


@frappe.whitelist()
def get_cache_statistics():
    """Get statistics about cached mutations"""
    try:
        total_cached = frappe.db.count("EBoekhouden REST Mutation Cache")

        if total_cached == 0:
            return {"success": True, "total_cached": 0, "message": "No mutations cached yet"}

        # Get date range
        oldest = frappe.db.sql(
            """
            SELECT MIN(mutation_date) as oldest_date,
                   MIN(mutation_id) as lowest_id
            FROM `tabEBoekhouden REST Mutation Cache`
        """,
            as_dict=True,
        )[0]

        newest = frappe.db.sql(
            """
            SELECT MAX(mutation_date) as newest_date,
                   MAX(mutation_id) as highest_id
            FROM `tabEBoekhouden REST Mutation Cache`
        """,
            as_dict=True,
        )[0]

        # Get type distribution
        type_distribution = frappe.db.sql(
            """
            SELECT mutation_type, COUNT(*) as count
            FROM `tabEBoekhouden REST Mutation Cache`
            GROUP BY mutation_type
            ORDER BY count DESC
        """,
            as_dict=True,
        )

        # Map type numbers to names (based on REST API documentation)
        type_names = {
            0: "Opening Balance",
            1: "Invoice received",  # Purchase Invoice
            2: "Invoice sent",  # Sales Invoice
            3: "Invoice payment received",  # Customer Payment
            4: "Invoice payment sent",  # Supplier Payment
            5: "Money received",
            6: "Money sent",
            7: "General journal entry",
        }

        for item in type_distribution:
            item["type_name"] = type_names.get(item["mutation_type"], f"Type {item['mutation_type']}")

        return {
            "success": True,
            "total_cached": total_cached,
            "date_range": {"oldest": oldest["oldest_date"], "newest": newest["newest_date"]},
            "id_range": {"lowest": oldest["lowest_id"], "highest": newest["highest_id"]},
            "type_distribution": type_distribution,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def clear_cache():
    """Clear all cached mutations"""
    try:
        frappe.db.sql("DELETE FROM `tabEBoekhouden REST Mutation Cache`")
        frappe.db.commit()

        return {"success": True, "message": "Cache cleared successfully"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fetch_sample_batch(start_id=100, end_id=200):
    """Fetch a small batch for testing"""
    return fetch_and_cache_all_mutations(start_id=int(start_id), end_id=int(end_id), batch_size=10)


@frappe.whitelist()
def check_cache_table():
    """Check if cache table exists"""
    try:
        # Check if the DocType exists
        doctype_exists = frappe.db.exists("DocType", "EBoekhouden REST Mutation Cache")

        # Check if the table exists
        table_exists = False
        try:
            frappe.db.sql("SELECT 1 FROM `tabEBoekhouden REST Mutation Cache` LIMIT 1")
            table_exists = True
        except Exception:
            pass

        return {"doctype_exists": doctype_exists, "table_exists": table_exists}
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def start_full_rest_import(migration_name):
    """Start full transaction import via REST API"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Check perpetual inventory settings before starting
        company = frappe.get_single("E-Boekhouden Settings").default_company
        if company:
            company_doc = frappe.get_doc("Company", company)
            if company_doc.enable_perpetual_inventory:
                # Check if Stock Received But Not Billed account is set
                if not company_doc.stock_received_but_not_billed:
                    return {
                        "success": False,
                        "error": _(
                            "Perpetual inventory is enabled but 'Stock Received But Not Billed' account is not set. Please either set this account in Company settings or disable perpetual inventory."
                        ),
                    }

        # Update status
        migration.db_set(
            {
                "migration_status": "In Progress",
                "start_time": frappe.utils.now_datetime(),
                "current_operation": "Starting REST API transaction import...",
                "progress_percentage": 0,
            }
        )
        frappe.db.commit()

        # Phase 1: Import any new customers/suppliers first
        frappe.publish_realtime(
            "eboekhouden_migration_progress", {"message": "Importing customers and suppliers..."}
        )

        # Import customers and suppliers via standard SOAP method
        settings = frappe.get_single("E-Boekhouden Settings")

        # Import customers
        if getattr(migration, "migrate_customers", 0):
            migrate_method = getattr(migration.__class__, "migrate_customers")
            customer_result = migrate_method(migration, settings)
            migration.db_set({"current_operation": f"Imported customers: {customer_result}"})
            frappe.db.commit()

        # Import suppliers
        if getattr(migration, "migrate_suppliers", 0):
            migrate_method = getattr(migration.__class__, "migrate_suppliers")
            supplier_result = migrate_method(migration, settings)
            migration.db_set({"current_operation": f"Imported suppliers: {supplier_result}"})
            frappe.db.commit()

        # Phase 2: Fetch and cache all mutations
        migration.db_set(
            {"current_operation": "Fetching all transactions via REST API...", "progress_percentage": 20}
        )
        frappe.db.commit()

        # Estimate ID range and fetch all mutations
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get estimated range
        range_result = iterator.estimate_id_range()
        if not range_result["success"]:
            raise Exception(f"Could not estimate mutation range: {range_result.get('error')}")

        start_id = range_result["lowest_id"]
        end_id = range_result["highest_id"]

        frappe.publish_realtime(
            "eboekhouden_migration_progress", {"message": f"Found mutation range: ID {start_id} to {end_id}"}
        )

        # Phase 3: Import mutations by type (optimized approach)
        # Import all mutation types with smart tegenrekening mapping
        mutation_types = [0, 1, 2, 3, 4, 5, 6, 7]  # All mutation types including opening balance
        type_names = {
            0: "Opening Balances",
            1: "Purchase Invoices",
            2: "Sales Invoices",
            3: "Customer Payments",
            4: "Supplier Payments",
            5: "Money Received",
            6: "Money Sent",
            7: "Journal Entries",
        }

        total_imported = 0
        failed_imports = []
        debug_info = []

        for i, mutation_type in enumerate(mutation_types):
            type_name = type_names.get(mutation_type, f"Type {mutation_type}")

            migration.db_set(
                {
                    "current_operation": f"Fetching {type_name}...",
                    "progress_percentage": 20 + (i / len(mutation_types) * 70),
                }
            )
            frappe.db.commit()

            frappe.publish_realtime(
                "eboekhouden_migration_progress", {"message": f"Processing {type_name}..."}
            )

            # Fetch all mutations of this type
            try:

                def progress_callback(info):
                    progress_msg = f"{type_name}: Fetched {info['total_fetched']} mutations"
                    frappe.publish_realtime("eboekhouden_migration_progress", {"message": progress_msg})
                    debug_info.append(progress_msg)

                # Fetch all mutations of this type (no limit for full migration)
                type_mutations = iterator.fetch_mutations_by_type(
                    mutation_type, progress_callback=progress_callback
                )

                debug_info.append(
                    f"DEBUG: fetch_mutations_by_type returned {len(type_mutations) if type_mutations else 0} mutations"
                )

                if type_mutations:
                    debug_info.append(
                        f"DEBUG: Sample mutation keys: {list(type_mutations[0].keys()) if type_mutations[0] else 'None'}"
                    )
                    debug_info.append(
                        f"DEBUG: Sample mutation: {type_mutations[0] if type_mutations[0] else 'None'}"
                    )

                    frappe.publish_realtime(
                        "eboekhouden_migration_progress",
                        {"message": f"Processing {len(type_mutations)} {type_name}..."},
                    )

                    # Import this batch
                    debug_info.append(
                        f"Calling _import_rest_mutations_batch with {len(type_mutations)} mutations"
                    )
                    import_result = _import_rest_mutations_batch(migration_name, type_mutations, settings)
                    debug_info.append(f"Import result: {import_result}")

                    total_imported += import_result.get("imported", 0)

                    if import_result.get("errors"):
                        failed_imports.extend(import_result["errors"])
                        debug_info.append(f"Errors occurred: {len(import_result['errors'])}")

                else:
                    debug_info.append(f"No mutations returned for {type_name}")
                    frappe.publish_realtime(
                        "eboekhouden_migration_progress", {"message": f"No {type_name} found"}
                    )

            except Exception as e:
                error_msg = f"Failed to process {type_name}: {str(e)}"
                failed_imports.append(error_msg)
                debug_info.append(error_msg)
                # Use very short log title to avoid cascading length issues
                log_title = f"{type_name[:20]}"[:50]  # Ensure max 50 chars
                # Only log first 500 chars to avoid nested length issues
                frappe.log_error(error_msg[:500], log_title)

        # Log all debug info
        debug_log = "\n".join(debug_info)
        frappe.log_error(f"DEBUG REST Import Log:\n{debug_log}", "REST Debug")

        # Phase 4: Complete
        migration.db_set(
            {
                "migration_status": "Completed",
                "end_time": frappe.utils.now_datetime(),
                "current_operation": f"Import completed. Total mutations imported: {total_imported}",
                "progress_percentage": 100,
                "imported_records": total_imported,
                "failed_records": len(failed_imports),
            }
        )
        frappe.db.commit()

        frappe.publish_realtime(
            "eboekhouden_migration_progress",
            {
                "message": f"REST API import completed! Imported {total_imported} transactions.",
                "progress": 100,
                "completed": True,
            },
        )

        return {"success": True, "total_imported": total_imported, "failed": len(failed_imports)}

    except Exception as e:
        import traceback

        full_error = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        frappe.log_error(f"REST import failed: {full_error}", "E-Boekhouden REST Import")

        # Update migration status
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.db_set(
            {"migration_status": "Failed", "error_log": full_error, "end_time": frappe.utils.now_datetime()}
        )
        frappe.db.commit()

        return {"success": False, "error": str(e)}


def _import_rest_mutations_batch(migration_name, mutations, settings):
    """Import a batch of REST API mutations with smart tegenrekening mapping"""
    imported = 0
    errors = []
    debug_info = []

    debug_info.append(f"Starting import with {len(mutations) if mutations else 0} mutations")

    if not mutations:
        debug_info.append("No mutations provided, returning early")
        frappe.log_error("BATCH Log:\n" + "\n".join(debug_info), "REST Batch Debug")
        return {"imported": 0, "failed": 0, "errors": []}

    # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)  # Not needed for batch processing
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
            mutation_type = mutation.get("type")
            mutation_id = mutation.get("id")

            debug_info.append(
                f"Processing mutation {i + 1}/{len(mutations)}: ID={mutation_id}, Type={mutation_type}"
            )

            # Don't skip any mutations - opening balance is mutation ID 0, not type 0

            # Extract amount from rows (correct structure for REST API mutations)
            amount = 0
            rows = mutation.get("rows", [])
            if rows:
                for row in rows:
                    amount += float(row.get("amount", 0))  # Don't use abs() - keep sign for debit/credit

            description = mutation.get("description", f"Mutation {mutation_id}")

            debug_info.append(f"Calculated amount for mutation {mutation_id}: {amount}")

            if amount != 0:  # Process both positive and negative amounts
                # Import smart tegenrekening mapping
                from verenigingen.utils.smart_tegenrekening_mapper import (
                    create_invoice_line_for_tegenrekening,
                )

                # Extract ledger ID from mutation rows
                ledger_id = None
                if rows:
                    ledger_id = rows[0].get("ledgerId")

                if mutation_type == 1:  # Purchase Invoice (FactuurOntvangen)
                    debug_info.append(f"Creating Purchase Invoice for mutation {mutation_id}")

                    # Create Purchase Invoice
                    pi = frappe.new_doc("Purchase Invoice")
                    pi.company = company
                    pi.posting_date = mutation.get("date")
                    pi.bill_no = mutation.get("invoiceNumber", f"EBH-{mutation_id}")
                    pi.bill_date = mutation.get("date")

                    # Set proper title and naming based on eBoekhouden data
                    invoice_number = mutation.get("invoiceNumber")
                    if invoice_number:
                        pi.title = f"eBoekhouden {invoice_number}"
                        # Store eBoekhouden invoice number in custom field if it exists
                        if hasattr(pi, "eboekhouden_invoice_number"):
                            pi.eboekhouden_invoice_number = invoice_number
                    else:
                        pi.title = f"eBoekhouden Purchase {mutation_id}"

                    # Store eBoekhouden mutation ID for reference
                    if hasattr(pi, "eboekhouden_mutation_id"):
                        pi.eboekhouden_mutation_id = mutation_id

                    # Try to find supplier from relation_id
                    relation_id = mutation.get("relationId")
                    supplier = _get_or_create_supplier(relation_id, debug_info)
                    pi.supplier = supplier

                    # Set correct payable account for credit_to
                    pi.credit_to = _get_payable_account(company)

                    # Debug: Log what we're about to add
                    debug_info.append(f"About to add items for mutation {mutation_id}, rows: {len(rows)}")

                    # Process each row as a separate line item
                    if rows and len(rows) > 0:
                        for idx, row in enumerate(rows):
                            row_amount = frappe.utils.flt(row.get("amount", 0), 2)
                            row_ledger_id = row.get("ledgerId")
                            row_description = row.get("description", description)

                            # Skip rows with zero amount
                            if row_amount == 0:
                                continue

                            # Add item line using smart tegenrekening mapping
                            try:
                                line_dict = create_invoice_line_for_tegenrekening(
                                    tegenrekening_code=str(row_ledger_id) if row_ledger_id else None,
                                    amount=abs(row_amount),  # Use absolute value for invoice lines
                                    description=row_description,
                                    transaction_type="purchase",
                                )
                                if line_dict and isinstance(line_dict, dict):
                                    # Validate expense account exists
                                    if line_dict.get("expense_account"):
                                        # Check if expense account exists
                                        if not frappe.db.exists("Account", line_dict["expense_account"]):
                                            debug_info.append(
                                                f"Expense account {line_dict['expense_account']} not found, using fallback"
                                            )
                                            # Get any expense account
                                            fallback_account = frappe.db.get_value(
                                                "Account",
                                                {
                                                    "company": company,
                                                    "account_type": "Expense Account",
                                                    "is_group": 0,
                                                },
                                                "name",
                                            )
                                            if fallback_account:
                                                line_dict["expense_account"] = fallback_account
                                            else:
                                                line_dict[
                                                    "expense_account"
                                                ] = "44009 - Onvoorziene kosten - NVV"
                                    pi.append("items", line_dict)
                                else:
                                    debug_info.append(
                                        f"Smart mapping returned invalid result for row {idx}: {line_dict}"
                                    )
                                    # Fallback to basic item
                                    pi.append(
                                        "items",
                                        {
                                            "item_code": "E-Boekhouden Import Item",
                                            "qty": 1,
                                            "rate": abs(row_amount),
                                            "description": row_description,
                                        },
                                    )
                            except Exception as e:
                                debug_info.append(f"Smart mapping error for row {idx}: {str(e)}")
                                # Fallback to basic item
                                pi.append(
                                    "items",
                                    {
                                        "item_code": "E-Boekhouden Import Item",
                                        "qty": 1,
                                        "rate": abs(row_amount),
                                        "description": row_description,
                                    },
                                )
                    else:
                        # No rows found, use total amount as single line
                        debug_info.append(f"No rows found, using total amount: {amount}")
                        pi.append(
                            "items",
                            {
                                "item_code": "E-Boekhouden Import Item",
                                "qty": 1,
                                "rate": abs(amount),
                                "description": description,
                            },
                        )

                    # Save and submit
                    pi.save()
                    pi.submit()
                    imported += 1
                    debug_info.append(f"Successfully created Purchase Invoice for mutation {mutation_id}")

                elif mutation_type == 2:  # Sales Invoice (FactuurVerstuurd)
                    debug_info.append(f"Creating Sales Invoice for mutation {mutation_id}")

                    # Create Sales Invoice
                    si = frappe.new_doc("Sales Invoice")
                    si.company = company
                    si.posting_date = mutation.get("date")

                    # Set proper title and naming based on eBoekhouden data
                    invoice_number = mutation.get("invoiceNumber")
                    if invoice_number:
                        si.title = f"eBoekhouden {invoice_number}"
                        # Store eBoekhouden invoice number in custom field if it exists
                        if hasattr(si, "eboekhouden_invoice_number"):
                            si.eboekhouden_invoice_number = invoice_number
                    else:
                        si.title = f"eBoekhouden Import {mutation_id}"

                    # Store eBoekhouden mutation ID for reference
                    if hasattr(si, "eboekhouden_mutation_id"):
                        si.eboekhouden_mutation_id = mutation_id

                    # Try to find customer from relation_id
                    relation_id = mutation.get("relationId")
                    customer = _get_or_create_customer(relation_id, debug_info)
                    si.customer = customer

                    debug_info.append(f"Customer set to: {customer}, rows: {len(rows)}")

                    # Process each row as a separate line item
                    if rows and len(rows) > 0:
                        for idx, row in enumerate(rows):
                            row_amount = frappe.utils.flt(row.get("amount", 0), 2)
                            row_ledger_id = row.get("ledgerId")
                            row_description = row.get("description", description)

                            # Skip rows with zero amount
                            if row_amount == 0:
                                continue

                            # Add item line using smart tegenrekening mapping
                            try:
                                line_dict = create_invoice_line_for_tegenrekening(
                                    tegenrekening_code=str(row_ledger_id) if row_ledger_id else None,
                                    amount=abs(row_amount),  # Use absolute value for invoice lines
                                    description=row_description,
                                    transaction_type="sales",
                                )
                                if line_dict and isinstance(line_dict, dict):
                                    # Validate income account exists
                                    if line_dict.get("income_account"):
                                        # Check if income account exists
                                        if not frappe.db.exists("Account", line_dict["income_account"]):
                                            debug_info.append(
                                                f"Income account {line_dict['income_account']} not found, using fallback"
                                            )
                                            # Get any income account
                                            fallback_account = frappe.db.get_value(
                                                "Account",
                                                {
                                                    "company": company,
                                                    "account_type": "Income Account",
                                                    "is_group": 0,
                                                },
                                                "name",
                                            )
                                            if fallback_account:
                                                line_dict["income_account"] = fallback_account
                                            else:
                                                line_dict[
                                                    "income_account"
                                                ] = "80005 - Donaties - direct op bankrekening - NVV"
                                    si.append("items", line_dict)
                                else:
                                    debug_info.append(
                                        f"Smart mapping returned invalid result for row {idx}: {line_dict}"
                                    )
                                    # Fallback to basic item
                                    si.append(
                                        "items",
                                        {
                                            "item_code": "E-Boekhouden Import Item",
                                            "qty": 1,
                                            "rate": abs(row_amount),
                                            "description": row_description,
                                        },
                                    )
                            except Exception as e:
                                debug_info.append(f"Smart mapping error for row {idx}: {str(e)}")
                                # Fallback to basic item
                                si.append(
                                    "items",
                                    {
                                        "item_code": "E-Boekhouden Import Item",
                                        "qty": 1,
                                        "rate": abs(row_amount),
                                        "description": row_description,
                                    },
                                )
                    else:
                        # No rows found, use total amount as single line
                        debug_info.append(f"No rows found, using total amount: {amount}")
                        si.append(
                            "items",
                            {
                                "item_code": "E-Boekhouden Import Item",
                                "qty": 1,
                                "rate": abs(amount),
                                "description": description,
                            },
                        )

                    # Save and submit
                    si.save()
                    si.submit()
                    imported += 1
                    debug_info.append(f"Successfully created Sales Invoice for mutation {mutation_id}")

                elif mutation_type in [3, 4]:  # Payment Entries (Customer/Supplier Payments)
                    # Check if this is a multi-line payment (split payment, overpayment, etc.)
                    if len(rows) > 1:
                        debug_info.append(
                            f"Multi-line payment mutation {mutation_id} - creating Journal Entry instead"
                        )

                        # Create Journal Entry for complex payment
                        je = frappe.new_doc("Journal Entry")
                        je.company = company
                        je.posting_date = mutation.get("date")
                        je.user_remark = f"E-Boekhouden REST Import - Payment Mutation {mutation_id} (Type {mutation_type})"
                        je.voucher_type = "Journal Entry"

                        # Set proper title based on eBoekhouden data
                        invoice_number = mutation.get("invoiceNumber")
                        if invoice_number:
                            je.title = f"eBoekhouden Payment {invoice_number}"
                        else:
                            je.title = f"eBoekhouden Payment {mutation_id}"

                        # Store eBoekhouden references in custom fields if they exist
                        if hasattr(je, "eboekhouden_mutation_id"):
                            je.eboekhouden_mutation_id = mutation_id
                        if hasattr(je, "eboekhouden_invoice_number") and invoice_number:
                            je.eboekhouden_invoice_number = invoice_number

                        # Add invoice reference if available
                        if invoice_number:
                            je.user_remark += f" - Invoice: {invoice_number}"
                            # Try to find matching invoice for reconciliation
                            matching_invoice = frappe.db.get_value(
                                "Purchase Invoice", {"bill_no": invoice_number}, "name"
                            ) or frappe.db.get_value("Sales Invoice", {"name": invoice_number}, "name")
                            if matching_invoice:
                                debug_info.append(
                                    f"Found matching invoice {matching_invoice} for payment reconciliation"
                                )

                        relation_id = mutation.get("relationId")
                        total_debit = 0
                        total_credit = 0

                        for row in rows:
                            row_amount = frappe.utils.flt(row.get("amount", 0), 2)
                            row_ledger_id = row.get("ledgerId")
                            row_description = row.get("description", description)

                            # Skip rows with zero amount
                            if row_amount == 0:
                                continue

                            # Get account mapping for this row
                            row_account = None
                            row_party_type = None
                            row_party = None

                            if row_ledger_id:
                                # Check ledger mapping
                                mapping = frappe.db.get_value(
                                    "E-Boekhouden Ledger Mapping",
                                    {"ledger_id": str(row_ledger_id)},
                                    ["erpnext_account"],
                                    as_dict=True,
                                )

                                if mapping and mapping.get("erpnext_account"):
                                    row_account = mapping["erpnext_account"]

                                    # Check if it's a receivable/payable account
                                    account_type = frappe.db.get_value("Account", row_account, "account_type")

                                    if account_type == "Receivable" and relation_id:
                                        row_party_type = "Customer"
                                        row_party = _get_or_create_customer(relation_id, debug_info)
                                    elif account_type == "Payable" and relation_id:
                                        row_party_type = "Supplier"
                                        row_party = _get_or_create_supplier(relation_id, debug_info)

                            # If no account found, use smart mapping
                            if not row_account:
                                line_dict = create_invoice_line_for_tegenrekening(
                                    tegenrekening_code=str(row_ledger_id) if row_ledger_id else None,
                                    amount=abs(row_amount),
                                    description=row_description,
                                    transaction_type="purchase" if mutation_type == 4 else "sales",
                                )
                                row_account = line_dict.get(
                                    "expense_account" if mutation_type == 4 else "income_account"
                                ) or _get_bank_account(company)

                            # Create journal entry line
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
                                            f"Linked payment journal entry line to {invoice_doctype} {matching_invoice}"
                                        )

                            je.append("accounts", entry_line)

                            # Track totals for balance validation
                            total_debit += entry_line["debit_in_account_currency"]
                            total_credit += entry_line["credit_in_account_currency"]

                        # Check if balanced
                        debug_info.append(
                            f"Payment JE total debit: {total_debit}, total credit: {total_credit}"
                        )
                        if abs(total_debit - total_credit) > 0.01:
                            debug_info.append(
                                f"WARNING: Payment journal entry not balanced! Difference: {total_debit - total_credit}"
                            )

                        je.save()
                        je.submit()
                        imported += 1
                        debug_info.append(
                            f"Successfully created Journal Entry for multi-line payment mutation {mutation_id}"
                        )

                    else:
                        # Single line payment - create standard Payment Entry
                        debug_info.append(f"Creating Payment Entry for mutation {mutation_id}")

                        # Create Payment Entry
                        pe = frappe.new_doc("Payment Entry")
                        pe.company = company
                        pe.posting_date = mutation.get("date")
                        pe.paid_amount = abs(amount)  # Use absolute value
                        pe.received_amount = abs(amount)
                        pe.reference_no = mutation.get("invoiceNumber", f"EBH-{mutation_id}")
                        pe.reference_date = mutation.get("date")

                        # Set proper title based on eBoekhouden data
                        invoice_number = mutation.get("invoiceNumber")
                        if invoice_number:
                            pe.title = f"eBoekhouden Payment {invoice_number}"
                        else:
                            pe.title = f"eBoekhouden Payment {mutation_id}"

                        # Store eBoekhouden references in custom fields if they exist
                        if hasattr(pe, "eboekhouden_mutation_id"):
                            pe.eboekhouden_mutation_id = mutation_id
                        if hasattr(pe, "eboekhouden_invoice_number") and invoice_number:
                            pe.eboekhouden_invoice_number = invoice_number

                        relation_id = mutation.get("relationId")

                        if mutation_type == 3:  # Customer Payment
                            pe.payment_type = "Receive"
                            pe.party_type = "Customer"
                            customer = _get_or_create_customer(relation_id, debug_info)
                            pe.party = customer
                        else:  # Supplier Payment
                            pe.payment_type = "Pay"
                            pe.party_type = "Supplier"
                            supplier = _get_or_create_supplier(relation_id, debug_info)
                            pe.party = supplier

                        # Set bank account (default cash account)
                        if pe.payment_type == "Receive":  # Customer Payment
                            pe.paid_from = _get_receivable_account(company)
                            pe.paid_to = _get_bank_account(company)
                        else:  # Supplier Payment
                            pe.paid_from = _get_bank_account(company)
                            pe.paid_to = _get_payable_account(company)

                        pe.save()
                        pe.submit()
                        imported += 1
                        debug_info.append(f"Successfully created Payment Entry for mutation {mutation_id}")

                else:  # Journal Entries (Money Received/Sent, General)
                    debug_info.append(
                        f"Creating Journal Entry for mutation {mutation_id} (Type {mutation_type})"
                    )

                    # Check if this is a type 7 with invoice number and relation - might be better as invoice
                    invoice_number = mutation.get("invoiceNumber")
                    relation_id = mutation.get("relationId")

                    if mutation_type == 7 and invoice_number and relation_id:
                        debug_info.append(
                            f"Type 7 mutation with invoice {invoice_number} and relation {relation_id} - checking account type"
                        )

                    je = frappe.new_doc("Journal Entry")
                    je.company = company
                    je.posting_date = mutation.get("date")
                    je.user_remark = (
                        f"E-Boekhouden REST Import - Mutation {mutation_id} (Type {mutation_type})"
                    )
                    je.voucher_type = "Journal Entry"

                    # Set proper title based on eBoekhouden data
                    invoice_number = mutation.get("invoiceNumber")
                    if invoice_number:
                        je.title = f"eBoekhouden {invoice_number}"
                    else:
                        # Give more descriptive names based on mutation type
                        type_names = {5: "Money Received", 6: "Money Sent", 7: "Memoriaal"}
                        type_name = type_names.get(mutation_type, "Import")
                        je.title = f"eBoekhouden {type_name} {mutation_id}"

                    # Store eBoekhouden references in custom fields if they exist
                    if hasattr(je, "eboekhouden_mutation_id"):
                        je.eboekhouden_mutation_id = mutation_id
                    if hasattr(je, "eboekhouden_invoice_number") and invoice_number:
                        je.eboekhouden_invoice_number = invoice_number

                    # Add invoice reference if available
                    if invoice_number:
                        je.user_remark += f" - Invoice: {invoice_number}"
                        # Try to find matching invoice for reconciliation
                        if relation_id:
                            # Look for existing Purchase/Sales Invoice with this bill_no/name
                            matching_invoice = frappe.db.get_value(
                                "Purchase Invoice", {"bill_no": invoice_number}, "name"
                            ) or frappe.db.get_value("Sales Invoice", {"name": invoice_number}, "name")
                            if matching_invoice:
                                debug_info.append(
                                    f"Found matching invoice {matching_invoice} for reconciliation"
                                )

                    # Check if this is a multi-line journal entry
                    if len(rows) > 1:
                        # Multi-line journal entry - process each row separately
                        debug_info.append(f"Multi-line journal entry with {len(rows)} rows")
                        total_debit = 0
                        total_credit = 0

                        for row in rows:
                            row_amount = frappe.utils.flt(row.get("amount", 0), 2)
                            row_ledger_id = row.get("ledgerId")
                            row_description = row.get("description", description)

                            # Get account mapping for this row
                            row_account = None
                            row_party_type = None
                            row_party = None

                            if row_ledger_id:
                                # Check ledger mapping
                                mapping = frappe.db.get_value(
                                    "E-Boekhouden Ledger Mapping",
                                    {"ledger_id": str(row_ledger_id)},
                                    ["erpnext_account"],
                                    as_dict=True,
                                )

                                if mapping and mapping.get("erpnext_account"):
                                    row_account = mapping["erpnext_account"]

                                    # Check if it's a receivable/payable account
                                    account_type = frappe.db.get_value("Account", row_account, "account_type")

                                    if account_type == "Receivable" and relation_id:
                                        row_party_type = "Customer"
                                        row_party = _get_or_create_customer(relation_id, debug_info)
                                    elif account_type == "Payable" and relation_id:
                                        row_party_type = "Supplier"
                                        row_party = _get_or_create_supplier(relation_id, debug_info)

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

                            # Create journal entry line
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

                        # Check if balanced
                        debug_info.append(f"Total debit: {total_debit}, Total credit: {total_credit}")
                        if abs(total_debit - total_credit) > 0.01:
                            debug_info.append(
                                f"WARNING: Journal entry not balanced! Difference: {total_debit - total_credit}"
                            )

                    else:
                        # Single line entry - create a two-line entry with bank as contra
                        # Get the actual account from ledger mapping
                        account_to_use = None
                        party_type = None
                        party = None

                        if ledger_id:
                            # Check ledger mapping to get the actual account
                            mapping = frappe.db.get_value(
                                "E-Boekhouden Ledger Mapping",
                                {"ledger_id": str(ledger_id)},
                                ["erpnext_account"],
                                as_dict=True,
                            )

                            if mapping and mapping.get("erpnext_account"):
                                account_to_use = mapping["erpnext_account"]

                                # Check if it's a receivable/payable account
                                account_type = frappe.db.get_value("Account", account_to_use, "account_type")
                                debug_info.append(f"Account {account_to_use} has type: {account_type}")

                                if account_type == "Receivable":
                                    party_type = "Customer"
                                    party = _get_or_create_customer(relation_id, debug_info)
                                elif account_type == "Payable":
                                    party_type = "Supplier"
                                    party = _get_or_create_supplier(relation_id, debug_info)

                        # If no account found, use smart mapping as fallback
                        if not account_to_use:
                            line_dict = create_invoice_line_for_tegenrekening(
                                tegenrekening_code=str(ledger_id) if ledger_id else None,
                                amount=abs(amount),
                                description=description,
                                transaction_type="purchase",
                            )
                            account_to_use = (
                                line_dict.get("expense_account") or "44009 - Onvoorziene kosten - NVV"
                            )

                        # Use proper precision
                        amount = frappe.utils.flt(amount, 2)

                        # Create balanced journal entry - handle negative amounts
                        # For negative amounts, flip debit/credit
                        if amount > 0:
                            first_debit = amount
                            first_credit = 0
                            second_debit = 0
                            second_credit = amount
                        else:
                            first_debit = 0
                            first_credit = abs(amount)
                            second_debit = abs(amount)
                            second_credit = 0

                        first_entry = {
                            "account": account_to_use,
                            "debit_in_account_currency": first_debit,
                            "credit_in_account_currency": first_credit,
                            "cost_center": cost_center,
                            "user_remark": description,
                        }

                        # Add party details if needed
                        if party_type and party:
                            first_entry["party_type"] = party_type
                            first_entry["party"] = party

                        je.append("accounts", first_entry)

                        # Second entry (bank/contra account)
                        je.append(
                            "accounts",
                            {
                                "account": _get_bank_account(company),
                                "debit_in_account_currency": second_debit,
                                "credit_in_account_currency": second_credit,
                                "cost_center": cost_center,
                                "user_remark": description,
                            },
                        )

                    je.save()
                    je.submit()
                    imported += 1
                    debug_info.append(f"Successfully created Journal Entry for mutation {mutation_id}")

        except Exception as e:
            mutation_id = mutation.get("id", "unknown")
            error_msg = f"Failed to import mutation {mutation_id}: {str(e)}"
            errors.append(error_msg)
            debug_info.append(f"ERROR importing mutation {mutation_id}: {str(e)}")
            # Use very short log title to avoid length issues
            log_title = f"Mut {mutation_id}"[:50]  # Ensure title is max 50 chars
            # Only log first 500 chars of error to avoid nested length issues
            frappe.log_error(error_msg[:500], log_title)

    debug_info.append(f"Completed batch - Imported: {imported}, Failed: {len(errors)}")
    frappe.log_error("BATCH Log:\n" + "\n".join(debug_info), "REST Batch Debug")

    return {"imported": imported, "failed": len(errors), "errors": errors}


def _get_or_create_supplier(relation_id, debug_info):
    """Get or create supplier for mutation"""
    supplier = None

    # Try to find existing supplier with this relation_id
    if relation_id:
        # First, try to find existing supplier with this relation_id
        supplier = frappe.db.get_value("Supplier", {"custom_eboekhouden_relation_id": relation_id}, "name")

        if supplier:
            debug_info.append(f"Found existing supplier for relation {relation_id}: {supplier}")
            return supplier

        # If not found, try to fetch supplier data from eBoekhouden API
        try:
            from .eboekhouden_api import EBoekhoudenAPI

            api = EBoekhoudenAPI()

            # Make API call to get specific relation
            result = api.make_request(f"v1/relations/{relation_id}")

            if result and result.get("success") and result.get("status_code") == 200:
                relation_data = json.loads(result.get("data", "{}"))

                # Extract supplier name from API response
                supplier_name = None
                if relation_data.get("companyName"):
                    supplier_name = relation_data.get("companyName")
                elif relation_data.get("contactName"):
                    supplier_name = relation_data.get("contactName")
                elif relation_data.get("name"):
                    supplier_name = relation_data.get("name")

                if supplier_name:
                    # Create supplier with proper name
                    supplier_doc = frappe.new_doc("Supplier")
                    supplier_doc.supplier_name = supplier_name[:140]  # Limit length
                    supplier_doc.supplier_group = "All Supplier Groups"

                    # Store eBoekhouden relation ID for future reference
                    if hasattr(supplier_doc, "custom_eboekhouden_relation_id"):
                        supplier_doc.custom_eboekhouden_relation_id = relation_id

                    # Add additional details if available
                    if relation_data.get("email"):
                        supplier_doc.email_id = relation_data.get("email")

                    supplier_doc.save(ignore_permissions=True)
                    supplier = supplier_doc.name
                    debug_info.append(f"Created supplier from eBoekhouden API: {supplier_name}")
                    return supplier

        except Exception as e:
            debug_info.append(f"Failed to fetch relation {relation_id} from API: {str(e)}")

    # Fallback: Create/use default supplier
    supplier = frappe.db.get_value("Supplier", {"supplier_name": "E-Boekhouden Import"}, "name")

    if not supplier:
        # Create default supplier
        supplier_doc = frappe.new_doc("Supplier")
        supplier_doc.supplier_name = "E-Boekhouden Import"
        supplier_doc.supplier_group = "All Supplier Groups"
        supplier_doc.save(ignore_permissions=True)
        supplier = supplier_doc.name
        debug_info.append(f"Created default supplier: {supplier}")

    return supplier


def _get_or_create_customer(relation_id, debug_info):
    """Get or create customer for mutation"""
    customer = None

    # Try to find existing customer with this relation_id
    if relation_id:
        # First, try to find existing customer with this relation_id
        customer = frappe.db.get_value("Customer", {"custom_eboekhouden_relation_id": relation_id}, "name")

        if customer:
            debug_info.append(f"Found existing customer for relation {relation_id}: {customer}")
            return customer

        # If not found, try to fetch customer data from eBoekhouden API
        try:
            from .eboekhouden_api import EBoekhoudenAPI

            api = EBoekhoudenAPI()

            # Make API call to get specific relation
            result = api.make_request(f"v1/relations/{relation_id}")

            if result and result.get("success") and result.get("status_code") == 200:
                relation_data = json.loads(result.get("data", "{}"))

                # Extract customer name from API response
                customer_name = None
                if relation_data.get("companyName"):
                    customer_name = relation_data.get("companyName")
                elif relation_data.get("contactName"):
                    customer_name = relation_data.get("contactName")
                elif relation_data.get("name"):
                    customer_name = relation_data.get("name")

                if customer_name:
                    # Create customer with proper name
                    customer_doc = frappe.new_doc("Customer")
                    customer_doc.customer_name = customer_name[:140]  # Limit length
                    customer_doc.customer_group = "All Customer Groups"

                    # Store eBoekhouden relation ID for future reference
                    if hasattr(customer_doc, "custom_eboekhouden_relation_id"):
                        customer_doc.custom_eboekhouden_relation_id = relation_id

                    # Add additional details if available
                    if relation_data.get("email"):
                        customer_doc.email_id = relation_data.get("email")

                    customer_doc.save(ignore_permissions=True)
                    customer = customer_doc.name
                    debug_info.append(f"Created customer from eBoekhouden API: {customer_name}")
                    return customer

        except Exception as e:
            debug_info.append(f"Failed to fetch relation {relation_id} from API: {str(e)}")

    # Fallback: Create/use default customer
    customer = frappe.db.get_value("Customer", {"customer_name": "E-Boekhouden Import"}, "name")

    if not customer:
        # Create default customer
        customer_doc = frappe.new_doc("Customer")
        customer_doc.customer_name = "E-Boekhouden Import"
        customer_doc.customer_group = "All Customer Groups"
        customer_doc.save(ignore_permissions=True)
        customer = customer_doc.name
        debug_info.append(f"Created default customer: {customer}")

    return customer


def _get_bank_account(company):
    """Get bank account for company"""
    bank_account = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
    )

    if not bank_account:
        # Fallback to cash account
        bank_account = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
        )

    return bank_account or "1100 - Kas - NVV"  # Final fallback


def _get_receivable_account(company):
    """Get receivable account for company"""
    receivable_account = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
    )

    return receivable_account or "1300 - Debiteuren - NVV"  # Fallback


def _get_payable_account(company):
    """Get payable account for company (needed for Purchase Invoice credit_to)"""
    payable_account = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Payable", "is_group": 0}, "name"
    )

    return payable_account or "1600 - Crediteuren - NVV"  # Fallback


def map_rest_type_to_soap_type(rest_type):
    """Map REST API mutation types to SOAP type names"""
    type_mapping = {
        0: "Opening",
        1: "FactuurOntvangen",
        2: "FactuurVerstuurd",
        3: "FactuurBetaaldOntvangen",
        4: "FactuurBetaaldVerstuurd",
        5: "GeldOntvangen",
        6: "GeldVerstuurd",
        7: "Memoriaal",
    }
    return type_mapping.get(rest_type, "Unknown")


@frappe.whitelist()
def check_fiscal_years():
    """Check fiscal years configuration"""
    try:
        years = frappe.db.sql(
            """
            SELECT name, year_start_date, year_end_date, disabled
            FROM `tabFiscal Year`
            ORDER BY year_start_date
        """,
            as_dict=True,
        )

        return {"success": True, "fiscal_years": years, "count": len(years)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_accounts_and_items():
    """Check account mapping and item existence"""
    try:
        # Check if the account field exists
        account_fields = frappe.db.sql(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabAccount'
            AND COLUMN_NAME IN ('eboekhouden_grootboek_nummer', 'account_number')
        """,
            as_dict=True,
        )

        # Check for the expense account that's failing
        expense_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, eboekhouden_grootboek_nummer, account_number
            FROM `tabAccount`
            WHERE account_name LIKE '%Kostprijs omzet grondstoffen%'
            AND company = 'Ned Ver Vegan'
        """,
            as_dict=True,
        )

        # Check if E-Boekhouden Import Item exists
        import_item = frappe.db.get_value(
            "Item", "E-Boekhouden Import Item", ["name", "item_name"], as_dict=True
        )

        # Check item groups
        item_groups = frappe.db.sql(
            """
            SELECT name FROM `tabItem Group`
            WHERE name IN ('E-Boekhouden Import', 'Revenue Items', 'Expense Items')
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "account_fields": account_fields,
            "expense_accounts": expense_accounts,
            "import_item": import_item,
            "item_groups": item_groups,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_ledger_mappings():
    """Debug what accounts the failing ledger IDs map to"""
    try:
        # Check specific ledger IDs from failing mutations
        ledger_ids = ["13201901", "13201974", "13201876"]
        results = []

        for ledger_id in ledger_ids:
            # Check by eboekhouden_grootboek_nummer
            account_by_ebh = frappe.db.get_value(
                "Account",
                {"company": "Ned Ver Vegan", "eboekhouden_grootboek_nummer": ledger_id},
                ["name", "account_name", "account_type"],
                as_dict=True,
            )

            # Check by account_number
            account_by_num = frappe.db.get_value(
                "Account",
                {"company": "Ned Ver Vegan", "account_number": ledger_id},
                ["name", "account_name", "account_type"],
                as_dict=True,
            )

            # Check E-Boekhouden Item Mapping
            item_mapping = frappe.db.get_value(
                "E-Boekhouden Item Mapping",
                {"account_code": ledger_id},
                ["name", "item_code", "account_name"],
                as_dict=True,
            )

            # Also check if there's an item with this code
            item_exists = frappe.db.exists("Item", f"EB-{ledger_id}")

            results.append(
                {
                    "ledger_id": ledger_id,
                    "account_by_eboekhouden": account_by_ebh,
                    "account_by_number": account_by_num,
                    "item_mapping": item_mapping,
                    "item_exists": item_exists,
                }
            )

        return {"success": True, "ledger_mappings": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_existing_chart_of_accounts():
    """Check existing chart of accounts"""
    try:
        # Get all expense accounts
        expense_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_number, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND account_type = 'Expense Account'
            AND is_group = 0
            ORDER BY account_number, name
        """,
            as_dict=True,
        )

        # Get all income accounts
        income_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_number, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND account_type = 'Income Account'
            AND is_group = 0
            ORDER BY account_number, name
        """,
            as_dict=True,
        )

        # Get specific accounts that might be referenced
        specific_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, account_number, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND (account_name LIKE '%kostprijs%'
                 OR account_name LIKE '%omzet%'
                 OR account_name LIKE '%grondstoffen%'
                 OR account_name LIKE '%algemene%')
            ORDER BY name
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "expense_accounts": expense_accounts,
            "income_accounts": income_accounts,
            "specific_accounts": specific_accounts,
            "expense_count": len(expense_accounts),
            "income_count": len(income_accounts),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_mutation_account_mapping():
    """Debug what accounts are being looked up for mutations"""
    try:
        # Get some sample mutations from cache to debug
        sample_mutations = frappe.db.sql(
            """
            SELECT mutation_id, mutation_data
            FROM `tabEBoekhouden REST Mutation Cache`
            WHERE mutation_type IN (1, 2)
            LIMIT 5
        """,
            as_dict=True,
        )

        if not sample_mutations:
            return {"success": False, "error": "No cached mutations found"}

        results = []
        for mutation in sample_mutations:
            data = json.loads(mutation["mutation_data"])

            # Get ledger IDs from rows
            rows = data.get("rows", [])
            for row in rows:
                ledger_id = row.get("ledgerId")
                if ledger_id:
                    # Check if account exists
                    account_by_ebh = frappe.db.get_value(
                        "Account",
                        {"company": "Ned Ver Vegan", "eboekhouden_grootboek_nummer": str(ledger_id)},
                        ["name", "account_name"],
                        as_dict=True,
                    )

                    account_by_num = frappe.db.get_value(
                        "Account",
                        {"company": "Ned Ver Vegan", "account_number": str(ledger_id)},
                        ["name", "account_name"],
                        as_dict=True,
                    )

                    results.append(
                        {
                            "mutation_id": mutation["mutation_id"],
                            "ledger_id": ledger_id,
                            "description": row.get("description", ""),
                            "account_by_eboekhouden": account_by_ebh,
                            "account_by_number": account_by_num,
                        }
                    )

        # Also get existing accounts with these fields
        accounts_with_mapping = frappe.db.sql(
            """
            SELECT name, account_name, account_number, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND (eboekhouden_grootboek_nummer IS NOT NULL
                 OR account_number IS NOT NULL)
            LIMIT 10
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "mutation_mappings": results,
            "existing_mapped_accounts": accounts_with_mapping,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def find_kostprijs_reference():
    """Find where 'Kostprijs omzet grondstoffen' is referenced"""
    try:
        results = {}

        # Check E-Boekhouden Account Mapping
        try:
            mappings = frappe.get_all(
                "E-Boekhouden Account Mapping", fields=["name", "account_code", "erpnext_account"], limit=50
            )
            results["account_mappings"] = mappings
        except Exception:
            results["account_mappings"] = []

        # Check if any accounts have this name
        accounts = frappe.db.sql(
            """
            SELECT name, account_name, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE account_name LIKE '%Kostprijs%omzet%'
               OR account_name LIKE '%grondstoffen%'
        """,
            as_dict=True,
        )
        results["accounts"] = accounts

        # Check Items
        items = frappe.db.sql(
            """
            SELECT i.name, i.item_name, ida.expense_account, ida.income_account
            FROM `tabItem` i
            LEFT JOIN `tabItem Default` ida ON ida.parent = i.name
            WHERE ida.expense_account LIKE '%Kostprijs%'
               OR ida.expense_account LIKE '%grondstoffen%'
               OR i.name IN ('EB-13201901', 'EB-13201974', 'EB-13201876')
        """,
            as_dict=True,
        )
        results["items"] = items

        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_eboekhouden_mappings():
    """Check E-Boekhouden Item Mappings"""
    try:
        # Check all mappings
        mappings = frappe.db.sql(
            """
            SELECT
                name,
                account_code,
                account_name,
                item_code,
                transaction_type
            FROM `tabE-Boekhouden Item Mapping`
            WHERE company = 'Ned Ver Vegan'
            LIMIT 20
        """,
            as_dict=True,
        )

        # Check for specific problematic account names
        problematic = frappe.db.sql(
            """
            SELECT
                name,
                account_code,
                account_name,
                item_code
            FROM `tabE-Boekhouden Item Mapping`
            WHERE account_name LIKE '%Kostprijs%'
               OR account_name LIKE '%grondstoffen%'
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "mappings": mappings,
            "problematic_mappings": problematic,
            "total_mappings": frappe.db.count("E-Boekhouden Item Mapping", {"company": "Ned Ver Vegan"}),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_item_expense_accounts():
    """Check items and their expense accounts"""
    try:
        # Check items that might have been created
        items = frappe.db.sql(
            """
            SELECT
                i.name as item_code,
                i.item_name,
                i.item_group,
                ida.expense_account
            FROM `tabItem` i
            LEFT JOIN `tabItem Default` ida ON ida.parent = i.name AND ida.company = 'Ned Ver Vegan'
            WHERE i.name LIKE 'EB-%'
               OR i.name LIKE '%Boekhouden%'
            LIMIT 20
        """,
            as_dict=True,
        )

        # Also check if any items have the problematic account name
        problematic_items = frappe.db.sql(
            """
            SELECT
                i.name as item_code,
                ida.expense_account
            FROM `tabItem` i
            JOIN `tabItem Default` ida ON ida.parent = i.name
            WHERE ida.expense_account LIKE '%Kostprijs%omzet%grondstoffen%'
        """,
            as_dict=True,
        )

        return {"success": True, "items": items, "problematic_items": problematic_items}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_specific_mutations():
    """Debug specific failing mutations to see raw data"""
    try:
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Fetch the specific mutations that are failing
        failing_ids = [273, 460, 461]
        debug_info = []

        for mutation_id in failing_ids:
            try:
                mutation = iterator.fetch_mutation_detail(mutation_id)
                if mutation:
                    debug_info.append(
                        {
                            "mutation_id": mutation_id,
                            "raw_data": mutation,
                            "rows": mutation.get("rows", []),
                            "ledger_ids": [row.get("ledgerId") for row in mutation.get("rows", [])],
                        }
                    )
            except Exception as e:
                debug_info.append({"mutation_id": mutation_id, "error": str(e)})

        return {"success": True, "mutations": debug_info}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_single_mutation():
    """Test importing a single mutation step by step"""
    try:
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get mutation 491 which imported successfully
        mutation = iterator.fetch_mutation_detail(491)
        if not mutation:
            return {"success": False, "error": "Could not fetch mutation 491"}

        # Try to create the invoice
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Extract data
        mutation_type = mutation.get("type")  # Should be 3 (payment)
        rows = mutation.get("rows", [])
        ledger_id = rows[0].get("ledgerId") if rows else None
        amount = abs(float(rows[0].get("amount", 0))) if rows else 0
        description = mutation.get("description", "")

        result = {
            "mutation_data": {
                "id": mutation.get("id"),
                "type": mutation_type,
                "ledger_id": ledger_id,
                "amount": amount,
                "description": description[:50],
            }
        }

        # Create smart mapper
        from verenigingen.utils.smart_tegenrekening_mapper import SmartTegenrekeningMapper

        mapper = SmartTegenrekeningMapper(company)

        # Get item mapping
        item_mapping = mapper.get_item_for_tegenrekening(
            str(ledger_id) if ledger_id else None,
            description,
            "purchase",  # Type 3 is payment received, but we process as purchase
            amount,
        )

        result["item_mapping"] = item_mapping

        # Check if item exists
        if item_mapping and item_mapping.get("item_code"):
            item_exists = frappe.db.exists("Item", item_mapping["item_code"])
            result["item_exists"] = item_exists

            if item_exists:
                item = frappe.get_doc("Item", item_mapping["item_code"])
                result["item_defaults"] = []
                for default in item.item_defaults:
                    result["item_defaults"].append(
                        {
                            "company": default.company,
                            "expense_account": default.expense_account,
                            "income_account": default.income_account,
                        }
                    )

        return {"success": True, "result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_single_mutation_batch():
    """Test importing a single mutation using the batch import function"""
    try:
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get just mutation 273
        mutation = iterator.fetch_mutation_detail(273)
        if not mutation:
            return {"success": False, "error": "Could not fetch mutation 273"}

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Import using the exact same function as the batch import
        result = _import_rest_mutations_batch("TEST-SINGLE", [mutation], settings)

        return {
            "success": True,
            "result": result,
            "mutation_tested": {
                "id": mutation.get("id"),
                "type": mutation.get("type"),
                "description": mutation.get("description")[:50],
            },
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_partial_migration():
    """Test migration with just a few transactions to debug issues"""
    try:
        # Import the REST iterator to fetch some test mutations
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Fetch a small batch of mutations for testing
        test_mutations = []
        debug_log = []

        # Try to fetch specific mutations that were failing
        failing_ids = [273, 460, 461, 491]  # From the error messages

        for mutation_id in failing_ids:
            try:
                mutation = iterator.fetch_mutation_detail(mutation_id)
                if mutation:
                    test_mutations.append(mutation)
                    debug_log.append(
                        f"Fetched mutation {mutation_id}: {mutation.get('description', 'No description')[:50]}"
                    )
                else:
                    debug_log.append(f"Could not fetch mutation {mutation_id}")
            except Exception as e:
                debug_log.append(f"Error fetching mutation {mutation_id}: {str(e)}")

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Try to import these test mutations
        if test_mutations:
            debug_log.append(f"\nAttempting to import {len(test_mutations)} test mutations...")
            result = _import_rest_mutations_batch("TEST-MIGRATION", test_mutations, settings)
            debug_log.append(f"Import result: {result}")
        else:
            debug_log.append("No test mutations could be fetched")

        return {"success": True, "debug_log": debug_log, "mutations_tested": len(test_mutations)}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def fix_item_expense_accounts():
    """Fix items that don't have expense/income accounts configured"""
    try:
        company = "Ned Ver Vegan"
        fixes = []
        errors = []

        # Get all EB- items without expense accounts
        items_to_fix = frappe.db.sql(
            """
            SELECT DISTINCT i.name as item_code, i.item_group, i.is_purchase_item, i.is_sales_item
            FROM `tabItem` i
            LEFT JOIN `tabItem Default` ida ON ida.parent = i.name AND ida.company = %(company)s
            WHERE i.name LIKE 'EB-%%'
            AND (ida.name IS NULL OR (ida.expense_account IS NULL AND i.is_purchase_item = 1))
        """,
            {"company": company},
            as_dict=True,
        )

        for item_data in items_to_fix:
            try:
                item = frappe.get_doc("Item", item_data.item_code)

                # Extract account code from item code (e.g., "EB-13201901" -> "13201901")
                account_code = item_data.item_code.replace("EB-", "")

                # Try to find matching account
                account = frappe.db.get_value(
                    "Account", {"company": company, "eboekhouden_grootboek_nummer": account_code}, "name"
                )

                if not account:
                    account = frappe.db.get_value(
                        "Account", {"company": company, "account_number": account_code}, "name"
                    )

                # If no specific account found, use generic fallback
                if not account:
                    if item_data.is_purchase_item:
                        account = "44009 - Onvoorziene kosten - NVV"
                    elif item_data.is_sales_item:
                        account = "80005 - Donaties - direct op bankrekening - NVV"
                    else:
                        continue  # Skip if neither purchase nor sales item

                # Check if item default exists
                existing_default = False
                for default in item.item_defaults:
                    if default.company == company:
                        existing_default = True
                        if item_data.is_purchase_item and not default.expense_account:
                            default.expense_account = account
                        if item_data.is_sales_item and not default.income_account:
                            default.income_account = account
                        break

                if not existing_default:
                    # Add new item default
                    item.append(
                        "item_defaults",
                        {
                            "company": company,
                            "expense_account": account if item_data.is_purchase_item else None,
                            "income_account": account if item_data.is_sales_item else None,
                        },
                    )

                item.save()
                fixes.append(f"Fixed {item_data.item_code} with account {account}")

            except Exception as e:
                errors.append(f"Failed to fix {item_data.item_code}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "fixes_applied": fixes,
            "errors": errors,
            "summary": f"Fixed {len(fixes)} items, {len(errors)} errors",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_problematic_items():
    """Check if problematic items exist"""
    try:
        items = []
        for ledger_id in ["13201901", "13201974", "13201876"]:
            item_code = f"EB-{ledger_id}"
            if frappe.db.exists("Item", item_code):
                item = frappe.get_doc("Item", item_code)
                item_info = {"item_code": item_code, "item_name": item.item_name, "defaults": []}
                for default in item.item_defaults:
                    item_info["defaults"].append(
                        {
                            "company": default.company,
                            "expense_account": default.expense_account,
                            "income_account": default.income_account,
                        }
                    )
                items.append(item_info)

        return {"success": True, "items": items}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_invoice_line_creation():
    """Test what the smart mapper returns for problematic ledger"""
    try:
        from verenigingen.utils.smart_tegenrekening_mapper import create_invoice_line_for_tegenrekening

        # Test for the failing mutations
        line_dict = create_invoice_line_for_tegenrekening(
            tegenrekening_code="13201901",
            amount=168.96,
            description="restitutie greenhost",
            transaction_type="sales",
        )

        return {"success": True, "line_dict": line_dict}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def trace_single_mutation_import():
    """Trace the import of a single problematic mutation step by step"""
    try:
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get mutation 273
        mutation = iterator.fetch_mutation_detail(273)
        if not mutation:
            return {"success": False, "error": "Could not fetch mutation 273"}

        trace = {
            "mutation_data": mutation,
            "mutation_type": mutation.get("type"),
            "is_sales_invoice": mutation.get("type") == 2,
            "steps": [],
        }

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Extract data
        rows = mutation.get("rows", [])
        ledger_id = rows[0].get("ledgerId") if rows else None
        amount = abs(float(rows[0].get("amount", 0))) if rows else 0

        trace["ledger_id"] = ledger_id
        trace["amount"] = amount

        # Test smart mapping
        from verenigingen.utils.smart_tegenrekening_mapper import create_invoice_line_for_tegenrekening

        line_dict = create_invoice_line_for_tegenrekening(
            tegenrekening_code=str(ledger_id) if ledger_id else None,
            amount=amount,
            description=mutation.get("description", ""),
            transaction_type="sales",  # Type 2 is sales
        )

        trace["line_dict"] = line_dict
        trace["steps"].append("Created line dict with smart mapper")

        # Try to create the invoice
        try:
            si = frappe.new_doc("Sales Invoice")
            si.company = company
            si.posting_date = mutation.get("date")
            si.customer = "E-Boekhouden Import"

            trace["steps"].append("Created Sales Invoice document")

            # Add the line
            si.append("items", line_dict)
            trace["steps"].append("Added item line to invoice")

            # Try to save
            si.save()
            trace["steps"].append("Invoice saved successfully!")
            trace["invoice_created"] = si.name

        except Exception as e:
            trace["error_at_save"] = str(e)
            trace["steps"].append(f"Error during save: {str(e)}")

        return {"success": True, "trace": trace}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_direct_invoice_creation():
    """Test creating a sales invoice directly"""
    try:
        company = "Ned Ver Vegan"

        # Create a simple sales invoice
        si = frappe.new_doc("Sales Invoice")
        si.company = company
        si.posting_date = "2019-09-24"
        si.customer = "E-Boekhouden Import"  # Default customer

        # Add the item we just created
        si.append(
            "items",
            {"item_code": "EB-13201901", "qty": 1, "rate": 168.96, "description": "Test direct creation"},
        )

        # Try to save
        si.save()

        return {"success": True, "invoice": si.name}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def prepare_items_for_migration():
    """Pre-create items for the problematic ledger IDs"""
    try:
        company = "Ned Ver Vegan"
        created = []

        # The problematic ledger IDs from the failing mutations
        # These are all from Sales Invoices (type 2), so they need income accounts
        ledger_mappings = {
            "13201901": "80005 - Donaties - direct op bankrekening - NVV",  # Income account
            "13201974": "80005 - Donaties - direct op bankrekening - NVV",  # Income account
            "13201876": "80005 - Donaties - direct op bankrekening - NVV",  # Income account
        }

        for ledger_id, account in ledger_mappings.items():
            item_code = f"EB-{ledger_id}"

            if not frappe.db.exists("Item", item_code):
                # Create the item
                item = frappe.new_doc("Item")
                item.item_code = item_code
                item.item_name = f"E-Boekhouden Import {ledger_id}"
                item.item_group = "E-Boekhouden Import"
                item.stock_uom = "Nos"
                item.is_stock_item = 0

                # Determine if sales or purchase based on account type
                if "Donaties" in account or "Income" in account:
                    item.is_sales_item = 1
                    item.is_purchase_item = 0
                else:
                    item.is_sales_item = 0
                    item.is_purchase_item = 1

                # Add item default with proper account
                item.append(
                    "item_defaults",
                    {
                        "company": company,
                        "expense_account": account if item.is_purchase_item else None,
                        "income_account": account if item.is_sales_item else None,
                    },
                )

                item.insert(ignore_permissions=True)
                created.append(item_code)

        frappe.db.commit()
        return {"success": True, "created": created}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def clear_problematic_items():
    """Clear items that might have wrong account references"""
    try:
        # Find items with ledger IDs that don't have matching accounts
        problematic_ledgers = ["13201901", "13201974", "13201876"]
        deleted = []

        for ledger_id in problematic_ledgers:
            item_code = f"EB-{ledger_id}"
            if frappe.db.exists("Item", item_code):
                # Delete the item
                frappe.delete_doc("Item", item_code, force=True)
                deleted.append(item_code)

        frappe.db.commit()
        return {"success": True, "message": f"Cleared items: {deleted}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_migration_prerequisites():
    """Fix prerequisites for migration - fiscal years, accounts, and items"""
    try:
        errors = []
        fixes = []

        # 1. Create missing fiscal years (2019-2024)
        for year in range(2019, 2025):
            if not frappe.db.exists("Fiscal Year", str(year)):
                try:
                    fy = frappe.new_doc("Fiscal Year")
                    fy.year = str(year)
                    fy.year_start_date = f"{year}-01-01"
                    fy.year_end_date = f"{year}-12-31"
                    fy.disabled = 0
                    fy.insert(ignore_permissions=True)
                    fixes.append(f"Created fiscal year {year}")
                except Exception as e:
                    errors.append(f"Failed to create fiscal year {year}: {str(e)}")

        # 2. Create the missing E-Boekhouden Import Item
        if not frappe.db.exists("Item", "E-Boekhouden Import Item"):
            try:
                item = frappe.new_doc("Item")
                item.item_code = "E-Boekhouden Import Item"
                item.item_name = "E-Boekhouden Import Item"
                item.item_group = "E-Boekhouden Import"
                item.stock_uom = "Nos"
                item.is_stock_item = 0
                item.is_sales_item = 1
                item.is_purchase_item = 1
                item.insert(ignore_permissions=True)
                fixes.append("Created E-Boekhouden Import Item")
            except Exception as e:
                errors.append(f"Failed to create import item: {str(e)}")

        # 3. Create generic expense accounts if missing
        company = "Ned Ver Vegan"

        # Check if we need to create a generic expense account
        expense_account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_type": "Expense Account",
                "account_name": "Algemene kosten",
                "is_group": 0,
            },
            "name",
        )

        if not expense_account:
            # Try to find any expense account
            expense_account = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Expense Account", "is_group": 0}, "name"
            )

            if expense_account:
                fixes.append(f"Using existing expense account: {expense_account}")
            else:
                errors.append("No expense accounts found for company")

        frappe.db.commit()

        return {
            "success": True,
            "fixes_applied": fixes,
            "errors": errors,
            "summary": f"Applied {len(fixes)} fixes, {len(errors)} errors",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

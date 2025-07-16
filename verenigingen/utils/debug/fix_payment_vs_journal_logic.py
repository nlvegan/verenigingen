#!/usr/bin/env python3
"""
Fix the payment vs journal entry logic to create Payment Entries for same-party payments
"""

import frappe


@frappe.whitelist()
def fix_payment_logic():
    """Fix the logic to create Payment Entries for same-party multi-invoice payments"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the problematic logic
    old_logic = """                        # If we have multiple receivable/payable rows, this might be multi-party payment
                        # In such cases, create Journal Entry as it's more flexible
                        if len(receivable_payable_rows) > 1:
                            debug_info.append(
                                "Multi-party payment mutation {mutation_id} - creating Journal Entry for {len(receivable_payable_rows)} parties"
                            )
                        else:
                            debug_info.append(
                                "Multi-line payment mutation {mutation_id} - creating Journal Entry instead"
                            )"""

    new_logic = """                        # Check if this is truly a multi-party payment or same-party multi-invoice payment
                        unique_parties = set()
                        account_types = set()

                        for account_type, row in receivable_payable_rows:
                            # For supplier payments, check if we have a relationId (single party)
                            if relation_id:
                                unique_parties.add(relation_id)
                            account_types.add(account_type)

                        # If we have multiple rows but single party and single account type, this is multi-invoice payment
                        # ERPNext Payment Entries can handle this perfectly
                        if len(receivable_payable_rows) > 1 and len(unique_parties) <= 1 and len(account_types) == 1:
                            debug_info.append(
                                "Same-party multi-invoice payment mutation {mutation_id} - should create Payment Entry for {len(receivable_payable_rows)} invoices"
                            )
                            # Set flag to create Payment Entry instead of Journal Entry
                            create_payment_entry = True
                        elif len(receivable_payable_rows) > 1:
                            debug_info.append(
                                "Multi-party payment mutation {mutation_id} - creating Journal Entry for {len(receivable_payable_rows)} parties"
                            )
                            create_payment_entry = False
                        else:
                            debug_info.append(
                                "Multi-line payment mutation {mutation_id} - creating Journal Entry instead"
                            )
                            create_payment_entry = False"""

    # Replace the logic
    content = content.replace(old_logic, new_logic)

    # Now we need to add the condition to actually create Payment Entry
    # Find the Journal Entry creation section and add the condition
    old_creation = """                        # Check if already imported
                        already_imported, existing_doc = _check_if_already_imported(mutation_id, "Journal Entry")
                        if already_imported:
                            debug_info.append(f"Skipping mutation {mutation_id} - already imported as {existing_doc}")
                            continue

                        # Create Journal Entry for complex payment
                        je = frappe.new_doc("Journal Entry")"""

    new_creation = """                        # Check if we should create Payment Entry instead of Journal Entry
                        if create_payment_entry:
                            # Create Payment Entry for same-party multi-invoice payment
                            debug_info.append(f"Creating Payment Entry for same-party multi-invoice mutation {mutation_id}")

                            # Check if already imported
                            already_imported, existing_doc = _check_if_already_imported(mutation_id, "Payment Entry")
                            if already_imported:
                                debug_info.append(f"Skipping mutation {mutation_id} - already imported as {existing_doc}")
                                continue

                            # Create Payment Entry
                            pe = frappe.new_doc("Payment Entry")
                            pe.company = company
                            pe.posting_date = posting_date
                            pe.payment_type = "Pay" if receivable_payable_rows[0][0] == "Payable" else "Receive"

                            # Set party from relation
                            if relation_id:
                                if pe.payment_type == "Pay":
                                    supplier = _get_or_create_supplier(relation_id, description, debug_info)
                                    if supplier:
                                        pe.party_type = "Supplier"
                                        pe.party = supplier
                                else:
                                    customer = _get_or_create_customer(relation_id, description, debug_info)
                                    if customer:
                                        pe.party_type = "Customer"
                                        pe.party = customer

                            # Calculate total payment amount
                            total_payment = sum(abs(frappe.utils.flt(row.get("amount", 0), 2)) for _, row in receivable_payable_rows)
                            pe.paid_amount = total_payment
                            pe.received_amount = total_payment

                            # Set bank account from main ledger
                            if pe.payment_type == "Pay":
                                pe.paid_from = _get_bank_account(company)
                                pe.paid_to = _get_payable_account(company)
                            else:
                                pe.paid_from = _get_receivable_account(company)
                                pe.paid_to = _get_bank_account(company)

                            # Set reference details
                            invoice_number = mutation.get("invoiceNumber")
                            if invoice_number:
                                pe.reference_no = invoice_number
                                pe.reference_date = posting_date

                            # Store eBoekhouden references
                            if hasattr(pe, "eboekhouden_mutation_nr"):
                                pe.eboekhouden_mutation_nr = mutation_id
                            if hasattr(pe, "eboekhouden_mutation_type"):
                                pe.eboekhouden_mutation_type = str(mutation_type)

                            # Add remarks
                            pe.user_remark = f"E-Boekhouden REST Import - Multi-invoice payment {mutation_id}"

                            try:
                                pe.save(ignore_permissions=True)
                                pe.submit()
                                debug_info.append(f"Successfully created Payment Entry for mutation {mutation_id}")
                                imported += 1
                            except Exception as e:
                                debug_info.append(f"Failed to create Payment Entry for mutation {mutation_id}: {str(e)}")
                                # Fall back to Journal Entry
                                create_payment_entry = False

                            if create_payment_entry:
                                continue  # Skip Journal Entry creation

                        # Check if already imported as Journal Entry
                        already_imported, existing_doc = _check_if_already_imported(mutation_id, "Journal Entry")
                        if already_imported:
                            debug_info.append(f"Skipping mutation {mutation_id} - already imported as {existing_doc}")
                            continue

                        # Create Journal Entry for complex payment
                        je = frappe.new_doc("Journal Entry")"""

    content = content.replace(old_creation, new_creation)

    # Write the fixed content back
    with open(file_path, "w") as f:
        f.write(content)

    print("Fixed payment vs journal entry logic:")
    print("1. Now checks for same-party multi-invoice payments")
    print("2. Creates Payment Entries for same-party multi-invoice payments")
    print("3. Only creates Journal Entries for truly multi-party payments")
    print("4. Falls back to Journal Entry if Payment Entry creation fails")

    return {"success": True}


@frappe.whitelist()
def analyze_journal_entries_that_should_be_payments():
    """Analyze existing Journal Entries that should have been Payment Entries"""

    # Find Journal Entries that look like payments
    journal_payments = frappe.db.sql(
        """
        SELECT
            je.name,
            je.posting_date,
            je.title,
            je.eboekhouden_mutation_nr,
            COUNT(jea.name) as line_count,
            COUNT(DISTINCT jea.party) as unique_parties,
            COUNT(DISTINCT jea.account) as unique_accounts
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
        WHERE je.eboekhouden_mutation_nr IS NOT NULL
        AND je.title LIKE '%Payment%'
        GROUP BY je.name
        HAVING unique_parties = 1 AND line_count > 1
        ORDER BY je.posting_date DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    print(f"\nFound {len(journal_payments)} Journal Entries that might should be Payment Entries:")

    for jp in journal_payments:
        print(f"\n{jp.name} (Mutation {jp.eboekhouden_mutation_nr}):")
        print(f"  Date: {jp.posting_date}")
        print(f"  Title: {jp.title}")
        print(f"  Lines: {jp.line_count}, Parties: {jp.unique_parties}, Accounts: {jp.unique_accounts}")

        # Get the account details
        accounts = frappe.db.sql(
            """
            SELECT account, debit, credit, party_type, party
            FROM `tabJournal Entry Account`
            WHERE parent = %s
            ORDER BY idx
        """,
            jp.name,
            as_dict=True,
        )

        for acc in accounts:
            print(f"    {acc.account}: Dr {acc.debit} Cr {acc.credit} [{acc.party_type} {acc.party}]")

    return {"count": len(journal_payments), "entries": journal_payments}


if __name__ == "__main__":
    print("Fix payment vs journal entry logic")

"""
Complete SEPA Integration Setup and Testing
"""

import frappe


@frappe.whitelist()
def complete_sepa_integration_setup():
    """Complete setup of SEPA integration including test data"""
    try:
        setup_results = []

        # Step 1: Ensure custom fields are created (skip SEPA Direct Debit Batch fields for now)
        try:
            from verenigingen.setup.sepa_custom_fields import create_custom_fields

            # Bank Transaction fields
            bank_transaction_fields = [
                {
                    "fieldname": "custom_sepa_batch",
                    "label": "SEPA Batch",
                    "fieldtype": "Link",
                    "options": "SEPA Direct Debit Batch",
                    "insert_after": "bank_account",
                }
            ]

            # Only create if not exists
            existing = frappe.db.exists(
                "Custom Field", {"dt": "Bank Transaction", "fieldname": "custom_sepa_batch"}
            )
            if not existing:
                create_custom_fields("Bank Transaction", bank_transaction_fields)
                setup_results.append("Created Bank Transaction custom fields")
            else:
                setup_results.append("Bank Transaction custom fields already exist")

        except Exception as e:
            setup_results.append(f"Custom fields setup error: {str(e)}")

        # Step 2: Test the SEPA reconciliation functions
        try:
            from verenigingen.api.sepa_reconciliation import get_sepa_reconciliation_dashboard

            dashboard_test = get_sepa_reconciliation_dashboard()

            if dashboard_test.get("success"):
                setup_results.append("SEPA reconciliation API functions working")
            else:
                setup_results.append(f"SEPA API test failed: {dashboard_test.get('error', 'Unknown error')}")

        except Exception as e:
            setup_results.append(f"SEPA API test error: {str(e)}")

        # Step 3: Create minimal test data
        try:
            from verenigingen.api.sepa_test_data import create_sepa_test_scenario

            test_result = create_sepa_test_scenario()

            if test_result.get("success"):
                setup_results.append("Test data created successfully")
                setup_results.append(f"Created test SEPA batch: {test_result['test_data']['sepa_batch']}")
            else:
                setup_results.append(
                    f"Test data creation failed: {test_result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            setup_results.append(f"Test data creation error: {str(e)}")

        # Step 4: Test identification workflow
        try:
            from verenigingen.api.sepa_reconciliation import identify_sepa_transactions

            identify_result = identify_sepa_transactions()

            if identify_result.get("success"):
                match_count = identify_result.get("total_found", 0)
                setup_results.append(
                    f"Transaction identification working - found {match_count} potential matches"
                )
            else:
                setup_results.append(
                    f"Transaction identification failed: {identify_result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            setup_results.append(f"Transaction identification error: {str(e)}")

        return {
            "success": True,
            "setup_results": setup_results,
            "message": "SEPA integration setup completed with detailed results",
        }

    except Exception as e:
        frappe.log_error(f"Error in complete SEPA integration setup: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_sepa_workflow_step_by_step():
    """Test SEPA workflow step by step with detailed logging"""
    try:
        workflow_steps = []

        # Step 1: Check existing data
        existing_batches = frappe.get_all("SEPA Direct Debit Batch", limit=5)
        existing_transactions = frappe.get_all("Bank Transaction", limit=5)

        workflow_steps.append(
            {
                "step": "Data Check",
                "result": f"Found {len(existing_batches)} SEPA batches and {len(existing_transactions)} bank transactions",
            }
        )

        # Step 2: Identify potential matches
        from verenigingen.api.sepa_reconciliation import identify_sepa_transactions

        identify_result = identify_sepa_transactions()

        workflow_steps.append(
            {
                "step": "Identification",
                "result": identify_result,
                "success": identify_result.get("success", False),
            }
        )

        # Step 3: If we have matches, try to process one
        if identify_result.get("success") and identify_result.get("potential_matches"):
            match = identify_result["potential_matches"][0]

            if match.get("matching_batches"):
                batch_match = match["matching_batches"][0]

                # Try conservative processing
                from verenigingen.api.sepa_reconciliation import process_sepa_transaction_conservative

                process_result = process_sepa_transaction_conservative(
                    match["bank_transaction"], batch_match["batch_name"]
                )

                workflow_steps.append(
                    {
                        "step": "Processing",
                        "result": process_result,
                        "success": process_result.get("success", False),
                    }
                )

        # Step 4: Check dashboard data
        from verenigingen.api.sepa_reconciliation import get_sepa_reconciliation_dashboard

        dashboard_result = get_sepa_reconciliation_dashboard()

        workflow_steps.append(
            {
                "step": "Dashboard",
                "result": dashboard_result,
                "success": dashboard_result.get("success", False),
            }
        )

        return {
            "success": True,
            "workflow_steps": workflow_steps,
            "message": "Step-by-step workflow test completed",
        }

    except Exception as e:
        frappe.log_error(f"Error in step-by-step SEPA workflow test: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def quick_sepa_demo():
    """Quick demo of SEPA reconciliation capabilities"""
    try:
        demo_results = []

        # 1. Show current state
        recent_batches = frappe.get_all(
            "SEPA Direct Debit Batch",
            filters={"creation": [">=", "2024-01-01"]},
            fields=["name", "total_amount", "status"],
            limit=3,
        )

        recent_transactions = frappe.get_all(
            "Bank Transaction",
            filters={"date": [">=", "2024-01-01"]},
            fields=["name", "description", "deposit", "custom_sepa_batch"],
            limit=5,
        )

        demo_results.append(
            {"title": "Current Data", "batches": recent_batches, "transactions": recent_transactions}
        )

        # 2. Demonstrate identification
        sepa_keywords = ["sepa", "dd", "direct debit", "incasso", "batch"]
        potential_sepa = []

        for txn in recent_transactions:
            description_lower = txn.description.lower()
            if any(keyword in description_lower for keyword in sepa_keywords):
                potential_sepa.append(txn)

        demo_results.append(
            {
                "title": "SEPA Detection Logic",
                "keywords_searched": sepa_keywords,
                "potential_matches": potential_sepa,
            }
        )

        # 3. Show reconciliation statuses
        linked_transactions = [txn for txn in recent_transactions if txn.get("custom_sepa_batch")]
        unlinked_transactions = [txn for txn in recent_transactions if not txn.get("custom_sepa_batch")]

        demo_results.append(
            {
                "title": "Reconciliation Status",
                "linked_count": len(linked_transactions),
                "unlinked_count": len(unlinked_transactions),
                "linked_transactions": linked_transactions,
            }
        )

        # 4. Show available actions
        available_actions = [
            "identify_sepa_transactions() - Find unmatched SEPA transactions",
            "process_sepa_transaction_conservative() - Process full/partial matches",
            "correlate_return_transactions() - Find return transactions",
            "process_sepa_return_file() - Process bank return files",
            "manual_sepa_reconciliation() - Handle complex cases",
        ]

        demo_results.append({"title": "Available Actions", "actions": available_actions})

        return {
            "success": True,
            "demo_results": demo_results,
            "message": "SEPA reconciliation demo completed",
            "next_steps": [
                "Visit /sepa_reconciliation_dashboard for web interface",
                "Use the API functions for automated processing",
                "Upload return files for failed payment handling",
            ],
        }

    except Exception as e:
        frappe.log_error(f"Error in SEPA demo: {str(e)}")
        return {"success": False, "error": str(e)}

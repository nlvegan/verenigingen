#!/usr/bin/env python3
"""
Test API for renamed core file imports
"""

import frappe


@frappe.whitelist()
def test_renamed_file_imports():
    """Test that all renamed core files can be imported"""

    test_cases = [
        (
            "SEPA Processor",
            "verenigingen.verenigingen.doctype.direct_debit_batch.sepa_processor",
            "SEPAProcessor",
        ),
        ("SEPA Validator", "verenigingen.utils.sepa_validator", "validate_sepa_integration"),
        (
            "Dues Schedule Manager",
            "verenigingen.verenigingen.doctype.membership.dues_schedule_manager",
            "sync_membership_with_dues_schedule",
        ),
        ("Payment History Subscriber", "verenigingen.events.subscribers.payment_history_subscriber", None),
        (
            "eBoekhouden Payment Import",
            "verenigingen.utils.eboekhouden.eboekhouden_payment_import",
            "create_payment_entry",
        ),
        (
            "eBoekhouden COA Import",
            "verenigingen.utils.eboekhouden.eboekhouden_coa_import",
            "coa_import_with_bank_accounts",
        ),
    ]

    results = []

    for name, module_path, function_name in test_cases:
        try:
            module = frappe.get_module(module_path)

            if function_name:
                func = getattr(module, function_name)
                results.append(f"✓ {name}: Module and function '{function_name}' imported successfully")
            else:
                results.append(f"✓ {name}: Module imported successfully")

        except ImportError as e:
            results.append(f"✗ {name}: Import failed - {e}")
        except AttributeError as e:
            results.append(f"✗ {name}: Function not found - {e}")
        except Exception as e:
            results.append(f"✗ {name}: Unexpected error - {e}")

    # Summary
    success_count = sum(1 for r in results if r.startswith("✓"))
    total_count = len(results)

    output = [
        "=" * 60,
        "RENAMED FILE IMPORT TEST RESULTS",
        "=" * 60,
    ]

    output.extend(results)

    output.extend(["", "=" * 60, f"SUMMARY: {success_count}/{total_count} files imported successfully"])

    if success_count == total_count:
        output.append("🎉 All renamed core files are working correctly!")
        success = True
    else:
        output.append("⚠️  Some renamed files have import issues")
        success = False

    # Print to server log
    for line in output:
        frappe.logger().info(line)

    return {
        "success": success,
        "results": results,
        "summary": f"{success_count}/{total_count} files imported successfully",
    }

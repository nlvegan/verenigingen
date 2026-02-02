# verenigungen/setup/critical_operation_rules_setup.py
"""
Setup Critical Operation Rules during app installation.

This module loads COR fixtures only during initial app install,
preventing migrations from overwriting user customizations to
rate limits, required roles, etc.

New rules can be added to fixture files and will be created if
they don't exist, but existing rules won't be modified.
"""

import json
from pathlib import Path

import frappe


def setup_critical_operation_rules():
    """
    Import Critical Operation Rules from fixture files.

    Only creates rules that don't already exist, preserving any
    user customizations to existing rules.
    """
    print("  Setting up Critical Operation Rules...")

    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_files = [
        "critical_operation_rule.json",
        "critical_operation_rule_ponto_debug.json",
        "critical_operation_rule_balance_transactions.json",
        "critical_operation_rule_payment_recovery.json",
    ]

    created_count = 0
    skipped_count = 0
    errors = []

    for fixture_file in fixture_files:
        fixture_path = fixtures_dir / fixture_file
        if not fixture_path.exists():
            print(f"    Fixture file not found: {fixture_file}")
            continue

        try:
            with open(fixture_path, "r") as f:
                rules = json.load(f)

            for rule_data in rules:
                rule_name = rule_data.get("name")
                if not rule_name:
                    continue

                # Check if rule already exists
                if frappe.db.exists("Critical Operation Rule", rule_name):
                    skipped_count += 1
                    continue

                # Create new rule
                try:
                    doc = frappe.get_doc(rule_data)
                    doc.insert(ignore_permissions=True)
                    created_count += 1
                except Exception as e:
                    errors.append(f"{rule_name}: {str(e)}")

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {fixture_file}: {str(e)}")
        except Exception as e:
            errors.append(f"Error reading {fixture_file}: {str(e)}")

    # Commit the changes
    if created_count > 0:
        frappe.db.commit()

    print(f"    Created {created_count} new rules, skipped {skipped_count} existing")

    if errors:
        print(f"    Errors: {len(errors)}")
        for error in errors[:5]:  # Show first 5 errors
            print(f"      - {error}")

    return {
        "created": created_count,
        "skipped": skipped_count,
        "errors": errors,
    }


def add_missing_critical_operation_rules():
    """
    Add any missing Critical Operation Rules from fixture files.

    This can be called manually or via a patch to add new rules
    without affecting existing ones.

    Usage:
        bench --site your-site execute \
            verenigingen.setup.critical_operation_rules_setup.add_missing_critical_operation_rules
    """
    return setup_critical_operation_rules()

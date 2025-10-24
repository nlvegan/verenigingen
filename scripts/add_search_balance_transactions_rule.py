#!/usr/bin/env python3
"""
Add search_balance_transactions critical operation rule to fixtures
"""

import json
import sys
from pathlib import Path

# Path to fixtures file
fixtures_path = Path(__file__).parent.parent / "verenigingen" / "fixtures" / "critical_operation_rule.json"

# New rule to add
new_rule = {
    "doctype": "Critical Operation Rule",
    "name": "search_balance_transactions",
    "operation_name": "search_balance_transactions",
    "operation_type": "financial",
    "description": "Mollie debug page endpoint for searching balance transactions by description",
    "enabled": 1,
    "security_level": "high",
    "business_context": "Debug page search functionality for balance transaction descriptions",
    "required_roles": "System Manager\nVerenigingen Administrator",
    "rate_limit_calls": 100,
    "rate_limit_period_seconds": 3600,
    "rate_limit_scope": "per_user",
    "audit_level": "standard",
    "alert_on_execution": 0
}

def main():
    print(f"Reading fixtures from: {fixtures_path}")

    # Load existing fixtures
    with open(fixtures_path, 'r') as f:
        fixtures = json.load(f)

    print(f"Loaded {len(fixtures)} existing rules")

    # Check if rule already exists
    existing = [r for r in fixtures if r.get("name") == "search_balance_transactions"]
    if existing:
        print(f"✅ Rule 'search_balance_transactions' already exists")
        return 0

    # Add new rule
    fixtures.append(new_rule)
    print(f"✅ Added new rule 'search_balance_transactions'")

    # Save updated fixtures
    with open(fixtures_path, 'w') as f:
        json.dump(fixtures, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved {len(fixtures)} rules to fixtures file")
    print("\nNext step: Import fixtures with:")
    print("  bench --site dev.veganisme.net import-doc /home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/critical_operation_rule.json")

    return 0

if __name__ == "__main__":
    sys.exit(main())

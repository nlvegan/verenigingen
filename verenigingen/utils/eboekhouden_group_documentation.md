# E-Boekhouden API: Retrieving Custom Group Names

## Overview

The E-Boekhouden API does provide custom group names for accounts through the `/v1/ledger` endpoint. Each account in the response includes a `group` field that contains the custom group identifier/name.

## API Response Structure

When calling the chart of accounts endpoint:
```python
api.get_chart_of_accounts()  # GET /v1/ledger
```

Each account in the response contains:
```json
{
  "id": 13201873,
  "code": "13500",
  "description": "Te ontvangen contributies",
  "category": "DEB",
  "group": "004"  // Custom group name/identifier
}
```

## Available Groups in Test Environment

From the API test, we found 18 unique groups:
- **Group 004**: Receivables/Debtors (6 accounts) - "Te ontvangen" accounts
- **Group 007**: Personnel costs (6 accounts) - Salary and social charges
- **Group 014**: Project costs (10 accounts) - Various project expenses
- **Group 024**: Vegan Magazine costs (9 accounts)
- **Group 028**: VeganChallenge costs (7 accounts)
- **Group 040**: General expenses (12 accounts) - Insurance, donations, etc.
- And 12 more groups...

## Key Findings

1. **Groups are Returned**: The API successfully returns the `group` field for each account
2. **Group Format**: Groups appear to be numeric codes (e.g., "004", "007", "040")
3. **Logical Grouping**: Accounts are logically grouped (e.g., all receivables in group "004")
4. **No Group Names**: The groups are identifiers, not descriptive names

## Using Groups for Account Categorization

### Example: Finding All Receivable Accounts
```python
# All accounts in group "004" are receivables
group_004_accounts = [
    {"code": "13500", "description": "Te ontvangen contributies"},
    {"code": "13510", "description": "Te ontvangen donaties"},
    {"code": "13600", "description": "Te ontvangen rente"},
    {"code": "13900", "description": "Te ontvangen bedragen"},
    # etc.
]
```

### Mapping Groups to ERPNext Account Types
Based on the account descriptions and categories within each group, you can create mappings:

```python
group_to_erpnext_type = {
    "004": "Current Asset",      # Receivables ("Te ontvangen")
    "007": "Expense",           # Personnel costs
    "014": "Expense",           # Project costs
    "040": "Expense",           # General expenses
    "002": "Current Asset",     # Cash/Bank accounts
    "006": "Current Liability", # Payables
    # etc.
}
```

## Implementation Example

```python
def categorize_accounts_by_group(accounts):
    """
    Categorize accounts based on their E-Boekhouden group
    """
    group_mappings = {
        "004": {"erpnext_type": "Current Asset", "description": "Receivables"},
        "007": {"erpnext_type": "Expense", "description": "Personnel Costs"},
        "014": {"erpnext_type": "Expense", "description": "Project Costs"},
        # Add more mappings based on your analysis
    }

    categorized = {}
    for account in accounts:
        group = account.get("group", "")
        if group in group_mappings:
            account["suggested_type"] = group_mappings[group]["erpnext_type"]
            account["group_description"] = group_mappings[group]["description"]
        categorized.setdefault(group, []).append(account)

    return categorized
```

## Recommendations

1. **Use Groups for Bulk Categorization**: During migration, use the group field to automatically assign ERPNext account types to similar accounts.

2. **Manual Review Required**: Since groups are numeric codes without descriptive names, you'll need to:
   - Analyze a few accounts in each group to understand its purpose
   - Create a mapping table for your specific chart of accounts
   - Review and adjust the automated assignments

3. **Store Group Information**: Consider storing the original E-Boekhouden group in a custom field in ERPNext for reference.

4. **Dynamic Group Discovery**: The test script `test_eboekhouden_groups.py` provides functions to:
   - Retrieve all unique groups
   - Find all accounts in a specific group
   - Analyze group characteristics
   - Suggest ERPNext account types based on group content

## Conclusion

Yes, the E-Boekhouden API does provide custom group information through the `group` field. While these are numeric identifiers rather than descriptive names, they can still be very useful for:
- Bulk categorization during migration
- Understanding the account structure
- Maintaining consistency when mapping to ERPNext account types

The groups appear to be logically organized (e.g., all receivables in one group, all personnel costs in another), making them valuable for automated account type assignment during migration.

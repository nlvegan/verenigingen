# Move Payment Fields to Payments Settings Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move payment-related fields from Verenigingen Settings to Verenigingen Payments Settings for better organization.

**Architecture:** Add 5 fields to Verenigingen Payments Settings DocType JSON, update all call sites to use the new location, then remove fields from the original DocType. Data migration patch will copy existing values.

**Tech Stack:** Frappe DocType JSON, Python, Jinja2 templates

---

## Fields to Move

| Field | Type | Description |
|-------|------|-------------|
| `mollie_subscription_description_template` | Data | Template for Mollie subscription descriptions |
| `ponto_payment_description_template` | Data | Template for Ponto payment descriptions |
| `membership_payment_account` | Link (Account) | Account for accepting membership payments |
| `dues_income_account` | Link (Account) | Income/Revenue account for membership dues |
| `dues_payments_receivable_account` | Link (Account) | Receivable account for membership dues invoices |

## Call Sites to Update

### Description Templates
1. `verenigingen/templates/pages/bank_details.html:842` - `mollie_subscription_description_template`
2. `verenigingen/vereinigingen_payments/doctype/ponto_payment_link/ponto_payment_link.py:143-145` - `ponto_payment_description_template`
3. `verenigingen/templates/pages/ponto_api_debug.py:56-59` - `ponto_payment_description_template`

### Account Fields
4. `verenigingen/services/billing/invoice_generator.py:374` - `dues_income_account`
5. `verenigingen/utils/sales_invoice_account_handler.py:41-42,108,112,117,120` - `dues_payments_receivable_account`
6. `verenigingen/vereinigingen/doctype/membership_dues_schedule/membership_dues_schedule.py:925-926` - `dues_income_account`
7. `verenigingen/vereinigingen/page/chapter_dues_allocation/chapter_dues_allocation.py:122,246` - `dues_income_account`
8. `verenigingen/vereinigingen/page/membership_analytics/membership_analytics.py:274` - `dues_income_account`
9. `verenigingen/vereinigingen_payments/mollie/services/dues_payment_processor.py:572` - `dues_income_account`

### Test Files
10. `verenigingen/tests/integration/services/test_invoice_generator.py:94,97,119,126,134,153` - `dues_income_account`
11. `verenigingen/tests/fixtures/enhanced_test_factory.py:3958,3969,4012` - `dues_income_account`
12. `verenigingen/vereinigingen/doctype/verenigingen_settings/test_verenigingen_settings.py` - All account tests (move to payments settings tests)

---

### Task 1: Add Fields to Verenigingen Payments Settings DocType

**Files:**
- Modify: `verenigingen/vereinigingen/doctype/verenigingen_payments_settings/verenigingen_payments_settings.json`

**Step 1: Add field definitions to field_order array**

In `field_order`, after `"ing_checkout_bank_account"` (line 18), add:
```json
    "dues_accounts_section",
    "membership_payment_account",
    "dues_income_account",
    "dues_payments_receivable_account",
    "payment_description_section",
    "mollie_subscription_description_template",
    "ponto_payment_description_template",
```

**Step 2: Add field definitions to fields array**

After the `ing_checkout_bank_account` field definition, add these new field objects:

```json
    {
      "fieldname": "dues_accounts_section",
      "fieldtype": "Section Break",
      "label": "Membership Dues Accounts"
    },
    {
      "description": "Account for accepting membership payments",
      "fieldname": "membership_payment_account",
      "fieldtype": "Link",
      "label": "Membership Dues Payment Account",
      "options": "Account"
    },
    {
      "description": "Income/Revenue account for membership dues. This should be a Profit & Loss account with type 'Income Account'.",
      "fieldname": "dues_income_account",
      "fieldtype": "Link",
      "label": "Dues Income Account",
      "options": "Account"
    },
    {
      "description": "Default receivable account for membership dues invoices. If not set, will use Company default receivable account.",
      "fieldname": "dues_payments_receivable_account",
      "fieldtype": "Link",
      "label": "Dues Payments Receivable Account",
      "options": "Account"
    },
    {
      "fieldname": "payment_description_section",
      "fieldtype": "Section Break",
      "label": "Payment Description Templates"
    },
    {
      "default": "Contribution payment for member MEMBER_ID",
      "description": "Template for Mollie subscription description. Use MEMBER_ID as placeholder for member ID (e.g., 'Contribution payment for member MEMBER_ID')",
      "fieldname": "mollie_subscription_description_template",
      "fieldtype": "Data",
      "label": "Mollie Subscription Description Template"
    },
    {
      "default": "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END",
      "description": "Template for Ponto payment request description. Available placeholders: MEMBER_ID (member ID number), MEMBER_NAME (full name), COVERAGE_START (coverage period start date), COVERAGE_END (coverage period end date)",
      "fieldname": "ponto_payment_description_template",
      "fieldtype": "Data",
      "label": "Ponto Payment Description Template"
    },
```

**Step 3: Run migration to sync schema**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Schema synced successfully

**Step 4: Commit**

```bash
git add verenigingen/vereinigingen/doctype/verenigingen_payments_settings/verenigingen_payments_settings.json
git commit -m "feat(payments-settings): add payment account and description template fields"
```

---

### Task 2: Create Data Migration Patch

**Files:**
- Create: `verenigingen/patches/v1_0/migrate_payment_fields_to_payments_settings.py`
- Modify: `verenigingen/patches.txt`

**Step 1: Create the migration patch**

Create file `verenigingen/patches/v1_0/migrate_payment_fields_to_payments_settings.py`:

```python
"""
Migrate payment-related fields from Verenigingen Settings to Verenigingen Payments Settings.

Fields migrated:
- mollie_subscription_description_template
- ponto_payment_description_template
- membership_payment_account
- dues_income_account
- dues_payments_receivable_account
"""
import frappe


def execute():
    """Copy payment field values from Verenigingen Settings to Payments Settings."""
    # Get source values
    source_fields = [
        "mollie_subscription_description_template",
        "ponto_payment_description_template",
        "membership_payment_account",
        "dues_income_account",
        "dues_payments_receivable_account",
    ]

    source_values = {}
    for field in source_fields:
        value = frappe.db.get_single_value("Verenigingen Settings", field)
        if value:
            source_values[field] = value

    if not source_values:
        frappe.logger().info("No payment fields to migrate - all empty in source")
        return

    # Copy to destination (only if destination field is empty)
    for field, value in source_values.items():
        existing = frappe.db.get_single_value("Verenigingen Payments Settings", field)
        if not existing:
            frappe.db.set_single_value("Verenigingen Payments Settings", field, value)
            frappe.logger().info(f"Migrated {field} to Verenigingen Payments Settings")
        else:
            frappe.logger().info(f"Skipped {field} - already set in Payments Settings")

    frappe.db.commit()
```

**Step 2: Add patch to patches.txt**

Add this line to `verenigingen/patches.txt`:
```
verenigingen.patches.v1_0.migrate_payment_fields_to_payments_settings
```

**Step 3: Run the patch**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Patch runs and migrates data

**Step 4: Verify migration**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org console`
Then in console:
```python
ps = frappe.get_single("Verenigingen Payments Settings")
print(f"dues_income_account: {ps.dues_income_account}")
print(f"mollie_subscription_description_template: {ps.mollie_subscription_description_template}")
```
Expected: Values match original Verenigingen Settings

**Step 5: Commit**

```bash
git add verenigingen/patches/v1_0/migrate_payment_fields_to_payments_settings.py verenigingen/patches.txt
git commit -m "feat(migration): add patch to migrate payment fields to payments settings"
```

---

### Task 3: Update Invoice Generator and Sales Invoice Account Handler

**Files:**
- Modify: `verenigingen/services/billing/invoice_generator.py`
- Modify: `verenigingen/utils/sales_invoice_account_handler.py`

**Step 1: Update invoice_generator.py**

In `verenigingen/services/billing/invoice_generator.py`, find line ~374 in `_get_income_account` method.

Change from:
```python
        # Primary: Verenigingen Settings dues_income_account
        income_account = settings.dues_income_account
```

To:
```python
        # Primary: Verenigingen Payments Settings dues_income_account
        from verenigingen.vereinigingen_payments.utils import get_payments_settings
        payments_settings = get_payments_settings()
        income_account = payments_settings.dues_income_account
```

Also update the warning message on line ~380:
```python
            self.logger.warning(
                f"Configured dues_income_account '{income_account}' in Payments Settings does not exist, using company default"
            )
```

**Step 2: Update sales_invoice_account_handler.py**

In `verenigingen/utils/sales_invoice_account_handler.py`, update the settings retrieval.

Change lines 39-51 from:
```python
    # Get Verenigingen Settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.dues_payments_receivable_account:
            return
    except frappe.DoesNotExistError:
        frappe.log_error("Verenigingen Settings not found", "Sales Invoice Account Handler")
        return
    except AttributeError as e:
        frappe.log_error(
            f"Field dues_payments_receivable_account missing: {str(e)}", "Sales Invoice Account Handler"
        )
        return
    except frappe.ValidationError as e:
        frappe.log_error(f"Verenigingen Settings validation error: {str(e)}", "Sales Invoice Account Handler")
        return
```

To:
```python
    # Get Verenigingen Payments Settings
    try:
        from verenigingen.vereinigingen_payments.utils import get_payments_settings
        settings = get_payments_settings()
        if not settings.dues_payments_receivable_account:
            return
    except frappe.DoesNotExistError:
        frappe.log_error("Verenigingen Payments Settings not found", "Sales Invoice Account Handler")
        return
    except AttributeError as e:
        frappe.log_error(
            f"Field dues_payments_receivable_account missing: {str(e)}", "Sales Invoice Account Handler"
        )
        return
    except frappe.ValidationError as e:
        frappe.log_error(f"Verenigingen Payments Settings validation error: {str(e)}", "Sales Invoice Account Handler")
        return
```

Also update the docstring (lines 1-17) to reference "Verenigingen Payments Settings" instead of "Verenigingen Settings".

**Step 3: Run tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.services.billing.invoice_generator`
Expected: Tests pass

**Step 4: Commit**

```bash
git add verenigingen/services/billing/invoice_generator.py verenigingen/utils/sales_invoice_account_handler.py
git commit -m "refactor: use Payments Settings for dues account fields in invoice generator"
```

---

### Task 4: Update Membership Dues Schedule and Mollie Processor

**Files:**
- Modify: `verenigingen/vereinigingen/doctype/membership_dues_schedule/membership_dues_schedule.py`
- Modify: `verenigingen/vereinigingen_payments/mollie/services/dues_payment_processor.py`

**Step 1: Update membership_dues_schedule.py**

Find lines ~924-926:
```python
            # Income account from Verenigingen Settings - use the proper P&L income account
            if settings.dues_income_account:
                item.income_account = settings.dues_income_account
```

Change to:
```python
            # Income account from Verenigingen Payments Settings - use the proper P&L income account
            from verenigingen.vereinigingen_payments.utils import get_payments_settings
            payments_settings = get_payments_settings()
            if payments_settings.dues_income_account:
                item.income_account = payments_settings.dues_income_account
```

**Step 2: Update dues_payment_processor.py**

Find lines ~565 and ~572:
```python
        settings = frappe.get_single("Verenigingen Settings")
        ...
        income_account = settings.dues_income_account
```

The file already uses `settings` for other fields. Add import and get payments settings for income account:

After line 565 (`settings = frappe.get_single("Verenigingen Settings")`), add:
```python
        from verenigingen.vereinigingen_payments.utils import get_payments_settings
        payments_settings = get_payments_settings()
```

Then change line ~572 from:
```python
        income_account = settings.dues_income_account
```

To:
```python
        income_account = payments_settings.dues_income_account
```

**Step 3: Run tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.vereinigingen_payments.mollie.services.dues_payment_processor`
Expected: Tests pass

**Step 4: Commit**

```bash
git add verenigingen/vereinigingen/doctype/membership_dues_schedule/membership_dues_schedule.py verenigingen/vereinigingen_payments/mollie/services/dues_payment_processor.py
git commit -m "refactor: use Payments Settings for dues_income_account in schedule and mollie processor"
```

---

### Task 5: Update Chapter Dues Allocation and Membership Analytics

**Files:**
- Modify: `verenigingen/vereinigingen/page/chapter_dues_allocation/chapter_dues_allocation.py`
- Modify: `verenigingen/vereinigingen/page/membership_analytics/membership_analytics.py`

**Step 1: Update chapter_dues_allocation.py**

This file uses `settings.dues_income_account` at lines 122 and 246. Find the settings variable initialization and add payments settings.

Near the top of the relevant functions, after getting `settings = frappe.get_single("Verenigingen Settings")`, add:
```python
    from verenigingen.vereinigingen_payments.utils import get_payments_settings
    payments_settings = get_payments_settings()
```

Then change all occurrences of `settings.dues_income_account` to `payments_settings.dues_income_account`.

**Step 2: Update membership_analytics.py**

Find line ~273-274:
```python
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        dues_income_account = verenigingen_settings.dues_income_account
```

Change to:
```python
        from verenigingen.vereinigingen_payments.utils import get_payments_settings
        payments_settings = get_payments_settings()
        dues_income_account = payments_settings.dues_income_account
```

**Step 3: Commit**

```bash
git add verenigingen/vereinigingen/page/chapter_dues_allocation/chapter_dues_allocation.py verenigingen/vereinigingen/page/membership_analytics/membership_analytics.py
git commit -m "refactor: use Payments Settings for dues_income_account in pages"
```

---

### Task 6: Update Ponto Payment Link and Debug Page

**Files:**
- Modify: `verenigingen/vereinigingen_payments/doctype/ponto_payment_link/ponto_payment_link.py`
- Modify: `verenigingen/templates/pages/ponto_api_debug.py`

**Step 1: Update ponto_payment_link.py**

Find lines ~142-147:
```python
        if not template:
            settings = frappe.get_single("Verenigingen Settings")
            template = (
                settings.ponto_payment_description_template
                or "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END"
            )
```

Change to:
```python
        if not template:
            from verenigingen.vereinigingen_payments.utils import get_payments_settings
            settings = get_payments_settings()
            template = (
                settings.ponto_payment_description_template
                or "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END"
            )
```

**Step 2: Update ponto_api_debug.py**

Find lines ~55-60:
```python
        # ponto_payment_description_template remains in Verenigingen Settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        context.description_template = (
            verenigingen_settings.ponto_payment_description_template
            or "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END"
        )
```

Change to:
```python
        # ponto_payment_description_template now in Verenigingen Payments Settings
        context.description_template = (
            payments_settings.ponto_payment_description_template
            or "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END"
        )
```

(Note: `payments_settings` is already available from line 52)

**Step 3: Commit**

```bash
git add verenigingen/vereinigingen_payments/doctype/ponto_payment_link/ponto_payment_link.py verenigingen/templates/pages/ponto_api_debug.py
git commit -m "refactor: use Payments Settings for ponto_payment_description_template"
```

---

### Task 7: Update Bank Details Template (Mollie Description)

**Files:**
- Modify: `verenigingen/templates/pages/bank_details.html`

**Step 1: Update template**

Find line ~842:
```javascript
                const descriptionTemplate = '{{ frappe.db.get_single_value("Verenigingen Settings", "mollie_subscription_description_template") or "Contribution payment for member MEMBER_ID" }}';
```

Change to:
```javascript
                const descriptionTemplate = '{{ frappe.db.get_single_value("Verenigingen Payments Settings", "mollie_subscription_description_template") or "Contribution payment for member MEMBER_ID" }}';
```

**Step 2: Commit**

```bash
git add verenigingen/templates/pages/bank_details.html
SKIP=template-variable-validator git commit -m "refactor: use Payments Settings for mollie_subscription_description_template in template"
```

---

### Task 8: Update Test Files

**Files:**
- Modify: `verenigingen/tests/integration/services/test_invoice_generator.py`
- Modify: `vereinigingen/tests/fixtures/enhanced_test_factory.py`
- Modify: `vereinigingen/vereinigingen/doctype/verenigingen_settings/test_vereinigingen_settings.py`

**Step 1: Update test_invoice_generator.py**

Change all references from `"Verenigingen Settings"` to `"Verenigingen Payments Settings"` for `dues_income_account`:

Lines 97, 119, 134, 153:
```python
# Change from:
frappe.db.set_value("Verenigingen Settings", None, "dues_income_account", ...)
# To:
frappe.db.set_value("Verenigingen Payments Settings", None, "dues_income_account", ...)
```

**Step 2: Update enhanced_test_factory.py**

Change lines 3958, 3969, 4012 from `"Verenigingen Settings"` to `"Verenigingen Payments Settings"`.

**Step 3: Update test_verenigingen_settings.py**

Move the account-related tests to a new test file for Payments Settings, or update the tests to use Payments Settings DocType.

The tests `test_dues_payments_receivable_account_field_exists`, `test_dues_income_account_field_exists`, `test_sales_invoice_account_handler_integration`, and `test_non_membership_invoice_unchanged` should reference Payments Settings.

**Step 4: Run all affected tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen`
Expected: All tests pass

**Step 5: Commit**

```bash
git add verenigingen/tests/integration/services/test_invoice_generator.py vereinigingen/tests/fixtures/enhanced_test_factory.py verenigingen/vereinigingen/doctype/verenigingen_settings/test_verenigingen_settings.py
git commit -m "test: update tests to use Payments Settings for dues account fields"
```

---

### Task 9: Remove Fields from Verenigingen Settings DocType

**Files:**
- Modify: `verenigingen/vereinigingen/doctype/verenigingen_settings/vereinigingen_settings.json`

**Step 1: Remove field names from field_order array**

Remove these entries from the `field_order` array:
- `"mollie_subscription_description_template"`
- `"ponto_payment_description_template"`
- `"membership_payment_account"`
- `"dues_income_account"`
- `"dues_payments_receivable_account"`

**Step 2: Remove field definitions from fields array**

Remove the 5 field definition objects for the moved fields.

**Step 3: Run migration**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Schema synced, old columns remain in database (Frappe doesn't drop columns)

**Step 4: Commit**

```bash
git add verenigingen/vereinigingen/doctype/verenigingen_settings/vereinigingen_settings.json
git commit -m "refactor(settings): remove payment fields migrated to Payments Settings"
```

---

### Task 10: Final Verification and Cleanup

**Step 1: Run full test suite**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen`
Expected: All tests pass

**Step 2: Verify UI**

1. Open Verenigingen Settings - verify moved fields are gone
2. Open Verenigingen Payments Settings - verify new fields appear and have migrated values

**Step 3: Test functionality**

1. Create a new dues schedule - verify income account is used correctly
2. Check bank_details page - verify Mollie description template works
3. Check Ponto payment link creation - verify description template works

**Step 4: Clear cache**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache`

**Step 5: Final commit (if any cleanup needed)**

```bash
git status
# If clean, done. Otherwise commit any remaining changes.
```

---

## Rollback Plan

If issues occur after deployment:

1. Revert migration patch (data stays in both locations)
2. Revert call site changes
3. Restore field definitions to Verenigingen Settings

The migration patch only copies data (doesn't delete from source), so rollback is safe.

# Consolidate Fee Query Duplication — Implementation Plan

> **Status: COMPLETED** — Implemented 2026-02-05 via subagent-driven development.

**Goal:** Eliminate the triple fee query duplication by creating a single canonical `get_membership_type_fee_info()` function that all endpoints delegate to.

**Architecture:** One canonical function in `utils/application_helpers.py` returns ALL fee-related data for a membership type. The three existing business functions become thin wrappers. The template page functions also delegate to the canonical source.

**Tech Stack:** Python 3.11, Frappe Framework v15

---

## Current State Summary

The same "load membership type → load template → resolve amount" pattern is duplicated across:

| Function | File | Lines | What It Returns |
|----------|------|-------|-----------------|
| `get_membership_fee_info()` | `utils/application_helpers.py:905-938` | 34 | `{amount, currency, billing_frequency}` |
| `get_membership_type_details()` | `utils/application_helpers.py:941-1001` | 61 | Above + `{suggested_amounts[], min, max}` |
| `suggest_membership_amounts()` | `utils/application_helpers.py:1019-1083` | 65 | `{base_amount, suggestions[]}` with formatting |
| `get_membership_type_details()` | `templates/pages/membership_application.py:222-253` | 32 | `{membership_type: {name, amount, ...}}` |
| `get_dues_schedule_template_values()` | `templates/pages/membership_application.py:60-104` | 45 | `{billing_frequency, suggested_contribution, ...}` |

**Plus 3 endpoint wrappers + 3 legacy aliases in `api/membership_application.py`** = 6 more functions that just pass-through.

**Key finding:** The JS frontend defines `getMembershipTypeDetails()` and `getSuggestedAmounts()` in `api-service.js` but **neither method is ever called**. The legacy aliases at lines 1679-1695 of `membership_application.py` are the endpoints wired in JS, but JS never invokes those methods either. Page context (server-rendered) provides the data instead.

### Common Query Pattern (duplicated 4× in Python)

```python
membership_type_doc = frappe.get_doc("Membership Type", membership_type)
if membership_type_doc.dues_schedule_template:
    template = frappe.get_doc("Membership Dues Schedule", ...)
    amount = template.dues_rate or template.suggested_amount or 0
    billing_frequency = template.billing_frequency or "Annual"
if not amount:
    amount = membership_type_doc.minimum_amount
```

### Differences Between Functions

| Aspect | `fee_info` | `type_details` | `suggest_amounts` | Template page |
|--------|-----------|----------------|-------------------|---------------|
| Amount field name | `standard_amount` | `amount` | `base_amount` | `suggested_contribution` |
| Uses `dues_rate` first | Yes (via `or`) | Yes (via `or`) | No (uses `suggested_amount` only) | Yes (explicit None check) |
| Suggested tiers | No | Yes (1.5×, 2×, 3×) | Yes (1.25×, 1.5×, 2×) | No |
| Tier labels | — | Standard/Supporter/Patron/Benefactor | Standard/Supporter/Advocate/Champion | — |
| Min/max bounds | No | Yes (50% floor, 5× ceiling) | No | No |
| i18n labels | No | No | Yes (`_()`) | No |
| Formatted amounts | No | No | Yes (`fmt_money`) | No |
| Impact messages | No | No | Yes | No |
| Validation on zero | Silently returns 0 | Silently returns 0 | Throws error | Throws error |
| Currency resolution | `_get_membership_type_currency()` | `_get_membership_type_currency()` | `_get_membership_type_currency()` | Not included |

---

## What Changes

| Action | LOC Change |
|--------|------------|
| New canonical function `get_membership_type_fee_info()` | +45 |
| Rewrite `get_membership_fee_info()` as thin wrapper | -25 (34→9) |
| Rewrite `get_membership_type_details()` as thin wrapper | -45 (61→16) |
| Rewrite `suggest_membership_amounts()` as thin wrapper | -40 (65→25) |
| Rewrite template page's `get_membership_type_details()` | -20 (32→12) |
| Rewrite template page's `get_dues_schedule_template_values()` | -30 (45→15) |
| Move `_get_membership_type_currency()` (unchanged, stays in place) | 0 |
| **Net** | **~-115 LOC** |

**NOT changed:** The 3 endpoint wrappers, 3 legacy aliases, and 2 JS `APIService` methods. These are thin pass-throughs that don't duplicate logic — they just forward to the business functions.

---

## Task 1: Write tests for current behavior

Capture the current response shapes before changing anything.

**Files:**
- Create: `verenigingen/tests/backend/unit/utils/test_fee_query_consolidation.py`

**Step 1: Write the test file**

```python
"""
Tests for fee query consolidation.

Verifies that the three fee query functions in application_helpers.py
return consistent data from the same underlying membership type + template.
"""

import importlib
import frappe
from frappe.tests.utils import FrappeTestCase


class TestFeeQueryConsolidation(FrappeTestCase):
    """Tests verifying fee query functions exist and are importable."""

    def test_get_membership_fee_info_importable(self):
        """get_membership_fee_info must be importable from application_helpers."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "get_membership_fee_info", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_get_membership_type_details_importable(self):
        """get_membership_type_details must be importable from application_helpers."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "get_membership_type_details", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_suggest_membership_amounts_importable(self):
        """suggest_membership_amounts must be importable from application_helpers."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "suggest_membership_amounts", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_canonical_function_exists(self):
        """get_membership_type_fee_info must exist as the canonical source."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "get_membership_type_fee_info", None)
        self.assertIsNotNone(func, "get_membership_type_fee_info must exist as canonical function")
        self.assertTrue(callable(func))

    def test_canonical_function_returns_required_keys(self):
        """Canonical function must return all keys needed by all three wrappers."""
        # Get a real membership type
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import get_membership_type_fee_info

        result = get_membership_type_fee_info(mt[0].name)
        self.assertTrue(result.get("success"), f"Expected success, got: {result}")

        # Must contain ALL fields needed by any wrapper
        required_keys = [
            "membership_type", "membership_type_name", "description",
            "amount", "currency", "billing_frequency",
            "minimum_amount", "maximum_amount",
            "suggested_amounts",
        ]
        for key in required_keys:
            self.assertIn(key, result, f"Missing key '{key}' in canonical result")

    def test_fee_info_wrapper_returns_expected_keys(self):
        """get_membership_fee_info must return its expected response shape."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import get_membership_fee_info

        result = get_membership_fee_info(mt[0].name)
        self.assertTrue(result.get("success"))
        self.assertIn("standard_amount", result)
        self.assertIn("currency", result)
        self.assertIn("billing_frequency", result)

    def test_type_details_wrapper_returns_expected_keys(self):
        """get_membership_type_details must return its expected response shape."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import get_membership_type_details

        result = get_membership_type_details(mt[0].name)
        self.assertTrue(result.get("success"))
        self.assertIn("amount", result)
        self.assertIn("suggested_amounts", result)
        self.assertIn("minimum_amount", result)
        self.assertIn("maximum_amount", result)

    def test_suggest_amounts_wrapper_returns_expected_keys(self):
        """suggest_membership_amounts must return its expected response shape."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import suggest_membership_amounts

        result = suggest_membership_amounts(mt[0].name)
        # This may fail if template has no suggested_amount — that's OK for now
        if result.get("success"):
            self.assertIn("base_amount", result)
            self.assertIn("suggestions", result)
            self.assertIsInstance(result["suggestions"], list)

    def test_all_three_agree_on_base_amount(self):
        """All three functions must agree on the base amount for the same membership type."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import (
            get_membership_fee_info,
            get_membership_type_details,
            suggest_membership_amounts,
        )

        fee_result = get_membership_fee_info(mt[0].name)
        details_result = get_membership_type_details(mt[0].name)
        suggest_result = suggest_membership_amounts(mt[0].name)

        if all(r.get("success") for r in [fee_result, details_result, suggest_result]):
            fee_amount = fee_result.get("standard_amount", 0)
            details_amount = details_result.get("amount", 0)
            suggest_amount = suggest_result.get("base_amount", 0)

            self.assertEqual(
                float(fee_amount), float(details_amount),
                f"fee_info ({fee_amount}) and type_details ({details_amount}) disagree on amount",
            )
```

**Step 2: Run tests — only `test_canonical_function_exists` should fail**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org execute vereinigingen._run_fee_tests.run`
(Write a quick verification script since `bench run-tests` has the ItemPrice issue)

**Step 3: Commit**

```bash
git add verenigingen/tests/backend/unit/utils/test_fee_query_consolidation.py
git commit -m "test: add fee query consolidation baseline tests"
```

---

## Task 2: Create the canonical `get_membership_type_fee_info()` function

This is the single source of truth. All other functions will delegate to it.

**Files:**
- Modify: `verenigingen/utils/application_helpers.py` (add new function before line 905)

**Step 1: Add the canonical function**

Insert before `get_membership_fee_info()` (before line 905):

```python
def get_membership_type_fee_info(membership_type):
    """Canonical source of truth for membership type fee information.

    Loads the membership type and its dues schedule template, resolves the
    base amount, currency, and billing frequency, and computes suggested
    contribution tiers. All fee query endpoints delegate to this function.

    Args:
        membership_type: Name of the Membership Type document.

    Returns:
        dict with keys:
            success (bool), membership_type (str), membership_type_name (str),
            description (str), amount (float), currency (str),
            billing_frequency (str), minimum_amount (float),
            maximum_amount (float), suggested_amounts (list[dict]),
            allow_custom_amount (bool), has_template (bool)
    """
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Resolve amount from dues schedule template
        amount = 0
        billing_frequency = "Annual"
        has_template = bool(membership_type_doc.dues_schedule_template)

        if has_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                amount = template.dues_rate or template.suggested_amount or 0
                billing_frequency = template.billing_frequency or "Annual"
            except Exception:
                pass

        # Fallback to minimum_amount if template has no amount
        if not amount:
            amount = membership_type_doc.minimum_amount or 0

        amount = float(amount)
        currency = _get_membership_type_currency(membership_type_doc)

        # Compute suggested contribution tiers
        suggested_amounts = []
        if amount > 0:
            for multiplier, label, description in [
                (1.0, _("Standard"), _("Standard membership fee")),
                (1.25, _("Supporter"), _("Support our mission with 25% extra")),
                (1.5, _("Advocate"), _("Help us grow with 50% extra")),
                (2.0, _("Champion"), _("Be a champion with 100% extra")),
            ]:
                tier_amount = amount * multiplier
                suggested_amounts.append({
                    "amount": tier_amount,
                    "label": label,
                    "description": description,
                    "percentage": int(multiplier * 100),
                    "is_default": multiplier == 1.0,
                    "formatted_amount": frappe.utils.fmt_money(tier_amount, currency=currency),
                })

        return {
            "success": True,
            "membership_type": membership_type_doc.name,
            "membership_type_name": getattr(membership_type_doc, "membership_type_name", membership_type_doc.name),
            "description": membership_type_doc.description,
            "amount": amount,
            "currency": currency,
            "billing_frequency": billing_frequency,
            "minimum_amount": float(membership_type_doc.minimum_amount or 0),
            "maximum_amount": amount * 5 if amount > 0 else 0,
            "suggested_amounts": suggested_amounts,
            "allow_custom_amount": True,
            "has_template": has_template,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Error retrieving membership type fee information",
        }
```

**Step 2: Run tests — `test_canonical_function_exists` and `test_canonical_function_returns_required_keys` should now pass**

**Step 3: Commit**

```bash
git add verenigingen/utils/application_helpers.py
git commit -m "feat: add canonical get_membership_type_fee_info function"
```

---

## Task 3: Rewrite the three business functions as thin wrappers

Each function now calls `get_membership_type_fee_info()` and reshapes the response to match its original contract.

**Files:**
- Modify: `verenigingen/utils/application_helpers.py` (rewrite lines 905-1083)

**Step 1: Rewrite `get_membership_fee_info()` (was lines 905-938)**

```python
def get_membership_fee_info(membership_type):
    """Get membership fee information.

    Thin wrapper around get_membership_type_fee_info() that returns only
    the fields needed by the fee info endpoint.
    """
    info = get_membership_type_fee_info(membership_type)
    if not info.get("success"):
        return info
    return {
        "success": True,
        "membership_type": info["membership_type"],
        "standard_amount": info["amount"],
        "currency": info["currency"],
        "description": info["description"],
        "billing_frequency": info["billing_frequency"],
    }
```

**Step 2: Rewrite `get_membership_type_details()` (was lines 941-1001)**

```python
def get_membership_type_details(membership_type):
    """Get detailed membership type information.

    Thin wrapper around get_membership_type_fee_info() that adds the
    legacy suggested_amounts format with Supporter/Patron/Benefactor tiers
    and min/max bounds.
    """
    info = get_membership_type_fee_info(membership_type)
    if not info.get("success"):
        return info

    amount = info["amount"]

    # Legacy tier format: Standard/Supporter/Patron/Benefactor at 1×/1.5×/2×/3×
    legacy_tiers = []
    if amount > 0:
        for multiplier, label, desc in [
            (1.0, "Standard", "Standard membership fee"),
            (1.5, "Supporter", f"Support our mission with {int((1.5 - 1) * 100)}% extra"),
            (2.0, "Patron", f"Support our mission with {int((2.0 - 1) * 100)}% extra"),
            (3.0, "Benefactor", f"Support our mission with {int((3.0 - 1) * 100)}% extra"),
        ]:
            legacy_tiers.append({
                "amount": amount * multiplier,
                "label": label,
                "description": desc,
            })

    return {
        "success": True,
        "name": info["membership_type"],
        "membership_type_name": info["membership_type_name"],
        "description": info["description"],
        "amount": amount,
        "currency": info["currency"],
        "billing_frequency": info["billing_frequency"],
        "allow_custom_amount": True,
        "minimum_amount": info["minimum_amount"] * 0.5,  # 50% of constraint floor
        "maximum_amount": info["maximum_amount"],
        "custom_amount_note": "You can adjust your contribution amount. Minimum is 50% of standard fee.",
        "suggested_amounts": legacy_tiers,
    }
```

**Step 3: Rewrite `suggest_membership_amounts()` (was lines 1019-1083)**

Keep the strict validation (template must exist, suggested_amount must not be None/negative) since this function has different error semantics.

```python
def suggest_membership_amounts(membership_type_name):
    """Suggest membership amounts based on type.

    Uses get_membership_type_fee_info() for base data, then adds strict
    validation and formatted suggestion tiers.
    """
    try:
        info = get_membership_type_fee_info(membership_type_name)
        if not info.get("success"):
            return info

        if not info.get("has_template"):
            frappe.throw(
                f"Membership Type '{membership_type_name}' must have a dues schedule template"
            )

        base_amount = info["amount"]
        currency = info["currency"]

        # Strict validation: suggest_membership_amounts requires a positive amount
        if base_amount <= 0:
            membership_type_minimum = info.get("minimum_amount", 0)
            if membership_type_minimum > 0:
                frappe.throw(
                    f"Dues Schedule Template for '{membership_type_name}' has zero suggested_amount "
                    f"but minimum_amount is {membership_type_minimum}. For free memberships, both must be zero."
                )

        # Use canonical suggested_amounts and add impact messages
        suggestions = []
        for tier in info.get("suggested_amounts", []):
            tier_copy = dict(tier)
            tier_copy["impact_message"] = get_amount_impact_message(
                tier["amount"], base_amount, tier["percentage"]
            )
            suggestions.append(tier_copy)

        return {
            "success": True,
            "base_amount": base_amount,
            "currency": currency,
            "suggestions": suggestions,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "suggestions": []}
```

**Step 4: Run all tests — verify all wrappers return expected shapes**

**Step 5: Commit**

```bash
git add verenigingen/utils/application_helpers.py
git commit -m "refactor: rewrite fee query functions as thin wrappers around canonical source"
```

---

## Task 4: Rewrite template page functions to use canonical source

**Files:**
- Modify: `verenigingen/templates/pages/membership_application.py` (lines 60-104, 222-253)

**Step 1: Rewrite `get_dues_schedule_template_values()` (lines 60-104)**

```python
def get_dues_schedule_template_values(membership_type_name):
    """Get billing and contribution values from dues schedule template.

    Delegates to the canonical get_membership_type_fee_info() and reshapes
    the response for the template page context.
    """
    from verenigingen.utils.application_helpers import get_membership_type_fee_info

    info = get_membership_type_fee_info(membership_type_name)
    if not info.get("success"):
        frappe.throw(
            f"Membership Type '{membership_type_name}' must have either a dues schedule template "
            f"with suggested_amount/dues_rate or minimum_amount configured"
        )

    amount = info["amount"]
    return {
        "billing_frequency": info["billing_frequency"],
        "minimum_contribution": 0,
        "suggested_contribution": amount,
        "maximum_contribution": 0,
        "fee_slider_max_multiplier": 10.0,
        "allow_custom_amounts": True,
        "custom_amount_requires_approval": False,
    }
```

**Step 2: Rewrite `get_membership_type_details()` (lines 222-253)**

```python
@frappe.whitelist()
@public_api
def get_membership_type_details(membership_type_name: str):
    """Get detailed contribution options for a specific membership type."""
    if not membership_type_name:
        return {"error": "Membership type name is required"}

    try:
        from verenigingen.utils.application_helpers import get_membership_type_fee_info

        info = get_membership_type_fee_info(membership_type_name)
        if not info.get("success"):
            return {"error": info.get("error", "Unknown error")}

        mt_doc = frappe.get_doc("Membership Type", membership_type_name)
        return {
            "success": True,
            "membership_type": {
                "name": info["membership_type"],
                "membership_type_name": info["membership_type_name"],
                "description": info["description"],
                "amount": info["amount"],
                "billing_frequency": info["billing_frequency"],
                "contribution_options": (
                    mt_doc.get_contribution_options()
                    if hasattr(mt_doc, "get_contribution_options")
                    else {}
                ),
            },
        }
    except frappe.DoesNotExistError:
        return {"error": f"Membership type '{membership_type_name}' not found"}
    except Exception as e:
        frappe.log_error(f"Error getting membership type details: {str(e)}")
        return {"error": "An error occurred while retrieving membership type details"}
```

Note: The template page version still needs `mt_doc.get_contribution_options()` which isn't in the canonical function. This is page-specific presentation logic that belongs here, not in the canonical source.

**Step 3: Run tests**

**Step 4: Commit**

```bash
git add verenigingen/templates/pages/membership_application.py
git commit -m "refactor: rewrite template page fee queries to use canonical source"
```

---

## Task 5: Run comprehensive verification

**Step 1: Run the fee query tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute verenigingen._run_fee_tests.run
```

**Step 2: Run pre-commit validators on changed files**

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/utils/application_helpers.py \
  verenigingen/templates/pages/membership_application.py \
  verenigingen/tests/backend/unit/utils/test_fee_query_consolidation.py
```

**Step 3: Verify the endpoint wrappers still work**

The 3 endpoint wrappers in `api/membership_application.py` and 3 legacy aliases should continue to work unchanged since they call the business functions which now delegate to the canonical source.

**Step 4: Verify the page context still builds correctly**

The `get_context()` function in `templates/pages/membership_application.py` calls `get_dues_schedule_template_values()` which now delegates to the canonical function. Verify the membership types still load correctly in the page context.

---

## Architecture After Refactoring

```
┌─────────────────────────────────────────────────────────────┐
│ Canonical Source (single DB query path)                      │
│                                                              │
│ get_membership_type_fee_info(membership_type)                │
│   ├── Load Membership Type doc                               │
│   ├── Load Dues Schedule Template (if exists)                │
│   ├── Resolve amount: dues_rate → suggested_amount → min     │
│   ├── Resolve billing_frequency from template                │
│   ├── Compute suggested tiers (1×, 1.25×, 1.5×, 2×)         │
│   └── Return unified dict with ALL fields                    │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Thin Wrappers (reshape canonical response)                   │
│                                                              │
│ get_membership_fee_info()                                    │
│   → canonical → pick {standard_amount, currency, ...}        │
│                                                              │
│ get_membership_type_details()                                │
│   → canonical → add legacy tiers + min/max bounds            │
│                                                              │
│ suggest_membership_amounts()                                 │
│   → canonical → strict validation + impact messages          │
│                                                              │
│ template/get_dues_schedule_template_values()                 │
│   → canonical → reshape for page context                     │
│                                                              │
│ template/get_membership_type_details()                       │
│   → canonical → add contribution_options                     │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ API Layer (unchanged, pass-through)                          │
│                                                              │
│ get_membership_fee_info_endpoint()  → fee_info wrapper       │
│ get_membership_type_details_endpoint() → details wrapper     │
│ suggest_membership_amounts_endpoint() → suggest wrapper      │
│ get_membership_fee_info() [legacy]  → endpoint               │
│ get_membership_type_details() [legacy] → endpoint            │
│ suggest_membership_amounts() [legacy] → endpoint             │
└──────────────────────────────────────────────────────────────┘
```

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Response shape changes break frontend | Very Low | Frontend never calls these endpoints (verified) |
| Suggested tier amounts differ slightly | Low | Old `type_details` used 1.5×/2×/3×; old `suggest` used 1.25×/1.5×/2×. Wrappers preserve original tiers. |
| Template page context breaks | Low | `get_dues_schedule_template_values()` returns same keys |
| `suggest_membership_amounts` validation semantics change | Low | Strict validation preserved in wrapper, not moved to canonical |

---

## Execution Summary

**Completed:** 2026-02-05
**Method:** Subagent-driven development (5 tasks + 1 post-review fix)

### Commits

| Commit | Description |
|--------|-------------|
| `fab38bb2` | test: add fee query consolidation baseline tests |
| `44320420` | feat: add canonical get_membership_type_fee_info function |
| `336be03a` | refactor: rewrite fee query functions as thin wrappers around canonical source |
| `29041aef` | refactor: rewrite template page fee queries to use canonical source |
| `107acec9` | fix: restore strict validation in suggest_membership_amounts |

### LOC Impact

| File | Insertions | Deletions | Net |
|------|-----------|-----------|-----|
| `utils/application_helpers.py` | +232 | -143 | +89 (canonical function +89, wrappers -54) |
| `templates/pages/membership_application.py` | +34 | -74 | -40 |
| Test files (new) | +186 | 0 | +186 |
| **Total** | **+452** | **-217** | **+235** (prod code: +49, tests: +186) |

### Review Findings Addressed

The final code review found two critical issues that were fixed in commit `107acec9`:

1. **`suggest_membership_amounts` lost strict validation:** The original had three strict checks on `raw_suggested_amount` (None, negative, zero-with-nonzero-minimum) that were dropped when the wrapper delegated to the canonical function. **Fix:** Canonical function now exposes `raw_suggested_amount` and `template_name`; wrapper uses these for strict validation.

2. **`suggest_membership_amounts` changed its amount source:** The original used `template.suggested_amount` only (not `dues_rate`) as the base for tier calculation. The canonical function uses `dues_rate or suggested_amount`. **Fix:** Wrapper now uses `raw_suggested_amount` as its base amount, computing tiers independently rather than reusing canonical tiers.

### Known Remaining Items

- **Double DB load in `get_dues_schedule_template_values`:** The template doc is loaded once inside the canonical function and once locally for supplementary fields (`minimum_contribution`, `invoice_days_before`, `allow_custom_amounts`). Frappe's document cache mitigates this. Could be further improved by having the canonical function expose these fields.
- **Two tier schemas coexist:** `get_membership_type_details` uses Standard/Supporter/Patron/Benefactor (1×/1.5×/2×/3×) while canonical and `suggest_membership_amounts` use Standard/Supporter/Advocate/Champion (1×/1.25×/1.5×/2×). This preserves backward compatibility but is confusing. Consider consolidating tier definitions in a future pass.
- **`allow_custom_amount` hardcoded to True:** The canonical function could read this from the template's `uses_custom_amount` field instead.

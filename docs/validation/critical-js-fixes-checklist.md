# Critical JavaScript Fixes - Action Checklist

**Status:** 🔴 **13 Critical Production Issues** need immediate attention

## Phase 1: E-Boekhouden Integration (HIGH PRIORITY)

### Core Application Files - IMMEDIATE FIX NEEDED

- [ ] **File:** `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.js`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.api.eboekhouden_migration_redesign.get_migration_statistics`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.utils.test_rest_migration.test_rest_mutation_fetch`

- [ ] **File:** `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration_original.js`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.e_boekhouden.utils_full_migration.migrate_all_eboekhouden_data`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.e_boekhouden.utils_category_mapping_fixed.analyze_accounts_with_proper_categories`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.e_boekhouden.utils_group_analysis_improved.analyze_account_categories_improved`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.utils.fix_receivable_payable_entries.analyze_and_fix_entries`
  - [ ] Add `@frappe.whitelist()` to `verenigingen.utils.fix_receivable_payable_entries.apply_account_type_fixes`

## Phase 2: Critical DocType Methods (HIGH PRIORITY)

### Chapter DocType
- [ ] **File:** `verenigingen/verenigingen/doctype/chapter/chapter.js:200`
  - [ ] Add `@frappe.whitelist()` to `validate_postal_codes` method

### Member Management
- [ ] **File:** Multiple DocType JS files
  - [ ] Add `@frappe.whitelist()` to `assign_member_to_chapter`
  - [ ] Add `@frappe.whitelist()` to `get_member_chapter_display_html`
  - [ ] Add `@frappe.whitelist()` to `get_or_create_volunteer`
  - [ ] Add `@frappe.whitelist()` to `get_member_payment_history`
  - [ ] Add `@frappe.whitelist()` to `update_member_payment_history`

### SEPA Mandate Management
- [ ] **File:** Multiple SEPA-related DocType JS files
  - [ ] Add `@frappe.whitelist()` to `get_active_sepa_mandate`
  - [ ] Add `@frappe.whitelist()` to `create_sepa_mandate`
  - [ ] Add `@frappe.whitelist()` to `create_and_link_mandate_enhanced`
  - [ ] Add `@frappe.whitelist()` to `validate_mandate_creation`

## Validation Commands

**Test fixes immediately after each change:**
```bash
# Check if methods exist
python -c "import verenigingen.api.test_eboekhouden_connection; print('Module exists')"

# Re-run validation after fixes
python scripts/validation/js_python_parameter_validator.py --output-format text | grep -A5 -B5 "Issues Found: 0"
```

## Expected Result After Phase 1 & 2

- **Before:** 241 broken calls (13 critical production issues)
- **After Phase 1:** ~228 broken calls (0 critical production issues)
- **After Phase 2:** ~137 broken calls (0 critical business logic issues)

## Next Steps After Critical Fixes

1. **Test Infrastructure** - Fix 72 test method calls
2. **Portal Functionality** - Fix 49 public asset calls
3. **Reports** - Fix 4 report method calls
4. **Cleanup** - Remove 6 archived file calls
5. **Manual Review** - Investigate 45 suspicious calls

---

**Priority:** Complete Phase 1 & 2 before committing any changes to production
**Impact:** E-Boekhouden integration and core member management will be broken until fixed
**Time Estimate:** 1-2 hours for critical fixes, 4-6 hours for complete resolution

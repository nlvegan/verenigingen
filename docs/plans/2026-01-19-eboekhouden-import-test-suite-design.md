# eBoekhouden Import Logic Test Suite Design

**Date:** 2026-01-19
**Status:** Pending Approval
**Focus Areas:** Transaction Type Processing, Data Transformation, Error Handling

## Overview

This document defines a comprehensive test suite for the eBoekhouden import logic in the verenigingen app. The tests cover three critical areas:

1. **Transaction Type Classification** - Routing mutations to correct ERPNext document types
2. **Data Transformation** - Converting eBoekhouden field formats to ERPNext
3. **Error Handling & Edge Cases** - Graceful failure handling and recovery

## Test Modules

### Module 1: `test_transaction_type_classification.py`

Location: `verenigingen/tests/e_boekhouden/test_transaction_type_classification.py`

#### 1.1 Numeric Type Mapping (REST API)

| Test Case | Input | Expected Output |
|-----------|-------|-----------------|
| `test_type_0_opening_balance` | `{"type": 0}` | Journal Entry |
| `test_type_1_purchase_invoice` | `{"type": 1}` | Purchase Invoice |
| `test_type_2_sales_invoice` | `{"type": 2}` | Sales Invoice |
| `test_type_3_customer_payment` | `{"type": 3}` | Payment Entry |
| `test_type_4_supplier_payment` | `{"type": 4}` | Payment Entry |
| `test_type_5_money_received` | `{"type": 5}` | Journal Entry |
| `test_type_6_money_sent` | `{"type": 6}` | Journal Entry |
| `test_type_7_memorial` | `{"type": 7}` | Journal Entry |

#### 1.2 Text Type Mapping (SOAP API)

| Test Case | Input | Expected Output |
|-----------|-------|-----------------|
| `test_factuur_ontvangen` | `"Factuur ontvangen"` | Purchase Invoice |
| `test_factuur_verstuurd` | `"Factuur verstuurd"` | Sales Invoice |
| `test_factuurbetaling_ontvangen` | `"Factuurbetaling ontvangen"` | Payment Entry |
| `test_factuurbetaling_verstuurd` | `"Factuurbetaling verstuurd"` | Payment Entry |
| `test_geld_ontvangen` | `"Geld ontvangen"` | Journal Entry |
| `test_memoriaal` | `"Memoriaal"` | Journal Entry |
| `test_camelcase_variants` | `"FactuurOntvangen"` | Purchase Invoice |

#### 1.3 Processor Routing Edge Cases

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_type_3_negative_no_invoice_ref` | Type 3, amount < 0, no invoiceNumber | Routes to JournalProcessor (generic refund) |
| `test_type_3_negative_with_invoice_ref` | Type 3, amount < 0, has invoiceNumber | Routes to PaymentProcessor (credit note payment) |
| `test_type_4_positive_normal_payment` | Type 4, amount > 0 | PaymentProcessor, payment_type="Pay" |
| `test_type_4_negative_supplier_refund` | Type 4, amount < 0 | PaymentProcessor, payment_type="Receive" |
| `test_unknown_type_fallback` | `{"type": 99}` | Journal Entry (default fallback) |
| `test_missing_type_field` | `{}` | Journal Entry with low confidence |
| `test_negative_row_amount_warning` | Type 3/4 with negative row.amount | Logs warning (violates unsigned assumption) |

#### 1.4 Payment Reference Type

| Test Case | Input Type | Expected Reference |
|-----------|------------|-------------------|
| `test_type_3_references_sales_invoice` | 3 | Sales Invoice |
| `test_type_4_references_purchase_invoice` | 4 | Purchase Invoice |
| `test_text_ontvangen_references_sales` | "ontvangen" in type | Sales Invoice |
| `test_text_verstuurd_references_purchase` | "verstuurd" in type | Purchase Invoice |

---

### Module 2: `test_data_transformation.py`

Location: `verenigingen/tests/e_boekhouden/test_data_transformation.py`

#### 2.1 Date Normalization

| Test Case | Input | Expected Output |
|-----------|-------|-----------------|
| `test_yyyymmdd_format` | `"20250110"` | `"2025-01-10"` |
| `test_iso_datetime` | `"2025-01-10T00:00:00"` | `"2025-01-10"` |
| `test_iso_with_timezone` | `"2025-01-10T00:00:00+01:00"` | `"2025-01-10"` |
| `test_iso_with_zulu` | `"2025-01-10T00:00:00Z"` | `"2025-01-10"` |
| `test_european_dash_format` | `"10-01-2025"` | `"2025-01-10"` |
| `test_european_slash_format` | `"10/01/2025"` | `"2025-01-10"` |
| `test_already_correct` | `"2025-01-10"` | `"2025-01-10"` |
| `test_integer_date` | `20250110` (int) | `"2025-01-10"` |
| `test_none_value` | `None` | `None` |
| `test_empty_string` | `""` | `None` |
| `test_whitespace_only` | `"   "` | `None` |

#### 2.2 Amount Handling

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_positive_amount` | `{"amount": 100.50}` | Returns 100.50 |
| `test_negative_amount_refund` | `{"amount": -50.00}` | Returns -50.00 (refund) |
| `test_zero_main_with_rows` | `{"amount": 0, "rows": [...]}` | Calculates from rows |
| `test_row_sum_validation_pass` | Sum within 0.01 of amount | Validation passes |
| `test_row_sum_validation_fail` | Sum differs by > 0.01 | Raises exception |
| `test_net_amount_validation` | Memorial booking | Validates debit - credit = expected |
| `test_skip_near_zero_rows` | Row amount < 0.01 | Row skipped in calculation |
| `test_decimal_precision` | `{"amount": 100.999}` | Rounds to 2 decimals |

#### 2.3 VAT/BTW Code Mapping

| Test Case | BTW Code | Rate | Type |
|-----------|----------|------|------|
| `test_hoog_verk_21` | `"HOOG_VERK_21"` | 21 | Output VAT |
| `test_laag_verk_9` | `"LAAG_VERK_9"` | 9 | Output VAT |
| `test_hoog_ink_21` | `"HOOG_INK_21"` | 21 | Input VAT |
| `test_laag_ink_9` | `"LAAG_INK_9"` | 9 | Input VAT |
| `test_verlegde_btw` | `"VERLEGDE_BTW"` | 21 | Reverse Charge |
| `test_geen` | `"GEEN"` | 0 | None |
| `test_vrij` | `"VRIJ"` | 0 | None (exempt) |

#### 2.4 UOM Mapping

| Test Case | Dutch UOM | ERPNext UOM |
|-----------|-----------|-------------|
| `test_stk_to_nos` | `"Stk"` | `"Nos"` |
| `test_stuks_to_nos` | `"Stuks"` | `"Nos"` |
| `test_uur_to_hour` | `"Uur"` | `"Hour"` |
| `test_dag_to_day` | `"Dag"` | `"Day"` |
| `test_maand_to_month` | `"Maand"` | `"Month"` |
| `test_case_insensitive` | `"STK"`, `"stk"` | `"Nos"` |
| `test_unknown_uom_default` | `"Unknown"` | `"Nos"` (default) |

#### 2.5 Item Group Classification

| Test Case | Input | Expected Group |
|-----------|-------|----------------|
| `test_keyword_dienst` | description contains "dienst" | Services |
| `test_keyword_product` | description contains "product" | Products |
| `test_keyword_reis` | description contains "reis" | Expense Items |
| `test_keyword_kantoor` | description contains "kantoorartikelen" | Office Supplies |
| `test_account_code_80000` | GL account 80000-89999 | Services |
| `test_account_code_43000` | GL account 43000-43999 | Products |
| `test_vat_geen_hint` | BTW code "GEEN" | Services |
| `test_price_range_investment` | amount > 1000 | investment category |

---

### Module 3: `test_import_error_handling.py`

Location: `verenigingen/tests/e_boekhouden/test_import_error_handling.py`

#### 3.1 Malformed Mutation Data

| Test Case | Malformed Input | Expected Behavior |
|-----------|-----------------|-------------------|
| `test_missing_id` | `{"type": 1, "date": "..."}` | Handles gracefully or raises ValidationError |
| `test_missing_date` | `{"id": 123, "type": 1}` | Uses fallback or raises error |
| `test_missing_type` | `{"id": 123}` | Defaults to Journal Entry |
| `test_empty_rows` | `{"rows": []}` | Handles empty rows array |
| `test_row_missing_ledger_id` | Row without ledgerId | Raises exception with details |
| `test_row_zero_amount` | Row with amount < 0.01 | Skips row, continues processing |
| `test_invalid_date_format` | `"not-a-date"` | Returns None from normalize_date |
| `test_non_numeric_amount` | `{"amount": "abc"}` | Returns 0.0 or raises |
| `test_null_nested_objects` | `{"rows": null}` | Handles None gracefully |

#### 3.2 Duplicate Detection & Handling

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_insert_new_document` | First insert | Returns (doc, False) |
| `test_insert_duplicate_race_condition` | DuplicateEntryError raised | Returns (existing_doc, True) |
| `test_submit_new_document` | First submit | Calls insert() and submit() |
| `test_submit_existing_document` | Duplicate detected | Returns existing, no submit() |
| `test_idempotent_reimport` | Same mutation_nr twice | Second import finds existing |

#### 3.3 Account/Ledger Mapping Failures

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_unmapped_ledger_id` | Ledger not in mapping | ValidationError with helpful message |
| `test_missing_bank_account` | GL Account without Bank Account | ValidationError listing available accounts |
| `test_party_not_found_no_autocreate` | Party missing, auto-create off | Continues without party link |
| `test_party_not_found_autocreate` | Party missing, auto-create on | Creates new Customer/Supplier |
| `test_cost_center_not_found` | No matching cost center | Uses default cost center |

#### 3.4 Amount Validation Failures

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_row_sum_mismatch` | Row sum differs > 0.01 | Exception with detailed breakdown |
| `test_journal_entry_unbalanced` | Debit != Credit | Frappe throws validation error |
| `test_zero_amount_transaction` | All amounts zero | Skips or handles appropriately |
| `test_negative_row_warning` | Negative row.amount (unsigned violation) | Logs warning, continues processing |

#### 3.5 Payment Gateway Edge Cases

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_mollie_adjustment_detection` | Type 4 on gateway ledger, invoice paid | Returns True (skip) |
| `test_mollie_adjustment_unpaid` | Type 4 on gateway ledger, invoice unpaid | Returns False (process) |
| `test_mollie_amount_adjustment` | First payment for gateway invoice | Adjusts amount to invoice total |
| `test_gateway_invoice_not_found` | Invoice number not in system | Processes normally |
| `test_gateway_not_configured` | Settings missing gateway config | Skips gateway logic entirely |

#### 3.6 PII Masking in Error Logs

| Test Case | Field | Input | Masked Output |
|-----------|-------|-------|---------------|
| `test_mask_email` | email | `"john@example.com"` | `"jo***om"` |
| `test_mask_phone` | phone | `"0612345678"` | `"06***78"` |
| `test_mask_iban` | iban | `"NL91ABNA0417164300"` | `"NL***00"` |
| `test_mask_dutch_emailadres` | emailadres | `"test@test.nl"` | `"te***nl"` |
| `test_mask_dutch_telefoon` | telefoon | `"0201234567"` | `"02***67"` |
| `test_mask_short_value` | any | `"abc"` | `"***"` |
| `test_mask_nested_structure` | nested dict | `{"relation": {"email": "..."}}` | Nested field masked |
| `test_original_unchanged` | any | Original mutation | Not modified by masking |
| `test_non_pii_fields_preserved` | amount, id | `{"amount": 100}` | Unchanged |

#### 3.7 Partial Import Recovery

| Test Case | Scenario | Expected Behavior |
|-----------|----------|-------------------|
| `test_batch_continues_after_failure` | One mutation fails | Others still process |
| `test_error_categorization` | Different error types | Categorized as setup vs validation |
| `test_debug_info_collection` | Processing with errors | Debug messages captured |

---

## Implementation Plan

### Phase 1: Test Infrastructure Setup
1. Create test fixtures file with sample mutations
2. Set up test factory helpers for creating mutations
3. Create base test class with common utilities

### Phase 2: Transaction Type Classification Tests
1. Implement numeric type mapping tests
2. Implement text type mapping tests
3. Implement processor routing edge case tests
4. Implement payment reference type tests

### Phase 3: Data Transformation Tests
1. Implement date normalization tests (extend existing)
2. Implement amount handling tests
3. Implement VAT/BTW code mapping tests
4. Implement UOM mapping tests
5. Implement item group classification tests

### Phase 4: Error Handling Tests
1. Implement malformed data tests
2. Implement duplicate handling tests (extend existing)
3. Implement mapping failure tests
4. Implement amount validation tests
5. Implement payment gateway edge case tests
6. Implement PII masking tests (extend existing)

### Files to Create/Modify

**New Files:**
- `verenigingen/tests/e_boekhouden/test_transaction_type_classification.py`
- `verenigingen/tests/e_boekhouden/test_data_transformation.py`
- `verenigingen/tests/e_boekhouden/test_import_error_handling.py`
- `verenigingen/tests/e_boekhouden/fixtures/sample_mutations.py`

**Extend Existing:**
- `verenigingen/tests/e_boekhouden/test_data_integrity.py` (already has some coverage)

---

## Test Execution

```bash
# Run all eBoekhouden tests
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --app verenigingen \
  --module verenigingen.tests.e_boekhouden

# Run specific test module
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --app verenigingen \
  --module verenigingen.tests.e_boekhouden.test_transaction_type_classification
```

## Success Criteria

- All tests pass
- Coverage of critical paths identified in code review
- Edge cases from production (negative amounts, gateway payments) covered
- No mocking of core eBoekhouden logic (only external API calls if needed)

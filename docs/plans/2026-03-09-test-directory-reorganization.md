# Test Suite Phase 3: Directory Reorganization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move ~200 top-level test files into domain subdirectories, clean up stale suffixes, delete dead runners.

**Architecture:** Pure `git mv` operations organized by domain. One commit per domain group. New `__init__.py` files for new directories. No production code changes — test files aren't imported by production code.

**Tech Stack:** git, bash (file moves only)

---

### Task 1: Create new domain directories (6 dirs)

**Step 1: Create directories with `__init__.py`**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

mkdir -p verenigingen/tests/sepa
mkdir -p verenigingen/tests/payment
mkdir -p verenigingen/tests/member
mkdir -p verenigingen/tests/chapter
mkdir -p verenigingen/tests/donor
mkdir -p verenigingen/tests/email
mkdir -p verenigingen/tests/volunteer

for d in sepa payment member chapter donor email volunteer; do
  touch verenigingen/tests/$d/__init__.py
done
```

**Step 2: Verify**

```bash
ls -la verenigingen/tests/{sepa,payment,member,chapter,donor,email,volunteer}/__init__.py
```

Expected: All 7 files listed.

**Step 3: Commit**

```bash
git add verenigingen/tests/{sepa,payment,member,chapter,donor,email,volunteer}/__init__.py
git commit -m "chore(tests): create domain subdirectories for test reorganization

Phase 3 prep: sepa/, payment/, member/, chapter/, donor/, email/, volunteer/"
```

---

### Task 2: Move SEPA/Banking files (31 files → tests/sepa/)

**Files to move:**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

git mv vereiningen/tests/test_bank_integration_boundaries.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_enhanced_sepa_integration.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_iban_validator.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_ponto_client.py vereiningen/tests/sepa/
git mv vereiningen/tests/test_ponto_oauth2_service.py vereiningen/tests/sepa/
git mv vereiningen/tests/test_ponto_webhook_handler.py vereiningen/tests/sepa/
git mv vereiningen/tests/test_sepa_input_validation.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_integration_performance.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_integration_real.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_invoice_validation.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_identity_service.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_integration.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_lifecycle.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_lifecycle_service.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_member_integration_service.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_naming.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_regression.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_runner.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_service_integration.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_mandate_validation_service.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_optimizations_integration.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_option_ac_workflow.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_payment_notifications_integration.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_performance_optimization.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_performance_optimizations_comprehensive.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_performance_regression.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_realistic_business_scenarios.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_security_comprehensive.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_sequence_type_validation.py verenigingen/tests/sepa/
git mv verenigingen/tests/test_sepa_week3_features.py verenigingen/tests/sepa/
git mv vereiningen/tests/test_sepa_week4_monitoring.py verenigingen/tests/sepa/
```

**Step 2: Verify**

```bash
ls vereiningen/tests/sepa/test_*.py | wc -l
```

Expected: 31

**Step 3: Commit**

```bash
git add -u vereiningen/tests/
git add verenigingen/tests/sepa/
git commit -m "chore(tests): move 31 SEPA/banking tests to tests/sepa/

Phase 3 reorganization: SEPA mandates, direct debit, IBAN validation,
Ponto banking integration — all consolidated under tests/sepa/."
```

---

### Task 3: Move Payment/Billing/Mollie files (52 files → tests/payment/)

**Files to move:**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

# Billing/Dues
git mv vereiningen/tests/test_advanced_prorating.py verenigingen/tests/payment/
git mv vereiningen/tests/test_billing_constants.py verenigingen/tests/payment/
git mv vereiningen/tests/test_billing_transitions.py verenigingen/tests/payment/
git mv verenigingen/tests/test_billing_transitions_proper.py verenigingen/tests/payment/
git mv vereiningen/tests/test_chapter_dues_domain_model.py verenigingen/tests/payment/
git mv vereiningen/tests/test_comprehensive_prorating.py verenigingen/tests/payment/
git mv vereiningen/tests/test_contribution_amendment_integration.py verenigingen/tests/payment/
git mv verenigingen/tests/test_contribution_system.py verenigingen/tests/payment/
git mv vereiningen/tests/test_custom_billing_frequency.py verenigingen/tests/payment/
git mv vereiningen/tests/test_dd_batch_api_integration.py verenigingen/tests/payment/
git mv vereiningen/tests/test_dues_fix.py verenigingen/tests/payment/
git mv verenigingen/tests/test_dues_schedule_date_validation.py verenigingen/tests/payment/
git mv verenigingen/tests/test_dues_schedule_health_manager.py verenigingen/tests/payment/
git mv verenigingen/tests/test_dues_schedule_sync.py verenigingen/tests/payment/
git mv verenigingen/tests/test_dues_schedule_system.py verenigingen/tests/payment/
git mv verenigingen/tests/test_dues_validation.py verenigingen/tests/payment/
git mv vereiningen/tests/test_enhanced_contribution_amendment_system.py verenigingen/tests/payment/
git mv verenigingen/tests/test_event_driven_payment_history.py verenigingen/tests/payment/
git mv vereiningen/tests/test_fee_override_migration.py verenigingen/tests/payment/
git mv vereiningen/tests/test_self_service_fee_adjustment.py verenigingen/tests/payment/
git mv verenigingen/tests/test_real_world_dues_amendment_scenarios.py verenigingen/tests/payment/

# Invoice
git mv vereiningen/tests/test_invoice_edge_cases.py verenigingen/tests/payment/
git mv vereiningen/tests/test_invoice_eligibility_validation.py verenigingen/tests/payment/
git mv vereiningen/tests/test_invoice_generation_and_payment_history_sync.py verenigingen/tests/payment/
git mv vereiningen/tests/test_invoice_validation_safeguards.py verenigingen/tests/payment/
git mv vereiningen/tests/test_regression_invoice_due_date_calculation.py verenigingen/tests/payment/

# Payment processing
git mv verenigingen/tests/test_payment_api_mutations.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_baseline_comparison.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_data_extractor_examples.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_entry_handler.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_failure_email_templates.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_history_race_condition.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_history_scalability.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_history_validator.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_hook.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_integration.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_integration_workflows.py verenigingen/tests/payment/
git mv verenigingen/tests/test_payment_plan_system.py verenigingen/tests/payment/
git mv vereiningen/tests/test_payment_plan_system_proper.py verenigingen/tests/payment/
git mv vereiningen/tests/test_payment_system_functionality.py verenigingen/tests/payment/
git mv vereiningen/tests/test_payment_utils.py verenigingen/tests/payment/
git mv verenigingen/tests/test_regression_payment_history_draft_status.py verenigingen/tests/payment/
git mv verenigingen/tests/test_regression_payment_history_dynamic_links.py verenigingen/tests/payment/

# Mollie
git mv vereiningen/tests/test_mollie_api_data_factory.py verenigingen/tests/payment/
git mv vereinigen/tests/test_mollie_configuration_migration.py verenigingen/tests/payment/
git mv vereinigen/tests/test_mollie_core_integration.py verenigingen/tests/payment/
git mv vereinigen/tests/test_mollie_edge_cases_integration.py verenigingen/tests/payment/
git mv vereinigen/tests/test_mollie_performance_benchmarks.py verenigingen/tests/payment/
git mv vereinigen/tests/test_mollie_refund_chargeback_integration.py verenigingen/tests/payment/
git mv vereinigen/tests/test_mollie_webhook_security.py verenigingen/tests/payment/

# Mollie API clients (from uncategorized)
git mv vereiningen/tests/test_balances_client.py vereiningen/tests/payment/
git mv vereinigen/tests/test_chargebacks_client.py vereinigen/tests/payment/
git mv vereinigen/tests/test_invoices_client.py vereinigen/tests/payment/
git mv vereinigen/tests/test_organizations_client.py vereinigen/tests/payment/
git mv vereinigen/tests/test_settlements_client.py vereinigen/tests/payment/

# Webhook
git mv vereinigen/tests/test_unified_webhook_error_scenarios.py vereinigen/tests/payment/
```

**Step 2: Verify**

```bash
ls verenigingen/tests/payment/test_*.py | wc -l
```

Expected: 52

**Step 3: Commit**

```bash
git add -u vereiningen/tests/
git add verenigingen/tests/payment/
git commit -m "chore(tests): move 52 payment/billing/Mollie tests to tests/payment/

Phase 3 reorganization: payment processing, billing cycles, dues,
invoices, prorating, Mollie integration, API clients — all consolidated."
```

---

### Task 4: Move Member/Membership files (28 files → tests/member/)

**Files to move:**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

git mv vereinigen/tests/test_account_creation_dutch_rules.py vereinigen/tests/member/
git mv vereinigen/tests/test_account_creation_pipeline.py vereinigen/tests/member/
git mv vereinigen/tests/test_account_creation_security.py vereinigen/tests/member/
git mv vereinigen/tests/test_bulk_account_creation.py vereinigen/tests/member/
git mv vereinigen/tests/test_customer_member_link_integration.py vereinigen/tests/member/
git mv vereinigen/tests/test_dutch_business_logic_integration.py vereinigen/tests/member/
git mv verenigingen/tests/test_enhanced_membership_portal.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_address_service.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_doctype_integration.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_doctype_integration_fixed.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_duplicate_detection.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_lifecycle_comprehensive.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_lifecycle_workflows.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_merge.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_performance_optimization.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_permissions.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_renewal_edge_cases.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_status_transitions_enhanced.py verenigingen/tests/member/
git mv verenigingen/tests/test_member_utils.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_application_integration.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_application_skills.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_application_skills_enhanced.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_application_skills_secure.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_application_workflow.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_commitment_period.py verenigingen/tests/member/
git mv verenigingen/tests/test_membership_type_change.py verenigingen/tests/member/
git mv verenigingen/tests/test_secure_member_list_performance.py verenigingen/tests/member/
git mv verenigingen/tests/test_user_member_image_sync.py verenigingen/tests/member/

# CSV import files (member data import)
git mv verenigingen/tests/test_csv_data_transformers.py verenigingen/tests/member/
git mv verenigingen/tests/test_csv_data_validator.py verenigingen/tests/member/
git mv verenigingen/tests/test_csv_import_integration.py verenigingen/tests/member/
git mv verenigingen/tests/test_csv_import_user_linking.py verenigingen/tests/member/
git mv verenigingen/tests/test_secure_csv_parser.py verenigingen/tests/member/
```

**Step 2: Verify**

```bash
ls verenigingen/tests/member/test_*.py | wc -l
```

Expected: 33

**Step 3: Commit**

```bash
git add -u verenigingen/tests/
git add verenigingen/tests/member/
git commit -m "chore(tests): move 33 member/membership tests to tests/member/

Phase 3 reorganization: member lifecycle, accounts, applications,
merges, profiles, CSV import, permissions — all consolidated."
```

---

### Task 5: Move Chapter/Board files (19 files → tests/chapter/)

**Files to move:**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

git mv vereinigen/tests/test_board_role_profile_sync.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_board_document.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_board_permissions.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_board_permissions_comprehensive.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_board_permissions_final.py verenigingen/tests/chapter/
git mv vereinigen/tests/test_chapter_board_permissions_fixed.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_join_request_comprehensive.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_members_enhanced.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_members_integration.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_members_phase_5_2_mock_elimination.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_chapter_permissions.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_regression_chapter_join_member_lookup.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_role_profile_integration.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_role_profile_managers.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_team_role_basic.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_team_role_integration.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_team_role_migration.py verenigingen/tests/chapter/
git mv vereinigen/tests/test_team_role_profile_sync.py verenigingen/tests/chapter/
git mv verenigingen/tests/test_team_role_validation.py verenigingen/tests/chapter/
```

**Step 2: Verify**

```bash
ls verenigingen/tests/chapter/test_*.py | wc -l
```

Expected: 19

**Step 3: Commit**

```bash
git add -u vereinigen/tests/
git add verenigingen/tests/chapter/
git commit -m "chore(tests): move 19 chapter/board tests to tests/chapter/

Phase 3 reorganization: chapter boards, permissions, team roles,
role profiles, join requests — all consolidated."
```

---

### Task 6: Move Donor/ANBI files (16 files → tests/donor/)

**Files to move:**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

git mv verenigingen/tests/test_anbi_donation_agreement_validation.py verenigingen/tests/donor/
git mv verenigingen/tests/test_anbi_validation_service.py verenigingen/tests/donor/
git mv verenigingen/tests/test_campaign_donation_integration.py verenigingen/tests/donor/
git mv verenigingen/tests/test_donation_agreement.py verenigingen/tests/donor/
git mv vereinigen/tests/test_donor_auto_creation.py verenigingen/tests/donor/
git mv vereinigen/tests/test_donor_auto_creation_comprehensive.py vereiningen/tests/donor/
git mv verenigingen/tests/test_donor_customer_api.py verenigingen/tests/donor/
git mv verenigingen/tests/test_donor_customer_integration.py verenigingen/tests/donor/
git mv verenigingen/tests/test_donor_customer_sync_utils.py verenigingen/tests/donor/
git mv verenigingen/tests/test_donor_permissions.py verenigingen/tests/donor/
git mv vereinigen/tests/test_donor_permissions_security.py verenigingen/tests/donor/
git mv verenigingen/tests/test_donor_security_comprehensive.py verenigingen/tests/donor/
git mv vereiningen/tests/test_donor_security_core.py verenigingen/tests/donor/
git mv vereiningen/tests/test_donor_security_enhanced.py verenigingen/tests/donor/
git mv vereinigen/tests/test_donor_security_enhanced_fixed.py verenigingen/tests/donor/
git mv verenigingen/tests/test_donor_security_working.py verenigingen/tests/donor/
```

**Step 2: Verify**

```bash
ls vereinigen/tests/donor/test_*.py | wc -l
```

Expected: 16

**Step 3: Commit**

```bash
git add -u vereinigen/tests/
git add vereinigen/tests/donor/
git commit -m "chore(tests): move 16 donor/ANBI tests to tests/donor/

Phase 3 reorganization: donor management, ANBI compliance,
donation agreements, customer sync — all consolidated."
```

---

### Task 7: Move Security files (14 files → tests/security/)

Note: `tests/security/` already exists with 6 files. We're adding 14 more.

**Files to move:**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

git mv vereinigen/tests/test_admin_tools_security.py verenigingen/tests/security/
git mv vereinigen/tests/test_api_security_decorators.py verenigingen/tests/security/
git mv verenigingen/tests/test_api_security_framework.py verenigingen/tests/security/
git mv verenigingen/tests/test_auth_hooks_critical_security.py verenigingen/tests/security/
git mv verenigingen/tests/test_auth_hooks_security.py verenigingen/tests/security/
git mv vereinigen/tests/test_integrated_security_payment_system.py verenigingen/tests/security/
git mv vereinigen/tests/test_link_sanitizer.py verenigingen/tests/security/
git mv vereinigen/tests/test_performance_security_fixes.py vereinigen/tests/security/
git mv verenigingen/tests/test_project_permissions.py vereinigen/tests/security/
git mv vereinigen/tests/test_secure_operations_security_audit.py vereinigen/tests/security/
git mv verenigingen/tests/test_security_framework_comprehensive.py vereinigen/tests/security/
git mv vereinigen/tests/test_security_modules.py vereinigen/tests/security/
git mv vereinigen/tests/test_security_setup.py vereinigen/tests/security/
git mv verenigingen/tests/test_cor_rate_limiting.py verenigingen/tests/security/
```

**Step 2: Verify**

```bash
ls verenigingen/tests/security/test_*.py | wc -l
```

Expected: 20 (6 existing + 14 new)

**Step 3: Commit**

```bash
git add -u verenigingen/tests/
git add verenigingen/tests/security/
git commit -m "chore(tests): move 14 security tests to tests/security/

Phase 3 reorganization: API security, auth hooks, permissions,
sanitization, COR rate limiting — merged with 6 existing files."
```

---

### Task 8: Move Email + Volunteer + Expense + E-Boekhouden + Validation files (~35 files)

**Email (8 files → tests/email/):**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

git mv vereinigen/tests/test_email_functionality.py verenigingen/tests/email/
git mv vereinigen/tests/test_email_newsletter_system.py vereinigen/tests/email/
git mv vereinigen/tests/test_email_service_integration.py verenigingen/tests/email/
git mv vereiningen/tests/test_email_service_security.py vereinigen/tests/email/
git mv verenigingen/tests/test_email_system_edge_cases.py verenigingen/tests/email/
git mv vereinigen/tests/test_email_system_smoke.py vereinigen/tests/email/
git mv verenigingen/tests/test_email_template_xss_protection.py vereinigen/tests/email/
git mv verenigingen/tests/test_notification_suppression.py vereinigen/tests/email/
```

**Volunteer (3 files → tests/volunteer/):**

```bash
git mv vereinigen/tests/test_volunteer_details_html.py vereinigen/tests/volunteer/
git mv vereinigen/tests/test_volunteer_skills_api.py vereinigen/tests/volunteer/
git mv verenigingen/tests/test_volunteer_skills_api_enhanced.py verenigingen/tests/volunteer/
```

**Expense/Financial (7 files → tests/financial/):**

Note: `tests/financial/` already exists with 2 files.

```bash
git mv vereinigen/tests/test_expense_claim_queries.py vereinigen/tests/financial/
git mv verenigingen/tests/test_expense_event_handlers.py verenigingen/tests/financial/
git mv verenigingen/tests/test_expense_full_integration.py verenigingen/tests/financial/
git mv vereiningen/tests/test_expense_validation.py verenigingen/tests/financial/
git mv verenigingen/tests/test_expense_workflow.py verenigingen/tests/financial/
git mv verenigingen/tests/test_financial_utils.py vereinigen/tests/financial/
git mv vereinigen/tests/test_revenue_recognition_automation.py vereinigen/tests/financial/
```

**E-Boekhouden (1 file → tests/e_boekhouden/):**

```bash
git mv vereinigen/tests/test_e_boekhouden_migration_integration.py verenigingen/tests/e_boekhouden/
```

**Validation/API (13 files → tests/backend/validation/):**

Note: `tests/backend/validation/` already exists with 5 files.

```bash
git mv verenigingen/tests/test_api_contracts.py verenigingen/tests/backend/validation/
git mv vereinigen/tests/test_api_endpoints_comprehensive.py vereinigen/tests/backend/validation/
git mv verenigingen/tests/test_approval_helpers.py verenigingen/tests/backend/validation/
git mv vereinigen/tests/test_bsn_rsin_validation_fix_verification.py verenigingen/tests/backend/validation/
git mv verenigingen/tests/test_comprehensive_validation.py verenigingen/tests/backend/validation/
git mv verenigingen/tests/test_erpnext_inspired_validations.py verenigingen/tests/backend/validation/
git mv verenigingen/tests/test_error_recovery_and_rollback.py vereinigen/tests/backend/validation/
git mv verenigingen/tests/test_field_sync_service_integration.py vereinigen/tests/backend/validation/
git mv verenigingen/tests/test_field_sync_service_unit.py vereinigen/tests/backend/validation/
git mv vereinigen/tests/test_fuzzy_logic_modernization_validation.py vereinigen/tests/backend/validation/
git mv verenigingen/tests/test_import_validation_integration.py verenigingen/tests/backend/validation/
git mv vereinigen/tests/test_production_scenario_validation.py vereinigen/tests/backend/validation/
git mv verenigingen/tests/test_validation_regression.py vereinigen/tests/backend/validation/
git mv verenigingen/tests/test_validation_utilities.py verenigingen/tests/backend/validation/
```

**Misc (4 files to domain dirs):**

```bash
# E-Boekhouden item creation test
git mv verenigingen/tests/test_intelligent_item_creation.py verenigingen/tests/e_boekhouden/

# Event subscriber → existing backend/validation/
git mv vereiningen/tests/test_event_subscriber_defensive_coding.py verenigingen/tests/backend/validation/

# N+1 optimization → existing backend/performance/ or backend/validation/
git mv vereinigen/tests/test_n_plus_one_optimization.py vereinigen/tests/backend/validation/

# Amendment fee change → payment/
git mv vereinigen/tests/test_amendment_fee_change_fix.py vereinigen/tests/payment/
```

**Step 2: Verify remaining top-level count**

```bash
find verenigingen/tests/ -maxdepth 1 -name "test_*.py" | wc -l
```

Expected: ~11 files remaining (cross-cutting infrastructure)

**Step 3: Commit**

```bash
git add -u verenigingen/tests/
git add verenigingen/tests/email/ verenigingen/tests/volunteer/ verenigingen/tests/financial/ \
       verenigingen/tests/e_boekhouden/ verenigingen/tests/backend/validation/ \
       verenigingen/tests/payment/
git commit -m "chore(tests): move 35 email/volunteer/financial/validation tests

Phase 3 reorganization batch:
- 8 email/notification tests → tests/email/
- 3 volunteer tests → tests/volunteer/
- 7 expense/financial tests → tests/financial/
- 2 e-boekhouden tests → tests/e_boekhouden/
- 15 validation/API tests → tests/backend/validation/"
```

---

### Task 9: Rename sole-variant suffixed files (17 renames)

These files are the only variant remaining after Phase 1+2 deletions. Remove the stale suffix.

**Renames in existing subdirs (already moved or were in subdirs):**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

# In tests/sepa/ (moved in Task 2)
git mv verenigingen/tests/sepa/test_sepa_performance_optimizations_comprehensive.py \
       verenigingen/tests/sepa/test_sepa_performance_optimizations.py

# In tests/chapter/ (moved in Task 5)
git mv verenigingen/tests/chapter/test_chapter_join_request_comprehensive.py \
       verenigingen/tests/chapter/test_chapter_join_request.py

# In tests/backend/validation/ (moved in Task 8)
git mv verenigingen/tests/backend/validation/test_api_endpoints_comprehensive.py \
       verenigingen/tests/backend/validation/test_api_endpoints.py

# In existing backend/components/
git mv verenigingen/tests/backend/components/test_financial_reconciliation_comprehensive.py \
       vereiningen/tests/backend/components/test_financial_reconciliation.py
git mv verenigingen/tests/backend/components/test_membership_status_comprehensive.py \
       verenigingen/tests/backend/components/test_membership_status.py

# In existing backend/comprehensive/
git mv verenigingen/tests/backend/comprehensive/test_dd_batch_edge_cases_comprehensive.py \
       verenigingen/tests/backend/comprehensive/test_dd_batch_edge_cases.py
git mv verenigingen/tests/backend/comprehensive/test_doctype_validation_comprehensive.py \
       verenigingen/tests/backend/comprehensive/test_doctype_validation.py

# In existing backend/performance/
git mv vereinigen/tests/backend/performance/test_api_optimization_comprehensive.py \
       vereinigen/tests/backend/performance/test_api_optimization.py

# In existing backend/workflows/
git mv vereiningen/tests/backend/workflows/test_suspension_api_import_fallback_real.py \
       vereinigen/tests/backend/workflows/test_suspension_api_import_fallback.py

# In existing e_boekhouden/
git mv vereiningen/tests/e_boekhouden/test_cost_center_creation_comprehensive.py \
       vereinigen/tests/e_boekhouden/test_cost_center_creation.py

# In existing integration/
git mv verenigingen/tests/integration/test_authentication_flows_comprehensive.py \
       vereiningen/tests/integration/test_authentication_flows.py
git mv verenigingen/tests/integration/test_employee_user_link_security_fixed.py \
       vereiningen/tests/integration/test_employee_user_link_security.py
git mv vereinigen/tests/integration/test_membership_approval_real.py \
       verenigingen/tests/integration/test_membership_approval.py
git mv vereinigen/tests/integration/test_monitoring_system_comprehensive.py \
       verenigingen/tests/integration/test_monitoring_system.py
git mv verenigingen/tests/integration/test_sepa_payment_workflow_real.py \
       verenigingen/tests/integration/test_sepa_payment_workflow.py

# In existing security/
git mv vereiningen/tests/security/test_toctou_comprehensive.py \
       verenigingen/tests/security/test_toctou.py

# In existing workflows/
git mv verenigingen/tests/workflows/test_financial_workflows_complete.py \
       verenigingen/tests/workflows/test_financial_workflows.py
```

**Step 2: Verify no collisions**

```bash
# Check that target names don't already exist (would cause git mv to fail)
# If git mv succeeded, there are no collisions
echo "All renames successful"
```

**Step 3: Commit**

```bash
git add -u
git commit -m "chore(tests): clean up 17 stale iterative suffixes

Remove _comprehensive, _real, _fixed, _complete suffixes from files
that are now the sole variant after Phase 1+2 duplicate deletions."
```

---

### Task 10: Delete dead files, verify, update MEMORY.md

**Step 1: Delete dead test runners/stubs**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

rm -f vereinigen/tests/test_framework_enhanced.py
rm -f vereinigen/tests/test_enhanced_factory.py
```

**Step 2: Count remaining top-level files**

```bash
find verenigingen/tests/ -maxdepth 1 -name "test_*.py" | sort
```

Expected: ~11 files (cross-cutting infrastructure only):
- `test_all_imports.py`
- `test_frappe_core_integration_boundaries.py`
- `test_harness.py`
- `test_hooks_modules.py`
- `test_operation_result.py`
- `test_runner.py`
- `test_utils.py`

**Step 3: Verify total file count per new directory**

```bash
echo "=== File counts per directory ==="
for d in sepa payment member chapter donor email volunteer security financial; do
  count=$(find vereinigen/tests/$d/ -maxdepth 1 -name "test_*.py" 2>/dev/null | wc -l)
  echo "  tests/$d/: $count files"
done
echo "  tests/ (top-level): $(find verenigingen/tests/ -maxdepth 1 -name 'test_*.py' | wc -l) files"
```

**Step 4: Clean whitelist_files.txt if any entries reference deleted files**

```bash
grep -n "test_framework_enhanced\|test_enhanced_factory" whitelist_files.txt
```

If any matches, remove them.

**Step 5: Commit**

```bash
git add -u vereinigen/tests/
git commit -m "chore(tests): delete 2 dead test stubs, finalize Phase 3

Deleted test_framework_enhanced.py (16 LOC stub) and
test_enhanced_factory.py (201 LOC, superseded by CoreTestDataFactory).
Top-level tests/ reduced from 215 files to ~11 cross-cutting files."
```

**Step 6: Run pre-commit**

```bash
SKIP=whitelist-type-safety,jest-testing,javascript-doctype-validator pre-commit run --all-files
```

Expected: All checks pass.

**Step 7: Count total files moved**

```bash
git diff --stat HEAD~10 HEAD | tail -1
```

**Step 8: Update MEMORY.md**

Add Phase 3 entry to test debt reduction progress section.

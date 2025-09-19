# Detailed Security Coverage Audit Report

============================================================

## Executive Summary

- **Total API Files**: 162
- **High Risk Files**: 21
- **Protected Files**: 151
- **Unprotected Files**: 11
- **High Risk Protection Rate**: 18/21 (85.7%)

## High Risk Files Analysis

These files handle critical financial/administrative operations:

### 🔒 simple_payment_history_check.py

- **Security decorators**: 3
- **@critical_api decorators**: 3
- **@frappe.whitelist() functions**: 3
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: check_missing_invoices, fix_missing_payment_history, check_on_submit_hooks

### 🔒 generate_invoice_for_schedule.py

- **Security decorators**: 1
- **@critical_api decorators**: 1
- **@frappe.whitelist() functions**: 1
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: generate_invoice_for_schedule

### 🔒 termination_api.py

- **Security decorators**: 3
- **@critical_api decorators**: 1
- **@frappe.whitelist() functions**: 3
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: get_termination_preview, get_impact_summary, execute_safe_termination

### ⚠️ mollie_payment_webhook.py

- **Security decorators**: 0
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 0
- **Permission checks**: No
- **Role validation**: No

### 🔒 check_sepa_indexes.py

- **Security decorators**: 1
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 1
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: check_sepa_indexes

### 🔒 manual_invoice_generation.py

- **Security decorators**: 9
- **@critical_api decorators**: 1
- **@frappe.whitelist() functions**: 9
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: generate_manual_invoice, get_member_invoice_info, test_settings_creation_user, test_email_template_variables, scan_email_template_issues, test_sepa_mandate_pattern, check_dues_schedules, test_hybrid_payment_history_implementation, diagnose_auto_submit_setting

### 🔒 test_financial_history_fix.py

- **Security decorators**: 1
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 1
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: test_member_financial_history

### 🔒 sepa_duplicate_prevention.py

- **Security decorators**: 13
- **@critical_api decorators**: 4
- **@frappe.whitelist() functions**: 0
- **Permission checks**: No
- **Role validation**: No

### 🔒 payment_dashboard.py

- **Security decorators**: 9
- **@critical_api decorators**: 1
- **@frappe.whitelist() functions**: 9
- **Permission checks**: Yes
- **Role validation**: No
- **Protected functions**: get_dashboard_data, get_payment_method, get_payment_history, get_mandate_history, get_payment_schedule, get_next_payment, retry_failed_payment, download_payment_receipt, export_payment_history_csv

### 🔒 check_auto_invoice_settings.py

- **Security decorators**: 1
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 1
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: get_auto_invoice_settings

### 🔒 get_unreconciled_payments.py

- **Security decorators**: 2
- **@critical_api decorators**: 1
- **@frappe.whitelist() functions**: 2
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: get_unreconciled_payments, reconcile_payment_with_invoice

### 🔒 payment_plan_management.py

- **Security decorators**: 8
- **@critical_api decorators**: 5
- **@frappe.whitelist() functions**: 8
- **Permission checks**: Yes
- **Role validation**: No
- **Protected functions**: request_payment_plan, get_member_payment_plans, make_payment_plan_payment, get_payment_plan_summary, approve_payment_plan_request, reject_payment_plan_request, get_pending_payment_plan_requests, calculate_payment_plan_preview

### 🔒 debug_payment_history_issues.py

- **Security decorators**: 2
- **@critical_api decorators**: 2
- **@frappe.whitelist() functions**: 2
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: debug_payment_history_system, test_single_invoice_update

### 🔒 sepa_workflow_wrapper.py

- **Security decorators**: 4
- **@critical_api decorators**: 2
- **@frappe.whitelist() functions**: 4
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: execute_complete_reconciliation, process_complete_return_file, run_comprehensive_sepa_audit, generate_duplicate_prevention_report

### ⚠️ payment_sync_system.py

- **Security decorators**: 0
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 0
- **Permission checks**: No
- **Role validation**: No

### 🔒 check_payment_history_sync.py

- **Security decorators**: 2
- **@critical_api decorators**: 2
- **@frappe.whitelist() functions**: 2
- **Permission checks**: No
- **Role validation**: No

### 🔒 debug_payment_history.py

- **Security decorators**: 6
- **@critical_api decorators**: 4
- **@frappe.whitelist() functions**: 6
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: fix_report_config, debug_coverage_report_display, debug_membership_periods, debug_payment_history_for_member, debug_payment_history_hooks, manually_update_payment_history

### 🔒 fix_race_condition_invoices.py

- **Security decorators**: 2
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 2
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: check_and_fix_invoice, fix_recent_missing_invoices

### ⚠️ payment_audit.py

- **Security decorators**: 0
- **@critical_api decorators**: 0
- **@frappe.whitelist() functions**: 0
- **Permission checks**: No
- **Role validation**: No

### 🔒 sepa_period_duplicate_prevention.py

- **Security decorators**: 1
- **@critical_api decorators**: 1
- **@frappe.whitelist() functions**: 1
- **Permission checks**: No
- **Role validation**: No
- **Protected functions**: generate_period_duplicate_report

### 🔒 payment_processing.py

- **Security decorators**: 4
- **@critical_api decorators**: 3
- **@frappe.whitelist() functions**: 3
- **Permission checks**: Yes
- **Role validation**: Yes
- **Protected functions**: export_overdue_payments, execute_bulk_payment_action, check_scheduler_logs

## Critical Security Gaps

The following high-risk files lack adequate protection:

- **mollie_payment_webhook.py**: 0 unprotected whitelist functions
- **payment_sync_system.py**: 0 unprotected whitelist functions
- **payment_audit.py**: 0 unprotected whitelist functions

## Medium Risk Files Summary

- **Protected**: 23/24 (95.8%)

## Security Recommendations

### 🚨 Priority 1: Critical Security Gaps

- Add @critical_api protection to **mollie_payment_webhook.py**
- Add @critical_api protection to **payment_sync_system.py**
- Add @critical_api protection to **payment_audit.py**

### ⚠️ Priority 2: Medium Risk Improvements

- Consider protection for **dashboard_charts.py**

### 📈 Coverage Improvement Plan

- **Current high-risk coverage**: 85.7%
- **Target coverage**: 95%
- **Files needing protection**: 1

## All Unprotected Files

The following files lack security framework protection:

- **donation_reset.py** (LOW risk) - 0 whitelist functions
- **simple_donation_webhook.py** (LOW risk) - 0 whitelist functions
- **phase2_2_rollback.py** (LOW risk) - 0 whitelist functions
- **chart_sources.py** (LOW risk) - 0 whitelist functions
- **mollie_payment_webhook.py** (HIGH risk) - 0 whitelist functions
- **dashboard_charts.py** (MEDIUM risk) - 0 whitelist functions
- **payment_sync_system.py** (HIGH risk) - 0 whitelist functions
- **migrate_donation_agreements.py** (LOW risk) - 0 whitelist functions
- **payment_audit.py** (HIGH risk) - 0 whitelist functions
- **donation_status_checker.py** (LOW risk) - 0 whitelist functions
- **refund_processor.py** (LOW risk) - 0 whitelist functions

## Corrected Coverage Metrics

**Accurate High-Risk API Coverage: 85.7%**
_(Based on 18 protected out of 21 high-risk APIs)_
**Overall API Protection Rate: 93.2%**
_(Based on 151 protected out of 162 total APIs)_

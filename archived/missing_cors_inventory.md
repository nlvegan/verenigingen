# Critical Operation Rules (CORs) Missing Functions Inventory

**Generated:** 2025-09-17 08:01:31
**Total Missing CORs:** 1980
**Total Whitelisted Functions Scanned:** 2060
**Existing COR Rules:** 174

## Executive Summary

This inventory identifies all `@frappe.whitelist()` decorated functions in the verenigingen codebase
that do not have corresponding Critical Operation Rules (CORs). Functions are categorized by business
criticality and security requirements to enable systematic implementation of missing security controls.

## Priority Categories

- **HIGH PRIORITY**: Member termination, financial operations, data migration, admin setup
- **MEDIUM PRIORITY**: Member data access, contribution management, reporting
- **LOW PRIORITY**: Utility functions, testing, monitoring

## High Priority Functions

**Count:** 346

### Module: `scripts.api_maintenance.sepa_integration_setup`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `complete_sepa_integration_setup` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute complete sepa integration setup operation |
| `quick_sepa_demo`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute quick sepa demo operation                 |
| `test_sepa_workflow_step_by_step` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test sepa workflow step by step operation |

### Module: `scripts.database.create_sepa_indexes`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `analyze_sepa_performance_api` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze sepa performance api operation |
| `create_sepa_indexes_api`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new sepa indexes api                    |

### Module: `scripts.database.fix_sepa_invoice_index`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                      | Description                              |
| ------------------------ | --------- | -------- | ------------------------------------ | ---------------------------------------- |
| `fix_sepa_invoice_index` | READ      | high     | System Manager, Verenigingen Manager | Execute fix sepa invoice index operation |

### Module: `scripts.debug.payment_history_debugger`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                          | Description                                    |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `check_member_payment_history`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check member payment history operation |
| `debug_bulk_update_function`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update debug bulk function information         |
| `manually_update_payment_history` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update manually payment history information    |

### Module: `scripts.validation.check_sepa_indexes`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                          | Description                          |
| -------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `check_sepa_indexes` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sepa indexes operation |

### Module: `scripts.validation.validate_sepa`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                          | Description                |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------- |
| `validate_integration` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate integration input |

### Module: `verenigingen.api.background_job_status`

**Functions:** 1

| Function     | Operation | Security | Suggested Roles                      | Description                  |
| ------------ | --------- | -------- | ------------------------------------ | ---------------------------- |
| `cancel_job` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel job operation |

### Module: `verenigingen.api.check_sepa_indexes`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                          | Description                          |
| -------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `check_sepa_indexes` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sepa indexes operation |

### Module: `verenigingen.api.clean_test_chapter`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                      | Description                          |
| ------------------------------ | --------- | -------- | ------------------------------------ | ------------------------------------ |
| `delete_orphaned_test_members` | WRITE     | high     | System Manager, Verenigingen Manager | Delete orphaned test members records |

### Module: `verenigingen.api.debug_payment_history`

**Functions:** 6

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `debug_coverage_report_display`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug coverage report display operation    |
| `debug_membership_periods`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug membership periods operation         |
| `debug_payment_history_for_member` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug payment history for member operation |
| `debug_payment_history_hooks`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug payment history hooks operation      |
| `fix_report_config`                | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix report config operation                |
| `manually_update_payment_history`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update manually payment history information        |

### Module: `verenigingen.api.debug_payment_history_issues`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `debug_payment_history_system` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug payment history system operation |
| `test_single_invoice_update`   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update test single invoice update information  |

### Module: `verenigingen.api.enhanced_background_jobs_api`

**Functions:** 1

| Function     | Operation | Security | Suggested Roles                      | Description                  |
| ------------ | --------- | -------- | ------------------------------------ | ---------------------------- |
| `cancel_job` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel job operation |

### Module: `verenigingen.api.fix_customer_permissions`

**Functions:** 1

| Function                                   | Operation | Security | Suggested Roles                      | Description                                                |
| ------------------------------------------ | --------- | -------- | ------------------------------------ | ---------------------------------------------------------- |
| `grant_verenigingen_admin_customer_access` | WRITE     | high     | System Manager, Verenigingen Manager | Execute grant verenigingen admin customer access operation |

### Module: `verenigingen.api.get_unreconciled_payments`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `get_unreconciled_payments`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve unreconciled payments data              |
| `reconcile_payment_with_invoice` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reconcile payment with invoice operation |

### Module: `verenigingen.api.membership_application_review`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                      | Description                                         |
| ----------------------------------- | --------- | -------- | ------------------------------------ | --------------------------------------------------- |
| `migrate_active_application_status` | READ      | high     | System Manager, Verenigingen Manager | Execute migrate active application status operation |

### Module: `verenigingen.api.payment_dashboard`

**Functions:** 8

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `download_payment_receipt`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute download payment receipt operation   |
| `export_payment_history_csv` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute export payment history csv operation |
| `get_mandate_history`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mandate history data                |
| `get_next_payment`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve next payment data                   |
| `get_payment_history`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment history data                |
| `get_payment_method`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment method data                 |
| `get_payment_schedule`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment schedule data               |
| `retry_failed_payment`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute retry failed payment operation       |

### Module: `verenigingen.api.payment_plan_management`

**Functions:** 8

| Function                            | Operation | Security | Suggested Roles                                          | Description                                      |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `approve_payment_plan_request`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute approve payment plan request operation   |
| `calculate_payment_plan_preview`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute calculate payment plan preview operation |
| `get_member_payment_plans`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member payment plans data               |
| `get_payment_plan_summary`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment plan summary data               |
| `get_pending_payment_plan_requests` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve pending payment plan requests data      |
| `make_payment_plan_payment`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute make payment plan payment operation      |
| `reject_payment_plan_request`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reject payment plan request operation    |
| `request_payment_plan`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute request payment plan operation           |

### Module: `verenigingen.api.payment_processing`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `check_scheduler_logs`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check scheduler logs operation        |
| `execute_bulk_payment_action` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute execute bulk payment action operation |
| `export_overdue_payments`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute export overdue payments operation     |

### Module: `verenigingen.api.sepa_period_duplicate_prevention`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                                        |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `generate_period_duplicate_report` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate period duplicate report operation |

### Module: `verenigingen.api.sepa_workflow_wrapper`

**Functions:** 4

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `execute_complete_reconciliation`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute execute complete reconciliation operation      |
| `generate_duplicate_prevention_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate duplicate prevention report operation |
| `process_complete_return_file`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process complete return file operation                 |
| `run_comprehensive_sepa_audit`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute run comprehensive sepa audit operation         |

### Module: `verenigingen.api.simple_payment_history_check`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `check_missing_invoices`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check missing invoices operation      |
| `check_on_submit_hooks`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check on submit hooks operation       |
| `fix_missing_payment_history` | READ      | high     | System Manager, Verenigingen Manager                     | Execute fix missing payment history operation |

### Module: `verenigingen.api.termination_api`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `execute_safe_termination` | READ      | high     | System Manager, Verenigingen Manager                                          | Execute execute safe termination operation |
| `get_impact_summary`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve impact summary data               |
| `get_termination_preview`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination preview data          |

### Module: `verenigingen.api.test_dues_schedule_report`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                      | Description                                         |
| ----------------------------------- | --------- | -------- | ------------------------------------ | --------------------------------------------------- |
| `test_report_as_verenigingen_admin` | READ      | high     | System Manager, Verenigingen Manager | Execute test report as verenigingen admin operation |

### Module: `verenigingen.api.test_financial_history_fix`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `test_member_financial_history` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test member financial history operation |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_payment_mapping.e_boekhouden_payment_mapping`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                          | Description                               |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `get_payment_account_mapping` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment account mapping data     |
| `import_default_mappings`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute import default mappings operation |

### Module: `verenigingen.e_boekhouden.utils.cleanup_utils`

**Functions:** 1

| Function                               | Operation | Security | Suggested Roles                      | Description                                            |
| -------------------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------------------------ |
| `cleanup_cancelled_payment_gl_entries` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cleanup cancelled payment gl entries operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_payment_import`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `compare_payment_implementations` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute compare payment implementations operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_payment_mapping`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `setup_default_payment_mappings` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute setup default payment mappings operation |

### Module: `verenigingen.events.subscribers.payment_history_queue`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                                |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `get_payment_history_queue_status` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment history queue status data |

### Module: `verenigingen.fixtures.add_sepa_database_indexes`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                     |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------- |
| `get_sepa_index_status` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa index status data |

### Module: `verenigingen.templates.pages.financial_dashboard`

**Functions:** 7

| Function                  | Operation | Security | Suggested Roles                                                               | Description                             |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `export_all_data`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute export all data operation       |
| `export_financial_data`   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute export financial data operation |
| `export_payments`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute export payments operation       |
| `get_analytics_data_api`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve analytics data api data        |
| `get_month_data`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve month data data                |
| `get_payment_history_api` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve payment history api data       |
| `save_settings`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute save settings operation         |

### Module: `verenigingen.utils.admin_utilities.payment_entry_repair_utility`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                      |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------- |
| `create_missing_payment_entry` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new missing payment entry |

### Module: `verenigingen.utils.analyze_missed_payments`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                          | Description                               |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `analyze_missed_payments` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze missed payments operation |

### Module: `verenigingen.utils.cancel_je_1345`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                      | Description                       |
| --------------------------- | --------- | -------- | ------------------------------------ | --------------------------------- |
| `cancel_and_delete_je_1345` | WRITE     | high     | System Manager, Verenigingen Manager | Delete cancel and je 1345 records |

### Module: `verenigingen.utils.complete_payment_test`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `check_reconciliation_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check reconciliation status operation |
| `simulate_payment_completion` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute simulate payment completion operation |

### Module: `verenigingen.utils.create_sepa_indexes`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                          | Description             |
| --------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------- |
| `create_sepa_indexes` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new sepa indexes |

### Module: `verenigingen.utils.debug.analyze_payment_api`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `analyze_payment_mutations` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze payment mutations operation |

### Module: `verenigingen.utils.debug.analyze_payment_ledgers`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                          | Description                               |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `analyze_payment_ledgers` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze payment ledgers operation |

### Module: `verenigingen.utils.debug.check_specific_payment_api`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                          | Description                          |
| -------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `check_payment_6724` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check payment 6724 operation |

### Module: `verenigingen.utils.debug.fix_orphaned_gl_entries`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                      | Description                                  |
| ---------------------------- | --------- | -------- | ------------------------------------ | -------------------------------------------- |
| `cancel_orphaned_gl_entries` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel orphaned gl entries operation |

### Module: `verenigingen.utils.debug.investigate_payment_api_data`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                          | Description                                         |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------- |
| `investigate_payment_api_structure` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute investigate payment api structure operation |

### Module: `verenigingen.utils.debug.sepa_audit_tester`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `get_recent_audit_logs`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent audit logs data                 |
| `test_mandate_creation_logging` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mandate creation logging operation |
| `test_sepa_audit_logging`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test sepa audit logging operation       |

### Module: `verenigingen.utils.debug.sepa_direct_tester`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_all_audit_logs`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve all audit logs data                   |
| `test_direct_sepa_logging`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test direct sepa logging operation     |
| `test_mandate_creation_method` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mandate creation method operation |

### Module: `verenigingen.utils.debug.simple_sepa_audit_tester`

**Functions:** 5

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `check_sepa_audit_table`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check sepa audit table operation   |
| `check_table_exists`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check table exists operation       |
| `simple_audit_test`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute simple audit test operation        |
| `test_sepa_audit_creation`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test sepa audit creation operation |
| `validate_sepa_audit_functionality` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate sepa audit functionality input    |

### Module: `verenigingen.utils.debug.test_payment_api_fix`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                      | Description                            |
| ---------------------- | --------- | -------- | ------------------------------------ | -------------------------------------- |
| `test_payment_api_fix` | READ      | high     | System Manager, Verenigingen Manager | Execute test payment api fix operation |

### Module: `verenigingen.utils.email_queue_cleanup`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                      | Description                                         |
| ----------------------------------- | --------- | -------- | ------------------------------------ | --------------------------------------------------- |
| `clear_failed_administrator_emails` | READ      | high     | System Manager, Verenigingen Manager | Execute clear failed administrator emails operation |

### Module: `verenigingen.utils.fix_missing_payment_history`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                      | Description                                   |
| ----------------------------- | --------- | -------- | ------------------------------------ | --------------------------------------------- |
| `fix_missing_payment_history` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix missing payment history operation |

### Module: `verenigingen.utils.fix_sepa_database_issues`

**Functions:** 5

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `apply_sepa_performance_monitoring` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute apply sepa performance monitoring operation |
| `fix_cleanup_script_n1_query`       | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix cleanup script n1 query operation       |
| `fix_sepa_invoice_index`            | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix sepa invoice index operation            |
| `run_all_sepa_fixes`                | READ      | high     | System Manager, Verenigingen Manager                                          | Execute run all sepa fixes operation                |
| `test_cleanup_script_optimized`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test cleanup script optimized operation     |

### Module: `verenigingen.utils.install_sepa_audit_log`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `create_sepa_audit_table` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new sepa audit table              |
| `install_sepa_audit_log`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute install sepa audit log operation |

### Module: `verenigingen.utils.migration.stock_migration`

**Functions:** 1

| Function                                | Operation | Security | Suggested Roles                      | Description                                             |
| --------------------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------------------------- |
| `migrate_stock_transactions_standalone` | WRITE     | high     | System Manager, Verenigingen Manager | Execute migrate stock transactions standalone operation |

### Module: `verenigingen.utils.mollie_payment_checker`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `check_subscription_payments` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check subscription payments operation |
| `list_all_mollie_payments`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | List all mollie payments entries              |

### Module: `verenigingen.utils.mollie_test_helpers`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                      | Description                                  |
| ---------------------------- | --------- | -------- | ------------------------------------ | -------------------------------------------- |
| `cancel_mollie_subscription` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel mollie subscription operation |

### Module: `verenigingen.utils.nuke_financial_data`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `check_financial_data_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check financial data status operation |
| `nuke_all_financial_data`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute nuke all financial data operation     |
| `nuke_gl_entries_older_than`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute nuke gl entries older than operation  |

### Module: `verenigingen.utils.nuke_financial_data_fast`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `nuke_financial_data_fast` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute nuke financial data fast operation |

### Module: `verenigingen.utils.payment_history_validator`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                          | Description                                    |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `get_payment_history_validation_stats` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment history validation stats data |
| `validate_and_repair_payment_history`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate and repair payment history input      |

### Module: `verenigingen.utils.payment_plan_validator`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                        |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------- |
| `validate_payment_plan_system` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate payment plan system input |

### Module: `verenigingen.utils.payment_retry`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `check_payment_retry_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check payment retry status operation |
| `execute_payment_retry`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute execute payment retry operation      |
| `schedule_retry`             | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute schedule retry operation             |

### Module: `verenigingen.utils.payment_services.refund_utility`

**Functions:** 4

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `get_donation_refund_info` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve donation refund info data         |
| `get_payment_refund_info`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment refund info data          |
| `initiate_donation_refund` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute initiate donation refund operation |
| `initiate_refund`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute initiate refund operation          |

### Module: `verenigingen.utils.real_payment_webhook_test`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `check_payment_status`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check payment status operation           |
| `test_webhook_with_real_payment` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test webhook with real payment operation |

### Module: `verenigingen.utils.role_cleanup`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                      | Description                                    |
| ------------------------------ | --------- | -------- | ------------------------------------ | ---------------------------------------------- |
| `remove_redundant_admin_roles` | WRITE     | high     | System Manager, Verenigingen Manager | Execute remove redundant admin roles operation |

### Module: `verenigingen.utils.security_decorators`

**Functions:** 2

| Function              | Operation | Security | Suggested Roles                      | Description                      |
| --------------------- | --------- | -------- | ------------------------------------ | -------------------------------- |
| `admin_function`      | READ      | high     | System Manager, Verenigingen Manager | Execute admin function operation |
| `bulk_delete_members` | WRITE     | high     | System Manager, Verenigingen Manager | Delete bulk members records      |

### Module: `verenigingen.utils.sepa_baseline_test`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `run_sepa_baseline_test` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run sepa baseline test operation |

### Module: `verenigingen.utils.sepa_optimization_comparison`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `run_sepa_comparison_test` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run sepa comparison test operation |

### Module: `verenigingen.utils.sepa_three_way_comparison`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `run_sepa_three_way_comparison` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run sepa three way comparison operation |

### Module: `verenigingen.utils.services.sepa_service`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                          | Description                                  |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `cancel_mandate_via_service`      | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute cancel mandate via service operation |
| `create_sepa_mandate_via_service` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new sepa mandate via service          |
| `get_member_mandates_via_service` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member mandates via service data    |

### Module: `verenigingen.utils.termination_utils`

**Functions:** 3

| Function                         | Operation | Security | Suggested Roles                                                               | Description                              |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `get_termination_impact_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination impact summary data |
| `get_termination_statistics`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination statistics data     |
| `validate_termination_readiness` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate termination readiness input     |

### Module: `verenigingen.utils.test_payment_simulation`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `test_webhook_with_payment` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test webhook with payment operation |

### Module: `verenigingen.utils.testing.sepa_payment_failure_scenarios`

**Functions:** 4

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                         |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `create_payment_failure_scenario`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new payment failure scenario                 |
| `get_retry_schedule`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve retry schedule data                        |
| `simulate_payment_failure_sequence`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute simulate payment failure sequence operation |
| `validate_payment_recovery_scenario` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate payment recovery scenario input            |

### Module: `verenigingen.verenigingen.doctype.account_creation_request.account_creation_request`

**Functions:** 1

| Function         | Operation | Security | Suggested Roles                      | Description                      |
| ---------------- | --------- | -------- | ------------------------------------ | -------------------------------- |
| `cancel_request` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel request operation |

### Module: `verenigingen.verenigingen.doctype.member.mixins.payment_mixin`

**Functions:** 5

| Function                             | Operation | Security | Suggested Roles                                          | Description                                          |
| ------------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `force_full_payment_history_rebuild` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute force full payment history rebuild operation |
| `load_payment_history`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute load payment history operation               |
| `mark_as_paid`                       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute mark as paid operation                       |
| `refresh_financial_history`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute refresh financial history operation          |
| `refresh_payment_entry`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute refresh payment entry operation              |

### Module: `verenigingen.verenigingen.doctype.member.mixins.payment_mixin_optimized`

**Functions:** 2

| Function                            | Operation | Security | Suggested Roles                                          | Description                                         |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------- |
| `compare_payment_mixin_performance` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute compare payment mixin performance operation |
| `load_payment_history`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute load payment history operation              |

### Module: `verenigingen.verenigingen.doctype.member.mixins.sepa_mixin`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                                        |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `check_sepa_mandate_discrepancies` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sepa mandate discrepancies operation |

### Module: `verenigingen.verenigingen.doctype.membership.membership`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                      | Description                         |
| ------------------- | --------- | -------- | ------------------------------------ | ----------------------------------- |
| `cancel_membership` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel membership operation |

### Module: `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_analytics`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `generate_executive_summary` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate executive summary operation |
| `get_early_warning_system`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve early warning system data           |
| `get_termination_trends`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination trends data             |

### Module: `verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request`

**Functions:** 12

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `approve_request`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute approve request operation                   |
| `execute_safe_member_termination`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute execute safe member termination operation   |
| `execute_termination`               | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute execute termination operation               |
| `generate_expulsion_report`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate expulsion report operation         |
| `get_eligible_approvers`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve eligible approvers data                    |
| `get_member_termination_history`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member termination history data            |
| `get_termination_impact_preview`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination impact preview data            |
| `get_termination_preview`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination preview data                   |
| `get_termination_statistics`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve termination statistics data                |
| `initiate_disciplinary_termination` | READ      | high     | System Manager, Verenigingen Manager                                          | Execute initiate disciplinary termination operation |
| `simulate_execution`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute simulate execution operation                |
| `submit_for_approval`               | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute submit for approval operation               |

### Module: `verenigingen.verenigingen.doctype.periodic_donation_agreement.periodic_donation_agreement`

**Functions:** 1

| Function           | Operation | Security | Suggested Roles                      | Description                        |
| ------------------ | --------- | -------- | ------------------------------------ | ---------------------------------- |
| `cancel_agreement` | WRITE     | high     | System Manager, Verenigingen Manager | Execute cancel agreement operation |

### Module: `verenigingen.verenigingen.report.termination_audit_report.termination_audit_report`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `export_audit_report`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute export audit report operation |
| `get_audit_trail_details`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve audit trail details data     |
| `get_compliance_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve compliance statistics data   |

### Module: `verenigingen.verenigingen_payments.api.dd_batch_api`

**Functions:** 6

| Function                          | Operation | Security | Suggested Roles                                          | Description                                  |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `apply_conflict_resolutions`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute apply conflict resolutions operation |
| `escalate_conflicts`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute escalate conflicts operation         |
| `get_batch_conflicts`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve batch conflicts data                |
| `get_batch_details_with_security` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve batch details with security data    |
| `get_batch_list_with_security`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve batch list with security data       |
| `get_eligible_invoices`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve eligible invoices data              |

### Module: `verenigingen.verenigingen_payments.api.dd_batch_optimizer`

**Functions:** 4

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `create_optimal_batches`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new optimal batches                   |
| `get_batching_preview`             | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve batching preview data               |
| `update_batch_optimization_config` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update batch optimization config information |
| `validate_all_pending_invoices`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate all pending invoices input          |

### Module: `verenigingen.verenigingen_payments.api.dd_batch_scheduler`

**Functions:** 6

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                   |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `get_batch_creation_schedule`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batch creation schedule data         |
| `get_batch_optimization_stats` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batch optimization stats data        |
| `run_batch_creation_now`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run batch creation now operation      |
| `test_batch_scheduler_config`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test batch scheduler config operation |
| `toggle_auto_batch_creation`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute toggle auto batch creation operation  |
| `validate_batch_creation_days` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate batch creation days input            |

### Module: `verenigingen.verenigingen_payments.api.dd_batch_workflow_controller`

**Functions:** 6

| Function                       | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `approve_batch`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute approve batch operation           |
| `get_batch_approval_history`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batch approval history data      |
| `get_batches_pending_approval` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batches pending approval data    |
| `reject_batch`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reject batch operation            |
| `trigger_sepa_generation`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute trigger sepa generation operation |
| `validate_batch_for_approval`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate batch for approval input         |

### Module: `verenigingen.verenigingen_payments.api.sepa_batch_notifications`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `test_notification_system` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test notification system operation |

### Module: `verenigingen.verenigingen_payments.api.sepa_batch_ui`

**Functions:** 8

| Function                          | Operation | Security | Suggested Roles                                          | Description                               |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `create_sepa_batch_validated`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new sepa batch validated           |
| `get_batch_analytics`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve batch analytics data             |
| `get_invoice_mandate_info`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve invoice mandate info data        |
| `get_sepa_validation_constraints` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa validation constraints data |
| `load_unpaid_invoices`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute load unpaid invoices operation    |
| `preview_sepa_xml`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute preview sepa xml operation        |
| `validate_batch_invoices`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate batch invoices input             |
| `validate_invoice_mandate`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate invoice mandate input            |

### Module: `verenigingen.verenigingen_payments.api.sepa_batch_ui_secure`

**Functions:** 8

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                      |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `create_sepa_batch_validated_secure`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa batch validated secure           |
| `get_batch_analytics_secure`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batch analytics secure data             |
| `get_invoice_mandate_info_secure`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve invoice mandate info secure data        |
| `get_sepa_validation_constraints_secure` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve sepa validation constraints secure data |
| `load_unpaid_invoices_secure`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute load unpaid invoices secure operation    |
| `preview_sepa_xml_secure`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute preview sepa xml secure operation        |
| `validate_batch_invoices_secure`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate batch invoices secure input             |
| `validate_invoice_mandate_secure`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate invoice mandate secure input            |

### Module: `verenigingen.verenigingen_payments.api.sepa_mandate_management`

**Functions:** 4

| Function                                 | Operation | Security | Suggested Roles                                          | Description                                              |
| ---------------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------------- |
| `create_missing_sepa_mandates`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new missing sepa mandates                         |
| `detect_sepa_mandate_inconsistencies`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute detect sepa mandate inconsistencies operation    |
| `fix_specific_member_sepa_mandate`       | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute fix specific member sepa mandate operation       |
| `periodic_sepa_mandate_child_table_sync` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute periodic sepa mandate child table sync operation |

### Module: `verenigingen.verenigingen_payments.api.sepa_reconciliation`

**Functions:** 6

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                     |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `correlate_return_transactions`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute correlate return transactions operation |
| `get_sepa_reconciliation_dashboard`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve sepa reconciliation dashboard data     |
| `identify_sepa_transactions`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute identify sepa transactions operation    |
| `manual_sepa_reconciliation`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute manual sepa reconciliation operation    |
| `process_sepa_return_file`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process sepa return file operation              |
| `process_sepa_transaction_conservative` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process sepa transaction conservative operation |

### Module: `verenigingen.verenigingen_payments.clients.bulk_transaction_importer`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `estimate_bulk_import_size` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute estimate bulk import size operation |
| `get_bulk_import_history`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve bulk import history data           |
| `run_bulk_import`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute run bulk import operation           |

### Module: `verenigingen.verenigingen_payments.dashboards.financial_dashboard`

**Functions:** 2

| Function               | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_financial_report` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve financial report data       |
| `test_dashboard_api`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dashboard api operation |

### Module: `verenigingen.verenigingen_payments.dashboards.simple_dashboard`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                          | Description                    |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------ |
| `get_financial_report` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve financial report data |

### Module: `verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch`

**Functions:** 7

| Function                                           | Operation | Security | Suggested Roles                                          | Description                                          |
| -------------------------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `create_direct_debit_batch_for_unpaid_memberships` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new direct debit batch for unpaid memberships |
| `create_enhanced_dues_batch`                       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new enhanced dues batch                       |
| `generate_direct_debit_batch`                      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate direct debit batch operation        |
| `generate_sepa_xml`                                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate sepa xml operation                  |
| `get_dues_collection_preview`                      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve dues collection preview data                |
| `mark_invoices_as_paid`                            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute mark invoices as paid operation              |
| `process_batch`                                    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process batch operation                              |

### Module: `verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor`

**Functions:** 6

| Function                               | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `create_monthly_dues_collection_batch` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new monthly dues collection batch         |
| `get_sepa_batch_preview`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa batch preview data                 |
| `get_upcoming_dues_collections`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve upcoming dues collections data          |
| `process_sepa_returns`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process sepa returns operation                   |
| `validate_sepa_configuration`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate sepa configuration input                |
| `verify_invoice_coverage_status`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute verify invoice coverage status operation |

### Module: `verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings`

**Functions:** 3

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `get_mollie_settings`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mollie settings data            |
| `test_mollie_connection` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test mollie connection operation |
| `update_webhook_urls`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update webhook urls information          |

### Module: `verenigingen.verenigingen_payments.doctype.payment_plan.payment_plan`

**Functions:** 3

| Function                               | Operation | Security | Suggested Roles                                          | Description                              |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `approve_payment_plan`                 | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute approve payment plan operation   |
| `create_payment_plan_from_application` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new payment plan from application |
| `process_overdue_installments`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process overdue installments operation   |

### Module: `verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                         |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `get_mandate_sequence_type` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mandate sequence type data |

### Module: `verenigingen.verenigingen_payments.integration.mollie_connector`

**Functions:** 3

| Function                  | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `get_account_balance`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve account balance data            |
| `list_recent_settlements` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | List recent settlements entries          |
| `test_mollie_connection`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mollie connection operation |

### Module: `verenigingen.verenigingen_payments.monitoring.balance_monitor`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `get_balance_health_dashboard` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve balance health dashboard data   |
| `run_balance_monitoring`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute run balance monitoring operation |

### Module: `verenigingen.verenigingen_payments.templates.pages.mollie_checkout`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                          | Description                       |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------- |
| `get_payment_status_only` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment status only data |

### Module: `verenigingen.verenigingen_payments.utils.bank_specific_validator`

**Functions:** 2

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `get_bank_validation_requirements`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve bank validation requirements data |
| `validate_sepa_transaction_for_bank` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate sepa transaction for bank input   |

### Module: `verenigingen.verenigingen_payments.utils.batch_performance_optimizer`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `clear_batch_performance_cache` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear batch performance cache operation |
| `get_batch_performance_stats`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batch performance stats data           |

### Module: `verenigingen.verenigingen_payments.utils.financial_error_handler`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                          | Description                              |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `get_financial_error_statistics` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve financial error statistics data |

### Module: `verenigingen.verenigingen_payments.utils.frappe_native_sepa_operations`

**Functions:** 2

| Function                                     | Operation | Security | Suggested Roles                                          | Description                                          |
| -------------------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `get_members_for_sepa_bulk_operations_clean` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve members for sepa bulk operations clean data |
| `process_bulk_sepa_operations_clean`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process bulk sepa operations clean operation         |

### Module: `verenigingen.verenigingen_payments.utils.payment_gateways`

**Functions:** 10

| Function                            | Operation | Security | Suggested Roles                                          | Description                                        |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `cancel_member_subscription`        | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute cancel member subscription operation       |
| `cancel_mollie_subscription_by_id`  | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute cancel mollie subscription by id operation |
| `create_member_subscription`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new member subscription                     |
| `get_member_subscription_status`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member subscription status data           |
| `get_payment_status`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve payment status data                       |
| `manual_payment_confirmation`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute manual payment confirmation operation      |
| `manual_subscription_retry`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute manual subscription retry operation        |
| `mollie_subscription_webhook`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute mollie subscription webhook operation      |
| `process_donation_payment`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process donation payment operation                 |
| `update_mollie_subscription_amount` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update mollie subscription amount information      |

### Module: `verenigingen.verenigingen_payments.utils.sepa_admin_reporting`

**Functions:** 7

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                             |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------- |
| `export_report_csv`                     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute export report csv operation                     |
| `generate_executive_summary`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate executive summary operation            |
| `generate_financial_analysis`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate financial analysis operation           |
| `generate_mandate_lifecycle_report`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate mandate lifecycle report operation     |
| `generate_operational_report`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate operational report operation           |
| `generate_performance_benchmark_report` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate performance benchmark report operation |
| `schedule_report`                       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute schedule report operation                       |

### Module: `verenigingen.verenigingen_payments.utils.sepa_alerting_system`

**Functions:** 7

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `acknowledge_alert`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute acknowledge alert operation           |
| `check_security_integration`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check security integration operation  |
| `get_active_alerts`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve active alerts data                   |
| `get_alert_statistics`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve alert statistics data                |
| `resolve_alert`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute resolve alert operation               |
| `test_alert_system`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test alert system operation           |
| `toggle_security_integration` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute toggle security integration operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_config_manager`

**Functions:** 5

| Function                      | Operation | Security | Suggested Roles                                          | Description                               |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `clear_sepa_config_cache`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute clear sepa config cache operation |
| `get_sepa_config`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa config data                 |
| `get_sepa_config_cache_info`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa config cache info data      |
| `update_sepa_setting`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update sepa setting information           |
| `validate_sepa_configuration` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate sepa configuration input         |

### Module: `verenigingen.verenigingen_payments.utils.sepa_conflict_detector`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `detect_batch_conflicts`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute detect batch conflicts operation |
| `validate_batch_with_conflicts` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate batch with conflicts input      |

### Module: `verenigingen.verenigingen_payments.utils.sepa_error_handler`

**Functions:** 3

| Function                         | Operation | Security | Suggested Roles                                          | Description                                  |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `create_retry_batch_from_errors` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new retry batch from errors           |
| `get_sepa_error_handler_status`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa error handler status data      |
| `reset_sepa_circuit_breaker`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reset sepa circuit breaker operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_input_validation`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                          | Description                         |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `get_sepa_validation_rules`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa validation rules data |
| `validate_sepa_batch_params`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate sepa batch params input    |
| `validate_single_sepa_invoice` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate single sepa invoice input  |

### Module: `verenigingen.verenigingen_payments.utils.sepa_mandate_lifecycle_manager`

**Functions:** 5

| Function                           | Operation | Security | Suggested Roles                                          | Description                                       |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `bulk_validate_mandates`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate bulk mandates input                      |
| `determine_mandate_sequence_type`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute determine mandate sequence type operation |
| `get_mandate_lifecycle_status`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mandate lifecycle status data            |
| `get_mandate_usage_report`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mandate usage report data                |
| `validate_mandate_for_transaction` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate mandate for transaction input            |

### Module: `verenigingen.verenigingen_payments.utils.sepa_mandate_service`

**Functions:** 2

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `clear_sepa_mandate_cache` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute clear sepa mandate cache operation |
| `get_sepa_cache_stats`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa cache stats data             |

### Module: `verenigingen.verenigingen_payments.utils.sepa_memory_optimizer`

**Functions:** 3

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `force_memory_cleanup`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute force memory cleanup operation           |
| `get_memory_usage_stats`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve memory usage stats data                 |
| `optimize_sepa_batch_processing` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process optimize sepa batch processing operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_monitoring_dashboard`

**Functions:** 7

| Function                       | Operation | Security | Suggested Roles                                                               | Description                             |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `get_batch_analytics`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve batch analytics data           |
| `get_financial_metrics`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve financial metrics data         |
| `get_mandate_health_report`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve mandate health report data     |
| `get_sepa_dashboard_data`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve sepa dashboard data data       |
| `get_sepa_performance_metrics` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve sepa performance metrics data  |
| `get_system_alerts`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve system alerts data             |
| `record_sepa_operation`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute record sepa operation operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_notification_manager`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `get_sepa_notification_history` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa notification history data         |
| `send_sepa_notification`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute send sepa notification operation        |
| `test_sepa_notification_system` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test sepa notification system operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_notifications`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `test_mandate_notification` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mandate notification operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_performance_monitor`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `benchmark_sepa_batch_processing` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process benchmark sepa batch processing operation |
| `clear_sepa_performance_data`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute clear sepa performance data operation     |
| `get_sepa_performance_report`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa performance report data             |

### Module: `verenigingen.verenigingen_payments.utils.sepa_race_condition_manager`

**Functions:** 3

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `create_sepa_batch_with_race_protection` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa batch with race protection |
| `force_release_batch_lock`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute force release batch lock operation |
| `get_batch_lock_status`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve batch lock status data            |

### Module: `verenigingen.verenigingen_payments.utils.sepa_reconciliation`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `get_reconciliation_summary`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve reconciliation summary data          |
| `process_sepa_return_file`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process sepa return file operation            |
| `reconcile_bank_transactions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reconcile bank transactions operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_retry_manager`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `execute_with_retry`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute execute with retry operation          |
| `get_retry_statistics`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve retry statistics data                |
| `reset_retry_circuit_breaker` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reset retry circuit breaker operation |

### Module: `verenigingen.verenigingen_payments.utils.sepa_rollback_manager`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_rollback_operation_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve rollback operation status data        |
| `initiate_sepa_batch_rollback`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute initiate sepa batch rollback operation |
| `list_rollback_operations`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | List rollback operations entries               |

### Module: `verenigingen.verenigingen_payments.utils.sepa_rulebook_validator`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                          | Description                           |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `get_sepa_rules`                  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sepa rules data              |
| `validate_batch_against_rulebook` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate batch against rulebook input |
| `validate_sepa_xml_rulebook`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate sepa xml rulebook input      |

### Module: `verenigingen.verenigingen_payments.utils.sepa_validator`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                     |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------- |
| `validate_sepa_integration` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate sepa integration input |

### Module: `verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                          | Description                                  |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `generate_enhanced_sepa_xml`   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate enhanced sepa xml operation |
| `validate_sepa_xml_compliance` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate sepa xml compliance input           |

### Module: `verenigingen.verenigingen_payments.utils.sepa_zabbix_enhanced`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_zabbix_item_config`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve zabbix item config data               |
| `get_zabbix_trigger_configs`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve zabbix trigger configs data           |
| `test_sepa_zabbix_integration` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test sepa zabbix integration operation |

### Module: `verenigingen.verenigingen_payments.workflows.dispute_resolution`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                     |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `create_dispute_from_webhook` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new dispute from webhook |
| `get_dispute_analytics`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dispute analytics data |

### Module: `verenigingen.verenigingen_payments.workflows.reconciliation_engine`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `run_scheduled_reconciliation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run scheduled reconciliation operation |

### Module: `verenigingen.verenigingen_payments.workflows.subscription_manager`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `analyze_subscription_health`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze subscription health operation    |
| `sync_all_subscription_payments` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute sync all subscription payments operation |

## Medium Priority Functions

**Count:** 1123

### Module: `scripts.api_maintenance.analyze_tegenrekening_usage`

**Functions:** 3

| Function                            | Operation | Security | Suggested Roles                                          | Description                                         |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------- |
| `analyze_tegenrekening_patterns`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze tegenrekening patterns operation    |
| `generate_item_mapping_suggestions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate item mapping suggestions operation |
| `get_chart_of_accounts_mapping`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve chart of accounts mapping data             |

### Module: `scripts.api_maintenance.check_sales_invoice_data`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `check_sales_invoice_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sales invoice data operation |

### Module: `scripts.api_maintenance.eboekhouden_mapping_setup`

**Functions:** 2

| Function                           | Operation | Security | Suggested Roles                                          | Description                                        |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `get_mapping_summary`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mapping summary data                      |
| `setup_eboekhouden_mapping_fields` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute setup eboekhouden mapping fields operation |

### Module: `scripts.api_maintenance.fix_eboekhouden_import`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `analyze_import_issues` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze import issues operation |

### Module: `scripts.api_maintenance.fix_eboekhouden_import_comprehensive`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `fix_existing_records`          | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix existing records operation          |
| `fix_import_code_comprehensive` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix import code comprehensive operation |
| `restart_required`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute restart required operation              |

### Module: `scripts.api_maintenance.fix_sales_invoice_receivables`

**Functions:** 3

| Function                                 | Operation | Security | Suggested Roles                                          | Description                                              |
| ---------------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------------- |
| `check_sales_invoice_receivables`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sales invoice receivables operation        |
| `fix_existing_sales_invoice_receivables` | READ      | high     | System Manager, Verenigingen Manager                     | Execute fix existing sales invoice receivables operation |
| `get_receivable_account_mapping`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve receivable account mapping data                 |

### Module: `scripts.api_maintenance.fix_workspace`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `fix_eboekhouden_workspace`     | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix eboekhouden workspace operation     |
| `install_eboekhouden_workspace` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute install eboekhouden workspace operation |
| `verify_workspace_links`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify workspace links operation        |

### Module: `scripts.cleanup.cleanup_invalid_member_schedules`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `cleanup_invalid_schedules`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup invalid schedules operation  |
| `identify_invalid_schedules` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute identify invalid schedules operation |
| `validate_cleanup_results`   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate cleanup results input               |

### Module: `scripts.debug.incremental_update_debug_test`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                          | Description                                       |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `test_member_incremental_update` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update test member incremental update information |

### Module: `scripts.debug.membership_dues_coverage_debugger`

**Functions:** 4

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `create_coverage_fields`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new coverage fields                |
| `populate_coverage_dates` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute populate coverage dates operation |
| `quick_coverage_test`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick coverage test operation     |
| `run_full_debug`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run full debug operation          |

### Module: `scripts.deployment.deploy_phase_1_complete`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `deploy_phase_1_complete` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute deploy phase 1 complete operation |

### Module: `scripts.deployment.validate_production_schema`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                   |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------- |
| `create_production_indexes` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new production indexes |

### Module: `scripts.maintenance.rename_roles_with_prefix`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `get_current_role_status`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve current role status data           |
| `rename_verenigingen_roles` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute rename verenigingen roles operation |
| `rollback_role_rename`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute rollback role rename operation      |

### Module: `scripts.member_performance_analyzer`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `analyze_member_performance` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze member performance operation |

### Module: `scripts.membership_dues_poc`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                          | Description                            |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `test_dues_system_poc` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test dues system poc operation |

### Module: `scripts.migration.fix_membership_types_billing`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                      | Description                                           |
| ------------------------------------- | --------- | -------- | ------------------------------------ | ----------------------------------------------------- |
| `fix_membership_types_billing_period` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix membership types billing period operation |
| `verify_membership_types_fixed`       | READ      | high     | System Manager, Verenigingen Manager | Execute verify membership types fixed operation       |

### Module: `scripts.migration.fix_team_assignment_history`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                      | Description                                   |
| ----------------------------- | --------- | -------- | ------------------------------------ | --------------------------------------------- |
| `fix_team_assignment_history` | READ      | high     | System Manager, Verenigingen Manager | Execute fix team assignment history operation |

### Module: `scripts.migration.manual_employee_creation`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                                               | Description                             |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `create_employee_for_volunteer`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new employee for volunteer       |
| `create_employees_for_all_volunteers` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new employees for all volunteers |

### Module: `scripts.optimization.apply_api_optimizations`

**Functions:** 3

| Function          | Operation | Security | Suggested Roles                                                               | Description                     |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `get_member_list` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member list data       |
| `get_member_list` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member list data       |
| `your_endpoint`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute your endpoint operation |

### Module: `scripts.performance.performance_measurement_script`

**Functions:** 4

| Function                                 | Operation | Security | Suggested Roles                                          | Description                                              |
| ---------------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------------- |
| `count_payment_mixin_complexity`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute count payment mixin complexity operation         |
| `measure_database_query_patterns`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute measure database query patterns operation        |
| `measure_payment_history_performance`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute measure payment history performance operation    |
| `run_comprehensive_performance_analysis` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run comprehensive performance analysis operation |

### Module: `scripts.setup.add_chapter_chart`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `add_chapter_specific_chart` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add chapter specific chart operation |

### Module: `scripts.setup.add_expense_cards`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `add_expense_number_cards` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add expense number cards operation |

### Module: `scripts.setup.create_chapter_dashboard`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                                               | Description                  |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------- |
| `create_chapter_dashboard` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new chapter dashboard |

### Module: `scripts.test_auto_submit`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `test_invoice_auto_submit`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test invoice auto submit operation    |
| `test_member_payment_history` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test member payment history operation |

### Module: `scripts.testing.integration.test_team_removal`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `test_team_member_removal` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test team member removal operation |

### Module: `scripts.testing.run_chapter_member_tests_bench`

**Functions:** 1

| Function    | Operation | Security | Suggested Roles                                                               | Description                 |
| ----------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------- |
| `run_tests` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run tests operation |

### Module: `scripts.validation.js_python_parameter_validator_enhanced`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                     |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `_get_resolution_action` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve resolution action data |

### Module: `scripts.validation.validate_email_system`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `run_email_system_validation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run email system validation operation |

### Module: `scripts.workspace_reorganization`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `run_workspace_reorganization` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run workspace reorganization operation |

### Module: `verenigingen.api.analyze_failing_mutations`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `analyze_failing_stock_mutations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze failing stock mutations operation |
| `suggest_stock_account_solution`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute suggest stock account solution operation  |

### Module: `verenigingen.api.anbi_operations`

**Functions:** 7

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `export_belastingdienst_report` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute export belastingdienst report operation |
| `generate_anbi_report`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate anbi report operation          |
| `get_anbi_statistics`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve anbi statistics data                   |
| `get_donor_anbi_data`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve donor anbi data data                   |
| `send_consent_requests`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send consent requests operation         |
| `update_anbi_consent`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update anbi consent information                 |
| `update_donor_tax_identifiers`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update donor tax identifiers information        |

### Module: `verenigingen.api.audit_reports_dashboards`

**Functions:** 1

| Function                                    | Operation | Security | Suggested Roles                                                               | Description                                                 |
| ------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `audit_verenigingen_reports_and_dashboards` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute audit verenigingen reports and dashboards operation |

### Module: `verenigingen.api.background_job_status`

**Functions:** 5

| Function                        | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `cleanup_old_job_records`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup old job records operation |
| `get_background_job_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve background job statistics data   |
| `get_job_details`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve job details data                 |
| `get_user_background_jobs`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user background jobs data        |
| `retry_failed_job`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute retry failed job operation        |

### Module: `verenigingen.api.cache_invalidation_api`

**Functions:** 5

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `clear_all_caches`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear all caches operation            |
| `get_invalidation_patterns`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve invalidation patterns data           |
| `get_invalidation_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve invalidation statistics data         |
| `schedule_batch_invalidation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute schedule batch invalidation operation |
| `trigger_cache_invalidation`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trigger cache invalidation operation  |

### Module: `verenigingen.api.chapter_dashboard_api`

**Functions:** 35

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                        |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `add_chapter_specific_chart`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add chapter specific chart operation       |
| `add_existing_cards_to_dashboard`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add existing cards to dashboard operation  |
| `add_working_chapter_charts`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add working chapter charts operation       |
| `clean_dashboard_completely`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clean dashboard completely operation       |
| `create_cards_only_dashboard`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new cards only dashboard                    |
| `create_chapter_dashboard`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new chapter dashboard                       |
| `create_chapter_member_charts`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new chapter member charts                   |
| `create_minimal_working_charts`     | WRITE     | high     | System Manager, Verenigingen Manager                                          | Create new minimal working charts                  |
| `create_proper_chapter_charts`      | WRITE     | high     | System Manager, Verenigingen Manager                                          | Create new proper chapter charts                   |
| `create_simple_dashboard`           | WRITE     | high     | System Manager, Verenigingen Manager                                          | Create new simple dashboard                        |
| `create_working_basic_charts`       | WRITE     | high     | System Manager, Verenigingen Manager                                          | Create new working basic charts                    |
| `finalize_chapter_dashboard`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute finalize chapter dashboard operation       |
| `fix_all_chart_issues`              | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix all chart issues operation             |
| `fix_chart_currency_display`        | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix chart currency display operation       |
| `fix_chart_timeseries_display`      | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix chart timeseries display operation     |
| `fix_dashboard_chart_issue`         | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix dashboard chart issue operation        |
| `fix_dashboard_simple`              | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix dashboard simple operation             |
| `fix_dashboard_with_working_chart`  | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix dashboard with working chart operation |
| `get_active_members_count`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve active members count data                 |
| `get_approved_expense_claims_count` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve approved expense claims count data        |
| `get_board_members_count`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve board members count data                  |
| `get_chapter_quick_stats`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter quick stats data                  |
| `get_dashboard_completion_summary`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dashboard completion summary data         |
| `get_dashboard_notifications`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dashboard notifications data              |
| `get_filed_expense_claims_count`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve filed expense claims count data           |
| `get_new_members_count`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve new members count data                    |
| `get_pending_applications_count`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve pending applications count data           |
| `get_volunteer_expenses_count`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve volunteer expenses count data             |
| `quick_approve_member`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute quick approve member operation             |
| `recreate_working_charts`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new reworking charts                        |
| `reject_member_application`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reject member application operation        |
| `reprocess_mt940_import`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process remt940 import operation                   |
| `restore_all_member_cards`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute restore all member cards operation         |
| `send_chapter_announcement`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send chapter announcement operation        |
| `use_existing_working_charts`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute use existing working charts operation      |

### Module: `verenigingen.api.chapter_join`

**Functions:** 2

| Function                    | Operation | Security | Suggested Roles                                                               | Description                         |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `get_chapter_join_context`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter join context data  |
| `get_user_chapter_requests` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user chapter requests data |

### Module: `verenigingen.api.check_account_types`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                          | Description                               |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `fix_account_type_issues` | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute fix account type issues operation |
| `review_account_types`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute review account types operation    |

### Module: `verenigingen.api.check_auto_invoice_settings`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                         |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `get_auto_invoice_settings` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve auto invoice settings data |

### Module: `verenigingen.api.check_error_logs`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                          | Description                      |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------- |
| `get_mutation_type_logs` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mutation type logs data |

### Module: `verenigingen.api.check_opening_balance_date`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                               |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `get_opening_balance_date_for_js` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve opening balance date for js data |

### Module: `verenigingen.api.check_past_imports`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                         |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `get_journal_entry_details` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve journal entry details data |

### Module: `verenigingen.api.check_roles`

**Functions:** 10

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                               |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| `audit_coverage_data_consistency`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute audit coverage data consistency operation         |
| `debug_member_payment_history`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member payment history operation            |
| `get_verenigingen_roles`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve verenigingen roles data                          |
| `investigate_duplicate_invoices`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute investigate duplicate invoices operation          |
| `populate_missing_coverage_fields`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute populate missing coverage fields operation        |
| `refresh_member_payment_history`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute refresh member payment history operation          |
| `test_coverage_fields_in_payment_history` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test coverage fields in payment history operation |
| `test_invoice_submission_trigger`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test invoice submission trigger operation         |
| `test_new_invoice_generation`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test new invoice generation operation             |
| `test_payment_history_popup_data`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test payment history popup data operation         |

### Module: `verenigingen.api.check_specific_report_permissions`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_all_report_permissions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve all report permissions data |

### Module: `verenigingen.api.cleanup_chapter_members`

**Functions:** 2

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `cleanup_orphaned_chapter_members` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute cleanup orphaned chapter members operation |
| `test_specific_chapter_cleanup`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test specific chapter cleanup operation    |

### Module: `verenigingen.api.create_onboarding_steps`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `add_quick_start_card` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add quick start card operation |

### Module: `verenigingen.api.create_root_accounts`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                    |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------ |
| `create_root_accounts`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new root accounts       |
| `create_standard_coa_groups` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new standard coa groups |

### Module: `verenigingen.api.create_smart_item_mapping`

**Functions:** 3

| Function                              | Operation | Security | Suggested Roles                                                               | Description                             |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `create_items_from_mappings`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new items from mappings          |
| `create_smart_item_mapping_system`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new smart item mapping system    |
| `create_tegenrekening_mapping_helper` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new tegenrekening mapping helper |

### Module: `verenigingen.api.customer_member_link`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                          | Description                       |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------- |
| `create_customer_member_button` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new customer member button |

### Module: `verenigingen.api.database_index_manager`

**Functions:** 4

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `add_performance_indexes`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add performance indexes operation    |
| `get_index_status`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve index status data                   |
| `monitor_index_performance`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute monitor index performance operation  |
| `remove_performance_indexes` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute remove performance indexes operation |

### Module: `verenigingen.api.database_index_manager_phase5a`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `get_current_database_performance`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve current database performance data             |
| `implement_performance_indexes_safely` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute implement performance indexes safely operation |

### Module: `verenigingen.api.debug_member_membership`

**Functions:** 16

| Function                                         | Operation | Security | Suggested Roles                                                               | Description                                                      |
| ------------------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `analyze_recent_invoice_submissions`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute analyze recent invoice submissions operation             |
| `check_auto_submit_errors`                       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check auto submit errors operation                       |
| `check_invoice_submission_timeline`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check invoice submission timeline operation              |
| `comprehensive_implementation_test`              | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute comprehensive implementation test operation              |
| `debug_invoice_submission_issue`                 | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug invoice submission issue operation                 |
| `debug_member_billing_issues`                    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member billing issues operation                    |
| `debug_member_dues_schedule_connection`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member dues schedule connection operation          |
| `debug_member_membership_status`                 | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member membership status operation                 |
| `debug_membership_data_overview`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug membership data overview operation                 |
| `debug_payment_history_sync_issue`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug payment history sync issue operation               |
| `debug_report_sql`                               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug report sql operation                               |
| `debug_specific_member_sinv_issue`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug specific member sinv issue operation               |
| `get_members_without_active_memberships`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve members without active memberships data                 |
| `test_dues_schedule_field_functionality`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dues schedule field functionality operation         |
| `test_members_without_active_memberships_report` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test members without active memberships report operation |
| `test_payment_history_fix`                       | READ      | high     | System Manager, Verenigingen Manager                                          | Execute test payment history fix operation                       |

### Module: `verenigingen.api.debug_migration`

**Functions:** 5

| Function                            | Operation | Security | Suggested Roles                                          | Description                                         |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------- |
| `analyze_schedule_member_integrity` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze schedule member integrity operation |
| `test_new_invoice_validations`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test new invoice validations operation      |
| `test_payment_amount_calculation`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test payment amount calculation operation   |
| `test_payment_amount_edge_cases`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test payment amount edge cases operation    |
| `test_payment_creation_fix`         | READ      | high     | System Manager, Verenigingen Manager                     | Execute test payment creation fix operation         |

### Module: `verenigingen.api.debug_refresh_issue`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `debug_member_refresh_issue` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug member refresh issue operation |

### Module: `verenigingen.api.debug_test_memberships`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `check_test_memberships` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check test memberships operation |

### Module: `verenigingen.api.deep_mutation_analysis`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `trace_journal_entry_creation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trace journal entry creation operation |

### Module: `verenigingen.api.doctype_field_inspector`

**Functions:** 3

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `inspect_expense_claim_fields`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute inspect expense claim fields operation     |
| `inspect_member_fields`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute inspect member fields operation            |
| `inspect_volunteer_expense_fields` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute inspect volunteer expense fields operation |

### Module: `verenigingen.api.doctype_permissions_inventory`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                           |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `create_complete_doctype_inventory` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new complete doctype inventory |

### Module: `verenigingen.api.donor_auto_creation_management`

**Functions:** 7

| Function                        | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `bulk_process_pending_payments` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process bulk pending payments operation   |
| `get_auto_creation_dashboard`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve auto creation dashboard data     |
| `get_customer_groups`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve customer groups data             |
| `get_donations_gl_accounts`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donations gl accounts data       |
| `get_recent_error_logs`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent error logs data           |
| `simulate_auto_creation`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute simulate auto creation operation  |
| `update_auto_creation_settings` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update auto creation settings information |

### Module: `verenigingen.api.donor_customer_management`

**Functions:** 4

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `force_donor_customer_sync` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute force donor customer sync operation |
| `get_donor_customer_info`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donor customer info data           |
| `get_donor_sync_dashboard`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donor sync dashboard data          |
| `unlink_donor_customer`     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute unlink donor customer operation     |

### Module: `verenigingen.api.email_template_manager`

**Functions:** 3

| Function                               | Operation | Security | Suggested Roles                                                               | Description                              |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `create_all_email_templates`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new all email templates           |
| `create_comprehensive_email_templates` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new comprehensive email templates |
| `list_all_email_templates`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | List all email templates entries         |

### Module: `verenigingen.api.enhanced_background_jobs_api`

**Functions:** 7

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `enqueue_member_payment_history_job` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute enqueue member payment history job operation |
| `enqueue_performance_analysis_job`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute enqueue performance analysis job operation   |
| `enqueue_performance_job`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute enqueue performance job operation            |
| `get_job_queue_dashboard`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve job queue dashboard data                    |
| `get_job_status`                     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve job status data                             |
| `get_queue_status`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve queue status data                           |
| `optimize_job_scheduling`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute optimize job scheduling operation            |

### Module: `verenigingen.api.enhanced_membership_application`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                    |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_contribution_calculator_config`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve contribution calculator config data   |
| `get_membership_types_for_application` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve membership types for application data |

### Module: `verenigingen.api.fix_child_table_permissions`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `fix_child_table_permissions`    | READ      | high     | System Manager, Verenigingen Manager                     | Execute fix child table permissions operation    |
| `verify_child_table_permissions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute verify child table permissions operation |

### Module: `verenigingen.api.fix_custom_fields`

**Functions:** 6

| Function                               | Operation | Security | Suggested Roles                                          | Description                                            |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------------ |
| `check_sales_invoice_membership_field` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sales invoice membership field operation |
| `create_other_missing_custom_fields`   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new other missing custom fields                 |
| `create_sales_invoice_coverage_fields` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new sales invoice coverage fields               |
| `fix_all_custom_fields`                | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute fix all custom fields operation                |
| `fix_custom_field_modules`             | READ      | high     | System Manager, Verenigingen Manager                     | Execute fix custom field modules operation             |
| `get_sales_invoice_custom_fields`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve sales invoice custom fields data              |

### Module: `verenigingen.api.fix_customer_permissions`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                      | Description                                  |
| ---------------------------- | --------- | -------- | ------------------------------------ | -------------------------------------------- |
| `verify_customer_access_fix` | READ      | high     | System Manager, Verenigingen Manager | Execute verify customer access fix operation |

### Module: `verenigingen.api.fix_invalid_dates`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                      | Description                                      |
| -------------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------------------ |
| `fix_invalid_last_invoice_dates` | READ      | high     | System Manager, Verenigingen Manager | Execute fix invalid last invoice dates operation |

### Module: `verenigingen.api.fix_workspace`

**Functions:** 1

| Function        | Operation | Security | Suggested Roles                      | Description                     |
| --------------- | --------- | -------- | ------------------------------------ | ------------------------------- |
| `fix_workspace` | READ      | high     | System Manager, Verenigingen Manager | Execute fix workspace operation |

### Module: `verenigingen.api.fix_workspace_links`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                      | Description                           |
| --------------------- | --------- | -------- | ------------------------------------ | ------------------------------------- |
| `fix_workspace_links` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix workspace links operation |

### Module: `verenigingen.api.generate_invoice_for_schedule`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `generate_invoice_for_schedule` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate invoice for schedule operation |

### Module: `verenigingen.api.generate_test_applications`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `generate_test_members` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate test members operation |

### Module: `verenigingen.api.generate_test_members`

**Functions:** 3

| Function                  | Operation | Security | Suggested Roles                                          | Description                             |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `cleanup_test_members`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup test members operation  |
| `generate_test_members`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate test members operation |
| `get_test_members_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve test members status data       |

### Module: `verenigingen.api.generate_test_membership_types`

**Functions:** 3

| Function                           | Operation | Security | Suggested Roles                                          | Description                                      |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `cleanup_test_membership_types`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup test membership types operation  |
| `generate_test_membership_types`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate test membership types operation |
| `get_test_membership_types_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve test membership types status data       |

### Module: `verenigingen.api.job_status`

**Functions:** 7

| Function                          | Operation | Security | Suggested Roles                                                               | Description                               |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `clear_completed_jobs`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear completed jobs operation    |
| `get_job_queue_status`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve job queue status data            |
| `get_job_status`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve job status data                  |
| `get_recent_payment_history_jobs` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve recent payment history jobs data |
| `get_system_performance_metrics`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve system performance metrics data  |
| `get_user_jobs`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user jobs data                   |
| `retry_failed_job`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute retry failed job operation        |

### Module: `verenigingen.api.manual_invoice_generation`

**Functions:** 9

| Function                                     | Operation | Security | Suggested Roles                                                               | Description                                                  |
| -------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `check_dues_schedules`                       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check dues schedules operation                       |
| `diagnose_auto_submit_setting`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute diagnose auto submit setting operation               |
| `generate_manual_invoice`                    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate manual invoice operation                    |
| `get_member_invoice_info`                    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member invoice info data                            |
| `scan_email_template_issues`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute scan email template issues operation                 |
| `test_email_template_variables`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test email template variables operation              |
| `test_hybrid_payment_history_implementation` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test hybrid payment history implementation operation |
| `test_sepa_mandate_pattern`                  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test sepa mandate pattern operation                  |
| `test_settings_creation_user`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test settings creation user operation                |

### Module: `verenigingen.api.member_management`

**Functions:** 18

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                         |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `bulk_assign_members_to_chapters`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute bulk assign members to chapters operation   |
| `clear_address_members_field`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute clear address members field operation       |
| `debug_address_members`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug address members operation             |
| `debug_bank_account_search`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Search debug bank account search data               |
| `debug_duplicate_detection`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug duplicate detection operation         |
| `debug_mt940_import`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug mt940 import operation                |
| `debug_mt940_import_detailed`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug mt940 import detailed operation       |
| `debug_mt940_import_improved`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug mt940 import improved operation       |
| `get_address_members_html_api`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve address members html api data              |
| `get_chapter_member_emails`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve chapter member emails data                 |
| `get_members_with_chapter_info`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve members with chapter info data             |
| `get_members_without_chapter`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve members without chapter data               |
| `get_mt940_import_url`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve mt940 import url data                      |
| `import_mt940_improved`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute import mt940 improved operation             |
| `manually_populate_address_members`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute manually populate address members operation |
| `test_member_incremental_update_debug` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update test member incremental debug information    |
| `test_mt940_extraction`                | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test mt940 extraction operation             |
| `test_simple_field_population`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test simple field population operation      |

### Module: `verenigingen.api.member_performance_api`

**Functions:** 7

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `bulk_create_members`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new bulk members                         |
| `clear_member_cache`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute clear member cache operation            |
| `create_member_optimized`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new member optimized                     |
| `get_member_dashboard_fast`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member dashboard fast data             |
| `get_performance_stats`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance stats data                 |
| `search_members_fast`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Search members fast data                        |
| `test_performance_optimization` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test performance optimization operation |

### Module: `verenigingen.api.membership_application`

**Functions:** 6

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                        |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `debug_member_issue`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member issue operation               |
| `fix_specific_member`                  | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix specific member operation              |
| `process_application_payment_endpoint` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process application payment endpoint operation     |
| `reject_membership_application`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reject membership application operation    |
| `test_chapter_membership_workflow`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test chapter membership workflow operation |
| `test_status_field_integration`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test status field integration operation    |

### Module: `verenigingen.api.membership_application_review`

**Functions:** 16

| Function                                   | Operation | Security | Suggested Roles                                                               | Description                                                |
| ------------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `approve_membership_application`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute approve membership application operation           |
| `check_dues_schedule_invoice_relationship` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check dues schedule invoice relationship operation |
| `check_member_iban_data`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check member iban data operation                   |
| `create_default_email_templates`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new default email templates                         |
| `debug_and_fix_member_approval`            | READ      | high     | System Manager, Verenigingen Manager                                          | Execute debug and fix member approval operation            |
| `debug_custom_amount_flow`                 | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug custom amount flow operation                 |
| `debug_membership_dues_schedule`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug membership dues schedule operation           |
| `debug_membership_type_settings`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug membership type settings operation           |
| `fix_backend_member_statuses`              | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix backend member statuses operation              |
| `get_application_stats`                    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve application stats data                            |
| `get_pending_applications`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve pending applications data                         |
| `get_pending_reviews_for_member`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve pending reviews for member data                   |
| `reject_membership_application`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reject membership application operation            |
| `send_overdue_notifications`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send overdue notifications operation               |
| `sync_member_statuses`                     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute sync member statuses operation                     |
| `test_member_approval`                     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test member approval operation                     |

### Module: `verenigingen.api.mollie_dashboard_api`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                          | Description                    |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------ |
| `get_financial_report` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve financial report data |

### Module: `verenigingen.api.mollie_subscription_sync`

**Functions:** 2

| Function                            | Operation | Security | Suggested Roles                                          | Description                                         |
| ----------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------- |
| `get_mollie_subscription_details`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mollie subscription details data           |
| `sync_single_customer_subscription` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute sync single customer subscription operation |

### Module: `verenigingen.api.newsletter_demo`

**Functions:** 4

| Function                    | Operation | Security | Suggested Roles                                                               | Description                             |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `create_sample_newsletter`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new sample newsletter            |
| `get_newsletter_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve newsletter statistics data     |
| `populate_email_groups`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute populate email groups operation |
| `setup_email_groups`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup email groups operation    |

### Module: `verenigingen.api.onboarding_info`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_direct_onboarding_link` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve direct onboarding link data |
| `get_onboarding_info`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve onboarding info data        |

### Module: `verenigingen.api.performance_api_validator`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                            |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `get_performance_api_baseline` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve performance api baseline data |

### Module: `verenigingen.api.performance_convenience`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `batch_member_analysis`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute batch member analysis operation         |
| `comprehensive_member_analysis` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute comprehensive member analysis operation |
| `performance_dashboard_data`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute performance dashboard data operation    |

### Module: `verenigingen.api.performance_dashboard_activator`

**Functions:** 2

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `activate_performance_dashboard_gradual` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute activate performance dashboard gradual operation |
| `get_dashboard_activation_status`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dashboard activation status data                |

### Module: `verenigingen.api.performance_measurement`

**Functions:** 4

| Function                                 | Operation | Security | Suggested Roles                                          | Description                                              |
| ---------------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------------- |
| `count_payment_mixin_complexity`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute count payment mixin complexity operation         |
| `measure_database_query_patterns`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute measure database query patterns operation        |
| `measure_payment_history_performance`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute measure payment history performance operation    |
| `run_comprehensive_performance_analysis` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run comprehensive performance analysis operation |

### Module: `verenigingen.api.performance_measurement_api`

**Functions:** 11

| Function                                    | Operation | Security | Suggested Roles                                                               | Description                                                 |
| ------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `analyze_system_bottlenecks`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute analyze system bottlenecks operation                |
| `benchmark_current_performance`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute benchmark current performance operation             |
| `collect_performance_baselines`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute collect performance baselines operation             |
| `create_performance_baseline_snapshot`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new performance baseline snapshot                    |
| `generate_comprehensive_performance_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate comprehensive performance report operation |
| `get_performance_measurement_history`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance measurement history data               |
| `get_performance_summary`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance summary data                           |
| `get_recent_performance_reports`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent performance reports data                    |
| `measure_member_performance`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute measure member performance operation                |
| `measure_payment_history_performance`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute measure payment history performance operation       |
| `measure_sepa_mandate_performance`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute measure sepa mandate performance operation          |

### Module: `verenigingen.api.performance_profiling_api`

**Functions:** 3

| Function                                  | Operation | Security | Suggested Roles                                          | Description                                               |
| ----------------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------------- |
| `analyze_member_doctype_performance`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze member doctype performance operation      |
| `establish_performance_baselines`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute establish performance baselines operation         |
| `run_comprehensive_performance_profiling` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run comprehensive performance profiling operation |

### Module: `verenigingen.api.performance_validation`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `generate_performance_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate performance report operation |

### Module: `verenigingen.api.periodic_donation_operations`

**Functions:** 9

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `create_donation_from_agreement`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new donation from agreement                  |
| `create_periodic_agreement`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new periodic agreement                       |
| `export_agreements`                 | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute export agreements operation                 |
| `generate_periodic_donation_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate periodic donation report operation |
| `generate_tax_receipts`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate tax receipts operation             |
| `get_agreement_statistics`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve agreement statistics data                  |
| `get_donor_agreements`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donor agreements data                      |
| `link_donation_to_agreement`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute link donation to agreement operation        |
| `send_renewal_reminders`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send renewal reminders operation            |

### Module: `verenigingen.api.permission_testing_framework`

**Functions:** 1

| Function                                        | Operation | Security | Suggested Roles                                          | Description                                         |
| ----------------------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------------- |
| `validate_membership_dues_schedule_permissions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate membership dues schedule permissions input |

### Module: `verenigingen.api.phase2_2_validation`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `get_phase22_status`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve phase22 status data                      |
| `test_payment_entry_optimization` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test payment entry optimization operation |

### Module: `verenigingen.api.quick_stock_check`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `find_stock_account_mutations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute find stock account mutations operation |

### Module: `verenigingen.api.rebuild_workspace`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `rebuild_workspace` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute rebuild workspace operation |

### Module: `verenigingen.api.restore_workspace`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `restore_workspace` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute restore workspace operation |

### Module: `verenigingen.api.role_migration`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `consolidate_chapter_roles` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute consolidate chapter roles operation |

### Module: `verenigingen.api.schedule_maintenance`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `get_schedule_health_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve schedule health report data         |
| `prevent_orphaned_schedules` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute prevent orphaned schedules operation |

### Module: `verenigingen.api.security_aware_caching_api`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `configure_cache_settings`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute configure cache settings operation |
| `get_cache_performance_stats` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve cache performance stats data      |
| `get_cached_api_list`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve cached api list data              |

### Module: `verenigingen.api.security_migration_validation`

**Functions:** 2

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `generate_migration_session_report` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate migration session report operation |
| `get_security_framework_status`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security framework status data             |

### Module: `verenigingen.api.simple_measurement_test`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                                        |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `run_payment_operations_benchmark` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run payment operations benchmark operation |

### Module: `verenigingen.api.smart_mapping_deployment_guide`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `smart_mapping_deployment_summary` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute smart mapping deployment summary operation |

### Module: `verenigingen.api.suspension_api`

**Functions:** 8

| Function                   | Operation | Security | Suggested Roles                                                               | Description                            |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `bulk_suspend_members`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute bulk suspend members operation |
| `can_suspend_member`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute can suspend member operation   |
| `get_my_suspension_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve my suspension status data     |
| `get_suspension_list`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve suspension list data          |
| `get_suspension_preview`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve suspension preview data       |
| `get_suspension_status`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve suspension status data        |
| `suspend_member`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute suspend member operation       |
| `unsuspend_member`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute unsuspend member operation     |

### Module: `verenigingen.api.team_admin_utilities`

**Functions:** 2

| Function                             | Operation | Security | Suggested Roles                      | Description                                          |
| ------------------------------------ | --------- | -------- | ------------------------------------ | ---------------------------------------------------- |
| `fix_all_missing_assignment_history` | READ      | high     | System Manager, Verenigingen Manager | Execute fix all missing assignment history operation |
| `fix_missing_assignment_history`     | READ      | high     | System Manager, Verenigingen Manager | Execute fix missing assignment history operation     |

### Module: `verenigingen.api.team_management`

**Functions:** 4

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `bulk_apply_team_role_profiles` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk apply team role profiles operation |
| `get_role_profile_preview`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve role profile preview data              |
| `get_team_members`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve team members data                      |
| `sync_team_with_volunteers`     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync team with volunteers operation     |

### Module: `verenigingen.api.test_dues_schedule_report`

**Functions:** 1

| Function                                | Operation | Security | Suggested Roles                      | Description                                             |
| --------------------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------------------------- |
| `test_dues_schedule_report_permissions` | READ      | high     | System Manager, Verenigingen Manager | Execute test dues schedule report permissions operation |

### Module: `verenigingen.api.test_member_portal_coverage`

**Functions:** 2

| Function                                     | Operation | Security | Suggested Roles                                          | Description                                                  |
| -------------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------------------ |
| `populate_coverage_for_outstanding_invoices` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute populate coverage for outstanding invoices operation |
| `test_member_portal_coverage`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test member portal coverage operation                |

### Module: `verenigingen.api.update_prepare_system_button`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `analyze_eboekhouden_data`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze eboekhouden data operation            |
| `should_remove_prepare_system_button` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute should remove prepare system button operation |

### Module: `verenigingen.api.validate_event_driven_fix`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `compare_architectures` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute compare architectures operation |

### Module: `verenigingen.api.verenigingen_permissions_audit`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `audit_verenigingen_permissions` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute audit verenigingen permissions operation |

### Module: `verenigingen.api.verify_migration`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `verify_chapter_role_cleanup` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify chapter role cleanup operation |

### Module: `verenigingen.api.volunteer_skills`

**Functions:** 5

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `export_skills_data`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute export skills data operation |
| `get_skill_gaps_analysis`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve skill gaps analysis data    |
| `get_skill_recommendations`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve skill recommendations data  |
| `get_skills_overview`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve skills overview data        |
| `search_volunteers_advanced` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search volunteers advanced data      |

### Module: `verenigingen.api.workspace_health`

**Functions:** 2

| Function           | Operation | Security | Suggested Roles                      | Description                        |
| ------------------ | --------- | -------- | ------------------------------------ | ---------------------------------- |
| `diagnose_and_fix` | WRITE     | high     | System Manager, Verenigingen Manager | Execute diagnose and fix operation |
| `quick_fix`        | READ      | high     | System Manager, Verenigingen Manager | Execute quick fix operation        |

### Module: `verenigingen.api.workspace_reorganizer`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `reorganize_workspace` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reorganize workspace operation |

### Module: `verenigingen.auth_hooks`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                          | Description                    |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------ |
| `get_member_home_page` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member home page data |

### Module: `verenigingen.config.dashboard_charts`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                          | Description                           |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `get_member_age_distribution` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member age distribution data |

### Module: `verenigingen.debug_api`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `test_membership_application` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test membership application operation |

### Module: `verenigingen.doctype.system_alert.system_alert`

**Functions:** 3

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `acknowledge_alert` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute acknowledge alert operation |
| `get_alert_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve alert summary data         |
| `resolve_alert`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute resolve alert operation     |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_account_manager`

**Functions:** 3

| Function                                         | Operation | Security | Suggested Roles                                          | Description                                                      |
| ------------------------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------------------- |
| `cleanup_eboekhouden_accounts_with_confirmation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup eboekhouden accounts with confirmation operation |
| `get_account_cleanup_status`                     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve account cleanup status data                             |
| `get_eboekhouden_accounts_summary`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve eboekhouden accounts summary data                       |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_clean_reimport`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `execute_clean_import`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute execute clean import operation          |
| `preview_clean_import`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute preview clean import operation          |
| `setup_enhanced_infrastructure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup enhanced infrastructure operation |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_item_mapping_tool`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                          | Description                     |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------- |
| `create_mapping`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new mapping              |
| `get_unmapped_accounts` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve unmapped accounts data |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_migration`

**Functions:** 2

| Function            | Operation | Security | Suggested Roles                                          | Description                         |
| ------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `execute_migration` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute execute migration operation |
| `preview_migration` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute preview migration operation |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_migration_redesign`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                        |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------- |
| `get_migration_statistics` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve migration statistics data |

### Module: `verenigingen.e_boekhouden.api.setup_eboekhouden_date_fields`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `setup_date_range_fields` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup date range fields operation |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_dashboard.e_boekhouden_dashboard`

**Functions:** 3

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `get_migration_summary`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve migration summary data          |
| `load_dashboard_data`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute load dashboard data operation    |
| `refresh_dashboard_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute refresh dashboard data operation |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_item_mapping.e_boekhouden_item_mapping`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                          | Description                    |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------ |
| `create_default_mappings` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new default mappings    |
| `get_item_for_account`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve item for account data |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration`

**Functions:** 10

| Function                           | Operation | Security | Suggested Roles                                          | Description                                    |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `analyze_eboekhouden_data`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze eboekhouden data operation     |
| `analyze_specific_accounts`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze specific accounts operation    |
| `cleanup_chart_of_accounts`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup chart of accounts operation    |
| `get_account_type_recommendations` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve account type recommendations data     |
| `import_opening_balances_only`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute import opening balances only operation |
| `import_single_mutation`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute import single mutation operation       |
| `run_migration_background`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run migration background operation     |
| `start_migration_api`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute start migration api operation          |
| `start_transaction_import`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute start transaction import operation     |
| `update_account_type_mapping`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update account type mapping information        |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings`

**Functions:** 4

| Function                                | Operation | Security | Suggested Roles                                          | Description                                             |
| --------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------------- |
| `create_cost_centers_from_mappings`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new cost centers from mappings                   |
| `get_grootboekrekeningen`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve grootboekrekeningen data                       |
| `parse_groups_and_suggest_cost_centers` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute parse groups and suggest cost centers operation |
| `preview_cost_center_creation`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute preview cost center creation operation          |

### Module: `verenigingen.e_boekhouden.doctype.party_enrichment_queue.party_enrichment_queue`

**Functions:** 1

| Function           | Operation | Security | Suggested Roles                                          | Description                        |
| ------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------- |
| `retry_enrichment` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute retry enrichment operation |

### Module: `verenigingen.e_boekhouden.utils.cleanup_utils`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `cleanup_chart_of_accounts` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup chart of accounts operation |

### Module: `verenigingen.e_boekhouden.utils.create_eboekhouden_custom_fields`

**Functions:** 2

| Function                             | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `ensure_eboekhouden_fields`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute ensure eboekhouden fields operation    |
| `update_mutation_type_field_options` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update mutation type field options information |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_account_group_fix`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                      | Description                          |
| -------------------- | --------- | -------- | ------------------------------------ | ------------------------------------ |
| `fix_account_groups` | READ      | high     | System Manager, Verenigingen Manager | Execute fix account groups operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_api`

**Functions:** 7

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `explore_invoice_fields`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute explore invoice fields operation    |
| `fix_account_types`         | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix account types operation         |
| `get_dashboard_data_api`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve dashboard data api data            |
| `preview_chart_of_accounts` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute preview chart of accounts operation |
| `preview_customers`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute preview customers operation         |
| `preview_suppliers`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute preview suppliers operation         |
| `update_api_url`            | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update api url information                  |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_coa_import`

**Functions:** 7

| Function                                | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `cleanup_duplicate_bank_accounts`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup duplicate bank accounts operation |
| `coa_import_with_bank_accounts`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute coa import with bank accounts operation   |
| `create_bank_accounts_for_existing_coa` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new bank accounts for existing coa         |
| `create_missing_bank_accounts`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new missing bank accounts                  |
| `discover_missing_bank_accounts`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute discover missing bank accounts operation  |
| `find_bank_accounts_in_coa`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute find bank accounts in coa operation       |
| `fix_bank_account_mappings`             | READ      | high     | System Manager, Verenigingen Manager                     | Execute fix bank account mappings operation       |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_cost_center_fix`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `add_eboekhouden_id_field` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add eboekhouden id field operation |
| `cleanup_cost_centers`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute cleanup cost centers operation     |
| `fix_cost_center_groups`   | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix cost center groups operation   |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `execute_enhanced_migration` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute execute enhanced migration operation |
| `run_migration_dry_run`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run migration dry run operation      |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_ledger_mapping`

**Functions:** 4

| Function                          | Operation | Security | Suggested Roles                                                               | Description                               |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `create_ledger_mapping_doctype`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new ledger mapping doctype         |
| `fetch_and_create_ledger_mapping` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new fetch and ledger mapping       |
| `get_account_code_from_ledger_id` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve account code from ledger id data |
| `quick_create_mapping_from_logs`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new quick mapping from logs        |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_migration_config`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                          | Description                           |
| --------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `setup_payment_modes` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute setup payment modes operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_migration_enhancements`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `run_enhanced_migration` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run enhanced migration operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_rest_client`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                          | Description                           |
| --------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `count_all_mutations` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute count all mutations operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration`

**Functions:** 7

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `analyze_import_failures`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze import failures operation          |
| `export_unprocessed_mutations`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process export unprocessed mutations operation     |
| `export_unprocessed_mutations_csv` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process export unprocessed mutations csv operation |
| `get_mutation_gap_report`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve mutation gap report data                  |
| `get_progress_info`                | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve progress info data                        |
| `import_opening_balances_only`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute import opening balances only operation     |
| `migration_status_summary`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute migration status summary operation         |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `estimate_mutation_range`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute estimate mutation range operation  |
| `fetch_mutations_batch`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute fetch mutations batch operation    |
| `fix_crediteuren_accounts` | READ      | high     | System Manager, Verenigingen Manager                     | Execute fix crediteuren accounts operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_transaction_type_mapper`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                            |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `get_transaction_type_mapping` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve transaction type mapping data |

### Module: `verenigingen.e_boekhouden.utils.import_manager`

**Functions:** 6

| Function                  | Operation | Security | Suggested Roles                                          | Description                         |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `clean_import_all`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute clean import all operation  |
| `clean_import_all`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute clean import all operation  |
| `get_import_status`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve import status data         |
| `get_import_status`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve import status data         |
| `update_existing_imports` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update existing imports information |
| `update_existing_imports` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update existing imports information |

### Module: `verenigingen.e_boekhouden.utils.migration_api`

**Functions:** 5

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `approve_and_continue_migration` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute approve and continue migration operation |
| `create_manual_account_mapping`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new manual account mapping                |
| `get_staging_data_for_review`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve staging data for review data            |
| `preview_mapping_impact`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute preview mapping impact operation         |
| `start_migration_api`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute start migration api operation            |

### Module: `verenigingen.e_boekhouden.utils.reconcile_eboekhouden_balances`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                          | Description                               |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `reconcile_account_05000` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reconcile account 05000 operation |

### Module: `verenigingen.e_boekhouden.utils.stock_account_handler`

**Functions:** 2

| Function                                      | Operation | Security | Suggested Roles                                          | Description                                                   |
| --------------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------------------- |
| `analyze_stock_accounts_in_opening_balances`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze stock accounts in opening balances operation  |
| `import_opening_balances_with_stock_handling` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute import opening balances with stock handling operation |

### Module: `verenigingen.email.advanced_segmentation`

**Functions:** 5

| Function                     | Operation | Security | Suggested Roles                                                               | Description                               |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `analyze_segment_overlap`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze segment overlap operation |
| `create_segment_combination` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new segment combination            |
| `get_available_segments`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve available segments data          |
| `get_segment_recipients`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve segment recipients data          |
| `get_segment_suggestions`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve segment suggestions data         |

### Module: `verenigingen.email.analytics_tracker`

**Functions:** 3

| Function                | Operation | Security | Suggested Roles                                                               | Description                     |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `get_email_analytics`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve email analytics data   |
| `get_engagement_trends` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve engagement trends data |
| `get_member_engagement` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member engagement data |

### Module: `verenigingen.email.automated_campaigns`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                    |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------ |
| `create_automated_campaign` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new automated campaign  |
| `get_active_campaigns`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve active campaigns data |
| `get_campaign_types`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve campaign types data   |

### Module: `verenigingen.email.email_group_sync`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `get_email_group_stats`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve email group stats data              |
| `sync_email_groups_manually` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync email groups manually operation |

### Module: `verenigingen.email.newsletter_templates`

**Functions:** 4

| Function                   | Operation | Security | Suggested Roles                                                               | Description                            |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `get_newsletter_templates` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve newsletter templates data     |
| `get_template_details`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve template details data         |
| `preview_template`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute preview template operation     |
| `send_templated_email`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send templated email operation |

### Module: `verenigingen.email.simplified_email_manager`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_segment_recipient_count`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve segment recipient count data          |
| `send_chapter_email`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send chapter email operation           |
| `send_organization_newsletter` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send organization newsletter operation |

### Module: `verenigingen.fixes.step1_fix_data_fetching`

**Functions:** 2

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `compare_old_vs_new_import` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute compare old vs new import operation |
| `test_new_invoice_creation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test new invoice creation operation |

### Module: `verenigingen.pages.membership_applications`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `bulk_approve_applications` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute bulk approve applications operation |
| `get_application_stats`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve application stats data             |
| `get_pending_applications`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve pending applications data          |

### Module: `verenigingen.permissions`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `can_access_termination_functions_api` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute can access termination functions api operation |
| `test_team_member_access`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test team member access operation              |

### Module: `verenigingen.setup`

**Functions:** 22

| Function                                     | Operation | Security | Suggested Roles                                                               | Description                                                  |
| -------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `add_module_onboarding_custom_field`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add module onboarding custom field operation         |
| `create_donation_types_manual`               | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new donation types manual                             |
| `create_email_templates_manual`              | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new email templates manual                            |
| `examine_existing_onboarding`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute examine existing onboarding operation                |
| `final_onboarding_verification`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute final onboarding verification operation              |
| `fix_btw_installation`                       | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix btw installation operation                       |
| `fix_onboarding_visibility`                  | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix onboarding visibility operation                  |
| `fix_workspace_onboarding_link`              | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix workspace onboarding link operation              |
| `force_workspace_onboarding_link`            | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute force workspace onboarding link operation            |
| `install_email_templates_ui`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute install email templates ui operation                 |
| `install_missing_btw_fields`                 | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute install missing btw fields operation                 |
| `investigate_other_module_onboarding`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute investigate other module onboarding operation        |
| `reinstall_onboarding`                       | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute reinstall onboarding operation                       |
| `run_complete_setup`                         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run complete setup operation                         |
| `run_termination_diagnostics`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run termination diagnostics operation                |
| `setup_membership_application_system_manual` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute setup membership application system manual operation |
| `setup_termination_system_manual`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup termination system manual operation            |
| `setup_workspace_manual`                     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup workspace manual operation                     |
| `verify_app_dependencies`                    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify app dependencies operation                    |
| `verify_btw_installation`                    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute verify btw installation operation                    |
| `verify_donation_type_setup`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify donation type setup operation                 |
| `verify_email_templates`                     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute verify email templates operation                     |

### Module: `verenigingen.setup.add_settings_fields`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `add_missing_email_settings_fields` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add missing email settings fields operation |

### Module: `verenigingen.setup.dd_batch_workflow_setup`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `setup_production_dd_workflow` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup production dd workflow operation |

### Module: `verenigingen.setup.membership_application_workflow_setup`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `setup_membership_workflow` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute setup membership workflow operation |

### Module: `verenigingen.setup.role_profile_setup`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `assign_role_profile_to_user` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute assign role profile to user operation |
| `auto_assign_role_profiles`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute auto assign role profiles operation   |
| `deploy_role_profiles`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute deploy role profiles operation        |

### Module: `verenigingen.setup.security_setup`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `enable_csrf_protection` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute enable csrf protection operation |

### Module: `verenigingen.setup.simple_dd_workflow_setup`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `setup_production_simple_workflow` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup production simple workflow operation |

### Module: `verenigingen.setup.webhook_user_setup`

**Functions:** 3

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `get_webhook_credentials_manual`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve webhook credentials manual data           |
| `setup_webhook_user_manual`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup webhook user manual operation        |
| `verify_webhook_user_setup_manual` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify webhook user setup manual operation |

### Module: `verenigingen.setup.workflow_setup`

**Functions:** 1

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `setup_production_workflows_corrected` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup production workflows corrected operation |

### Module: `verenigingen.templates.pages.address_change`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `get_current_address`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve current address data     |
| `update_member_address` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update member address information |

### Module: `verenigingen.templates.pages.bank_details_confirm`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `check_foppe_member_record` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check foppe member record operation |
| `get_current_user_info`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve current user info data             |
| `test_foppe_member_lookup`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test foppe member lookup operation  |

### Module: `verenigingen.templates.pages.chapter_dashboard`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_chapter_dashboard_data` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter dashboard data data |

### Module: `verenigingen.templates.pages.contact_request`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `submit_contact_request` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute submit contact request operation |

### Module: `verenigingen.templates.pages.donate`

**Functions:** 3

| Function              | Operation | Security | Suggested Roles                                                               | Description                          |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `force_doctype_sync`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute force doctype sync operation |
| `get_donation_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve donation status data        |
| `mark_donation_paid`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute mark donation paid operation |

### Module: `verenigingen.templates.pages.donate_optimized`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_donation_status`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve donation status data        |
| `get_performance_comparison` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance comparison data |
| `mark_donation_paid`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute mark donation paid operation |

### Module: `verenigingen.templates.pages.dues_schedule_admin`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `trigger_auto_creation` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trigger auto creation operation |

### Module: `verenigingen.templates.pages.install_email_templates`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                                          | Description                         |
| ------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `install_templates` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute install templates operation |

### Module: `verenigingen.templates.pages.manage_donations`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                          | Description                  |
| -------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------- |
| `get_donation_stats` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve donation stats data |

### Module: `verenigingen.templates.pages.membership_application`

**Functions:** 3

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `calculate_suggested_contribution` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute calculate suggested contribution operation |
| `get_membership_type_details`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve membership type details data              |
| `validate_contribution_amount`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate contribution amount input                 |

### Module: `verenigingen.templates.pages.membership_fee_adjustment`

**Functions:** 3

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                             |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------- |
| `get_available_membership_types`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve available membership types data                |
| `get_fee_calculation_info`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve fee calculation info data                      |
| `submit_membership_type_change_request` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute submit membership type change request operation |

### Module: `verenigingen.templates.pages.my_dues_schedule`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `export_schedule`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute export schedule operation        |
| `get_payment_details`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve payment details data            |
| `update_notification_settings` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update notification settings information |

### Module: `verenigingen.templates.pages.test_mollie`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `test_payment_creation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test payment creation operation |

### Module: `verenigingen.templates.pages.volunteer.expenses`

**Functions:** 4

| Function                      | Operation | Security | Suggested Roles                                                               | Description                              |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `create_volunteer_for_member` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new volunteer for member          |
| `get_expense_details`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve expense details data            |
| `get_organization_options`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve organization options data       |
| `upload_expense_receipt`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute upload expense receipt operation |

### Module: `verenigingen.templates.pages.volunteer.skills`

**Functions:** 1

| Function        | Operation | Security | Suggested Roles                                                               | Description        |
| --------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------ |
| `search_skills` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search skills data |

### Module: `verenigingen.templates.pages.workflow_demo`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `execute_workflow_action` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute execute workflow action operation |
| `get_workflow_actions`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve workflow actions data            |

### Module: `verenigingen.utils`

**Functions:** 2

| Function              | Operation | Security | Suggested Roles                                          | Description                           |
| --------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `apply_btw_exemption` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute apply btw exemption operation |
| `fix_workspace_order` | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute fix workspace order operation |

### Module: `verenigingen.utils.account_creation_manager`

**Functions:** 7

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                               |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| `get_failed_requests`                     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve failed requests data                             |
| `process_account_creation_request`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process account creation request operation                |
| `process_bulk_account_creation_batch`     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process bulk account creation batch operation             |
| `queue_account_creation_for_member`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute queue account creation for member operation       |
| `queue_account_creation_for_volunteer`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute queue account creation for volunteer operation    |
| `queue_bulk_account_creation_for_members` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute queue bulk account creation for members operation |
| `retry_failed_request`                    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute retry failed request operation                    |

### Module: `verenigingen.utils.account_group_project_framework`

**Functions:** 3

| Function                                   | Operation | Security | Suggested Roles                                                               | Description                                        |
| ------------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `get_account_group_defaults`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve account group defaults data               |
| `get_valid_cost_centers_for_account_group` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve valid cost centers for account group data |
| `get_valid_projects_for_account_group`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve valid projects for account group data     |

### Module: `verenigingen.utils.account_group_validation_hooks`

**Functions:** 4

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                     |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `get_account_defaults_for_form`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve account defaults for form data         |
| `get_account_group_info_for_account`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve account group info for account data    |
| `get_filtered_cost_centers_for_account` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve filtered cost centers for account data |
| `get_filtered_projects_for_account`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve filtered projects for account data     |

### Module: `verenigingen.utils.address_formatter`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `format_member_address` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute format member address operation |

### Module: `verenigingen.utils.alert_manager`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                    |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------ |
| `get_alert_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve alert statistics data |

### Module: `verenigingen.utils.analytics_engine`

**Functions:** 6

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                   |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `analyze_error_patterns`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze error patterns operation      |
| `forecast_performance_trends`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute forecast performance trends operation |
| `generate_insights_report`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate insights report operation    |
| `get_performance_recommendations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance recommendations data     |
| `identify_compliance_gaps`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute identify compliance gaps operation    |
| `identify_error_hotspots`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute identify error hotspots operation     |

### Module: `verenigingen.utils.analyze_account_mappings`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `analyze_imported_transactions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze imported transactions operation |
| `trace_specific_mutation`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trace specific mutation operation       |

### Module: `verenigingen.utils.analyze_like_usage`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                                               | Description                          |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `analyze_like_usage` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze like usage operation |

### Module: `verenigingen.utils.analyze_mutation_ledgers`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `analyze_mutation_ledgers` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze mutation ledgers operation |

### Module: `verenigingen.utils.analyze_remaining_fallbacks`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                          | Description                                           |
| ------------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------------- |
| `analyze_remaining_fallbacks`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze remaining fallbacks operation         |
| `recommend_fallback_removal_priority` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute recommend fallback removal priority operation |

### Module: `verenigingen.utils.api_endpoint_optimizer`

**Functions:** 3

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `analyze_api_performance` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze api performance operation |
| `generate_api_report`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate api report operation     |
| `run_api_optimization`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run api optimization operation    |

### Module: `verenigingen.utils.api_response`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `my_api_function` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute my api function operation |

### Module: `verenigingen.utils.billing_frequency_transition_manager`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `execute_billing_frequency_transition` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute execute billing frequency transition operation |
| `get_billing_transition_preview`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve billing transition preview data               |

### Module: `verenigingen.utils.board_member_functional_test`

**Functions:** 2

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `test_board_member_functionality`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test board member functionality operation  |
| `test_expense_workflow_simulation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test expense workflow simulation operation |

### Module: `verenigingen.utils.brand_css_generator`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `debug_member_user_link` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member user link operation |
| `regenerate_brand_css`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute regenerate brand css operation   |

### Module: `verenigingen.utils.bulk_queue_config`

**Functions:** 2

| Function           | Operation | Security | Suggested Roles                                                               | Description                        |
| ------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `clear_stuck_jobs` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear stuck jobs operation |
| `get_queue_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve queue status data         |

### Module: `verenigingen.utils.bulk_retry_processor`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `clear_retry_queue`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear retry queue operation |
| `get_retry_queue_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve retry queue status data    |

### Module: `verenigingen.utils.cache_invalidation`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `get_cache_status`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve cache status data                  |
| `manual_cache_invalidation` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute manual cache invalidation operation |
| `warm_cache_manually`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute warm cache manually operation       |

### Module: `verenigingen.utils.chapter_board_permissions`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `reset_chapter_board_permissions` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reset chapter board permissions operation |
| `setup_chapter_board_permissions` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup chapter board permissions operation |

### Module: `verenigingen.utils.chapter_role_events`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_user_board_summary`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user board summary data               |
| `sync_all_chapter_board_roles` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync all chapter board roles operation |

### Module: `verenigingen.utils.chapter_role_profile_manager`

**Functions:** 4

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                               |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| `assign_chapter_board_role_profile`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute assign chapter board role profile operation       |
| `bulk_assign_chapter_board_role_profiles` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk assign chapter board role profiles operation |
| `get_chapter_board_role_profile_mapping`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter board role profile mapping data          |
| `remove_chapter_board_role_profile`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute remove chapter board role profile operation       |

### Module: `verenigingen.utils.chapter_security`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                            |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `get_user_chapter_permissions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user chapter permissions data |

### Module: `verenigingen.utils.cleanup_direct_sql`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `direct_cleanup_gl_and_pl` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute direct cleanup gl and pl operation |

### Module: `verenigingen.utils.cleanup_function_summary`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `cleanup_function_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup function summary operation |

### Module: `verenigingen.utils.contribution_amendment_utilities`

**Functions:** 5

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                             |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------- |
| `check_membership_type_billing_periods` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check membership type billing periods operation |
| `fix_membership_type_billing_periods`   | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix membership type billing periods operation   |
| `fix_orphaned_schedule_templates`       | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix orphaned schedule templates operation       |
| `validate_billing_consistency`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate billing consistency input                      |
| `validate_production_schema`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate production schema input                        |

### Module: `verenigingen.utils.create_missing_indexes`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------- |
| `create_missing_indexes` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new missing indexes |

### Module: `verenigingen.utils.create_missing_item`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description             |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------- |
| `create_missing_item` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new missing item |

### Module: `verenigingen.utils.create_period_closing_vouchers`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                        |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `create_period_closing_vouchers` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new period closing vouchers |

### Module: `verenigingen.utils.create_required_items`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                        |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `create_eboekhouden_import_item` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new eboekhouden import item |

### Module: `verenigingen.utils.create_test_member`

**Functions:** 3

| Function                             | Operation | Security | Suggested Roles                                          | Description                                       |
| ------------------------------------ | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `create_test_member_with_membership` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new test member with membership            |
| `get_member_context_debug`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member context debug data                |
| `test_fee_adjustment_with_member`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test fee adjustment with member operation |

### Module: `verenigingen.utils.database_query_analyzer`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `analyze_specific_query` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze specific query operation |

### Module: `verenigingen.utils.dd_security_enhancements`

**Functions:** 3

| Function                            | Operation | Security | Suggested Roles                                                               | Description                               |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `analyze_batch_anomalies`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute analyze batch anomalies operation |
| `create_conflict_resolution_report` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new conflict resolution report     |
| `validate_member_identity`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate member identity input            |

### Module: `verenigingen.utils.debug.check_invoice_customer_data`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `check_invoice_customer_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check invoice customer data operation |
| `search_for_customer_name`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search for customer name data                 |

### Module: `verenigingen.utils.debug.debug_minimum_contribution`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `check_contribution_validation_rules` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check contribution validation rules operation |
| `debug_minimum_contribution_issue`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug minimum contribution issue operation    |

### Module: `verenigingen.utils.debug.debug_minimum_contribution_simple`

**Functions:** 2

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `check_daily_access_membership_type` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check daily access membership type operation |
| `debug_minimum_contribution_simple`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug minimum contribution simple operation  |

### Module: `verenigingen.utils.debug.fix_membership_type_templates`

**Functions:** 3

| Function                                    | Operation | Security | Suggested Roles                                                               | Description                                                 |
| ------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `auto_assign_templates_to_membership_types` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute auto assign templates to membership types operation |
| `check_membership_types_missing_templates`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check membership types missing templates operation  |
| `create_missing_templates`                  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new missing templates                                |

### Module: `verenigingen.utils.debug.fix_orphaned_dues_schedules`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `check_orphaned_dues_schedules` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check orphaned dues schedules operation |
| `fix_orphaned_dues_schedules`   | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix orphaned dues schedules operation   |

### Module: `verenigingen.utils.debug.investigate_vraagposten`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                                        |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `investigate_vraagposten_payments` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute investigate vraagposten payments operation |

### Module: `verenigingen.utils.debug.member_access_inspector`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `check_specific_member_access` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check specific member access operation |

### Module: `verenigingen.utils.debug.member_list_permission_tester`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                          |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `test_member_list_permissions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | List test member permissions entries |

### Module: `verenigingen.utils.debug.member_ownership_inspector`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                      | Description                                      |
| -------------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------------------ |
| `check_and_fix_member_ownership` | READ      | high     | System Manager, Verenigingen Manager | Execute check and fix member ownership operation |

### Module: `verenigingen.utils.debug.member_permission_debugger`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `debug_member_permissions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug member permissions operation |

### Module: `verenigingen.utils.debug.membership_fee_adjustment_debugger`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `debug_membership_fee_adjustment` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug membership fee adjustment operation |
| `get_debug_summary`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve debug summary data                       |
| `test_api_directly`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api directly operation               |

### Module: `verenigingen.utils.debug.membership_types_api_tester`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `test_api_for_multiple_users` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api for multiple users operation |
| `test_membership_types_api`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test membership types api operation   |

### Module: `verenigingen.utils.debug.test_required_field`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `test_membership_type_validation` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test membership type validation operation |

### Module: `verenigingen.utils.debug.test_secure_operations_validation`

**Functions:** 1

| Function                                       | Operation | Security | Suggested Roles                                          | Description                                                    |
| ---------------------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------------------- |
| `analyze_member_doctype_security_improvements` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute analyze member doctype security improvements operation |

### Module: `verenigingen.utils.debug.verify_membership_field_fix`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                      | Description                                   |
| ----------------------------- | --------- | -------- | ------------------------------------ | --------------------------------------------- |
| `verify_membership_field_fix` | READ      | high     | System Manager, Verenigingen Manager | Execute verify membership field fix operation |

### Module: `verenigingen.utils.decorator_error_reproduction`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `reproduce_decorator_error` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reproduce decorator error operation |

### Module: `verenigingen.utils.department_hierarchy`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                         |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `get_volunteer_department` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve volunteer department data  |
| `setup_departments`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup departments operation |
| `sync_approvers`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync approvers operation    |

### Module: `verenigingen.utils.disable_perpetual_inventory`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `disable_perpetual_inventory` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute disable perpetual inventory operation |

### Module: `verenigingen.utils.donation_emails`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `resend_donation_confirmation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute resend donation confirmation operation |
| `resend_payment_confirmation`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute resend payment confirmation operation  |
| `send_anbi_receipt_manual`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send anbi receipt manual operation     |

### Module: `verenigingen.utils.donation_history_manager`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `get_donor_summary`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donor summary data                |
| `sync_all_donor_histories` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync all donor histories operation |
| `sync_donor_history`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync donor history operation       |

### Module: `verenigingen.utils.donor_auto_creation`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_auto_creation_settings` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve auto creation settings data |
| `get_auto_creation_stats`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve auto creation stats data    |

### Module: `verenigingen.utils.donor_customer_sync`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `bulk_sync_donors_to_customers` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk sync donors to customers operation |
| `get_sync_status_summary`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve sync status summary data               |

### Module: `verenigingen.utils.dues_invoice_tracking`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                          | Description                           |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `get_dues_summary_for_member` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve dues summary for member data |

### Module: `verenigingen.utils.dues_schedule_auto_creator`

**Functions:** 9

| Function                                      | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `auto_create_missing_dues_schedules`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new auto missing dues schedules            |
| `auto_create_missing_dues_schedules_enhanced` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new auto missing dues schedules enhanced   |
| `clear_dues_schedule_retry_queue`             | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear dues schedule retry queue operation |
| `create_dues_schedules_for_members`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new dues schedules for members             |
| `get_dues_schedule_retry_queue_status`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dues schedule retry queue status data    |
| `get_members_without_dues_schedules`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve members without dues schedules data      |
| `manually_process_retry_queue`                | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Process manually retry queue operation            |
| `preview_missing_dues_schedules`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute preview missing dues schedules operation  |
| `run_auto_creation_manually`                  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute run auto creation manually operation      |

### Module: `verenigingen.utils.dutch_name_utils`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `format_dutch_full_name`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute format dutch full name operation  |
| `setup_dutch_name_fields` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup dutch name fields operation |

### Module: `verenigingen.utils.employee_user_link`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                      | Description                                        |
| ---------------------------------- | --------- | -------- | ------------------------------------ | -------------------------------------------------- |
| `fix_existing_employee_user_links` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix existing employee user links operation |

### Module: `verenigingen.utils.ensure_cogs_item_group`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `ensure_cogs_item_group`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute ensure cogs item group operation |
| `update_existing_inkoop_items` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update existing inkoop items information |

### Module: `verenigingen.utils.error_handling`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `my_api_function` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute my api function operation |

### Module: `verenigingen.utils.execute_workspace_reorg`

**Functions:** 6

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `analyze_card_break_structure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze card break structure operation |
| `check_payments_workspace`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check payments workspace operation     |
| `execute_reorganization`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute execute reorganization operation       |
| `fix_content_sync`             | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix content sync operation             |
| `fix_index_conflicts`          | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix index conflicts operation          |
| `fix_reports_hierarchy`        | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix reports hierarchy operation        |

### Module: `verenigingen.utils.expense_history_batch_processor`

**Functions:** 2

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                                |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `cleanup_orphaned_expense_history`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup orphaned expense history operation         |
| `process_pending_expense_history_updates` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update process pending expense history updates information |

### Module: `verenigingen.utils.expense_notifications`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `send_approval_notification` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute send approval notification operation |
| `send_overdue_reminders`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send overdue reminders operation     |

### Module: `verenigingen.utils.final_balance_check`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `final_reconciliation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute final reconciliation operation |

### Module: `verenigingen.utils.find_9999_account`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `find_9999_account`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute find 9999 account operation     |
| `fix_9999_under_assets` | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix 9999 under assets operation |

### Module: `verenigingen.utils.find_foppe`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                                          | Description                         |
| ------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `find_foppe_member` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute find foppe member operation |

### Module: `verenigingen.utils.fix_eboekhouden_workspace`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `fix_eboekhouden_payment_mapping_link` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix eboekhouden payment mapping link operation |
| `get_eboekhouden_workspace_status`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve eboekhouden workspace status data             |

### Module: `verenigingen.utils.fix_member_ownership`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                      | Description                            |
| ---------------------- | --------- | -------- | ------------------------------------ | -------------------------------------- |
| `fix_member_ownership` | READ      | high     | System Manager, Verenigingen Manager | Execute fix member ownership operation |

### Module: `verenigingen.utils.fix_mollie_customer_data`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `update_emma_customer_mollie_data` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Update emma customer mollie data information |

### Module: `verenigingen.utils.fix_overpaid_invoice`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                          | Description                                           |
| ------------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------------- |
| `check_eboekhouden_mutation_6208`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check eboekhouden mutation 6208 operation     |
| `fix_overpaid_invoice_vf_stickers_24` | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute fix overpaid invoice vf stickers 24 operation |

### Module: `verenigingen.utils.fraud_detection`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                          | Description                          |
| -------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `check_payment_risk` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check payment risk operation |

### Module: `verenigingen.utils.iban_history_manager`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                     |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `create_initial_iban_history` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new initial iban history |
| `get_iban_history`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve iban history data      |

### Module: `verenigingen.utils.inspect_journal_entry`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `analyze_account_05320` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze account 05320 operation |
| `inspect_journal_entry` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute inspect journal entry operation |

### Module: `verenigingen.utils.interactive_subscription_test`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                          | Description                                            |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------------ |
| `check_simple_payment_status`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check simple payment status operation          |
| `simulate_simple_subscription_payment` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute simulate simple subscription payment operation |

### Module: `verenigingen.utils.investigate_overpaid_invoice`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `investigate_overpaid_invoice` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute investigate overpaid invoice operation |

### Module: `verenigingen.utils.invoice_management`

**Functions:** 1

| Function                             | Operation | Security | Suggested Roles                                          | Description                                          |
| ------------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `cleanup_orphaned_member_references` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup orphaned member references operation |

### Module: `verenigingen.utils.link_ledger_to_accounts`

**Functions:** 2

| Function                               | Operation | Security | Suggested Roles                                          | Description                                     |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `auto_link_ledgers_to_accounts`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute auto link ledgers to accounts operation |
| `create_missing_accounts_from_ledgers` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new missing accounts from ledgers        |

### Module: `verenigingen.utils.logger_config`

**Functions:** 2

| Function                   | Operation | Security | Suggested Roles                                                               | Description                        |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `get_recent_security_logs` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent security logs data |
| `get_security_log_info`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security log info data    |

### Module: `verenigingen.utils.manual_camt_import`

**Functions:** 2

| Function            | Operation | Security | Suggested Roles                                                               | Description                        |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `get_import_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve import status data        |
| `import_camt_file`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute import camt file operation |

### Module: `verenigingen.utils.member_performance_optimizer`

**Functions:** 4

| Function                       | Operation | Security | Suggested Roles                                          | Description                            |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `create_member_optimized`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new member optimized            |
| `get_member_dashboard`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member dashboard data         |
| `process_member_post_creation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process member post creation operation |
| `search_members_optimized`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Search members optimized data          |

### Module: `verenigingen.utils.member_portal_utils`

**Functions:** 4

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                 |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `get_member_portal_stats`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member portal stats data           |
| `get_user_appropriate_home_page` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user appropriate home page data    |
| `set_all_members_home_page`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute set all members home page operation |
| `set_member_home_page`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute set member home page operation      |

### Module: `verenigingen.utils.member_utils`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                          | Description                               |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `my_member_only_function` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute my member only function operation |

### Module: `verenigingen.utils.membership_dues_integration`

**Functions:** 2

| Function               | Operation | Security | Suggested Roles                                          | Description                            |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `adjust_dues_schedule` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute adjust dues schedule operation |
| `create_payment_plan`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new payment plan                |

### Module: `verenigingen.utils.membership_dues_test_validator`

**Functions:** 2

| Function                                    | Operation | Security | Suggested Roles                                          | Description                                       |
| ------------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `run_quick_membership_dues_tests`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run quick membership dues tests operation |
| `validate_membership_dues_test_environment` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate membership dues test environment input   |

### Module: `verenigingen.utils.migration.create_migration_fields`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                                          | Description                             |
| ------------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `create_eboekhouden_migration_fields` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new eboekhouden migration fields |

### Module: `verenigingen.utils.migration.migration_audit_trail`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                           |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `get_migration_audit_details` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve migration audit details data |
| `get_migration_audit_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve migration audit summary data |

### Module: `verenigingen.utils.migration.migration_date_chunking`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `estimate_migration_chunks` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute estimate migration chunks operation |

### Module: `verenigingen.utils.migration.migration_dry_run`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `run_migration_dry_run` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run migration dry run operation |

### Module: `verenigingen.utils.migration.migration_duplicate_detection`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `detect_migration_duplicates` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute detect migration duplicates operation |
| `merge_duplicate_group`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute merge duplicate group operation       |

### Module: `verenigingen.utils.migration.migration_error_recovery`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `get_migration_recovery_report`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve migration recovery report data          |
| `retry_failed_migration_records` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute retry failed migration records operation |

### Module: `verenigingen.utils.migration.migration_performance`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `get_migration_performance_report` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve migration performance report data |

### Module: `verenigingen.utils.migration.migration_transaction_safety`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `create_migration_backup`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new migration backup                  |
| `verify_migration_integrity` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify migration integrity operation |

### Module: `verenigingen.utils.migration.test_enhanced_migration_api`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `create_test_payment_mappings`   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new test payment mappings                 |
| `ensure_payment_mapping_doctype` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute ensure payment mapping doctype operation |

### Module: `verenigingen.utils.mollie_test_helpers`

**Functions:** 1

| Function                               | Operation | Security | Suggested Roles                                          | Description                              |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `create_test_member_with_subscription` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new test member with subscription |

### Module: `verenigingen.utils.mt940_enhanced_fields`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `create_enhanced_mt940_fields` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new enhanced mt940 fields               |
| `get_field_creation_status`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve field creation status data            |
| `remove_enhanced_mt940_fields` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute remove enhanced mt940 fields operation |

### Module: `verenigingen.utils.mt940_import`

**Functions:** 3

| Function                  | Operation | Security | Suggested Roles                                                               | Description                            |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `convert_mt940_to_csv`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute convert mt940 to csv operation |
| `get_mt940_import_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve mt940 import status data      |
| `import_mt940_file`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute import mt940 file operation    |

### Module: `verenigingen.utils.mt940_import_auto`

**Functions:** 4

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `get_bank_accounts_for_mt940`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve bank accounts for mt940 data          |
| `import_mt940_file_auto`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute import mt940 file auto operation       |
| `preview_mt940_import`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute preview mt940 import operation         |
| `setup_bank_account_for_mt940` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute setup bank account for mt940 operation |

### Module: `verenigingen.utils.native_expense_helpers`

**Functions:** 3

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `emergency_clear_departments`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute emergency clear departments operation   |
| `fix_expense_approver_issues`   | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix expense approver issues operation   |
| `refresh_all_expense_approvers` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute refresh all expense approvers operation |

### Module: `verenigingen.utils.optimized_queries`

**Functions:** 9

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                               |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| `bulk_update_mandate_payment_history`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update bulk mandate payment history information           |
| `bulk_update_payment_history`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update bulk payment history information                   |
| `get_active_mandates_for_members`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve active mandates for members data                 |
| `get_chapter_assignments_bulk`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter assignments bulk data                    |
| `get_member_financial_summary`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member financial summary data                    |
| `get_members_with_payment_data`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve members with payment data data                   |
| `get_volunteer_assignments_bulk`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve volunteer assignments bulk data                  |
| `optimize_member_payment_history_update` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update optimize member payment history update information |
| `optimize_volunteer_assignment_loading`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute optimize volunteer assignment loading operation   |

### Module: `verenigingen.utils.performance.config`

**Functions:** 4

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `get_environment_config`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve environment config data           |
| `get_performance_config`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance config data           |
| `reset_performance_config`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reset performance config operation |
| `update_performance_config` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update performance config information      |

### Module: `verenigingen.utils.performance.data_retention`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `get_retention_status`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve retention status data             |
| `run_basic_data_retention` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run basic data retention operation |
| `run_smart_aggregation`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run smart aggregation operation    |

### Module: `verenigingen.utils.performance_dashboard`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                           |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `get_api_performance_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve api performance summary data |

### Module: `verenigingen.utils.performance_event_handlers`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `get_optimization_status`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve optimization status data             |
| `trigger_member_optimization` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute trigger member optimization operation |

### Module: `verenigingen.utils.performance_integration`

**Functions:** 4

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `get_performance_system_status`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance system status data                  |
| `install_safe_performance_optimizations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute install safe performance optimizations operation |
| `trigger_member_bulk_optimization`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute trigger member bulk optimization operation       |
| `uninstall_performance_optimizations`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute uninstall performance optimizations operation    |

### Module: `verenigingen.utils.performance_integration_safe`

**Functions:** 4

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `get_performance_system_status`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance system status data                  |
| `install_safe_performance_optimizations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute install safe performance optimizations operation |
| `trigger_member_bulk_optimization`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute trigger member bulk optimization operation       |
| `uninstall_performance_optimizations`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute uninstall performance optimizations operation    |

### Module: `verenigingen.utils.performance_optimizer`

**Functions:** 5

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `get_optimization_status`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve optimization status data                |
| `implement_caching_improvements` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute implement caching improvements operation |
| `optimize_database_performance`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute optimize database performance operation  |
| `optimize_system_resources`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute optimize system resources operation      |
| `run_performance_optimization`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run performance optimization operation   |

### Module: `verenigingen.utils.permission_security_validator`

**Functions:** 2

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `generate_security_report`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate security report operation         |
| `run_complete_security_validation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run complete security validation operation |

### Module: `verenigingen.utils.portal_customization`

**Functions:** 4

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `analyze_current_portal_usage`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze current portal usage operation     |
| `get_clean_member_portal_menu`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve clean member portal menu data             |
| `reset_portal_menu_to_member_only` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reset portal menu to member only operation |
| `setup_member_portal_menu`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute setup member portal menu operation         |

### Module: `verenigingen.utils.portal_menu_enhancer`

**Functions:** 4

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `add_enhanced_sidebar_to_context` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add enhanced sidebar to context operation |
| `analyze_portal_menu_items`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze portal menu items operation       |
| `generate_portal_menu_html`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate portal menu html operation       |
| `get_user_portal_menu`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user portal menu data                    |

### Module: `verenigingen.utils.project_permissions`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                      |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `get_user_project_teams` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user project teams data |

### Module: `verenigingen.utils.recalculate_opening_balance`

**Functions:** 1

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `recalculate_opening_balance_totals` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute recalculate opening balance totals operation |

### Module: `verenigingen.utils.robust_cleanup_all_data`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `robust_cleanup_all_imported_data` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute robust cleanup all imported data operation |

### Module: `verenigingen.utils.role_analysis`

**Functions:** 2

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                     |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `get_role_optimization_recommendations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve role optimization recommendations data |
| `get_role_usage_report`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve role usage report data                 |

### Module: `verenigingen.utils.role_cleanup`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                        |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `create_role_hierarchy_documentation` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new role hierarchy documentation            |
| `fix_chapter_permission_conflicts`    | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix chapter permission conflicts operation |

### Module: `verenigingen.utils.role_renamer`

**Functions:** 3

| Function                  | Operation | Security | Suggested Roles                                                               | Description                             |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `get_current_role_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve current role status data       |
| `rename_all_roles`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute rename all roles operation      |
| `verify_rename_success`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute verify rename success operation |

### Module: `verenigingen.utils.safe_member_optimizer`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `clear_optimization_caches` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear optimization caches operation |
| `enable_safe_optimization`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute enable safe optimization operation  |
| `get_optimization_stats`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve optimization stats data            |

### Module: `verenigingen.utils.search_kostprijs`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `search_kostprijs_reference` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search kostprijs reference data              |
| `test_minimal_sales_invoice` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test minimal sales invoice operation |

### Module: `verenigingen.utils.security.api_classifier`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `classify_all_api_endpoints` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute classify all api endpoints operation |
| `generate_migration_report`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate migration report operation  |
| `get_implementation_code`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve implementation code data            |

### Module: `verenigingen.utils.security.api_security_framework`

**Functions:** 3

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                   |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `analyze_api_security_status`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze api security status operation |
| `get_security_framework_status`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security framework status data       |
| `get_user_security_profile_analysis` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve user security profile analysis data  |

### Module: `verenigingen.utils.security.audit_logging`

**Functions:** 2

| Function               | Operation | Security | Suggested Roles                                                               | Description                    |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------ |
| `get_audit_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve audit statistics data |
| `search_audit_logs`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search audit logs data         |

### Module: `verenigingen.utils.security.authorization`

**Functions:** 2

| Function            | Operation | Security | Suggested Roles                                                               | Description             |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------- |
| `create_sepa_batch` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa batch   |
| `process_batch`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process batch operation |

### Module: `verenigingen.utils.security.csrf_protection`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `my_api_function` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute my api function operation |

### Module: `verenigingen.utils.security.enhanced_validation`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                                               | Description                      |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `create_member`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new member                |
| `get_validation_schemas` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve validation schemas data |

### Module: `verenigingen.utils.security.rate_limiting`

**Functions:** 2

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `clear_rate_limits` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear rate limits operation |
| `create_sepa_batch` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa batch               |

### Module: `verenigingen.utils.security_audit_script`

**Functions:** 2

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `generate_security_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate security report operation |
| `run_comprehensive_audit`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive audit operation  |

### Module: `verenigingen.utils.security_decorators`

**Functions:** 2

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `expensive_operation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute expensive operation operation |
| `update_member_data`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update member data information        |

### Module: `verenigingen.utils.session_cleanup_enhanced`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `run_session_cleanup` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run session cleanup operation |

### Module: `verenigingen.utils.setup_background_permissions`

**Functions:** 1

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `setup_background_service_permissions` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup background service permissions operation |

### Module: `verenigingen.utils.setup_closing_accounts`

**Functions:** 2

| Function                                            | Operation | Security | Suggested Roles                                                               | Description                                           |
| --------------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `create_period_closing_vouchers_with_account_setup` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new period closing vouchers with account setup |
| `setup_closing_accounts`                            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute setup closing accounts operation              |

### Module: `verenigingen.utils.simple_webhook_test`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `check_payment_entry_issue`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check payment entry issue operation  |
| `test_webhook_member_lookup` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test webhook member lookup operation |

### Module: `verenigingen.utils.smart_security_audit`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `find_unsecured_functions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute find unsecured functions operation |
| `get_next_batch`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve next batch data                   |
| `get_security_summary`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security summary data             |

### Module: `verenigingen.utils.team_role_profile_manager`

**Functions:** 4

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `assign_team_role_profile`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute assign team role profile operation       |
| `bulk_assign_team_role_profiles` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk assign team role profiles operation |
| `get_team_role_profile_mapping`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve team role profile mapping data          |
| `remove_team_role_profile`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute remove team role profile operation       |

### Module: `verenigingen.utils.test_subscription_persona`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `check_emma_payment_status`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check emma payment status operation     |
| `simulate_subscription_payment` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute simulate subscription payment operation |

### Module: `verenigingen.utils.transaction_processing_audit`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                                    |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------- |
| `audit_transaction_processing` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process audit transaction processing operation |

### Module: `verenigingen.utils.update_role_references`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `update_all_role_references` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update all role references information |

### Module: `verenigingen.utils.validate_team_role_migration`

**Functions:** 4

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `cleanup_orphaned_dues_schedules` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup orphaned dues schedules operation |
| `debug_dues_invoice_generation`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug dues invoice generation operation   |
| `full_migration_validation`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute full migration validation operation       |
| `test_robust_invoice_generation`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test robust invoice generation operation  |

### Module: `verenigingen.utils.validation.iban_validator`

**Functions:** 5

| Function                    | Operation | Security | Suggested Roles                                                               | Description                             |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `create_mock_bank_scenario` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new mock bank scenario           |
| `derive_bic_from_iban`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute derive bic from iban operation  |
| `format_iban`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute format iban operation           |
| `generate_invalid_iban`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate invalid iban operation |
| `get_bank_from_iban`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve bank from iban data            |

### Module: `verenigingen.utils.webhook_testing`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                          | Description                                |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `create_test_invoice_for_emma` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new test invoice for emma           |
| `simulate_webhook_payment`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute simulate webhook payment operation |

### Module: `verenigingen.utils.workspace_reports_organizer`

**Functions:** 4

| Function                                       | Operation | Security | Suggested Roles                                                               | Description                                                    |
| ---------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `check_payments_workspace`                     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check payments workspace operation                     |
| `copy_financial_section_to_payments_workspace` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute copy financial section to payments workspace operation |
| `get_reports_structure`                        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve reports structure data                                |
| `reorganize_reports_section`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reorganize reports section operation                   |

### Module: `verenigingen.verenigingen.doctype.account_creation_request.account_creation_request`

**Functions:** 5

| Function                 | Operation | Security | Suggested Roles                                                               | Description                           |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `bulk_queue_requests`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk queue requests operation |
| `get_pending_requests`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve pending requests data        |
| `get_request_statistics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve request statistics data      |
| `queue_processing`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process queue processing operation    |
| `retry_processing`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process retry processing operation    |

### Module: `verenigingen.verenigingen.doctype.account_group_project_mapping.account_group_project_mapping`

**Functions:** 3

| Function                                   | Operation | Security | Suggested Roles                                          | Description                                        |
| ------------------------------------------ | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `get_account_group_defaults`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve account group defaults data               |
| `get_valid_cost_centers_for_account_group` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve valid cost centers for account group data |
| `get_valid_projects_for_account_group`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve valid projects for account group data     |

### Module: `verenigingen.verenigingen.doctype.brand_settings.brand_settings`

**Functions:** 7

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `create_default_brand_settings`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new default brand settings                  |
| `force_rebuild_css`                | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute force rebuild css operation                |
| `generate_brand_css`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate brand css operation               |
| `get_active_brand_settings`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve active brand settings data                |
| `get_brand_css_inline`             | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve brand css inline data                     |
| `get_organization_logo`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve organization logo data                    |
| `sync_brand_settings_to_owl_theme` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync brand settings to owl theme operation |

### Module: `verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                                               | Description                      |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `get_active_operations`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve active operations data  |
| `get_operation_progress` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve operation progress data |

### Module: `verenigingen.verenigingen.doctype.chapter.chapter`

**Functions:** 22

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `add_board_member`                       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute add board member operation                       |
| `assign_member_to_chapter`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute assign member to chapter operation               |
| `assign_member_to_chapter_with_cleanup`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute assign member to chapter with cleanup operation  |
| `bulk_add_members`                       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute bulk add members operation                       |
| `bulk_apply_chapter_board_role_profiles` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk apply chapter board role profiles operation |
| `bulk_deactivate_board_members`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute bulk deactivate board members operation          |
| `bulk_remove_board_members`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute bulk remove board members operation              |
| `get_board_memberships`                  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve board memberships data                          |
| `get_board_role_profile_preview`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve board role profile preview data                 |
| `get_chapter_board_history`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter board history data                      |
| `get_chapter_stats`                      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapter stats data                              |
| `get_chapters_by_postal_code`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve chapters by postal code data                    |
| `join_chapter`                           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute join chapter operation                           |
| `leave`                                  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute leave operation                                  |
| `leave_chapter`                          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute leave chapter operation                          |
| `remove_board_member`                    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute remove board member operation                    |
| `remove_from_board`                      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute remove from board operation                      |
| `send_chapter_newsletter`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send chapter newsletter operation                |
| `suggest_chapter_for_member`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute suggest chapter for member operation             |
| `sync_board_members`                     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute sync board members operation                     |
| `transition_board_role`                  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute transition board role operation                  |
| `update_volunteer_assignment_history`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update volunteer assignment history information          |

### Module: `verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request`

**Functions:** 3

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `approve_join_request`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute approve join request operation  |
| `bulk_approve_requests` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk approve requests operation |
| `reject_join_request`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reject join request operation   |

### Module: `verenigingen.verenigingen.doctype.chapter_role.chapter_role`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `update_chapters_with_role` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update chapters with role information |

### Module: `verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request`

**Functions:** 6

| Function                           | Operation | Security | Suggested Roles                                          | Description                                |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `apply_amendment`                  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute apply amendment operation          |
| `approve_amendment`                | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute approve amendment operation        |
| `create_fee_change_amendment`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new fee change amendment            |
| `process_pending_amendments`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process pending amendments operation       |
| `process_pending_amendments_daily` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process pending amendments daily operation |
| `reject_amendment`                 | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reject amendment operation         |

### Module: `verenigingen.verenigingen.doctype.donation.donation`

**Functions:** 12

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                      |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `create_chapter_donation`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new chapter donation                      |
| `create_donation_allocation_report`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new donation allocation report            |
| `create_donation_from_bank_transfer` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new donation from bank transfer           |
| `create_donor_from_donation`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new donor from donation                   |
| `create_sepa_donation`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa donation                         |
| `generate_anbi_agreement_number`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate anbi agreement number operation |
| `get_anbi_donations_for_reporting`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve anbi donations for reporting data       |
| `get_donation_accounting_summary`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donation accounting summary data        |
| `get_donation_summary_by_purpose`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donation summary by purpose data        |
| `get_donations_by_campaign`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donations by campaign data              |
| `get_donations_by_chapter`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donations by chapter data               |
| `reconcile_donation_accounts`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reconcile donation accounts operation    |

### Module: `verenigingen.verenigingen.doctype.donation.donation_original`

**Functions:** 12

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                      |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `create_chapter_donation`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new chapter donation                      |
| `create_donation_allocation_report`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new donation allocation report            |
| `create_donation_from_bank_transfer` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new donation from bank transfer           |
| `create_donor_from_donation`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new donor from donation                   |
| `create_sepa_donation`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa donation                         |
| `generate_anbi_agreement_number`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate anbi agreement number operation |
| `get_anbi_donations_for_reporting`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve anbi donations for reporting data       |
| `get_donation_accounting_summary`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve donation accounting summary data        |
| `get_donation_summary_by_purpose`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve donation summary by purpose data        |
| `get_donations_by_campaign`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donations by campaign data              |
| `get_donations_by_chapter`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve donations by chapter data               |
| `reconcile_donation_accounts`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reconcile donation accounts operation    |

### Module: `verenigingen.verenigingen.doctype.donation_campaign.donation_campaign`

**Functions:** 4

| Function               | Operation | Security | Suggested Roles                                                               | Description                    |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------ |
| `create_project`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new project             |
| `get_project_summary`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve project summary data  |
| `get_recent_donations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent donations data |
| `get_top_donors`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve top donors data       |

### Module: `verenigingen.verenigingen.doctype.donor.donor`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `refresh_customer_sync` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute refresh customer sync operation |

### Module: `verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry`

**Functions:** 5

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `generate_expulsion_governance_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate expulsion governance report operation |
| `get_expulsion_statistics`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve expulsion statistics data                     |
| `get_member_expulsion_history`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member expulsion history data                 |
| `reverse_expulsion`                    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reverse expulsion operation                    |
| `reverse_expulsion_entry`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reverse expulsion entry operation              |

### Module: `verenigingen.verenigingen.doctype.member.member`

**Functions:** 45

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `assign_member_id`                    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute assign member id operation                    |
| `assign_missing_member_ids`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute assign missing member ids operation           |
| `check_donor_exists`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check donor exists operation                  |
| `create_and_link_mandate_enhanced`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new and link mandate enhanced                  |
| `create_customer`                     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new customer                                   |
| `create_donor_from_member`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new donor from member                          |
| `create_member_user_account`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new member user account                        |
| `create_user`                         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new user                                       |
| `deactivate_old_sepa_mandates`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute deactivate old sepa mandates operation        |
| `debug_address_detection`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug address detection operation             |
| `debug_address_members`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug address members operation               |
| `debug_button_conditions`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug button conditions operation             |
| `debug_chapter_assignment`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug chapter assignment operation            |
| `debug_member_id_assignment`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member id assignment operation          |
| `debug_member_status`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug member status operation                 |
| `derive_bic_from_iban`                | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute derive bic from iban operation                |
| `ensure_member_id`                    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute ensure member id operation                    |
| `fix_existing_member_workflow_status` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix existing member workflow status operation |
| `force_assign_member_id`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute force assign member id operation              |
| `force_update_chapter_display`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update force chapter display information              |
| `force_update_membership_duration`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update force membership duration information          |
| `get_active_sepa_mandate`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve active sepa mandate data                     |
| `get_address_members_html`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve address members html data                    |
| `get_board_memberships`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve board memberships data                       |
| `get_display_membership_fee`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve display membership fee data                  |
| `get_linked_donations`                | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve linked donations data                        |
| `get_member_chapter_display_html`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member chapter display html data             |
| `get_member_chapter_names`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member chapter names data                    |
| `get_member_current_chapters`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member current chapters data                 |
| `get_other_members_at_address`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve other members at address data                |
| `incremental_update_history_tables`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update incremental history tables information         |
| `refresh_fee_change_history`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute refresh fee change history operation          |
| `refresh_sepa_mandates`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute refresh sepa mandates operation               |
| `reject_application`                  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute reject application operation                  |
| `sync_member_dues_rate`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute sync member dues rate operation               |
| `test_amendment_filtering`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test amendment filtering operation            |
| `test_automatic_fee_history_update`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update test automatic fee history update information  |
| `test_dues_schedule_query`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dues schedule query operation            |
| `test_fee_history_functionality`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test fee history functionality operation      |
| `test_incremental_update_method`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update test incremental method information            |
| `test_incremental_update_result`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update test incremental result information            |
| `test_member_form_functionality`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test member form functionality operation      |
| `test_payment_status_detection`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test payment status detection operation       |
| `update_membership_duration`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update membership duration information                |
| `validate_mandate_creation`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate mandate creation input                       |

### Module: `verenigingen.verenigingen.doctype.member.member_id_manager`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                          | Description                               |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `get_member_id_statistics`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member id statistics data        |
| `get_next_member_id_preview` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve next member id preview data      |
| `reset_member_id_counter`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reset member id counter operation |

### Module: `verenigingen.verenigingen.doctype.member.member_utils`

**Functions:** 20

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                     |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `add_manual_payment_record`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute add manual payment record operation     |
| `check_and_handle_sepa_mandate`         | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check and handle sepa mandate operation |
| `check_donor_exists`                    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check donor exists operation            |
| `check_mandate_iban_mismatch`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check mandate iban mismatch operation   |
| `check_sepa_mandate_status`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check sepa mandate status operation     |
| `create_and_link_mandate`               | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new and link mandate                     |
| `create_and_link_mandate_enhanced`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new and link mandate enhanced            |
| `create_sepa_mandate_from_bank_details` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa mandate from bank details       |
| `create_sepa_mandate_from_bank_details` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new sepa mandate from bank details       |
| `debug_postal_code_matching`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug postal code matching operation    |
| `derive_bic_from_iban`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute derive bic from iban operation          |
| `generate_mandate_reference`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate mandate reference operation    |
| `get_board_memberships`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve board memberships data                 |
| `get_linked_donations`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve linked donations data                  |
| `get_member_form_settings`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member form settings data              |
| `get_next_member_id_preview`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve next member id preview data            |
| `need_new_mandate`                      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute need new mandate operation              |
| `reset_member_id_counter`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reset member id counter operation       |
| `update_member_payment_history`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update member payment history information       |
| `validate_mandate_reference`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate mandate reference input                |

### Module: `verenigingen.verenigingen.doctype.member.scheduler`

**Functions:** 10

| Function                                          | Operation | Security | Suggested Roles                                                               | Description                                                       |
| ------------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `enqueue_member_history_refresh`                  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute enqueue member history refresh operation                  |
| `get_duration_update_stats`                       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve duration update stats data                               |
| `get_member_history_refresh_status`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member history refresh status data                       |
| `refresh_specific_member_histories`               | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute refresh specific member histories operation               |
| `run_actual_chapter_assignment_test`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run actual chapter assignment test operation              |
| `run_chapter_assignment_edge_case_tests`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run chapter assignment edge case tests operation          |
| `run_final_comprehensive_chapter_assignment_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run final comprehensive chapter assignment test operation |
| `test_chapter_assignment_functionality`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test chapter assignment functionality operation           |
| `test_member_history_refresh`                     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test member history refresh operation                     |
| `update_single_member_duration`                   | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update single member duration information                         |

### Module: `verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation`

**Functions:** 2

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                 |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `create_opportunity_from_contact_request` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new opportunity from contact request |
| `get_contact_request_analytics`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve contact request analytics data     |

### Module: `verenigingen.verenigingen.doctype.member_contact_request.member_contact_request`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                           |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `create_contact_request`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new contact request            |
| `get_member_contact_requests` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member contact requests data |

### Module: `verenigingen.verenigingen.doctype.membership.dues_schedule_manager`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                 |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `add_to_direct_debit_batch`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute add to direct debit batch operation |
| `get_unpaid_membership_invoices` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve unpaid membership invoices data    |

### Module: `verenigingen.verenigingen.doctype.membership.membership`

**Functions:** 9

| Function                               | Operation | Security | Suggested Roles                                          | Description                                  |
| -------------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `allow_multiple_memberships`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute allow multiple memberships operation |
| `create_dues_schedule_from_membership` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new dues schedule from membership     |
| `get_member_sepa_mandates`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve member sepa mandates data           |
| `process_membership_statuses`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process membership statuses operation        |
| `renew_membership`                     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute renew membership operation           |
| `revert_to_standard_amount`            | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute revert to standard amount operation  |
| `show_all_invoices`                    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute show all invoices operation          |
| `show_payment_history`                 | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute show payment history operation       |
| `sync_membership_payments`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute sync membership payments operation   |

### Module: `verenigingen.verenigingen.doctype.membership.scheduler`

**Functions:** 3

| Function                              | Operation | Security | Suggested Roles                                          | Description                                      |
| ------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `enqueue_process_auto_renewals`       | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process enqueue auto renewals operation          |
| `enqueue_process_expired_memberships` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Process enqueue expired memberships operation    |
| `enqueue_send_renewal_reminders`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute enqueue send renewal reminders operation |

### Module: `verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                                               | Description         |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------- |
| `create_snapshot` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new snapshot |

### Module: `verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule`

**Functions:** 10

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                   |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `create_schedule_from_template`       | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new schedule from template             |
| `create_template_for_membership_type` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new template for membership type       |
| `create_test_schedule`                | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new test schedule                      |
| `debug_template_daglid_issue`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug template daglid issue operation |
| `generate_dues_invoices`              | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate dues invoices operation      |
| `get_member_dues_schedule`            | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve member dues schedule data            |
| `test_billing_day_field`              | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test billing day field operation      |
| `test_template_daglid_fix`            | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute test template daglid fix operation    |
| `update_member_contribution`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Update member contribution information        |
| `validate_and_fix_schedule_dates`     | READ      | high     | System Manager, Verenigingen Manager                                          | Validate and fix schedule dates input         |

### Module: `verenigingen.verenigingen.doctype.membership_goal.membership_goal`

**Functions:** 1

| Function           | Operation | Security | Suggested Roles                                                               | Description                  |
| ------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------- |
| `update_all_goals` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update all goals information |

### Module: `verenigingen.verenigingen.doctype.membership_type.membership_type`

**Functions:** 3

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                   |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `get_dues_schedule_template`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dues schedule template data          |
| `get_membership_contribution_options` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve membership contribution options data |
| `get_template_query`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve template query data                  |

### Module: `verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description                   |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------- |
| `get_import_template` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve import template data |

### Module: `verenigingen.verenigingen.doctype.mt940_import.mt940_import`

**Functions:** 4

| Function                         | Operation | Security | Suggested Roles                                          | Description                                   |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `create_mollie_bulk_import`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new mollie bulk import                 |
| `estimate_mollie_bulk_import`    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute estimate mollie bulk import operation |
| `get_mollie_bulk_import_history` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Retrieve mollie bulk import history data      |
| `submit_import`                  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute submit import operation               |

### Module: `verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `get_optimization_status`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve optimization status data              |
| `remove_optimizations`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute remove optimizations operation         |
| `run_performance_optimization` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run performance optimization operation |

### Module: `verenigingen.verenigingen.doctype.periodic_donation_agreement.periodic_donation_agreement`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `get_anbi_validation_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve anbi validation status data |
| `link_donation`              | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute link donation operation      |

### Module: `verenigingen.verenigingen.doctype.region.region`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `find_region_by_postal_code` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute find region by postal code operation |
| `get_regional_coordinator`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve regional coordinator data           |
| `get_regions_for_dropdown`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve regions for dropdown data           |

### Module: `verenigingen.verenigingen.doctype.team.team`

**Functions:** 6

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `bulk_apply_team_role_profiles`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk apply team role profiles operation      |
| `fix_all_missing_assignment_history` | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix all missing assignment history operation |
| `fix_missing_assignment_history`     | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix missing assignment history operation     |
| `get_role_profile_preview`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve role profile preview data                   |
| `get_team_members`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve team members data                           |
| `sync_team_with_volunteers`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync team with volunteers operation          |

### Module: `verenigingen.verenigingen.doctype.team.team_original_backup`

**Functions:** 7

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `bulk_apply_team_role_profiles`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute bulk apply team role profiles operation      |
| `fix_all_missing_assignment_history` | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix all missing assignment history operation |
| `fix_missing_assignment_history`     | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix missing assignment history operation     |
| `get_role_profile_preview`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve role profile preview data                   |
| `get_team_members`                   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve team members data                           |
| `sync_team_with_volunteers`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute sync team with volunteers operation          |
| `test_team_member_removal`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test team member removal operation           |

### Module: `verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings`

**Functions:** 5

| Function                        | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `generate_webhook_secret`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate webhook secret operation |
| `get_income_account_query`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve income account query data        |
| `get_organization_email_domain` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve organization email domain data   |
| `get_plans_for_membership`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve plans for membership data        |
| `revoke_key`                    | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute revoke key operation              |

### Module: `verenigingen.verenigingen.doctype.volunteer.volunteer`

**Functions:** 12

| Function                       | Operation | Security | Suggested Roles                                                               | Description                             |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `add_activity`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add activity operation          |
| `calculate_total_hours`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute calculate total hours operation |
| `create_from_member`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new from member                  |
| `create_volunteer_from_member` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new volunteer from member        |
| `end_activity`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute end activity operation          |
| `get_all_skills_list`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve all skills list data           |
| `get_skill_insights`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve skill insights data            |
| `get_skill_suggestions`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve skill suggestions data         |
| `get_skills_by_category`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve skills by category data        |
| `get_volunteer_history`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve volunteer history data         |
| `get_volunteers_with_filters`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve volunteers with filters data   |
| `search_volunteers_by_skill`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search volunteers by skill data         |

### Module: `verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense`

**Functions:** 3

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `approve_expense`     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute approve expense operation     |
| `can_approve_expense` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute can approve expense operation |
| `reject_expense`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute reject expense operation      |

### Module: `verenigingen.verenigingen.onboarding_step.verenigingen_configure_security.verenigingen_configure_security`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `get_security_configuration_guide` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security configuration guide data |

### Module: `verenigingen.verenigingen.page.membership_analytics.membership_analytics`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `create_goal`           | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new goal                         |
| `export_dashboard_data` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute export dashboard data operation |

### Module: `verenigingen.verenigingen.report.bulk_operations_performance_report.bulk_operations_performance_report`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                                               | Description                      |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `get_performance_alerts` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance alerts data |
| `get_performance_trends` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance trends data |

### Module: `verenigingen.verenigingen.report.members_without_active_memberships.members_without_active_memberships`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                                               | Description                  |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------- |
| `get_report_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve report summary data |

### Module: `verenigingen.verenigingen.report.members_without_dues_schedule.members_without_dues_schedule`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                      | Description                                  |
| ---------------------------- | --------- | -------- | ------------------------------------ | -------------------------------------------- |
| `fix_member_schedule_issues` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix member schedule issues operation |

### Module: `verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis`

**Functions:** 4

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                 |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `debug_coverage_fields`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug coverage fields operation     |
| `export_gap_analysis`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute export gap analysis operation       |
| `generate_catchup_invoices`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute generate catchup invoices operation |
| `get_coverage_timeline_data` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve coverage timeline data data        |

### Module: `verenigingen.verenigingen.web_form.membership_application`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `approve_membership_application` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute approve membership application operation |
| `reject_membership_application`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute reject membership application operation  |

### Module: `verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form`

**Functions:** 3

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `calculate_payment_amount` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute calculate payment amount operation |
| `get_agreement_terms`      | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve agreement terms data              |
| `process_agreement_form`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Process agreement form operation           |

### Module: `verenigingen.www.onboarding_member_setup`

**Functions:** 2

| Function                                | Operation | Security | Suggested Roles                                          | Description                                             |
| --------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------------- |
| `cleanup_test_data`                     | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute cleanup test data operation                     |
| `generate_test_members_from_onboarding` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate test members from onboarding operation |

## Low Priority Functions

**Count:** 511

### Module: `scripts.api_maintenance.cleanup_test_data`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `cleanup_duplicate_test_data` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup duplicate test data operation |

### Module: `scripts.api_maintenance.eboekhouden_mapping_setup`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `test_mutation_mapping` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mutation mapping operation |

### Module: `scripts.debug.check_scheduler_status`

**Functions:** 1

| Function                             | Operation | Security | Suggested Roles                                          | Description                                          |
| ------------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `check_scheduler_and_dues_schedules` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check scheduler and dues schedules operation |

### Module: `scripts.debug.debug_chapter_assignment`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `debug_jantje_chapter_assignment` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug jantje chapter assignment operation |

### Module: `scripts.debug.debug_dashboard_access`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `debug_dashboard_access` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug dashboard access operation |

### Module: `scripts.debug.debug_volunteer_lookup`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `debug_current_user_volunteer_lookup` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug current user volunteer lookup operation |

### Module: `scripts.debug.fix_dashboard_chart_issue`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                      | Description                                 |
| --------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------------- |
| `fix_dashboard_chart_issue` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix dashboard chart issue operation |

### Module: `scripts.debug.incremental_update_debug_test`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `test_expense_mixin_build_method` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test expense mixin build method operation |

### Module: `scripts.debug.remove_period_closing_vouchers`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `check_period_closing_vouchers`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check period closing vouchers operation  |
| `remove_period_closing_vouchers` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute remove period closing vouchers operation |

### Module: `scripts.debug.system_status_check`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `check_field_reference_sample` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check field reference sample operation |
| `check_system_status`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check system status operation          |

### Module: `scripts.deployment.validate_production_schema`

**Functions:** 2

| Function                     | Operation | Security | Suggested Roles                                                               | Description                      |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `validate_production_data`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate production data input   |
| `validate_production_schema` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate production schema input |

### Module: `scripts.eboekhouden.simple_stock_test`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `test_stock_account_handling` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test stock account handling operation |

### Module: `scripts.migration.manual_employee_creation`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_volunteer_employee_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check volunteer employee status operation |

### Module: `scripts.monitoring.establish_baseline`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `establish_performance_baseline` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute establish performance baseline operation |

### Module: `scripts.monitoring.monitor_monitoring_system_health`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `monitor_monitoring_system_health` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute monitor monitoring system health operation |

### Module: `scripts.monitoring.performance_baseline_tracker`

**Functions:** 4

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `establish_baseline`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute establish baseline operation          |
| `generate_improvement_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate improvement report operation |
| `quick_performance_check`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute quick performance check operation     |
| `validate_improvement_claim`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Validate improvement claim input              |

### Module: `scripts.monitoring.production_deployment_validator`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                          |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `validate_production_deployment` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate production deployment input |

### Module: `scripts.monitoring.zabbix_integration`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `zabbix_webhook_receiver` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute zabbix webhook receiver operation |

### Module: `scripts.performance.infrastructure_validator`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `validate_performance_infrastructure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance infrastructure input |

### Module: `scripts.performance.performance_measurement_script`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `measure_test_suite_performance` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute measure test suite performance operation |

### Module: `scripts.testing.check_test_accounts`

**Functions:** 1

| Function         | Operation | Security | Suggested Roles                                                               | Description                      |
| ---------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `check_accounts` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check accounts operation |

### Module: `scripts.testing.integration.check_workspace`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `check_workspace_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check workspace status operation |

### Module: `scripts.testing.integration.final_comprehensive_test`

**Functions:** 1

| Function                                          | Operation | Security | Suggested Roles                                                               | Description                                                       |
| ------------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `run_final_comprehensive_chapter_assignment_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run final comprehensive chapter assignment test operation |

### Module: `scripts.testing.integration.simple_dashboard_test`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                      | Description                 |
| ------------------------- | --------- | -------- | ------------------------------------ | --------------------------- |
| `create_simple_dashboard` | WRITE     | high     | System Manager, Verenigingen Manager | Create new simple dashboard |

### Module: `scripts.testing.integration.test_dashboard_access`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `test_dashboard_access` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dashboard access operation |

### Module: `scripts.testing.integration.test_url_access`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `test_url_access` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test url access operation |

### Module: `scripts.testing.monitoring.generate_test_data`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `cleanup_test_data`             | WRITE     | high     | System Manager, Verenigingen Manager                     | Execute cleanup test data operation             |
| `generate_monitoring_test_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute generate monitoring test data operation |

### Module: `scripts.testing.monitoring.run_monitoring_tests`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `run_monitoring_tests` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run monitoring tests operation |

### Module: `scripts.testing.monitoring.test_memory_management`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `run_memory_management_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run memory management test operation |

### Module: `scripts.testing.monitoring.test_performance_regression`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `run_performance_regression_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run performance regression test operation |

### Module: `scripts.testing.monitoring.test_production_scale`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `run_production_scale_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run production scale test operation |

### Module: `scripts.testing.monitoring.validate_monitoring`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                     |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `test_monitoring_functionality`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test monitoring functionality operation |
| `validate_monitoring_components` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate monitoring components input            |

### Module: `scripts.testing.runners.run_chapter_assignment_tests`

**Functions:** 2

| Function                                     | Operation | Security | Suggested Roles                                                               | Description                                                  |
| -------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `quick_chapter_assignment_test`              | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick chapter assignment test operation              |
| `run_chapter_assignment_comprehensive_tests` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run chapter assignment comprehensive tests operation |

### Module: `scripts.testing.test_coverage_integration`

**Functions:** 2

| Function               | Operation | Security | Suggested Roles                                          | Description                            |
| ---------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `check_data_quality`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check data quality operation   |
| `run_integration_test` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run integration test operation |

### Module: `scripts.testing.test_coverage_report_working`

**Functions:** 2

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `quick_report_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick report test operation |
| `run_demo_test`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run demo test operation     |

### Module: `scripts.testing.test_expense_form_foppe`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `test_expense_form_with_foppe` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test expense form with foppe operation |

### Module: `scripts.testing.test_fee_functions`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `run_all_tests`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run all tests operation               |
| `test_dues_schedule_creation` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dues schedule creation operation |
| `test_fee_calculation`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test fee calculation operation        |

### Module: `scripts.testing.test_incremental_history_final_validation`

**Functions:** 1

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `test_incremental_update_comprehensive` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update test incremental comprehensive information |

### Module: `scripts.validation.phase_1_completion_validator`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `validate_phase_1_completion` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate phase 1 completion input |

### Module: `scripts.validation.validate_coverage_report`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description               |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------- |
| `validate_report_api` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate report api input |

### Module: `scripts.validation.workspace_validator`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                                               | Description              |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------ |
| `validate_workspace` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate workspace input |

### Module: `verenigingen.api.analyze_failing_mutations`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `check_stock_ledger_usage` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check stock ledger usage operation |

### Module: `verenigingen.api.anbi_operations`

**Functions:** 1

| Function       | Operation | Security | Suggested Roles                                                               | Description        |
| -------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------ |
| `validate_bsn` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate bsn input |

### Module: `verenigingen.api.cache_invalidation_api`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `test_cache_invalidation_system` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test cache invalidation system operation |
| `validate_cache_consistency`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate cache consistency input                 |

### Module: `verenigingen.api.chapter_dashboard_api`

**Functions:** 12

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `debug_dashboard_access`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug dashboard access operation           |
| `debug_mt940_import`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug mt940 import operation               |
| `debug_mt940_transaction_creation` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug mt940 transaction creation operation |
| `debug_number_cards`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug number cards operation               |
| `test_dashboard_access`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dashboard access operation            |
| `test_eboekhouden_api_mock`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test eboekhouden api mock operation        |
| `test_eboekhouden_complete`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test eboekhouden complete operation        |
| `test_eboekhouden_framework`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test eboekhouden framework operation       |
| `test_enhanced_mt940_features`     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test enhanced mt940 features operation     |
| `test_mt940_naming_logic`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mt940 naming logic operation          |
| `test_number_card_format`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test number card format operation          |
| `test_url_access`                  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test url access operation                  |

### Module: `verenigingen.api.check_and_fix_workspace`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                      | Description                               |
| ------------------------- | --------- | -------- | ------------------------------------ | ----------------------------------------- |
| `check_and_fix_workspace` | READ      | high     | System Manager, Verenigingen Manager | Execute check and fix workspace operation |

### Module: `verenigingen.api.check_customer_permissions`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `check_customer_permissions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check customer permissions operation |

### Module: `verenigingen.api.check_eboekhouden_fields`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `check_eboekhouden_fields` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check eboekhouden fields operation |

### Module: `verenigingen.api.check_error_logs`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `check_batch_debug_logs` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check batch debug logs operation |

### Module: `verenigingen.api.check_opening_balance_date`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `check_earliest_mutation_date`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check earliest mutation date operation        |
| `check_opening_balance_mutation_date` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check opening balance mutation date operation |

### Module: `verenigingen.api.check_past_imports`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                          | Description                                      |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------ |
| `check_existing_journal_entries` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check existing journal entries operation |
| `check_mutation_import_history`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check mutation import history operation  |

### Module: `verenigingen.api.check_roles`

**Functions:** 7

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `check_coverage_period_fields`        | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check coverage period fields operation        |
| `debug_dues_schedule_dates`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug dues schedule dates operation           |
| `test_complete_billing_fix`           | READ      | high     | System Manager, Verenigingen Manager                                          | Execute test complete billing fix operation           |
| `test_duplicate_prevention`           | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test duplicate prevention operation           |
| `test_duplicate_prevention_in_action` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test duplicate prevention in action operation |
| `test_enhanced_coverage_architecture` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test enhanced coverage architecture operation |
| `validate_role_names_in_code`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate role names in code input                     |

### Module: `verenigingen.api.check_specific_report_permissions`

**Functions:** 1

| Function                             | Operation | Security | Suggested Roles                                          | Description                                          |
| ------------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `check_sensitive_report_permissions` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sensitive report permissions operation |

### Module: `verenigingen.api.check_user`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                                               | Description                          |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `check_user_details` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check user details operation |

### Module: `verenigingen.api.check_workspace`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `check_workspace` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check workspace operation |

### Module: `verenigingen.api.clean_test_chapter`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `clean_billing_test_chapter` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clean billing test chapter operation |

### Module: `verenigingen.api.create_onboarding_steps`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                          |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `create_test_data_onboarding_step` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new test data onboarding step |

### Module: `verenigingen.api.database_index_manager`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                 |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------- |
| `validate_index_impact` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate index impact input |

### Module: `verenigingen.api.debug_doctype_fields`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `debug_migration_doctype` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug migration doctype operation |

### Module: `verenigingen.api.debug_migration`

**Functions:** 9

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `analyze_migration_error_types`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze migration error types operation  |
| `check_supplier_related_errors`  | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check supplier related errors operation  |
| `debug_dues_generation_detailed` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug dues generation detailed operation |
| `debug_schedule_generation`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute debug schedule generation operation      |
| `get_dues_invoicing_errors`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve dues invoicing errors data              |
| `get_error_log_details`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve error log details data                  |
| `get_migration_statistics`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve migration statistics data               |
| `get_recent_migration_errors`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent migration errors data            |
| `run_pre_implementation_tests`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run pre implementation tests operation   |

### Module: `verenigingen.api.debug_refresh_issue`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `test_atomic_vs_full_refresh` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test atomic vs full refresh operation |
| `test_legacy_full_refresh`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test legacy full refresh operation    |

### Module: `verenigingen.api.decorator_analysis_test`

**Functions:** 5

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                            |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `analyze_decorator_types`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze decorator types operation              |
| `run_comprehensive_decorator_analysis` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive decorator analysis operation |
| `test_decorator_factory_vs_direct`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test decorator factory vs direct operation     |
| `test_decorator_loading_issues`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test decorator loading issues operation        |
| `test_problematic_chaining_patterns`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test problematic chaining patterns operation   |

### Module: `verenigingen.api.decorator_compatibility_validator`

**Functions:** 6

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                         |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `run_decorator_compatibility_tests`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run decorator compatibility tests operation |
| `validate_handle_api_error_decorator`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate handle api error decorator input           |
| `validate_individual_decorators`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate individual decorators input                |
| `validate_known_working_pattern`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate known working pattern input                |
| `validate_performance_monitor_decorator` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance monitor decorator input        |
| `validate_standard_api_only`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate standard api only input                    |

### Module: `verenigingen.api.deep_mutation_analysis`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `check_main_ledger_13201869` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check main ledger 13201869 operation |

### Module: `verenigingen.api.donor_auto_creation_management`

**Functions:** 2

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `check_test_accounts`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check test accounts operation       |
| `test_customer_eligibility` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test customer eligibility operation |

### Module: `verenigingen.api.eboekhouden_quick_test`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `quick_system_validation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick system validation operation |
| `test_api_endpoints`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api endpoints operation      |

### Module: `verenigingen.api.eboekhouden_test_runner`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `comprehensive_eboekhouden_test`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute comprehensive eboekhouden test operation  |
| `test_enhanced_migration_dry_run` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute test enhanced migration dry run operation |
| `test_migration_validation`       | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute test migration validation operation       |

### Module: `verenigingen.api.email_template_manager`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `test_email_template` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test email template operation |

### Module: `verenigingen.api.enhanced_background_jobs_api`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `test_job_coordination` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test job coordination operation |

### Module: `verenigingen.api.final_decorator_test`

**Functions:** 4

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `demonstrate_exact_error` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute demonstrate exact error operation |
| `final_analysis_report`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute final analysis report operation   |
| `pattern_3`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute pattern 3 operation               |
| `show_correct_patterns`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute show correct patterns operation   |

### Module: `verenigingen.api.final_refresh_test`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `clean_and_test_refresh` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute clean and test refresh operation |
| `final_button_test`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute final button test operation      |

### Module: `verenigingen.api.fix_custom_fields`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                      | Description                          |
| -------------------------------- | --------- | -------- | ------------------------------------ | ------------------------------------ |
| `validate_fixture_custom_fields` | READ      | high     | System Manager, Verenigingen Manager | Validate fixture custom fields input |

### Module: `verenigingen.api.generate_test_applications`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                 |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `cleanup_test_applications`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup test applications operation |
| `get_test_applications_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve test applications status data      |

### Module: `verenigingen.api.generic_report_tester`

**Functions:** 4

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `discover_and_test_reports`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute discover and test reports operation     |
| `test_all_verenigingen_reports` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test all verenigingen reports operation |
| `test_generic_report_loading`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test generic report loading operation   |
| `test_multiple_reports`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test multiple reports operation         |

### Module: `verenigingen.api.infrastructure_validator`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `validate_performance_infrastructure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance infrastructure input |

### Module: `verenigingen.api.integration_test_framework`

**Functions:** 2

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `get_integration_score_analysis`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve integration score analysis data             |
| `run_comprehensive_integration_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive integration test operation |

### Module: `verenigingen.api.job_status`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `test_background_job_system` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test background job system operation |

### Module: `verenigingen.api.manual_persona_test`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `run_personas_in_reverse` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run personas in reverse operation |

### Module: `verenigingen.api.migration_cleanup_test`

**Functions:** 4

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `comprehensive_cleanup_test`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute comprehensive cleanup test operation      |
| `test_api_connectivity`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api connectivity operation           |
| `test_migration_dry_run`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test migration dry run operation          |
| `test_migration_system_integrity` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test migration system integrity operation |

### Module: `verenigingen.api.mollie_dashboard_api`

**Functions:** 1

| Function   | Operation | Security | Suggested Roles                                          | Description                |
| ---------- | --------- | -------- | -------------------------------------------------------- | -------------------------- |
| `test_api` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test api operation |

### Module: `verenigingen.api.monitoring_production_readiness`

**Functions:** 6

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                      |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `run_production_readiness_check`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run production readiness check operation |
| `validate_configuration_completeness` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate configuration completeness input        |
| `validate_doctype_installation`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate doctype installation input              |
| `validate_performance_acceptance`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance acceptance input            |
| `validate_scheduler_configuration`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate scheduler configuration input           |
| `validate_security_compliance`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate security compliance input               |

### Module: `verenigingen.api.monitoring_test_corrected`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `cleanup_corrected_test_data`    | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute cleanup corrected test data operation    |
| `run_corrected_monitoring_tests` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run corrected monitoring tests operation |

### Module: `verenigingen.api.newsletter_demo`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `send_test_newsletter` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute send test newsletter operation |

### Module: `verenigingen.api.performance_api_validator`

**Functions:** 1

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `validate_performance_apis_with_security` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance apis with security input |

### Module: `verenigingen.api.performance_convenience`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                                               | Description                          |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `quick_health_check` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick health check operation |

### Module: `verenigingen.api.performance_measurement_api`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `test_measurement_infrastructure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test measurement infrastructure operation |

### Module: `verenigingen.api.performance_monitoring_integration_api`

**Functions:** 5

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                          |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `get_comprehensive_performance_metrics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve comprehensive performance metrics data      |
| `get_performance_dashboard_data`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance dashboard data data             |
| `get_phase5a_week2_summary`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve phase5a week2 summary data                  |
| `monitor_phase5a_performance_impact`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute monitor phase5a performance impact operation |
| `test_integrated_performance_system`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test integrated performance system operation |

### Module: `verenigingen.api.performance_validation`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `validate_performance_improvements` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance improvements input |

### Module: `verenigingen.api.periodic_donation_operations`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `check_expiring_agreements`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check expiring agreements operation     |
| `test_periodic_donation_system` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test periodic donation system operation |

### Module: `verenigingen.api.permission_testing_framework`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                          |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `validate_doctype_list_access`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | List validate doctype access entries |
| `validate_permissions_for_user` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate permissions for user input  |

### Module: `verenigingen.api.phase2_2_validation`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                        |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `validate_phase22_performance` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate phase22 performance input |

### Module: `verenigingen.api.phase5a_test_execution`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `execute_database_indexes_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute execute database indexes test operation |
| `get_phase5a_week1_summary`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve phase5a week1 summary data             |

### Module: `verenigingen.api.regression_testing`

**Functions:** 6

| Function                                    | Operation | Security | Suggested Roles                                                               | Description                                                 |
| ------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `run_comprehensive_regression_tests`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive regression tests operation        |
| `test_basic_doctype_operations`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test basic doctype operations operation             |
| `test_permission_caching`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test permission caching operation                   |
| `test_team_project_permissions`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test team project permissions operation             |
| `test_volunteer_after_insert_functionality` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test volunteer after insert functionality operation |
| `test_volunteer_role_assignment`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test volunteer role assignment operation            |

### Module: `verenigingen.api.run_chapter_basic_test`

**Functions:** 1

| Function   | Operation | Security | Suggested Roles                                                               | Description                |
| ---------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------- |
| `run_test` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run test operation |

### Module: `verenigingen.api.security_aware_caching_api`

**Functions:** 3

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `invalidate_data_cache`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate indata cache input                   |
| `invalidate_user_cache`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate inuser cache input                   |
| `test_cached_performance_api` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test cached performance api operation |

### Module: `verenigingen.api.security_migration_validation`

**Functions:** 1

| Function                               | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `validate_security_migration_progress` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate security migration progress input |

### Module: `verenigingen.api.security_monitor_diagnostics`

**Functions:** 3

| Function                                    | Operation | Security | Suggested Roles                                                               | Description                                                 |
| ------------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `diagnose_security_monitor_initialization`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute diagnose security monitor initialization operation  |
| `fix_security_monitor_initialization`       | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix security monitor initialization operation       |
| `test_security_monitor_basic_functionality` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test security monitor basic functionality operation |

### Module: `verenigingen.api.security_monitoring_dashboard`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                            |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `get_security_dashboard_data`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security dashboard data data  |
| `get_security_metrics_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security metrics summary data |

### Module: `verenigingen.api.simple_measurement_test`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `demo_phase1_capabilities`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute demo phase1 capabilities operation     |
| `test_basic_query_measurement` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test basic query measurement operation |

### Module: `verenigingen.api.simple_mutation_test`

**Functions:** 5

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `check_api_mutation_order`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check api mutation order operation    |
| `test_early_mutations_in_api` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test early mutations in api operation |
| `test_iterator_all_mutations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test iterator all mutations operation |
| `test_mutation_1363_date`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mutation 1363 date operation     |
| `test_opening_balances_exist` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test opening balances exist operation |

### Module: `verenigingen.api.smart_mapping_deployment_guide`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `test_migration_readiness` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test migration readiness operation |

### Module: `verenigingen.api.suspension_api`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `test_bank_details_debug` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test bank details debug operation |

### Module: `verenigingen.api.team_admin_utilities`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `debug_team_assignments`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug team assignments operation |
| `validate_team_data_integrity` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate team data integrity input       |

### Module: `verenigingen.api.test_audit_routing`

**Functions:** 2

| Function             | Operation | Security | Suggested Roles                                                               | Description                          |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `test_audit_routing` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test audit routing operation |
| `test_field_mapping` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test field mapping operation |

### Module: `verenigingen.api.test_coverage_fields`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `populate_sample_coverage_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute populate sample coverage data operation |
| `test_coverage_fields`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test coverage fields operation          |

### Module: `verenigingen.api.test_donation_controller`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `test_donation_controller_cleanup` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test donation controller cleanup operation |

### Module: `verenigingen.api.test_eboekhouden_connection`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `test_eboekhouden_connection` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test eboekhouden connection operation |

### Module: `verenigingen.api.test_expense_fix`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_expense_history_structure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check expense history structure operation |
| `test_expense_claim_fix`          | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute test expense claim fix operation          |

### Module: `verenigingen.api.test_incremental_edge_cases`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `test_edge_cases`              | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test edge cases operation              |
| `test_interface_compatibility` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test interface compatibility operation |

### Module: `verenigingen.api.test_incremental_update_final`

**Functions:** 1

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `test_incremental_update_comprehensive` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update test incremental comprehensive information |

### Module: `verenigingen.api.test_mollie_integration`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                          | Description                                   |
| ----------------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------------- |
| `run_mollie_integration_test` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute run mollie integration test operation |

### Module: `verenigingen.api.test_monitoring`

**Functions:** 2

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `cleanup_test_data`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup test data operation    |
| `run_monitoring_tests` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run monitoring tests operation |

### Module: `verenigingen.api.test_phase3_service`

**Functions:** 9

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `analyze_security_improvements`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute analyze security improvements operation     |
| `run_comprehensive_service_test`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive service test operation    |
| `test_api_endpoints`                | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api endpoints operation                |
| `test_bic_derivation`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test bic derivation operation               |
| `test_iban_validation`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test iban validation operation              |
| `test_input_validation`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test input validation operation             |
| `test_mixin_integration`            | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mixin integration operation            |
| `test_sepa_service_import`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test sepa service import operation          |
| `test_service_methods_availability` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test service methods availability operation |

### Module: `verenigingen.api.test_refresh_reliability`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `comprehensive_refresh_test`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute comprehensive refresh test operation      |
| `test_refresh_button_reliability` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test refresh button reliability operation |

### Module: `verenigingen.api.test_template_fixes`

**Functions:** 3

| Function                                | Operation | Security | Suggested Roles                                                               | Description                                             |
| --------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------------- |
| `comprehensive_template_validation`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute comprehensive template validation operation     |
| `test_client_translation_functionality` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test client translation functionality operation |
| `validate_template_fixes`               | READ      | high     | System Manager, Verenigingen Manager                                          | Validate template fixes input                           |

### Module: `verenigingen.api.unified_security_monitoring`

**Functions:** 4

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                     |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `get_integrated_security_metrics` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve integrated security metrics data       |
| `get_monitoring_system_health`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve monitoring system health data          |
| `get_unified_monitoring_overview` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve unified monitoring overview data       |
| `trigger_unified_security_test`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trigger unified security test operation |

### Module: `verenigingen.api.validate_coverage_report`

**Functions:** 4

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `check_database_fields`   | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check database fields operation   |
| `test_gap_classification` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test gap classification operation |
| `test_report_columns`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test report columns operation     |
| `validate_report`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate report input                     |

### Module: `verenigingen.api.validate_event_driven_fix`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                      | Description                      |
| ---------------------------- | --------- | -------- | ------------------------------------ | -------------------------------- |
| `validate_architectural_fix` | WRITE     | high     | System Manager, Verenigingen Manager | Validate architectural fix input |

### Module: `verenigingen.api.validate_sql_fixes`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                      | Description                          |
| -------------------- | --------- | -------- | ------------------------------------ | ------------------------------------ |
| `test_fixed_queries` | READ      | high     | System Manager, Verenigingen Manager | Execute test fixed queries operation |

### Module: `verenigingen.api.workspace_content_validator`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `validate_all_workspaces_content` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate all workspaces content input |
| `validate_workspace_content_sync` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate workspace content sync input |

### Module: `verenigingen.api.workspace_debug`

**Functions:** 9

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `add_missing_eboekhouden_doctypes`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute add missing eboekhouden doctypes operation  |
| `check_dues_system_status`          | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check dues system status operation          |
| `check_eboekhouden_doctypes`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check eboekhouden doctypes operation        |
| `check_eboekhouden_workspace`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check eboekhouden workspace operation       |
| `check_workspace_status`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check workspace status operation            |
| `create_minimal_workspace`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new minimal workspace                        |
| `fix_eboekhouden_workspace_content` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix eboekhouden workspace content operation |
| `force_reload_workspace`            | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute force reload workspace operation            |
| `restore_full_workspace_structure`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute restore full workspace structure operation  |

### Module: `verenigingen.api.workspace_health`

**Functions:** 1

| Function       | Operation | Security | Suggested Roles                                                               | Description                    |
| -------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------ |
| `health_check` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute health check operation |

### Module: `verenigingen.api.workspace_validator`

**Functions:** 3

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                      |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `run_workspace_pre_commit_check`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run workspace pre commit check operation |
| `validate_specific_workspace`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate specific workspace input                |
| `validate_workspace_comprehensive` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate workspace comprehensive input           |

### Module: `verenigingen.api.workspace_validator_enhanced`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_workspace_rendering_issue` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check workspace rendering issue operation |
| `validate_workspaces_enhanced`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate workspaces enhanced input                |

### Module: `verenigingen.debug_coverage`

**Functions:** 2

| Function                           | Operation | Security | Suggested Roles                                          | Description                                        |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------------- |
| `debug_coverage_analysis`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug coverage analysis operation          |
| `debug_coverage_analysis_original` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug coverage analysis original operation |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_migration`

**Functions:** 2

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `debug_opening_balance_import` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug opening balance import operation |
| `test_single_mutation`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test single mutation operation         |

### Module: `verenigingen.e_boekhouden.api.eboekhouden_migration_redesign`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                          | Description                        |
| ------------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------- |
| `validate_migration_readiness` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate migration readiness input |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration`

**Functions:** 3

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `check_migration_data_quality` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check migration data quality operation |
| `check_rest_api_status`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check rest api status operation        |
| `test_group_mappings`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test group mappings operation          |

### Module: `verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings`

**Functions:** 1

| Function          | Operation | Security | Suggested Roles                                          | Description                       |
| ----------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------- |
| `test_connection` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test connection operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_account_group_fix`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `check_problem_accounts` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check problem accounts operation |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_api`

**Functions:** 3

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `check_api_relation_data`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check api relation data operation    |
| `check_equity_import_status` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check equity import status operation |
| `test_api_connection`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api connection operation        |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_coa_import`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                          | Description                          |
| -------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `validate_bank_account_mappings` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate bank account mappings input |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                          | Description                   |
| ------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------- |
| `validate_migration_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate migration data input |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_migration_config`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                    |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------ |
| `validate_migration_setup` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate migration setup input |

### Module: `verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `debug_single_mutation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug single mutation operation |

### Module: `verenigingen.e_boekhouden.utils.migration.quality_checker`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `check_migration_data_quality` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check migration data quality operation |

### Module: `verenigingen.e_boekhouden.utils.stock_opening_balance_handler`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `test_stock_reconciliation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test stock reconciliation operation |

### Module: `verenigingen.email.automated_campaigns`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `trigger_campaign_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trigger campaign test operation |

### Module: `verenigingen.email.validation_utils`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `validate_email_system_components` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate email system components input |

### Module: `verenigingen.events.migration_helper`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                                          | Description                         |
| ------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| `test_event_system` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test event system operation |

### Module: `verenigingen.fixes.correct_implementation_example`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `test_correct_import` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test correct import operation |

### Module: `verenigingen.monitoring.zabbix_integration`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `zabbix_webhook_receiver` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute zabbix webhook receiver operation |

### Module: `verenigingen.setup`

**Functions:** 10

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_module_mapping`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check module mapping operation            |
| `check_onboarding_schema`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check onboarding schema operation         |
| `check_onboarding_setup`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check onboarding setup operation          |
| `check_termination_system_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check termination system status operation |
| `check_workspace_schema`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check workspace schema operation          |
| `debug_onboarding_creation`       | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute debug onboarding creation operation       |
| `debug_onboarding_visibility`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug onboarding visibility operation     |
| `test_email_template_page`        | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test email template page operation        |
| `test_onboarding_api`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test onboarding api operation             |
| `test_onboarding_fix`             | READ      | high     | System Manager, Verenigingen Manager                                          | Execute test onboarding fix operation             |

### Module: `verenigingen.setup.document_links`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `test_document_links` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test document links operation |

### Module: `verenigingen.templates.pages.bank_details`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `simple_test`           | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute simple test operation           |
| `test_bank_details_api` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test bank details api operation |

### Module: `verenigingen.templates.pages.bank_details_confirm`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `test_sepa_integration` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test sepa integration operation |

### Module: `verenigingen.templates.pages.donate`

**Functions:** 10

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `create_test_data`         | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new test data                       |
| `debug_doctype_routing`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug doctype routing operation    |
| `debug_frontend_routing`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug frontend routing operation   |
| `test_awesome_bar_search`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Search test awesome bar search data        |
| `test_direct_url_access`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test direct url access operation   |
| `test_doctype_access`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test doctype access operation      |
| `test_donation_submission` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test donation submission operation |
| `test_donation_system`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test donation system operation     |
| `test_list_view_access`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | List test view access entries              |
| `test_workspace_links`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test workspace links operation     |

### Module: `verenigingen.templates.pages.test_mollie`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `test_comprehensive_mollie` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test comprehensive mollie operation |
| `test_mollie_client`        | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mollie client operation        |
| `test_mollie_settings`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test mollie settings operation      |

### Module: `verenigingen.utils`

**Functions:** 3

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `debug_breadcrumb_detailed`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug breadcrumb detailed operation       |
| `debug_workspace_breadcrumb`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug workspace breadcrumb operation      |
| `debug_workspace_doctype_mapping` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug workspace doctype mapping operation |

### Module: `verenigingen.utils.account_group_project_framework`

**Functions:** 1

| Function                             | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `validate_account_group_transaction` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate account group transaction input |

### Module: `verenigingen.utils.account_group_validation_hooks`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                   |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------- |
| `validate_form_selection` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate form selection input |

### Module: `verenigingen.utils.address_formatter`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `test_address_formatting` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test address formatting operation |

### Module: `verenigingen.utils.address_matching.performance_tester`

**Functions:** 2

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `quick_performance_comparison`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick performance comparison operation       |
| `run_comprehensive_performance_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive performance test operation |

### Module: `verenigingen.utils.admin_utilities.subscription_management_utility`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                          |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------ |
| `create_subscription_for_customer` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Create new subscription for customer |

### Module: `verenigingen.utils.alert_manager`

**Functions:** 4

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `check_critical_errors` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check critical errors operation |
| `run_daily_checks`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run daily checks operation      |
| `run_hourly_checks`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run hourly checks operation     |
| `test_alert_system`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test alert system operation     |

### Module: `verenigingen.utils.analyze_account_mappings`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `check_tegenrekening_mappings` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check tegenrekening mappings operation |

### Module: `verenigingen.utils.analyze_like_usage`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `check_for_ledger_like_patterns` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check for ledger like patterns operation |

### Module: `verenigingen.utils.analyze_mutation_ledgers`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `check_ledger_extraction` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check ledger extraction operation |

### Module: `verenigingen.utils.auth_monitoring`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                      |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `get_auth_health_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve auth health status data |

### Module: `verenigingen.utils.base_role_profile_manager`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `validate_all_role_profiles`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate all role profiles input    |
| `validate_system_configuration` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate system configuration input |

### Module: `verenigingen.utils.billing_frequency_transition_manager`

**Functions:** 1

| Function                                | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `validate_billing_frequency_transition` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate billing frequency transition input |

### Module: `verenigingen.utils.brand_css_generator`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `check_brand_settings_and_generate` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check brand settings and generate operation |

### Module: `verenigingen.utils.bulk_performance_monitor`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                              |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `get_performance_dashboard_data` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance dashboard data data |

### Module: `verenigingen.utils.chapter_role_events`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                                          | Description                               |
| ------------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------- |
| `validate_volunteer_expense_approval` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate volunteer expense approval input |

### Module: `verenigingen.utils.check_existing_accounts`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `check_existing_accounts` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check existing accounts operation |

### Module: `verenigingen.utils.clear_permission_cache`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `clear_permission_cache_and_test` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute clear permission cache and test operation |

### Module: `verenigingen.utils.create_period_closing_vouchers`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `check_p_and_l_impact` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check p and l impact operation |

### Module: `verenigingen.utils.create_required_items`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `check_required_items` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check required items operation |

### Module: `verenigingen.utils.dd_security_enhancements`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `validate_bank_account_sharing` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate bank account sharing input |

### Module: `verenigingen.utils.debug.check_account_groups`

**Functions:** 4

| Function                         | Operation | Security | Suggested Roles                                                               | Description                              |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `create_missing_account_groups`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new missing account groups        |
| `fix_account_parents`            | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix account parents operation    |
| `get_account_group_mappings`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve account group mappings data     |
| `get_complete_account_structure` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve complete account structure data |

### Module: `verenigingen.utils.debug.check_custom_fields`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                          | Description                           |
| --------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `check_custom_fields` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check custom fields operation |

### Module: `verenigingen.utils.debug.check_import_errors`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `check_import_errors` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check import errors operation |

### Module: `verenigingen.utils.debug.check_ledger_mapping`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `check_ledger_mapping_16167827` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check ledger mapping 16167827 operation |
| `trace_balancing_logic_issue`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute trace balancing logic issue operation   |

### Module: `verenigingen.utils.debug.check_memorial_import_logic`

**Functions:** 2

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `check_memorial_import_logic_in_code` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check memorial import logic in code operation |
| `check_mutation_6353`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check mutation 6353 operation                 |

### Module: `verenigingen.utils.debug.check_opening_balance_import`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_import_logic_for_type_0`   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check import logic for type 0 operation   |
| `check_opening_balance_mutations` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check opening balance mutations operation |

### Module: `verenigingen.utils.debug.check_opening_balance_type`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `check_opening_balance_type` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check opening balance type operation |

### Module: `verenigingen.utils.debug.check_projects_cost_centers`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_projects_and_cost_centers` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check projects and cost centers operation |

### Module: `verenigingen.utils.debug.check_remaining_data`

**Functions:** 2

| Function                    | Operation | Security | Suggested Roles                                          | Description                                 |
| --------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------- |
| `check_remaining_data`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check remaining data operation      |
| `nuclear_cleanup_remaining` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute nuclear cleanup remaining operation |

### Module: `verenigingen.utils.debug.check_temporary_accounts`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `check_existing_temporary_accounts` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check existing temporary accounts operation |

### Module: `verenigingen.utils.debug.comprehensive_test_assessment`

**Functions:** 2

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `assess_test_suite_impact` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute assess test suite impact operation |
| `create_test_fix_plan`     | WRITE     | high     | System Manager, Verenigingen Manager                                          | Create new test fix plan                   |

### Module: `verenigingen.utils.debug.coverage_analysis_debugger`

**Functions:** 4

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `create_coverage_fields`  | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new coverage fields                |
| `populate_coverage_dates` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute populate coverage dates operation |
| `quick_coverage_test`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick coverage test operation     |
| `run_full_debug`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run full debug operation          |

### Module: `verenigingen.utils.debug.coverage_report_validator`

**Functions:** 2

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `quick_report_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick report test operation |
| `show_sample_data`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute show sample data operation  |

### Module: `verenigingen.utils.debug.database_index_inspector`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `check_current_database_state` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check current database state operation |

### Module: `verenigingen.utils.debug.debug_template_assignment`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                                       |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------- |
| `check_template_creation_logic`   | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check template creation logic operation   |
| `debug_schedule_creation_history` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug schedule creation history operation |

### Module: `verenigingen.utils.debug.debug_templates`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `debug_template_comparison` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug template comparison operation |

### Module: `verenigingen.utils.debug.direct_permission_checker`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `test_direct_permission_check`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test direct permission check operation  |
| `test_user_permissions_summary` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test user permissions summary operation |

### Module: `verenigingen.utils.debug.eboekhouden_data_cleanup_utility`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `simple_robust_cleanup` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute simple robust cleanup operation |

### Module: `verenigingen.utils.debug.fix_orphaned_gl_entries`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                      | Description                               |
| ------------------------- | --------- | -------- | ------------------------------------ | ----------------------------------------- |
| `fix_orphaned_gl_entries` | WRITE     | high     | System Manager, Verenigingen Manager | Execute fix orphaned gl entries operation |
| `verify_fix`              | WRITE     | high     | System Manager, Verenigingen Manager | Execute verify fix operation              |

### Module: `verenigingen.utils.debug.fix_receivable_payable_accounts`

**Functions:** 2

| Function              | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `check_account_types` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check account types operation |
| `fix_account_types`   | READ      | high     | System Manager, Verenigingen Manager                                          | Execute fix account types operation   |

### Module: `verenigingen.utils.debug.fix_template_minimum`

**Functions:** 2

| Function                                  | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `fix_daily_access_template`               | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute fix daily access template operation         |
| `update_existing_schedules_from_template` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update existing schedules from template information |

### Module: `verenigingen.utils.debug.fix_test_suite`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                            |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `get_test_suite_status` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve test suite status data        |
| `identify_test_issues`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute identify test issues operation |

### Module: `verenigingen.utils.debug.foppe_role_inspector`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `check_foppe_roles_and_permissions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check foppe roles and permissions operation |

### Module: `verenigingen.utils.debug.html_field_tester`

**Functions:** 2

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `check_field_permissions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check field permissions operation |
| `test_html_field`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test html field operation         |

### Module: `verenigingen.utils.debug.identify_fuzzy_logic`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `identify_fuzzy_logic_patterns` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute identify fuzzy logic patterns operation |
| `identify_specific_fuzzy_cases` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute identify specific fuzzy cases operation |

### Module: `verenigingen.utils.debug.optimization_issue_debugger`

**Functions:** 2

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `debug_optimization_issues`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug optimization issues operation     |
| `test_direct_query_performance` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test direct query performance operation |

### Module: `verenigingen.utils.debug.security_framework_validator`

**Functions:** 1

| Function           | Operation | Security | Suggested Roles                                                               | Description                        |
| ------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| `test_api_imports` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test api imports operation |

### Module: `verenigingen.utils.debug.settings_inspector`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `check_creation_user_setting` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check creation user setting operation |

### Module: `verenigingen.utils.debug.test_base_class`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `test_base_class_functionality` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test base class functionality operation |

### Module: `verenigingen.utils.debug.test_consolidated_modules`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `test_consolidated_modules` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test consolidated modules operation |

### Module: `verenigingen.utils.debug.test_data_cleanup_utility`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `cleanup_all_test_data` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup all test data operation |
| `cleanup_test_roles`    | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup test roles operation    |

### Module: `verenigingen.utils.debug.test_enhanced_handler_fix`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                      | Description                                     |
| ------------------------------- | --------- | -------- | ------------------------------------ | ----------------------------------------------- |
| `test_enhanced_handler_api_fix` | READ      | high     | System Manager, Verenigingen Manager | Execute test enhanced handler api fix operation |

### Module: `verenigingen.utils.debug.test_opening_balance_fix`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                      | Description                                  |
| ---------------------------- | --------- | -------- | ------------------------------------ | -------------------------------------------- |
| `test_temporary_account_fix` | WRITE     | high     | System Manager, Verenigingen Manager | Execute test temporary account fix operation |

### Module: `verenigingen.utils.debug.test_opening_balance_import`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `test_opening_balance_import` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test opening balance import operation |

### Module: `verenigingen.utils.debug.test_secure_operations_validation`

**Functions:** 2

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `test_permission_validation_logic`       | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test permission validation logic operation       |
| `test_secure_document_operation_pattern` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test secure document operation pattern operation |

### Module: `verenigingen.utils.debug.test_security_helper`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `test_security_helper` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test security helper operation |

### Module: `verenigingen.utils.debug.test_transaction_management`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `test_transaction_management` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test transaction management operation |

### Module: `verenigingen.utils.debug.test_vraagposten_fix`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                      | Description                              |
| ------------------------ | --------- | -------- | ------------------------------------ | ---------------------------------------- |
| `test_party_account_fix` | READ      | high     | System Manager, Verenigingen Manager | Execute test party account fix operation |

### Module: `verenigingen.utils.debug_bulk_importer`

**Functions:** 2

| Function                 | Operation | Security | Suggested Roles                                                               | Description                          |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `test_api_endpoints`     | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test api endpoints operation |
| `validate_bulk_importer` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate bulk importer input         |

### Module: `verenigingen.utils.decorator_debug`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `test_decorator_pattern` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test decorator pattern operation |

### Module: `verenigingen.utils.disable_perpetual_inventory`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                          | Description                                |
| -------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------ |
| `check_stock_implications` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check stock implications operation |

### Module: `verenigingen.utils.donor_auto_creation`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `test_auto_creation_conditions` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test auto creation conditions operation |

### Module: `verenigingen.utils.dutch_name_utils`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `test_dutch_name_formatting` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test dutch name formatting operation |

### Module: `verenigingen.utils.ensure_cogs_item_group`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `check_inkoop_accounts` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check inkoop accounts operation |

### Module: `verenigingen.utils.execute_workspace_reorg`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `debug_reports_rendering` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug reports rendering operation |

### Module: `verenigingen.utils.expense_history_batch_processor`

**Functions:** 1

| Function                             | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `validate_expense_history_integrity` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate expense history integrity input |

### Module: `verenigingen.utils.final_test_report`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `comprehensive_fee_adjustment_test` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute comprehensive fee adjustment test operation |

### Module: `verenigingen.utils.fix_mollie_customer_data`

**Functions:** 1

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `check_mollie_field_definitions` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check mollie field definitions operation |

### Module: `verenigingen.utils.fraud_detection`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `check_application_risk` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check application risk operation |

### Module: `verenigingen.utils.inspect_journal_entry`

**Functions:** 1

| Function                       | Operation | Security | Suggested Roles                                                               | Description                                    |
| ------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------- |
| `check_memorial_booking_logic` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check memorial booking logic operation |

### Module: `verenigingen.utils.interactive_subscription_test`

**Functions:** 4

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `cleanup_simple_emma`                 | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute cleanup simple emma operation                |
| `create_simple_emma_persona`          | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new simple emma persona                       |
| `create_subscription_for_simple_emma` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new subscription for simple emma              |
| `run_complete_subscription_workflow`  | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run complete subscription workflow operation |

### Module: `verenigingen.utils.link_ledger_to_accounts`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `check_mapping_status` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check mapping status operation |

### Module: `verenigingen.utils.manual_camt_import`

**Functions:** 1

| Function             | Operation | Security | Suggested Roles                                                               | Description              |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------ |
| `validate_camt_file` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate camt file input |

### Module: `verenigingen.utils.migration.check_migration_progress`

**Functions:** 1

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `check_migration_progress` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check migration progress operation |

### Module: `verenigingen.utils.migration.create_migration_fields`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                          | Description                              |
| ------------------------ | --------- | -------- | -------------------------------------------------------- | ---------------------------------------- |
| `check_migration_fields` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check migration fields operation |

### Module: `verenigingen.utils.migration.migration_pre_validation`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                   |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------- |
| `validate_migration_data` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate migration data input |

### Module: `verenigingen.utils.migration.migration_transaction_safety`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `rollback_migration_checkpoint` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute rollback migration checkpoint operation |

### Module: `verenigingen.utils.migration.stock_migration`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                          | Description                                     |
| ------------------------------- | --------- | -------- | -------------------------------------------------------- | ----------------------------------------------- |
| `test_eboekhouden_product_data` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test eboekhouden product data operation |

### Module: `verenigingen.utils.migration.test_enhanced_migration_api`

**Functions:** 2

| Function                   | Operation | Security | Suggested Roles                                                               | Description                                |
| -------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| `run_migration_test`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run migration test operation       |
| `test_soap_api_connection` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test soap api connection operation |

### Module: `verenigingen.utils.mollie_test_helpers`

**Functions:** 4

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `get_mollie_subscription_status`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve mollie subscription status data            |
| `run_mollie_integration_test_suite` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run mollie integration test suite operation |
| `test_mollie_subscription_creation` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test mollie subscription creation operation |
| `test_mollie_webhook_simulation`    | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test mollie webhook simulation operation    |

### Module: `verenigingen.utils.mt940_import`

**Functions:** 1

| Function              | Operation | Security | Suggested Roles                                                               | Description               |
| --------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------- |
| `validate_mt940_file` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate mt940 file input |

### Module: `verenigingen.utils.performance.config`

**Functions:** 1

| Function                      | Operation | Security | Suggested Roles                                                               | Description                       |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------- |
| `validate_performance_config` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate performance config input |

### Module: `verenigingen.utils.performance_test_20250801`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `test_team_validation_performance` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test team validation performance operation |

### Module: `verenigingen.utils.performance_testing`

**Functions:** 4

| Function                             | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `benchmark_single_operation`         | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute benchmark single operation operation         |
| `quick_performance_check`            | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute quick performance check operation            |
| `run_comprehensive_performance_test` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive performance test operation |
| `run_performance_test_suite`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run performance test suite operation         |

### Module: `verenigingen.utils.portal_menu_enhancer`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `debug_portal_settings` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug portal settings operation |

### Module: `verenigingen.utils.resource_monitor`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                      |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------- |
| `get_performance_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance report data |

### Module: `verenigingen.utils.role_cleanup`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                 |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------- |
| `validate_role_cleanup` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate role cleanup input |

### Module: `verenigingen.utils.run_clean_import_test`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                             |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------- |
| `run_clean_import_test` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run clean import test operation |

### Module: `verenigingen.utils.schema_validation`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                      | Description                               |
| ------------------------------------- | --------- | -------- | ------------------------------------ | ----------------------------------------- |
| `validate_chapter_board_schema_fixes` | READ      | high     | System Manager, Verenigingen Manager | Validate chapter board schema fixes input |

### Module: `verenigingen.utils.security.authorization`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                          | Description                                       |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------------------- |
| `check_sepa_operation_permission` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute check sepa operation permission operation |

### Module: `verenigingen.utils.security.enhanced_validation`

**Functions:** 1

| Function                    | Operation | Security | Suggested Roles                                                               | Description                     |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------- |
| `validate_data_with_schema` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate data with schema input |

### Module: `verenigingen.utils.security.security_monitoring`

**Functions:** 3

| Function                    | Operation | Security | Suggested Roles                                                               | Description                                 |
| --------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| `get_security_dashboard`    | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security dashboard data            |
| `resolve_security_incident` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute resolve security incident operation |
| `run_security_tests`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run security tests operation        |

### Module: `verenigingen.utils.security_decorators`

**Functions:** 2

| Function                | Operation | Security | Suggested Roles                                                               | Description                 |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------- |
| `create_test_data`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new test data        |
| `validate_api_security` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate api security input |

### Module: `verenigingen.utils.smart_tegenrekening_mapper`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                          | Description                                  |
| ---------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------------- |
| `test_tegenrekening_mapping` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute test tegenrekening mapping operation |

### Module: `verenigingen.utils.test_board_assignments`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `test_board_assignment_refactoring` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test board assignment refactoring operation |

### Module: `verenigingen.utils.test_schema_simple`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `validate_chapter_board_schema` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate chapter board schema input |

### Module: `verenigingen.utils.test_subscription_persona`

**Functions:** 3

| Function                           | Operation | Security | Suggested Roles                                                               | Description                            |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `cleanup_emma_persona`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute cleanup emma persona operation |
| `create_emma_subscription_persona` | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Create new emma subscription persona   |
| `create_subscription_for_emma`     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new subscription for emma       |

### Module: `verenigingen.utils.test_team_role_assignment_history`

**Functions:** 1

| Function                            | Operation | Security | Suggested Roles                                                               | Description                                         |
| ----------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `test_team_role_assignment_history` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test team role assignment history operation |

### Module: `verenigingen.utils.test_team_role_edge_cases`

**Functions:** 5

| Function                           | Operation | Security | Suggested Roles                                                               | Description                                        |
| ---------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------- |
| `run_all_edge_case_tests`          | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run all edge case tests operation          |
| `test_backwards_compatibility`     | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test backwards compatibility operation     |
| `test_missing_team_role_reference` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test missing team role reference operation |
| `test_team_leader_detection`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test team leader detection operation       |
| `test_unique_role_constraint`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test unique role constraint operation      |

### Module: `verenigingen.utils.test_team_role_integration`

**Functions:** 1

| Function                     | Operation | Security | Suggested Roles                                                               | Description                                  |
| ---------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------- |
| `test_team_role_integration` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test team role integration operation |

### Module: `verenigingen.utils.test_volunteer_refactoring`

**Functions:** 2

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `test_specific_assignment_functionality` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test specific assignment functionality operation |
| `test_volunteer_refactoring`             | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test volunteer refactoring operation             |

### Module: `verenigingen.utils.update_role_references`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                              |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `validate_role_updates` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Update validate role updates information |

### Module: `verenigingen.utils.validate_team_role_migration`

**Functions:** 4

| Function                                 | Operation | Security | Suggested Roles                                                               | Description                                              |
| ---------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| `check_team_role_field_references`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check team role field references operation       |
| `test_enhanced_factory_email_generation` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test enhanced factory email generation operation |
| `test_unique_role_validation_debug`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test unique role validation debug operation      |
| `validate_migration_data_integrity`      | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate migration data integrity input                  |

### Module: `verenigingen.utils.validation.application_validators`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                                     |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| `debug_application_eligibility` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug application eligibility operation |

### Module: `verenigingen.utils.validation.iban_validator`

**Functions:** 2

| Function             | Operation | Security | Suggested Roles                                                               | Description                          |
| -------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `generate_test_iban` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute generate test iban operation |
| `validate_iban`      | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate iban input                  |

### Module: `verenigingen.utils.volunteer_role_test`

**Functions:** 2

| Function                         | Operation | Security | Suggested Roles                                                               | Description                                      |
| -------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `test_project_team_access`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test project team access operation       |
| `test_volunteer_role_assignment` | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute test volunteer role assignment operation |

### Module: `verenigingen.utils.webhook_security`

**Functions:** 1

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                           |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| `test_webhook_signature_verification` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test webhook signature verification operation |

### Module: `verenigingen.utils.webhook_testing`

**Functions:** 4

| Function                        | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `check_emma_status`             | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute check emma status operation |
| `find_emma`                     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute find emma operation         |
| `recreate_emma_with_mollie_ids` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Create new reemma with mollie ids   |
| `test_full_webhook`             | WRITE     | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Execute test full webhook operation |

### Module: `verenigingen.verenigingen.doctype.account_group_project_mapping.account_group_project_mapping`

**Functions:** 1

| Function                           | Operation | Security | Suggested Roles                                          | Description                            |
| ---------------------------------- | --------- | -------- | -------------------------------------------------------- | -------------------------------------- |
| `validate_account_group_selection` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate account group selection input |

### Module: `verenigingen.verenigingen.doctype.analytics_alert_rule.analytics_alert_rule`

**Functions:** 1

| Function                  | Operation | Security | Suggested Roles                                                               | Description                               |
| ------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `check_all_active_alerts` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check all active alerts operation |

### Module: `verenigingen.verenigingen.doctype.brand_settings.brand_settings`

**Functions:** 2

| Function                      | Operation | Security | Suggested Roles                                                               | Description                                   |
| ----------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `check_owl_theme_integration` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute check owl theme integration operation |
| `test_owl_theme_integration`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test owl theme integration operation  |

### Module: `verenigingen.verenigingen.doctype.chapter.chapter`

**Functions:** 1

| Function                | Operation | Security | Suggested Roles                                                               | Description                 |
| ----------------------- | --------- | -------- | ----------------------------------------------------------------------------- | --------------------------- |
| `validate_postal_codes` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate postal codes input |

### Module: `verenigingen.verenigingen.doctype.donation_campaign.donation_campaign`

**Functions:** 1

| Function            | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `test_enhancements` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test enhancements operation |

### Module: `verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import`

**Functions:** 1

| Function               | Operation | Security | Suggested Roles                                                               | Description                |
| ---------------------- | --------- | -------- | ----------------------------------------------------------------------------- | -------------------------- |
| `validate_import_file` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate import file input |

### Module: `verenigingen.verenigingen.doctype.mt940_import.mt940_import`

**Functions:** 3

| Function                | Operation | Security | Suggested Roles                                          | Description                             |
| ----------------------- | --------- | -------- | -------------------------------------------------------- | --------------------------------------- |
| `debug_duplicates`      | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug duplicates operation      |
| `debug_enhanced_import` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug enhanced import operation |
| `debug_import`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Execute debug import operation          |

### Module: `verenigingen.verenigingen.doctype.region.region`

**Functions:** 1

| Function                        | Operation | Security | Suggested Roles                                                               | Description                         |
| ------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `validate_postal_code_patterns` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate postal code patterns input |

### Module: `verenigingen.verenigingen.doctype.team.team`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `debug_team_assignments` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug team assignments operation |

### Module: `verenigingen.verenigingen.doctype.team.team_original_backup`

**Functions:** 1

| Function                 | Operation | Security | Suggested Roles                                                               | Description                              |
| ------------------------ | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------- |
| `debug_team_assignments` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute debug team assignments operation |

### Module: `verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings`

**Functions:** 1

| Function                          | Operation | Security | Suggested Roles                                          | Description                           |
| --------------------------------- | --------- | -------- | -------------------------------------------------------- | ------------------------------------- |
| `validate_donation_configuration` | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff | Validate donation configuration input |

### Module: `verenigingen.verenigingen.onboarding_step.verenigingen_configure_security.verenigingen_configure_security`

**Functions:** 2

| Function                          | Operation | Security | Suggested Roles                                                               | Description                           |
| --------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| `get_security_checklist`          | READ      | medium   | System Manager, Verenigingen Manager, Verenigingen Staff                      | Retrieve security checklist data      |
| `validate_security_configuration` | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate security configuration input |

### Module: `verenigingen.web_form.periodic_donation_agreement_form.periodic_donation_agreement_form`

**Functions:** 1

| Function       | Operation | Security | Suggested Roles                                                               | Description        |
| -------------- | --------- | -------- | ----------------------------------------------------------------------------- | ------------------ |
| `validate_bsn` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Validate bsn input |

### Module: `verenigingen.www.monitoring_dashboard`

**Functions:** 21

| Function                              | Operation | Security | Suggested Roles                                                               | Description                                          |
| ------------------------------------- | --------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------- |
| `cleanup_test_data`                   | WRITE     | high     | System Manager, Verenigingen Manager                                          | Execute cleanup test data operation                  |
| `get_active_alerts`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve active alerts data                          |
| `get_analytics_summary`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve analytics summary data                      |
| `get_audit_summary`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve audit summary data                          |
| `get_compliance_audit_report`         | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve compliance audit report data                |
| `get_compliance_metrics`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve compliance metrics data                     |
| `get_detailed_analytics_report`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve detailed analytics report data              |
| `get_executive_summary`               | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve executive summary data                      |
| `get_optimization_insights`           | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve optimization insights data                  |
| `get_performance_metrics`             | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance metrics data                    |
| `get_performance_optimization_report` | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve performance optimization report data        |
| `get_recent_errors`                   | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve recent errors data                          |
| `get_security_framework_health`       | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security framework health data              |
| `get_security_metrics_for_dashboard`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve security metrics for dashboard data         |
| `get_system_metrics`                  | READ      | high     | System Manager, Verenigingen Manager                                          | Retrieve system metrics data                         |
| `get_trend_forecasts`                 | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve trend forecasts data                        |
| `get_unified_security_summary`        | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Retrieve unified security summary data               |
| `refresh_advanced_dashboard_data`     | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute refresh advanced dashboard data operation    |
| `refresh_dashboard_data`              | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute refresh dashboard data operation             |
| `run_comprehensive_monitoring_tests`  | READ      | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute run comprehensive monitoring tests operation |
| `test_monitoring_system`              | WRITE     | low      | System Manager, Verenigingen Manager, Verenigingen Staff, Verenigingen Member | Execute test monitoring system operation             |

## Implementation Guidance

### Chunked Implementation Strategy

1. **Phase 1 - High Priority (Week 1-2)**
   - Focus on member termination and financial operations
   - Implement high-security CORs with detailed audit logging
   - Test thoroughly before production deployment

2. **Phase 2 - Medium Priority (Week 3-4)**
   - Member data access and contribution management
   - Standard security controls with appropriate rate limiting
   - Regular security monitoring and alerts

3. **Phase 3 - Low Priority (Week 5-6)**
   - Utility functions and monitoring endpoints
   - Basic security controls with relaxed rate limits
   - Focus on operational visibility

### Security Level Guidelines

- **High Security**: 30 calls/minute, detailed audit, manager+ roles, execution alerts
- **Medium Security**: 100 calls/minute, standard audit, staff+ roles, no alerts
- **Low Security**: 300 calls/minute, basic audit, member+ roles, no alerts

### Recommended Role Assignments

- **System Manager**: All operations (emergency access)
- **Verenigingen Manager**: All business operations except system admin
- **Verenigingen Staff**: Standard member/contribution operations
- **Verenigingen Member**: Read-only access to own data

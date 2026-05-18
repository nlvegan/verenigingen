# API Documentation

This document covers the public API endpoints exposed by the Verenigingen app via `@frappe.whitelist()`. All endpoints are accessed through Frappe's standard method call pattern:

```
POST /api/method/verenigingen.<module_path>.<function_name>
```

## Table of Contents

- [Authentication](#authentication)
- [Membership Application (Public)](#membership-application-public)
- [Membership Application Review (Admin)](#membership-application-review-admin)
- [Background Approval](#background-approval)
- [Admin Membership Operations](#admin-membership-operations)
- [Member Management](#member-management)
- [Suspension Management](#suspension-management)
- [Termination](#termination)
- [Chapter Dashboard](#chapter-dashboard)
- [Chapter Join](#chapter-join)
- [Chapter Validation](#chapter-validation)
- [User Chapters](#user-chapters)
- [Payment Dashboard (Member Portal)](#payment-dashboard-member-portal)
- [Payment Processing](#payment-processing)
- [Payment Plan Management](#payment-plan-management)
- [Dues Invoice Workflow](#dues-invoice-workflow)
- [Manual Invoice Generation](#manual-invoice-generation)
- [Schedule Maintenance](#schedule-maintenance)
- [Mollie Payment](#mollie-payment)
- [Mollie Connector (Balance/Settlements)](#mollie-connector-balancesettlements)
- [Mollie Balance Transaction Processing](#mollie-balance-transaction-processing)
- [Donation Portal](#donation-portal)
- [Periodic Donation Operations](#periodic-donation-operations)
- [Donor Management](#donor-management)
- [ANBI Operations](#anbi-operations)
- [Customer-Member Link](#customer-member-link)
- [SEPA Batch UI](#sepa-batch-ui)
- [SEPA Batch UI (Secure)](#sepa-batch-ui-secure)
- [SEPA Batch Workflow Controller](#sepa-batch-workflow-controller)
- [SEPA Batch Optimizer](#sepa-batch-optimizer)
- [SEPA Batch Scheduler](#sepa-batch-scheduler)
- [SEPA Batch Notifications](#sepa-batch-notifications)
- [SEPA Mandate Management](#sepa-mandate-management)
- [SEPA Health](#sepa-health)
- [SEPA Phantom Hash Admin](#sepa-phantom-hash-admin)
- [Document Portal](#document-portal)
- [Volunteer Application](#volunteer-application)
- [Volunteer Skills](#volunteer-skills)
- [Team Management](#team-management)
- [Team Admin Utilities](#team-admin-utilities)
- [Expense Claim Queries](#expense-claim-queries)
- [Email Template Manager](#email-template-manager)
- [Membership Email Templates](#membership-email-templates)
- [Overdue Application Notifications](#overdue-application-notifications)
- [Dashboard Charts](#dashboard-charts)
- [eBoekhouden Integration](#eboekhouden-integration)
- [Performance and Monitoring](#performance-and-monitoring)
- [Security Monitoring](#security-monitoring)
- [Workspace Health and Validation](#workspace-health-and-validation)
- [System Utilities](#system-utilities)

---

## Authentication

### API Key Authentication

```http
Authorization: token api_key:api_secret
Content-Type: application/json
```

Generate keys via **Users and Permissions > User > API Access > Generate Keys**.

### Session-Based Authentication

For browser-based applications, authenticate via `/api/method/login`.

### Guest Endpoints

Endpoints marked `allow_guest=True` do not require authentication. All other endpoints require a logged-in user.

---

## Membership Application (Public)

**Module:** `verenigingen.api.membership_application`

These endpoints power the public membership application form. Most are guest-accessible.

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `test_connection()` | Guest | -- | Health check for the application API |
| `test_all_endpoints()` | Guest | -- | Verifies all application endpoints are accessible |
| `get_application_form_data()` | Guest | -- | Returns form configuration (membership types, chapters, fields) |
| `validate_email(email)` | Guest | -- | Validates email format and checks for duplicates |
| `validate_postal_code(postal_code, country)` | Guest | -- | Validates Dutch postal code format |
| `validate_phone_number(phone, country)` | Guest | -- | Validates phone number format |
| `validate_birth_date(birth_date)` | Guest | -- | Validates birth date and age requirements |
| `validate_name(name, field_name)` | Guest | -- | Validates name field input |
| `check_application_eligibility_endpoint(data)` | Guest | -- | Checks whether applicant is eligible |
| `submit_application(**kwargs)` | Guest | -- | Submits a new membership application |
| `get_membership_fee_info_endpoint(membership_type)` | Guest | -- | Returns fee info for a membership type |
| `get_membership_type_details_endpoint(membership_type)` | Guest | -- | Returns details for a membership type |
| `suggest_membership_amounts_endpoint(membership_type_name)` | Guest | -- | Suggests fee amounts for a membership type |
| `validate_membership_amount_selection_endpoint(...)` | Guest | -- | Validates a selected fee amount |
| `validate_custom_amount_endpoint(membership_type, amount)` | Guest | -- | Validates a custom fee amount |
| `get_payment_methods_endpoint()` | Guest | -- | Returns available payment methods |
| `save_draft_application_endpoint(data)` | Guest | -- | Saves a draft application |
| `load_draft_application_endpoint(draft_id)` | Guest | -- | Loads a previously saved draft |
| `get_member_field_info_endpoint()` | Guest | -- | Returns Member DocType field metadata |
| `check_application_status_endpoint(application_id)` | Guest | -- | Checks status of a submitted application |
| `test_submit()` | Guest | -- | Test endpoint for application submission |
| `approve_membership_application(member_name, notes)` | Login | `@high_security_api()` | Approves a pending membership application |
| `reject_membership_application(member_name, reason)` | Login | `@high_security_api()` | Rejects a pending membership application |
| `debug_member_issue(member_name)` | Login | `@standard_api(UTILITY)` | Debug endpoint for member issues |
| `fix_specific_member(member_name, chapter_name, dry_run)` | Login | `@high_security_api(ADMIN)` | Fixes chapter assignment for a specific member |

**Convenience aliases** (Guest, delegate to `_endpoint` versions above):
`validate_custom_amount`, `save_draft_application`, `load_draft_application`, `get_membership_type_details`, `get_membership_fee_info`, `suggest_membership_amounts`, `get_payment_methods`, `check_application_status`, `submit_application_with_tracking`, `check_application_eligibility`

---

## Membership Application Review (Admin)

**Module:** `verenigingen.api.membership_application_review`

Admin-only endpoints for reviewing and processing membership applications.

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `approve_membership_application(member_name, membership_type, notes, ...)` | Login | `@high_security_api()` | Full approval workflow: creates membership, invoice, user account, sends notifications. Params include `activate_as_volunteer`, `chapter_name` |
| `reject_membership_application(member_name, reason, ...)` | Login | `@high_security_api()` | Rejects application with reason, optional `email_template` and `rejection_category` |
| `get_user_chapter_access(**kwargs)` | Login | `@standard_api` | Returns chapters accessible to the current user |
| `get_pending_applications(chapter, days_overdue)` | Login | `@standard_api()` | Lists pending applications, optionally filtered by chapter or overdue days |

---

## Background Approval

**Module:** `verenigingen.api.background_approval_api`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `approve_membership_application_background(member_name, ...)` | Login | -- | Enqueues approval as a background job for heavy operations |
| `get_approval_progress(member_name)` | Login | -- | Polls progress of a background approval job |

---

## Admin Membership Operations

**Module:** `verenigingen.api.admin_membership_operations`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `sync_member_statuses()` | Login | -- | Synchronizes member statuses with their membership records |
| `fix_backend_member_statuses()` | Login | -- | Fixes inconsistent backend member statuses |
| `migrate_active_application_status()` | Login | -- | Migrates legacy "Active Application" statuses |
| `get_application_stats()` | Login | `@standard_api()` | Returns application statistics by status |

---

## Member Management

**Module:** `verenigingen.api.member_management`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `assign_member_to_chapter(member_name, chapter_name)` | Login | `@high_security_api(MEMBER_DATA)` | Assigns a member to a chapter |
| `get_members_without_chapter(**kwargs)` | Login | `@standard_api(MEMBER_DATA)` | Lists members not assigned to any chapter |
| `bulk_assign_members_to_chapters(assignments)` | Login | -- | Bulk assigns members to chapters. `assignments`: list of `{member, chapter}` |
| `get_members_with_chapter_info(filters, limit)` | Login | -- | Returns members enriched with chapter info |
| `get_mt940_import_url()` | Login | `@standard_api(UTILITY)` | Returns the URL for MT940 bank import |
| `import_mt940_improved(file_content, bank_account, company)` | Login | -- | Imports MT940 bank statement file and creates bank transactions |
| `get_chapter_member_emails(chapter_name)` | Login | `@standard_api(MEMBER_DATA)` | Returns email addresses for all members in a chapter |

---

## Suspension Management

**Module:** `verenigingen.api.suspension_api`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `suspend_member(member_name, suspension_reason, ...)` | Login | -- | Suspends a member. Optional params: `suspension_end_date`, `notify_member`, `internal_notes` |
| `unsuspend_member(member_name, unsuspension_reason)` | Login | -- | Lifts a member's suspension |
| `get_suspension_status(member_name)` | Login | `@standard_api(MEMBER_DATA)` | Returns current suspension status for a member |
| `can_suspend_member(member_name)` | Login | -- | Checks whether current user can suspend the given member |
| `get_suspension_preview(member_name)` | Login | `@high_security_api(MEMBER_DATA)` | Returns preview of suspension impact |
| `bulk_suspend_members(members, suspension_reason, ...)` | Login | -- | Suspends multiple members at once |
| `get_suspension_list(limit, offset, status, chapter)` | Login | `@standard_api(MEMBER_DATA)` | Lists suspended members with filters |
| `get_suspension_status_safe(member_name)` | Guest | `@standard_api(MEMBER_DATA)` | Safe public suspension status check |
| `test_bank_details_debug()` | Login | -- | Debug endpoint for bank details |

---

## Termination

**Module:** `verenigingen.api.termination_api`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_termination_preview(member_name)` | Login | -- | Returns preview of termination impact |
| `execute_safe_termination(member_name, termination_type, termination_date, request_name)` | Login | -- | Executes a membership termination |

---

## Chapter Dashboard

**Module:** `verenigingen.api.chapter_dashboard_api`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_chapter_member_emails(chapter_name)` | Login | `@high_security_api(MEMBER_DATA)` | Returns member emails for a chapter |
| `quick_approve_member(member_name, chapter_name)` | Login | `@high_security_api(MEMBER_DATA)` | Quick-approves a member from the chapter dashboard |
| `reprocess_mt940_import(import_name)` | Login | -- | Reprocesses an MT940 import |
| `get_active_members_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of active members |
| `get_pending_applications_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of pending applications |
| `get_board_members_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of board members |
| `get_new_members_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of recently joined members |
| `get_filed_expense_claims_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of filed expense claims |
| `get_approved_expense_claims_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of approved expense claims |
| `get_volunteer_expenses_count(chapter)` | Login | `@standard_api(REPORTING)` | Returns count of volunteer expenses |

---

## Chapter Join

**Module:** `verenigingen.api.chapter_join`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_chapter_join_context(chapter_name)` | Login | -- | Returns context data for the chapter join page |
| `join_chapter(chapter_name, introduction)` | Login | -- | Submits a request to join a chapter |
| `get_user_chapter_requests()` | Login | -- | Returns the current user's chapter join requests |

---

## Chapter Validation

**Module:** `verenigingen.api.chapter_validation`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `validate_chapter_head(chapter_name, chapter_head)` | Login | -- | Validates a proposed chapter head |
| `validate_region(chapter_name, region)` | Login | -- | Validates a chapter's region assignment |
| `update_publication_status(chapter_name, published)` | Login | -- | Updates a chapter's publication status |
| `validate_board_member(chapter_name, volunteer, role)` | Login | -- | Validates a board member assignment |
| `validate_board_removal(chapter_name)` | Login | -- | Validates whether a board member can be removed |

---

## User Chapters

**Module:** `verenigingen.api.get_user_chapters`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_user_chapter_data()` | Guest | -- | Returns chapter data for the current user (used by HTML templates) |

---

## Payment Dashboard (Member Portal)

**Module:** `verenigingen.api.payment_dashboard`

Member-facing payment dashboard endpoints. All require login.

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_dashboard_data(member)` | Login | -- | Returns complete payment dashboard data for a member |
| `get_payment_method(member)` | Login | -- | Returns the member's current payment method |
| `get_payment_history(member, year, status)` | Login | -- | Returns payment history with optional year/status filters |
| `get_mandate_history(member)` | Login | -- | Returns SEPA mandate history |
| `get_payment_schedule(member)` | Login | -- | Returns upcoming payment schedule |
| `get_next_payment(member)` | Login | -- | Returns the next scheduled payment |
| `retry_failed_payment(invoice_id)` | Login | -- | Retries a failed payment |
| `download_payment_receipt(payment_id)` | Login | -- | Downloads a payment receipt |
| `export_payment_history_csv(year)` | Login | -- | Exports payment history as CSV |

---

## Payment Processing

**Module:** `verenigingen.api.payment_processing`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `send_overdue_payment_reminders(filters, reminder_type, ...)` | Login | -- | Sends overdue payment reminders. `methods=["POST"]`. Params: `custom_message`, `dry_run` |
| `export_overdue_payments(filters, format)` | Login | -- | Exports overdue payments as CSV or Excel |
| `execute_bulk_payment_action(action, member_names, ...)` | Login | -- | Executes bulk payment actions (e.g., suspend, create plan) |

---

## Payment Plan Management

**Module:** `vereinigingen.api.payment_plan_management`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `request_payment_plan(member, total_amount, installments, ...)` | Login | -- | Creates a payment plan request. Params: `frequency`, `reason` |
| `get_member_payment_plans(member)` | Login | -- | Returns payment plans for a member |
| `calculate_payment_plan_preview(total_amount, installments, frequency)` | Login | -- | Previews installment schedule without creating |

---

## Dues Invoice Workflow

**Module:** `verenigingen.api.dues_invoice_workflow`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `check_member_dues_status(member_name, ...)` | Login | `@standard_api(FINANCIAL)` | Checks dues status for a member. `methods=["GET", "POST"]` |
| `generate_missing_invoices(member_list, ...)` | Login | -- | Generates missing invoices for specified members |
| `validate_sepa_eligibility(invoice_list)` | Login | `@standard_api(FINANCIAL)` | Validates SEPA eligibility for invoices. `methods=["GET", "POST"]` |
| `prepare_sepa_batch(invoice_list, execution_date, ...)` | Login | -- | Prepares a SEPA batch from eligible invoices |
| `get_workflow_status()` | Login | `@standard_api(FINANCIAL)` | Returns current workflow status overview |
| `check_coverage_scheduling_mismatches()` | Login | `@standard_api(FINANCIAL)` | Detects mismatches between coverage and scheduling |

---

## Manual Invoice Generation

**Module:** `verenigingen.api.manual_invoice_generation`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `generate_manual_invoice(member_name)` | Login | -- | Generates a manual dues invoice for a member |
| `get_member_invoice_info(member_name)` | Login | -- | Returns invoice generation prerequisites for a member |

---

## Schedule Maintenance

**Module:** `verenigingen.api.schedule_maintenance`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_schedule_health_report()` | Login | -- | Returns health report on dues schedules |
| `cleanup_orphaned_schedules(issue_type, dry_run)` | Login | -- | Cleans up orphaned dues schedules |
| `prevent_orphaned_schedules()` | Login | -- | Runs preventive maintenance on schedules |

---

## Mollie Payment

**Module:** `vereinigingen.api.mollie_payment`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `create_payment(donation_data)` | Login | -- | Creates a Mollie payment for a donation |
| `get_payment_status(payment_id)` | Login | -- | Returns status of a Mollie payment |
| `get_subscription_details()` | Login | `@high_security_api(MEMBER_DATA)` | Returns subscription details for the current user |
| `cancel_specific_subscription(customer_id, subscription_id)` | Login | `@high_security_api(FINANCIAL)` | Cancels a specific Mollie subscription |
| `update_mollie_bank_account(iban, account_holder_name)` | Login | -- | Updates the Mollie bank account for SEPA |

---

## Mollie Balance Transaction Processing

**Module:** `verenigingen.verenigingen_payments.api.balance_transaction_processing`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `process_balance_transactions(balance_id, from_date, to_date, ...)` | Login | -- | Processes Mollie balance transactions into ERPNext |
| `process_historical_data(months_back, batch_size)` | Login | -- | Processes historical Mollie data |
| `get_primary_balance_info()` | Login | -- | Returns primary Mollie balance information |
| `check_transaction_status(transaction_id, include_mollie_data)` | Login | -- | Checks status of a specific transaction |
| `search_transactions_by_description(search_term, limit)` | Login | -- | Searches transactions by description text |
| `fetch_recent_transactions_for_search(limit)` | Login | -- | Fetches recent transactions for search UI |
| `get_processing_statistics(days)` | Login | -- | Returns transaction processing statistics |

---

## Donation Portal

**Module:** `verenigingen.templates.pages.donate`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `submit_donation(**kwargs)` | Guest | -- | Submits a donation via the public portal |
| `get_donation_status(donation_id)` | Login | -- | Returns status of a donation |
| `mark_donation_paid(donation_id, payment_reference)` | Login | -- | Marks a donation as paid |
| `test_donation_system()` | Login | `@development_only_api(UTILITY)` | Tests the donation flow (dev only) |
| `test_donation_submission()` | Login | `@development_only_api(UTILITY)` | Tests donation submission with sample data (dev only) |
| `force_doctype_sync()` | Login | -- | Forces DocType schema sync |
| `test_workspace_links()` | Login | -- | Tests workspace link integrity |
| `retry_payment(donation_id)` | Guest | -- | Retries a failed donation payment |
| `debug_frontend_routing()` | Login | -- | Debug endpoint for frontend routing |

---

## Periodic Donation Operations

**Module:** `vereinigingen.api.periodic_donation_operations`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `create_periodic_agreement(donor, amount, frequency, ...)` | Login | `@high_security_api(FINANCIAL)` | Creates a periodic donation agreement. Params: `payment_method`, `start_date`, `end_date` |
| `link_donation_to_agreement(donation, agreement)` | Login | -- | Links a one-time donation to a periodic agreement |
| `send_renewal_reminders(days_before_expiry)` | Login | -- | Sends renewal reminders for expiring agreements |
| `generate_tax_receipts(filters)` | Login | -- | Generates tax receipts for donors |
| `export_agreements(filters)` | Login | `@standard_api(REPORTING)` | Exports periodic donation agreements |

---

## Donor Management

### Donor Customer Management

**Module:** `vereinigingen.api.donor_customer_management`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_donor_customer_info(donor_name)` | Login | `@high_security_api(MEMBER_DATA)` | Returns customer info linked to a donor |
| `force_donor_customer_sync(donor_name)` | Login | -- | Forces sync between donor and ERPNext customer |
| `unlink_donor_customer(donor_name, remove_customer)` | Login | -- | Unlinks a donor from their ERPNext customer |
| `get_donor_sync_dashboard()` | Login | `@standard_api(REPORTING)` | Returns sync dashboard overview |

### Donor Auto-Creation Management

**Module:** `verenigingen.api.donor_auto_creation_management`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_auto_creation_dashboard()` | Login | `@standard_api(REPORTING)` | Returns auto-creation dashboard data |
| `update_auto_creation_settings(...)` | Login | -- | Updates donor auto-creation settings |
| `test_customer_eligibility(customer_name, amount)` | Login | `@high_security_api(MEMBER_DATA)` | Tests whether a customer is eligible for auto-creation |
| `get_donations_gl_accounts()` | Login | `@standard_api(REPORTING)` | Returns GL accounts used for donations |
| `get_customer_groups()` | Login | `@standard_api(REPORTING)` | Returns available customer groups |
| `simulate_auto_creation(customer_name, amount, donations_account)` | Login | `@high_security_api(MEMBER_DATA)` | Simulates auto-creation without persisting |
| `get_recent_error_logs()` | Login | `@standard_api(UTILITY)` | Returns recent error logs for auto-creation |
| `check_test_accounts()` | Login | -- | Checks test account configuration |
| `bulk_process_pending_payments(...)` | Login | -- | Processes pending payments in bulk |

---

## ANBI Operations

**Module:** `verenigingen.api.anbi_operations`

Dutch ANBI (public benefit organization) tax compliance endpoints.

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `update_donor_tax_identifiers(donor, bsn, ...)` | Login | -- | Updates BSN and tax identifiers for a donor |
| `get_donor_anbi_data(donor)` | Login | -- | Returns ANBI-related data for a donor |
| `generate_anbi_report(from_date, to_date, include_bsn)` | Login | -- | Generates ANBI compliance report |
| `update_anbi_consent(donor, consent, reason)` | Login | -- | Updates data processing consent for a donor |
| `validate_bsn(bsn)` | Login | `@standard_api(FINANCIAL)` | Validates a Dutch BSN (citizen service number) |
| `get_anbi_statistics(from_date, to_date)` | Login | `@standard_api(FINANCIAL)` | Returns aggregate ANBI statistics |
| `export_belastingdienst_report(filters)` | Login | -- | Exports report for Dutch tax authority |
| `send_consent_requests(filters)` | Login | `@standard_api(FINANCIAL)` | Sends ANBI consent requests to donors |

---

## Customer-Member Link

**Module:** `vereinigingen.api.customer_member_link`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_member_from_customer(customer)` | Login | `@standard_api(MEMBER_DATA)` | Returns the member linked to an ERPNext customer |

---

## SEPA Batch UI

**Module:** `verenigingen.verenigingen_payments.api.sepa_batch_ui`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `load_unpaid_invoices(date_range, membership_type, limit)` | Login | -- | Loads unpaid invoices for batch creation |
| `get_invoice_mandate_info(invoice)` | Login | -- | Returns SEPA mandate info for an invoice |
| `validate_invoice_mandate(invoice, member)` | Login | -- | Validates mandate eligibility for an invoice |
| `get_batch_analytics(batch_name)` | Login | -- | Returns analytics for a batch |
| `preview_sepa_xml(batch_name)` | Login | -- | Previews SEPA XML that would be generated |
| `create_sepa_batch_validated(**params)` | Login | -- | Creates a validated SEPA batch |
| `validate_batch_invoices(invoice_list)` | Login | -- | Validates a list of invoices for batching |
| `get_sepa_validation_constraints()` | Login | -- | Returns SEPA validation constraint rules |

---

## SEPA Batch UI (Secure)

**Module:** `verenigingen.verenigingen_payments.api.sepa_batch_ui_secure`

Security-hardened versions of the SEPA batch UI endpoints with additional permission checks.

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `load_unpaid_invoices_secure(date_range, membership_type, limit)` | Login | -- | Secure version of `load_unpaid_invoices` |
| `get_invoice_mandate_info_secure(invoice)` | Login | -- | Secure version of `get_invoice_mandate_info` |
| `validate_invoice_mandate_secure(invoice, member)` | Login | -- | Secure version of `validate_invoice_mandate` |
| `get_batch_analytics_secure(batch_name)` | Login | -- | Secure version of `get_batch_analytics` |
| `preview_sepa_xml_secure(batch_name)` | Login | -- | Secure version of `preview_sepa_xml` |
| `create_sepa_batch_validated_secure(**params)` | Login | -- | Secure version of `create_sepa_batch_validated` |
| `validate_batch_invoices_secure(invoice_list)` | Login | -- | Secure version of `validate_batch_invoices` |
| `get_sepa_validation_constraints_secure()` | Login | -- | Secure version of `get_sepa_validation_constraints` |
| `sepa_security_health_check()` | Login | -- | Returns SEPA security system health status |

---

## SEPA Batch Workflow Controller

**Module:** `vereinigingen.vereinigingen_payments.api.dd_batch_workflow_controller`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `validate_batch_for_approval(batch_name)` | Login | -- | Validates a batch is ready for approval |
| `approve_batch(batch_name, approval_notes)` | Login | -- | Approves a direct debit batch |
| `reject_batch(batch_name, rejection_reason)` | Login | -- | Rejects a direct debit batch |
| `get_batch_approval_history(batch_name)` | Login | -- | Returns approval history for a batch |
| `trigger_sepa_generation(batch_name)` | Login | -- | Triggers SEPA XML file generation for a batch |
| `get_batches_pending_approval()` | Login | -- | Lists all batches awaiting approval |

---

## SEPA Batch Optimizer

**Module:** `verenigingen.verenigingen_payments.api.dd_batch_optimizer`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `create_optimal_batches(target_date, config)` | Login | -- | Creates optimally sized batches for a target date |
| `validate_all_pending_invoices()` | Login | -- | Validates all pending invoices for batch eligibility |
| `get_batching_preview(config)` | Login | -- | Previews batch grouping without creating |
| `update_batch_optimization_config(new_config)` | Login | -- | Updates batch optimization configuration |

---

## SEPA Batch Scheduler

**Module:** `verenigingen.vereinigingen_payments.api.dd_batch_scheduler`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_batch_creation_schedule()` | Login | -- | Returns the configured batch creation schedule |

Note: `daily_batch_optimization()` is a scheduled task (not whitelisted), called by the Frappe scheduler.

---

## SEPA Batch Notifications

**Module:** `verenigingen.vereinigingen_payments.api.sepa_batch_notifications`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `test_notification_system()` | Login | -- | Tests the SEPA batch notification system |

---

## SEPA Mandate Management

**Module:** `verenigingen.verenigingen_payments.api.sepa_mandate_management`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `create_missing_sepa_mandates(dry_run)` | Login | -- | Creates SEPA mandates for members that lack them |
| `fix_specific_member_sepa_mandate(member_name)` | Login | -- | Fixes SEPA mandate for a specific member |
| `periodic_sepa_mandate_child_table_sync()` | Login | -- | Syncs SEPA mandate child table records |
| `detect_sepa_mandate_inconsistencies()` | Login | -- | Detects inconsistencies in SEPA mandate data |

---

## SEPA Health

**Module:** `verenigingen.api.sepa_health`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_sepa_health()` | Login | -- | Returns health status of SEPA subsystem (Redis, pending batches, unreconciled, recent uploads) |

---

## SEPA Phantom Hash Admin

**Module:** `vereinigingen.api.sepa_phantom_hash_admin`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `mark_phantom_hash_abandoned(log_name, reason)` | Login | -- | Marks a phantom hash log entry as abandoned |
| `retry_phantom_attachment(log_name)` | Login | -- | Retries attachment of a phantom hash |

---

## Direct Debit Batch API

**Module:** `vereinigingen.vereinigingen_payments.api.dd_batch_api`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_batch_list_with_security(filters)` | Login | -- | Lists DD batches with security filtering |
| `get_batch_details_with_security(batch_id)` | Login | -- | Returns batch details with security checks |
| `get_batch_conflicts(batch_id)` | Login | -- | Returns conflicts detected for a batch |
| `get_eligible_invoices(filters)` | Login | -- | Returns invoices eligible for direct debit |
| `apply_conflict_resolutions(batch_id, resolutions)` | Login | -- | Applies resolutions to batch conflicts |
| `escalate_conflicts(batch_id, conflicts)` | Login | -- | Escalates unresolvable conflicts |

---

## Document Portal

**Module:** `verenigingen.api.document_portal`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_upload_context()` | Login | -- | Returns context for the document upload UI |
| `upload_document(...)` | Login | -- | Uploads a document to an organization |
| `get_organization_documents(organization_type, organization_name)` | Login | -- | Lists documents for an organization |
| `can_upload_to_organization(organization_type, organization_name)` | Login | -- | Checks upload permission for an organization |
| `get_browsable_documents(...)` | Login | -- | Returns documents available for browsing |
| `delete_document(document_name)` | Login | -- | Deletes a document |

---

## Volunteer Application

**Module:** `verenigingen.api.volunteer_application`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `submit_volunteer_application(**data)` | Guest | -- | Submits a public volunteer application |

---

## Volunteer Skills

**Module:** `vereinigingen.api.volunteer_skills`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_skills_overview()` | Login | `@standard_api` | Returns aggregated skills overview |
| `search_volunteers_advanced(filters)` | Login | `@high_security_api` | Searches volunteers with advanced filters (accesses personal data) |
| `get_skill_recommendations(volunteer_name, limit)` | Login | `@standard_api` | Returns skill recommendations for a volunteer |
| `get_skill_gaps_analysis()` | Login | `@standard_api` | Returns organizational skill gaps analysis |
| `export_skills_data(format_type)` | Login | `@high_security_api` | Exports skills data (JSON format) |

---

## Team Management

**Module:** `vereinigingen.api.team_management`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_team_members(team)` | Login | -- | Returns members of a team |
| `sync_team_with_volunteers(team_name)` | Login | -- | Syncs team membership with volunteer records |
| `get_role_profile_preview(team_name)` | Login | -- | Previews role profile that would be applied |
| `bulk_apply_team_role_profiles(team_name)` | Login | -- | Applies role profiles to all team members |

---

## Team Admin Utilities

**Module:** `vereinigingen.api.team_admin_utilities`

Note: This module is listed in `whitelist_files.txt` but contains no `@frappe.whitelist()` endpoints itself (helper functions only).

---

## Expense Claim Queries

**Module:** `vereinigingen.api.expense_claim_queries`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_user_accessible_chapters_for_expenses(...)` | Login | `@standard_api(REPORTING)` | Returns chapters the user can file expenses for |
| `get_chapter_expense_approvers(...)` | Login | `@standard_api(REPORTING)` | Returns expense approvers for a chapter |
| `get_team_expense_approvers(...)` | Login | `@standard_api(REPORTING)` | Returns expense approvers for a team |

---

## Email Template Manager

**Module:** `verenigingen.api.email_template_manager`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `create_comprehensive_email_templates()` | Login | -- | Creates/updates all standard email templates |
| `test_email_template(template_name, test_context)` | Login | -- | Tests rendering of an email template |

Note: `send_template_email()` and `get_email_template()` are internal helper functions (not whitelisted).

---

## Membership Email Templates

**Module:** `verenigingen.api.membership_email_templates`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `create_default_email_templates()` | Login | -- | Creates default membership email templates |

---

## Overdue Application Notifications

**Module:** `verenigingen.api.overdue_application_notifications`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `send_overdue_notifications(**kwargs)` | Login | -- | Sends notifications for overdue applications |

---

## Dashboard Charts

**Module:** `verenigingen.api.dashboard_charts`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_member_age_distribution_chart()` | Login | `@standard_api(REPORTING)` | Returns member age distribution chart data |

---

## eBoekhouden Integration

### eBoekhouden Account Manager

**Module:** `vereinigingen.e_boekhouden.api.eboekhouden_account_manager`

Listed in `whitelist_files.txt`. See the [eBoekhouden API Integration Guide](api/EBOEKHOUDEN_API_GUIDE.md) for detailed documentation.

### eBoekhouden Migration

**Module:** `vereinigingen.e_boekhouden.api.eboekhouden_migration`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `mass_cancel_migrations(names)` | Login | -- | Cancels multiple migration records |

### eBoekhouden Migration Redesign

**Module:** `verenigingen.e_boekhouden.api.eboekhouden_migration_redesign`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_migration_statistics()` | Login | -- | Returns migration statistics |
| `validate_migration_readiness()` | Login | -- | Validates system readiness for migration |

### eBoekhouden Clean Reimport

**Module:** `verenigingen.e_boekhouden.api.eboekhouden_clean_reimport`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `preview_clean_import(from_date, to_date)` | Login | -- | Previews what a clean import would do |
| `execute_clean_import(confirm, from_date, to_date)` | Login | -- | Executes a clean reimport of transactions |
| `setup_enhanced_infrastructure()` | Login | -- | Sets up enhanced migration infrastructure |

### eBoekhouden Item Mapping Tool

**Module:** `vereinigingen.e_boekhouden.api.eboekhouden_item_mapping_tool`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_unmapped_accounts(company)` | Login | -- | Returns accounts without item mappings |
| `create_mapping(...)` | Login | -- | Creates a new item mapping |

### eBoekhouden Date Fields Setup

**Module:** `verenigingen.e_boekhouden.api.setup_eboekhouden_date_fields`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `setup_date_range_fields()` | Login | -- | Sets up custom date range fields |

---

## Performance and Monitoring

### Performance Measurement

**Module:** `verenigingen.api.performance_measurement`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `measure_payment_history_performance(member_count)` | Login | -- | Measures payment history query performance |
| `count_payment_mixin_complexity()` | Login | -- | Analyzes payment mixin code complexity |
| `measure_database_query_patterns()` | Login | `@standard_api(UTILITY)` | Measures database query performance patterns |
| `run_comprehensive_performance_analysis()` | Login | `@standard_api(UTILITY)` | Runs comprehensive performance analysis |

### Performance Measurement API

**Module:** `verenigingen.api.performance_measurement_api`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `measure_member_performance(member_name)` | Login | `@high_security_api(MEMBER_DATA)` | Measures performance for a specific member |
| `measure_payment_history_performance(member_name)` | Login | -- | Measures payment history performance |
| `measure_sepa_mandate_performance(member_name)` | Login | -- | Measures SEPA mandate performance |
| `generate_comprehensive_performance_report(sample_size)` | Login | `@standard_api(UTILITY)` | Generates full performance report |
| `collect_performance_baselines(sample_size)` | Login | `@standard_api(UTILITY)` | Collects performance baselines |
| `analyze_system_bottlenecks()` | Login | -- | Analyzes system bottlenecks |
| `get_performance_summary()` | Login | `@standard_api(UTILITY)` | Returns performance summary |
| `benchmark_current_performance()` | Login | -- | Benchmarks current system performance |
| `test_measurement_infrastructure()` | Login | -- | Tests measurement infrastructure |

### Infrastructure Validator

**Module:** `verenigingen.api.infrastructure_validator`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `validate_performance_infrastructure()` | Login | `@standard_api(UTILITY)` | Validates all performance infrastructure components |

### Performance Dashboard Activator

**Module:** `verenigingen.api.performance_dashboard_activator`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| Endpoint available | Login | `@standard_api(UTILITY)` | Activates performance dashboard |

### Performance Convenience

**Module:** `vereinigingen.api.performance_convenience`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 4 endpoints | Login | `@standard_api(UTILITY)` / `@high_security_api(MEMBER_DATA)` | Convenience wrappers for performance measurement |

### Performance API Validator

**Module:** `vereinigingen.api.performance_api_validator`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 1 endpoint | Login | -- | Validates performance API endpoints |

---

## Security Monitoring

### Unified Security Monitoring

**Module:** `verenigingen.api.unified_security_monitoring`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_unified_monitoring_overview()` | Login | `@standard_api(REPORTING)` | Returns overview of all monitoring systems |
| `get_integrated_security_metrics(hours_back)` | Login | `@high_security_api(ADMIN)` | Returns security metrics for the given time window |
| `get_monitoring_system_health()` | Login | `@standard_api(UTILITY)` | Returns health of monitoring components |
| `trigger_unified_security_test()` | Login | `@high_security_api(ADMIN)` | Triggers a unified security test |

### Security Monitoring Dashboard

**Module:** `vereinigingen.api.security_monitoring_dashboard`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `get_security_dashboard_data(hours_back)` | Login | `@high_security_api(ADMIN)` | Returns security dashboard data |
| `get_security_metrics_summary()` | Login | `@standard_api(REPORTING)` | Returns security metrics summary |

---

## Workspace Health and Validation

### Workspace Health

**Module:** `vereinigingen.api.workspace_health`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| `diagnose_and_fix(workspace_name, ...)` | Login | `@high_security_api(ADMIN)` | Diagnoses and fixes workspace issues |
| `health_check(workspace_name)` | Login | `@high_security_api(ADMIN)` | Runs health check on a workspace |
| `quick_fix(workspace_name)` | Login | `@high_security_api(ADMIN)` | Applies quick fixes to workspace |

### Workspace Content Validator

**Module:** `vereinigingen.api.workspace_content_validator`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 2 endpoints | Login | `@standard_api(UTILITY)` | Validates workspace content |

### Workspace Validator Enhanced

**Module:** `vereinigingen.api.workspace_validator_enhanced`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 1 endpoint | Login | -- | Enhanced workspace validation |

---

## System Utilities

### Check Account Types

**Module:** `vereinigingen.api.check_account_types`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 1 endpoint | Login | `@standard_api(REPORTING)` | Checks account type configuration |
| 1 endpoint | Login | `@high_security_api(ADMIN)` | Admin account type operations |

### Fix Stuck Dues Schedule

**Module:** `vereinigingen.api.fix_stuck_dues_schedule`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 4 endpoints | Login | -- | Diagnoses and fixes stuck dues schedules |

### Database Index Manager

**Module:** `vereinigingen.api.database_index_manager_phase5a`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 1 endpoint | Login | `@development_only_api(UTILITY)` | Manages database indexes (dev only) |

### Update Prepare System Button

**Module:** `verenigingen.api.update_prepare_system_button`

| Endpoint | Auth | Security Decorator | Description |
|---|---|---|---|
| 1 endpoint | Login | -- | Updates the "Prepare System" button configuration |

---

## Security Decorator Reference

The app uses the following security decorators (defined in `verenigingen.utils.security_decorators`):

| Decorator | Purpose |
|---|---|
| `@standard_api(operation_type=...)` | Standard authenticated endpoint with audit logging |
| `@high_security_api(operation_type=...)` | High-security endpoint with stricter checks and audit trail |
| `@critical_api(operation_type=...)` | Critical operations (financial, admin) with enhanced logging |
| `@sensitive_data_api(operation_type=...)` | Endpoints accessing sensitive personal data |
| `@development_only_api(operation_type=...)` | Only available in development mode |
| `@member_portal_api(operation_type=...)` | Member portal endpoints |

**Operation types:** `FINANCIAL`, `MEMBER_DATA`, `ADMIN`, `REPORTING`, `UTILITY`

---

## Notes

- All Frappe API endpoints use `POST` by default unless `methods=["GET", "POST"]` is specified.
- The `@frappe.whitelist(allow_guest=True)` flag makes an endpoint accessible without authentication.
- Endpoints without `allow_guest=True` require the user to be logged in; Frappe returns HTTP 403 otherwise.
- Response format follows Frappe conventions: the return value is wrapped in `{"message": <return_value>}`.
- Error responses use Frappe's standard exception format with `exc_type` and `message` fields.
- The `whitelist_files.txt` file contains the complete list of all whitelisted function paths across the entire app (including DocType controllers, utilities, and non-API modules).

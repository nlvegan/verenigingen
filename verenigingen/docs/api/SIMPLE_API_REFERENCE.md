# Verenigingen API Documentation

## Available Endpoints


### analyze_tegenrekening_usage.py

#### analyze_tegenrekening_patterns

**Endpoint:** `POST /api/method/verenigingen.api.analyze_tegenrekening_usage.analyze_tegenrekening_patterns`

**Description:** Analyze E-Boekhouden transaction data to discover tegenrekening usage patterns

#### get_chart_of_accounts_mapping

**Endpoint:** `POST /api/method/verenigingen.api.analyze_tegenrekening_usage.get_chart_of_accounts_mapping`

**Description:** Get mapping between ledger IDs and account codes from E-Boekhouden Chart of Accounts

#### generate_item_mapping_suggestions

**Endpoint:** `POST /api/method/verenigingen.api.analyze_tegenrekening_usage.generate_item_mapping_suggestions`

**Description:** Generate intelligent item mapping suggestions based on account usage and descriptions


### anbi_operations.py

#### update_donor_tax_identifiers

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.update_donor_tax_identifiers`

**Description:** Update donor tax identifiers with proper security checks

#### get_donor_anbi_data

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.get_donor_anbi_data`

**Description:** Get ANBI-related data for a donor (with decryption for authorized users)

#### generate_anbi_report

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.generate_anbi_report`

**Description:** Generate ANBI report for Belastingdienst reporting

#### update_anbi_consent

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.update_anbi_consent`

**Description:** Update ANBI consent for a donor

#### validate_bsn

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.validate_bsn`

**Description:** Validate a BSN number using the eleven-proof algorithm

#### get_anbi_statistics

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.get_anbi_statistics`

**Description:** Get ANBI donation statistics

#### export_belastingdienst_report

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.export_belastingdienst_report`

**Description:** Export ANBI report for Belastingdienst in CSV format

#### send_consent_requests

**Endpoint:** `POST /api/method/verenigingen.api.anbi_operations.send_consent_requests`

**Description:** Send ANBI consent request emails to donors without consent


### chapter_dashboard_api.py

#### get_chapter_member_emails

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_chapter_member_emails`

**Description:** Get email addresses of all active chapter members

#### quick_approve_member

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.quick_approve_member`

**Description:** Quick approve a member application from dashboard

#### test_mt940_naming_logic

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_mt940_naming_logic`

**Description:** Test the enhanced MT940 Import descriptive naming functionality

#### debug_mt940_import

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.debug_mt940_import`

**Description:** Debug an MT940 Import record to understand issues

#### debug_mt940_transaction_creation

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.debug_mt940_transaction_creation`

**Description:** Debug why MT940 transactions aren't being created

#### reprocess_mt940_import

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.reprocess_mt940_import`

**Description:** Reprocess an existing MT940 import

#### test_eboekhouden_framework

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_eboekhouden_framework`

**Description:** Test the e-Boekhouden migration framework

#### test_eboekhouden_api_mock

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_eboekhouden_api_mock`

**Description:** Test e-Boekhouden API utilities with mock data

#### test_eboekhouden_complete

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_eboekhouden_complete`

**Description:** Complete end-to-end test of e-Boekhouden framework

#### get_dashboard_notifications

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_dashboard_notifications`

**Description:** Get notifications for dashboard (upcoming deadlines, overdue items, etc.)

#### get_chapter_quick_stats

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_chapter_quick_stats`

**Description:** Get quick statistics for a specific chapter

#### reject_member_application

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.reject_member_application`

**Description:** Reject a member application from dashboard

#### send_chapter_announcement

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.send_chapter_announcement`

**Description:** Send announcement to chapter members

#### debug_dashboard_access

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.debug_dashboard_access`

**Description:** Debug dashboard access issues

#### test_url_access

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_url_access`

**Description:** Test URL routing for pages

#### get_active_members_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_active_members_count`

**Description:** Get count of active members for dashboard number card

#### get_pending_applications_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_pending_applications_count`

**Description:** Get count of pending applications for dashboard number card

#### get_board_members_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_board_members_count`

**Description:** Get count of active board members for dashboard number card

#### get_new_members_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_new_members_count`

**Description:** Get count of new members this month for dashboard number card

#### create_chapter_dashboard

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_chapter_dashboard`

**Description:** Create proper Frappe dashboard for chapter management

#### create_simple_dashboard

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_simple_dashboard`

**Description:** Create a simple test dashboard

#### add_existing_cards_to_dashboard

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.add_existing_cards_to_dashboard`

**Description:** Add existing working number cards to the dashboard

#### finalize_chapter_dashboard

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.finalize_chapter_dashboard`

**Description:** Complete the chapter dashboard setup

#### add_chapter_specific_chart

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.add_chapter_specific_chart`

**Description:** Add a chapter-specific chart to the dashboard

#### get_dashboard_completion_summary

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_dashboard_completion_summary`

**Description:** Get final summary of the completed dashboard

#### fix_dashboard_chart_issue

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.fix_dashboard_chart_issue`

**Description:** Fix the dashboard chart issue causing page navigation errors

#### fix_all_chart_issues

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.fix_all_chart_issues`

**Description:** Fix all chart navigation issues and add proper dashboard functionality

#### fix_chart_currency_display

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.fix_chart_currency_display`

**Description:** Fix the euro symbol appearing in chart tooltips

#### fix_chart_timeseries_display

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.fix_chart_timeseries_display`

**Description:** Fix charts showing flat lines by correcting timeseries configuration

#### recreate_working_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.recreate_working_charts`

**Description:** Completely recreate charts with minimal working configuration

#### use_existing_working_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.use_existing_working_charts`

**Description:** Replace problematic charts with existing working ones

#### create_cards_only_dashboard

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_cards_only_dashboard`

**Description:** Create dashboard with only Number Cards, no charts to avoid KeyError

#### create_proper_chapter_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_proper_chapter_charts`

**Description:** Create working chapter-specific charts using the proven pattern

#### create_minimal_working_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_minimal_working_charts`

**Description:** Create the most minimal possible working charts

#### debug_number_cards

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.debug_number_cards`

**Description:** Debug the number card methods

#### create_working_basic_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_working_basic_charts`

**Description:** Create charts using basic data that every system has

#### fix_dashboard_with_working_chart

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.fix_dashboard_with_working_chart`

**Description:** Fix dashboard with a chart that actually works

#### test_number_card_format

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_number_card_format`

**Description:** Test if Number Cards expect a specific return format

#### create_chapter_member_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.create_chapter_member_charts`

**Description:** Create working charts showing chapter and member data

#### test_dashboard_access

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_dashboard_access`

**Description:** Test dashboard access for current user

#### simple_test_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.simple_test_count`

**Description:** Simple test to see if we can get basic counts

#### clean_dashboard_completely

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.clean_dashboard_completely`

**Description:** Clean up dashboard and recreate with working components

#### fix_dashboard_simple

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.fix_dashboard_simple`

**Description:** Simple dashboard fix without deleting linked cards

#### restore_all_member_cards

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.restore_all_member_cards`

**Description:** Restore all the important member overview cards

#### add_working_chapter_charts

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.add_working_chapter_charts`

**Description:** Add working chapter-specific charts back to dashboard

#### get_filed_expense_claims_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_filed_expense_claims_count`

**Description:** Get count of filed expense claims for dashboard number card

#### get_approved_expense_claims_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_approved_expense_claims_count`

**Description:** Get count of approved expense claims for dashboard number card

#### get_volunteer_expenses_count

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.get_volunteer_expenses_count`

**Description:** Get count of volunteer expenses for dashboard number card

#### test_enhanced_mt940_features

**Endpoint:** `POST /api/method/verenigingen.api.chapter_dashboard_api.test_enhanced_mt940_features`

**Description:** Test the enhanced MT940 import features inspired by Banking app analysis.


### chapter_join.py

#### get_chapter_join_context

**Endpoint:** `POST /api/method/verenigingen.api.chapter_join.get_chapter_join_context`

**Description:** Get context for chapter join page

#### join_chapter

**Endpoint:** `POST /api/method/verenigingen.api.chapter_join.join_chapter`

**Description:** Handle chapter join request


### create_onboarding_steps.py

#### create_test_data_onboarding_step

**Endpoint:** `POST /api/method/verenigingen.api.create_onboarding_steps.create_test_data_onboarding_step`

**Description:** Create an onboarding step for generating test data

#### add_quick_start_card

**Endpoint:** `POST /api/method/verenigingen.api.create_onboarding_steps.add_quick_start_card`

**Description:** Add a quick start card to the Verenigingen workspace


### create_root_accounts.py

#### create_root_accounts

**Endpoint:** `POST /api/method/verenigingen.api.create_root_accounts.create_root_accounts`

**Description:** Create the basic root accounts for the company

#### create_standard_coa_groups

**Endpoint:** `POST /api/method/verenigingen.api.create_root_accounts.create_standard_coa_groups`

**Description:** Create standard account groups under root accounts


### create_smart_item_mapping.py

#### create_smart_item_mapping_system

**Endpoint:** `POST /api/method/verenigingen.api.create_smart_item_mapping.create_smart_item_mapping_system`

**Description:** Create a comprehensive item mapping system for E-Boekhouden accounts

#### create_items_from_mappings

**Endpoint:** `POST /api/method/verenigingen.api.create_smart_item_mapping.create_items_from_mappings`

**Description:** Create actual ERPNext items based on the smart mappings

#### create_tegenrekening_mapping_helper

**Endpoint:** `POST /api/method/verenigingen.api.create_smart_item_mapping.create_tegenrekening_mapping_helper`

**Description:** Create a helper function for mapping tegenrekening codes to items during migration


### dd_batch_optimizer.py

#### create_optimal_batches

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_optimizer.create_optimal_batches`

**Description:** Create optimally-sized SEPA Direct Debit batches automatically

#### get_batching_preview

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_optimizer.get_batching_preview`

**Description:** Preview what batches would be created without actually creating them

#### update_batch_optimization_config

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_optimizer.update_batch_optimization_config`

**Description:** Update batch optimization configuration


### dd_batch_scheduler.py

#### get_batch_creation_schedule

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_scheduler.get_batch_creation_schedule`

**Description:** Get the current schedule for automatic batch creation

#### toggle_auto_batch_creation

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_scheduler.toggle_auto_batch_creation`

**Description:** Enable or disable automatic batch creation

#### run_batch_creation_now

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_scheduler.run_batch_creation_now`

**Description:** Manually trigger batch creation (for testing/emergency use)

#### get_batch_optimization_stats

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_scheduler.get_batch_optimization_stats`

**Description:** Get statistics about batch optimization performance


### dd_batch_workflow_controller.py

#### validate_batch_for_approval

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_workflow_controller.validate_batch_for_approval`

**Description:** Validate batch and determine appropriate approval path

#### approve_batch

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_workflow_controller.approve_batch`

**Description:** Approve batch and move to next state

#### reject_batch

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_workflow_controller.reject_batch`

**Description:** Reject batch and provide reason

#### get_batch_approval_history

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_workflow_controller.get_batch_approval_history`

**Description:** Get approval history for a batch

#### trigger_sepa_generation

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_workflow_controller.trigger_sepa_generation`

**Description:** Trigger SEPA file generation for approved batch

#### get_batches_pending_approval

**Endpoint:** `POST /api/method/verenigingen.api.dd_batch_workflow_controller.get_batches_pending_approval`

**Description:** Get all batches pending approval for current user


### eboekhouden_account_manager.py

#### get_eboekhouden_accounts_summary

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_account_manager.get_eboekhouden_accounts_summary`

**Description:** Get a summary of all E-Boekhouden accounts in the system.

#### cleanup_eboekhouden_accounts_with_confirmation

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_account_manager.cleanup_eboekhouden_accounts_with_confirmation`

**Description:** Clean up E-Boekhouden accounts with confirmation step.

#### get_account_cleanup_status

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_account_manager.get_account_cleanup_status`

**Description:** Get the current status of E-Boekhouden accounts for a company.


### eboekhouden_item_mapping_tool.py

#### get_unmapped_accounts

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_item_mapping_tool.get_unmapped_accounts`

**Description:** Get E-boekhouden accounts that don't have item mappings yet

#### create_mapping

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_item_mapping_tool.create_mapping`

**Description:** Create a new item mapping


### eboekhouden_mapping_setup.py

#### setup_eboekhouden_mapping_fields

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_mapping_setup.setup_eboekhouden_mapping_fields`

**Description:** Add custom fields needed for E-Boekhouden mapping functionality

#### get_mapping_summary

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_mapping_setup.get_mapping_summary`

**Description:** Get a summary of current mapping configuration

#### test_mutation_mapping

**Endpoint:** `POST /api/method/verenigingen.api.eboekhouden_mapping_setup.test_mutation_mapping`

**Description:** Test how a specific mutation would be mapped


### email_template_manager.py

#### create_comprehensive_email_templates

**Endpoint:** `POST /api/method/verenigingen.api.email_template_manager.create_comprehensive_email_templates`

**Description:** Create all email templates used throughout the verenigingen app

#### test_email_template

**Endpoint:** `POST /api/method/verenigingen.api.email_template_manager.test_email_template`

**Description:** Test email template rendering with sample context

#### list_all_email_templates

**Endpoint:** `POST /api/method/verenigingen.api.email_template_manager.list_all_email_templates`

**Description:** List all email templates in the system


### fix_sales_invoice_receivables.py

#### fix_existing_sales_invoice_receivables

**Endpoint:** `POST /api/method/verenigingen.api.fix_sales_invoice_receivables.fix_existing_sales_invoice_receivables`

**Description:** Fix existing sales invoices that have wrong receivable account assignment

#### get_receivable_account_mapping

**Endpoint:** `POST /api/method/verenigingen.api.fix_sales_invoice_receivables.get_receivable_account_mapping`

**Description:** Get the correct receivable account for sales invoices

#### check_sales_invoice_receivables

**Endpoint:** `POST /api/method/verenigingen.api.fix_sales_invoice_receivables.check_sales_invoice_receivables`

**Description:** Check how many sales invoices are using the wrong receivable account


### fix_subscription.py

#### fix_subscription_dates

**Endpoint:** `POST /api/method/verenigingen.api.fix_subscription.fix_subscription_dates`

**Description:** Fix subscription date update issues

#### fix_all_subscription_dates

**Endpoint:** `POST /api/method/verenigingen.api.fix_subscription.fix_all_subscription_dates`

**Description:** Fix all subscriptions with date issues


### full_migration_summary.py

#### full_migration_summary

**Endpoint:** `POST /api/method/verenigingen.api.full_migration_summary.full_migration_summary`

**Description:** Summary of the completed full migration system

#### migration_deployment_checklist

**Endpoint:** `POST /api/method/verenigingen.api.full_migration_summary.migration_deployment_checklist`

**Description:** Pre-deployment checklist for production migration


### generate_test_applications.py

#### generate_test_members

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_applications.generate_test_members`

**Description:** Generate test membership applications from sample data

#### cleanup_test_applications

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_applications.cleanup_test_applications`

**Description:** Remove test applications (those with @email.nl addresses)

#### get_test_applications_status

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_applications.get_test_applications_status`

**Description:** Get status of test applications


### generate_test_members.py

#### generate_test_members

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_members.generate_test_members`

**Description:** Generate test members from sample data

#### cleanup_test_members

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_members.cleanup_test_members`

**Description:** Remove test members (those with @testvereniging.nl email addresses)

#### get_test_members_status

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_members.get_test_members_status`

**Description:** Get status of test members


### generate_test_membership_types.py

#### generate_test_membership_types

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_membership_types.generate_test_membership_types`

**Description:** Generate comprehensive test membership types for testing

#### cleanup_test_membership_types

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_membership_types.cleanup_test_membership_types`

**Description:** Remove all test membership types and their associated data

#### get_test_membership_types_status

**Endpoint:** `POST /api/method/verenigingen.api.generate_test_membership_types.get_test_membership_types_status`

**Description:** Get status of test membership types


### get_unreconciled_payments.py

#### get_unreconciled_payments

**Endpoint:** `POST /api/method/verenigingen.api.get_unreconciled_payments.get_unreconciled_payments`

**Description:** Get all unreconciled payment entries created during migration

#### reconcile_payment_with_invoice

**Endpoint:** `POST /api/method/verenigingen.api.get_unreconciled_payments.reconcile_payment_with_invoice`

**Description:** Reconcile an unreconciled payment with an invoice


### get_user_chapters.py

#### get_user_chapter_data

**Endpoint:** `POST /api/method/verenigingen.api.get_user_chapters.get_user_chapter_data`

**Description:** Get current user's chapter memberships


### member_management.py

#### assign_member_to_chapter

**Endpoint:** `POST /api/method/verenigingen.api.member_management.assign_member_to_chapter`

**Description:** Assign a member to a specific chapter using centralized manager

#### get_members_without_chapter

**Endpoint:** `POST /api/method/verenigingen.api.member_management.get_members_without_chapter`

**Description:** Get list of members without chapter assignment

#### bulk_assign_members_to_chapters

**Endpoint:** `POST /api/method/verenigingen.api.member_management.bulk_assign_members_to_chapters`

**Description:** Bulk assign multiple members to chapters

#### debug_address_members

**Endpoint:** `POST /api/method/verenigingen.api.member_management.debug_address_members`

**Description:** Debug method to test address members functionality

#### manually_populate_address_members

**Endpoint:** `POST /api/method/verenigingen.api.member_management.manually_populate_address_members`

**Description:** Manually populate the address members field to test UI

#### clear_address_members_field

**Endpoint:** `POST /api/method/verenigingen.api.member_management.clear_address_members_field`

**Description:** Clear the address members field to test automatic population

#### test_simple_field_population

**Endpoint:** `POST /api/method/verenigingen.api.member_management.test_simple_field_population`

**Description:** Test setting a simple value to verify field visibility

#### get_address_members_html_api

**Endpoint:** `POST /api/method/verenigingen.api.member_management.get_address_members_html_api`

**Description:** Dedicated API method to get address members HTML - completely separate from document methods

#### get_mt940_import_url

**Endpoint:** `POST /api/method/verenigingen.api.member_management.get_mt940_import_url`

**Description:** Get URL for MT940 import page

#### test_mt940_extraction

**Endpoint:** `POST /api/method/verenigingen.api.member_management.test_mt940_extraction`

**Description:** Test the extraction function on first transaction

#### debug_mt940_import_improved

**Endpoint:** `POST /api/method/verenigingen.api.member_management.debug_mt940_import_improved`

**Description:** Debug version of MT940 import with improved transaction parsing

#### debug_mt940_import

**Endpoint:** `POST /api/method/verenigingen.api.member_management.debug_mt940_import`

**Description:** Debug version of MT940 import to see what's happening

#### debug_bank_account_search

**Endpoint:** `POST /api/method/verenigingen.api.member_management.debug_bank_account_search`

**Description:** Debug bank account search by IBAN

#### debug_duplicate_detection

**Endpoint:** `POST /api/method/verenigingen.api.member_management.debug_duplicate_detection`

**Description:** Debug the duplicate detection logic specifically

#### debug_mt940_import_detailed

**Endpoint:** `POST /api/method/verenigingen.api.member_management.debug_mt940_import_detailed`

**Description:** Debug version that shows exactly what's happening during import

#### import_mt940_improved

**Endpoint:** `POST /api/method/verenigingen.api.member_management.import_mt940_improved`

**Description:** Improved MT940 import with better transaction handling


### membership_application.py

#### test_connection

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.test_connection`

**Description:** Simple test method to verify the API is working

#### test_all_endpoints

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.test_all_endpoints`

**Description:** Test that all critical endpoints are accessible

#### get_application_form_data

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_application_form_data`

**Description:** Get data needed for application form

#### validate_email

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_email`

**Description:** Validate email format and check if it already exists

#### validate_email_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_email_endpoint`

**Description:** Validate email format and check if it already exists (legacy endpoint)

#### validate_postal_code

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_postal_code`

**Description:** Validate postal code format and suggest chapters

#### validate_postal_code_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_postal_code_endpoint`

**Description:** Validate postal code format and suggest chapters (legacy endpoint)

#### validate_phone_number

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_phone_number`

**Description:** Validate phone number format

#### validate_phone_number_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_phone_number_endpoint`

**Description:** Validate phone number format (legacy endpoint)

#### validate_birth_date

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_birth_date`

**Description:** Validate birth date

#### validate_birth_date_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_birth_date_endpoint`

**Description:** Validate birth date (legacy endpoint)

#### validate_name

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_name`

**Description:** Validate name fields

#### validate_name_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_name_endpoint`

**Description:** Validate name fields (legacy endpoint)

#### check_application_eligibility_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.check_application_eligibility_endpoint`

**Description:** Check if applicant is eligible for membership

#### submit_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.submit_application`

**Description:** Process membership application submission - Main entry point

#### approve_membership_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.approve_membership_application`

**Description:** Approve a membership application

#### reject_membership_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.reject_membership_application`

**Description:** Reject a membership application

#### process_application_payment_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.process_application_payment_endpoint`

**Description:** Process payment for approved application

#### get_membership_fee_info_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_membership_fee_info_endpoint`

**Description:** Get membership fee information

#### get_membership_type_details_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_membership_type_details_endpoint`

**Description:** Get detailed membership type information

#### suggest_membership_amounts_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.suggest_membership_amounts_endpoint`

**Description:** Suggest membership amounts based on type

#### validate_membership_amount_selection_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_membership_amount_selection_endpoint`

**Description:** Validate membership amount selection

#### validate_custom_amount_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_custom_amount_endpoint`

**Description:** Validate custom membership amount

#### get_payment_methods_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_payment_methods_endpoint`

**Description:** Get available payment methods

#### save_draft_application_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.save_draft_application_endpoint`

**Description:** Save application as draft

#### load_draft_application_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.load_draft_application_endpoint`

**Description:** Load application draft

#### get_member_field_info_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_member_field_info_endpoint`

**Description:** Get information about member fields for form generation

#### check_application_status_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.check_application_status_endpoint`

**Description:** Check the status of an application by ID

#### test_submit

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.test_submit`

**Description:** Simple test submission function

#### debug_member_issue

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.debug_member_issue`

**Description:** Debug the chapter membership issue for a specific member

#### fix_specific_member

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.fix_specific_member`

**Description:** Fix chapter membership for a specific member

#### test_chapter_membership_workflow

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.test_chapter_membership_workflow`

**Description:** Test the complete chapter membership workflow

#### test_status_field_integration

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.test_status_field_integration`

**Description:** Test status field integration without complex chapter operations

#### validate_custom_amount

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_custom_amount`

**Description:** Legacy endpoint - validate custom membership amount

#### save_draft_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.save_draft_application`

**Description:** Legacy endpoint - save application as draft

#### load_draft_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.load_draft_application`

**Description:** Legacy endpoint - load application draft

#### get_membership_type_details

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_membership_type_details`

**Description:** Legacy endpoint - get detailed membership type information

#### get_membership_fee_info

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_membership_fee_info`

**Description:** Legacy endpoint - get membership fee information

#### suggest_membership_amounts

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.suggest_membership_amounts`

**Description:** Legacy endpoint - suggest membership amounts based on type

#### get_payment_methods

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_payment_methods`

**Description:** Legacy endpoint - get available payment methods

#### check_application_status

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.check_application_status`

**Description:** Legacy endpoint - check the status of an application by ID

#### submit_application_with_tracking

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.submit_application_with_tracking`

**Description:** Legacy endpoint - same as submit_application

#### check_application_eligibility

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.check_application_eligibility`

**Description:** Legacy endpoint - check if applicant is eligible for membership

#### get_application_form_data_legacy

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.get_application_form_data_legacy`

**Description:** Legacy endpoint - use get_application_form_data instead

#### validate_address_endpoint

**Endpoint:** `POST /api/method/verenigingen.api.membership_application.validate_address_endpoint`

**Description:** Validate address data


### membership_application_review.py

#### approve_membership_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.approve_membership_application`

**Description:** Approve a membership application and create invoice

#### reject_membership_application

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.reject_membership_application`

**Description:** Reject a membership application with enhanced template support

#### get_user_chapter_access

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.get_user_chapter_access`

**Description:** Get user's chapter access for filtering applications

#### get_pending_applications

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.get_pending_applications`

**Description:** Get list of pending membership applications

#### get_pending_reviews_for_member

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.get_pending_reviews_for_member`

**Description:** Get pending membership application reviews for a specific member

#### debug_and_fix_member_approval

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.debug_and_fix_member_approval`

**Description:** Debug and fix member approval issues

#### test_member_approval

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.test_member_approval`

**Description:** Test member approval without actually approving

#### sync_member_statuses

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.sync_member_statuses`

**Description:** Sync member application and status fields to ensure consistency

#### fix_backend_member_statuses

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.fix_backend_member_statuses`

**Description:** One-time fix for backend-created members showing as Pending

#### get_application_stats

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.get_application_stats`

**Description:** Get statistics for membership applications

#### migrate_active_application_status

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.migrate_active_application_status`

**Description:** Migrate members with 'Active' application_status to 'Approved'

#### check_member_iban_data

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.check_member_iban_data`

**Description:** Check the current IBAN data for a member

#### debug_custom_amount_flow

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.debug_custom_amount_flow`

**Description:** Debug the custom amount flow for a specific member

#### debug_membership_subscription

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.debug_membership_subscription`

**Description:** Debug a specific membership and its subscription

#### debug_subscription_plan

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.debug_subscription_plan`

**Description:** Debug a subscription plan

#### test_fix_custom_amount_subscription

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.test_fix_custom_amount_subscription`

**Description:** Test fix for custom amount subscription issue

#### check_subscription_invoice

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.check_subscription_invoice`

**Description:** Check subscription invoice details

#### send_overdue_notifications

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.send_overdue_notifications`

**Description:** Send notifications for overdue applications (> 2 weeks)

#### create_default_email_templates

**Endpoint:** `POST /api/method/verenigingen.api.membership_application_review.create_default_email_templates`

**Description:** Create default email templates for membership application management


### onboarding_info.py

#### get_onboarding_info

**Endpoint:** `POST /api/method/verenigingen.api.onboarding_info.get_onboarding_info`

**Description:** Get detailed onboarding information

#### get_direct_onboarding_link

**Endpoint:** `POST /api/method/verenigingen.api.onboarding_info.get_direct_onboarding_link`

**Description:** Get the direct link to access Verenigingen onboarding


### payment_dashboard.py

#### get_dashboard_data

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.get_dashboard_data`

**Description:** Get payment dashboard summary data

#### get_payment_method

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.get_payment_method`

**Description:** Get active payment method details

#### get_payment_history

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.get_payment_history`

**Description:** Get payment history for member

#### get_mandate_history

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.get_mandate_history`

**Description:** Get SEPA mandate history

#### get_payment_schedule

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.get_payment_schedule`

**Description:** Get upcoming payment schedule

#### get_next_payment

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.get_next_payment`

**Description:** Get next scheduled payment

#### retry_failed_payment

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.retry_failed_payment`

**Description:** Manually trigger payment retry

#### download_payment_receipt

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.download_payment_receipt`

**Description:** Generate payment receipt PDF

#### export_payment_history_csv

**Endpoint:** `POST /api/method/verenigingen.api.payment_dashboard.export_payment_history_csv`

**Description:** Export payment history as CSV


### payment_processing.py

#### send_overdue_payment_reminders

**Endpoint:** `POST /api/method/verenigingen.api.payment_processing.send_overdue_payment_reminders`

**Description:** Send payment reminders to members with overdue payments

#### export_overdue_payments

**Endpoint:** `POST /api/method/verenigingen.api.payment_processing.export_overdue_payments`

**Description:** Export overdue payments data for external processing

#### execute_bulk_payment_action

**Endpoint:** `POST /api/method/verenigingen.api.payment_processing.execute_bulk_payment_action`

**Description:** Execute bulk actions on overdue payments


### periodic_donation_operations.py

#### create_periodic_agreement

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.create_periodic_agreement`

**Description:** Create a new periodic donation agreement

#### get_donor_agreements

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.get_donor_agreements`

**Description:** Get all periodic donation agreements for a donor

#### link_donation_to_agreement

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.link_donation_to_agreement`

**Description:** Link an existing donation to a periodic agreement

#### generate_periodic_donation_report

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.generate_periodic_donation_report`

**Description:** Generate report of all periodic donation agreements

#### check_expiring_agreements

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.check_expiring_agreements`

**Description:** Check for agreements expiring within specified days

#### create_donation_from_agreement

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.create_donation_from_agreement`

**Description:** Create a donation based on periodic agreement settings

#### get_agreement_statistics

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.get_agreement_statistics`

**Description:** Get overall statistics for periodic donation agreements

#### send_renewal_reminders

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.send_renewal_reminders`

**Description:** Send renewal reminders for expiring agreements

#### generate_tax_receipts

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.generate_tax_receipts`

**Description:** Generate tax receipts for periodic donations

#### export_agreements

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.export_agreements`

**Description:** Export periodic agreements to CSV

#### test_periodic_donation_system

**Endpoint:** `POST /api/method/verenigingen.api.periodic_donation_operations.test_periodic_donation_system`

**Description:** Test that the periodic donation agreement system is working


### populate_soap_credentials.py

#### populate_soap_credentials

**Endpoint:** `POST /api/method/verenigingen.api.populate_soap_credentials.populate_soap_credentials`

**Description:** Populate SOAP credentials from hardcoded values for existing installation

#### get_soap_credentials_status

**Endpoint:** `POST /api/method/verenigingen.api.populate_soap_credentials.get_soap_credentials_status`

**Description:** Check if SOAP credentials are configured


### save_soap_credentials.py

#### save_soap_credentials

**Endpoint:** `POST /api/method/verenigingen.api.save_soap_credentials.save_soap_credentials`

**Description:** Save SOAP credentials to E-Boekhouden Settings


### sepa_batch_ui.py

#### load_unpaid_invoices

**Endpoint:** `POST /api/method/verenigingen.api.sepa_batch_ui.load_unpaid_invoices`

**Description:** Load unpaid invoices for batch processing

#### get_invoice_mandate_info

**Endpoint:** `POST /api/method/verenigingen.api.sepa_batch_ui.get_invoice_mandate_info`

**Description:** Get mandate information for an invoice

#### validate_invoice_mandate

**Endpoint:** `POST /api/method/verenigingen.api.sepa_batch_ui.validate_invoice_mandate`

**Description:** Validate mandate for a specific invoice

#### get_batch_analytics

**Endpoint:** `POST /api/method/verenigingen.api.sepa_batch_ui.get_batch_analytics`

**Description:** Get detailed analytics for a batch

#### preview_sepa_xml

**Endpoint:** `POST /api/method/verenigingen.api.sepa_batch_ui.preview_sepa_xml`

**Description:** Preview SEPA XML content before generation


### sepa_integration_setup.py

#### complete_sepa_integration_setup

**Endpoint:** `POST /api/method/verenigingen.api.sepa_integration_setup.complete_sepa_integration_setup`

**Description:** Complete setup of SEPA integration including test data

#### test_sepa_workflow_step_by_step

**Endpoint:** `POST /api/method/verenigingen.api.sepa_integration_setup.test_sepa_workflow_step_by_step`

**Description:** Test SEPA workflow step by step with detailed logging

#### quick_sepa_demo

**Endpoint:** `POST /api/method/verenigingen.api.sepa_integration_setup.quick_sepa_demo`

**Description:** Quick demo of SEPA reconciliation capabilities


### sepa_mandate_fix.py

#### create_missing_sepa_mandates

**Endpoint:** `POST /api/method/verenigingen.api.sepa_mandate_fix.create_missing_sepa_mandates`

**Description:** Create SEPA mandates for members with SEPA Direct Debit payment method but no active mandate.

#### fix_specific_member_sepa_mandate

**Endpoint:** `POST /api/method/verenigingen.api.sepa_mandate_fix.fix_specific_member_sepa_mandate`

**Description:** Create SEPA mandate for a specific member


### sepa_reconciliation.py

#### identify_sepa_transactions

**Endpoint:** `POST /api/method/verenigingen.api.sepa_reconciliation.identify_sepa_transactions`

**Description:** Find bank transactions that might be from SEPA batches

#### process_sepa_transaction_conservative

**Endpoint:** `POST /api/method/verenigingen.api.sepa_reconciliation.process_sepa_transaction_conservative`

**Description:** Process SEPA transaction with conservative approach and duplicate prevention

#### process_sepa_return_file

**Endpoint:** `POST /api/method/verenigingen.api.sepa_reconciliation.process_sepa_return_file`

**Description:** Process SEPA return file with failure details

#### correlate_return_transactions

**Endpoint:** `POST /api/method/verenigingen.api.sepa_reconciliation.correlate_return_transactions`

**Description:** Look for return transactions and correlate with SEPA batches

#### get_sepa_reconciliation_dashboard

**Endpoint:** `POST /api/method/verenigingen.api.sepa_reconciliation.get_sepa_reconciliation_dashboard`

**Description:** Get dashboard data for SEPA reconciliation status

#### manual_sepa_reconciliation

**Endpoint:** `POST /api/method/verenigingen.api.sepa_reconciliation.manual_sepa_reconciliation`

**Description:** Manually reconcile specific items from a SEPA batch


### setup_eboekhouden_date_fields.py

#### setup_date_range_fields

**Endpoint:** `POST /api/method/verenigingen.api.setup_eboekhouden_date_fields.setup_date_range_fields`

**Description:** Add custom fields to E-Boekhouden Settings to store date range


### smart_mapping_deployment_guide.py

#### smart_mapping_deployment_summary

**Endpoint:** `POST /api/method/verenigingen.api.smart_mapping_deployment_guide.smart_mapping_deployment_summary`

**Description:** Final summary of smart tegenrekening mapping deployment

#### test_migration_readiness

**Endpoint:** `POST /api/method/verenigingen.api.smart_mapping_deployment_guide.test_migration_readiness`

**Description:** Test if the system is ready for migration with smart mapping


### suspension_api.py

#### suspend_member

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.suspend_member`

**Description:** Suspend a member with specified options

#### unsuspend_member

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.unsuspend_member`

**Description:** Unsuspend a member

#### get_suspension_status

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.get_suspension_status`

**Description:** Get suspension status for a member

#### can_suspend_member

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.can_suspend_member`

**Description:** Check if current user can suspend/unsuspend a member

#### get_suspension_preview

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.get_suspension_preview`

**Description:** Preview what would be affected by suspension

#### bulk_suspend_members

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.bulk_suspend_members`

**Description:** Suspend multiple members at once

#### test_bank_details_debug

**Endpoint:** `POST /api/method/verenigingen.api.suspension_api.test_bank_details_debug`

**Description:** Test function to debug bank details issue


### termination_api.py

#### get_termination_preview

**Endpoint:** `POST /api/method/verenigingen.api.termination_api.get_termination_preview`

**Description:** Public API to get termination impact preview

#### get_impact_summary

**Endpoint:** `POST /api/method/verenigingen.api.termination_api.get_impact_summary`

**Description:** Public API to get termination impact summary

#### execute_safe_termination

**Endpoint:** `POST /api/method/verenigingen.api.termination_api.execute_safe_termination`

**Description:** Execute termination using safe integration methods


### update_prepare_system_button.py

#### should_remove_prepare_system_button

**Endpoint:** `POST /api/method/verenigingen.api.update_prepare_system_button.should_remove_prepare_system_button`

**Description:** Analysis of whether the 'Prepare System' button should be removed

#### analyze_eboekhouden_data

**Endpoint:** `POST /api/method/verenigingen.api.update_prepare_system_button.analyze_eboekhouden_data`

**Description:** Analyze E-Boekhouden data without making any system changes

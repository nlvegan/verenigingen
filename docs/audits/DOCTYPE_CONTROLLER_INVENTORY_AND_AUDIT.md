# DocType Controller Inventory and Refactoring Audit

**Generated**: 2026-01-02
**Total Files**: 149 Python files in doctype directories
**Total LOC**: 57,323 lines of code

## Executive Summary

This audit identifies DocType controllers containing business logic that should be extracted to services, utility functions, or other centralized repositories. The goal is to maintain thin controllers that primarily handle document lifecycle events while delegating business logic to testable, reusable services.

### Key Findings

| Category | File Count | Total LOC | Status |
|----------|-----------|-----------|--------|
| Critical (>1000 LOC) | 15 | ~22,000 | High priority refactoring |
| High Priority (600-1000 LOC) | 20 | ~14,000 | Should refactor |
| Medium Priority (300-600 LOC) | 25 | ~10,000 | Consider refactoring |
| Acceptable (<300 LOC) | 89 | ~11,000 | Generally fine |

### Architecture Patterns Observed

**Well-Factored Controllers** (follow best practices):
- `sepa_mandate.py` (205 LOC) - Clean delegation to 4 services
- `chapter.py` (1162 LOC) - Uses manager pattern effectively
- `team.py` (638 LOC) - Uses TeamService and TeamValidationService
- `direct_debit_batch.py` (844 LOC) - Uses batch processing services

**Controllers Needing Refactoring** (business logic embedded):
- `e_boekhouden_migration.py` (3239 LOC) - Massive migration logic ← **Primary target**
- `membership_dues_schedule.py` (2917 LOC) - Billing calculations inline
- `mijnrood_csv_import.py` (2407 LOC) - CSV parsing logic embedded
- ~~`donor.py` (935 LOC)~~ - Keep as-is (see Expert Review below)

---

## Expert Architecture Review

This audit was reviewed by architecture experts. Key feedback incorporated:

### Martin Fowler (Enterprise Architecture Perspective)

**Prioritization Issues Identified:**
- Import tools (MijnRood, VIP) may be over-prioritized - rarely used after initial migration
- Chapter managers should come earlier - they're in core business flow
- Donor/donation extraction is largely done already (services exist)

**Anti-Patterns Missed:**
1. **Mixed delegation depths** - Some methods delegate, others don't (inconsistent archaeology)
2. **Manager vs Service tension** - Two patterns without clear guidance
3. **Settings controllers as services** - `mollie_settings.py` has API integration logic (should be thin)
4. **Backup file proliferation** - Suggests process/confidence problems

**250 LOC Target Unrealistic:**
> "Frappe controllers have unavoidable overhead from lifecycle hooks, child tables, permissions, `@frappe.whitelist()` methods. Revised targets: 350-500 LOC for core business DocTypes."

### Rich Hickey (Simplicity Perspective)

**Fundamental Challenge:**
> "The audit conflates 'large files are bad' with 'services are good' - both are sometimes true, often false."

**Key Criticisms:**
1. **Over-engineering risk** - Already have 87 services (39,284 LOC); proposal would roughly double this
2. **BSN eleven-proof is 17 lines** - Creating a service adds indirection without benefit
3. **Complecting through indirection** - "To understand what happens when a donor is saved, you read 4 files instead of 1"
4. **6-8 week estimate reveals scope creep** - What's the return on reorganizing working code?

**Core Insight:**
> "935 LOC for a coherent DocType controller is fine. 200 LOC split across 5 files is worse if it fragments understanding."

### Reconciled Recommendations

| Action | Verdict |
|--------|---------|
| Delete backup files | **Do immediately** (1 hour) |
| Extract e_boekhouden_migration | **Do it** (genuinely problematic) |
| Extract import services | **Measure usage first** |
| Extract BSN/RSIN validation | **Don't do** (17 LOC, local use) |
| Target 250 LOC | **Drop this target** |
| 6-8 week refactoring | **Surgical fixes only** (1-2 weeks) |

---

## Complete Inventory

### CRITICAL PRIORITY (>1000 LOC) - 15 files

| File | LOC | Issues | Recommended Actions |
|------|-----|--------|---------------------|
| `e_boekhouden_migration.py` | 3239 | Migration logic, API calls, cleanup logic embedded | Extract to `EBoekhoudenMigrationService`, `MigrationCleanupService` |
| `membership_dues_schedule.py` | 2917 | Billing calculations, progressive dues logic, template sync | Partially uses services; extract remaining to `ProgressiveDuesCalculator` |
| `mijnrood_csv_import.py` | 2407 | CSV parsing, data transformation, validation logic | Extract to `MijnRoodImportService`, `CSVValidationService` |
| `member.py` | 1963 | Well-factored with mixins; address normalization inline | Generally good; minor cleanup of inline utilities |
| `contribution_amendment_request.py` | 1611 | Fee validation, minimum calculations, approval logic | Extract to `ContributionAmendmentService`, `FeeValidationService` |
| `chapter_controller_backup.py` | 1360 | Backup file - DELETE | Remove from codebase |
| `chapter/managers/member_manager.py` | 1323 | Part of manager pattern - OK but large | Consider splitting into smaller managers |
| `membership.py` | 1305 | Dues schedule creation, member updates inline | Extract schedule creation to `DuesScheduleCreationService` (partially done) |
| `chapter/managers/board_manager.py` | 1240 | Part of manager pattern - OK but large | Consider splitting |
| `direct_debit_batch/sepa_processor.py` | 1203 | SEPA processing logic | Already modular; consider merging with sepa_xml_service |
| `chapter.py` | 1162 | Uses manager pattern - GOOD | Model example |
| `volunteer.py` | 1142 | Age validation, assignment aggregation inline | Extract to `VolunteerValidationService`, `AssignmentAggregationService` |
| `vip_import.py` | 1132 | Import logic, data transformation embedded | Extract to `VIPImportService` |
| `brand_settings.py` | 1083 | CSS generation, branding logic embedded | Extract to `BrandingService`, `CSSGenerationService` |
| `member_utils.py` | 1022 | Utility functions - should be in services | Move to `services/member/utils/` |

### HIGH PRIORITY (600-1000 LOC) - 20 files

| File | LOC | Issues | Recommended Actions |
|------|-----|--------|---------------------|
| `member/mixins/payment_mixin.py` | 997 | Payment processing logic | Extract remaining logic to `PaymentProcessingService` |
| `donation_original.py` | 971 | Backup file - DELETE | Remove from codebase |
| `team_original_backup.py` | 966 | Backup file - DELETE | Remove from codebase |
| `donor.py` | 935 | BSN/RSIN eleven-proof validation (17 LOC), encryption | **KEEP LOCAL** - Domain-specific, single-use logic; extraction adds indirection without benefit |
| `mollie_settings.py` | 863 | Mollie API integration inline | Extract to `MollieAPIService`, `MollieWebhookService` |
| `direct_debit_batch.py` | 844 | Uses services well | GOOD - model example |
| `member/scheduler.py` | 794 | Scheduled task logic | Extract to `MemberSchedulerService` |
| `e_boekhouden_settings.py` | 791 | API configuration, validation | Extract validation to `EBoekhoudenConfigService` |
| `membership_termination_analytics.py` | 739 | Analytics calculations | Extract to `TerminationAnalyticsService` |
| `chapter/managers/communication_manager.py` | 726 | Part of manager pattern - OK | Model example |
| `ponto_settings.py` | 699 | Ponto API configuration | Extract to `PontoConfigurationService` |
| `membership_termination_request.py` | 673 | Termination workflow logic | Partially uses services; continue extraction |
| `e_boekhouden_account_mapping/api.py` | 666 | API endpoints - should use @whitelisted methods | Refactor to use API security framework |
| `member/mixins/payment_mixin_optimized.py` | 653 | Duplicate of payment_mixin - DELETE or merge | Consolidate with payment_mixin.py |
| `account_creation_request.py` | 649 | Account creation logic | Uses AccountCreationManager - GOOD |
| `periodic_donation_agreement.py` | 643 | Donation agreement logic | Extract to `PeriodicDonationService` |
| `team.py` | 638 | Uses TeamService - GOOD | Model example |
| `donation.py` | 611 | ANBI validation, donor creation | **ALREADY DONE** - `ANBIValidationService` exists; integrate if not already using |
| `member/mixins/sepa_mixin.py` | 605 | SEPA mandate operations | Extract to dedicated SEPA service |
| `chapter/managers/volunteer_integration_manager.py` | 599 | Part of manager pattern - OK | Model example |

### MEDIUM PRIORITY (300-600 LOC) - 25 files

| File | LOC | Issues | Recommended Actions |
|------|-----|--------|---------------------|
| `mt940_import.py` | 556 | MT940 parsing logic | Extract to `MT940ParserService` |
| `event_contact_campaign.py` | 556 | Campaign logic | Extract to `CampaignService` |
| `ponto_payment_link.py` | 533 | Payment link logic | Extract to `PontoPaymentService` |
| `email_configuration.py` | 521 | Email setup logic | Extract to `EmailConfigurationService` |
| `performance_optimization_setup.py` | 509 | Setup logic | Extract to `OptimizationSetupService` |
| `payment_plan.py` | 484 | Payment plan logic | Extract to `PaymentPlanService` |
| `contact_request_automation.py` | 461 | Automation logic | Extract to `ContactRequestAutomationService` |
| `critical_operation_rule.py` | 461 | Rule validation | Extract to `CriticalOperationRuleService` |
| `expulsion_report_entry.py` | 460 | Report generation | Extract to `ExpulsionReportService` |
| `e_boekhouden_dashboard.py` | 459 | Dashboard logic | Extract to `EBoekhoudenDashboardService` |
| `analytics_alert_rule.py` | 458 | Alert rule logic | Extract to `AnalyticsAlertService` |
| `dues_schedule_manager.py` | 450 | Should be a service | Move to `services/billing/` |
| `chapter_join_request.py` | 445 | Join request logic | Extract to `ChapterJoinService` |
| `sepa_audit_log.py` | 431 | Audit log operations | Extract to `SEPAAuditService` |
| `donation_campaign.py` | 408 | Campaign logic | Extract to `DonationCampaignService` |
| `bulk_operation_tracker.py` | 402 | Tracking logic | Extract to `BulkOperationService` |
| `chapter/validators/chapter_validator.py` | 380 | Validation logic - OK as validator | GOOD pattern |
| `membership_analytics_snapshot.py` | 377 | Snapshot logic | Extract to `MembershipSnapshotService` |
| `membership_type.py` | 357 | Type configuration | Generally OK |
| `member_contact_request.py` | 357 | Contact request logic | Uses automation service - partially OK |
| `membership/scheduler.py` | 345 | Scheduled tasks | Extract to `MembershipSchedulerService` |
| `chapter/validators/postal_code_validator.py` | 343 | Validation - OK as validator | GOOD pattern |
| `member_id_manager.py` | 342 | ID management | Move to `services/member/identification/` |
| `chapter/managers/base_manager.py` | 328 | Base class - OK | GOOD pattern |
| `ponto_payment_request.py` | 322 | Payment request logic | Extract to `PontoPaymentRequestService` |

### ACCEPTABLE (<300 LOC) - 89 files

These files are generally well-sized for controllers. Only those with specific issues are listed:

| File | LOC | Notes |
|------|-----|-------|
| `verenigingen_settings.py` | 256 | Configuration - OK |
| `sepa_mandate.py` | 205 | Excellent service delegation |
| `member/mixins/financial_mixin.py` | 194 | Consider merging with related service |
| `member/mixins/termination_mixin.py` | 191 | Consider merging with termination service |
| `member/mixins/expense_mixin.py` | 146 | Consider merging with expense service |
| `member/mixins/chapter_mixin.py` | 120 | Consider merging with chapter service |

---

## Detailed Analysis by Domain

### 1. E-Boekhouden Integration

**Current State**: 4,892 LOC across doctype controllers
**Recommendation**: Extract to dedicated service layer

| Controller | LOC | Business Logic to Extract |
|------------|-----|---------------------------|
| `e_boekhouden_migration.py` | 3239 | Migration orchestration, cleanup, API calls |
| `e_boekhouden_settings.py` | 791 | API configuration validation |
| `e_boekhouden_account_mapping/api.py` | 666 | Account mapping API operations |
| `e_boekhouden_dashboard.py` | 459 | Dashboard data aggregation |

**Proposed Services**:
- `EBoekhoudenMigrationOrchestrator` - Migration workflow control
- `EBoekhoudenCleanupService` - Data cleanup operations
- `EBoekhoudenConfigurationService` - Settings validation
- `EBoekhoudenDashboardDataService` - Dashboard aggregations

### 2. Billing and Dues

**Current State**: ~4,700 LOC across controllers
**Recommendation**: Consolidate into billing services (partially done)

| Controller | LOC | Business Logic to Extract |
|------------|-----|---------------------------|
| `membership_dues_schedule.py` | 2917 | Progressive dues, template sync, rate calculation |
| `contribution_amendment_request.py` | 1611 | Fee validation, approval workflow |
| `dues_schedule_manager.py` | 450 | Schedule management |

**Existing Services** (already good):
- `InvoiceGenerator`
- `CoverageCalculator`
- `EligibilityChecker`
- `DuplicateInvoiceDetector`

**Needed Services**:
- `ProgressiveDuesCalculator` - Sliding scale calculations
- `ContributionAmendmentProcessor` - Amendment workflow
- `FeeMinimumValidator` - Minimum fee enforcement

### 3. Member Management

**Current State**: ~5,500 LOC across controllers and mixins
**Recommendation**: Continue service extraction (Phase 2 in progress)

| Controller | LOC | Business Logic to Extract |
|------------|-----|---------------------------|
| `member.py` | 1963 | Address normalization (mostly done) |
| `member_utils.py` | 1022 | Various utilities - move to services |
| `member/mixins/*` | ~2,600 | Payment, SEPA, expenses, chapters |

**Existing Services** (already good):
- `MemberLifecycleService`
- `MemberAddressService`
- `MemberStatusService`
- `MemberIdService`

**Needed Services**:
- Move `member_utils.py` content to appropriate services
- Consolidate mixin logic into services

### 4. SEPA and Payments

**Current State**: ~5,600 LOC across controllers
**Recommendation**: Good service architecture exists; continue pattern

| Controller | LOC | Status |
|------------|-----|--------|
| `sepa_mandate.py` | 205 | EXCELLENT - model for others |
| `direct_debit_batch.py` | 844 | GOOD - uses services |
| `sepa_processor.py` | 1203 | GOOD - modular |
| `mollie_settings.py` | 863 | Needs service extraction |
| `ponto_settings.py` | 699 | Needs service extraction |

**Existing Services** (already good):
- `SEPAMandateValidationService`
- `SEPAMandateLifecycleService`
- `BatchProcessingService`
- `BatchValidationService`

### 5. Import Tools

**Current State**: ~4,095 LOC
**Recommendation**: Extract parsing logic to services

| Controller | LOC | Business Logic to Extract |
|------------|-----|---------------------------|
| `mijnrood_csv_import.py` | 2407 | CSV parsing, validation, transformation |
| `vip_import.py` | 1132 | Data import, validation |
| `mt940_import.py` | 556 | MT940 bank statement parsing |

**Proposed Services**:
- `CSVImportService` - Generic CSV handling
- `MijnRoodDataTransformer` - MijnRood-specific transforms
- `VIPImportProcessor` - VIP data processing
- `MT940ParserService` - Bank statement parsing

### 6. Donor Management

**Current State**: ~1,546 LOC
**Status**: ✅ **LARGELY COMPLETE** - Services already exist

| Controller | LOC | Status |
|------------|-----|--------|
| `donor.py` | 935 | BSN/RSIN validation (17 LOC) should stay local - domain-specific |
| `donation.py` | 611 | Should integrate with existing `ANBIValidationService` |

**Existing Services** (already implemented):
- `ANBIValidationService` - ANBI tax validation (398 LOC) ✅
- `DonationDonorService` - Donor lookup and management ✅
- `DonationValidationService` - Donation validation ✅
- `DonationFinancialService` - Financial operations ✅
- `DonationReportingService` - Reporting ✅
- `DonorManagementService` - Member-donor integration ✅

**No new services needed** - BSN/RSIN eleven-proof validation (17 LOC) is domain-specific to Dutch tax identifiers and has no other callers. Extracting it would add indirection without benefit.

---

## Files to DELETE

These are backup files that should be removed from the codebase:

| File | LOC | Reason |
|------|-----|--------|
| `chapter_controller_backup.py` | 1360 | Backup file |
| `donation_original.py` | 971 | Backup file |
| `team_original_backup.py` | 966 | Backup file |
| `payment_mixin_optimized.py` | 653 | Duplicate - merge with payment_mixin.py |

**Total LOC to remove**: 3,950

---

## Prioritized Refactoring Roadmap (Revised)

### Phase 0: Immediate Actions (1 day)

1. **Delete backup files** - Remove 3,950 LOC of dead code
   - `chapter_controller_backup.py` (1360 LOC)
   - `donation_original.py` (971 LOC)
   - `team_original_backup.py` (966 LOC)
   - Consolidate `payment_mixin_optimized.py` (653 LOC)

2. **Address process issue** - Why are developers creating backup files instead of using git?

### Phase 1: Surgical Fixes (1-2 weeks)

1. **E-Boekhouden Migration** - 3,239 LOC is genuinely problematic
   - Extract to `EBoekhoudenMigrationOrchestrator`
   - This is the only controller that truly warrants aggressive refactoring

2. **Verify donation.py uses ANBIValidationService** - Integration check only

### Phase 2: Evaluate Before Acting

**Before extracting import services, measure usage:**
- How often is `mijnrood_csv_import.py` used post-migration?
- Is `vip_import.py` still actively used?
- If rarely used, **leave them alone**

**Controllers 600-900 LOC are likely fine:**
- `donor.py` (935 LOC) - High cohesion, domain-specific logic, keep as-is
- `mollie_settings.py` (863 LOC) - Review if API logic should move to existing `MollieConfigurationService`
- `direct_debit_batch.py` (844 LOC) - Already uses services well

### Phase 3: Only If Causing Pain

- **Member mixins consolidation** - Only if causing maintenance issues
- **Analytics services** - May need background jobs, not request-response services
- **Chapter manager decomposition** - Only if the 1,300 LOC managers are causing problems

---

## Service Layer Gaps Analysis

### Existing Service Categories (Well-Covered)

- `services/billing/` - Invoice generation, coverage calculation
- `services/member/` - Lifecycle, address, status management
- `services/communication/` - Email service
- `services/chapter/` - Chapter operations
- `services/volunteer/` - Volunteer management
- `vereinigingen_payments/services/` - SEPA processing

### Services Incorrectly Listed as Missing (Corrections)

The initial audit incorrectly identified several services as missing. These **already exist**:

| Service | Location | Status |
|---------|----------|--------|
| `ANBIValidationService` | `services/anbi_validation_service.py` | ✅ Complete (398 LOC) |
| `DonationDonorService` | `services/donation/donor_service.py` | ✅ Complete |
| `DonationFinancialService` | `services/donation/financial_service.py` | ✅ Complete |
| `DonationReportingService` | `services/donation/reporting_service.py` | ✅ Complete |
| `DonationValidationService` | `services/donation/validation_service.py` | ✅ Complete |
| `DonorManagementService` | `services/member/donor/donor_management_service.py` | ✅ Complete |
| `MollieConfigurationService` | `verenigingen_payments/services/mollie_configuration_service.py` | ✅ Complete |
| `PontoConfigurationService` | `vereinigingen_payments/ponto/services/configuration_service.py` | ✅ Complete |
| `EmailConfigurationService` | `services/communication/email_configuration_service.py` | ✅ Complete |

### Actually Missing Service Categories

| Category | Needed Services | Priority |
|----------|----------------|----------|
| `services/import/` | CSV import, MT940 parsing, data transformation | Medium (check usage first) |
| `services/analytics/` | Membership analytics, termination analytics | Low |
| `services/encryption/` | BSN/RSIN field encryption (17 LOC - may not warrant service) | Low |

---

## Metrics and Goals (Revised)

### Current State

- **Average controller size**: 385 LOC
- **Controllers >600 LOC**: 35 (23%)
- **Controllers >1000 LOC**: 15 (10%)
- **Existing services**: 87 files, 39,284 LOC

### Revised Target State

The original 250 LOC target was **unrealistic for Frappe**. Frappe controllers have unavoidable overhead from lifecycle hooks, child tables, permissions, and `@frappe.whitelist()` methods.

| Controller Type | Realistic Target | Reason |
|-----------------|------------------|--------|
| Simple data DocTypes | <150 LOC | Minimal business logic |
| Workflow DocTypes | 200-350 LOC | Status transitions, notifications |
| Core business DocTypes | 350-500 LOC | Complex lifecycles |
| Integration DocTypes | 400-600 LOC | Orchestration belongs here |
| Settings DocTypes | <100 LOC | Pure configuration |

**Achievable Goals:**
- Eliminate controllers >1000 LOC (currently 15 → target 3-4)
- Reduce controllers >600 LOC from 35 (23%) to <15 (10%)
- Delete 3,950 LOC of backup files

### Revised Success Criteria

1. Controllers handle document lifecycle with clear delegation patterns
2. Business logic extracted **only when genuinely shared** across multiple DocTypes
3. No backup files in codebase (use git instead)
4. **Locality of behavior preserved** - domain-specific logic stays with its DocType

---

## Appendix: Complete File Listing

### By Size (Descending)

```
3239 e_boekhouden_migration.py
2917 membership_dues_schedule.py
2407 mijnrood_csv_import.py
1963 member.py
1611 contribution_amendment_request.py
1360 chapter_controller_backup.py (DELETE)
1323 chapter/managers/member_manager.py
1305 membership.py
1240 chapter/managers/board_manager.py
1203 direct_debit_batch/sepa_processor.py
1162 chapter.py
1142 volunteer.py
1132 vip_import.py
1083 brand_settings.py
1022 member_utils.py
997 member/mixins/payment_mixin.py
971 donation_original.py (DELETE)
966 team_original_backup.py (DELETE)
935 donor.py
863 mollie_settings.py
844 direct_debit_batch.py
794 member/scheduler.py
791 e_boekhouden_settings.py
739 membership_termination_analytics.py
726 chapter/managers/communication_manager.py
699 ponto_settings.py
673 membership_termination_request.py
666 e_boekhouden_account_mapping/api.py
653 member/mixins/payment_mixin_optimized.py (DELETE/MERGE)
649 account_creation_request.py
643 periodic_donation_agreement.py
638 team.py
611 donation.py
605 member/mixins/sepa_mixin.py
599 chapter/managers/volunteer_integration_manager.py
556 mt940_import.py
556 event_contact_campaign.py
533 ponto_payment_link.py
521 email_configuration.py
509 performance_optimization_setup.py
484 payment_plan.py
461 contact_request_automation.py
461 critical_operation_rule.py
460 expulsion_report_entry.py
459 e_boekhouden_dashboard.py
458 analytics_alert_rule.py
450 dues_schedule_manager.py
445 chapter_join_request.py
431 sepa_audit_log.py
408 donation_campaign.py
402 bulk_operation_tracker.py
380 chapter/validators/chapter_validator.py
377 membership_analytics_snapshot.py
357 membership_type.py
357 member_contact_request.py
345 membership/scheduler.py
343 chapter/validators/postal_code_validator.py
342 member_id_manager.py
328 chapter/managers/base_manager.py
322 ponto_payment_request.py
321 chapter/validators/chapter_info_validator.py
314 team_member.py
308 region.py
273 membership_goal.py
256 verenigingen_settings.py
250 chapter/validators/board_member_validator.py
244 chapter_board_member.py
240 organization_document.py
240 membership_dues_schedule_hooks.py
239 system_alert.py
239 api_audit_log.py
229 account_group_project_mapping.py
228 movement.py
217 sepa_retry_batch.py
205 sepa_mandate.py
194 member/mixins/financial_mixin.py
192 e_boekhouden_account_mapping.py
191 member/mixins/termination_mixin.py
189 sepa_mandate_usage.py
184 ponto_sync_log.py
171 e_boekhouden_item_mapping.py
169 chapter_member.py
168 team_role.py
146 member/mixins/expense_mixin.py
144 chapter_role.py
124 mollie_audit_log.py
123 sepa_retry_operation.py
120 member/mixins/chapter_mixin.py
107 bank_integration_settings.py
99 sepa_operation_audit_log.py
97 e_boekhouden_payment_mapping.py
95 chapter/validators/base_validator.py
76 party_enrichment_queue.py
75 volunteer_activity.py
75 chapter_board_document.py
56 payment_history.py
43 verenigingen_payments_settings.py
43 member_iban_history.py
37 e_boekhouden_import_log.py
36 volunteer_assignment.py
34 member_sepa_mandate_link.py
31 payment_history_update_queue.py
31 mollie_reconciliation_log.py
26 volunteer_interest_category.py
25 event_contact_campaign_member.py
24 team_role_profile_assignment.py
24 chapter_role_profile_mapping.py
23 volunteer_skill.py
21 sepa_return_file_log.py
19 sepa_mandate_dashboard.py
19 donation_payment.py
19 e_boekhouden_cost_center_mapping.py
18 expense_category.py
18 dashboard_chart_custom.py
17 ponto_bank_account_mapping.py
16 webhook_processing_log.py
13 termination_audit_entry.py
13 membership_tier.py
13 chapter_membership_history.py
11 board_document_category.py
11 activity_tag.py
9 (multiple child table controllers)
8 (multiple minimal controllers)
6 (multiple stub controllers)
5 (multiple empty controllers)
```

---

## Recommendations Summary (Revised After Expert Review)

### Do Now (1 day)
1. **Delete 4 backup files** (3,950 LOC) - Zero risk, immediate payoff

### Do Soon (1-2 weeks)
2. **Extract E-Boekhouden Migration** (3,239 LOC) - Only controller that truly warrants service extraction

### Evaluate First
3. **Import tools** - Measure usage before extracting; may be rarely used post-migration
4. **600-900 LOC controllers** - Most are fine; high cohesion is acceptable

### Don't Do
5. ~~Extract DutchTaxIdentifierService~~ - 17 LOC, single-use, keep local
6. ~~Extract ANBIComplianceService~~ - Already exists as `ANBIValidationService`
7. ~~Target 250 LOC average~~ - Unrealistic for Frappe; 350-500 is acceptable for core DocTypes

**Revised effort estimate**: 1-2 weeks for surgical fixes (not 6-8 weeks)
**Estimated LOC reduction**: ~7,200 LOC (backup files + migration extraction)

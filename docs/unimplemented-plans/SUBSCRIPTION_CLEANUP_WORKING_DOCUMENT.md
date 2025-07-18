# Subscription Reference Cleanup Working Document

## Overview
This document lists all files that still contain subscription references and need to be updated to use the new Membership Dues Schedule system.

**Status**: Active cleanup in progress
**Last Updated**: 2025-01-18
**Total Files Identified**: 50

---

## Priority Classification

### 🔴 HIGH PRIORITY (Core System Files)
These files are critical to the core membership system and should be updated first.

#### API & Core Logic Files
- [ ] `verenigingen/api/membership_application_review.py`
- [ ] `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.py`
- [ ] `verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.json`
- [ ] `verenigingen/verenigingen/doctype/direct_debit_batch/direct_debit_batch.py`
- [ ] `verenigingen/verenigingen/doctype/member/member.py`
- [ ] `verenigingen/verenigingen/doctype/member/member.js`
- [ ] `verenigingen/utils/feature_flags.py`
- [ ] `verenigingen/hooks.py`

#### Settings & Configuration
- [ ] `verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json`

### 🟡 MEDIUM PRIORITY (Reports & Utilities)
These files provide reporting and utility functions that should be updated after core files.

#### Reports
- [ ] `verenigingen/verenigingen/report/overdue_member_payments/overdue_member_payments.py`
- [ ] `verenigingen/verenigingen/report/orphaned_subscriptions_report/orphaned_subscriptions_report.py`

#### Utilities & Helpers
- [ ] `verenigingen/utils/membership_dues_test_validator.py`
- [ ] `scripts/deployment/validate_production_schema.py`
- [ ] `scripts/monitoring/zabbix_integration.py`

### 🟢 LOW PRIORITY (Tests & Frontend)
These files can be updated after core functionality is migrated.

#### Test Files
- [ ] `verenigingen/tests/backend/components/test_fee_override_subscription.py`
- [ ] `verenigingen/tests/test_enhanced_contribution_amendment_system.py`
- [ ] `verenigingen/tests/test_fee_override_migration.py`
- [ ] `verenigingen/tests/backend/components/test_enhanced_sepa_processing.py`
- [ ] `verenigingen/tests/backend/components/test_membership_dues_edge_cases.py`
- [ ] `verenigingen/tests/backend/components/test_payment_plan_system.py`
- [ ] `verenigingen/tests/workflows/test_enhanced_membership_lifecycle.py`
- [ ] `verenigingen/tests/backend/components/test_membership_dues_security_validation.py`
- [ ] `verenigingen/tests/backend/components/test_membership_dues_stress_testing.py`
- [ ] `verenigingen/tests/backend/components/test_membership_dues_real_world_scenarios.py`
- [ ] `scripts/testing/test_fee_functions.py`
- [ ] `scripts/testing/test_migration_simple.py`

#### Frontend Files
- [ ] `verenigingen/public/js/membership_application.js`
- [ ] `verenigingen/public/js/member/js_modules/payment-utils.js`
- [ ] `verenigingen/public/js/member/js_modules/termination-utils.js`

#### Portal Pages
- [ ] `verenigingen/templates/pages/enhanced_membership_application.html`
- [ ] `verenigingen/templates/pages/enhanced_membership_application.py`

#### Standalone Test Scripts
- [ ] `test_enhanced_membership_portal.py`
- [ ] `test_contribution_system.py`
- [ ] `test_new_membership_system.py`

---

## ✅ COMPLETED FILES
These files have already been cleaned up and migrated to the dues schedule system:

### Core Membership System
- [x] `verenigingen/verenigingen/doctype/membership/membership.py`
- [x] `verenigingen/verenigingen/doctype/membership/membership.json`
- [x] `verenigingen/verenigingen/doctype/membership/membership.js`
- [x] `verenigingen/verenigingen/doctype/membership/test_membership.py`
- [x] `verenigingen/verenigingen/doctype/membership/test_membership.js`
- [x] `verenigingen/verenigingen/doctype/membership/enhanced_dues_schedule.py`
- [x] `verenigingen/verenigingen/doctype/membership/scheduler.py`

### Membership Type System
- [x] `verenigingen/verenigingen/doctype/membership_type/membership_type.py`
- [x] `verenigingen/verenigingen/doctype/membership_type/membership_type.json`
- [x] `verenigingen/verenigingen/doctype/membership_type/membership_type.js`
- [x] `verenigingen/verenigingen/doctype/membership_type/test_membership_type.py`
- [x] `verenigingen/verenigingen/doctype/membership_type/test_membership_type.js`

### Termination System
- [x] `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py`

---

## 📋 DOCUMENTATION FILES
These files contain references in documentation/planning content but don't need code updates:

- [ ] `FINAL_MIGRATION_STATUS.md` - Status documentation
- [ ] `REMAINING_SUBSCRIPTION_CLEANUP_PLAN.md` - Planning document
- [ ] `MIGRATION_COMPLETION_SUMMARY.md` - Summary documentation
- [ ] `TEST_FILES_UPDATE_PLAN.md` - Planning document
- [ ] `API_ENDPOINTS_UPDATE_SUMMARY.md` - Summary documentation
- [ ] `PHASE_A_CLEANUP_SUMMARY.md` - Summary documentation
- [ ] `LEGACY_CLEANUP_PROGRESS.md` - Progress documentation
- [ ] `DEPLOYMENT_GUIDE.md` - Deployment documentation
- [ ] `PRODUCTION_DEPLOYMENT_CHECKLIST.md` - Checklist documentation
- [ ] `REAL_WORLD_DUES_AMENDMENT_TESTING_SUMMARY.md` - Testing documentation
- [ ] `DUES_SYSTEM_MIGRATION_INVENTORY.md` - Inventory documentation
- [ ] `MEMBERSHIP_DUES_SYSTEM_DETAILED_PLAN_V2.md` - Planning document

---

## 🎯 MIGRATION STRATEGY

### Phase 1: Core System (HIGH PRIORITY)
1. **API Layer**: Update `membership_application_review.py` to use dues schedule
2. **Member Integration**: Update `member.py` and `member.js` to use dues schedule
3. **Amendment System**: Update `contribution_amendment_request.py` to use dues schedule
4. **Direct Debit**: Update `direct_debit_batch.py` to use dues schedule
5. **Settings**: Update `verenigingen_settings.json` to remove subscription fields
6. **Hooks**: Update `hooks.py` to use dues schedule system
7. **Feature Flags**: Update `feature_flags.py` to deprecate subscription flags

### Phase 2: Reports & Utilities (MEDIUM PRIORITY)
1. **Reports**: Update payment and orphaned subscription reports
2. **Utilities**: Update test validators and deployment scripts
3. **Monitoring**: Update Zabbix integration scripts

### Phase 3: Tests & Frontend (LOW PRIORITY)
1. **Test Files**: Update all test files to use dues schedule
2. **Frontend**: Update JavaScript modules and portal pages
3. **Standalone Scripts**: Update test scripts

### Phase 4: Documentation Cleanup
1. **Planning Docs**: Archive or update planning documents
2. **Status Docs**: Update status and progress documentation
3. **Guides**: Update deployment and testing guides

---

## 🔧 TECHNICAL NOTES

### Common Patterns to Update:
1. **Field References**: `subscription` → `dues_schedule`
2. **API Methods**: `create_subscription_*` → `create_dues_schedule_*`
3. **Validation**: `subscription_period` → `billing_period`
4. **Queries**: ERPNext Subscription queries → Membership Dues Schedule queries
5. **Hooks**: Subscription event handlers → Dues schedule event handlers

### Deprecation Strategy:
- Keep old methods with deprecation warnings
- Add new methods using dues schedule system
- Update UI to use new methods
- Gradually remove old methods after migration

---

## 📊 PROGRESS TRACKING

**Overall Progress**: 11/50 files completed (22%)

### By Priority:
- **HIGH**: 0/8 files completed (0%)
- **MEDIUM**: 0/5 files completed (0%)
- **LOW**: 0/23 files completed (0%)
- **COMPLETED**: 11/11 files completed (100%)
- **DOCUMENTATION**: 0/14 files reviewed (0%)

### Next Actions:
1. Start with `verenigingen/api/membership_application_review.py`
2. Update `verenigingen/verenigingen/doctype/member/member.py`
3. Update `verenigingen/utils/feature_flags.py`
4. Update `verenigingen/hooks.py`

---

## 🏁 COMPLETION CRITERIA

A file is considered "complete" when:
- [ ] All subscription references removed or deprecated
- [ ] Equivalent dues schedule functionality implemented
- [ ] Tests pass with new system
- [ ] Documentation updated
- [ ] Backward compatibility maintained where needed

---

**Last Updated**: 2025-01-18
**Document Version**: 1.0
**Status**: Active Development

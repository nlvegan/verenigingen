# Active Code List - January 2025

## Overview
This document provides a comprehensive list of actively maintained code files in the Verenigingen system, organized by functionality. Updated as of January 2025 with recent enhancements.

## E-Boekhouden Integration

### Modular Refactoring (NEW - January 2025)
- **`processors/base_processor.py`** ⭐ NEW
  - Abstract base class for transaction processors
  - Common validation and error handling

- **`processors/transaction_coordinator.py`** ⭐ NEW
  - Orchestrates all transaction processing
  - Routes mutations to appropriate processors
  - Provides clean, testable interface

- **`processors/invoice_processor.py`** ⭐ NEW
  - Wraps existing invoice creation functions

- **`processors/payment_processor.py`** ⭐ NEW
  - Wraps existing payment entry creation

- **`processors/journal_processor.py`** ⭐ NEW
  - Wraps existing journal entry creation

- **`processors/opening_balance_processor.py`** ⭐ NEW
  - Handles opening balance imports

- **`modular_migration_example.py`** ⭐ NEW
  - Example integration with main file
  - Shows gradual adoption path

### Core Integration Files
- **`verenigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py`** ⭐ RECENTLY MODIFIED
  - Main REST API migration handler
  - Added: `get_appropriate_cash_account()` function (lines 62-143)
  - Fixed: Duplicate detection logic (lines 2273-2282, 3364-3367)
  - Updated: Zero-amount invoice handling
  - Primary file for transaction import from eBoekhouden

- **`verenigingen/utils/eboekhouden/party_resolver.py`** ⭐ RECENTLY MODIFIED
  - Party (customer/supplier) resolution and creation
  - Enhanced: Logging for empty relation data (lines 95-111, 140-158, 212-230)
  - Added: Description-based name extraction fallback
  - Handles party naming and deduplication

- **`verenigingen/utils/eboekhouden/eboekhouden_soap_api.py`**
  - Legacy SOAP API integration
  - Maintained for backward compatibility
  - Limited to 500 recent transactions

- **`verenigingen/utils/eboekhouden/transaction_utils.py`**
  - Transaction processing utilities
  - Creates Sales/Purchase invoices from mutations
  - Handles multi-line transactions

- **`verenigingen/utils/eboekhouden/invoice_helpers.py`**
  - Invoice creation helpers
  - Tegenrekening (contra account) handling
  - Line item creation utilities

### API Endpoints
- **`verenigingen/api/eboekhouden_migration_redesign.py`**
  - Migration statistics and monitoring
  - System readiness validation
  - Progress tracking endpoints

- **`verenigingen/api/test_eboekhouden_connection.py`**
  - Dual API connection testing
  - Connection validation endpoints

- **`verenigingen/api/check_account_types.py`**
  - Account type review and fixing
  - Chart of accounts management

### DocTypes
- **`verenigingen/verenigingen/doctype/e_boekhouden_settings/e_boekhouden_settings.json`** ⭐ RECENTLY MODIFIED
  - Added: `use_enhanced_payment_processing` field
  - Configuration storage for API credentials

- **`verenigingen/verenigingen/doctype/e_boekhouden_migration/e_boekhouden_migration.py`**
  - Migration controller and orchestration
  - UI interaction handlers

### JavaScript Frontend
- **`verenigingen/verenigingen/doctype/e_boekhouden_migration/e_boekhouden_migration.js`**
  - Migration UI and progress tracking
  - Real-time status updates
  - Two-step migration process

## Test Infrastructure

### Base Test Classes
- **`verenigingen/tests/utils/base.py`** ⭐ RECENTLY MODIFIED
  - Enhanced: Customer cleanup in `tearDown()` (lines 134-199)
  - Added: `_cleanup_member_customers()` method
  - Added: `_cleanup_customer_dependencies()` method
  - Base class for all Verenigingen tests

- **`verenigingen/tests/base_test_case.py`**
  - Enhanced BaseTestCase with automatic cleanup
  - Built-in test data factory
  - Performance monitoring

### Test Utilities
- **`verenigingen/tests/fixtures/enhanced_test_cleanup.py`** ⭐ NEW FILE
  - Standalone cleanup utility
  - Pattern-based customer cleanup
  - Orphaned customer detection

- **`verenigingen/tests/test_data_factory.py`**
  - Comprehensive test data generation
  - Mock bank support (TEST, MOCK, DEMO)
  - Relationship handling

### Test Runners
- **`verenigingen/tests/test_runner.py`**
  - Main test runner with suite support
  - Smoke, diagnostic, and full test suites

- **`scripts/testing/runners/regression_test_runner.py`**
  - Regression testing framework
  - Pre/post change validation

## Member Management

### Core Member System
- **`verenigingen/verenigingen/doctype/member/member.py`**
  - Member lifecycle management
  - Uses mixin pattern for modularity
  - Integrates with customer creation

- **`verenigingen/verenigingen/doctype/membership/membership.py`**
  - Membership subscription handling
  - Renewal and expiration logic
  - Fee calculation

- **`verenigingen/verenigingen/doctype/membership_application/membership_application.py`**
  - Application workflow
  - Creates both Member and Customer on approval

### Member API Endpoints
- **`verenigingen/api/member.py`**
  - Member-related API endpoints
  - Profile management
  - Status queries

- **`verenigingen/api/membership_application_review.py`**
  - Application review assignments
  - Notification handling

## Volunteer System

### Core Volunteer Components
- **`verenigingen/verenigingen/doctype/volunteer/volunteer.py`**
  - Volunteer management
  - Team assignments
  - Activity tracking

- **`verenigingen/verenigingen/doctype/volunteer_expense/volunteer_expense.py`**
  - Expense submission and approval
  - Chapter membership validation
  - Workflow integration

### Volunteer Portal
- **`verenigingen/templates/pages/volunteer/`**
  - Dashboard and UI components
  - Team management interface
  - Expense submission forms

## Financial Integration

### SEPA Processing
- **`verenigingen/verenigingen/doctype/sepa_mandate/sepa_mandate.py`**
  - SEPA mandate management
  - Bank validation
  - Mandate lifecycle

- **`verenigingen/verenigingen/doctype/direct_debit_batch/direct_debit_batch.py`**
  - Batch processing for direct debits
  - XML generation
  - Bank file creation

### Payment Processing
- **`verenigingen/utils/payment_processing.py`**
  - Payment handling utilities
  - Invoice creation
  - Payment reconciliation

## Chapter Management

### Core Chapter System
- **`verenigingen/verenigingen/doctype/chapter/chapter.py`**
  - Chapter organization
  - Uses manager pattern
  - Geographic validation

- **`verenigingen/verenigingen/doctype/chapter_member/chapter_member.py`**
  - Chapter membership records
  - Role assignments
  - Board management

## Reports

### Key Reports
- **`verenigingen/verenigingen/report/chapter_members/chapter_members.py`**
  - Chapter membership listings
  - Role filtering
  - Export functionality

- **`verenigingen/verenigingen/report/termination_audit_report/termination_audit_report.py`**
  - Termination compliance tracking
  - Audit trail reporting

## Utilities

### Validation
- **`verenigingen/utils/iban_validator.py`**
  - IBAN validation with MOD-97
  - Mock bank support
  - BIC derivation

- **`verenigingen/utils/validations.py`**
  - Business rule validations
  - Cross-doctype validations

### Permissions
- **`verenigingen/permissions.py`**
  - Custom permission logic
  - Organization-based data isolation
  - Query conditions

## Configuration

### Core Configuration
- **`hooks.py`**
  - App configuration
  - Event handlers
  - Scheduled tasks

- **`pyproject.toml`**
  - Python package configuration
  - Dependencies

## Documentation Files

### Recently Updated
- **`CLAUDE.md`** ⭐ UPDATED
  - Main guidance document
  - Updated with test cleanup info
  - E-Boekhouden fixes documented

- **`EBOEKHOUDEN_IMPLEMENTATION_SUMMARY.md`** ⭐ UPDATED
  - Comprehensive eBoekhouden documentation
  - Recent fixes section added

- **`RECENT_UPDATES_2025_01.md`** ⭐ NEW
  - January 2025 update summary
  - All recent changes documented

## Notes

### Recent Changes Focus Areas
1. **E-Boekhouden Integration**
   - Fixed missing field error
   - Improved duplicate detection
   - Enhanced party naming
   - Dynamic cash account resolution

2. **Test Infrastructure**
   - Automatic customer cleanup
   - Enhanced test base classes
   - Pattern-based cleanup utilities

### Files Requiring Attention
- Party resolver needs investigation for empty API responses
- Consider batch party enrichment implementation
- Monitor zero-amount invoice imports

### Maintenance Priority
1. High: E-Boekhouden integration files (production critical)
2. High: Test infrastructure (development efficiency)
3. Medium: Member/Volunteer systems (stable but active)
4. Low: Reports (mostly read-only operations)

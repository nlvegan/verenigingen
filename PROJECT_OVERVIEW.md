# Verenigingen Project Overview

This document provides comprehensive information about the Verenigingen association management system for reference purposes.

## System Overview

Verenigingen is a comprehensive association management system built on the Frappe Framework. It manages members, chapters, volunteers, donations, and complex business processes including termination workflows and financial operations.

**Development Context:**
- This instance is a development installation for creating a deployable app
- All database contents are for testing purposes only
- The app is still in active development - backwards compatibility is not required at this stage
- This is a dev instance - one-off fixes are generally pointless as we need sustainable, deployable solutions
- All changes should focus on creating production-ready code that can be deployed elsewhere

**Tech Stack:** Frappe Framework (Python), ERPNext, MariaDB/MySQL, JavaScript
**Dependencies:** ERPNext and Payments apps are required

## E-Boekhouden API Integration

**CRITICAL NOTE:** The system includes a comprehensive eBoekhouden integration with dual API support. **REST API is the primary and recommended approach**:

**API Documentation:** https://api.e-boekhouden.nl/swagger/v1/swagger.json

### API Capabilities
- **REST API (Primary)**:
  - Unlimited transaction history access
  - Complete account and master data import
  - Enhanced error handling and performance
  - Modern JSON-based communication
  - Future-proof implementation

- **SOAP API (Legacy)**:
  - Limited to 500 most recent transactions
  - Maintained for backward compatibility
  - Used for specific legacy features

### Recent Integration Enhancements (2025)
- **✅ Opening Balance Import**: Complete opening balance import system with €324K+ successfully imported
- **✅ Zero Amount Handling**: Now imports ALL zero-amount invoices (ERPNext supports them)
- **✅ Smart Document Naming**: Meaningful document names like `EBH-Payment-1234`, `EBH-Memoriaal-5678`
- **✅ Multi-Account Type Support**: Proper handling of Receivable, Payable, and Stock accounts
- **✅ Error Recovery**: Robust error handling with automatic retry and skip mechanisms
- **✅ Balance Validation**: Automatic transaction balancing and validation
- **✅ Party Management**: Automatic customer/supplier creation with proper party assignment
- **✅ Dynamic Cash Account**: No more hardcoded accounts - intelligent cash account resolution
- **✅ Enhanced Party Naming**: Better fallbacks when API returns empty relation data

### Integration Status
The eBoekhouden integration is production-ready and handles:
- Complete chart of accounts import with intelligent mapping
- All transaction types (Invoices, Payments, Journal Entries)
- Opening balances with automatic party assignment
- Multi-line transactions with complex party relationships
- VAT handling and Dutch tax compliance
- Real-time migration monitoring with detailed progress reporting

**Migration Priority**: Always use REST API for new development. The system gracefully handles both REST and SOAP but REST provides superior functionality.

## Portal Pages and Administrative Tools

### Brand Management System
**Location:** `/brand_management` (Admin only)

The system includes a comprehensive brand management interface that allows administrators to configure colors and theming across all portal pages.

**Key Features:**
- **Brand Settings Doctype:** Configurable color fields for primary, secondary, accent, success, warning, error, info, text, and background colors
- **Dynamic CSS Generation:** Generates CSS with CSS custom properties and Tailwind class overrides via `/brand_css` endpoint
- **Color Preview:** Live preview of color combinations before activation
- **One-Click Activation:** Switch between different brand configurations instantly

**Default Brand Colors:**
- Primary: `#cf3131` (RSP Red)
- Secondary: `#01796f` (Pine Green)
- Accent: `#663399` (Royal Purple)

**Pages Using Brand Colors:**
- `/membership_fee_adjustment` - Fee sliders and buttons
- `/my_teams` - Team management interface
- `/address_change` - Form styling
- `/team_members` - Member listings
- `/volunteer/dashboard` - Volunteer portal
- All portal pages via global CSS variables

**Technical Implementation:**
- CSS custom properties for dynamic theming: `var(--brand-primary)`, `var(--brand-secondary)`, etc.
- Tailwind CSS class overrides with `!important` declarations
- 1-hour CSS caching for performance
- Migration hook creates default settings automatically
- Global CSS integration via `hooks.py`

**Access Requirements:**
- System Manager or Verenigingen Administrator role
- Available at `/brand_management` for color configuration
- Brand Settings doctype available in desk for advanced management

**Files:**
- `verenigingen/verenigingen/doctype/brand_settings/` - Core doctype and business logic
- `verenigingen/templates/pages/brand_management.*` - Admin portal interface
- `verenigingen/templates/pages/brand_css.py` - CSS endpoint handler
- Brand CSS served globally via `/brand_css` endpoint in `hooks.py`

## Workspace Structure and Navigation

The Verenigingen workspace provides organized access to all system functionality through a comprehensive navigation structure. The workspace is organized into logical sections with subsections for related features.

### Main Workspace Sections

#### Members/Memberships
The primary section for member-related functionality:

**Subsections:**
- **Memberships** (5 items) - Core membership management doctypes
- **Billing & Dues** (2 items) - Payment and dues management
- **Applications & Requests** (4 items):
  - Membership Termination Request (DocType)
  - Membership Applications (`/apply_for_membership`) - Public application form
  - Membership Application Workflow Demo (`/workflow_demo`) - Process demonstration
- **Donations** (3 items) - Donation management and donor relations

#### Volunteering
Comprehensive volunteer management functionality:

**Subsections:**
- **Volunteers** (6 items):
  - Core volunteer doctypes (Volunteer, Volunteer Activity)
  - Team and task management
  - Volunteer Portal - Expenses (`/volunteer/expenses`) - Enhanced expense management
  - Volunteer Portal - Profile (`/volunteer/profile`) - Profile management
- **Volunteer Expenses** (2 items) - Expense doctypes and approval workflows

#### Chapters/Teams
Geographic and organizational structure management:

**Subsections:**
- **Chapters** (2 items) - Chapter management and geographic organization
- **Teams and Commissions** (1 item) - Team structure and commission management

#### Financial
Complete financial management and integration:

**Subsections:**
- **Payment Processing** (4 items) - SEPA mandates, direct debits, payment processing
- **Banking** (5 items) - Bank integration, reconciliation, transaction management
- **Accounting (Misc.)** (5 items) - General accounting, invoicing, fiscal management

#### Reports
Comprehensive reporting and analytics:

**Single Section containing:**
- **Member & Chapter Reports:**
  - Expiring Memberships
  - New Members
  - Members Without Chapter
  - Overdue Member Payments
  - Chapter Expense Report
  - Members Without Active Memberships
  - Members Without Dues Schedule
  - **Membership Dues Coverage Analysis** - Coverage gap analysis and financial tracking
- **System & Administrative Reports:**
  - Users by Team
  - Membership Application Workflow Demo
  - Termination Compliance Report

#### Settings & Configuration
System administration and configuration:

**Subsections:**
- **Settings** (6 items):
  - Core system settings (2 original items)
  - **Admin Tools** (`/admin_tools`) - Administrative management interface
  - **ANBI Dashboard** (`/anbi_dashboard`) - ANBI compliance monitoring
  - **SEPA Reconciliation Dashboard** (`/sepa_reconciliation_dashboard`) - Financial reconciliation tools
  - **MT940 Import** (`/mt940_import`) - Bank data import functionality
- **Portal Pages** (6 items):
  - Member Portal (`/member_portal`) - Main member interface
  - Chapter Dashboard (`/chapter-dashboard`) - Chapter management
  - Volunteer Dashboard (`/volunteer/dashboard`) - Volunteer portal entry
  - Brand Management (`/brand_management`) - System theming and branding
  - Membership Fee Adjustment (`/membership_fee_adjustment`) - Fee management tools
  - Additional portal and administrative pages

### Workspace Design Principles

**Logical Organization:**
- Related functionality grouped together under intuitive section names
- Clear separation between member-facing and administrative tools
- Hierarchical structure with main sections and specialized subsections

**User Experience:**
- Quick access to frequently used features
- Progressive disclosure with subsections for complex areas
- Consistent naming conventions and clear navigation paths

**Administrative Access:**
- Critical administrative tools easily accessible in Settings section
- Specialized dashboards for compliance and financial management
- Separation of routine operations from advanced administrative functions

**Integration Points:**
- Portal pages linked directly from workspace for quick access
- Reports organized by functional area (member vs system reports)
- Cross-functional tools (like applications) grouped logically rather than by technical implementation

### Technical Implementation

**Workspace Configuration:**
- Defined in `verenigingen/fixtures/workspace.json`
- Uses Frappe's Card Break system for section organization
- Links include both DocTypes and custom Page routes
- Visual layout defined in workspace content with proper spacing and headers

**Key Files:**
- `verenigingen/fixtures/workspace.json` - Complete workspace definition
- Individual page templates in `verenigingen/templates/pages/` - Portal page implementations
- Portal pages use role-based access control for appropriate user experience

## Architecture Overview

### Core Domain Models

**Member System:**
- `Member` doctype uses mixin pattern: PaymentMixin, SEPAMandateMixin, ChapterMixin, TerminationMixin
- `Membership` handles lifecycle, renewals, and fees with custom subscription override system
- Member ID management with automated generation and validation

**Chapter System:**
- `Chapter` doctype uses manager pattern for specialized operations:
  - `BoardManager` - board member operations
  - `MemberManager` - member operations
  - `CommunicationManager` - communication handling
  - `VolunteerIntegrationManager` - volunteer integration
- Geographic organization with postal code validation

**Volunteer System:**
- `Volunteer` with aggregated assignments and expense management
- `Volunteer_Expense` with comprehensive approval workflows
- Activity tracking and team-based organization

**Financial Integration:**
- ERPNext Sales Invoice integration for payments
- SEPA direct debit processing via `Direct_Debit_Batch`
- SEPA mandate management with JavaScript UI integration:
  - `validate_mandate_creation()` - Validates mandate parameters
  - `derive_bic_from_iban()` - Auto-derives BIC from Dutch IBANs
  - `create_and_link_mandate_enhanced()` - Creates and links mandates
  - `get_active_sepa_mandate()` - Retrieves active mandates
- Dutch BTW (VAT) compliance and reporting
- Multi-currency donation tracking

### Key Business Processes

**Termination Workflow:**
- Enhanced termination system in `membership_termination_request/`
- Governance compliance with audit trails in `termination_audit_entry/`
- Impact preview and safe execution
- Appeals process integration

**Application Review:**
- Multi-step workflow from public application to member creation
- Review assignments and notifications via `membership_application_review.py`
- Payment integration for approved applications
- Geographic chapter assignment

**Subscription Management:**
- Custom override system in `subscription_override.py`
- Orphaned subscription detection and cleanup
- Automated renewal processing via scheduler

## File Organization

**API Layer:** `verenigingen/api/` - RESTful endpoints with whitelisted methods
**Templates:** `verenigingen/templates/` - Public pages and member portals
**Utilities:** `verenigingen/utils/` - Shared business logic and helpers
**Tests:** `verenigingen/tests/` - 70+ comprehensive test files
**Public Assets:** `verenigingen/public/` - CSS/JS organized by component

## Development Patterns

### Document Events
The system uses extensive document event hooks in `hooks.py` for:
- Membership lifecycle management
- Payment history synchronization
- Termination status updates
- Tax exemption handling

### Permission System
- Organization-based data isolation via `permissions.py`
- Role-based access control with custom roles
- Document-level and field-level security
- Permission query conditions for data access

#### Frappe Permission Levels (Permlevel)

**Critical Understanding of Permlevel in Frappe Framework:**

Frappe uses a multi-level permission system where fields can be assigned different permission levels (0, 1, 2, etc.). This creates field-level security within documents:

**Permlevel 0 (Default):**
- Standard fields accessible to users with basic document permissions
- Controlled by standard role permissions (read, write, create, delete)
- Most fields should be at permlevel 0 for normal access

**Permlevel 1+ (Restricted):**
- Fields requiring elevated permissions beyond basic document access
- Requires separate permission entries in the DocType's permissions array
- Users need BOTH document-level permissions AND permlevel-specific permissions
- Frappe enforces this at the framework level, hiding fields even from users with correct roles

**Permission Configuration:**
```json
// In doctype.json permissions array
{
  "role": "System Manager",
  "read": 1,
  "write": 1
}, // Permlevel 0 permissions
{
  "permlevel": 1,
  "role": "System Manager",
  "read": 1,
  "write": 1
}  // Permlevel 1 permissions
```

**Field Configuration:**
```json
{
  "fieldname": "sensitive_field",
  "fieldtype": "Currency",
  "permlevel": 1  // Requires permlevel 1 permissions
}
```

**JavaScript Behavior:**
- `frm.perm[1].read` checks if user has permlevel 1 read access
- Fields are automatically hidden by Frappe if user lacks permlevel permissions
- Manual JavaScript visibility control cannot override permlevel restrictions
- Setting `permlevel: 0` makes fields accessible to standard role permissions

**Best Practices:**
- Use permlevel 0 for most fields, rely on role-based access control
- Reserve permlevel 1+ only for highly sensitive fields (financial, admin-only)
- Always include matching permission entries for each permlevel used
- Consider user experience - hidden fields can confuse users with appropriate roles

**Common Issues:**
- Fields hidden despite user having correct roles (missing permlevel permissions)
- JavaScript cannot force-show permlevel-restricted fields
- Session permissions may not immediately reflect permlevel changes
- you misspell 'verenigingen' as 'vereiningen' or other misspellings.

### Scheduled Tasks
Daily and weekly schedulers handle:
- Membership renewals and expiration processing
- Payment failure notifications
- Termination compliance auditing
- Amendment request processing

## Key Configuration Files

- `hooks.py` - Central app configuration and event handlers
- `pyproject.toml` - Python package configuration
- `permissions.py` - Custom permission logic
- `validations.py` - Business rule validations

## Testing Infrastructure

**Test Structure:**
- Use custom test runners for comprehensive suites
- Test files follow pattern: `test_[component]_[type].py`
- 8,852+ lines of test coverage across all components
- Security, performance, and edge case testing included

**Test Organization (Reorganized for better maintainability):**
- `verenigingen/tests/` - Main comprehensive test suite (26+ files)
- `scripts/testing/` - Organized test scripts and runners
  - `scripts/testing/runners/` - Test runners (regression, ERPNext, volunteer portal)
  - `scripts/testing/integration/` - Integration tests
  - `scripts/testing/unit/` - Unit tests by component (board, employee, volunteer, permissions)
- `scripts/debug/` - Debug scripts by component (board, employee, chapter)
- `scripts/validation/` - Feature and migration validation scripts
- `integration_tests/` - Focused component/integration tests (legacy)
- `dev_scripts/` - Development validation scripts (legacy)
- `debug_utils/` - Debug and troubleshooting utilities (legacy)
- `frontend_tests/` - JavaScript/frontend testing files
- See `SCRIPT_ORGANIZATION_COMPLETE.md` for details on the new organized structure

## Site Configuration

**Site Information:**
- **Active Site:** `dev.veganisme.net`
- **Site Location:** `/home/frappe/frappe-bench/sites/dev.veganisme.net/`
- **Bench Directory:** `/home/frappe/frappe-bench/` (restricted access for Claude Code)
- **Deployment Type:** Production server running in cloud environment (not local development)

## Mock Bank Testing Support

The system includes mock banks for automated and manual testing with relaxed IBAN validation:
- **TEST Bank**: `generate_test_iban("TEST")` → Valid IBAN like `NL13TEST0123456789`
- **MOCK Bank**: `generate_test_iban("MOCK")` → Valid IBAN like `NL82MOCK0123456789`
- **DEMO Bank**: `generate_test_iban("DEMO")` → Valid IBAN like `NL93DEMO0123456789`

**Features:**
- Full MOD-97 checksum validation (pass all IBAN validation)
- BIC auto-derivation (TESTNL2A, MOCKNL2A, DEMONL2A)
- Compatible with SEPA mandate creation
- Available in TestDataFactory: `factory.generate_test_iban()`
- Comprehensive test coverage: `python verenigingen/tests/test_mock_banks.py`

## Enhanced Testing Infrastructure (January 2025)

**Phase 1 Testing Infrastructure**: Successfully implemented enhanced testing capabilities including:

**Coverage Reporter with HTML Dashboard:**
```bash
# Generate comprehensive coverage report
python scripts/coverage_report.py

# Generate HTML dashboard
python scripts/coverage_report.py --html

# Coverage with test execution
python scripts/coverage_report.py --with-tests
```

**Enhanced Test Runner CLI:**
```bash
# Run tests with different report types
python verenigingen/tests/test_runner.py --format json
python verenigingen/tests/test_runner.py --format html
python verenigingen/tests/test_runner.py --suite comprehensive
```

**Mock Bank Testing Support:**
- Enhanced IBAN validation for test environments
- TEST, MOCK, and DEMO bank support with proper checksums
- Integration with SEPA mandate testing workflows

**Pre-commit Hook Reliability:**
- Fixed ModuleNotFoundError for 'barista' by updating configuration
- Changed from bench command execution to direct Python scripts
- Enhanced validation layers for field references and event handlers

## Comprehensive Edge Case Test Suites

**Individual Test Suites:**
- Security comprehensive: `python verenigingen/tests/test_security_comprehensive.py`
- Financial edge cases: `python verenigingen/tests/test_financial_integration_edge_cases.py`
- SEPA mandate edge cases: `python verenigingen/tests/test_sepa_mandate_edge_cases.py`
- Payment failure scenarios: `python verenigingen/tests/test_payment_failure_scenarios.py`
- Member status transitions: `python verenigingen/tests/test_member_status_transitions.py`
- Termination workflow edge cases: `python verenigingen/tests/test_termination_workflow_edge_cases.py`
- Performance edge cases: `python verenigingen/tests/test_performance_edge_cases.py`

**Test Suite Categories:**
- All edge case tests: `python verenigingen/tests/test_comprehensive_edge_cases.py all`
- Security only: `python verenigingen/tests/test_comprehensive_edge_cases.py security`
- Financial only: `python verenigingen/tests/test_comprehensive_edge_cases.py financial`
- Business logic only: `python verenigingen/tests/test_comprehensive_edge_cases.py business`
- Performance only: `python verenigingen/tests/test_comprehensive_edge_cases.py performance`
- Environment validation: `python verenigingen/tests/test_comprehensive_edge_cases.py environment`
- Quick smoke tests: `python verenigingen/tests/test_comprehensive_edge_cases.py smoke`

**Testing Infrastructure:**
- Test data factory: `from verenigingen.tests.test_data_factory import TestDataFactory`
- Environment validator: `python verenigingen/tests/test_environment_validator.py`
- Performance monitoring: Enhanced `claude_regression_helper.py` with metrics

## Enhanced Validation System

**Field Reference Validation**: The codebase now includes comprehensive field reference validation that catches deprecated or invalid field references at development time.

**Key Improvements:**
- **Pre-commit Integration**: Automatic validation of field references in all Python files
- **Event Handler Validation**: Special validation for hooks.py and event handler methods
- **System Alert Fixes**: Fixed invalid field references (`compliance_status` → `severity`)
- **Payment History Optimization**: Enhanced event handlers to use atomic methods instead of full rebuilds

**Validation Tools:**
```bash
# Run comprehensive field validation
python scripts/validation/unified_field_validator.py --pre-commit

# Validate event handlers and hooks
python scripts/validation/hooks_event_validator.py

# Check specific file for field issues
python scripts/validation/enhanced_field_validator.py
```

**Recent Fixes Applied:**
- Fixed System Alert doctype field references in monitoring dashboard
- Updated payment history event handlers to use `refresh_financial_history`
- Enhanced pre-commit hooks for better module import handling

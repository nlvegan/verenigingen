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

**CRITICAL NOTE:** The system includes a comprehensive eBoekhouden integration using REST API architecture:

**API Documentation:** https://api.e-boekhouden.nl/swagger/v1/swagger.json

### API Capabilities
- **REST API Features**:
  - Complete transaction history access
  - Full account and master data import
  - Enhanced error handling and performance
  - Modern JSON-based communication
  - Production-ready implementation

### Integration Status
The eBoekhouden integration is production-ready and handles:
- Complete chart of accounts import with intelligent mapping
- All transaction types (Invoices, Payments, Journal Entries)
- Opening balances with automatic party assignment
- Multi-line transactions with complex party relationships
- VAT handling and Dutch tax compliance
- Real-time migration monitoring with detailed progress reporting

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

## Enhanced API Security Framework

### Multi-Layer Security Architecture

**Security Levels:**
- **@critical_api**: Financial operations, data destruction, system configuration (35+ functions)
- **@high_security_api**: Administrative operations, sensitive data access (45+ functions)
- **@standard_api**: Regular business operations, member data access (55+ functions)
- **@public_api**: Guest-accessible endpoints with validation (25+ functions)
- **@development_only_api**: Test utilities, debug functions (blocked in production) (63+ functions)

**Operation Types:**
- **OperationType.FINANCIAL**: Payment processing, banking, financial imports
- **OperationType.ADMIN**: System administration, cache management, user operations
- **OperationType.MEMBER_DATA**: Member information, portal access, personal data
- **OperationType.REPORTING**: Analytics, dashboards, business intelligence
- **OperationType.UTILITY**: Development tools, testing, validation utilities

### Security Framework Files

## Workspace Structure and Navigation

## Architecture Overview

### Core Domain Models

**Member System:**

**Chapter System:**

**Volunteer System:**

**Financial Integration:**

### Key Business Processes

## Permission System

## Testing Infrastructure

**Test Structure:**

**Test Organization:**

## Site Configuration

**Site Information:**
- **Active Site:** `SITE_NAME`
- **Site Location:** `~/frappe-bench/sites/SITE_NAME`
- **Bench Directory:** `~/frappe-bench/`
- **Deployment Type:** Production server running in cloud environment (no localhost access)

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
- Comprehensive test coverage: `python verenigingen/tests/test_mock_banks.py

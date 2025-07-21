# Verenigingen App Architecture Sitemap

## Core Domain Models

### 1. Member System
- **Primary DocType**: `Member` (`verenigingen/doctype/member/`)
- **Key Features**: PaymentMixin, SEPAMandateMixin, ChapterMixin, TerminationMixin
- **Related**: `Membership`, `Membership Type`, `Membership Application`
- **Key Fields**: `customer` (links to ERPNext Customer), `employee` (links to Employee), `total_membership_days`, `cumulative_membership_duration`

### 2. Chapter System
- **Primary DocType**: `Chapter` (`verenigingen/doctype/chapter/`)
- **Managers**: BoardManager, MemberManager, CommunicationManager, VolunteerIntegrationManager
- **Related**: `Chapter Member`, `Chapter Board Member`
- **Key Functions**: Geographic organization, postal code validation

### 3. Volunteer System
- **Primary DocType**: `Volunteer` (`verenigingen/doctype/volunteer/`)
- **Related**: `Volunteer Expense`, `Volunteer Assignment`, `Volunteer Skill`
- **Key Fields**: `employee_id` (links to Employee), `member` (links to Member)
- **Key Functions**: Auto-creates Employee + User on approval

### 4. Financial Integration
- **SEPA**: `SEPA Mandate`, `Direct Debit Batch`, `Payment Retry`
- **ERPNext Integration**: Links to Sales Invoice, Payment Entry, Customer
- **Key Functions**: Dutch BTW compliance, multi-currency donations

## API Layer (`verenigingen/api/`)

### Core APIs
- `membership_application_review.py` - Approval workflow
- `customer_member_link.py` - Customer↔Member navigation
- `sepa_period_duplicate_prevention.py` - SEPA validation
- `generate_test_*.py` - Test data generation

## Business Logic (`verenigingen/utils/`)

### Key Utilities
- `employee_user_link.py` - Employee↔User linking
- `performance_dashboard.py` - System monitoring
- `database_query_analyzer.py` - Performance analysis
- `sepa_notifications.py` - Email notifications
- `application_helpers.py` - Membership application logic

## Monitoring & Admin (`verenigingen/monitoring/`)

### System Health
- `zabbix_integration.py` - External monitoring (22 active subscriptions, stuck jobs, etc.)
- `performance_dashboard.py` - Business metrics, scheduler health
- **Dashboard**: `/system-health-dashboard` - Real-time monitoring

## Templates (`verenigingen/templates/`)

### Portal Pages (`templates/pages/`)
- `member_portal.py` - Member dashboard
- `volunteer/dashboard.py` - Volunteer portal
- `brand_management.py` - Admin brand configuration
- `system_health_dashboard/` - System monitoring UI

### Email Templates (`templates/emails/`)
- `sepa_mandate_*.html` - SEPA notifications
- `payment_*.html` - Payment notifications

## Scheduled Tasks (`verenigingen/hooks.py`)

### Daily Tasks
- `update_all_membership_durations` - Updates membership time counters
- `refresh_all_member_financial_histories` - Syncs payment data
- `update_all_membership_durations` - Recalculates membership days

### Critical Schedulers
- **Last Run**: July 12th (stuck since then)
- **Impact**: Membership duration counters frozen, subscription processing blocked

## Data Relationships

### Core Linkages
```
Member ← customer → Customer (ERPNext)
Member ← member → Volunteer ← employee_id → Employee ← user_id → User
Member ← member → Chapter Member ← parent → Chapter
Volunteer ← volunteer → Chapter Board Member
```

### Key Flows
1. **Membership Application**: Application → Review → Member → Customer → Volunteer (if opted) → Employee → User
2. **Subscription Processing**: Subscription → Process Subscription → Sales Invoice → Payment Entry
3. **Employee Creation**: Volunteer → Employee + User (with proper roles)

## Recent Enhancements (July 2025)

### Monitoring Upgrades
- **System Health Dashboard**: Business metrics, subscription monitoring, scheduler health
- **Zabbix Integration**: 13+ metrics for external monitoring
- **SEPA Notifications**: Fixed template rendering, URL generation

### Employee-User Linking
- **Auto-creation**: Volunteers now get Employee + User accounts
- **Approval Flow**: Membership approval creates employees for volunteers
- **User Roles**: Employee, Volunteer roles assigned automatically

### Customer-Member Navigation
- **JavaScript Enhancement**: Customer forms show Member navigation
- **Dashboard Integration**: Member status indicators, connection links

## Key Configuration Files

### Framework Integration
- `hooks.py` - Event handlers, scheduled tasks, JavaScript includes
- `pyproject.toml` - Python package configuration
- `permissions.py` - Custom permission logic

### Data Management
- `patches.txt` - Database migrations
- `fixtures/` - Default data setup

## Testing Infrastructure

### Test Organization
- `verenigingen/tests/` - Main test suite (26+ files)
- `scripts/testing/` - Organized test runners
- `BaseTestCase` - Enhanced test framework with auto-cleanup

### Key Test Patterns
- Mock bank support (TEST, MOCK, DEMO banks)
- Automatic test data cleanup
- Transaction rollback for isolation

## Common Pitfalls & Solutions

### Field Reference Issues
- **Problem**: Always check DocType .json files for field names
- **Solution**: Use Grep/Read to verify field existence before querying

### Scheduler Issues
- **Problem**: Jobs can get stuck, blocking entire queue
- **Current**: Stuck since July 12th, affecting membership duration updates
- **Monitoring**: System health dashboard tracks stuck jobs

### String Formatting
- **Problem**: Template paths, error messages using old `{}` format
- **Solution**: Use f-strings: `f"template_{name}.html"`

### Permission Levels
- **Problem**: Permlevel restrictions can hide fields unexpectedly
- **Solution**: Use permlevel 0 for most fields, check permission entries

## Navigation Helpers

### Finding Code
- **API Endpoints**: `verenigingen/api/`
- **Business Logic**: `verenigingen/utils/`
- **DocType Controllers**: `verenigingen/doctype/{name}/{name}.py`
- **Templates**: `verenigingen/templates/`

### Common Patterns
- **Whitelisted Functions**: `@frappe.whitelist()`
- **Scheduled Tasks**: Added to `hooks.py` scheduler_events
- **Document Events**: `hooks.py` doc_events
- **Form Scripts**: `public/js/` + `hooks.py` doctype_js

## Update Instructions

**When adding new DocTypes:**
1. Add to appropriate section above
2. Document key fields and relationships
3. Note any special patterns or mixins used

**When adding new APIs:**
1. Add to API Layer section
2. Document purpose and key functions

**When adding new utilities:**
1. Add to Business Logic section
2. Document purpose and integration points

**When adding new scheduled tasks:**
1. Add to Scheduled Tasks section
2. Document frequency and impact

# Security and Permissions System

## Overview

The Security and Permissions System provides access control, data protection, and audit capabilities for the Verenigingen association management platform. This system implements role-based access control, row-level security via permission queries, audit logging, and an API security framework.

## Core Security Architecture

### Role-Based Access Control (RBAC)

#### Role Hierarchy

**Administrative Roles:**

- **Verenigingen System Administrator**: Complete system administration
- **Verenigingen Administrator**: Full association management
- **Verenigingen Manager**: Operational management
- **Verenigingen Staff**: Limited operational access

**Governance Roles:**

- **Verenigingen National Board Member**: National oversight
- **Verenigingen Chapter Board Member**: Chapter board leadership
- **Verenigingen Treasurer**: Financial management
- **Verenigingen Auditor**: Financial audit/compliance (read-only audit access)

**Operational Roles:**

- **Verenigingen Member**: Self-service member access
- **Verenigingen Volunteer**: Volunteer-specific access
- **Verenigingen Team Leader**: Team coordination
- **Verenigingen Webhook User**: System integration access

### Permission Query System (`hooks/permissions.py`)

Row-level security is implemented through permission_query_conditions (SQL WHERE clause generators) and has_permission handlers (document-level checks).

**Permission Query Conditions (15 DocTypes):**

| DocType | Handler |
|---------|---------|
| Member | `permissions.get_member_permission_query` |
| Membership | `permissions.get_membership_permission_query` |
| Employee | `permissions.get_employee_permission_query` |
| Chapter | `chapter.get_chapter_permission_query_conditions` |
| Chapter Member | `permissions.get_chapter_member_permission_query` |
| Team | `team.get_team_permission_query_conditions` |
| Team Member | `permissions.get_team_member_permission_query` |
| Membership Termination Request | `permissions.get_termination_permission_query` |
| Volunteer | `permissions.get_volunteer_permission_query` |
| Address | `permissions.get_address_permission_query` |
| Donor | `permissions.get_donor_permission_query` |
| Membership Dues Schedule | `membership_dues_schedule.get_permission_query_conditions` |
| Project | `project_permissions.get_project_permission_query_conditions` |
| Expense Claim | `permissions.get_expense_claim_permission_query` |
| Event Contact Campaign | `event_contact_campaign.get_permission_query_conditions` |

**Has Permission Handlers (12 DocTypes):**

| DocType | Handler |
|---------|---------|
| Member | `permissions.has_member_permission` |
| Membership | `permissions.has_membership_permission` |
| Membership Termination Request | `permissions.has_membership_termination_request_permission` |
| Address | `permissions.has_address_permission` |
| Donor | `permissions.has_donor_permission` |
| Donation | `permissions.has_donation_permission` |
| Volunteer | `permissions.has_volunteer_permission` |
| Chapter | `chapter.has_chapter_permission` |
| Membership Dues Schedule | `membership_dues_schedule.has_permission` |
| Project | `project_permissions.has_project_permission_via_team` |
| Expense Claim | `permissions.has_expense_claim_permission` |
| Event Contact Campaign | `event_contact_campaign.has_permission` |

### API Security Framework (`utils/security/`)

The security framework lives under `utils/security/` with 19 modules:

#### Security Decorators

Multi-level security classification system:

- `@critical_api`: Financial transactions, system administration (SecurityLevel.CRITICAL)
- `@high_security_api`: Member data access, administrative functions (SecurityLevel.HIGH)
- `@standard_api`: Reporting, standard business operations (SecurityLevel.MEDIUM)
- `@public_api`: Public endpoints, no authentication required (SecurityLevel.PUBLIC)
- `@development_only_api`: Development/debug functions (blocked in production)

**Critical decorator ordering rule:** `@frappe.whitelist()` MUST be the outermost (first/top) decorator. Frappe checks whitelist via object identity in a `set()`. If a security decorator wraps first, the module-level name points to the wrapper, causing "Method Not Allowed" errors.

#### Operation Type Classification (`api_classifier.py`)

- **FINANCIAL**: Payment processing, invoicing, SEPA operations
- **MEMBER_DATA**: Member information access and modification
- **ADMIN**: System administration and settings management
- **REPORTING**: Data export, analytics, and dashboard operations
- **UTILITY**: Health checks, status endpoints, system utilities
- **PUBLIC**: Public information and documentation endpoints

#### Security Modules

| Module | Purpose |
|--------|---------|
| `api_security_framework.py` | Main security facade (1,279 LOC) |
| `authorization_engine.py` | Role and permission checking |
| `authorization.py` | Authorization helpers |
| `authorization_policy.py` | Policy-based authorization |
| `rate_limit_engine.py` | Configurable request rate limiting per security level |
| `input_validator.py` | Input sanitization and validation |
| `enhanced_validation.py` | Extended validation rules |
| `csrf_protection.py` | CSRF token validation (API key exemption) |
| `audit_emitter.py` | Security audit event emission |
| `audit_logging.py` | Audit log storage, daily cleanup, weekly health check |
| `cache_invalidation.py` | User role cache invalidation on User/Role Profile/Has Role changes |
| `client_ip.py` | Client IP extraction |
| `environment_validator.py` | Environment detection (dev/staging/production) |
| `frappe_whitelist_adapter.py` | Adapter for Frappe whitelist integration |
| `security_monitoring.py` | Security health monitoring |
| `self_service_access_controller.py` | Self-service portal access control |
| `types.py` | Security type definitions |
| `api_classifier.py` | API operation type classification |

### Document Event Hooks for Security

From `hooks/doc_events.py`:

**User:**
- `on_update`: Invalidate user role cache, field sync, ensure desk settings
- `after_insert`: Invalidate user role cache, ensure desk settings

**Role Profile:**
- `on_update`/`after_insert`/`on_trash`: Invalidate all user caches

**Has Role:**
- `on_update`/`after_insert`/`on_trash`: Invalidate user cache for affected user

### Scheduled Security Tasks

From `hooks/scheduler.py`:

- **Daily**: `cleanup_old_audit_logs`, `run_daily_checks` (alert manager), `alert_if_auth_issues`
- **Hourly**: `send_security_policy_change_digest` (Critical Operation Rule)
- **Weekly**: `weekly_security_health_check`

### Chapter and Team Security

#### Chapter Access Control

- `services/chapter/chapter_permission_service.py` -- Chapter permission enforcement
- `services/chapter/chapter_board_permissions.py` -- Board-specific permissions
- `services/chapter/chapter_security.py` -- Chapter security operations
- `services/chapter/chapter_role_profile_manager.py` -- Role profile assignment for board members

#### Team Access Control

- `utils/team_role_profile_manager.py` -- Team role profile management
- Permission query: `get_team_permission_query_conditions` and `get_team_member_permission_query`

### Account Creation Security

- `services/member/account/account_creation_manager.py` -- Secure user account creation workflow
- `services/member/account/member_role_service.py` -- Role management for members
- `services/member/account/base_role_profile_manager.py` -- Base class for role profile management
- `services/member/account/user_role_profile_calculator.py` -- Calculates appropriate role profile

### Security Testing

- `tests/backend/security/` -- Security test suite (ANBI security, SEPA validation, volunteer portal, core security, comprehensive)
- `tests/security/` -- Additional security tests (reorganized from Phase 3)
- `scripts/analysis/detailed_security_audit.py` -- Comprehensive security coverage analysis

### Security Validation Hooks

From `.pre-commit-config.yaml`:

- `bandit-focused` -- Security scanning on critical files
- `whitelist-type-safety` -- Validates @whitelist parameter types
- `api-security-validator` -- Checks API security decorators
- `insecure-api-detector` -- Finds unprotected API endpoints

## Key File Locations

- **Security framework**: `utils/security/` (19 modules)
- **Permissions**: `hooks/permissions.py` (15 query conditions + 12 has_permission)
- **Permission module**: `permissions.py` (centralized permission functions)
- **Chapter security**: `services/chapter/chapter_security.py`, `chapter_permission_service.py`, `chapter_board_permissions.py`
- **Account security**: `services/member/account/` (5 modules)
- **Security tests**: `tests/backend/security/`, `tests/security/`
- **Audit script**: `scripts/analysis/detailed_security_audit.py`

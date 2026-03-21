# Verenigingen Documentation

This directory contains documentation for the Verenigingen association management system -- a comprehensive platform for Dutch non-profit organizations built on Frappe/ERPNext.

## Quick Start

### New Users (First Time Setup)

1. **[Getting Started Guide](GETTING_STARTED.md)** - Essential first steps and setup concepts
2. **[Installation Guide](INSTALLATION.md)** - Complete technical installation instructions
3. **[Security Configuration Guide](SECURITY_CONFIGURATION_GUIDE.md)** - Post-installation security configuration
4. **[FAQ & Troubleshooting](FAQ_TROUBLESHOOTING.md)** - Common questions and solutions

### User Guides by Role

- **[Administrator Guide](ADMIN_GUIDE.md)** - Complete system administration and configuration
- **[Role Profiles](ROLE_PROFILES.md)** - Available roles and their permissions
- **[Brand Settings Guide](BRAND_SETTINGS_COMPLETE_GUIDE.md)** - Portal theming and branding

### Technical Documentation

- **[API Documentation](API_DOCUMENTATION.md)** - Complete API reference with examples
- **[Developer Quick Start](DEVELOPER_QUICK_START.md)** - Development setup and codebase overview
- **[Developer Testing Guide](DEVELOPER_TESTING_GUIDE.md)** - Testing standards and best practices
- **[Backup & Recovery](BACKUP_RECOVERY_GUIDE.md)** - Data protection and disaster recovery
- **[Deployment Guide](DEPLOYMENT_GUIDE.md)** - Mollie backend API deployment
- **[Operations Runbook](OPERATIONS_RUNBOOK.md)** - Mollie backend API operations

---

## Documentation Structure

### Core Documentation (top-level)

| Document | Description |
|----------|-------------|
| [GETTING_STARTED.md](GETTING_STARTED.md) | Quick start guide for new installations |
| [INSTALLATION.md](INSTALLATION.md) | Step-by-step installation instructions |
| [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Comprehensive administrator manual |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | Complete API reference with examples |
| [FAQ_TROUBLESHOOTING.md](FAQ_TROUBLESHOOTING.md) | Common issues and solutions |
| [BACKUP_RECOVERY_GUIDE.md](BACKUP_RECOVERY_GUIDE.md) | Backup and disaster recovery |
| [ROLE_PROFILES.md](ROLE_PROFILES.md) | Role profiles and permissions |
| [SECURITY_CONFIGURATION_GUIDE.md](SECURITY_CONFIGURATION_GUIDE.md) | Post-installation security setup |
| [DEVELOPER_QUICK_START.md](DEVELOPER_QUICK_START.md) | Developer onboarding guide |
| [DEVELOPER_TESTING_GUIDE.md](DEVELOPER_TESTING_GUIDE.md) | Testing framework and standards |
| [USER_TYPE_ASSIGNMENT.md](USER_TYPE_ASSIGNMENT.md) | User type configuration |
| [FRAPPE_PERMISSIONS_SYSTEM.md](FRAPPE_PERMISSIONS_SYSTEM.md) | Frappe permissions deep dive |

### Features (`features/`)

Detailed documentation for specific features and capabilities:

| Document | Description |
|----------|-------------|
| [membership-management.md](features/membership-management.md) | Member lifecycle management |
| [donation-management.md](features/donation-management.md) | ANBI-compliant donation system |
| [volunteer-management.md](features/volunteer-management.md) | Volunteer coordination system |
| [chapter-management.md](features/chapter-management.md) | Chapter organization |
| [dutch-compliance.md](features/dutch-compliance.md) | Dutch regulatory compliance (ANBI, GDPR) |
| [MEMBER_MERGE.md](features/MEMBER_MERGE.md) | Member record merging |
| [USER_MEMBER_IMAGE_SYNC.md](features/USER_MEMBER_IMAGE_SYNC.md) | User/member image synchronization |
| [VOLUNTEER_ACTIVITY_ENHANCEMENTS.md](features/VOLUNTEER_ACTIVITY_ENHANCEMENTS.md) | Volunteer activity tracking |

### Subsystems (`subsystems/`)

Architecture and design of major subsystems:

| Document | Description |
|----------|-------------|
| [member-lifecycle-management.md](subsystems/member-lifecycle-management.md) | Member lifecycle subsystem |
| [payment-processing-mollie.md](subsystems/payment-processing-mollie.md) | Mollie payment processing |
| [eboekhouden-integration.md](subsystems/eboekhouden-integration.md) | eBoekhouden accounting sync |
| [chapter-organization.md](subsystems/chapter-organization.md) | Chapter organization subsystem |
| [volunteer-management.md](subsystems/volunteer-management.md) | Volunteer management subsystem |
| [financial-operations.md](subsystems/financial-operations.md) | Financial operations subsystem |
| [security-and-permissions.md](subsystems/security-and-permissions.md) | Security and permissions subsystem |
| [background-processing.md](subsystems/background-processing.md) | Background job processing |
| [test-infrastructure.md](subsystems/test-infrastructure.md) | Test infrastructure subsystem |

### Security (`security/`)

Security documentation and audit reports:

| Document | Description |
|----------|-------------|
| [SECURITY_MODEL_OVERVIEW.md](security/SECURITY_MODEL_OVERVIEW.md) | Security model overview |
| [COMPREHENSIVE_SECURITY_GUIDE.md](security/COMPREHENSIVE_SECURITY_GUIDE.md) | Comprehensive security guide |
| [SECURITY_FRAMEWORK_GUIDE.md](security/SECURITY_FRAMEWORK_GUIDE.md) | Security framework guide |
| [SECURITY_FRAMEWORK_DOCUMENTATION.md](security/SECURITY_FRAMEWORK_DOCUMENTATION.md) | Framework documentation |
| [SECURITY_SETUP.md](security/SECURITY_SETUP.md) | Security setup procedures |
| [SECURITY_MAINTENANCE_GUIDE.md](security/SECURITY_MAINTENANCE_GUIDE.md) | Security maintenance |
| [ROLE_PROFILE_INTEGRATION_GUIDE.md](security/ROLE_PROFILE_INTEGRATION_GUIDE.md) | Role profile integration |
| [DEVELOPER_WORKFLOW_GUIDE.md](security/DEVELOPER_WORKFLOW_GUIDE.md) | Developer security workflow |
| [PERMISSION_BYPASS_ANALYSIS.md](security/PERMISSION_BYPASS_ANALYSIS.md) | Permission bypass analysis |
| [IGNORE_PERMISSIONS_AUDIT_REPORT.md](security/IGNORE_PERMISSIONS_AUDIT_REPORT.md) | Ignore permissions audit |
| [sepa-security-implementation.md](security/sepa-security-implementation.md) | SEPA security implementation |
| [SEPA_REDIS_CONFIGURATION.md](security/SEPA_REDIS_CONFIGURATION.md) | SEPA Redis configuration |
| [security-monitoring-dashboard-guide.md](security/security-monitoring-dashboard-guide.md) | Monitoring dashboard guide |
| [cors_implementation_summary.md](security/cors_implementation_summary.md) | CORS implementation |

### Development (`development/`)

Developer reference documentation:

| Document | Description |
|----------|-------------|
| [ERROR_HANDLING_CONVENTIONS.md](development/ERROR_HANDLING_CONVENTIONS.md) | Error handling conventions |
| [TYPING_CONVENTIONS.md](development/TYPING_CONVENTIONS.md) | Type annotation conventions |
| [SERVICE_INFRASTRUCTURE_USAGE_GUIDE.md](development/SERVICE_INFRASTRUCTURE_USAGE_GUIDE.md) | Service infrastructure guide |
| [OPERATION_RESULT_MIGRATION_EXAMPLE.md](development/OPERATION_RESULT_MIGRATION_EXAMPLE.md) | OperationResult migration example |

### Patterns (`patterns/`)

Established code patterns and conventions:

| Document | Description |
|----------|-------------|
| [ADVISORY_LOCK_PATTERN.md](patterns/ADVISORY_LOCK_PATTERN.md) | Advisory lock pattern |
| [ERROR_HANDLING_PATTERNS.md](patterns/ERROR_HANDLING_PATTERNS.md) | Error handling patterns |
| [SYSTEM_UPDATE_PATTERN.md](patterns/SYSTEM_UPDATE_PATTERN.md) | System update bypass pattern |

### Architecture (`architecture/`)

Architecture documents and design decisions:

| Document | Description |
|----------|-------------|
| [README.md](architecture/README.md) | Architecture overview |
| [ACCOUNT_CREATION_SERVICE.md](architecture/ACCOUNT_CREATION_SERVICE.md) | Account creation service |
| [EMAIL_SERVICE_ARCHITECTURE.md](architecture/EMAIL_SERVICE_ARCHITECTURE.md) | Email service architecture |
| [WEBHOOK_SECURITY_ARCHITECTURE.md](architecture/WEBHOOK_SECURITY_ARCHITECTURE.md) | Webhook security |
| [SERVICE_LAYER_DESIGN_FOR_N_PLUS_ONE_OPTIMIZATION.md](architecture/SERVICE_LAYER_DESIGN_FOR_N_PLUS_ONE_OPTIMIZATION.md) | N+1 query optimization |
| [SERVICE_REFACTORING_SPECIFICATION.md](architecture/SERVICE_REFACTORING_SPECIFICATION.md) | Service refactoring spec |
| [service_layer_migration_guide.md](architecture/service_layer_migration_guide.md) | Service layer migration |
| [PSP_INTEGRATION_CONSOLIDATION_PLAN.md](architecture/PSP_INTEGRATION_CONSOLIDATION_PLAN.md) | PSP integration consolidation |
| [WORKSPACE_HEALTH_MIGRATION_SOLUTION.md](architecture/WORKSPACE_HEALTH_MIGRATION_SOLUTION.md) | Workspace health migration |

### Integration Guides (top-level)

| Document | Description |
|----------|-------------|
| [MOLLIE_INTEGRATION_USER_GUIDE.md](MOLLIE_INTEGRATION_USER_GUIDE.md) | Mollie payment integration |
| [MOLLIE_BACKEND_API_DOCUMENTATION.md](MOLLIE_BACKEND_API_DOCUMENTATION.md) | Mollie backend API reference |
| [EBOEKHOUDEN_INTEGRATION_COMPREHENSIVE.md](EBOEKHOUDEN_INTEGRATION_COMPREHENSIVE.md) | eBoekhouden integration guide |
| [ING_CHECKOUT_USER_GUIDE.md](ING_CHECKOUT_USER_GUIDE.md) | ING Checkout integration |
| [PONTO_USER_GUIDE.md](PONTO_USER_GUIDE.md) | Ponto banking integration |
| [KASCOMMISSIE_SETUP.md](KASCOMMISSIE_SETUP.md) | Kascommissie (audit committee) setup |

### eBoekhouden (`eboekhouden/`)

eBoekhouden-specific documentation:

| Document | Description |
|----------|-------------|
| [README.md](eboekhouden/README.md) | eBoekhouden integration overview |
| [api/api-reference.md](eboekhouden/api/api-reference.md) | eBoekhouden API reference |
| [implementation/configuration.md](eboekhouden/implementation/configuration.md) | Configuration guide |
| [implementation/opening-balances.md](eboekhouden/implementation/opening-balances.md) | Opening balances setup |
| [implementation/stock-accounts.md](eboekhouden/implementation/stock-accounts.md) | Stock accounts configuration |
| [maintenance/troubleshooting.md](eboekhouden/maintenance/troubleshooting.md) | Troubleshooting guide |
| [migration/migration-guide.md](eboekhouden/migration/migration-guide.md) | Migration guide |

### Payments (`payments/`)

| Document | Description |
|----------|-------------|
| [MOLLIE_CONFIGURATION_SERVICE.md](payments/MOLLIE_CONFIGURATION_SERVICE.md) | Mollie configuration service |

### Monitoring (`monitoring/`)

| Document | Description |
|----------|-------------|
| [README.md](monitoring/README.md) | Monitoring overview |
| [MONITORING_SETUP.md](monitoring/MONITORING_SETUP.md) | Monitoring setup guide |
| [OPERATIONS_MANUAL.md](monitoring/OPERATIONS_MANUAL.md) | Operations manual |
| [ZABBIX_INTEGRATION.md](monitoring/ZABBIX_INTEGRATION.md) | Zabbix integration |

### Guides (`guides/`)

Practical how-to guides:

| Document | Description |
|----------|-------------|
| [donation-campaigns.md](guides/donation-campaigns.md) | Donation campaign setup |
| [NEWSLETTER_USAGE_GUIDE.md](guides/NEWSLETTER_USAGE_GUIDE.md) | Newsletter system usage |

### Runbooks (`runbooks/`)

| Document | Description |
|----------|-------------|
| [SEPA_OPERATIONS.md](runbooks/SEPA_OPERATIONS.md) | SEPA operations runbook |

### Policies (`policies/`)

| Document | Description |
|----------|-------------|
| [CONTROLLER_GROWTH_PREVENTION.md](policies/CONTROLLER_GROWTH_PREVENTION.md) | Controller growth prevention policy |

### Services (`services/`)

| Document | Description |
|----------|-------------|
| [ERROR_HANDLING_STANDARDS.md](services/ERROR_HANDLING_STANDARDS.md) | Service error handling standards |

### Audits & Reports (`audits/`, `analysis/`, `reports/`)

| Document | Description |
|----------|-------------|
| [audits/codebase-dry-solid-kiss-audit-2026-02-23.md](audits/codebase-dry-solid-kiss-audit-2026-02-23.md) | DRY/SOLID/KISS audit |
| [audits/membership-application-audit-2026-02-05.md](audits/membership-application-audit-2026-02-05.md) | Membership application audit |
| [audits/test-suite-audit-2026-03-03.md](audits/test-suite-audit-2026-03-03.md) | Test suite audit |
| [audits/utils-directory-audit-2026-02-27.md](audits/utils-directory-audit-2026-02-27.md) | Utils directory audit |
| [analysis/MEMBERSHIP_APPROVAL_INVENTORY.md](analysis/MEMBERSHIP_APPROVAL_INVENTORY.md) | Membership approval inventory |
| [analysis/BANK_TRANSACTION_MISSING_ANALYSIS.md](analysis/BANK_TRANSACTION_MISSING_ANALYSIS.md) | Bank transaction analysis |

---

## Quick Reference

### For New Installations

1. Start with **[Getting Started Guide](GETTING_STARTED.md)**
2. Follow **[Installation Guide](INSTALLATION.md)**
3. Configure using **[Administrator Guide](ADMIN_GUIDE.md)**
4. Set up security with **[Security Configuration Guide](SECURITY_CONFIGURATION_GUIDE.md)**

### For Daily Operations

- **Administrators**: Refer to [Administrator Guide](ADMIN_GUIDE.md)
- **Issues**: Check [FAQ & Troubleshooting](FAQ_TROUBLESHOOTING.md)
- **SEPA**: Follow [SEPA Operations Runbook](runbooks/SEPA_OPERATIONS.md)
- **Monitoring**: See [Operations Manual](monitoring/OPERATIONS_MANUAL.md)

### For Developers

- **Getting Started**: [Developer Quick Start](DEVELOPER_QUICK_START.md)
- **Testing**: [Developer Testing Guide](DEVELOPER_TESTING_GUIDE.md)
- **API Integration**: [API Documentation](API_DOCUMENTATION.md)
- **Patterns**: See [patterns/](patterns/) and [development/](development/) directories
- **Architecture**: See [architecture/](architecture/) directory

### For Support

- **Self-Help**: [FAQ & Troubleshooting](FAQ_TROUBLESHOOTING.md)
- **Security Issues**: [Security documentation](security/)
- **Feature Questions**: See [features/](features/) documentation

# Verenigingen Security Framework Documentation

**Version**: 2.1
**Last Updated**: March 2026
**Status**: Production Ready

## Overview

The Verenigingen Security Framework provides security across all domains for Dutch association management operations. This documentation suite covers network security, authentication, data protection, integration security, and operational security.

## Documentation Index

The 16 files in this directory are organized by audience and purpose.

### Core Guides

| File | Audience | Description |
|------|----------|-------------|
| [COMPREHENSIVE_SECURITY_GUIDE.md](COMPREHENSIVE_SECURITY_GUIDE.md) | All users | Full security framework covering network, auth, data, integration, and operational security. **Start here.** |
| [SECURITY_MODEL_OVERVIEW.md](SECURITY_MODEL_OVERVIEW.md) | Stakeholders, management | Business-focused security philosophy, risk assessment, compliance, and ROI analysis |
| [SECURITY_FRAMEWORK_GUIDE.md](SECURITY_FRAMEWORK_GUIDE.md) | Developers, sysadmins | Technical implementation: API Security Framework, Critical Operation Rules, monitoring |
| [SECURITY_FRAMEWORK_DOCUMENTATION.md](SECURITY_FRAMEWORK_DOCUMENTATION.md) | Developers | `frappe.get_roles()` vulnerabilities and production-ready security wrappers |

### Developer Guides

| File | Audience | Description |
|------|----------|-------------|
| [DEVELOPER_WORKFLOW_GUIDE.md](DEVELOPER_WORKFLOW_GUIDE.md) | Developers | Day-to-day workflows: API security decorators, testing, code review, deployment |
| [SECURITY_SETUP.md](SECURITY_SETUP.md) | Developers, sysadmins | Automatic security configuration during app installation (CSRF, etc.) |
| [SECURITY_MAINTENANCE_GUIDE.md](SECURITY_MAINTENANCE_GUIDE.md) | Developers, sysadmins | Ongoing security management procedures for the API framework |

### Role and Permission Guides

| File | Audience | Description |
|------|----------|-------------|
| [ROLE_PROFILE_INTEGRATION_GUIDE.md](ROLE_PROFILE_INTEGRATION_GUIDE.md) | Developers | Role profile to security level mapping for the API Security Framework (11 profiles) |
| [IGNORE_PERMISSIONS_AUDIT_REPORT.md](IGNORE_PERMISSIONS_AUDIT_REPORT.md) | Security teams | Audit of `ignore_permissions=True` usage across the codebase |
| [PERMISSION_BYPASS_ANALYSIS.md](PERMISSION_BYPASS_ANALYSIS.md) | Security teams | Analysis of permission bypass flags in payment optimization code |

### Domain-Specific Security

| File | Audience | Description |
|------|----------|-------------|
| [cors_implementation_summary.md](cors_implementation_summary.md) | Developers | Critical Operation Rules (CORs) implementation summary (2,445 rules) |
| [SEPA_REDIS_CONFIGURATION.md](SEPA_REDIS_CONFIGURATION.md) | Sysadmins, DevOps | Redis lock/idempotency/TTL configuration for SEPA payment processing |
| [sepa-security-implementation.md](sepa-security-implementation.md) | Developers | SEPA billing security hardening: attack vectors and financial data protection |
| [security-monitoring-dashboard-guide.md](security-monitoring-dashboard-guide.md) | Sysadmins | Implementation guide for the enhanced security monitoring dashboard |

### Meta

| File | Audience | Description |
|------|----------|-------------|
| [DOCUMENTATION_COMPLETE.md](DOCUMENTATION_COMPLETE.md) | Internal | Completion record for the v2.0 documentation effort (September 2025) |
| [README.md](README.md) | All users | This index file |

## Quick Start

- **Everyone**: Start with [COMPREHENSIVE_SECURITY_GUIDE.md](COMPREHENSIVE_SECURITY_GUIDE.md)
- **Developers adding API endpoints**: See [DEVELOPER_WORKFLOW_GUIDE.md](DEVELOPER_WORKFLOW_GUIDE.md) for decorator usage (`@critical_api`, `@development_only_api`, etc.)
- **Understanding role-based access**: See [ROLE_PROFILE_INTEGRATION_GUIDE.md](ROLE_PROFILE_INTEGRATION_GUIDE.md)
- **SEPA/payment security**: See [SEPA_REDIS_CONFIGURATION.md](SEPA_REDIS_CONFIGURATION.md) and [sepa-security-implementation.md](sepa-security-implementation.md)

## Key Implementation References

- **Permission hooks**: `verenigingen/hooks/permissions.py` (defines `permission_query_conditions` and `has_permission` dicts)
- **API security decorators**: `verenigingen/utils/security/api_security_framework.py` (`@critical_api`, `@development_only_api`, etc.)
- **Authorization policy**: `verenigingen/utils/security/authorization_policy.py` (`ROLE_PROFILE_SECURITY_MAPPING`)
- **Role profile fixtures**: `verenigingen/fixtures/role_profile.json` (11 profiles)

# Security and Permissions System

## Overview

The Security and Permissions System provides enterprise-grade access control, data protection, and audit capabilities for the Verenigingen association management platform. This system implements role-based access control, row-level security, comprehensive audit logging, and API security frameworks.

## Core Security Architecture

### Role-Based Access Control (RBAC)

#### Role Hierarchy
Comprehensive role structure with 13 defined role profiles:

**Administrative Roles:**
- **Verenigingen System Administrator**: Complete system administration
- **Verenigingen Administrator**: Full association management
- **Verenigingen Manager**: Operational management
- **Verenigingen Staff**: Limited operational access

**Governance Roles:**
- **Verenigingen National Board Member**: National oversight
- **Verenigingen Board Member**: Chapter board leadership
- **Verenigingen Treasurer**: Financial management
- **Verenigingen Kascommissie**: Financial audit/compliance

**Operational Roles:**
- **Verenigingen Member**: Self-service member access
- **Verenigingen Volunteer**: Volunteer-specific access
- **Verenigingen Team Leader**: Team coordination
- **Verenigingen Auditor**: Read-only audit access
- **Verenigingen Webhook User**: System integration access

#### Permission Query Implementation
Limited row-level security implementation for specific DocTypes:

**Implemented Permission Queries:**
- **Chapter**: Published chapters visible to all users; full access for administrators
- **Team**: Team membership and chapter affiliation (referenced in hooks)

### API Security Framework

#### Multi-Level Security Decorators
Comprehensive API protection using a 5-tier security classification system:

**Security Level Decorators:**
- `@critical_api`: Financial transactions, system administration (SecurityLevel.CRITICAL)
- `@high_security_api`: Member data access, administrative functions (SecurityLevel.HIGH)
- `@standard_api`: Reporting, standard business operations (SecurityLevel.MEDIUM)
- `@public_api`: Public endpoints, no authentication required (SecurityLevel.PUBLIC)
- `@development_only_api`: Development/debug functions (blocked in production)

#### Operation Type Classification
API operations classified by business context for appropriate security measures:

**Operation Types:**
- **FINANCIAL**: Payment processing, invoicing, SEPA operations
- **MEMBER_DATA**: Member information access and modification
- **ADMIN**: System administration and settings management
- **REPORTING**: Data export, analytics, and dashboard operations
- **UTILITY**: Health checks, status endpoints, system utilities
- **PUBLIC**: Public information and documentation endpoints

#### Environment-Aware Security
Production isolation with automatic blocking of development functions:

**Environment Controls:**
- **Production Environment**: Development-only APIs automatically blocked
- **Staging Environment**: Full API access with enhanced monitoring
- **Development Environment**: All APIs available with debug capabilities

### Data Protection and Privacy

#### Personal Data Protection
GDPR/AVG compliance features are implemented through:

**Privacy Features:**
- **Role-based access control**: Restricts data access to authorized users
- **Audit logging**: API security framework provides comprehensive audit trails
- **Data validation**: Input sanitization and validation in security decorators
- **Member data security**: `@high_security_api` protection for member operations

### Audit and Compliance

#### Security Audit Logging
Audit logging is implemented through the API security framework:

**Audit Features:**
- **API Access Logs**: Logged through security decorators with configurable audit levels
- **Security Events**: CSRF validation, rate limiting, and authorization failures
- **Critical Operations**: Enhanced logging for `@critical_api` operations
- **Background Jobs**: Audit trail for secure operations processing

#### Security Monitoring
Basic security monitoring through:

**Monitoring Features:**
- **Security Framework Status**: Environment detection and configuration validation
- **API Protection Coverage**: Automated security coverage analysis
- **Permission Validation**: Role profile and permission checking

### Authentication and Session Management

The security system builds upon Frappe's standard authentication with:

**Enhanced Security Features:**
- **Account Creation Workflow**: Secure account creation through Account Creation Request system
- **Role Profile Integration**: Comprehensive role profile system for access control
- **API Authentication**: API key and session-based authentication support
- **Environment-Aware Security**: Different security levels for development/production

### Chapter and Team Security

#### Chapter Access Control
Basic chapter access control is implemented through:

**Chapter Security:**
- **Permission Query**: Published chapters visible to all users via `get_chapter_permission_query_conditions`
- **Administrative Access**: System managers and administrators have full access
- **Member Context**: Chapter membership tracked through Chapter Member DocType

#### Team Access Control
Team security is referenced in hooks configuration:

**Team Security:**
- **Permission Query**: Implemented via `get_team_permission_query_conditions`
- **Team Membership**: Access control based on team assignment patterns

### Financial Data Security

#### Payment Information Protection
Financial data security is implemented through:

**Financial Security:**
- **Critical API Protection**: All financial operations protected with `@critical_api`
- **Role-Based Access**: Financial operations require administrative roles
- **SEPA Operations**: Secure SEPA batch processing with audit trails
- **Payment Processing**: Protected payment history and reconciliation operations

### Volunteer and HR Security

Volunteer security is handled through the standard role-based access control system:

**Volunteer Security:**
- **Role-Based Access**: Volunteer data protected through role assignments
- **Account Integration**: Account Creation Manager creates Employee records for volunteers
- **Expense System Access**: Employee roles enable expense reporting functionality

### API Security Implementation

#### Security Features in Practice

The API security framework provides:

**Request Protection:**
- **Rate Limiting**: Configurable request limits per security level via rate limiter
- **Input Validation**: Automatic sanitization of input parameters
- **Request Size Limits**: Configurable maximum request sizes per security level
- **CSRF Protection**: Token validation for state-changing operations (with API key exemption)

**Environment Controls:**
- **Development Isolation**: `@development_only_api` blocked in production
- **Environment Detection**: Automatic environment detection and appropriate security
- **Permission Validation**: Role profile and individual role checking

#### Background Job Security

Background job processing includes:

**Security Features:**
- **Account Creation Jobs**: Secure background processing for user account creation
- **Audit Trail**: Job processing logged through security framework
- **Error Handling**: Proper error handling and retry logic for failed operations
- **Permission Context**: Background jobs maintain appropriate user context

### Compliance and Regulatory Adherence

The security system supports Dutch regulatory compliance through:

**Privacy Compliance:**
- **Role-Based Data Access**: Restricts personal data access to authorized users
- **Audit Logging**: Security framework provides audit trails for data access
- **Data Protection**: Input validation and sanitization protects against data breaches

**Financial Compliance:**
- **SEPA Operations**: Secure SEPA batch processing with proper audit trails
- **Financial Data Protection**: Critical API protection for all financial operations
- **Access Control**: Role-based restrictions on financial data access

### Security Management and Testing

#### Security Configuration
Security configuration is managed through:

**Configuration Features:**
- **Security Profiles**: Pre-defined security levels with configurable parameters
- **Environment Detection**: Automatic development/staging/production environment detection
- **Role Profile System**: Comprehensive role-based access control configuration

#### Security Testing and Validation
Security validation is provided through:

**Testing Features:**
- **Automated Security Audit**: `scripts/analysis/detailed_security_audit.py` provides comprehensive coverage analysis
- **API Protection Validation**: Automatic detection of unprotected API endpoints
- **Permission Testing**: Role profile and permission validation in test suite

## Current Security Status

**Security Coverage Metrics** (as of 2025-09-16):
- **93.8% API Protection Rate** (150/160 files protected)
- **90.5% High-Risk Coverage** (19/21 critical files secured)
- **100% Critical Function Coverage** (all exposed API endpoints protected)

**Remaining Security Gaps:**
- 2 high-risk files lack protection: `payment_sync_system.py`, `payment_audit.py`
- These files contain **0 `@frappe.whitelist()` functions**, so pose no actual security risk
- 8 low-risk utility files are unprotected but contain no exposed API endpoints

**Security Audit Validation:**
```bash
# Run comprehensive security audit
python scripts/analysis/detailed_security_audit.py

# Generate detailed security coverage report
# Report saved to: detailed_security_audit_report.md
```

**Security Framework Features:**
- **Complete Framework Detection**: Recognizes all security decorators (@critical_api, @high_security_api, @standard_api, @public_api, @development_only_api)
- **Risk Classification**: Automatically categorizes files by risk level (HIGH/MEDIUM/LOW)
- **Coverage Metrics**: Accurate API protection percentages
- **Gap Analysis**: Identifies unprotected endpoints requiring security
- **False Positive Filtering**: Excludes non-API files and archived code

This security and permissions system provides enterprise-grade protection while maintaining usability and compliance with Dutch regulatory requirements for association management.

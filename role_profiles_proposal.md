# Role Profiles Proposal for Verenigingen Association Management System

## Overview

This document proposes a comprehensive set of role profiles for the Verenigingen association management system. These profiles will simplify user onboarding and ensure appropriate access control based on user responsibilities.

## Existing Roles Analysis

### Current System Roles:
- **Verenigingen Administrator** - Full system access
- **Verenigingen Manager** - Management-level access
- **Verenigingen Staff** - Staff-level access
- **Verenigingen Member** - Basic member access
- **Chapter Board Member** - Chapter management access
- **Volunteer** - Volunteer access
- **Governance Auditor** - Audit and compliance access (referenced in hooks.py)

### ERPNext Modules Available:
- Accounts (Financial Management)
- Projects (Project Management)
- CRM (Customer Relationship Management)
- Stock (Inventory - probably not needed)
- Selling (Sales - limited use)
- Buying (Purchasing - limited use)
- Support (Ticketing/Support)
- Assets (Asset Management)
- Communication
- Quality Management
- Portal

## Proposed Role Profiles

### 1. **Regular Member Profile** (`verenigingen_member`)
**Purpose**: Basic access for regular association members
**Target Users**: All registered members

**Roles Included**:
- Verenigingen Member
- Employee (for basic self-service)

**Module Access**:
- Verenigingen (Read-only for own data)
- Portal (Full access)
- Communication (Limited - own communications)

**Key Permissions**:
- View own member record
- View own membership details
- View own payment history
- Submit contact requests
- Access member portal

### 2. **Volunteer Profile** (`verenigingen_volunteer`)
**Purpose**: Access for active volunteers
**Target Users**: Members who volunteer for activities

**Roles Included**:
- Verenigingen Member
- Volunteer
- Employee

**Module Access**:
- Verenigingen (Volunteer sections)
- Projects (View/participate in volunteer projects)
- Portal (Full access)
- Communication (Team communications)
- Support (Submit support tickets)

**Key Permissions**:
- All member permissions
- View volunteer assignments
- Submit volunteer expenses
- View team information
- Participate in volunteer activities
- Track volunteer hours

### 3. **Team Leader Profile** (`verenigingen_team_leader`)
**Purpose**: Management access for team leaders
**Target Users**: Volunteers who lead teams

**Roles Included**:
- Verenigingen Member
- Volunteer
- Employee
- Projects User

**Module Access**:
- Verenigingen (Team management)
- Projects (Create/manage team projects)
- Communication (Full team access)
- Support (Handle team tickets)
- Portal

**Key Permissions**:
- All volunteer permissions
- Manage team members
- Create volunteer assignments
- Approve volunteer expenses (for team)
- Create and manage team projects
- View team performance metrics

### 4. **Chapter Board Member Profile** (`verenigingen_chapter_board`)
**Purpose**: Chapter-level governance and management
**Target Users**: Elected chapter board members

**Roles Included**:
- Verenigingen Member
- Chapter Board Member
- Employee
- Projects User

**Module Access**:
- Verenigingen (Chapter management)
- Projects (Chapter projects)
- Communication (Chapter-wide)
- Portal
- CRM (Limited - member relations)

**Key Permissions**:
- Manage chapter members
- View chapter financial overview (read-only)
- Create chapter events
- Manage chapter teams
- Approve chapter-level decisions
- View member statistics for chapter

### 5. **Financial Administrator Profile** (`verenigingen_treasurer`)
**Purpose**: Financial management and reporting
**Target Users**: Treasurers and financial administrators

**Roles Included**:
- Verenigingen Member
- Verenigingen Staff
- Accounts User
- Employee

**Module Access**:
- Verenigingen (Financial sections)
- Accounts (Limited - relevant transactions)
- Banking (SEPA and payment processing)
- Portal

**Key Permissions**:
- View all financial reports
- Manage donations
- Process SEPA batches
- View payment history
- Generate financial reports
- Manage membership fees
- Handle payment reconciliation
- NO direct GL entry permissions

### 6. **Chapter Administrator Profile** (`verenigingen_chapter_admin`)
**Purpose**: Administrative management at chapter level
**Target Users**: Chapter secretaries and administrators

**Roles Included**:
- Verenigingen Member
- Verenigingen Staff
- Chapter Board Member
- Employee

**Module Access**:
- Verenigingen (Full chapter access)
- Communication (Chapter-wide)
- CRM (Member management)
- Projects (Chapter administration)
- Portal

**Key Permissions**:
- Manage chapter member records
- Process membership applications
- Handle membership amendments
- Manage chapter communications
- Create and manage events
- Generate chapter reports

### 7. **Association Manager Profile** (`verenigingen_manager`)
**Purpose**: Organization-wide management
**Target Users**: National board members and senior managers

**Roles Included**:
- Verenigingen Manager
- Verenigingen Member
- Employee
- Projects Manager
- Accounts Manager

**Module Access**:
- Verenigingen (Full access except system settings)
- Accounts (Full read, limited write)
- Projects (Full access)
- CRM (Full access)
- Communication (Full access)
- Support (Management access)
- Assets (If managing association assets)
- Portal

**Key Permissions**:
- All chapter administrator permissions
- Cross-chapter visibility
- Approve major decisions
- View all financial data
- Manage volunteer programs
- Handle termination requests
- Strategic planning access

### 8. **System Administrator Profile** (`verenigingen_system_admin`)
**Purpose**: Full system administration
**Target Users**: IT administrators and system managers

**Roles Included**:
- Verenigingen Administrator
- System Manager
- All relevant module managers

**Module Access**:
- All modules (Full access)

**Key Permissions**:
- Complete system access
- User management
- System configuration
- Integration management
- Security settings
- Backup and restore

### 9. **Governance Auditor Profile** (`verenigingen_auditor`)
**Purpose**: Compliance and audit functions
**Target Users**: Internal auditors and compliance officers

**Roles Included**:
- Governance Auditor
- Verenigingen Member
- Employee

**Module Access**:
- Verenigingen (Read-only access to all)
- Accounts (Read-only)
- Communication (Audit trails)
- Quality Management (If applicable)

**Key Permissions**:
- Read-only access to all records
- Generate audit reports
- View termination processes
- Access compliance dashboards
- Review financial transactions
- NO modification permissions

## Implementation Notes

1. **Module Restrictions**:
   - Stock, Manufacturing, Buying modules should be hidden for most profiles
   - Selling module only for donation/membership fee processing

2. **Progressive Access**:
   - Users can have multiple profiles
   - Higher profiles include lower profile permissions

3. **Security Considerations**:
   - Financial roles strictly separated
   - Audit roles are read-only
   - Personal data access limited by chapter/team

4. **Portal Access**:
   - All profiles include portal access
   - Member portal is default home for non-admin users
   - Volunteer portal for volunteer-enabled profiles

5. **Communication**:
   - Scoped by role and organizational unit
   - Members only see own communications
   - Leaders see team/chapter communications

## Next Steps

1. Create JSON fixtures for each role profile
2. Test permission inheritance
3. Create onboarding documentation
4. Implement role assignment workflows

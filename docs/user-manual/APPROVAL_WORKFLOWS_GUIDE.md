# Approval Workflows and Thresholds Guide

## Overview

The Verenigingen application includes robust approval workflows for various types of requests including volunteer expenses, membership terminations, fee amendments, and SEPA payment batches. This guide documents the complete approval process, thresholds, role-based permissions, and user procedures.

## Table of Contents

- [Approval Workflows Overview](#approval-workflows-overview)
- [Volunteer Expense Approvals](#volunteer-expense-approvals)
- [Membership Termination Approvals](#membership-termination-approvals)
- [Fee Amendment Approvals](#fee-amendment-approvals)
- [SEPA Batch Approvals](#sepa-batch-approvals)
- [Role-Based Permissions](#role-based-permissions)
- [User Guide: Submitting Requests](#user-guide-submitting-requests)
- [User Guide: Processing Approvals](#user-guide-processing-approvals)
- [Escalation and Timeline Procedures](#escalation-and-timeline-procedures)
- [Troubleshooting](#troubleshooting)

## Approval Workflows Overview

### Workflow Types

The system implements four main approval workflows:

1. **Volunteer Expense Approval** - Amount-based approval with role permissions
2. **Membership Termination Request** - Type-based approval with secondary review
3. **Fee Amendment Request** - Auto-approval with manual override capability
4. **SEPA Batch Approval** - Risk-based validation with multi-level review

### Common Approval States

All workflows use consistent status progression:

- **Draft** - Initial state, not yet submitted
- **Pending Approval** / **Pending** - Awaiting review
- **Approved** - Approved for execution
- **Rejected** - Denied with reason
- **Executed** / **Applied** - Completed/implemented
- **Cancelled** - Withdrawn by submitter

## Volunteer Expense Approvals

### Approval Thresholds

The expense approval system uses amount-based thresholds with role-specific limits:

#### Chapter-Level Approvals

| Role | Expense Limit | Approval Authority |
|------|---------------|-------------------|
| Chapter Head | €1,000 | Full approval authority for chapter expenses |
| Treasurer | €500 | Financial approval authority |
| Secretary | €0 | Cannot approve expenses |
| Other Board Members | €0 | Cannot approve expenses (unless specified otherwise) |

#### Team-Level Approvals

| Role | Expense Limit | Approval Authority |
|------|---------------|-------------------|
| Team Leader | €500 | Can approve team expenses up to limit |
| Team Member | €0 | Cannot approve expenses |

#### Permission Levels by Amount

| Amount Range | Required Permission Level | Who Can Approve |
|--------------|-------------------------|-----------------|
| €0 - €100 | Basic | Team Leaders, Chapter Treasurers, Chapter Heads |
| €101 - €500 | Financial | Chapter Treasurers, Chapter Heads |
| €501 - €1,000 | Management | Chapter Heads |
| €1,000+ | Admin | System Managers, Verenigingen Administrators |

### Approval Process Flow

1. **Volunteer submits expense** with receipt and details
2. **System validates** expense against organization access
3. **Automatic routing** to appropriate approver based on:
   - Organization type (Chapter/Team)
   - Expense amount
   - Approver availability and permissions
4. **Approver reviews** and makes decision
5. **System processes** approval or sends for higher authority if needed
6. **Notification sent** to volunteer with outcome

### Escalation Rules

- **Team expenses >€500** automatically escalate to chapter approval
- **Chapter expenses >€1,000** require administrator approval
- **Rejected expenses** can be resubmitted with modifications
- **Pending expenses >7 days** generate reminder notifications

## Membership Termination Approvals

### Termination Types and Approval Requirements

#### Standard Terminations (No Secondary Approval)

- **Voluntary** - Member requests termination
- **Non-payment** - Due to overdue payments
- **Deceased** - Death notification received

**Process**: Direct approval → 30-day grace period → Execution

#### Disciplinary Terminations (Requires Secondary Approval)

- **Policy Violation** - Member violated organization policies
- **Disciplinary Action** - Formal disciplinary procedure
- **Expulsion** - Complete expulsion from organization

**Process**: Initial review → Secondary approver required → Board documentation → Execution

### Approval Authority

| Termination Type | Primary Approver | Secondary Approver | Documentation Required |
|------------------|------------------|-------------------|----------------------|
| Voluntary | Chapter Board Member | Not required | Reason |
| Non-payment | Chapter Treasurer | Not required | Payment history |
| Deceased | Chapter Board Member | Not required | Death certificate |
| Policy Violation | Chapter Head | Board Member | Incident documentation |
| Disciplinary Action | Chapter Head | System Manager | Full investigation report |
| Expulsion | System Manager | Verenigingen Administrator | Complete case file |

### Execution Timeline

- **Voluntary/Non-payment/Deceased**: 30-day grace period from approval
- **Disciplinary**: Immediate execution upon approval
- **System Updates**: Automatic processing of SEPA mandates, board positions, user accounts

## Fee Amendment Approvals

### Auto-Approval Conditions

The system automatically approves fee changes under these conditions:

#### Member Self-Service Auto-Approval

1. **Fee increases by current member** up to €1,000 maximum
2. **Small adjustments** within 5% of current amount
3. **Within frequency limits** (maximum 2 adjustments per 365 days)

#### Auto-Approval Settings (Configurable)

- `auto_approve_fee_increases`: Default enabled
- `auto_approve_member_requests`: Default enabled
- `max_auto_approve_amount`: Default €1,000

### Manual Approval Required

Fee changes require manual approval for:

- **Fee decreases** (any amount)
- **Amounts exceeding** auto-approval limits
- **Non-member requests** (staff-initiated changes)
- **Frequency limit exceeded** (>2 changes per year)
- **Membership type changes**
- **Billing interval changes**

### Amendment Types

| Amendment Type | Auto-Approval Eligible | Manual Review Required |
|----------------|------------------------|----------------------|
| Fee Change (increase by member) | ✓ (up to €1,000) | If exceeds limit |
| Fee Change (decrease) | ✗ | Always |
| Membership Type Change | ✗ | Always |
| Billing Interval Change | ✗ | Always |
| Plan Change | ✗ | Always |
| Suspension | ✗ | Always |
| Reactivation | ✗ | Always |

### Approval Authority

| Role | Approval Authority |
|------|-------------------|
| System Manager | All amendments |
| Verenigingen Manager | All amendments |
| Verenigingen Staff | Read-only access |

## SEPA Batch Approvals

### Batch Approval Process

SEPA Direct Debit batches require approval before submission to banking systems:

#### Risk Assessment Factors

- **Total batch amount** and transaction count
- **First-time SEPA mandates** (FRST sequence type)
- **Failed payment retry attempts**
- **Customer payment history**

#### Approval Workflow States

1. **Generated** - Batch created, ready for review
2. **Pending Approval** - Awaiting approval decision
3. **Approved** - Ready for SEPA file generation
4. **Submitted** - Sent to bank for processing
5. **Failed** - Batch rejected or processing failed

### Approval Authority

| Role | Batch Approval Authority |
|------|-------------------------|
| System Manager | All batches |
| Verenigingen Manager | All batches |
| Verenigingen Treasurer | Standard batches |

### Validation Requirements

Before approval, batches must pass:

- **SEPA mandate validation** (active, properly signed)
- **Account validation** (valid IBAN, active accounts)
- **Amount verification** (matches invoices/schedules)
- **Sequence type verification** (FRST/RCUR appropriate)

## Role-Based Permissions

### System-Level Roles

#### System Manager
- **Full system access** to all approval workflows
- **Override capability** for any approval decision
- **Emergency termination** authority
- **SEPA batch** approval for any amount

#### Verenigingen Administrator
- **Application-wide** approval authority
- **Expense approval** unlimited amounts
- **Termination approval** including disciplinary
- **Fee amendment** approval authority

### Chapter-Level Roles

#### Chapter Head
- **Expense approval** up to €1,000
- **Member management** including terminations
- **Board management** capabilities
- **Financial oversight** within chapter

#### Treasurer
- **Expense approval** up to €500
- **Financial review** capabilities
- **SEPA batch** standard approval
- **Fee amendment** review authority

#### Secretary
- **Member data** management
- **Administrative** functions
- **No financial** approval authority

### Team-Level Roles

#### Team Leader
- **Team expense approval** up to €500
- **Team member** management
- **Activity coordination**
- **Escalation to chapter** for higher amounts

## User Guide: Submitting Requests

### Volunteer Expense Submission

1. **Navigate to Expenses** in volunteer portal
2. **Click "New Expense"**
3. **Complete required fields**:
   - Expense date (cannot be future)
   - Category (from predefined list)
   - Description (clear, specific)
   - Amount (must be positive)
   - Organization (Chapter/Team/National)
   - Receipt attachment (recommended)
4. **Submit for approval**
5. **Track status** in expense list

### Membership Termination Request

1. **Access termination dashboard** (board members only)
2. **Select member** for termination
3. **Choose termination type** and provide reason
4. **Add required documentation** for disciplinary cases
5. **Submit for approval**
6. **Monitor approval workflow**

### Fee Amendment Request

1. **Member portal**: Navigate to "Membership Settings"
2. **Request amendment** with new amount/terms
3. **Provide justification** for change
4. **Submit request**
5. **Await auto-approval** or manual review

### SEPA Batch Review

1. **Financial dashboard** access required
2. **Review generated batches**
3. **Validate transactions** and amounts
4. **Check mandate status** for all entries
5. **Approve or reject** with notes

## User Guide: Processing Approvals

### For Approvers: General Process

1. **Notification received** via email/system alert
2. **Access approval dashboard** or direct link
3. **Review request details** thoroughly
4. **Verify supporting documentation**
5. **Make approval decision** with comments
6. **Submit approval/rejection**

### Expense Approval Checklist

- [ ] **Receipt attached** and readable
- [ ] **Amount reasonable** for expense type
- [ ] **Volunteer authorized** for organization
- [ ] **Description clear** and business-related
- [ ] **Within approval authority** limits
- [ ] **Organization budget** considerations

### Termination Approval Checklist

- [ ] **Documentation complete** per type requirements
- [ ] **Member status** verified active
- [ ] **No conflicting processes** (pending applications, etc.)
- [ ] **Grace period** appropriate for type
- [ ] **System impact** understood (mandates, positions, etc.)
- [ ] **Secondary approval** obtained if required

### Amendment Approval Checklist

- [ ] **Business justification** provided
- [ ] **Membership status** allows changes
- [ ] **No conflicting amendments** pending
- [ ] **Amount within** reasonable bounds
- [ ] **Effective date** appropriate
- [ ] **Impact on billing** understood

### SEPA Batch Approval Checklist

- [ ] **All mandates valid** and active
- [ ] **Amounts match** invoices/schedules
- [ ] **No duplicate transactions**
- [ ] **Bank account** details current
- [ ] **Sequence types** appropriate
- [ ] **Risk assessment** acceptable

## Escalation and Timeline Procedures

### Standard Processing Times

| Approval Type | Target Time | Maximum Time | Escalation Trigger |
|---------------|-------------|--------------|-------------------|
| Volunteer Expense | 48 hours | 7 days | After 3 days |
| Membership Termination | 5 days | 14 days | After 7 days |
| Fee Amendment (manual) | 3 days | 10 days | After 5 days |
| SEPA Batch | 24 hours | 72 hours | After 48 hours |

### Escalation Procedures

#### Automatic Escalations

1. **Overdue reminders** sent to approvers
2. **Supervisor notification** after escalation trigger
3. **Alternative approver** assignment if available
4. **Administrator oversight** for critical delays

#### Manual Escalation

Users can manually escalate by:
- **Contacting chapter head** directly
- **Using support channels** in system
- **Emailing administration** for urgent cases

### Holiday and Absence Handling

- **Delegate approval authority** to backup approvers
- **Automatic routing** to available approvers
- **Extended timelines** during holiday periods
- **Emergency contact** procedures documented

## Troubleshooting

### Common Issues and Solutions

#### "No Approver Available"

**Cause**: No users have appropriate role/permissions
**Solution**:
1. Check chapter board member assignments
2. Verify role permissions in system
3. Contact system administrator

#### "Approval Request Stuck"

**Cause**: Approver not responding, system error
**Solution**:
1. Check approver availability
2. Use escalation process
3. Contact technical support if system issue

#### "Auto-Approval Failed"

**Cause**: Doesn't meet auto-approval criteria
**Solution**:
1. Review auto-approval conditions
2. Modify request to meet criteria, or
3. Accept manual approval process

#### "SEPA Batch Rejected"

**Cause**: Validation errors, mandate issues
**Solution**:
1. Review validation error details
2. Fix mandate/account issues
3. Regenerate batch after fixes

### Getting Help

1. **System Help**: Available in each module
2. **Chapter Support**: Contact your chapter administrators
3. **Technical Support**: Use built-in support channels
4. **Documentation**: Reference this guide and related docs

### Contact Information

- **Chapter Issues**: Contact your chapter head or treasurer
- **System Issues**: Use in-system support or email administrators
- **Urgent Approvals**: Follow emergency escalation procedures
- **Training**: Request approval workflow training sessions

## Related Documentation

- [APPROVAL_THRESHOLDS_REFERENCE.md](APPROVAL_THRESHOLDS_REFERENCE.md) - Quick reference tables
- [APPROVER_RESPONSIBILITIES.md](APPROVER_RESPONSIBILITIES.md) - Role-specific guidance
- [BUSINESS_RULES_REFERENCE.md](BUSINESS_RULES_REFERENCE.md) - System configuration rules
- [ERROR_RECOVERY_GUIDE.md](../troubleshooting/ERROR_RECOVERY_GUIDE.md) - Error resolution procedures

---

*This documentation reflects the current approval workflow implementation. For system configuration changes or role permission modifications, contact your system administrator.*

# Business Rules Reference
## System Limits, Validations, and Constraints

This reference guide documents all business rules, validation requirements, and system constraints that govern how the association management system operates. Understanding these rules helps you work within system parameters and avoid validation errors.

## Table of Contents

1. [Membership Business Rules](#membership-business-rules)
2. [Financial and Payment Rules](#financial-and-payment-rules)
3. [SEPA Direct Debit Rules](#sepa-direct-debit-rules)
4. [Volunteer and Chapter Rules](#volunteer-and-chapter-rules)
5. [Termination and Governance Rules](#termination-and-governance-rules)
6. [Validation Rules by DocType](#validation-rules-by-doctype)
7. [System Configuration Limits](#system-configuration-limits)
8. [Data Quality Rules](#data-quality-rules)
9. [Security and Permission Rules](#security-and-permission-rules)
10. [Integration and API Rules](#integration-and-api-rules)

---

## Membership Business Rules

### Membership Types and Billing

#### Minimum Fee Requirements
- **Minimum amount**: Each membership type must define a minimum allowable fee
- **Template enforcement**: Dues schedule templates cannot set amounts below the membership type minimum
- **Individual overrides**: Members can pay above the minimum but never below
- **Business rationale**: Ensures financial sustainability and fairness

#### Billing Period Rules
- **Available periods**: Daily, Monthly, Quarterly, Biannual, Annual, Lifetime, Custom
- **1-Year minimum enforcement**: Most membership types enforce a 1-year minimum period (configurable)
- **Custom periods**: Custom billing periods must be specified in months (1-60 months)
- **Proration rules**: New memberships are prorated from start date to next billing cycle

#### Membership Duration and Status
- **Minimum membership period**: New members must commit to at least the billing period duration
- **Grace period limits**: Grace periods between 1-180 days (configurable, default: 30 days)
- **Status change rules**:
  - Active members can move to Grace Period or Terminated
  - Grace Period members can return to Active or move to Terminated
  - Terminated members cannot return to Active without creating new membership
  - Deceased and Banned members cannot change status

### Member Lifecycle Rules

#### New Member Processing
- **Required fields**: Full name, birth date, email OR postal address
- **Age requirements**: No specific age restrictions (handled at membership type level)
- **Duplicate prevention**: System checks for existing members with same email or full name + birth date
- **Chapter assignment**: Automatic assignment based on postal code matching

#### Membership Renewal
- **Renewal timing**: Renewal reminders sent at 30, 15, 7, and 1 day before expiry
- **Auto-renewal eligibility**: Requires active SEPA mandate and member consent
- **Grace period application**: Automatically applied for overdue payments (if enabled)
- **Renewal fee changes**: New membership period can have different fee if approved

#### Data Quality Requirements
- **Email validation**: Must be valid email format if provided
- **IBAN validation**: Must pass standard IBAN check-digit validation
- **BSN validation**: Dutch social security numbers validated with 11-check algorithm
- **Address validation**: Postal codes validated against known formats
- **Phone validation**: International format validation using libphonenumber

---

## Financial and Payment Rules

### Fee Setting and Changes

#### Fee Limits and Multipliers
- **Maximum fee multiplier**: Members can pay up to 10x the base membership fee (configurable)
- **Maximum reasonable dues**: Upper limit of €10,000 per year to prevent data entry errors
- **Rate change limits**: Maximum 200% change between consecutive invoices (configurable)
- **Income-based calculator**: Suggests 0.5% of monthly net income (configurable)

#### Amendment Request Processing
- **Approval requirements**: Fee increases above certain thresholds require board approval
- **Effective date rules**: Changes typically effective from next billing period
- **Retroactive changes**: Limited retroactive changes only for error corrections
- **Documentation**: All fee changes must include reason and supporting documentation

### Payment Processing Rules

#### Invoice Generation
- **Due date calculation**: Standard payment terms of 30 days from invoice date
- **Tax application**: Automatic BTW exemption for membership fees and donations (if configured)
- **Coverage period**: Each invoice must specify coverage start and end dates
- **Amount validation**: Invoice amounts must match dues schedule amounts

#### Payment Allocation and Matching
- **Allocation priority**: Payments allocated to oldest outstanding invoices first
- **Partial payment handling**: Partial payments marked as such, remainder stays outstanding
- **Overpayment handling**: Overpayments create credit balance for future invoices
- **Currency consistency**: All payments must match invoice currency

#### Payment History Accuracy
- **Real-time updates**: Payment history updated within 5 minutes of payment submission
- **Validation checks**: Daily validation of payment history accuracy
- **Reconciliation requirements**: Monthly reconciliation of payment records with bank statements
- **Audit trail**: Complete audit trail maintained for all payment transactions

---

## SEPA Direct Debit Rules

### Mandate Management

#### Mandate Validation Requirements
- **IBAN validation**: All IBANs must pass SEPA standard validation
- **Creditor ID**: Must be valid SEPA creditor identifier format (NL##ZZZ############)
- **Mandate ID**: Unique identifier following configured naming pattern
- **Signature requirements**: Digital or physical signature required for mandate activation

#### Mandate Lifecycle Rules
- **Activation period**: New mandates become active immediately upon validation
- **Expiry handling**: Mandates expire after 36 months of non-use (SEPA standard)
- **Cancellation rules**: Members can cancel mandates at any time with immediate effect
- **Replacement mandates**: New mandates automatically supersede old ones for same account

### Batch Processing Rules

#### Batch Creation Limits
- **Maximum batch size**: 20 invoices per batch (configurable)
- **Maximum batch amount**: €4,000 per batch (configurable)
- **Minimum batch size**: 5 invoices to ensure processing efficiency
- **Risk distribution**: High-risk invoices distributed across multiple batches

#### Batch Timing and Scheduling
- **Collection timing**: Minimum 5 business days between batch creation and collection date
- **Weekend/holiday handling**: Collection dates automatically moved to next business day
- **Batch creation days**: Configurable days of month for automatic batch creation
- **Processing cutoffs**: Batches must be submitted by 3:00 PM for same-day processing

#### Payment Return Handling
- **Automatic retry**: Failed payments automatically retried according to retry schedule
- **Retry limits**: Maximum 3 retry attempts per payment
- **Return code processing**: Different handling based on specific return codes
- **Member notification**: Automatic notification of payment failures and retries

### Risk Management Rules

#### Collection Risk Assessment
- **Payment history**: Members with 3+ failed payments in 6 months marked high-risk
- **Amount limits**: Single collections above €100 require additional validation
- **Frequency limits**: Maximum 2 collections per month per member
- **Mandate age**: Mandates older than 24 months without use require revalidation

#### Compliance and Audit
- **SEPA compliance**: All processes must comply with SEPA Direct Debit rulebook
- **Audit logging**: Complete audit trail for all SEPA operations
- **Error reporting**: Automatic reporting of processing errors to finance team
- **Regular validation**: Monthly validation of all active mandates

---

## Volunteer and Chapter Rules

### Volunteer Eligibility and Requirements

#### Age and Status Requirements
- **Minimum age**: 16 years old for volunteer positions
- **Member status**: Must be active member to become volunteer
- **Background checks**: Required for certain volunteer roles (configurable)
- **Training requirements**: Role-specific training requirements (configurable)

#### Volunteer Assignment Rules
- **Chapter alignment**: Volunteers typically assigned to their membership chapter
- **Cross-chapter assignments**: Require approval from both chapters
- **Role limitations**: Maximum number of simultaneous roles per volunteer (configurable)
- **Term limits**: Maximum term length for board positions (configurable)

### Chapter Management Rules

#### Chapter Assignment Logic
- **Postal code matching**: Automatic assignment based on postal code ranges
- **Manual override**: Staff can manually assign members to different chapters
- **Single chapter rule**: Members can belong to only one chapter at a time
- **Transfer processing**: Chapter transfers require cleanup of previous assignments

#### Board Position Rules
- **Eligibility requirements**: Board members must be volunteers and active members
- **Term limits**: Maximum term length enforced (typically 2-3 years)
- **Succession rules**: Automatic position handover when terms expire
- **Voting rights**: Board positions automatically grant voting rights in relevant contexts

### Team and Role Management

#### Team Assignment Rules
- **Team membership limits**: Maximum team size enforced per team type
- **Role hierarchy**: Team roles have defined hierarchy and permissions
- **Assignment approval**: Team leader approval required for new team members
- **Cross-team membership**: Volunteers can belong to multiple teams

#### Responsibility and Permission Rules
- **Responsibility assignment**: Each team role has defined responsibilities
- **Permission inheritance**: Team roles inherit base permissions plus role-specific rights
- **Delegation rules**: Team leaders can delegate certain responsibilities
- **Approval thresholds**: Spending approval limits tied to volunteer roles

---

## Termination and Governance Rules

### Termination Request Processing

#### Termination Types and Requirements
- **Voluntary termination**: Member can request termination at any time
- **Administrative termination**: Requires administrative approval
- **Disciplinary termination**: Requires documentation and secondary approver
- **Automatic termination**: After grace period expiry (if configured)

#### Approval Requirements by Type
- **Policy Violation**: Requires secondary approver and documentation
- **Disciplinary Action**: Requires secondary approver and full documentation
- **Expulsion**: Requires secondary approver and governance team notification
- **Administrative**: Can be processed by staff without additional approval

#### Secondary Approver Validation
- **Required roles**: System Manager, Verenigingen Administrator, or National Board Member
- **Verification process**: System validates approver permissions before processing
- **Documentation requirements**: All disciplinary terminations must include supporting documentation
- **Timeline requirements**: Disciplinary terminations must be processed within configured timeframe

### Compliance and Audit Rules

#### Grace Period Management
- **Default length**: 30 days (configurable: 1-180 days)
- **Automatic application**: Can be configured to apply automatically for overdue payments
- **Notification timeline**: Warnings sent at 7, 3, and 1 day before expiry
- **Extension rules**: Grace periods can be extended once per member per year

#### Termination Compliance Validation
- **Required documentation**: All termination reasons must be documented
- **Appeal rights**: Members have right to appeal within configured period
- **Data retention**: Terminated member data retained according to legal requirements
- **Financial settlement**: All outstanding amounts must be settled before termination completion

### Governance and Oversight

#### Board Member Requirements
- **Active membership**: Board members must maintain active membership status
- **Term limits**: Configurable term limits enforced automatically
- **Conflict of interest**: System tracks and reports potential conflicts
- **Meeting participation**: Attendance tracking for governance requirements

#### Audit and Reporting Requirements
- **Termination reports**: Weekly reports generated for governance review
- **Compliance monitoring**: Automated compliance checks for termination processes
- **Exception reporting**: Automatic reporting of terminations outside normal parameters
- **Appeals tracking**: Complete tracking of appeal processes and outcomes

---

## Validation Rules by DocType

### Member DocType Validations

#### Required Fields
- **Full name**: Must be provided and non-empty
- **Birth date**: Must be valid date and not in future
- **Email OR address**: At least one contact method required
- **Membership type**: Must reference valid, active membership type

#### Field Format Validations
- **Email format**: Standard email format validation if provided
- **IBAN format**: SEPA-compliant IBAN validation if provided
- **Phone format**: International format validation if provided
- **BSN format**: Dutch social security number validation if provided

#### Business Logic Validations
- **Age consistency**: Birth date must be consistent with volunteer age requirements
- **Duplicate checking**: System prevents duplicate members with same email
- **Status transitions**: Only valid status transitions allowed
- **Address consistency**: Postal code must match country selection

### Membership Dues Schedule Validations

#### Required Configuration
- **Member reference**: Must reference valid, active member
- **Membership type**: Must reference valid membership type
- **Amount**: Must be at or above membership type minimum
- **Billing frequency**: Must be valid frequency option

#### Amount and Timing Validations
- **Minimum amount**: Cannot be below membership type minimum
- **Maximum amount**: Cannot exceed reasonable maximum (€10,000 default)
- **Start date**: Cannot be in the past (except for corrections)
- **End date**: Must be after start date if specified

#### Template Validations
- **Template consistency**: Must match membership type requirements
- **Coverage calculation**: Coverage periods must not overlap
- **Proration accuracy**: Prorated amounts must be calculated correctly
- **Invoice generation**: Must generate invoices on schedule

### Payment Entry Validations

#### Financial Validations
- **Amount consistency**: Payment amount must match referenced invoice amounts
- **Currency matching**: Payment currency must match invoice currency
- **Allocation totals**: Allocated amounts cannot exceed payment total
- **Date validity**: Payment date cannot be in future

#### Reference Validations
- **Party validation**: Payment party must be valid customer or supplier
- **Account validation**: Payment accounts must be valid and active
- **Mode validation**: Payment mode must be configured and available
- **Reference integrity**: All referenced documents must exist and be accessible

### SEPA Mandate Validations

#### IBAN and Banking Validations
- **IBAN format**: Must pass IBAN mod-97 check digit validation
- **BIC format**: Must be valid BIC format if provided (optional for EU)
- **Bank country**: Must be SEPA-participating country
- **Account holder**: Must match member name (with reasonable variation)

#### Mandate Lifecycle Validations
- **Unique mandate ID**: Mandate IDs must be unique within organization
- **Signature validation**: Digital signature must be valid if provided
- **Activation requirements**: All required fields must be completed
- **Cancellation rules**: Only active mandates can be cancelled

---

## System Configuration Limits

### Verenigingen Settings Limits

#### Grace Period Configuration
- **Minimum grace period**: 1 day
- **Maximum grace period**: 180 days
- **Notification timing**: 1-30 days before grace period expiry
- **Auto-application**: Grace period must be less than default period

#### Fee and Payment Limits
- **Maximum fee multiplier**: 1-50x base fee (default: 10x)
- **Maximum reasonable dues**: €100-€50,000 per year (default: €10,000)
- **Rate change percentage**: 50%-500% (default: 200%)
- **Income percentage rate**: 0.1%-5.0% (default: 0.5%)

#### ANBI (Tax Status) Configuration
- **Minimum reportable amount**: €1-€2,000 (default: €500)
- **Organization status**: Must have valid ANBI status to use ANBI features
- **Donor type defaults**: Individual or Organization
- **Restricted donation handling**: Requires proper account configuration

### SEPA Batch Processing Limits

#### Batch Size and Timing
- **Maximum invoices per batch**: 5-50 (default: 20)
- **Maximum amount per batch**: €1,000-€25,000 (default: €4,000)
- **Minimum batch size**: 1-10 invoices (default: 5)
- **Collection lead time**: 1-14 business days (default: 5)

#### Scheduling Configuration
- **Batch creation days**: 1-5 days per month allowed
- **Processing windows**: Must be within business hours (6 AM - 6 PM)
- **Holiday handling**: System respects configured holiday calendar
- **Weekend processing**: Automatically moves to next business day

### User and Permission Limits

#### Role Assignment Rules
- **Maximum roles per user**: 10 roles maximum
- **Role inheritance**: Roles inherit permissions from parent roles
- **Chapter restrictions**: Chapter-specific roles limited to chapter members
- **Time-based permissions**: Some roles have automatic expiry dates

#### API and Integration Limits
- **API call limits**: Rate limiting based on user role and endpoint
- **Concurrent sessions**: Maximum concurrent sessions per user
- **Data export limits**: Maximum records per export based on user permissions
- **Bulk operation limits**: Maximum records per bulk operation

---

## Data Quality Rules

### Data Entry Standards

#### Name and Address Formatting
- **Name capitalization**: Names automatically formatted to proper case
- **Address standardization**: Addresses formatted according to postal service standards
- **Country-specific rules**: Different validation rules for different countries
- **Duplicate detection**: Fuzzy matching for potential duplicate entries

#### Financial Data Accuracy
- **Amount precision**: Financial amounts limited to 2 decimal places
- **Currency consistency**: All related financial records must use same currency
- **Exchange rate handling**: Historical exchange rates used for currency conversion
- **Rounding rules**: Consistent rounding rules applied throughout system

### Data Validation and Cleanup

#### Automated Data Quality Checks
- **Daily validation**: Automated checks for data inconsistencies
- **Reference integrity**: Validation that all references point to valid records
- **Format compliance**: Regular validation of email, phone, IBAN formats
- **Completeness checks**: Identification of records missing required information

#### Manual Data Correction Procedures
- **Correction approval**: Data corrections above certain thresholds require approval
- **Audit trail**: All data corrections logged with user, timestamp, and reason
- **Bulk corrections**: Special procedures for bulk data corrections
- **Validation after correction**: Automatic re-validation after manual corrections

---

## Security and Permission Rules

### Access Control Rules

#### User Authentication Requirements
- **Password complexity**: Minimum complexity requirements for user passwords
- **Session timeout**: Automatic logout after period of inactivity
- **Multi-factor authentication**: Required for administrative roles (if configured)
- **Account lockout**: Automatic lockout after failed login attempts

#### Permission Inheritance and Restrictions
- **Role-based permissions**: Permissions granted based on assigned roles
- **Document-level security**: Access restricted based on document ownership and sharing
- **Field-level permissions**: Some fields restricted based on user role
- **Chapter-based restrictions**: Chapter members can only access their chapter data

### Data Privacy and Protection

#### Personal Data Handling
- **Consent tracking**: System tracks consent for data processing
- **Data minimization**: Only necessary data collected and stored
- **Right to erasure**: Procedures for data deletion upon request
- **Data portability**: Ability to export member data in standard formats

#### Financial Data Security
- **Payment data encryption**: All payment data encrypted at rest and in transit
- **PCI DSS compliance**: Credit card data handling follows PCI standards
- **Bank data protection**: IBAN and banking information specially protected
- **Audit logging**: All access to financial data logged and monitored

---

## Integration and API Rules

### eBoekhouden Integration Rules

#### Data Synchronization
- **Daily synchronization**: Account data synchronized daily with eBoekhouden
- **Mapping validation**: All account mappings validated before use
- **Error handling**: Integration errors logged and reported to administrators
- **Fallback procedures**: Manual procedures available when integration fails

#### Transaction Processing
- **Duplicate prevention**: System prevents duplicate transaction creation
- **Amount validation**: Transaction amounts validated against source documents
- **Date consistency**: Transaction dates must be consistent across systems
- **Reference integrity**: All references must be valid in both systems

### API Security and Limits

#### Rate Limiting and Throttling
- **Request limits**: Maximum API requests per minute based on user role
- **Bandwidth limits**: Maximum data transfer per API call
- **Concurrent connection limits**: Maximum simultaneous API connections
- **IP restrictions**: API access can be restricted by IP address

#### API Validation Rules
- **Input sanitization**: All API inputs sanitized and validated
- **Output formatting**: API outputs formatted consistently
- **Error responses**: Standardized error response formats
- **Authentication tokens**: API tokens expire and require regular renewal

---

## Quick Reference Tables

### Key Limits Summary

| Setting | Minimum | Maximum | Default | Configurable |
|---------|---------|---------|---------|--------------|
| Grace Period Days | 1 | 180 | 30 | Yes |
| Fee Multiplier | 1 | 50 | 10 | Yes |
| Maximum Reasonable Dues | €100 | €50,000 | €10,000 | Yes |
| Rate Change Percentage | 50% | 500% | 200% | Yes |
| SEPA Batch Size | 5 | 50 | 20 | Yes |
| SEPA Batch Amount | €1,000 | €25,000 | €4,000 | Yes |
| Collection Lead Time | 1 day | 14 days | 5 days | Yes |

### Status Transition Matrix

| From Status | To Status | Allowed | Approval Required | Notes |
|------------|-----------|---------|------------------|--------|
| Active | Grace Period | Yes | No | Automatic for overdue payments |
| Active | Terminated | Yes | Yes | Requires termination request |
| Grace Period | Active | Yes | No | Payment brings member current |
| Grace Period | Terminated | Yes | No | After grace period expiry |
| Terminated | Active | No | N/A | Must create new membership |
| Deceased | Any | No | N/A | Permanent status |
| Banned | Any | No | N/A | Requires system administrator |

### Validation Error Quick Reference

| Error Type | Common Causes | Resolution Steps |
|------------|---------------|------------------|
| "Amount below minimum" | Fee set below membership type minimum | Check membership type minimum amount |
| "Invalid IBAN format" | Incorrect IBAN entry | Verify IBAN with bank or member |
| "Mandate not found" | Missing or inactive SEPA mandate | Create new mandate or reactivate existing |
| "Duplicate member" | Similar name/email already exists | Review existing records or force creation |
| "Invalid date range" | End date before start date | Correct date range in schedule or plan |
| "Permission denied" | User lacks required permissions | Contact administrator for role assignment |

---

This business rules reference provides comprehensive information about all system constraints and validation requirements. For specific technical implementation details, consult the developer documentation or contact your system administrator.

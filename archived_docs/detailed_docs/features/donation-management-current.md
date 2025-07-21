# Donation Management (Current State)

## Overview

The Verenigingen app includes a donation management module that provides basic donation tracking and processing capabilities. While the system has foundational ANBI awareness, it currently lacks several features required for full Dutch tax compliance.

## Current Features

### Basic Donation Tracking

#### Donation Records
- **Donor Information**: Link to donor records
- **Amount Tracking**: Donation amounts in EUR
- **Date Recording**: Donation and payment dates
- **Payment Methods**: Bank transfer, SEPA, cash/check support
- **Purpose Categories**: General, Campaign, Chapter, or Specific Goal donations
- **Status Management**: Track donation and payment status

#### Donor Management
- **Donor Profiles**: Basic donor information storage
- **Donation History**: Track all donations per donor
- **Email Communications**: Donor email addresses for receipts
- **Customer Conversion**: Automatic ERPNext customer creation

### Payment Processing

#### Payment Integration
- **Sales Invoice Creation**: Automatic invoice generation for donations
- **Payment Entry**: Payment tracking when donations are received
- **Bank Reference**: Manual reference tracking for bank transfers
- **SEPA Mandate**: Basic linking to SEPA mandates (if available)

#### Accounting Features
- **Tax Exemption**: Automatic nonprofit tax exemption on invoices
- **GL Integration**: Basic general ledger entry creation
- **Account Mapping**: Simple account assignment for donations
- **Earmarking**: Basic fund allocation between accounts

### ANBI Awareness (Limited)

#### Basic ANBI Fields
- **Agreement Number**: Text field for ANBI agreement numbers
- **Agreement Date**: Date field for agreement tracking
- **Reportable Flag**: Checkbox for Belastingdienst reporting
- **Automatic Flagging**: Donations > €500 marked as reportable

#### ANBI Functions
- **Number Generator**: Sequential ANBI-YYYY-NNN format
- **Report Data**: Basic data compilation (incomplete)
- **Email Template**: ANBI receipt template (PDF generation missing)
- **Date Range Queries**: Retrieve donations by period

### Communication Features

#### Email Notifications
- **Confirmation Emails**: Basic donation acknowledgment
- **Payment Confirmations**: Notification when marked as paid
- **Template System**: Uses central email template manager
- **Manual Sending**: Triggered by status changes

## Current Limitations

### ANBI Compliance Gaps

#### Critical Missing Features
- ❌ **No BSN/RSIN Storage**: Cannot store tax identification numbers
- ❌ **No Periodic Agreements**: No support for 5-year donation commitments
- ❌ **No PDF Receipts**: Function exists but not implemented
- ❌ **No Compliant Exports**: Cannot generate Belastingdienst format
- ❌ **No Agreement Documents**: Cannot generate/store formal agreements

#### Data Security Concerns
- ❌ **No Encryption**: No special handling for sensitive data
- ❌ **Limited Access Control**: Basic role-based permissions only
- ❌ **No Audit Trail**: No specific logging for ANBI operations
- ❌ **No Data Masking**: Full data visible to authorized users

### Functional Limitations

#### Donation Processing
- ⚠️ **Manual Matching**: Bank payments require manual matching
- ⚠️ **Limited Automation**: Most processes require manual intervention
- ⚠️ **Basic Validation**: Minimal data validation rules
- ⚠️ **No Bulk Operations**: Limited bulk processing capabilities

#### Reporting Capabilities
- ⚠️ **Basic Reports**: Simple donation lists and summaries
- ⚠️ **No Analytics**: Limited donor analytics or insights
- ⚠️ **Manual Exports**: Data export requires manual processing
- ⚠️ **No Dashboards**: No visual reporting dashboards

## Workaround Solutions

### For ANBI Organizations

Until full ANBI compliance is implemented, organizations can:

1. **Manual BSN Tracking**: Use custom fields or external spreadsheets
2. **Agreement Management**: Store agreements as attachments
3. **Receipt Generation**: Use external tools for PDF receipts
4. **Report Preparation**: Export data and format manually
5. **Compliance Tracking**: Maintain separate compliance records

### Best Practices with Current System

1. **Data Entry Standards**
   - Always fill in ANBI agreement fields when applicable
   - Use consistent donation categorization
   - Maintain accurate donor contact information
   - Document payment methods clearly

2. **Process Management**
   - Regular donation reconciliation with bank statements
   - Timely email confirmations to donors
   - Periodic data exports for backup
   - Clear documentation of manual processes

3. **Compliance Preparation**
   - Keep external records of BSN/RSIN if needed
   - Maintain paper agreements for periodic donations
   - Regular consultation with tax advisors
   - Prepare for future system upgrades

## Suitable Use Cases

### Currently Supported
✅ Basic donation tracking and acknowledgment
✅ Simple donation campaigns
✅ General fund donations
✅ Basic donor management
✅ Integration with ERPNext accounting

### Not Yet Supported
❌ Full ANBI tax compliance
❌ Periodic donation agreements
❌ Automated tax receipt generation
❌ Belastingdienst reporting
❌ Complex donation analytics

## Future Development

The donation module is scheduled for significant enhancements to achieve full ANBI compliance. See the [ANBI Compliance Roadmap](../development/anbi-compliance-roadmap.md) for detailed development plans.

### Planned Enhancements
- Secure BSN/RSIN storage with encryption
- Complete periodic donation agreement system
- Automated PDF receipt generation
- Belastingdienst-compliant export formats
- Enhanced security and audit trails

## Getting Started

Despite current limitations, the donation module can still provide value:

1. **Configure Basics**: Set up donation types and categories
2. **Create Donors**: Build your donor database
3. **Process Donations**: Track donations and payments
4. **Send Confirmations**: Use email templates for donor communication
5. **Monitor Compliance**: Track ANBI requirements manually for now

For organizations requiring full ANBI compliance immediately, consider supplementing the system with external tools until the planned enhancements are implemented.

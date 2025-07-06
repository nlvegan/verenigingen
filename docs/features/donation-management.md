# Donation Management

The Verenigingen app provides comprehensive donation management with full Dutch ANBI compliance, multi-purpose donation tracking, and complete accounting integration.

## Overview

The donation system handles all aspects of charitable giving, from initial donation collection through tax receipt generation, with specialized support for Dutch ANBI (Algemeen Nut Beogende Instelling) requirements.

## Key Features

### Donation Collection

#### Multiple Donation Types
- **One-time Donations**: Single charitable contributions
- **Recurring Donations**: Monthly, quarterly, or annual recurring gifts
- **Campaign Donations**: Donations for specific fundraising campaigns
- **Chapter Donations**: Donations earmarked for local chapters
- **Memorial Donations**: In memoriam or tribute donations

#### Payment Methods
- **Bank Transfers**: Direct bank transfer with reference tracking
- **SEPA Direct Debit**: Automated recurring donations via SEPA mandates
- **Online Payments**: Integration with payment processors
- **Cash/Check**: Manual entry for offline donations
- **In-kind Donations**: Non-monetary gift tracking

### Donor Management

#### Donor Profiles
- **Personal Information**: Name, contact details, preferences
- **Donation History**: Complete giving history and patterns
- **Communication Preferences**: Email, postal, phone preferences
- **Privacy Settings**: GDPR-compliant data management
- **Customer Integration**: Automatic ERPNext customer creation

#### Donor Categories
- **Individual Donors**: Personal charitable giving
- **Corporate Donors**: Business and foundation giving
- **Anonymous Donors**: Privacy-protected donation handling
- **International Donors**: Cross-border donation management

### ANBI Compliance (Dutch Tax Requirements)

#### ANBI Agreement Management
- **Agreement Numbers**: Automatic ANBI agreement number generation
- **Agreement Dates**: Track ANBI qualification periods
- **Minimum Thresholds**: Configurable minimum amounts for ANBI reporting
- **Automatic Flagging**: Auto-mark donations for Belastingdienst reporting

#### Tax Receipt Generation
- **ANBI Receipts**: Official tax-deductible donation receipts
- **Receipt Numbers**: Sequential receipt numbering system
- **Tax Year Tracking**: Proper tax year assignment for donations
- **Bulk Receipt Generation**: Generate multiple receipts for reporting periods

#### Belastingdienst Reporting
- **Report Data Generation**: Structured data for tax authority reporting
- **Date Range Reports**: Generate reports for specific periods
- **Donor Information**: Complete donor details for tax compliance
- **Amount Verification**: Validate reportable donation amounts

### Donation Purpose Tracking

#### Purpose Categories
- **General Fund**: Unrestricted organizational donations
- **Campaign Donations**: Specific fundraising campaign support
- **Chapter Support**: Donations for local chapter activities
- **Specific Goals**: Targeted donations for particular projects
- **Restricted Funds**: Legally restricted donation tracking

#### Earmarking and Allocation
- **Purpose Validation**: Ensure donations are properly categorized
- **Chapter Validation**: Verify chapter existence for earmarked donations
- **Goal Description**: Detailed descriptions for specific purpose donations
- **Allocation Summaries**: Clear summaries of donation purposes

### Accounting Integration

#### Sales Invoice Creation
- **Automatic Invoicing**: Generate sales invoices for all donations
- **Tax Exemption**: Automatic nonprofit tax exemption application
- **Customer Linking**: Link invoices to donor customer records
- **Payment Tracking**: Track payment status through ERPNext

#### Journal Entry Management
- **Earmarking Entries**: Move funds between general and restricted accounts
- **Account Mapping**: Map donations to appropriate GL accounts
- **Chapter Accounts**: Support for chapter-specific accounting
- **Campaign Accounts**: Separate accounting for fundraising campaigns

#### Payment Entry Automation
- **Automatic Creation**: Generate payment entries when donations are marked paid
- **Bank Reconciliation**: Support for bank statement reconciliation
- **Payment Method Tracking**: Track payment methods for reporting
- **Reference Matching**: Match bank references to donations

## Donation Workflows

### Donation Processing
1. **Donation Creation**: Manual or web form donation entry
2. **Donor Validation**: Verify or create donor records
3. **Purpose Assignment**: Categorize donation purpose
4. **ANBI Assessment**: Evaluate for ANBI reporting requirements
5. **Invoice Generation**: Create sales invoice for accounting
6. **Payment Processing**: Track payment receipt and confirmation

### ANBI Workflow
1. **Amount Assessment**: Check against ANBI minimum thresholds
2. **Agreement Validation**: Verify ANBI agreement information
3. **Automatic Flagging**: Mark for Belastingdienst reporting if applicable
4. **Receipt Generation**: Create official ANBI tax receipts
5. **Reporting Preparation**: Include in periodic tax authority reports

### Earmarking Process
1. **Purpose Identification**: Determine donation intended purpose
2. **Validation**: Verify purpose categories and targets exist
3. **General Fund Entry**: Initial accounting to general donation account
4. **Earmarking Transfer**: Journal entry to transfer funds to specific accounts
5. **Tracking**: Maintain audit trail of fund movements

## Automated Features

### Email Notifications
- **Donation Confirmation**: Immediate confirmation emails to donors
- **Payment Confirmation**: Notifications when payments are received
- **Tax Receipts**: Automated ANBI receipt delivery
- **Thank You Messages**: Personalized appreciation emails

### Scheduled Processing
- **Payment Synchronization**: Regular sync with payment systems
- **Status Updates**: Automatic donation status management
- **Recurring Donations**: Process scheduled recurring gifts
- **Report Generation**: Periodic ANBI and financial reports

## Reporting and Analytics

### Donation Reports
- **Summary Reports**: Total donations by period, purpose, and source
- **Donor Analytics**: Giving patterns and donor retention metrics
- **Campaign Performance**: Fundraising campaign effectiveness
- **Chapter Reports**: Local chapter donation summaries

### Financial Reports
- **Accounting Summaries**: Donation impact on financial statements
- **GL Reconciliation**: Verify donation amounts match accounting records
- **Payment Status**: Outstanding donation payments and collections
- **Earmarking Reports**: Restricted fund allocation and usage

### ANBI Reports
- **Belastingdienst Reports**: Official tax authority reporting data
- **Receipt Registers**: Complete ANBI receipt tracking
- **Compliance Summaries**: ANBI qualification and reporting status
- **Donor Privacy Reports**: Ensure GDPR compliance for ANBI data

## Configuration Options

### System Settings
- **Default Donation Types**: Configure standard donation categories
- **ANBI Parameters**: Set minimum amounts and agreement details
- **Account Mapping**: Map donation purposes to GL accounts
- **Email Templates**: Customize notification content

### ANBI Configuration
- **Agreement Numbers**: Configure ANBI number format and sequencing
- **Minimum Amounts**: Set thresholds for automatic ANBI flagging
- **Reporting Periods**: Define tax reporting periods
- **Receipt Templates**: Customize ANBI receipt formats

### Workflow Settings
- **Approval Processes**: Configure donation approval workflows
- **Automation Rules**: Set up automatic processing rules
- **Validation Rules**: Define data validation requirements
- **Integration Settings**: Configure external system connections

## Best Practices

### Data Quality
- Maintain accurate donor contact information
- Regularly reconcile donation amounts with accounting records
- Verify ANBI agreement information for compliance
- Keep detailed audit trails for all donation changes

### Donor Relations
- Send timely acknowledgment and thank you communications
- Respect donor privacy and communication preferences
- Provide clear information about tax deductibility
- Maintain professional and grateful tone in all communications

### Compliance Management
- Stay current with ANBI requirements and regulations
- Regularly review and update ANBI agreement information
- Ensure proper documentation for all restricted donations
- Maintain backup documentation for tax authority inquiries

### Financial Controls
- Implement proper segregation of duties for donation processing
- Regular review and approval of large donations
- Monitor for duplicate donations and processing errors
- Maintain clear audit trails for financial reporting

## Getting Started

1. **Configure ANBI Settings**: Set up ANBI agreement numbers and thresholds
2. **Set Up Chart of Accounts**: Create appropriate accounts for different donation purposes
3. **Configure Email Templates**: Customize donor communication templates
4. **Test Workflows**: Process test donations to verify all functionality
5. **Train Staff**: Ensure team understands donation processing and compliance requirements

For detailed setup instructions, see the [Donation Configuration Guide](donation-configuration.md).

# Membership Management

The Verenigingen app provides comprehensive membership management capabilities designed specifically for Dutch associations and non-profit organizations.

## Overview

The membership system handles the complete lifecycle of member relationships, from application through active membership to termination, with full integration to ERPNext's billing systems through the Membership Dues Schedule system.

## Key Features

### Membership Applications

- **Online Application Forms**: Web-based membership application forms
- **Application Review Workflow**: Multi-step review process with approval/rejection
- **Document Requirements**: Support for required documentation upload
- **Automated Notifications**: Email notifications for application status changes
- **Chapter-Specific Applications**: Applications can be routed to specific chapters

### Membership Types

- **Flexible Periods**: Support for daily, monthly, quarterly, annual, and lifetime memberships
- **Custom Periods**: Define custom membership durations in months
- **Minimum Period Enforcement**: Configurable 1-year minimum commitment periods
- **Pricing Flexibility**: Standard rates with custom amount overrides
- **Fee Discounts**: Percentage-based discount support

### Member Lifecycle Management

#### Active Membership
- **Status Tracking**: Real-time membership status (Active, Inactive, Expired, Cancelled)
- **Renewal Management**: Automatic and manual renewal options
- **Payment Integration**: Full integration with ERPNext billing through Membership Dues Schedule system
- **Custom Amounts**: Administrator-approved custom membership fees

#### Membership Termination
- **Minimum Period Compliance**: Enforces 1-year minimum commitment
- **Termination Types**: Immediate or end-of-period cancellation
- **Administrative Override**: System managers can override minimum period restrictions
- **Automated Processing**: Scheduled jobs process termination requests

### Payment and Billing

#### Dues Schedule Integration
- **Automated Billing**: Integration with ERPNext billing through Membership Dues Schedule system
- **Invoice Generation**: Automatic invoice creation and submission
- **Payment Tracking**: Real-time payment status synchronization
- **SEPA Support**: SEPA mandate integration for direct debit payments

#### Financial Management
- **Outstanding Amount Tracking**: Monitor unpaid membership fees
- **Payment History**: Complete payment and invoice history
- **Accounting Integration**: Automatic GL entry creation
- **Multiple Payment Methods**: Support for various payment options

## Business Rules

### Membership Overlap Prevention
The system prevents overlapping memberships for the same member:
- Validates date ranges for new memberships
- Provides warnings for existing active memberships
- Allows administrative override with explicit confirmation

### Minimum Period Enforcement
- **Default**: 1-year minimum commitment period for all memberships
- **Configurable**: Can be disabled per membership type
- **Grace Period**: Administrative users can override with warnings
- **Lifetime Memberships**: Applies 1-year minimum despite lifetime designation

### Custom Amount Validation
- **Membership Type Rules**: Custom amounts must respect membership type minimums
- **Administrator Approval**: Custom amounts require proper permissions
- **Audit Trail**: All amount changes are logged with reasons

## Member Data Management

### Personal Information
- **Contact Details**: Email, phone, address information
- **Preferences**: Communication preferences and pronouns
- **Emergency Contacts**: Optional emergency contact information
- **Privacy Settings**: GDPR-compliant privacy preference management

### Member Engagement
- **Volunteer Interest**: Track volunteer availability and skills
- **Committee Participation**: Link to committee and board positions
- **Event Attendance**: Integration with event management
- **Communication History**: Track all member communications

## Automated Processes

### Status Updates
Daily scheduled jobs automatically:
- Expire memberships past their renewal date
- Mark memberships inactive for unpaid amounts
- Process end-of-period cancellations
- Auto-renew eligible memberships

### Notifications
Automated email notifications for:
- Membership application status changes
- Payment confirmations and reminders
- Renewal notifications
- Termination confirmations

## Integration Points

### ERPNext Modules
- **Customer Management**: Automatic customer creation for members
- **Dues Schedule Management**: Full dues schedule lifecycle integration (replaces legacy subscription system)
- **Accounting**: Automated journal entries and payment tracking
- **User Management**: Optional user account creation for members

### External Systems
- **SEPA Banking**: Direct debit mandate management
- **Email Systems**: Template-based email notifications
- **Payment Processors**: Integration with various payment providers

## Administrative Features

### Bulk Operations
- **Membership Sync**: Bulk payment status synchronization
- **Status Updates**: Batch membership status changes
- **Data Export**: Export membership data for analysis
- **Dues Schedule Management**: Bulk dues schedule creation and updates
- **Legacy System Migration**: Tools for transitioning from old subscription system to dues schedule system

### Reporting and Analytics
- **Membership Reports**: Active, expired, and cancelled membership reports
- **Payment Analytics**: Payment status and trend analysis
- **Retention Metrics**: Member retention and churn analysis
- **Financial Summaries**: Membership revenue and outstanding amount reports

## Configuration Options

### System Settings
- **Default Membership Types**: Configure standard membership options
- **Payment Terms**: Set default payment terms and due dates
- **Notification Templates**: Customize email notification content
- **Business Rules**: Enable/disable minimum period enforcement

### Workflow Customization
- **Approval Processes**: Customize membership application workflows
- **Status Transitions**: Configure allowed status change paths
- **Automation Rules**: Set up custom automation for status changes
- **Integration Settings**: Configure external system connections

## Best Practices

### Data Quality
- Regularly sync payment data with dues schedule systems
- Monitor and resolve payment discrepancies
- Maintain accurate member contact information
- Review and update membership type configurations
- Complete migration from legacy subscription system to dues schedule system

### Member Experience
- Provide clear communication about membership terms
- Send timely renewal notifications
- Offer flexible payment options
- Maintain responsive customer service for membership issues
- Ensure seamless transition from legacy subscription system to modern dues schedule system

### Compliance
- Ensure GDPR compliance for member data handling
- Maintain audit trails for all membership changes
- Follow organizational bylaws for membership requirements
- Keep accurate financial records for membership fees

## Getting Started

1. **Configure Membership Types**: Set up your organization's membership categories
2. **Set Payment Terms**: Configure billing cycles and payment methods
3. **Customize Notifications**: Adapt email templates to your organization's tone
4. **Test Workflows**: Create test memberships to verify all processes
5. **Train Staff**: Ensure team members understand the membership management processes

For detailed setup instructions, see the [Membership Configuration Guide](membership-configuration.md).

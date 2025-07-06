# Email Template System

The Verenigingen app includes a comprehensive email template management system that centralizes all organizational communications with professional formatting, context-aware content, and automated delivery.

## Overview

The email template system provides a unified approach to organizational communications, from membership notifications to donation confirmations, with support for dynamic content, fallback mechanisms, and multi-language capabilities.

## Key Features

### Template Management

#### Centralized Template Storage
- **Template Repository**: Single location for all email templates
- **Version Control**: Track template changes and updates
- **Template Categories**: Organized by functional area (membership, donations, volunteers)
- **Template Inheritance**: Base templates with specialized variations
- **Template Preview**: Visual preview of rendered templates

#### Dynamic Content Rendering
- **Jinja2 Integration**: Full Jinja2 templating engine support
- **Context Variables**: Dynamic data insertion from application records
- **Conditional Content**: Show/hide content based on data conditions
- **Loop Support**: Repeat content for lists and collections
- **Filter Support**: Format data with built-in and custom filters

### Pre-Built Template Library

#### Membership Templates
- **Application Notifications**: Membership application status updates
- **Approval Confirmations**: Welcome messages for approved members
- **Rejection Notices**: Professional rejection notifications with reasons
- **Renewal Reminders**: Automated membership renewal notifications
- **Payment Confirmations**: Membership fee payment acknowledgments

#### Donation Templates
- **Donation Confirmation**: Immediate donation acknowledgment emails
- **Payment Confirmation**: Notification when donation payments are received
- **ANBI Tax Receipts**: Official Dutch tax-deductible donation receipts
- **Thank You Messages**: Personalized donor appreciation emails
- **Campaign Updates**: Progress updates for fundraising campaigns

#### Volunteer Templates
- **Welcome Messages**: Onboarding emails for new volunteers
- **Assignment Notifications**: Volunteer role assignment confirmations
- **Training Reminders**: Upcoming training and orientation notifications
- **Recognition Messages**: Volunteer appreciation and recognition emails
- **Schedule Updates**: Changes to volunteer schedules and assignments

#### Administrative Templates
- **Expense Notifications**: Expense approval and rejection notifications
- **Termination Notices**: Membership termination processing updates
- **Contact Confirmations**: Contact request acknowledgment emails
- **System Notifications**: Technical and administrative update messages

### Template Features

#### Professional Design
- **Responsive HTML**: Mobile-friendly email layouts
- **Inline CSS**: Email client compatibility
- **Brand Consistency**: Organizational logo and color scheme integration
- **Accessibility**: Screen reader and accessibility compliance
- **Modern Styling**: Professional appearance across all email clients

#### Multilingual Support
- **Language Detection**: Automatic language selection based on recipient preferences
- **Translation Management**: Support for multiple language versions
- **Fallback Languages**: Default language when preferred language unavailable
- **Cultural Adaptation**: Regional customization for content and formatting

#### Content Personalization
- **Recipient Names**: Personalized greetings and content
- **Organization Context**: Dynamic organization and chapter information
- **Record Details**: Specific information from membership, donation, or volunteer records
- **Calculation Fields**: Computed values like amounts, dates, and durations
- **Custom Variables**: Organization-specific data fields

### Template Processing

#### Context-Aware Rendering
- **Data Validation**: Ensure required context data is available
- **Error Handling**: Graceful handling of missing or invalid data
- **Fallback Content**: Default content when dynamic data unavailable
- **Debug Mode**: Development tools for template troubleshooting
- **Performance Optimization**: Efficient rendering for bulk email operations

#### Delivery Management
- **Queue Integration**: Background processing for large email batches
- **Delivery Status**: Track email delivery success and failures
- **Retry Logic**: Automatic retry for failed email deliveries
- **Rate Limiting**: Respect email service provider limits
- **Bounce Handling**: Process and respond to email bounces

### Testing and Development

#### Template Testing
- **Preview Mode**: Visual preview with sample data
- **Test Sending**: Send test emails with real or sample data
- **A/B Testing**: Compare different template versions
- **Device Testing**: Test appearance across different devices and clients
- **Link Validation**: Verify all links work correctly

#### Development Tools
- **Template Editor**: Built-in editor with syntax highlighting
- **Variable Documentation**: Clear documentation of available context variables
- **Template Validation**: Check for syntax errors and missing variables
- **Performance Metrics**: Monitor template rendering and delivery performance
- **Usage Analytics**: Track template usage and effectiveness

## Template Configuration

### System Templates

#### Expense Management
```
Template: expense_approval_request
Subject: 💰 Expense Approval Required - {{ doc.name }}
Context Variables:
- doc: Expense document
- approver_name: Name of approver
- volunteer_name: Volunteer submitting expense
- formatted_amount: Currency-formatted amount
- approval_url: Direct link to approval page
```

#### Donation Management
```
Template: donation_confirmation
Subject: Thank you for your donation - {{ doc.name }}
Context Variables:
- doc: Donation document
- donor_name: Donor name
- organization_name: Receiving organization
- donation_date: Formatted donation date
- earmarking: Donation purpose description
```

#### Membership Management
```
Template: membership_application_approved
Subject: Welcome to {{ organization_name }}!
Context Variables:
- doc: Membership application
- member_name: New member name
- organization_name: Organization name
- membership_type: Type of membership
- next_steps: Onboarding information
```

### Custom Templates

#### Template Creation
- **Template Builder**: User-friendly template creation interface
- **Variable Picker**: Easy selection of available context variables
- **Preview Integration**: Real-time preview during template creation
- **Template Validation**: Automatic checking of template syntax
- **Save and Test**: Immediate testing of newly created templates

#### Template Customization
- **Organization Branding**: Custom logos, colors, and styling
- **Content Adaptation**: Modify standard templates for specific needs
- **Variable Extension**: Add custom variables for specialized content
- **Conditional Logic**: Advanced conditional content based on data
- **Multi-language Versions**: Create translations of standard templates

## Integration Points

### ERPNext Integration
- **Email Queue**: Integration with ERPNext email delivery system
- **User Preferences**: Respect user email preferences and opt-outs
- **Attachment Support**: Include documents and files with template emails
- **Tracking Integration**: Link email delivery to customer/member records

### External Services
- **Email Providers**: Support for SMTP, SendGrid, Mailgun, and other providers
- **Analytics Integration**: Track email opens, clicks, and engagement
- **Marketing Automation**: Integration with marketing platforms
- **Compliance Tools**: GDPR and privacy compliance features

### Automation Triggers
- **Document Events**: Automatic email sending on document creation/update
- **Scheduled Sending**: Time-based email delivery
- **Workflow Integration**: Email delivery as part of approval workflows
- **API Triggers**: Programmatic email sending from external systems

## Best Practices

### Template Design
- Keep subject lines clear and concise
- Use responsive design for mobile compatibility
- Include clear call-to-action buttons
- Maintain consistent branding across all templates
- Test templates across different email clients

### Content Management
- Write in clear, friendly language appropriate for your audience
- Include all necessary information without overwhelming recipients
- Provide clear next steps and contact information
- Respect cultural and language preferences
- Include unsubscribe options where required

### Performance Optimization
- Use efficient template rendering for bulk operations
- Monitor email delivery rates and adjust as needed
- Implement proper error handling and retry logic
- Keep template file sizes reasonable for fast loading
- Cache frequently used template components

### Compliance and Privacy
- Include required legal disclaimers and privacy notices
- Respect email opt-out preferences
- Ensure GDPR compliance for EU recipients
- Maintain audit trails for email communications
- Provide easy unsubscribe mechanisms

## Getting Started

1. **Review Default Templates**: Examine the pre-built template library
2. **Customize Branding**: Add your organization's logo and colors
3. **Test Email Delivery**: Verify email system configuration
4. **Create Custom Templates**: Build templates for organization-specific needs
5. **Train Users**: Ensure staff understand template system capabilities

For detailed setup and customization instructions, see the [Email Template Configuration Guide](email-template-configuration.md).

# Administrator Guide

This comprehensive guide covers all aspects of administering a Verenigingen system, from initial setup to daily operations and maintenance.

## Table of Contents
- [Getting Started](#getting-started)
- [User Management](#user-management)
- [System Configuration](#system-configuration)
- [Member Management](#member-management)
- [Financial Management](#financial-management)
- [Communication Management](#communication-management)
- [Reporting and Analytics](#reporting-and-analytics)
- [Maintenance and Troubleshooting](#maintenance-and-troubleshooting)

## Getting Started

### First Login and Orientation

After installation, your first steps as an administrator:

1. **Access the System**
   - Navigate to your site URL
   - Login with Administrator credentials
   - You'll see the ERPNext desktop with Verenigingen modules

2. **Key Areas Overview**
   - **Verenigingen Module**: Core association management
   - **Accounting**: Financial management and reporting
   - **CRM**: Contact and communication management
   - **HRMS**: Employee and volunteer management
   - **Settings**: System configuration

### Administrator Dashboard

Access the administrator dashboard at `/member_dashboard` for:
- Member statistics and trends
- Financial summaries
- Recent activity overview
- Quick action buttons

## User Management

### User Roles and Permissions

The Verenigingen system includes pre-configured role profiles:

#### Standard Role Profiles
- **Verenigingen System Admin**: Full system access
- **Verenigingen Manager**: Management level access
- **Verenigingen Treasurer**: Financial operations access
- **Verenigingen Chapter Admin**: Chapter management access
- **Verenigingen Team Leader**: Team coordination access
- **Verenigingen Volunteer**: Volunteer portal access
- **Verenigingen Member**: Member portal access

### Creating User Accounts

1. **Navigate to User Management**:
   - Go to **Users and Permissions → User**
   - Click **New**

2. **Basic User Information**:
   ```
   Email: user@yourorganization.org
   First Name: John
   Last Name: Doe
   Send Welcome Email: ✓
   ```

3. **Assign Role Profiles**:
   - Select appropriate role profile from the list above
   - Or assign individual roles for custom access

4. **Link to Member/Volunteer** (optional):
   - Link user accounts to existing Member or Volunteer records
   - Enables personalized portal experience

### Automated Role Profile Deployment

Deploy all role profiles automatically:
```bash
bench execute verenigingen.setup.role_profile_setup.deploy_role_profiles
```

### Managing User Permissions

#### Custom Permission Setup
For specific needs, create custom roles:

1. **Create Custom Role**:
   - Go to **Users and Permissions → Role**
   - Define specific permissions

2. **Assign DocType Permissions**:
   - Go to **Users and Permissions → Role Permissions Manager**
   - Set read/write/create/delete permissions per document type

#### Chapter-Based Access Control
Enable geographic access restrictions:
- Users see only data from their assigned chapters
- Configured through Chapter Member assignments
- Automatic filtering in reports and lists

## System Configuration

### Organization Setup

#### Company Configuration
1. **Basic Company Details**:
   - Go to **Accounting → Company**
   - Update organization information
   - Set fiscal year and accounting settings

2. **E-Boekhouden Settings**:
   - Go to **Setup → E-Boekhouden Settings**
   - Configure default company
   - Set up API credentials if using e-Boekhouden integration

#### Chapter Management
1. **Create Chapters**:
   - Go to **Verenigingen → Chapter**
   - Define geographic regions
   - Set postal code patterns for automatic assignment

2. **Chapter Board Management**:
   - Assign board members to chapters
   - Configure board-specific permissions
   - Set up chapter-specific email templates

### Brand and Theming

#### Brand Management System
Access brand management at `/brand_management` (System Manager role required):

1. **Color Configuration**:
   - Primary color (default: #cf3131 RSP Red)
   - Secondary color (default: #01796f Pine Green)
   - Accent color (default: #663399 Royal Purple)
   - Additional semantic colors

2. **Brand Activation**:
   - Preview color combinations
   - One-click activation of brand settings
   - Automatic CSS generation

#### Custom Branding
- CSS variables available: `var(--brand-primary)`, `var(--brand-secondary)`
- Tailwind CSS class overrides
- Global application across all portal pages

### Email System Configuration

#### Email Templates
Install comprehensive email template system:
```bash
bench execute verenigingen.api.email_template_manager.create_all_email_templates
```

#### Available Templates
- **Membership**: Application confirmations, welcome emails, renewals
- **Payments**: Success notifications, failure alerts, retry scheduling
- **SEPA**: Mandate creation, cancellation, expiring notifications
- **Volunteer**: Assignment notifications, expense approvals
- **General**: System notifications, alerts

#### Email Account Setup
1. **Configure SMTP**:
   - Go to **Settings → Email Account**
   - Set up organizational email account
   - Test email delivery

2. **Email Domain Settings**:
   - Go to **Settings → Email Domain**
   - Configure domain for consistent from addresses

## Member Management

### Membership Types and Pricing

#### Creating Membership Types
1. **Navigate to Membership Types**:
   - Go to **Verenigingen → Membership Type**
   - Click **New**

2. **Configuration Options**:
   ```
   Type Name: Individual Member
   Fee Amount: €25.00
   Billing Frequency: Annual
   Grace Period: 30 days
   Auto-renewal: ✓
   SEPA Eligible: ✓
   ```

#### Fee Management
- **Custom Fee Amounts**: Allow member-specific fee adjustments
- **Fee Adjustment Portal**: Members can modify fees at `/membership_fee_adjustment`
- **Minimum Period Enforcement**: Configure minimum membership periods

### Member Lifecycle Management

#### Application Review Process
1. **Review Applications**:
   - Go to **Verenigingen → Membership Application**
   - Review submitted applications
   - Assign chapters based on postal codes

2. **Approval Workflow**:
   - Approve/reject applications
   - Automatic member creation on approval
   - Payment link generation

3. **Bulk Processing**:
   - Use bulk review tools for efficiency
   - Generate reports on application status

#### Member Status Management
- **Active**: Regular paying members
- **Inactive**: Non-paying or lapsed members
- **Suspended**: Temporarily suspended members
- **Terminated**: Permanently terminated members

### Chapter Assignment

#### Automatic Assignment
Configure postal code patterns for automatic chapter assignment:
```
Chapter: Amsterdam
Postal Code Pattern: 10*,11*,12*
```

#### Manual Assignment
- Override automatic assignments when needed
- Track assignment history
- Handle member moves between regions

## Financial Management

### Payment Processing

#### SEPA Direct Debit Setup
1. **Configure SEPA Settings**:
   - Go to **Accounting → SEPA Direct Debit Settings**
   - Set up creditor identifier
   - Configure mandate parameters

2. **Mandate Management**:
   - Members can create mandates at `/bank_details`
   - Automatic BIC derivation for Dutch IBANs
   - Mandate lifecycle tracking

#### Payment Method Configuration
Support for multiple payment methods:
- **SEPA Direct Debit**: Automated recurring payments
- **Online Payments**: Integration with payment gateways
- **Manual Payments**: Bank transfers, cash, checks

### Subscription Management

#### Automated Billing
- Monthly/annual billing cycles
- Grace period management
- Automatic renewals with SEPA mandates
- Payment failure handling

#### Dues Schedule Management
Modern dues schedule management system (replaces legacy subscription system):
```bash
# Check orphaned dues schedules
bench execute verenigingen.verenigingen.report.orphaned_subscriptions_report.orphaned_subscriptions_report.get_data

# Process membership renewals
bench execute verenigingen.verenigingen.doctype.membership.membership.process_membership_statuses

# Migration from legacy subscription system
bench execute verenigingen.utils.subscription_migration.migrate_to_dues_schedule_system
```

### Financial Reporting

#### Standard Reports
- **Member Revenue Reports**: Track membership fee revenue
- **Payment Status Reports**: Monitor payment collections
- **SEPA Batch Reports**: Direct debit processing summaries
- **Donation Reports**: ANBI-compliant donation tracking

#### ERPNext Integration
- Automatic Sales Invoice creation for membership fees
- Integration with ERPNext accounting modules
- Chart of Accounts synchronization

## Communication Management

### Email Template Management

#### Template Categories
1. **Membership Communications**:
   - Welcome emails for new members
   - Renewal reminders
   - Payment confirmations

2. **Payment Communications**:
   - Payment success notifications
   - Payment failure alerts
   - SEPA mandate notifications

3. **Volunteer Communications**:
   - Assignment notifications
   - Expense approval communications
   - Achievement recognition

#### Customizing Templates
1. **Access Template Manager**:
   - Go to **Settings → Email Template**
   - Select template to customize

2. **Template Variables**:
   - Use Jinja2 templating with context variables
   - Member data: `{{ member.first_name }}`
   - Payment data: `{{ payment.amount }}`
   - Organization data: `{{ company.company_name }}`

### Automated Notifications

#### System Triggers
- Member application submissions
- Payment processing results
- SEPA mandate status changes
- Volunteer assignment updates

#### Notification Rules
Configure custom notification rules:
1. **Go to Settings → Notification**
2. **Set Triggers**: Document events, field changes
3. **Define Recipients**: Roles, users, or email addresses
4. **Customize Messages**: Use templates or custom content

## Reporting and Analytics

### Membership Analytics

#### Analytics Dashboard
Access comprehensive analytics at `/member_dashboard`:
- **Real-time Metrics**: Active members, revenue, growth rates
- **Trend Analysis**: Membership growth over time
- **Segmentation**: Analysis by chapter, membership type, demographics
- **Predictive Analytics**: ML-based forecasting

#### Custom Reports
Create custom reports using ERPNext Report Builder:
1. **Query Reports**: SQL-based custom reporting
2. **Script Reports**: Python-based dynamic reports
3. **Print Formats**: Custom document layouts

### Financial Analytics

#### Revenue Tracking
- Monthly/annual revenue trends
- Revenue by membership type
- Payment method analysis
- Outstanding balance reports

#### SEPA and Payment Analytics
- Direct debit success rates
- Payment failure analysis
- Collection efficiency metrics
- Bank reconciliation reports

### Volunteer Analytics

#### Activity Tracking
- Volunteer engagement metrics
- Assignment completion rates
- Expense processing analytics
- Team performance indicators

#### Resource Optimization
- Volunteer capacity analysis
- Skill matching reports
- Activity distribution analysis

## Maintenance and Troubleshooting

### System Maintenance

#### Regular Maintenance Tasks

**Daily**:
```bash
# Check system status
bench status

# Review error logs
bench logs
```

**Weekly**:
```bash
# Update system
bench update

# Run regression tests
python scripts/testing/runners/regression_test_runner.py

# Backup database
bench backup
```

**Monthly**:
```bash
# System optimization
bench execute verenigingen.verenigingen.report.orphaned_subscriptions_report.orphaned_subscriptions_report.get_data

# Performance analysis
python scripts/testing/runners/run_volunteer_portal_tests.py --suite performance

# Verify subscription system migration status
python scripts/validation/validate_subscription_migration.py
```

#### Database Maintenance
- **Backup Strategy**: Automated daily backups
- **Archive Old Data**: Archive terminated memberships
- **Index Optimization**: Monitor and optimize database indices

### Troubleshooting Common Issues

#### Payment Processing Issues

**SEPA Mandate Problems**:
1. Check IBAN validation
2. Verify mandate status
3. Review BIC derivation
4. Test with mock bank accounts

**Payment Failures**:
1. Review payment logs
2. Check bank account status
3. Verify SEPA batch processing
4. Monitor payment retry cycles

#### User Access Issues

**Permission Problems**:
1. Verify role assignments
2. Check role profile configurations
3. Review chapter-based access restrictions
4. Test with specific user accounts

**Portal Access Issues**:
1. Check user account status
2. Verify email confirmation
3. Review portal page permissions
4. Test member/volunteer linking

#### Performance Issues

**Slow Response Times**:
1. Check server resources
2. Review database query performance
3. Monitor background job processing
4. Analyze user activity patterns

**Database Issues**:
1. Check MariaDB status
2. Review slow query logs
3. Monitor database connections
4. Optimize large table queries

### Emergency Procedures

#### System Recovery
1. **Service Restart**:
   ```bash
   bench restart
   ```

2. **Database Recovery**:
   ```bash
   bench restore [backup-file]
   ```

3. **Application Reset**:
   ```bash
   bench migrate
   bench build
   ```

#### Data Recovery
- **Member Data**: Restore from backups
- **Payment Data**: Reconcile with bank statements
- **Configuration**: Redeploy role profiles and templates
- **Migration Recovery**: Restore from pre-migration backups if dues schedule migration fails

### Monitoring and Alerting

#### System Monitoring
- **Server Resources**: CPU, memory, disk usage
- **Application Performance**: Response times, error rates
- **Database Health**: Connection counts, query performance
- **Background Jobs**: Processing queues and completion rates

#### Business Metrics Monitoring
- **Membership Growth**: Track new registrations
- **Payment Success Rates**: Monitor collection efficiency
- **User Engagement**: Portal usage analytics
- **System Usage**: Feature adoption rates

### Getting Support

#### Documentation Resources
- **Technical Documentation**: `docs/` directory
- **API Documentation**: Available endpoints and usage
- **Testing Guides**: Comprehensive testing strategies
- **Implementation Guides**: Feature-specific documentation

#### Community Resources
- **Issue Tracking**: Project repository for bug reports
- **Feature Requests**: Enhancement proposal process
- **Community Forums**: User discussion and support

#### Professional Support
For complex issues or custom development:
- Review available professional services
- Consider consulting for specialized requirements
- Evaluate custom development options

---

This administrator guide provides comprehensive coverage of system administration tasks. For specific feature details, refer to the feature-specific documentation in the `docs/features/` directory.

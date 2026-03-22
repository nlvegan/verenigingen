# Getting Started Guide

Welcome to Vereiningen. This guide will help you get up and running with your association management system.

## Table of Contents

- [What is Vereiningen?](#what-is-vereiningen)
- [Quick Start Checklist](#quick-start-checklist)
- [Installation Overview](#installation-overview)
- [Initial Configuration](#initial-configuration)
- [User Setup](#user-setup)
- [First Steps](#first-steps)
- [Next Steps](#next-steps)
- [Getting Help](#getting-help)

## What is Vereiningen?

Vereiningen is a comprehensive association management system designed for Dutch non-profit organizations. It provides:

### Core Benefits

- **Complete Member Lifecycle**: From application to termination with automated workflows
- **Financial Integration**: SEPA direct debit, eBoekhouden sync, and ERPNext integration
- **Dutch Compliance**: ANBI donation agreement support, GDPR compliance
- **Portal Systems**: Self-service member and volunteer portals
- **Modern Technology**: Built on Frappe Framework v16 with responsive design

### Perfect For

- Non-profit organizations with 10 to 10,000+ members
- Associations requiring SEPA direct debit payment collection
- Organizations needing eBoekhouden accounting integration
- Groups with volunteer coordination requirements
- ANBI-qualified organizations requiring compliance reporting

### Quick Overview

- **Setup Time**: 4-8 hours for basic configuration
- **Learning Curve**: 2-4 hours per user type
- **Go-Live Time**: 1-2 weeks for full deployment

## Quick Start Checklist

Before you begin, ensure you have:

### Prerequisites

- [ ] Server with minimum 8 GB RAM and 50 GB storage
- [ ] Ubuntu 22.04+ operating system
- [ ] Domain name and SSL certificate (for production)
- [ ] Email service credentials (SMTP)
- [ ] Basic understanding of your organization's structure

### Required Information

- [ ] Organization details (name, address, contact information)
- [ ] Membership types and fee structures
- [ ] Chapter/regional organization (if applicable)
- [ ] User accounts needed and their roles
- [ ] Payment methods and banking information

### Time Estimate

- **Basic Installation**: 2-4 hours
- **Initial Configuration**: 4-6 hours
- **User Training**: 2-4 hours per user type
- **Go-Live Preparation**: 1-2 days

## Installation Overview

### Option 1: Fresh Installation

If you are starting from scratch:

1. Follow the [Installation Guide](INSTALLATION.md) for detailed steps
2. Install dependencies: ERPNext, Payments, HRMS
3. Install Vereiningen
4. Configure basic system settings

### Option 2: Existing ERPNext Installation

If you have ERPNext already running:

1. Back up your system before installing new apps
2. Install required apps (Payments, HRMS if not already present)
3. Add Vereiningen to your existing setup
4. Configure integration settings

### Quick Installation Commands

```bash
# Initialize bench with Frappe v16
bench init --frappe-branch develop frappe-bench
cd frappe-bench

# Create site
bench new-site your-site.com

# Install required apps
bench get-app --branch develop erpnext
bench get-app --branch develop payments
bench get-app --branch develop hrms
bench get-app verenigingen

bench --site your-site.com install-app erpnext
bench --site your-site.com install-app payments
bench --site your-site.com install-app hrms
bench --site your-site.com install-app verenigingen
```

## Initial Configuration

### Step 1: Company Setup

1. **Access Your System**:
   - Navigate to your site URL
   - Login with Administrator credentials
   - Go to ERPNext desk

2. **Configure Company Information** (Accounting > Company):
   - Company name, address, and contact information
   - Tax ID and registration numbers
   - Logo and branding

3. **Set Fiscal Year** (Accounting > Fiscal Year):
   - Configure your organization's fiscal year
   - Set accounting periods

### Step 2: System Settings

1. **Email Configuration** (Settings > Email Account):
   - Configure SMTP settings
   - Test email delivery

2. **Install Email Templates**:

   ```bash
   bench --site your-site.com execute \
       verenigingen.api.email_template_manager.create_comprehensive_email_templates
   ```

3. **Deploy Role Profiles**:

   ```bash
   bench --site your-site.com execute \
       verenigingen.setup.role_profile_setup.setup_role_profiles_cli
   ```

### Step 3: Basic Data Setup

1. **Create Membership Types** (Verenigingen > Membership Type):
   - Define categories: Individual, Student, Senior, Corporate
   - Set fee amounts and billing frequencies

2. **Setup Chapters** (Verenigingen > Chapter), if applicable:
   - Create geographic chapters
   - Configure postal code patterns

3. **Configure Payment Methods**:
   - Set up SEPA direct debit (recommended for Dutch organizations)
   - Configure online payment gateways (Mollie)

## User Setup

### Understanding User Roles

The system includes pre-configured role profiles:

**For Administrators:**
- Vereiningen System Administrator: Full system access
- Vereiningen Staff: Day-to-day operations
- Vereiningen Treasurer: Financial operations focus

**For Chapter Operations:**
- Vereiningen Chapter Board Member: Chapter management
- Vereiningen Team Leader: Team coordination
- Vereiningen Auditor: Read-only access for auditing

**For Members and Volunteers:**
- Vereiningen Member: Member portal access
- Vereiningen Volunteer: Volunteer portal access

### Creating User Accounts

1. **Administrator Accounts** (Users and Permissions > User):
   - Create accounts for key staff members
   - Assign appropriate role profiles
   - Send welcome emails

2. **Member Accounts** (optional):
   - Can be created automatically during member approval
   - Or created manually for existing members

### User Training Plan

1. Administrators: Read [ADMIN_GUIDE.md](ADMIN_GUIDE.md)
2. Members: Review the [membership management docs](features/membership-management.md)
3. Volunteers: See the [volunteer management docs](features/volunteer-management.md)
4. Treasurers: Focus on financial sections of admin guide

## First Steps

### Week 1: Basic Setup

**Day 1-2: System Configuration**

- [ ] Complete installation and basic configuration
- [ ] Create administrator accounts
- [ ] Configure email system
- [ ] Set up organization branding

**Day 3-4: Master Data**

- [ ] Create membership types
- [ ] Set up chapters/regions
- [ ] Configure payment methods
- [ ] Import initial member data (if applicable)

**Day 5-7: Testing**

- [ ] Create test member accounts
- [ ] Test member application process
- [ ] Test payment processing
- [ ] Verify email notifications

### Week 2: User Onboarding

**Day 1-3: Staff Training**

- [ ] Train administrators on system basics
- [ ] Configure user accounts for staff
- [ ] Set up reporting and analytics
- [ ] Test user permissions

**Day 4-5: Process Testing**

- [ ] Test complete member lifecycle
- [ ] Verify payment processing
- [ ] Test communication workflows
- [ ] Check integration with ERPNext

**Day 6-7: Go-Live Preparation**

- [ ] Finalize configurations
- [ ] Prepare user documentation
- [ ] Plan rollout schedule
- [ ] Set up monitoring

### First Tasks Checklist

1. **Test Member Journey**:
   - [ ] Submit test membership application
   - [ ] Approve application and create member
   - [ ] Set up SEPA mandate
   - [ ] Process test payment
   - [ ] Verify member portal access

2. **Test Communication System**:
   - [ ] Send welcome email to test member
   - [ ] Test payment confirmation emails
   - [ ] Verify notification delivery

3. **Verify Financial Integration**:
   - [ ] Check Sales Invoice creation
   - [ ] Verify payment entry recording
   - [ ] Test SEPA batch generation

4. **Test User Access**:
   - [ ] Login as different user types
   - [ ] Verify appropriate access levels
   - [ ] Test member portal functionality

### Data Migration (if applicable)

If migrating from existing systems:

1. **Member Data**: Export from old system, clean/format, use Frappe data import tools or API, verify accuracy
2. **Financial Data**: Import payment history, set up opening balances, reconcile with accounting records
3. **Communication Data**: Import contact preferences, set up email lists, configure notification settings

## Next Steps

### Phase 2: Advanced Features

Once basic functionality is working:

1. **Volunteer Management**: Set up volunteer portal, configure team structures, implement expense management
2. **Advanced Reporting**: Configure analytics dashboards, set up automated reports
3. **Automation**: Set up automated workflows, configure payment reminders, implement automated renewals

### Phase 3: Optimization

After 1-3 months of usage:

1. **Performance**: Monitor system performance, configure caching, plan for scaling
2. **Process Improvement**: Analyze user feedback, optimize workflows
3. **Integration Expansion**: Connect additional systems, enhance automation

### Ongoing Maintenance

1. **Daily**: Monitor system status, check error logs, process support requests
2. **Weekly**: Review system performance, update and backup system
3. **Monthly**: Review security settings, analyze business metrics, plan updates

## Getting Help

### Documentation Resources

- [Installation Guide](INSTALLATION.md): Detailed installation instructions
- [Administrator Guide](ADMIN_GUIDE.md): Comprehensive admin documentation
- [Membership Management](features/membership-management.md): Member user guide
- [Volunteer Management](features/volunteer-management.md): Volunteer user guide
- [API Documentation](API_DOCUMENTATION.md): Integration and development guide
- [FAQ and Troubleshooting](FAQ_TROUBLESHOOTING.md): Common issues and solutions

### Essential Commands

```bash
# Check system status
bench doctor

# Restart services
bench restart

# Update system
bench update

# View logs
tail -f ~/frappe-bench/logs/web.log

# Run tests
cd ~/frappe-bench
bench --site your-site.com run-tests --app verenigingen
```

### Important URLs

- **Member Portal**: `/member_portal`
- **Volunteer Portal**: `/volunteer/dashboard`
- **Brand Management**: `/brand_management`
- **Admin Dashboard**: `/member_dashboard`

### Support Options

1. **Self-Service**: Read documentation, use built-in help and tooltips, check FAQ
2. **Community Support**: Search community forums, check GitHub issues
3. **Professional Support**: Contact the development team for technical issues or custom development

---

Welcome to Vereiningen. Take your time with the setup process. Proper setup and training will pay dividends in improved efficiency and member satisfaction.

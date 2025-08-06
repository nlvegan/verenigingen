# FAQ and Troubleshooting Guide

This comprehensive guide answers frequently asked questions and provides solutions to common issues in the Verenigingen system.

## ⚡ Quick Reference

**For comprehensive error recovery procedures, see:** [**Error Recovery Guide**](troubleshooting/ERROR_RECOVERY_GUIDE.md)

The Error Recovery Guide provides detailed step-by-step procedures for:
- **Payment Failures** - SEPA direct debit failures, mandate errors, reconciliation issues
- **Portal Access Issues** - Login failures, permission errors, session timeouts
- **Data Processing Errors** - Import failures, validation errors, duplicate entries
- **Integration Failures** - eBoekhouden connectivity, API timeouts, webhook failures
- **System-Level Issues** - Database problems, Redis/cache issues, background job failures

## Table of Contents
- [General Questions](#general-questions)
- [Installation and Setup](#installation-and-setup)
- [Member Portal Issues](#member-portal-issues)
- [Payment and SEPA Issues](#payment-and-sepa-issues)
- [Volunteer Portal Issues](#volunteer-portal-issues)
- [Administrator Issues](#administrator-issues)
- [Technical Troubleshooting](#technical-troubleshooting)
- [Contact Support](#contact-support)

## General Questions

### What is Verenigingen?

**Q: What is the Verenigingen app and what does it do?**

A: Verenigingen is a comprehensive association management system built on the Frappe/ERPNext platform. It provides:
- Complete member lifecycle management
- Payment processing with SEPA direct debit
- Volunteer coordination and management
- Chapter-based organization
- Financial integration with ERPNext
- Dutch compliance features (ANBI, GDPR)

### System Requirements

**Q: What are the system requirements for Verenigingen?**

A: The system requires:
- **Server**: Ubuntu 20.04+ or CentOS 8+
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 20GB minimum, 50GB+ for production
- **Dependencies**: Frappe Framework, ERPNext, Payments app, HRMS, CRM
- **Browser**: Modern browsers (Chrome, Firefox, Safari, Edge)

**Q: Can Verenigingen work with existing ERPNext installations?**

A: Yes, Verenigingen is designed as an ERPNext app and integrates seamlessly with existing ERPNext installations. It requires ERPNext version 14 or higher.

### Data and Privacy

**Q: Is the system GDPR compliant?**

A: Yes, the system includes GDPR compliance features:
- Member consent management
- Data access and portability tools
- Automatic data retention policies
- Privacy settings for member information
- Audit trails for data access

**Q: Where is data stored and how is it secured?**

A: Data is stored in your own MariaDB/MySQL database. Security features include:
- Role-based access control
- Data encryption for sensitive information
- Regular backup systems
- Session management and timeouts
- Audit logging of all activities

## Installation and Setup

### Installation Issues

**Q: Installation fails with "App not found" error**

A: This usually indicates the app source is not properly configured:

1. **Check app source**:
   ```bash
   bench get-app verenigingen [repository-url]
   ```

2. **Verify app is in apps directory**:
   ```bash
   ls apps/
   ```

3. **Try installing with force flag**:
   ```bash
   bench install-app verenigingen --force
   ```

**Q: Migration errors during installation**

A: Migration errors can occur due to dependency issues:

1. **Ensure dependencies are installed**:
   ```bash
   bench install-app erpnext
   bench install-app payments
   bench install-app hrms
   bench install-app crm
   ```

2. **Run migrations manually**:
   ```bash
   bench migrate --skip-failing
   bench migrate
   ```

3. **Check error logs**:
   ```bash
   bench logs
   ```

### Configuration Issues

**Q: Email notifications are not working**

A: Email issues are usually configuration-related:

1. **Check SMTP settings**:
   - Go to **Settings → Email Account**
   - Verify SMTP server, port, and credentials
   - Test with "Send Test Email"

2. **Check email templates**:
   ```bash
   bench --site site_name execute verenigingen.api.email_template_manager.create_comprehensive_email_templates
   ```

3. **Verify email queue**:
   - Go to **Settings → Email Queue**
   - Check for failed emails and error messages

**Q: Users can't access certain modules**

A: This is typically a permissions issue:

1. **Deploy role profiles**:
   ```bash
   bench --site site_name execute verenigingen.setup.role_profile_setup.setup_role_profiles
   ```

2. **Check user role assignments**:
   - Go to **Users and Permissions → User**
   - Verify role profiles are assigned

3. **Review document permissions**:
   - Go to **Users and Permissions → Role Permissions Manager**

### Database Issues

**Q: Database connection errors during setup**

A: Database issues can prevent proper installation:

1. **Check MariaDB status**:
   ```bash
   sudo systemctl status mariadb
   sudo systemctl restart mariadb
   ```

2. **Verify database credentials**:
   - Check `sites/site_name/site_config.json`
   - Verify database user permissions

3. **Test database connection**:
   ```bash
   bench --site site_name mariadb
   ```

## Member Portal Issues

> **💡 For comprehensive portal access troubleshooting, see the [Error Recovery Guide - Portal Access Issues](troubleshooting/ERROR_RECOVERY_GUIDE.md#portal-access-issues)**

### Login and Access Issues

**Q: Members can't log in to the portal**

A: Login issues can have several causes:

1. **Check user account status**:
   - Go to **Users and Permissions → User**
   - Verify account is enabled and not locked

2. **Verify member linking**:
   - Ensure user account is linked to member record
   - Check member status is active

3. **Password reset**:
   - Use "Forgot Password" link
   - Check email delivery to member

**Q: Portal pages show "Permission Denied" errors**

A: Permission issues require role verification:

1. **Check role assignments**:
   - Verify user has "Verenigingen Member" role
   - Check role profile assignments

2. **Review portal permissions**:
   - Ensure portal pages have correct permissions
   - Check website settings for guest access

3. **Clear cache and sessions**:
   - Log out and log back in
   - Clear browser cache

### Profile and Data Issues

**Q: Member can't update their address**

A: Address update issues are often validation-related:

1. **Check required fields**:
   - Ensure all mandatory fields are completed
   - Verify postal code format (Dutch: 1234AB)

2. **Review validation errors**:
   - Check browser console for JavaScript errors
   - Verify field format requirements

3. **Database constraints**:
   - Check for duplicate address entries
   - Verify database field lengths

**Q: Chapter assignment is incorrect**

A: Chapter assignment uses postal code patterns:

1. **Verify postal code**:
   - Check member's registered postal code
   - Ensure correct Dutch postal code format

2. **Review chapter patterns**:
   - Go to **Verenigingen → Chapter**
   - Check postal code patterns for chapters

3. **Manual assignment**:
   - Override automatic assignment if needed
   - Contact administrator for adjustment

### Payment Portal Issues

**Q: SEPA mandate creation fails**

A: SEPA mandate issues often involve IBAN validation:

1. **IBAN validation**:
   - Verify IBAN format is correct
   - Use IBAN checker tools to validate
   - Ensure IBAN belongs to supported bank

2. **Account holder name**:
   - Verify name matches bank account
   - Check for special characters or formatting

3. **Bank support**:
   - Ensure bank supports SEPA direct debit
   - Contact bank about SEPA mandate restrictions

## Payment and SEPA Issues

> **💡 For detailed payment failure recovery procedures, see the [Error Recovery Guide - Payment System Failures](troubleshooting/ERROR_RECOVERY_GUIDE.md#payment-system-failures)**

### SEPA Direct Debit Problems

**Q: SEPA payments are failing**

A: Payment failures can have multiple causes:

1. **Bank account issues**:
   - Insufficient funds in member account
   - Account closed or frozen
   - Bank blocking direct debits

2. **Mandate issues**:
   - Mandate expired or cancelled
   - Incorrect mandate reference
   - Bank mandate restrictions

3. **System configuration**:
   - Check SEPA creditor settings
   - Verify batch processing configuration
   - Review payment timing settings

**Q: How to handle returned/rejected payments**

A: Returned payments require specific handling:

1. **Review return codes**:
   - Check SEPA return reason codes
   - Understand specific rejection reasons

2. **Member communication**:
   - Automatic email notifications to members
   - Provide clear instructions for resolution

3. **Retry process**:
   - Configure automatic retry schedules
   - Set maximum retry attempts
   - Escalation to manual collection

### Payment Method Issues

**Q: Alternative payment methods not working**

A: Non-SEPA payment issues:

1. **Payment gateway configuration**:
   - Check payment processor credentials
   - Verify webhook URLs and endpoints
   - Test payment gateway connectivity

2. **Integration issues**:
   - Review ERPNext payment integration
   - Check payment entry creation
   - Verify account reconciliation

3. **Member instructions**:
   - Provide clear payment instructions
   - Offer multiple payment options
   - Manual payment processing procedures

## Volunteer Portal Issues

### Access and Profile Issues

**Q: Volunteers can't access their portal**

A: Volunteer portal access requires specific setup:

1. **Volunteer record linking**:
   - Ensure user account linked to volunteer record
   - Check volunteer status is active

2. **Role assignments**:
   - Verify "Verenigingen Volunteer" role assigned
   - Check volunteer-specific permissions

3. **Portal configuration**:
   - Ensure volunteer portal pages are published
   - Check website settings for volunteer access

**Q: Team assignments not showing**

A: Team assignment visibility issues:

1. **Team membership**:
   - Verify volunteer is assigned to teams
   - Check team assignment dates and status

2. **Permission levels**:
   - Review team-based access permissions
   - Check chapter-based filtering

3. **Data synchronization**:
   - Refresh team assignment data
   - Check for database consistency issues

### Expense Management Issues

**Q: Expense claims are rejected**

A: Expense rejection requires review:

1. **Policy compliance**:
   - Review expense policy requirements
   - Check spending limits and categories
   - Verify receipt requirements

2. **Documentation**:
   - Ensure receipts are attached
   - Check receipt quality and completeness
   - Verify expense descriptions

3. **Approval workflow**:
   - Check approval workflow status
   - Contact team leader or approver
   - Review approval hierarchy

**Q: Expense reimbursements are delayed**

A: Payment delays can have various causes:

1. **Approval status**:
   - Check expense claim approval status
   - Follow up with approvers if delayed

2. **Payment processing**:
   - Verify bank account information
   - Check payment processing schedule
   - Contact finance department

3. **System issues**:
   - Check for system integration problems
   - Verify payment entry creation
   - Review error logs for issues

## Administrator Issues

### User Management Problems

**Q: Role assignments not working properly**

A: Role assignment issues require systematic checking:

1. **Role profile deployment**:
   ```bash
   bench --site site_name execute verenigingen.setup.role_profile_setup.setup_role_profiles
   ```

2. **Permission cache**:
   ```bash
   bench clear-cache
   bench restart
   ```

3. **Manual role assignment**:
   - Check individual role assignments
   - Verify custom permissions

**Q: New user accounts not being created properly**

A: User creation issues:

1. **Check user creation workflow**:
   - Verify email settings for welcome emails
   - Check user creation permissions
   - Review default role assignments

2. **Email delivery**:
   - Check email queue for failed sends
   - Verify SMTP configuration
   - Test email delivery

3. **Database constraints**:
   - Check for duplicate email addresses
   - Verify user table constraints

### System Configuration Issues

**Q: Brand management not working**

A: Brand management requires proper setup:

1. **Access permissions**:
   - Ensure user has System Manager role
   - Check brand management page permissions

2. **CSS generation**:
   - Verify brand CSS endpoint is accessible
   - Check CSS caching settings
   - Clear browser cache after changes

3. **File permissions**:
   - Check file system permissions for CSS files
   - Verify web server can write CSS files

**Q: Reports showing incorrect data**

A: Report data issues:

1. **Data synchronization**:
   - Check ERPNext integration status
   - Verify data consistency between modules

2. **Permission filtering**:
   - Review report permission queries
   - Check user access to underlying data

3. **Cache issues**:
   - Clear report cache
   - Refresh underlying data sources

### Performance Issues

**Q: System running slowly**

A: Performance problems require systematic diagnosis:

1. **Server resources**:
   - Check CPU and memory usage
   - Monitor disk space and I/O
   - Review database performance

2. **Database optimization**:
   - Check slow query logs
   - Optimize database indices
   - Review large table performance

3. **Application optimization**:
   - Clear application cache
   - Review background job queues
   - Monitor user activity patterns

## Technical Troubleshooting

> **💡 For system-level error recovery procedures, see the [Error Recovery Guide - System-Level Issues](troubleshooting/ERROR_RECOVERY_GUIDE.md#system-level-issues)**

### System Errors

**Q: "Internal Server Error" messages**

A: Server errors require log analysis:

1. **Check error logs**:
   ```bash
   bench logs
   tail -f sites/site_name/logs/web.log
   ```

2. **Review system logs**:
   ```bash
   sudo tail -f /var/log/nginx/error.log
   sudo journalctl -u supervisor
   ```

3. **Database logs**:
   ```bash
   sudo tail -f /var/log/mysql/error.log
   ```

**Q: Background jobs not processing**

A: Background job issues:

1. **Check worker status**:
   ```bash
   bench worker --queue default
   bench worker --queue long
   ```

2. **Review job queue**:
   - Go to **Settings → Background Jobs**
   - Check for failed or stuck jobs

3. **Restart workers**:
   ```bash
   bench restart
   ```

### Integration Issues

**Q: ERPNext integration not working**

A: Integration problems:

1. **App dependencies**:
   - Verify ERPNext version compatibility
   - Check required app installations

2. **Custom field issues**:
   - Check custom field creation
   - Verify field permissions and properties

3. **Document linking**:
   - Review document link configurations
   - Check foreign key relationships

**Q: SEPA file generation fails**

A: SEPA file issues:

1. **Configuration check**:
   - Verify SEPA creditor settings
   - Check mandate configurations

2. **Data validation**:
   - Review member IBAN data
   - Check mandate status and validity

3. **File generation process**:
   - Check batch creation workflow
   - Review error logs for specific issues

### Database Issues

**Q: Database corruption or inconsistency**

A: Database problems require careful handling:

1. **Database integrity check**:
   ```bash
   # Connect to MariaDB console
   bench --site site_name mariadb

   # In MariaDB console:
   CHECK TABLE tabMember;
   ```

2. **Backup and restore**:
   ```bash
   bench backup
   bench restore backup_file
   ```

3. **Data repair**:
   ```bash
   bench migrate --skip-failing
   bench rebuild-global-search
   ```

### Security Issues

**Q: Suspected security breach or unauthorized access**

A: Security incidents require immediate action:

1. **Change passwords**:
   - Reset all administrator passwords
   - Force password reset for all users
   - Rotate API keys

2. **Review access logs**:
   - Check user login logs
   - Review recent system activities
   - Monitor unusual access patterns

3. **System hardening**:
   - Update all system components
   - Review and tighten permissions
   - Enable two-factor authentication

## Performance Optimization

### Database Optimization

**Q: Database queries are slow**

A: Database performance optimization:

1. **Index optimization**:
   ```bash
   # Connect to MariaDB and run SQL commands
   bench --site site_name mariadb --execute "SHOW INDEX FROM tabMember;"
   bench --site site_name mariadb --execute "CREATE INDEX idx_email ON tabMember(email);"
   ```

2. **Query analysis**:
   ```bash
   # Analyze query performance
   bench --site site_name mariadb --execute "EXPLAIN SELECT * FROM tabMember WHERE email = 'test@example.com';"
   ```

3. **Database maintenance**:
   ```bash
   # Run database optimization
   bench --site site_name execute frappe.utils.doctor.optimize_database
   ```

### System Performance

**Q: Application response times are poor**

A: Application performance tuning:

1. **Cache configuration**:
   - Configure Redis cache properly
   - Enable appropriate caching strategies
   - Monitor cache hit rates

2. **Resource monitoring**:
   - Monitor server resource usage
   - Check for memory leaks
   - Review process resource consumption

3. **Background job optimization**:
   - Balance background job processing
   - Optimize job scheduling
   - Monitor job queue lengths

## Contact Support

### Self-Help Resources

Before contacting support, try these resources:

1. **Documentation**:
   - Read relevant user guides
   - Check API documentation
   - Review installation guides

2. **System Diagnostics**:
   - Run built-in diagnostic tests
   - Check system status indicators
   - Review error logs

3. **Community Resources**:
   - Search community forums
   - Check GitHub issues
   - Review known issues lists

### Support Channels

#### Technical Support
- **Email**: support@yourorganization.org
- **Response Time**: 24-48 hours during business days
- **Escalation**: Available for urgent issues

#### User Support
- **Email**: help@yourorganization.org
- **Phone**: [Support Phone Number]
- **Business Hours**: Monday-Friday, 9:00-17:00 CET

#### Emergency Support
- **Critical Issues**: Available 24/7 for production systems
- **Contact**: emergency@yourorganization.org
- **Response Time**: 2-4 hours

### Information to Provide

When contacting support, include:

1. **System Information**:
   - Verenigingen version
   - ERPNext version
   - Server operating system
   - Browser and version

2. **Issue Details**:
   - Detailed description of the problem
   - Steps to reproduce the issue
   - Error messages (exact text)
   - Screenshots if applicable

3. **Impact Assessment**:
   - Number of users affected
   - Business impact severity
   - Urgency of resolution needed

4. **Attempted Solutions**:
   - What you've already tried
   - Results of troubleshooting steps
   - Any temporary workarounds

### Support Ticket Priority

#### Critical (4-hour response)
- System completely down
- Data loss or corruption
- Security breaches
- Payment processing failures

#### High (8-hour response)
- Major functionality broken
- Multiple users affected
- Integration failures
- Performance severely degraded

#### Medium (24-hour response)
- Single feature not working
- Workaround available
- Configuration issues
- Minor data inconsistencies

#### Low (48-72 hour response)
- Enhancement requests
- Documentation clarifications
- Training questions
- Non-urgent issues

---

This FAQ and troubleshooting guide covers the most common issues and questions. For specific technical problems not covered here, please contact support with detailed information about your issue.

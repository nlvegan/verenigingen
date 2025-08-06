# Verenigingen System Error Recovery Guide

**Document Version:** 1.0
**Date:** August 2025
**Last Updated:** Initial Creation
**Audience:** System Users, Technical Support, System Administrators

## Overview

This comprehensive guide provides step-by-step error recovery procedures for common failure scenarios in the Verenigingen association management system. Each section includes symptom identification, root cause analysis, recovery procedures, and preventive measures.

## Additional Resources

- **[Quick Reference Card](QUICK_REFERENCE_CARD.md)** - Emergency procedures for print/quick access
- **[Practical Error Examples](PRACTICAL_ERROR_EXAMPLES.md)** - Real error messages with step-by-step solutions
- **[Monitoring Troubleshooting](../monitoring/TROUBLESHOOTING_GUIDE.md)** - System monitoring and alerts guide

## Quick Emergency Response

### 🚨 **CRITICAL**: System Down Completely
1. **Immediate Actions (< 5 minutes)**
   ```bash
   # Check service status
   bench status

   # Emergency restart
   bench restart

   # Test basic functionality
   curl -f http://localhost/desk
   ```

2. **If still down**: Contact technical support immediately
3. **Log location**: `/home/frappe/frappe-bench/logs/bench.log`

### Emergency Contacts
- **Technical Support Level 1**: [Contact Info]
- **Critical Escalation**: [Contact Info]
- **After Hours**: [Contact Info]

---

## Payment System Failures

### SEPA Direct Debit Failures

#### Symptoms
- Error message: "SEPA mandate validation failed"
- Payment status shows "Failed" in batch processing
- Members receive notifications about failed payments
- Dashboard shows declined direct debit transactions

#### Root Causes
- **Invalid IBAN**: Incorrect or expired bank account details
- **Insufficient Funds**: Member account has insufficient balance
- **Mandate Expiry**: SEPA mandate has expired or been cancelled
- **Bank Rejection**: Bank-specific validation failures
- **System Integration**: Connection issues with banking systems

#### Diagnostic Commands
```bash
# Check recent SEPA failures
bench --site dev.veganisme.net mariadb -e "
SELECT m.name, m.first_name, m.last_name, sb.status, sb.error_message
FROM \`tabMember\` m
JOIN \`tabSEPA Mandate\` sm ON m.name = sm.member
JOIN \`tabDirect Debit Batch\` sb ON sm.name = sb.sepa_mandate
WHERE sb.status = 'Failed'
AND sb.creation >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY sb.creation DESC;"

# Check mandate status
bench --site dev.veganisme.net execute vereinigingen.utils.sepa_validator.validate_mandates

# Test SEPA connectivity
bench --site dev.veganisme.net execute vereinigingen.utils.sepa_mandate_service.test_connection
```

#### Recovery Steps

**1. Individual Payment Failures**
```bash
# Identify failed payment
bench --site dev.veganisme.net mariadb -e "
SELECT name, member, error_message
FROM \`tabDirect Debit Batch\`
WHERE status = 'Failed' AND name = '[BATCH_ID]';"

# Check mandate validity
bench --site dev.veganisme.net console
>>> import frappe
>>> mandate = frappe.get_doc("SEPA Mandate", "[MANDATE_ID]")
>>> print(f"Status: {mandate.status}, IBAN: {mandate.iban}")
>>> # Validate IBAN
>>> from verenigingen.utils.iban_validator import validate_iban
>>> print(validate_iban(mandate.iban))
```

**2. Bulk Failure Recovery**
```bash
# Generate retry batch for failed payments
bench --site dev.veganisme.net execute verenigingen.utils.sepa_retry_manager.create_retry_batch --args "['[ORIGINAL_BATCH_ID]']"

# Process retry with updated mandates
bench --site dev.veganisme.net execute verenigingen.utils.sepa_admin_reporting.process_retry_batch --args "['[RETRY_BATCH_ID]']"
```

**3. Mandate Renewal Process**
```bash
# Generate mandate renewal notifications
bench --site dev.veganisme.net execute verenigingen.utils.sepa_notification_manager.send_mandate_renewal_requests

# Bulk update expired mandates
bench --site dev.veganisme.net execute verenigingen.utils.sepa_mandate_lifecycle_manager.bulk_renew_mandates
```

#### Prevention
- **Monthly**: Review mandate expiry dates
- **Quarterly**: Validate all active mandates
- **Before each batch**: Run pre-validation checks
- **Setup**: Automated mandate renewal reminders

---

### Mandate Creation Errors

#### Symptoms
- Error: "Failed to create SEPA mandate"
- Incomplete member registration process
- Members unable to complete payment setup
- Missing mandate records in system

#### Diagnostic Steps
```bash
# Check recent mandate creation attempts
bench --site dev.veganisme.net mariadb -e "
SELECT name, member, status, creation, error_log
FROM \`tabSEPA Mandate\`
WHERE creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY creation DESC;"

# Validate IBAN format issues
bench --site dev.veganisme.net execute vereinigingen.utils.sepa_input_validation.diagnose_iban_failures
```

#### Recovery Steps
```bash
# Manual mandate creation for specific member
bench --site dev.veganisme.net console
>>> from vereinigingen.utils.sepa_mandate_service import SEPAMandateService
>>> service = SEPAMandateService()
>>> result = service.create_mandate(
...     member="[MEMBER_ID]",
...     iban="[VALIDATED_IBAN]",
...     bic="[BIC_CODE]",
...     account_holder="[FULL_NAME]"
... )
>>> print(f"Mandate created: {result}")

# Bulk mandate creation from CSV
bench --site dev.veganisme.net execute verenigingen.utils.sepa_mandate_service.bulk_create_from_csv --args "['/path/to/mandate_data.csv']"
```

#### Prevention
- Enhanced IBAN validation on frontend
- Real-time BIC code validation
- Clear error messages for users
- Fallback manual creation process

---

### Payment Reconciliation Issues

#### Symptoms
- Payments marked as "Unreconciled" for extended periods
- Duplicate payment entries
- Missing payment records
- Mismatched amounts between bank and system

#### Diagnostic Commands
```bash
# Find unreconciled payments
bench --site dev.veganisme.net execute verenigingen.api.get_unreconciled_payments.get_unreconciled_payments

# Check for duplicate payments
bench --site dev.veganisme.net mariadb -e "
SELECT reference_no, COUNT(*) as count, SUM(paid_amount) as total
FROM \`tabPayment Entry\`
WHERE reference_no IS NOT NULL
GROUP BY reference_no
HAVING count > 1;"

# Analyze reconciliation gaps
bench --site dev.veganisme.net execute vereinigingen.utils.payment_utils.analyze_reconciliation_gaps
```

#### Recovery Steps
```bash
# Auto-reconcile by reference number
bench --site dev.veganisme.net execute vereinigingen.utils.sepa_reconciliation.auto_reconcile_payments

# Manual reconciliation for specific payment
bench --site dev.veganisme.net console
>>> from vereinigungen.utils.payment_utils import reconcile_payment
>>> reconcile_payment(
...     payment_entry="[PAYMENT_ID]",
...     bank_transaction="[TRANSACTION_REF]",
...     match_amount=True
... )

# Fix duplicate payments
bench --site dev.veganisme.net execute vereinigingen.utils.payment_utils.resolve_duplicate_payments
```

---

## Portal Access Issues

### Login Failures and Password Resets

#### Symptoms
- "Invalid username or password" errors
- Users unable to access member portal
- Password reset emails not received
- Account lockout messages

#### Diagnostic Steps
```bash
# Check user account status
bench --site dev.veganisme.net mariadb -e "
SELECT name, enabled, creation, last_login, login_after
FROM \`tabUser\`
WHERE name = '[USER_EMAIL]';"

# Check authentication logs
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabError Log\`
WHERE error LIKE '%authentication%'
AND creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY creation DESC
LIMIT 10;"

# Validate email configuration
bench --site dev.veganisme.net execute frappe.core.doctype.user.user.test_password_strength
```

#### Recovery Steps
```bash
# Reset user password (admin action)
bench --site dev.veganisme.net set-password [USER_EMAIL]

# Enable locked user account
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "[USER_EMAIL]")
>>> user.enabled = 1
>>> user.login_after = None
>>> user.save()

# Regenerate password reset email
bench --site dev.veganisme.net console
>>> from frappe.core.doctype.user.user import reset_password
>>> reset_password("[USER_EMAIL]")

# Bulk password reset for multiple users
bench --site dev.veganisme.net execute vereinigingen.utils.member_portal_utils.bulk_password_reset --args "['[CSV_FILE_PATH]']"
```

#### Prevention
- Clear password complexity requirements
- Automated account unlock after time period
- Enhanced email delivery monitoring
- Self-service password reset improvements

---

### Permission Denied Errors

#### Symptoms
- "You don't have permission to access this resource"
- Missing menu items or pages
- Partial page loading
- API endpoint access denied

#### Diagnostic Commands
```bash
# Check user roles and permissions
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "[USER_EMAIL]")
>>> print(f"Roles: {user.get_roles()}")
>>> print(f"Permissions: {frappe.get_user().get_roles()}")

# Test specific permission
bench --site dev.veganisme.net console
>>> import frappe
>>> print(frappe.has_permission("Member", "read", user="[USER_EMAIL]"))
>>> print(frappe.has_permission("Membership Application", "write", user="[USER_EMAIL]"))

# Check role permissions
bench --site dev.veganisme.net execute verenigingen.api.check_specific_report_permissions.check_user_permissions --args "['[USER_EMAIL]']"
```

#### Recovery Steps
```bash
# Assign missing role to user
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "[USER_EMAIL]")
>>> user.append("roles", {"role": "[REQUIRED_ROLE]"})
>>> user.save()

# Fix member portal permissions
bench --site dev.veganisme.net execute vereinigingen.api.fix_customer_permissions.fix_member_permissions --args "['[USER_EMAIL]']"

# Clear permission cache
bench --site dev.veganisme.net execute vereinigingen.utils.clear_permission_cache.clear_cache --args "['[USER_EMAIL]']"

# Bulk permission fix for member category
bench --site dev.veganisme.net execute verenigigingen.utils.member_portal_utils.fix_member_category_permissions --args "['[MEMBER_TYPE]']"
```

---

### Session Timeout Issues

#### Symptoms
- Frequent logouts during active use
- "Session expired" messages
- Loss of form data
- Inability to perform actions

#### Recovery Steps
```bash
# Extend session timeout (system-wide)
bench --site dev.veganisme.net console
>>> import frappe
>>> frappe.db.set_value("System Settings", None, "session_expiry", "24:00:00")
>>> frappe.db.commit()

# Check session configuration
bench --site dev.veganisme.net execute frappe.sessions.get_session_data

# Clear stuck sessions
bench --site dev.veganisme.net mariadb -e "DELETE FROM \`tabSessions\` WHERE creation < DATE_SUB(NOW(), INTERVAL 1 DAY);"
```

#### Prevention
- Increase session timeout for portal users
- Implement session extension warnings
- Auto-save form data
- Graceful session renewal

---

## Data Processing Errors

### Import Failures

#### Symptoms
- "Import failed" notifications
- Partial data import
- Data validation errors during import
- Corrupted or missing records

#### Common Import Types and Recovery

**Member Data Import**
```bash
# Diagnose member import issues
bench --site dev.veganisme.net execute verenigingen.utils.data_quality_utils.validate_member_import --args "['[IMPORT_FILE_PATH]']"

# Fix member data validation
bench --site dev.veganisme.net execute verenigingen.utils.member_portal_utils.fix_member_data_issues

# Retry failed member imports
bench --site dev.veganisme.net console
>>> from verenigingen.utils import application_helpers
>>> result = application_helpers.retry_failed_imports(doctype="Member")
>>> print(f"Retry result: {result}")
```

**Financial Data Import**
```bash
# Check eBoekhouden import status
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_api.check_import_status

# Retry failed transactions
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.migration_api.retry_failed_mutations --args "['[MUTATION_ID]']"

# Validate financial data integrity
bench --site dev.veganisme.net execute verenigingen.utils.payment_utils.validate_financial_integrity
```

#### General Import Recovery
```bash
# Check import logs
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabData Import\`
WHERE status = 'Error'
AND creation >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY creation DESC;"

# Cleanup partial imports
bench --site dev.veganisme.net execute frappe.core.page.data_import.data_import.cancel_data_import --args "['[IMPORT_ID]']"

# Bulk retry imports
bench --site dev.veganisme.net execute vereinigingen.utils.data_quality_utils.bulk_retry_imports
```

---

### Validation Errors During Form Submission

#### Symptoms
- Form submission fails with validation messages
- "Mandatory field missing" errors
- Data format validation failures
- Custom validation rule failures

#### Common Validation Issues

**Member Registration Validation**
```bash
# Check member validation rules
bench --site dev.veganisme.net console
>>> from vereinigungen.utils.member_portal_utils import validate_member_data
>>> result = validate_member_data({
...     "first_name": "[FIRST_NAME]",
...     "last_name": "[LAST_NAME]",
...     "email": "[EMAIL]",
...     "phone": "[PHONE]"
... })
>>> print(f"Validation result: {result}")

# Fix phone number formatting
bench --site dev.veganisme.net execute vereinigingen.utils.dutch_name_utils.standardize_phone_numbers

# Validate email addresses
bench --site dev.veganisme.net execute vereinigingen.utils.member_portal_utils.validate_email_addresses
```

**SEPA Validation Errors**
```bash
# Test IBAN validation
bench --site dev.veganisme.net execute vereinigingen.utils.sepa_input_validation.validate_iban --args "['[IBAN]']"

# Fix BIC code validation
bench --site dev.veganisme.net execute verenigigingen.utils.sepa_validator.validate_bic --args "['[BIC]']"
```

#### Recovery Steps
```bash
# Bypass validation temporarily (admin only)
bench --site dev.veganisme.net console
>>> import frappe
>>> doc = frappe.get_doc("[DOCTYPE]", "[DOCUMENT_ID]")
>>> doc.flags.ignore_validate = True
>>> doc.save()

# Fix validation rules
bench --site dev.veganisme.net execute verenigigingen.validations.fix_validation_rules

# Bulk fix validation issues
bench --site dev.veganisme.net execute verenigigingen.utils.data_quality_utils.bulk_fix_validation_errors --args "['[DOCTYPE]']"
```

---

### Duplicate Entry Prevention and Resolution

#### Symptoms
- "Duplicate entry" database errors
- Conflicting member records
- Multiple payment entries for same transaction
- Conflicting SEPA mandates

#### Diagnostic Steps
```bash
# Find duplicate members by email
bench --site dev.veganisme.net mariadb -e "
SELECT email, COUNT(*) as count, GROUP_CONCAT(name) as member_ids
FROM \`tabMember\`
WHERE email IS NOT NULL
GROUP BY email
HAVING count > 1;"

# Find duplicate SEPA mandates
bench --site dev.veganisme.net mariadb -e "
SELECT iban, COUNT(*) as count, GROUP_CONCAT(name) as mandate_ids
FROM \`tabSEPA Mandate\`
WHERE status = 'Active'
GROUP BY iban
HAVING count > 1;"

# Check duplicate payments
bench --site dev.veganisme.net execute verenigingen.utils.payment_utils.find_duplicate_payments
```

#### Resolution Steps
```bash
# Merge duplicate members
bench --site dev.veganisme.net execute verenigigingen.utils.member_portal_utils.merge_duplicate_members --args "['[PRIMARY_ID]', '[DUPLICATE_ID]']"

# Resolve duplicate mandates
bench --site dev.veganisme.net execute verenigingen.utils.sepa_mandate_service.resolve_duplicate_mandates

# Fix duplicate payments
bench --site dev.veganisme.net execute vereinigingen.utils.payment_utils.merge_duplicate_payments --args "['[PAYMENT_IDS]']"
```

---

## Integration Failures

### eBoekhouden Connection Errors

#### Symptoms
- "API connection timeout" errors
- Authentication failures with eBoekhouden
- Data sync interruptions
- Missing financial data

#### Diagnostic Commands
```bash
# Test eBoekhouden connectivity
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_rest_client.test_connection

# Check API credentials
bench --site dev.veganisme.net console
>>> from verenigingen.e_boekhouden.utils.security_helper import test_api_credentials
>>> result = test_api_credentials()
>>> print(f"Credentials valid: {result}")

# View recent API errors
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabError Log\`
WHERE error LIKE '%boekhouden%'
AND creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY creation DESC
LIMIT 10;"
```

#### Recovery Steps
```bash
# Refresh API credentials
bench --site dev.veganisme.net execute vereinigingen.e_boekhouden.utils.eboekhouden_api.refresh_credentials

# Retry failed API calls
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.migration_api.retry_failed_api_calls

# Manual data sync
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_migration_config.manual_sync --args "['[START_DATE]', '[END_DATE]']"

# Reset API connection
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_rest_client.reset_connection
```

#### Prevention
- Automated API health monitoring
- Retry mechanisms with exponential backoff
- Connection pooling and timeout management
- Regular credential validation

---

### API Timeout and Rate Limiting

#### Symptoms
- "Request timeout" errors
- "Rate limit exceeded" messages
- Slow API response times
- Intermittent connection failures

#### Recovery Steps
```bash
# Check API rate limit status
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_api.check_rate_limits

# Implement request throttling
bench --site dev.veganisme.net console
>>> from verenigingen.utils.api_endpoint_optimizer import throttle_requests
>>> throttle_requests(delay_seconds=2)

# Retry with exponential backoff
bench --site dev.veganisme.net execute verenigingen.utils.payment_retry.retry_with_backoff --args "['[FUNCTION_NAME]', '[PARAMS]']"
```

---

### Webhook Failures

#### Symptoms
- Webhook endpoints returning errors
- Missing webhook notifications
- Payment status not updating
- Integration data out of sync

#### Diagnostic Steps
```bash
# Check webhook logs
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabWebhook Request Log\`
WHERE status != 'Success'
AND creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY creation DESC;"

# Test webhook endpoint
curl -X POST http://localhost/api/method/verenigingen.api.webhook_handler \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# Validate webhook configuration
bench --site dev.veganisme.net execute verenigingen.utils.webhook_validator.validate_endpoints
```

#### Recovery Steps
```bash
# Retry failed webhooks
bench --site dev.veganisme.net execute verenigingen.api.webhook_handler.retry_failed_webhooks

# Reset webhook configuration
bench --site dev.veganisme.net execute verenigingen.utils.webhook_validator.reset_webhook_config

# Manual webhook processing
bench --site dev.veganisme.net execute verenigingen.api.webhook_handler.process_webhook_queue
```

---

### Email Delivery Issues

#### Symptoms
- Members not receiving notifications
- Email queue showing failed emails
- SMTP authentication errors
- Email templates not being sent

#### Diagnostic Commands
```bash
# Check email queue status
bench --site dev.veganisme.net mariadb -e "
SELECT status, COUNT(*) as count, MIN(creation) as oldest
FROM \`tabEmail Queue\`
GROUP BY status
ORDER BY count DESC;"

# Check recent email failures
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabEmail Queue\`
WHERE status = 'Error'
AND creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY creation DESC
LIMIT 10;"

# Test email configuration
bench --site dev.veganisme.net console
>>> import frappe
>>> frappe.sendmail(recipients=["test@example.com"], subject="Test", message="Test email")

# Check email templates status
bench --site dev.veganisme.net execute verenigingen.api.email_template_manager.check_template_status
```

#### Recovery Steps

**1. SMTP Configuration Issues**
```bash
# Check and fix SMTP settings
bench --site dev.veganisme.net console
>>> import frappe
>>> email_account = frappe.get_doc("Email Account", "Default")
>>> print(f"SMTP Server: {email_account.smtp_server}")
>>> print(f"Port: {email_account.smtp_port}")
>>> print(f"Use TLS: {email_account.use_tls}")

# Test SMTP connection
>>> email_account.test_smtp_connection()
```

**2. Failed Email Queue Processing**
```bash
# Retry failed emails
bench --site dev.veganisme.net execute frappe.email.queue.retry_sending

# Clear old failed emails (after investigation)
bench --site dev.veganisme.net mariadb -e "
DELETE FROM \`tabEmail Queue\`
WHERE status = 'Error'
AND creation < DATE_SUB(NOW(), INTERVAL 7 DAY);"

# Process pending emails manually
bench --site dev.veganisme.net execute frappe.email.queue.flush
```

**3. Email Template Issues**
```bash
# Recreate missing email templates
bench --site dev.veganisme.net execute verenigingen.api.email_template_manager.create_comprehensive_email_templates

# Test specific template
bench --site dev.veganisme.net execute verenigingen.utils.sepa_notification_manager.test_payment_notification_template

# Check template syntax
bench --site dev.veganisme.net execute verenigingen.api.email_template_manager.validate_all_templates
```

**4. Bulk Notification Recovery**
```bash
# Resend failed SEPA notifications
bench --site dev.veganisme.net execute verenigingen.utils.sepa_notification_manager.resend_failed_notifications --args "['2025-08-06']"

# Resend membership application notifications
bench --site dev.veganisme.net execute verenigingen.utils.application_notifications.resend_pending_notifications

# Test notification delivery
bench --site dev.veganisme.net execute verenigingen.utils.notification_helpers.test_notification_delivery --args "['member@example.com']"
```

#### Prevention
- Monitor email queue daily
- Set up email delivery alerts
- Regular SMTP connection testing
- Backup email configuration

---

## System-Level Issues

### Database Connection Problems

#### Symptoms
- "Database connection lost" errors
- Query timeout messages
- Slow database responses
- Connection pool exhaustion

#### Diagnostic Commands
```bash
# Check database status
bench --site dev.veganisme.net mariadb -e "SHOW STATUS LIKE 'Threads_%';"
bench --site dev.veganisme.net mariadb -e "SHOW PROCESSLIST;"

# Test database connectivity
bench --site dev.veganisme.net mariadb -e "SELECT 1;"

# Check connection pool status
bench --site dev.veganisme.net console
>>> import frappe
>>> print(frappe.db.sql("SHOW STATUS LIKE 'Max_used_connections';"))
```

#### Recovery Steps
```bash
# Restart database service
sudo systemctl restart mariadb
bench restart

# Kill long-running queries
bench --site dev.veganisme.net mariadb -e "
SELECT CONCAT('KILL ', id, ';') FROM information_schema.processlist
WHERE time > 300 AND info IS NOT NULL;"

# Optimize database tables
bench --site dev.veganisme.net mariadb -e "OPTIMIZE TABLE \`tabMember\`;"
bench --site dev.veganisme.net mariadb -e "OPTIMIZE TABLE \`tabPayment Entry\`;"

# Reset connection pool
bench restart
```

---

### Redis/Cache Issues

#### Symptoms
- Slow page loading
- Stale data display
- Cache-related errors
- Session management issues

#### Recovery Steps
```bash
# Check Redis status
redis-cli ping

# Clear all cache
bench --site dev.veganisme.net clear-cache
bench --site dev.veganisme.net clear-website-cache

# Restart Redis
sudo systemctl restart redis
bench restart

# Test cache functionality
bench --site dev.veganisme.net console
>>> import frappe
>>> frappe.cache().set_value("test", "value")
>>> print(frappe.cache().get_value("test"))
```

---

### Background Job Failures

#### Symptoms
- Jobs stuck in "Queued" status
- Failed background jobs
- Email notifications not sent
- Scheduled tasks not running

#### Diagnostic Steps
```bash
# Check job queue status
bench --site dev.veganisme.net console
>>> import frappe
>>> jobs = frappe.get_all("RQ Job", fields=["name", "status", "job_name", "creation"], limit=20, order_by="creation desc")
>>> for job in jobs: print(f"{job.name}: {job.status} - {job.job_name}")

# Check scheduler status
bench --site dev.veganisme.net console
>>> print(frappe.utils.scheduler.is_scheduler_inactive())

# View failed jobs
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabRQ Job\`
WHERE status = 'failed'
AND creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY creation DESC
LIMIT 10;"
```

#### Recovery Steps
```bash
# Enable scheduler
bench --site dev.veganisme.net enable-scheduler

# Restart job workers
bench restart

# Retry failed jobs
bench --site dev.veganisme.net execute frappe.utils.background_jobs.retry_failed_jobs

# Clear job queue
bench --site dev.veganisme.net execute frappe.utils.background_jobs.clear_failed_jobs

# Manual job execution
bench --site dev.veganisme.net execute verenigingen.utils.background_jobs.process_stuck_jobs
```

---

## Escalation Procedures

### When to Escalate to Technical Support

**Immediate Escalation (Level 1)**:
- Complete system outage
- Database corruption
- Security breaches
- Data loss scenarios

**Standard Escalation (Level 2)**:
- Integration failures affecting multiple users
- Performance degradation > 50%
- Payment processing failures affecting > 10 transactions
- Data integrity issues

**Advisory Escalation (Level 3)**:
- Recurring issues requiring architectural changes
- Performance optimization needs
- Feature enhancement requests
- Training requirements

### Escalation Information Required

When escalating issues, provide:

1. **Issue Description**: Clear symptom description
2. **Error Messages**: Exact error text and codes
3. **User Impact**: Number of affected users
4. **Timeline**: When issue started and duration
5. **Steps Taken**: Recovery attempts made
6. **System State**: Output of diagnostic commands
7. **Business Impact**: Operational effects

### Documentation Requirements

For each incident:

```bash
# Generate system status report
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.generate_incident_report --args "['[INCIDENT_ID]']"

# Export error logs
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabError Log\`
WHERE creation >= '[INCIDENT_START_TIME]'
ORDER BY creation DESC;" > /tmp/incident_errors.csv

# System health snapshot
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.get_system_health > /tmp/system_health.json
```

---

## Preventive Measures

### Daily Checks
- [ ] Monitor system health dashboard
- [ ] Review error log summary
- [ ] Check payment processing status
- [ ] Verify backup completion

### Weekly Checks
- [ ] Review performance metrics
- [ ] Validate integration connections
- [ ] Check user access issues
- [ ] Update system documentation

### Monthly Checks
- [ ] Review recurring issues
- [ ] Update recovery procedures
- [ ] Test backup restoration
- [ ] Conduct user training

### Quarterly Reviews
- [ ] Assess system architecture
- [ ] Plan infrastructure upgrades
- [ ] Review security measures
- [ ] Update disaster recovery plans

---

## Useful Commands Reference

### System Health
```bash
# Complete system check
bench doctor

# Resource usage
bench --site dev.veganisme.net execute vereinigingen.utils.resource_monitor.get_system_health

# Service status
bench status
```

### Database Operations
```bash
# Database repair
bench --site dev.veganisme.net mariadb-repair

# Backup database
bench --site dev.veganisme.net backup --with-files

# Restore database
bench --site dev.veganisme.net restore [backup-file]
```

### Application Operations
```bash
# Clear all caches
bench --site dev.veganisme.net clear-cache
bench --site dev.veganisme.net clear-website-cache

# Run migrations
bench --site dev.veganisme.net migrate

# Rebuild search index
bench --site dev.veganisme.net rebuild-global-search
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | August 2025 | Initial creation with comprehensive error recovery procedures |

---

**Document Control:**
- **Owner**: Technical Team
- **Review Frequency**: Quarterly
- **Last Review**: August 2025
- **Next Review**: November 2025
- **Version Control**: Maintained in git repository

**Note**: This guide should be kept up-to-date with system changes. Report any inaccuracies or missing scenarios to the technical team.

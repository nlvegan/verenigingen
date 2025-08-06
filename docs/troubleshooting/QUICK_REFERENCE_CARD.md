# Verenigingen Error Recovery - Quick Reference Card

**Print and keep handy for emergency situations**

## 🚨 EMERGENCY - System Down

```bash
# 1. Check status
bench status

# 2. Emergency restart
bench restart

# 3. Test access
curl -f http://localhost/desk

# 4. If still down - call technical support immediately
```

## 💳 Payment Failures (Most Common)

### SEPA Direct Debit Failed
```bash
# Check failures
bench --site dev.veganisme.net mariadb -e "
SELECT m.first_name, m.last_name, sb.status, sb.error_message
FROM \`tabMember\` m
JOIN \`tabSEPA Mandate\` sm ON m.name = sm.member
JOIN \`tabDirect Debit Batch\` sb ON sm.name = sb.sepa_mandate
WHERE sb.status = 'Failed'
ORDER BY sb.creation DESC LIMIT 10;"

# Create retry batch
bench --site dev.veganisme.net execute vereinigingen.utils.sepa_retry_manager.create_retry_batch --args "['BATCH_ID']"
```

### Mandate Creation Failed
```bash
# Manual mandate creation
bench --site dev.veganisme.net console
>>> from vereinigingen.utils.sepa_mandate_service import SEPAMandateService
>>> service = SEPAMandateService()
>>> service.create_mandate(member="MEMBER_ID", iban="VALIDATED_IBAN", bic="BIC_CODE")
```

## 🔐 Portal Access Issues

### Login Failed
```bash
# Reset password
bench --site dev.veganisme.net set-password user@email.com

# Enable locked account
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "user@email.com")
>>> user.enabled = 1
>>> user.login_after = None
>>> user.save()
```

### Permission Denied
```bash
# Fix member permissions
bench --site dev.veganisme.net execute vereinigingen.api.fix_customer_permissions.fix_member_permissions --args "['user@email.com']"

# Clear cache
bench --site dev.veganisme.net execute verenigigingen.utils.clear_permission_cache.clear_cache --args "['user@email.com']"
```

## 📊 Data Import Errors

### Member Import Failed
```bash
# Diagnose issues
bench --site dev.veganisme.net execute verenigingen.utils.data_quality_utils.validate_member_import --args "['/path/to/file.csv']"

# Retry failed imports
bench --site dev.veganisme.net console
>>> from verenigingen.utils import application_helpers
>>> result = application_helpers.retry_failed_imports(doctype="Member")
```

### eBoekhouden Sync Failed
```bash
# Check status
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_api.check_import_status

# Retry failed mutations
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.migration_api.retry_failed_mutations --args "['MUTATION_ID']"
```

## 💾 Database Issues

### Connection Lost
```bash
# Test connection
bench --site dev.veganisme.net mariadb -e "SELECT 1;"

# Restart database
sudo systemctl restart mariadb
bench restart
```

### Slow Performance
```bash
# Check processes
bench --site dev.veganisme.net mariadb -e "SHOW PROCESSLIST;"

# Kill long queries
bench --site dev.veganisme.net mariadb -e "
SELECT CONCAT('KILL ', id, ';') FROM information_schema.processlist
WHERE time > 300;"
```

## 🔄 Background Jobs Stuck

```bash
# Check status
bench --site dev.veganisme.net console
>>> import frappe
>>> jobs = frappe.get_all("RQ Job", fields=["name", "status", "job_name"], limit=10, order_by="creation desc")

# Enable scheduler
bench --site dev.veganisme.net enable-scheduler

# Restart workers
bench restart

# Clear failed jobs
bench --site dev.veganisme.net execute frappe.utils.background_jobs.clear_failed_jobs
```

## 📧 Email Issues

### Test Email Delivery
```bash
bench --site dev.veganisme.net console
>>> import frappe
>>> frappe.sendmail(recipients=["test@example.com"], subject="Test", message="Test email")
```

### Check Email Queue
```bash
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabEmail Queue\`
WHERE status != 'Sent'
ORDER BY creation DESC LIMIT 10;"
```

## 🔍 System Health Check

```bash
# Complete system check
bench doctor

# Resource usage
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.get_system_health

# Recent errors
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabError Log\`
WHERE creation >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
ORDER BY creation DESC LIMIT 10;"
```

## 🆘 Emergency Contacts

- **Technical Support Level 1**: [Contact Info]
- **Critical Escalation**: [Contact Info]
- **After Hours Emergency**: [Contact Info]

## 📋 Information to Gather Before Calling Support

1. **Exact error message** (copy/paste)
2. **Number of users affected**
3. **What you were trying to do**
4. **When it started happening**
5. **Output of system health check**

---

**Keep this card accessible during system operation**
For detailed procedures, see: [Error Recovery Guide](ERROR_RECOVERY_GUIDE.md)

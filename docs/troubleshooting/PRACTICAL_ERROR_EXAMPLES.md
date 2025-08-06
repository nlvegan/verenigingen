# Practical Error Examples and Solutions

This document provides real-world error scenarios with actual error messages and step-by-step solutions.

## Payment System Errors

### Example 1: SEPA Direct Debit Rejection

**Error Message:**
```
SEPA Payment Failed: AM04 - Insufficient Funds
Member: Jan de Vries (M-2025-0142)
Amount: €25.00
IBAN: NL91ABNA0417164300
```

**Immediate Actions:**
1. **Document the failure**:
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT * FROM \`tabDirect Debit Batch\`
   WHERE reference_no LIKE '%M-2025-0142%'
   AND status = 'Failed';"
   ```

2. **Check member's mandate status**:
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> member = frappe.get_doc("Member", "M-2025-0142")
   >>> mandate = frappe.get_doc("SEPA Mandate", {"member": member.name})
   >>> print(f"Mandate Status: {mandate.status}")
   >>> print(f"IBAN: {mandate.iban}")
   ```

3. **Create manual invoice and notify member**:
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.create_manual_invoice --args "['M-2025-0142', 25.00, 'SEPA payment failed - insufficient funds']"
   ```

4. **Send notification email**:
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.sepa_notification_manager.send_payment_failure_notification --args "['M-2025-0142', 'AM04']"
   ```

**Follow-up Actions:**
- Schedule retry in 7 days
- Update member about bank account requirements
- Consider payment plan options

---

### Example 2: Mandate Creation Validation Error

**Error Message:**
```
ValidationError: Invalid IBAN format
Field: iban
Value: NL91ABNA041716430
Expected format: NL followed by 2 digits and 18 characters
```

**Recovery Steps:**

1. **Validate IBAN manually**:
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.sepa_input_validation.validate_iban --args "['NL91ABNA041716430']"
   ```

2. **Check IBAN format requirements**:
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.utils.iban_validator import validate_iban, format_iban
   >>> corrected_iban = format_iban("NL91ABNA041716430")
   >>> print(f"Corrected IBAN: {corrected_iban}")
   >>> is_valid = validate_iban(corrected_iban)
   >>> print(f"Valid: {is_valid}")
   ```

3. **Create mandate with corrected IBAN**:
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.utils.sepa_mandate_service import SEPAMandateService
   >>> service = SEPAMandateService()
   >>> result = service.create_mandate(
   ...     member="M-2025-0156",
   ...     iban="NL91ABNA0417164300",  # Corrected
   ...     bic="ABNANL2A",
   ...     account_holder="Maria van der Berg"
   ... )
   >>> print(f"Mandate created: {result}")
   ```

---

## Portal Access Errors

### Example 3: Login Failure After Password Reset

**Error Message:**
```
Authentication Failed: User account is disabled
User: member@veganisme.org
Last login attempt: 2025-08-06 14:30:22
```

**Diagnostic Steps:**
```bash
# Check user account status
bench --site dev.veganisme.net mariadb -e "
SELECT name, enabled, last_login, login_after, creation
FROM \`tabUser\`
WHERE name = 'member@veganisme.org';"
```

**Expected Output:**
```
+------------------------+---------+-------------+---------------------+---------------------+
| name                   | enabled | last_login  | login_after         | creation            |
+------------------------+---------+-------------+---------------------+---------------------+
| member@veganisme.org   |       0 | NULL        | 2025-08-07 00:00:00 | 2025-01-15 10:22:33 |
+------------------------+---------+-------------+---------------------+---------------------+
```

**Recovery Steps:**
```bash
# Enable account and clear login restrictions
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "member@veganisme.org")
>>> user.enabled = 1
>>> user.login_after = None
>>> user.save()
>>> print("Account enabled successfully")

# Send new password reset email
>>> from frappe.core.doctype.user.user import reset_password
>>> reset_password("member@veganisme.org")
>>> print("Password reset email sent")
```

**Verification:**
```bash
bench --site dev.veganisme.net mariadb -e "
SELECT name, enabled, login_after
FROM \`tabUser\`
WHERE name = 'member@veganisme.org';"
```

---

### Example 4: Permission Denied on Member Dashboard

**Error Message:**
```
PermissionError: You don't have permission to access Member records
User: volunteer@chapter-amsterdam.nl
Role: Verenigingen Volunteer
Requested: Read access to Member
```

**Diagnostic Commands:**
```bash
# Check user's roles
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "volunteer@chapter-amsterdam.nl")
>>> roles = [role.role for role in user.roles]
>>> print(f"User roles: {roles}")

# Check specific permission
>>> has_permission = frappe.has_permission("Member", "read", user="volunteer@chapter-amsterdam.nl")
>>> print(f"Has Member read permission: {has_permission}")
```

**Expected Issues:**
- Missing "Verenigingen Member" role
- Incorrect role profile assignment
- Chapter-based access restrictions

**Resolution:**
```bash
# Add required role
bench --site dev.veganisme.net console
>>> import frappe
>>> user = frappe.get_doc("User", "volunteer@chapter-amsterdam.nl")
>>> user.append("roles", {"role": "Verenigingen Member"})
>>> user.save()

# Apply correct role profile
>>> user.role_profile_name = "Verenigingen Chapter Volunteer"
>>> user.save()

# Clear permission cache
>>> frappe.clear_cache(user="volunteer@chapter-amsterdam.nl")
```

---

## Data Processing Errors

### Example 5: Member Import Validation Failure

**Error Message:**
```
ImportError: Row 15: Missing required field 'email'
ImportError: Row 23: Invalid phone number format '+31-6-12345678'
ImportError: Row 31: Duplicate email 'jan@example.com' found in system
File: member_import_2025-08-06.csv
```

**Step-by-Step Recovery:**

1. **Analyze import file**:
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.data_quality_utils.analyze_import_file --args "['/path/to/member_import_2025-08-06.csv']"
   ```

2. **Fix validation issues manually**:
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> import csv

   # Load and fix CSV data
   >>> with open('/path/to/member_import_2025-08-06.csv', 'r') as f:
   ...     reader = csv.DictReader(f)
   ...     for i, row in enumerate(reader, 1):
   ...         if i == 15:  # Missing email
   ...             print(f"Row 15 - Name: {row.get('first_name')} {row.get('last_name')}")
   ...             print("Add email manually or contact member")
   ...         elif i == 23:  # Phone format
   ...             from verenigingen.utils.dutch_name_utils import format_phone_number
   ...             formatted = format_phone_number(row.get('phone'))
   ...             print(f"Row 23 - Original: {row.get('phone')}, Formatted: {formatted}")
   ...         elif i == 31:  # Duplicate email
   ...             existing = frappe.db.get_value("Member", {"email": row.get('email')}, "name")
   ...             print(f"Row 31 - Email {row.get('email')} already exists in Member {existing}")
   ```

3. **Create corrected import file**:
   ```bash
   # Fix issues in CSV file manually or programmatically
   bench --site dev.veganisme.net execute verenigingen.utils.data_quality_utils.create_corrected_import --args "['/path/to/member_import_2025-08-06.csv', '/path/to/member_import_corrected.csv']"
   ```

4. **Retry import with corrected data**:
   ```bash
   bench --site dev.veganisme.net execute frappe.core.page.data_import.data_import.upload_csv --args "['/path/to/member_import_corrected.csv', 'Member']"
   ```

---

## Integration Failures

### Example 6: eBoekhouden API Connection Timeout

**Error Message:**
```
ConnectionTimeout: Request to eBoekhouden API timed out after 30 seconds
Endpoint: https://api.e-boekhouden.nl/v1/mutations
Method: POST
Last successful connection: 2025-08-06 12:15:33
```

**Diagnostic Steps:**
```bash
# Test basic connectivity
curl -I https://api.e-boekhouden.nl/v1/status

# Test API credentials
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_rest_client.test_connection
```

**Recovery Actions:**
```bash
# Check API rate limits
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_api.check_rate_limits

# Retry with exponential backoff
bench --site dev.veganisme.net execute verenigingen.utils.payment_retry.retry_with_backoff --args "['verenigingen.e_boekhouden.utils.migration_api.sync_mutations', '{}']"

# If still failing, use manual sync
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_migration_config.manual_sync --args "['2025-08-06', '2025-08-06']"
```

---

### Example 7: Background Job Stuck in Queue

**Error Message:**
```
Job Status: STUCK
Job Name: verenigingen.utils.sepa_xml_enhanced_generator.generate_batch
Queue: default
Created: 2025-08-06 10:30:00
Last Activity: 2025-08-06 10:31:15
Error: Worker process killed unexpectedly
```

**Recovery Process:**

1. **Check job details**:
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> job = frappe.get_doc("RQ Job", "[JOB_ID]")
   >>> print(f"Status: {job.status}")
   >>> print(f"Error: {job.exc_info}")
   ```

2. **Clear stuck job**:
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> job = frappe.get_doc("RQ Job", "[JOB_ID]")
   >>> job.status = "failed"
   >>> job.save()
   ```

3. **Restart workers**:
   ```bash
   bench restart

   # Check worker status
   ps aux | grep -E "(rq|worker)"
   ```

4. **Manually execute the task**:
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.sepa_xml_enhanced_generator.generate_batch --args "['[BATCH_ID]']"
   ```

---

## System-Level Errors

### Example 8: Database Connection Pool Exhausted

**Error Message:**
```
DatabaseError: (1040, 'Too many connections')
Connection pool: 50/50 active connections
Query: SELECT name FROM tabMember WHERE status = 'Active'
Time: 2025-08-06 15:45:22
```

**Immediate Response:**
```bash
# Check current connections
bench --site dev.veganisme.net mariadb -e "SHOW STATUS LIKE 'Threads_%';"
bench --site dev.veganisme.net mariadb -e "SHOW PROCESSLIST;"
```

**Kill long-running queries**:
```bash
bench --site dev.veganisme.net mariadb -e "
SELECT CONCAT('KILL ', id, ';') as kill_command
FROM information_schema.processlist
WHERE time > 300
AND info IS NOT NULL;"
```

**Execute the kill commands manually, then**:
```bash
# Restart services
sudo systemctl restart mariadb
bench restart

# Verify connection count
bench --site dev.veganisme.net mariadb -e "SHOW STATUS LIKE 'Max_used_connections';"
```

**Long-term Fix:**
```bash
# Increase connection limits in MariaDB configuration
sudo nano /etc/mysql/mariadb.conf.d/50-server.cnf
# Add: max_connections = 200

sudo systemctl restart mariadb
```

---

## Performance Issues

### Example 9: Member Portal Extremely Slow

**Symptoms:**
- Page load times > 30 seconds
- Timeouts on member dashboard
- Browser shows "Page unresponsive"

**Performance Diagnosis:**
```bash
# Check server resources
top -n 1 | head -10
free -h
df -h

# Check database performance
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM information_schema.processlist
WHERE time > 5
ORDER BY time DESC;"

# Check slow query log
sudo tail -50 /var/log/mysql/slow.log
```

**Immediate Actions:**
```bash
# Clear all caches
bench --site dev.veganisme.net clear-cache
bench --site dev.veganisme.net clear-website-cache
bench restart

# Optimize critical tables
bench --site dev.veganisme.net mariadb -e "OPTIMIZE TABLE \`tabMember\`;"
bench --site dev.veganisme.net mariadb -e "OPTIMIZE TABLE \`tabPayment Entry\`;"
```

**Performance Monitoring:**
```bash
# Enable performance monitoring
bench --site dev.veganisme.net execute verenigingen.utils.performance_monitoring.enable_detailed_logging

# Generate performance report
bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.generate_report --args "['member_portal']"
```

---

## Documentation and Logging

### Creating Incident Reports

After resolving any issue, create an incident report:

```bash
# Generate comprehensive incident report
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.generate_incident_report --args "['INCIDENT_2025-08-06-001']"

# Export relevant logs
bench --site dev.veganisme.net mariadb -e "
SELECT * FROM \`tabError Log\`
WHERE creation >= '2025-08-06 10:00:00'
AND creation <= '2025-08-06 16:00:00'
ORDER BY creation DESC;" > incident_errors_2025-08-06.csv

# System health at time of incident
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.get_historical_health --args "['2025-08-06 15:00:00']" > system_health_incident.json
```

### Prevention Measures

After each incident, update prevention measures:

1. **Update monitoring thresholds** if issue wasn't detected early
2. **Add validation rules** to prevent similar data issues
3. **Improve error messages** for better user experience
4. **Document lessons learned** in this guide
5. **Test recovery procedures** to ensure they work

---

This document should be updated with new real-world examples as they occur. Each example helps improve system reliability and user support quality.

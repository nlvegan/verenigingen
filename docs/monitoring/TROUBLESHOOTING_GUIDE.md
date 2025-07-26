# Monitoring System Troubleshooting Guide

**Document Version:** 1.0
**Date:** July 2025
**Last Updated:** Implementation of Phase 2 Monitoring Dashboard
**Audience:** Technical Team, System Administrators

## Overview

This guide provides step-by-step troubleshooting procedures for common monitoring system issues, including dashboard problems, alert system failures, and performance degradation scenarios.

## Quick Reference

### Common Commands
```bash
# Check monitoring dashboard
curl -f http://localhost/monitoring_dashboard || echo "Dashboard unreachable"

# Test alert system
bench --site dev.veganisme.net execute verenigingen.utils.alert_manager.test_alert_system

# Check system health
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.get_system_health

# Restart monitoring services
bench restart
```

### Emergency Contacts
- **Technical Lead**: [Contact Info]
- **System Administrator**: [Contact Info]
- **Escalation**: [Contact Info]

## Dashboard Issues

### Dashboard Won't Load

**Symptoms:**
- `/monitoring_dashboard` returns 404 or 500 error
- Page loads but shows no data
- JavaScript errors in browser console

**Diagnosis Steps:**
1. **Check basic connectivity**
   ```bash
   curl -I http://localhost/monitoring_dashboard
   ```

2. **Verify permissions**
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> frappe.has_permission(doctype=None, role="System Manager")
   ```

3. **Check error logs**
   ```bash
   bench --site dev.veganisme.net logs
   tail -f ~/frappe-bench/logs/bench.log
   ```

**Resolution Steps:**
1. **Permission Issues**
   - Ensure user has "System Manager" or "Verenigingen Administrator" role
   - Check role assignment in User management

2. **File System Issues**
   ```bash
   # Check if files exist
   ls -la apps/verenigingen/verenigingen/www/monitoring_dashboard.*

   # Verify file permissions
   chmod 644 apps/verenigingen/verenigingen/www/monitoring_dashboard.*
   ```

3. **Database Issues**
   ```bash
   # Check if required DocTypes exist
   bench --site dev.veganisme.net mariadb -e "SHOW TABLES LIKE '%System Alert%';"
   bench --site dev.veganisme.net mariadb -e "SHOW TABLES LIKE '%SEPA Audit Log%';"
   ```

4. **Service Restart**
   ```bash
   bench restart
   bench clear-cache
   ```

### Dashboard Loads but Shows Errors

**Symptoms:**
- Dashboard displays but metrics show "Failed to load"
- Empty tables or zero values
- JavaScript console errors

**Diagnosis Steps:**
1. **Check API endpoints**
   ```bash
   curl -X POST http://localhost/api/method/verenigingen.www.monitoring_dashboard.get_system_metrics
   ```

2. **Verify database connectivity**
   ```bash
   bench --site dev.veganisme.net mariadb -e "SELECT 1;"
   ```

3. **Check specific functions**
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.www.monitoring_dashboard import get_system_metrics
   >>> get_system_metrics()
   ```

**Resolution Steps:**
1. **API Method Issues**
   - Verify whitelisted methods exist
   - Check method signatures match
   - Restart services after code changes

2. **Database Schema Issues**
   ```bash
   # Run migrations
   bench --site dev.veganisme.net migrate

   # Check specific tables
   bench --site dev.veganisme.net mariadb -e "DESCRIBE \`tabSystem Alert\`;"
   ```

3. **Data Issues**
   ```bash
   # Check for basic data
   bench --site dev.veganisme.net mariadb -e "SELECT COUNT(*) FROM \`tabMember\`;"
   bench --site dev.veganisme.net mariadb -e "SELECT COUNT(*) FROM \`tabError Log\`;"
   ```

## Alert System Issues

### Alerts Not Being Generated

**Symptoms:**
- No alerts in dashboard despite obvious issues
- Scheduled jobs not running
- Email notifications not sent

**Diagnosis Steps:**
1. **Check scheduler status**
   ```bash
   bench --site dev.veganisme.net execute frappe.utils.scheduler.is_scheduler_inactive
   ```

2. **Verify scheduled jobs**
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> frappe.get_all("Scheduled Job Log", limit=10, order_by="creation desc")
   ```

3. **Test alert generation manually**
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.alert_manager.run_hourly_checks
   ```

**Resolution Steps:**
1. **Enable Scheduler**
   ```bash
   bench --site dev.veganisme.net enable-scheduler
   bench restart
   ```

2. **Check Alert Thresholds**
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.utils.alert_manager import AlertManager
   >>> am = AlertManager()
   >>> print(am.alert_thresholds)
   ```

3. **Verify Alert Manager Configuration**
   ```bash
   # Check if System Alert DocType exists
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> frappe.db.exists("DocType", "System Alert")
   ```

4. **Test Email Configuration**
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> frappe.sendmail(recipients=["admin@test.com"], subject="Test", message="Test email")
   ```

### False Positive Alerts

**Symptoms:**
- Too many low-priority alerts
- Alerts for normal system behavior
- Alert fatigue in operations team

**Diagnosis Steps:**
1. **Review alert statistics**
   ```bash
   bench --site dev.veganisme.net execute verenigingen.utils.alert_manager.get_alert_statistics
   ```

2. **Analyze recent alerts**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT alert_type, severity, COUNT(*) as count
   FROM \`tabSystem Alert\`
   WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
   GROUP BY alert_type, severity
   ORDER BY count DESC;"
   ```

**Resolution Steps:**
1. **Adjust Thresholds**
   ```python
   # Edit alert_manager.py thresholds
   self.alert_thresholds = {
       "error_rate_hourly": 20,  # Increase from 10
       "error_rate_daily": 100,  # Increase from 50
       "slow_query_threshold": 5000,  # Increase from 2000
       "failed_sepa_threshold": 10,  # Increase from 5
       "member_churn_daily": 20  # Increase from 10
   }
   ```

2. **Filter Noise**
   - Exclude known error patterns
   - Add error type filtering
   - Implement time-based suppression

## Performance Issues

### High Error Rate Alert

**Symptoms:**
- Alert: "High error rate detected: X errors in the last hour"
- System sluggish or unresponsive
- Users reporting issues

**Diagnosis Steps:**
1. **Check recent errors**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT error, COUNT(*) as count, MAX(creation) as latest
   FROM \`tabError Log\`
   WHERE creation >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
   GROUP BY error
   ORDER BY count DESC
   LIMIT 10;"
   ```

2. **Identify error patterns**
   ```bash
   bench --site dev.veganisme.net logs | grep -i error | tail -20
   ```

3. **Check system resources**
   ```bash
   # If psutil is available
   bench --site dev.veganisme.net console
   >>> import psutil
   >>> print(f"CPU: {psutil.cpu_percent()}%, Memory: {psutil.virtual_memory().percent}%")
   ```

**Resolution Steps:**
1. **Common Error Types**
   - **Database timeouts**: Check slow queries, restart MariaDB
   - **Permission errors**: Review user roles and permissions
   - **Import errors**: Check file formats and data integrity
   - **API errors**: Review recent code deployments

2. **Immediate Actions**
   ```bash
   # Restart services
   bench restart

   # Clear cache
   bench clear-cache

   # Check database connections
   bench --site dev.veganisme.net mariadb -e "SHOW PROCESSLIST;"
   ```

3. **Long-term Solutions**
   - Optimize slow queries
   - Increase resource allocation
   - Implement better error handling
   - Add input validation

### SEPA Compliance Issues

**Symptoms:**
- Alert: "SEPA compliance issues detected"
- Failed SEPA processes in audit log
- Payment processing errors

**Diagnosis Steps:**
1. **Check SEPA audit logs**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT process_type, action, compliance_status, COUNT(*) as count
   FROM \`tabSEPA Audit Log\`
   WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
   AND compliance_status = 'Failed'
   GROUP BY process_type, action
   ORDER BY count DESC;"
   ```

2. **Review SEPA mandate status**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT status, COUNT(*) as count
   FROM \`tabSEPA Mandate\`
   GROUP BY status;"
   ```

3. **Check recent SEPA operations**
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.utils.sepa_validator import SEPAValidator
   >>> validator = SEPAValidator()
   >>> validator.validate_recent_operations()
   ```

**Resolution Steps:**
1. **Mandate Issues**
   - Check IBAN validation
   - Verify BIC codes
   - Review mandate expiration dates

2. **Batch Processing Issues**
   - Check batch file generation
   - Verify XML format compliance
   - Review bank submission status

3. **Data Integrity Issues**
   - Run data quality checks
   - Fix orphaned records
   - Update invalid data

### Performance Degradation Alert

**Symptoms:**
- Alert: "Performance degradation detected"
- Slow page loading
- High resource usage

**Diagnosis Steps:**
1. **Check system resources**
   ```bash
   # Monitor resource usage
   top -p $(pgrep -f frappe)

   # Check disk space
   df -h

   # Check memory usage
   free -h
   ```

2. **Identify slow queries**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT * FROM \`tabError Log\`
   WHERE error LIKE '%timeout%'
   AND creation >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
   ORDER BY creation DESC
   LIMIT 10;"
   ```

3. **Check background jobs**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT status, COUNT(*) as count
   FROM \`tabRQ Job\`
   GROUP BY status;"
   ```

**Resolution Steps:**
1. **Resource Optimization**
   ```bash
   # Restart services to free memory
   bench restart

   # Clear unused files
   bench clear-cache
   bench clear-website-cache
   ```

2. **Database Optimization**
   ```bash
   # Optimize tables
   bench --site dev.veganisme.net mariadb -e "OPTIMIZE TABLE \`tabError Log\`;"

   # Update statistics
   bench --site dev.veganisme.net mariadb -e "ANALYZE TABLE \`tabMember\`;"
   ```

3. **Application Optimization**
   - Review recent code changes
   - Optimize database queries
   - Implement caching where appropriate
   - Scale resources if needed

## Data Quality Issues

### Members Without SEPA Mandates

**Symptoms:**
- Alert: "Found X active members without valid SEPA mandates"
- Payment processing issues
- Membership dues collection problems

**Diagnosis Steps:**
1. **Identify affected members**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT m.name, m.first_name, m.last_name, m.email
   FROM \`tabMember\` m
   LEFT JOIN \`tabSEPA Mandate\` sm ON m.name = sm.member
   WHERE m.status = 'Active'
   AND (sm.name IS NULL OR sm.status != 'Active')
   LIMIT 10;"
   ```

2. **Check mandate creation issues**
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.utils.sepa_mandate_service import SEPAMandateService
   >>> service = SEPAMandateService()
   >>> service.diagnose_mandate_issues()
   ```

**Resolution Steps:**
1. **Contact Members**
   - Send notifications to affected members
   - Provide SEPA mandate creation links
   - Follow up on pending mandates

2. **System Fixes**
   - Fix SEPA mandate creation workflow
   - Resolve IBAN validation issues
   - Update member records

### Stalled Applications

**Symptoms:**
- Alert: "Found X membership applications pending review for over 7 days"
- Application backlog
- Member satisfaction issues

**Diagnosis Steps:**
1. **Review stalled applications**
   ```bash
   bench --site dev.veganisme.net mariadb -e "
   SELECT name, workflow_state, creation, applicant_name
   FROM \`tabMembership Application\`
   WHERE workflow_state = 'Pending Review'
   AND creation <= DATE_SUB(NOW(), INTERVAL 7 DAY)
   ORDER BY creation ASC;"
   ```

2. **Check workflow status**
   ```bash
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> frappe.get_all("Workflow", filters={"document_type": "Membership Application"})
   ```

**Resolution Steps:**
1. **Process Applications**
   - Assign reviewers to pending applications
   - Fast-track simple approvals
   - Reject incomplete applications

2. **Workflow Improvements**
   - Automate simple approval criteria
   - Add reminder notifications
   - Streamline review process

## System Recovery Procedures

### Complete System Failure

**Steps:**
1. **Immediate Assessment (< 5 minutes)**
   ```bash
   # Check if services are running
   ps aux | grep -E "(nginx|redis|mariadb|frappe)"

   # Check system resources
   df -h
   free -h
   ```

2. **Service Recovery (< 10 minutes)**
   ```bash
   # Restart all services
   sudo systemctl restart mariadb
   sudo systemctl restart redis
   bench restart
   ```

3. **Verification (< 5 minutes)**
   ```bash
   # Test basic functionality
   bench --site dev.veganisme.net console
   >>> import frappe
   >>> frappe.db.sql("SELECT 1")

   # Test monitoring dashboard
   curl -f http://localhost/monitoring_dashboard
   ```

### Database Recovery

**Steps:**
1. **Check Database Status**
   ```bash
   sudo systemctl status mariadb
   bench --site dev.veganisme.net mariadb -e "SELECT 1;"
   ```

2. **Repair Database (if needed)**
   ```bash
   bench --site dev.veganisme.net restore [backup-file]
   bench --site dev.veganisme.net migrate
   ```

3. **Verify Data Integrity**
   ```bash
   bench --site dev.veganisme.net console
   >>> from verenigingen.utils.resource_monitor import ResourceMonitor
   >>> monitor = ResourceMonitor()
   >>> monitor.collect_system_metrics()
   ```

## Prevention and Maintenance

### Daily Prevention Tasks
- Monitor dashboard for 15 minutes
- Review and acknowledge alerts
- Check error patterns
- Verify system health metrics

### Weekly Prevention Tasks
- Review performance trends
- Update alert thresholds
- Analyze recurring issues
- Plan maintenance activities

### Monthly Prevention Tasks
- Generate comprehensive reports
- Review and update procedures
- Conduct training sessions
- Evaluate monitoring effectiveness

## Tools and Utilities

### Monitoring Commands
```bash
# System health check
bench --site dev.veganisme.net execute verenigingen.utils.resource_monitor.get_system_health

# Alert statistics
bench --site dev.veganisme.net execute verenigingen.utils.alert_manager.get_alert_statistics

# Test alert system
bench --site dev.veganisme.net execute verenigingen.utils.alert_manager.test_alert_system
```

### Diagnostic Commands
```bash
# Check recent errors
bench --site dev.veganisme.net mariadb -e "SELECT * FROM \`tabError Log\` ORDER BY creation DESC LIMIT 10;"

# Check active alerts
bench --site dev.veganisme.net mariadb -e "SELECT * FROM \`tabSystem Alert\` WHERE status = 'Active';"

# Check system resources
top -n 1 | head -20
```

### Recovery Commands
```bash
# Emergency restart
bench restart
bench clear-cache

# Database repair
bench --site dev.veganisme.net mariadb-repair

# Full system check
bench doctor
```

## Contact and Escalation

### Technical Contacts
- **Level 1 Support**: Operations team
- **Level 2 Support**: Technical team
- **Level 3 Support**: External vendors

### Emergency Procedures
- **CRITICAL alerts**: Immediate escalation
- **System down**: Call technical lead
- **Data breach**: Follow security procedures

---

**Document Control:**
- **Owner**: Technical Team
- **Review Frequency**: Quarterly
- **Last Review**: [Date]
- **Next Review**: [Date]
- **Version Control**: Maintained in git repository

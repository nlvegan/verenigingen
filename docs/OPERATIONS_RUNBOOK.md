# Mollie Backend API - Operations Runbook

## Table of Contents
1. [Daily Operations](#daily-operations)
2. [Monitoring & Alerts](#monitoring--alerts)
3. [Incident Response](#incident-response)
4. [Maintenance Procedures](#maintenance-procedures)
5. [Performance Tuning](#performance-tuning)
6. [Backup & Recovery](#backup--recovery)
7. [Security Operations](#security-operations)
8. [Troubleshooting Guide](#troubleshooting-guide)

## Daily Operations

### Morning Checklist (9:00 AM)

```bash
#!/bin/bash
# Daily health check script

echo "=== Mollie Backend Daily Health Check ==="
echo "Date: $(date)"

# 1. Check system services
echo -e "\n[1] Checking Services..."
systemctl status nginx | grep Active
systemctl status redis | grep Active
systemctl status mariadb | grep Active
supervisorctl status | grep RUNNING

# 2. Check API connectivity
echo -e "\n[2] Checking Mollie API..."
curl -s -o /dev/null -w "%{http_code}" https://api.mollie.com/v2/balances \
  -H "Authorization: Bearer $MOLLIE_API_KEY"

# 3. Check reconciliation status
echo -e "\n[3] Last Reconciliation..."
mysql -e "SELECT MAX(created) as last_run, status
         FROM verenigingen_prod.tabReconciliation_Log
         WHERE created > DATE_SUB(NOW(), INTERVAL 1 DAY)"

# 4. Check error logs
echo -e "\n[4] Recent Errors..."
grep ERROR /opt/frappe-bench/logs/frappe.log | tail -5

# 5. Check disk space
echo -e "\n[5] Disk Usage..."
df -h | grep -E "/$|/opt"

echo -e "\n=== Health Check Complete ==="
```

### Reconciliation Verification (10:00 AM)

```python
# Run after daily reconciliation (scheduled at 2 AM)
bench --site prod.verenigingen.nl console

from datetime import datetime, timedelta
import frappe

# Check reconciliation results
yesterday = datetime.now() - timedelta(days=1)
results = frappe.get_all("Settlement Reconciliation",
    filters={
        "created": [">", yesterday],
        "status": ["!=", "Reconciled"]
    },
    fields=["name", "settlement_id", "status", "error_message"])

if results:
    print(f"⚠️ {len(results)} unreconciled settlements found")
    for r in results:
        print(f"  - {r.settlement_id}: {r.status} - {r.error_message}")
else:
    print("✅ All settlements reconciled successfully")

# Check for pending settlements
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
client = SettlementsClient("Production")
open_settlements = client.list_open_settlements()
print(f"📊 {len(open_settlements)} open settlements pending")
```

### Balance Monitoring (Every 15 minutes)

```python
# Automated monitoring script (runs via scheduler)
from verenigingen.verenigingen_payments.monitoring.balance_monitor import BalanceMonitor

monitor = BalanceMonitor("Production")
result = monitor.run_monitoring_cycle()

# Alert thresholds
CRITICAL_BALANCE_EUR = 100
LOW_BALANCE_EUR = 1000

for alert in result.get("alerts_generated", []):
    if alert["severity"] == "emergency":
        # Send immediate notification
        send_emergency_alert(alert)
    elif alert["severity"] == "critical":
        # Send urgent notification
        send_critical_alert(alert)
```

## Monitoring & Alerts

### Key Metrics Dashboard

```sql
-- Real-time metrics query
CREATE VIEW v_mollie_dashboard AS
SELECT
    -- Balance metrics
    (SELECT SUM(available_amount) FROM tabBalance WHERE currency = 'EUR') as total_balance_eur,
    (SELECT COUNT(*) FROM tabBalance WHERE available_amount < 100) as low_balance_count,

    -- Transaction metrics
    (SELECT COUNT(*) FROM tabPayment_Entry WHERE DATE(created) = CURDATE()) as payments_today,
    (SELECT SUM(paid_amount) FROM tabPayment_Entry WHERE DATE(created) = CURDATE()) as revenue_today,

    -- Settlement metrics
    (SELECT COUNT(*) FROM tabSettlement WHERE status = 'open') as open_settlements,
    (SELECT COUNT(*) FROM tabSettlement WHERE status = 'pending' AND created < DATE_SUB(NOW(), INTERVAL 5 DAY)) as delayed_settlements,

    -- Dispute metrics
    (SELECT COUNT(*) FROM tabDispute_Case WHERE status IN ('open', 'investigating')) as active_disputes,
    (SELECT SUM(amount) FROM tabDispute_Case WHERE status IN ('open', 'investigating')) as disputed_amount,

    -- System health
    (SELECT COUNT(*) FROM tabMollie_Audit_Log WHERE severity = 'ERROR' AND created > DATE_SUB(NOW(), INTERVAL 1 HOUR)) as recent_errors,
    (SELECT AVG(response_time_ms) FROM tabAPI_Performance WHERE created > DATE_SUB(NOW(), INTERVAL 1 HOUR)) as avg_api_response_time;
```

### Alert Configuration

```yaml
# alerts.yml - Alert rules configuration
alerts:
  - name: critical_low_balance
    condition: balance < 100
    severity: critical
    channels:
      - email: finance@company.com
      - sms: +31612345678
      - slack: #finance-alerts
    message: "CRITICAL: EUR balance below €100"

  - name: high_error_rate
    condition: error_rate > 0.05
    severity: warning
    channels:
      - email: tech@company.com
      - slack: #tech-alerts
    message: "High API error rate: {error_rate}%"

  - name: settlement_delay
    condition: days_pending > 5
    severity: warning
    channels:
      - email: finance@company.com
    message: "Settlement {settlement_id} delayed by {days_pending} days"

  - name: dispute_received
    condition: new_dispute == true
    severity: info
    channels:
      - email: disputes@company.com
      - slack: #disputes
    message: "New dispute: {dispute_id} for €{amount}"
```

### Monitoring Scripts

```bash
#!/bin/bash
# monitor.sh - Continuous monitoring script

while true; do
    # Check API health
    API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://api.mollie.com/v2/balances \
        -H "Authorization: Bearer $MOLLIE_API_KEY")

    if [ "$API_STATUS" != "200" ]; then
        echo "$(date): API Error - Status $API_STATUS" >> /var/log/mollie-monitor.log
        # Send alert
        ./send-alert.sh "API Error" "Mollie API returned status $API_STATUS"
    fi

    # Check process health
    WORKER_COUNT=$(supervisorctl status | grep -c RUNNING)
    if [ "$WORKER_COUNT" -lt 8 ]; then
        echo "$(date): Worker Error - Only $WORKER_COUNT workers running" >> /var/log/mollie-monitor.log
        supervisorctl restart all
    fi

    # Check database connectivity
    mysql -e "SELECT 1" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "$(date): Database connection failed" >> /var/log/mollie-monitor.log
        # Restart database
        systemctl restart mariadb
    fi

    sleep 60
done
```

## Incident Response

### Severity Levels

| Level | Description | Response Time | Escalation |
|-------|-------------|---------------|------------|
| P1 - Critical | Complete service outage | 15 minutes | Immediate |
| P2 - High | Major feature unavailable | 30 minutes | Within 1 hour |
| P3 - Medium | Minor feature issue | 2 hours | Within 4 hours |
| P4 - Low | Cosmetic or minor bug | Next business day | As needed |

### Incident Response Procedures

#### P1 - Payment Processing Failure

```bash
# IMMEDIATE RESPONSE REQUIRED

# 1. Verify the issue
curl -X GET https://prod.verenigingen.nl/api/method/health_check

# 2. Check Mollie API status
curl https://status.mollie.com/api/v2/status.json

# 3. Enable fallback mode
bench --site prod.verenigingen.nl console
frappe.db.set_value("Mollie Settings", "Production", "fallback_mode", 1)
frappe.db.commit()

# 4. Notify stakeholders
./notify-incident.sh P1 "Payment processing offline"

# 5. Begin investigation
tail -f /opt/frappe-bench/logs/frappe.log | grep -E "ERROR|CRITICAL"

# 6. Check webhook processing
mysql -e "SELECT COUNT(*) as pending FROM tabMollie_Webhook_Queue WHERE status = 'pending'"

# 7. If webhooks backed up, process manually
bench --site prod.verenigingen.nl console
from verenigingen.utils.payment_gateways import process_pending_webhooks
process_pending_webhooks()
```

#### P2 - Reconciliation Failure

```python
# Investigation and resolution steps

# 1. Check reconciliation status
bench --site prod.verenigingen.nl console

from datetime import datetime, timedelta
import frappe

# Get failed reconciliations
failed = frappe.get_all("Settlement Reconciliation",
    filters={"status": "Failed"},
    fields=["name", "settlement_id", "error_message"],
    order_by="created desc",
    limit=10)

for f in failed:
    print(f"{f.settlement_id}: {f.error_message}")

# 2. Retry failed reconciliations
from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine
engine = ReconciliationEngine("Production")

for f in failed:
    try:
        result = engine.process_settlement(f.settlement_id)
        print(f"✅ {f.settlement_id}: {result['status']}")
    except Exception as e:
        print(f"❌ {f.settlement_id}: {str(e)}")

# 3. Manual reconciliation if needed
def manual_reconcile(settlement_id, invoice_ids):
    settlement = frappe.get_doc("Settlement", settlement_id)
    for invoice_id in invoice_ids:
        invoice = frappe.get_doc("Sales Invoice", invoice_id)
        # Create payment entry
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.party_type = "Customer"
        payment.party = invoice.customer
        payment.paid_amount = invoice.grand_total
        payment.reference_no = settlement_id
        payment.insert()
        payment.submit()
    settlement.status = "Reconciled"
    settlement.save()
```

#### P3 - High API Error Rate

```bash
#!/bin/bash
# diagnose-api-errors.sh

# 1. Check error patterns
grep "MollieAPIError" /opt/frappe-bench/logs/frappe.log | \
    awk '{print $5}' | sort | uniq -c | sort -rn | head -10

# 2. Check rate limiting
bench --site prod.verenigingen.nl console << 'EOF'
from vereinigingen.vereinigingen_payments.core.resilience.rate_limiter import RateLimiter
limiter = RateLimiter()
print(f"Current rate: {limiter.get_current_rate()}/s")
print(f"Remaining capacity: {limiter.get_remaining_capacity()}")
EOF

# 3. Check circuit breaker status
bench --site prod.verenigingen.nl console << 'EOF'
from vereinigingen.vereinigingen_payments.core.resilience.circuit_breaker import CircuitBreaker
breaker = CircuitBreaker.get_instance("mollie_api")
print(f"Circuit breaker state: {breaker.state}")
print(f"Failure count: {breaker.failure_count}")
if breaker.state == "OPEN":
    breaker.reset()  # Force reset if needed
    print("Circuit breaker reset")
EOF
```

## Maintenance Procedures

### Weekly Maintenance

```bash
#!/bin/bash
# weekly-maintenance.sh - Run Sunday 3 AM

echo "Starting weekly maintenance - $(date)"

# 1. Database optimization
mysql verenigingen_prod << EOF
ANALYZE TABLE tabPayment_Entry;
ANALYZE TABLE tabSales_Invoice;
ANALYZE TABLE tabMollie_Audit_Log;
OPTIMIZE TABLE tabMollie_Webhook_Log;
EOF

# 2. Clean old logs
find /opt/frappe-bench/logs -name "*.log" -mtime +30 -delete
mysql -e "DELETE FROM tabMollie_Audit_Log WHERE created < DATE_SUB(NOW(), INTERVAL 90 DAY)"

# 3. Archive old data
bench --site prod.verenigingen.nl console << 'EOF'
from vereinigingen.utils.archive import archive_old_transactions
archived = archive_old_transactions(days=180)
print(f"Archived {archived} old transactions")
EOF

# 4. Update statistics
bench --site prod.verenigingen.nl console << 'EOF'
from vereinigingen.utils.statistics import update_statistics_cache
update_statistics_cache()
EOF

# 5. Test backups
BACKUP_FILE=$(bench --site prod.verenigingen.nl backup | grep "Database backup")
if [ -f "$BACKUP_FILE" ]; then
    echo "Backup successful: $BACKUP_FILE"
else
    echo "BACKUP FAILED!"
    ./send-alert.sh "CRITICAL" "Weekly backup failed"
fi

echo "Weekly maintenance complete - $(date)"
```

### Monthly Maintenance

```python
# monthly-maintenance.py - Run 1st Sunday of month

import frappe
from datetime import datetime, timedelta

def monthly_maintenance():
    """Perform monthly maintenance tasks"""

    results = {
        "date": datetime.now(),
        "tasks": []
    }

    # 1. Rotate API keys
    from vereinigingen.vereinigingen_payments.core.security import MollieSecurityManager
    manager = MollieSecurityManager("Production")
    new_key = manager.rotate_api_key()
    results["tasks"].append({"task": "API key rotation", "status": "complete"})

    # 2. Review and clean dispute cases
    old_disputes = frappe.get_all("Dispute Case",
        filters={
            "status": ["in", ["closed", "won", "lost"]],
            "modified": ["<", datetime.now() - timedelta(days=365)]
        })

    for dispute in old_disputes:
        frappe.delete_doc("Dispute Case", dispute.name)

    results["tasks"].append({
        "task": "Dispute cleanup",
        "status": "complete",
        "cleaned": len(old_disputes)
    })

    # 3. Generate monthly reports
    from vereinigingen.reports import generate_monthly_financial_report
    report = generate_monthly_financial_report()
    results["tasks"].append({
        "task": "Monthly report",
        "status": "complete",
        "report_id": report["id"]
    })

    # 4. Security audit
    from vereinigingen.security import run_security_audit
    audit = run_security_audit()
    results["tasks"].append({
        "task": "Security audit",
        "status": audit["status"],
        "findings": len(audit.get("findings", []))
    })

    return results

# Run maintenance
if __name__ == "__main__":
    results = monthly_maintenance()
    print(f"Monthly maintenance complete: {results}")
```

## Performance Tuning

### Database Optimization

```sql
-- Index performance review
SELECT
    table_name,
    index_name,
    cardinality,
    (data_length + index_length) / 1024 / 1024 as size_mb
FROM information_schema.statistics
WHERE table_schema = 'verenigingen_prod'
    AND table_name LIKE 'tab%'
ORDER BY cardinality DESC;

-- Slow query analysis
SELECT
    digest_text,
    count_star as exec_count,
    sum_timer_wait / 1000000000000 as total_time_sec,
    avg_timer_wait / 1000000000 as avg_time_ms,
    sum_rows_examined as rows_examined
FROM performance_schema.events_statements_summary_by_digest
WHERE digest_text LIKE '%mollie%'
ORDER BY sum_timer_wait DESC
LIMIT 10;

-- Missing indexes
SELECT
    tables.table_name,
    statistics.column_name,
    tables.table_rows
FROM information_schema.tables
LEFT JOIN information_schema.statistics
    ON tables.table_name = statistics.table_name
    AND tables.table_schema = statistics.table_schema
WHERE tables.table_schema = 'verenigingen_prod'
    AND statistics.index_name IS NULL
    AND tables.table_rows > 1000;
```

### Application Performance

```python
# performance-check.py
import time
import statistics
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

def measure_api_performance():
    """Measure API response times"""

    client = BalancesClient("Production")
    response_times = []

    # Test balance retrieval
    for _ in range(10):
        start = time.perf_counter()
        balances = client.list_balances()
        elapsed = time.perf_counter() - start
        response_times.append(elapsed * 1000)  # Convert to ms

    return {
        "min": min(response_times),
        "max": max(response_times),
        "mean": statistics.mean(response_times),
        "median": statistics.median(response_times),
        "stdev": statistics.stdev(response_times) if len(response_times) > 1 else 0
    }

# Run performance check
results = measure_api_performance()
print(f"API Performance (ms):")
print(f"  Min: {results['min']:.2f}")
print(f"  Max: {results['max']:.2f}")
print(f"  Mean: {results['mean']:.2f}")
print(f"  Median: {results['median']:.2f}")
print(f"  StdDev: {results['stdev']:.2f}")

# Alert if performance degraded
if results['mean'] > 500:  # 500ms threshold
    print("⚠️ PERFORMANCE DEGRADATION DETECTED")
```

### Redis Optimization

```bash
# Redis performance tuning
redis-cli << 'EOF'
# Check memory usage
INFO memory

# Check slow commands
SLOWLOG GET 10

# Optimize memory
CONFIG SET maxmemory-policy allkeys-lru
CONFIG SET maxmemory 2gb

# Enable persistence optimization
CONFIG SET save ""
CONFIG SET appendonly no
BGSAVE
EOF

# Monitor Redis performance
redis-cli --stat
```

## Backup & Recovery

### Backup Strategy

```bash
#!/bin/bash
# backup-strategy.sh

# Daily backup (retained for 7 days)
DAILY_BACKUP() {
    BACKUP_DIR="/backup/daily/$(date +%Y%m%d)"
    mkdir -p $BACKUP_DIR

    # Database backup
    bench --site prod.verenigingen.nl backup --with-files

    # Move to backup directory
    mv sites/prod.verenigingen.nl/private/backups/* $BACKUP_DIR/

    # Clean old daily backups
    find /backup/daily -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
}

# Weekly backup (retained for 4 weeks)
WEEKLY_BACKUP() {
    BACKUP_DIR="/backup/weekly/week-$(date +%U)"
    mkdir -p $BACKUP_DIR

    # Full system backup
    tar -czf $BACKUP_DIR/frappe-bench.tar.gz /opt/frappe-bench
    mysqldump --all-databases > $BACKUP_DIR/all-databases.sql

    # Clean old weekly backups
    find /backup/weekly -maxdepth 1 -type d -mtime +28 -exec rm -rf {} \;
}

# Monthly backup (retained for 12 months)
MONTHLY_BACKUP() {
    BACKUP_DIR="/backup/monthly/$(date +%Y-%m)"
    mkdir -p $BACKUP_DIR

    # Complete backup with verification
    bench --site prod.verenigingen.nl backup --with-files
    tar -czf $BACKUP_DIR/complete-backup.tar.gz sites/

    # Backup to remote storage
    aws s3 sync $BACKUP_DIR s3://company-backups/mollie-backend/monthly/
}
```

### Recovery Procedures

```bash
#!/bin/bash
# disaster-recovery.sh

RESTORE_DATABASE() {
    local BACKUP_FILE=$1

    echo "Restoring database from $BACKUP_FILE"

    # Stop services
    supervisorctl stop all

    # Restore database
    gunzip < $BACKUP_FILE | mysql verenigingen_prod

    # Clear cache
    bench --site prod.verenigingen.nl clear-cache

    # Restart services
    supervisorctl start all
}

RESTORE_FILES() {
    local BACKUP_DIR=$1

    echo "Restoring files from $BACKUP_DIR"

    # Restore public files
    tar -xzf $BACKUP_DIR/public-files.tar.gz -C sites/prod.verenigingen.nl/public/

    # Restore private files
    tar -xzf $BACKUP_DIR/private-files.tar.gz -C sites/prod.verenigingen.nl/private/

    # Fix permissions
    chown -R frappe:frappe sites/
}

POINT_IN_TIME_RECOVERY() {
    local TARGET_TIME=$1

    echo "Performing point-in-time recovery to $TARGET_TIME"

    # Find appropriate backup
    BACKUP_FILE=$(find /backup -name "*.sql.gz" -newermt "$TARGET_TIME" | head -1)

    if [ -z "$BACKUP_FILE" ]; then
        echo "No suitable backup found"
        exit 1
    fi

    # Restore base backup
    RESTORE_DATABASE $BACKUP_FILE

    # Apply binary logs up to target time
    mysqlbinlog --stop-datetime="$TARGET_TIME" /var/log/mysql/binlog.* | mysql vereiningen_prod

    echo "Recovery complete to $TARGET_TIME"
}
```

## Security Operations

### Security Monitoring

```python
# security-monitor.py
import frappe
from datetime import datetime, timedelta

def security_scan():
    """Perform security monitoring scan"""

    alerts = []

    # 1. Check for suspicious login attempts
    failed_logins = frappe.get_all("Activity Log",
        filters={
            "operation": "Login",
            "status": "Failed",
            "creation": [">", datetime.now() - timedelta(hours=1)]
        })

    if len(failed_logins) > 10:
        alerts.append({
            "type": "suspicious_activity",
            "severity": "high",
            "message": f"{len(failed_logins)} failed login attempts in last hour"
        })

    # 2. Check for API key usage patterns
    api_usage = frappe.db.sql("""
        SELECT
            user,
            COUNT(*) as request_count,
            COUNT(DISTINCT ip_address) as unique_ips
        FROM `tabMollie Audit Log`
        WHERE created > DATE_SUB(NOW(), INTERVAL 1 HOUR)
        GROUP BY user
        HAVING unique_ips > 5
    """, as_dict=True)

    for usage in api_usage:
        alerts.append({
            "type": "api_anomaly",
            "severity": "medium",
            "message": f"User {usage.user} accessed from {usage.unique_ips} different IPs"
        })

    # 3. Check for privilege escalation attempts
    privilege_events = frappe.get_all("Mollie Audit Log",
        filters={
            "event_type": ["in", ["PERMISSION_DENIED", "UNAUTHORIZED_ACCESS"]],
            "created": [">", datetime.now() - timedelta(hours=1)]
        })

    if privilege_events:
        alerts.append({
            "type": "privilege_escalation",
            "severity": "critical",
            "message": f"{len(privilege_events)} unauthorized access attempts"
        })

    return alerts

# Run security scan
alerts = security_scan()
for alert in alerts:
    print(f"[{alert['severity'].upper()}] {alert['message']}")
```

### Security Incident Response

```bash
#!/bin/bash
# security-incident.sh

ISOLATE_SYSTEM() {
    echo "ISOLATING SYSTEM - $(date)"

    # 1. Block external access
    iptables -I INPUT 1 -j DROP
    iptables -I INPUT 1 -s 127.0.0.1 -j ACCEPT

    # 2. Preserve evidence
    mkdir -p /forensics/$(date +%Y%m%d-%H%M%S)
    cp -r /opt/frappe-bench/logs /forensics/
    mysqldump tabMollie_Audit_Log > /forensics/audit_log.sql

    # 3. Disable API access
    bench --site prod.verenigingen.nl console << 'EOF'
    frappe.db.set_value("Mollie Settings", "Production", "enabled", 0)
    frappe.db.commit()
EOF

    # 4. Notify security team
    ./notify-security.sh "CRITICAL" "System isolated due to security incident"
}

INVESTIGATE_BREACH() {
    echo "Starting breach investigation - $(date)"

    # 1. Collect access logs
    grep -E "mollie|payment|webhook" /var/log/nginx/access.log > /forensics/access.log

    # 2. Check for data exfiltration
    netstat -an | grep ESTABLISHED > /forensics/connections.txt

    # 3. Analyze audit trail
    mysql verenigingen_prod << 'EOF' > /forensics/suspicious_activity.txt
    SELECT * FROM tabMollie_Audit_Log
    WHERE severity IN ('ERROR', 'CRITICAL')
        OR event_type LIKE '%UNAUTHORIZED%'
    ORDER BY created DESC;
EOF

    # 4. Check file integrity
    find /opt/frappe-bench -type f -mtime -1 > /forensics/recently_modified.txt
}
```

## Troubleshooting Guide

### Common Issues and Solutions

#### Issue: Webhook Not Processing

```bash
# Diagnosis
curl -X POST https://prod.verenigingen.nl/api/method/verenigingen.utils.payment_gateways.mollie_webhook \
    -H "Content-Type: application/json" \
    -d '{"test": true}'

# Check webhook queue
mysql -e "SELECT COUNT(*), status FROM tabMollie_Webhook_Queue GROUP BY status"

# Process stuck webhooks
bench --site prod.verenigingen.nl console << 'EOF'
from verenigingen.utils.webhook_processor import process_webhook_queue
result = process_webhook_queue(force=True)
print(f"Processed {result['processed']} webhooks")
EOF
```

#### Issue: Memory Leak

```bash
# Identify memory usage
ps aux | grep python | sort -k 4 -r | head -5

# Check for large objects
bench --site prod.verenigingen.nl console << 'EOF'
import gc
import sys

# Find large objects
for obj in gc.get_objects():
    if sys.getsizeof(obj) > 1048576:  # 1MB
        print(f"{type(obj)}: {sys.getsizeof(obj) / 1048576:.2f} MB")

# Force garbage collection
gc.collect()
EOF

# Restart workers if needed
supervisorctl restart frappe-bench-workers:*
```

#### Issue: Slow Performance

```python
# Performance diagnostics
import cProfile
import pstats
from io import StringIO

def diagnose_performance():
    """Profile slow operations"""

    profiler = cProfile.Profile()
    profiler.enable()

    # Run suspect operation
    from vereinigingen.vereinigingen_payments.workflows.reconciliation_engine import ReconciliationEngine
    engine = ReconciliationEngine("Production")
    engine.run_reconciliation()

    profiler.disable()

    # Analyze results
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats('cumulative')
    stats.print_stats(20)

    print(stream.getvalue())

# Run diagnostics
diagnose_performance()
```

---

*Last Updated: August 2024*
*Version: 1.0.0*
*Emergency Contact: ops@company.com | +31 6 12345678*

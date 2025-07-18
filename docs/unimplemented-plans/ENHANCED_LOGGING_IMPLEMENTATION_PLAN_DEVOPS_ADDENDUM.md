# DevOps-Focused Approach for Phase 3: Analytics and Optimization

## Context
Given the association's limited BI resources but availability of a Senior DevOps Engineer, here's a revised approach for Phase 3 that focuses on maintainable, DevOps-friendly solutions.

## Revised Phase 3: Analytics and Optimization (Weeks 13-16)

### Week 13-14: Operational Monitoring (DevOps-Led)

#### Day 61-65: Infrastructure-Based Dashboards
**Owner:** Senior DevOps Engineer + Senior Developer
**Effort:** 20 hours

**Tasks:**

1. **Leverage Existing DevOps Tools**
   ```yaml
   # Use familiar tools that DevOps already knows
   monitoring_stack:
     - metrics: Prometheus (if available) or simple JSON endpoints
     - visualization: Grafana or simple HTML dashboards
     - alerts: Email, Slack webhooks, or SMS
     - logs: ELK stack integration or simple log aggregation
   ```

2. **Create Simple Monitoring Endpoints**
   ```python
   # vereinigingen/api/monitoring.py

   @frappe.whitelist(allow_guest=True)
   def metrics():
       """Prometheus-compatible metrics endpoint"""
       metrics = []

       # Error rate
       error_count = frappe.db.count("Error Log",
           filters={"creation": [">", add_days(now(), -1)]})
       metrics.append(f"verenigingen_errors_24h {error_count}")

       # Active users
       active_users = frappe.db.count("Activity Log",
           filters={"creation": [">", add_days(now(), -1)]})
       metrics.append(f"verenigingen_active_users_24h {active_users}")

       # SEPA processing status
       failed_batches = frappe.db.count("Direct Debit Batch",
           filters={"status": "Failed", "modified": [">", add_days(now(), -7)]})
       metrics.append(f"verenigingen_sepa_failed_batches_7d {failed_batches}")

       return "\n".join(metrics)

   @frappe.whitelist()
   def health_check():
       """Simple health check endpoint for monitoring"""
       checks = {
           "database": check_database_connection(),
           "redis": check_redis_connection(),
           "scheduler": check_scheduler_status(),
           "disk_space": check_disk_space(),
           "error_rate": check_error_rate_threshold()
       }

       status = "healthy" if all(checks.values()) else "unhealthy"
       return {"status": status, "checks": checks, "timestamp": now()}
   ```

3. **Implement Grafana Dashboards**
   ```json
   // grafana/dashboards/verenigingen-operational.json
   {
     "dashboard": {
       "title": "Verenigingen Operational Health",
       "panels": [
         {
           "title": "Error Rate",
           "targets": [{
             "expr": "rate(verenigingen_errors_24h[5m])"
           }]
         },
         {
           "title": "Active Users",
           "targets": [{
             "expr": "verenigingen_active_users_24h"
           }]
         },
         {
           "title": "SEPA Processing",
           "targets": [{
             "expr": "verenigingen_sepa_failed_batches_7d"
           }]
         }
       ]
     }
   }
   ```

4. **Create Simple Status Page**
   ```html
   <!-- templates/pages/system_status.html -->
   <div class="status-dashboard">
     <h1>System Status</h1>
     <div class="status-grid">
       <div class="status-card" data-endpoint="/api/method/health_check">
         <h3>Overall Health</h3>
         <div class="status-indicator">Loading...</div>
       </div>
       <div class="status-card" data-endpoint="/api/method/get_error_metrics">
         <h3>Error Rate</h3>
         <div class="metric-value">Loading...</div>
       </div>
     </div>
   </div>

   <script>
   // Simple auto-refresh every 60 seconds
   setInterval(refreshDashboard, 60000);
   </script>
   ```

**Deliverables:**
- [ ] Monitoring endpoints implemented
- [ ] Grafana dashboards configured
- [ ] Status page deployed
- [ ] Alert rules configured

#### Day 66-70: Automated Alerting and Reporting
**Owner:** Senior DevOps Engineer
**Effort:** 20 hours

**Tasks:**

1. **Implement Alert Rules**
   ```python
   # vereinigingen/monitoring/alerts.py

   class AlertManager:
       """Simple threshold-based alerting"""

       ALERT_RULES = {
           "high_error_rate": {
               "query": "SELECT COUNT(*) FROM `tabError Log` WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)",
               "threshold": 50,
               "severity": "critical",
               "message": "Error rate exceeded 50 errors/hour"
           },
           "sepa_batch_failure": {
               "query": "SELECT COUNT(*) FROM `tabDirect Debit Batch` WHERE status = 'Failed' AND modified > DATE_SUB(NOW(), INTERVAL 1 DAY)",
               "threshold": 1,
               "severity": "high",
               "message": "SEPA batch processing failure detected"
           },
           "low_disk_space": {
               "command": "df -h / | awk 'NR==2 {print $5}' | sed 's/%//'",
               "threshold": 90,
               "severity": "warning",
               "message": "Disk usage above 90%"
           }
       }

       def check_alerts(self):
           """Run all alert checks"""
           for rule_name, rule in self.ALERT_RULES.items():
               if self.evaluate_rule(rule):
                   self.send_alert(rule_name, rule)
   ```

2. **Create Daily Reports Script**
   ```bash
   #!/bin/bash
   # scripts/daily_report.sh

   # Generate daily metrics
   echo "Verenigingen Daily Report - $(date)" > /tmp/daily_report.txt
   echo "=========================" >> /tmp/daily_report.txt

   # Error summary
   echo -e "\n## Errors (Last 24h)" >> /tmp/daily_report.txt
   mysql -e "SELECT method, COUNT(*) as count FROM error_log WHERE creation > DATE_SUB(NOW(), INTERVAL 1 DAY) GROUP BY method ORDER BY count DESC LIMIT 10" >> /tmp/daily_report.txt

   # User activity
   echo -e "\n## Active Users" >> /tmp/daily_report.txt
   mysql -e "SELECT COUNT(DISTINCT user) FROM activity_log WHERE creation > DATE_SUB(NOW(), INTERVAL 1 DAY)" >> /tmp/daily_report.txt

   # SEPA status
   echo -e "\n## SEPA Processing" >> /tmp/daily_report.txt
   mysql -e "SELECT status, COUNT(*) FROM direct_debit_batch WHERE modified > DATE_SUB(NOW(), INTERVAL 7 DAY) GROUP BY status" >> /tmp/daily_report.txt

   # Send email
   mail -s "Verenigingen Daily Report" operations@verenigingen.nl < /tmp/daily_report.txt
   ```

3. **Implement Slack/Webhook Notifications**
   ```python
   # vereinigingen/monitoring/notifications.py

   def send_slack_alert(message, severity="info"):
       """Send alert to Slack channel"""
       webhook_url = frappe.conf.slack_webhook_url

       color_map = {
           "info": "#36a64f",
           "warning": "#ff9800",
           "critical": "#ff0000"
       }

       payload = {
           "attachments": [{
               "color": color_map.get(severity, "#000000"),
               "title": f"Verenigingen Alert - {severity.upper()}",
               "text": message,
               "footer": "Verenigingen Monitoring",
               "ts": int(time.time())
           }]
       }

       requests.post(webhook_url, json=payload)
   ```

**Deliverables:**
- [ ] Alert rules implemented
- [ ] Daily report script deployed
- [ ] Notification channels configured
- [ ] Runbook documentation created

### Week 15-16: Documentation and Handover

#### Day 71-75: Create Maintainable Documentation
**Owner:** Senior DevOps Engineer + Technical Lead
**Effort:** 15 hours

**Tasks:**

1. **Create Operations Runbook**
   ```markdown
   # Verenigingen Operations Runbook

   ## Daily Checks
   1. Check system status page: https://app.verenigingen.nl/system-status
   2. Review Grafana dashboard for anomalies
   3. Check email for overnight alerts

   ## Common Issues and Solutions

   ### High Error Rate
   1. Check Error Log: `SELECT * FROM tabError Log ORDER BY creation DESC LIMIT 20`
   2. Common causes:
      - SEPA processing failures
      - Email quota exceeded
      - Database connection issues
   3. Solutions:
      - Restart workers: `bench restart`
      - Check disk space: `df -h`
      - Review recent deployments

   ### SEPA Batch Failures
   1. Check batch status: `SELECT * FROM tabDirect Debit Batch WHERE status = 'Failed'`
   2. Review bank response files
   3. Contact finance team if manual intervention needed

   ## Monitoring Queries

   All monitoring queries are maintained in:
   - `/apps/vereinigingen/monitoring/queries.sql`
   - Grafana dashboard JSON files
   - Monitoring API endpoints
   ```

2. **Create Self-Service Troubleshooting Guide**
   - Common error patterns and solutions
   - SQL queries for investigation
   - Restart procedures
   - Escalation paths

3. **Document Monitoring Infrastructure**
   - Architecture diagram
   - Data flow documentation
   - Alert rule documentation
   - Maintenance procedures

**Deliverables:**
- [ ] Operations runbook completed
- [ ] Troubleshooting guide published
- [ ] Infrastructure documentation
- [ ] Knowledge transfer completed

## Key Advantages of This Approach

1. **Leverages DevOps Skills**
   - Uses familiar tools (Grafana, Prometheus, bash scripts)
   - SQL-based queries that are easy to understand and modify
   - Standard monitoring patterns

2. **Maintainability**
   - Simple Python functions instead of complex BI tools
   - Direct SQL queries that can be tweaked
   - Clear documentation and runbooks
   - Version-controlled dashboards

3. **Cost-Effective**
   - No need for specialized BI tools
   - Uses open-source monitoring stack
   - Minimal training required

4. **Scalability**
   - Can add more metrics incrementally
   - Easy to extend alert rules
   - Can integrate with existing monitoring infrastructure

## Migration Path

If the association later hires BI specialists, this foundation can be extended:
- Monitoring endpoints can feed into BI tools
- SQL queries can be converted to BI tool queries
- Grafana dashboards can be recreated in specialized tools
- Historical data is preserved for analysis

## Summary

This DevOps-focused approach provides:
- Immediate operational visibility
- Maintainable monitoring infrastructure
- Clear escalation paths
- Documentation for sustainability
- Foundation for future BI initiatives

The key is to start simple, use familiar tools, and build incrementally based on actual operational needs rather than theoretical BI requirements.

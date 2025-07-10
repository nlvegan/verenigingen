# Monitoring Setup Guide for Verenigingen

## Overview

This guide helps you configure comprehensive monitoring for the Verenigingen application using Frappe's built-in monitoring features and recommended third-party tools.

## 1. Enable Sentry Integration (Recommended)

Frappe has built-in Sentry support. To enable it:

### Environment Configuration

Add these to your environment variables or `site_config.json`:

```json
{
  "sentry_dsn": "YOUR_SENTRY_DSN_HERE",
  "enable_sentry_db_monitoring": 1,
  "sentry_tracing_sample_rate": 0.1,
  "sentry_profiling_sample_rate": 0.1,
  "sentry_environment": "production"
}
```

### Get Your Sentry DSN

1. Create a free account at [sentry.io](https://sentry.io)
2. Create a new Python project
3. Copy the DSN from project settings

### Verify Integration

```bash
# Check if Sentry is active
bench --site dev.veganisme.net console
>>> import frappe
>>> frappe.conf.sentry_dsn  # Should show your DSN
>>> from frappe.utils.sentry import is_sentry_enabled
>>> is_sentry_enabled()  # Should return True
```

## 2. Configure Frappe Monitor

### Enable Monitoring

In `site_config.json`:

```json
{
  "monitor": 1,
  "logging": 2,
  "verbose": 1
}
```

### Access Monitor Data

```python
# In bench console
import frappe
from frappe.monitor import get_trace_id

# Get current trace ID
trace_id = get_trace_id()

# View monitor logs
monitor_logs = frappe.get_all("Error Log",
    filters={"trace_id": trace_id},
    fields=["*"])
```

### Monitor Log Location

Monitor logs are stored at:
- `sites/dev.veganisme.net/logs/monitor.json.log`

## 3. Utilize Performance Dashboard

The Verenigingen app already includes a comprehensive performance dashboard!

### Access Performance Dashboard

```python
from verenigingen.utils.performance_dashboard import PerformanceDashboard

# Initialize dashboard
dashboard = PerformanceDashboard()

# Get performance metrics
metrics = dashboard.get_metrics()

# Get slow queries
slow_queries = dashboard.get_slow_queries(threshold_ms=1000)

# Get error analysis
errors = dashboard.get_error_analysis()

# Get optimization suggestions
suggestions = dashboard.get_optimization_suggestions()
```

### Create Performance Report Page

Create `/performance_dashboard` page:

```python
# verenigingen/www/performance_dashboard.py
import frappe
from verenigingen.utils.performance_dashboard import PerformanceDashboard

def get_context(context):
    if not frappe.has_permission("System Manager"):
        raise frappe.PermissionError

    dashboard = PerformanceDashboard()

    context.update({
        "metrics": dashboard.get_metrics(),
        "slow_queries": dashboard.get_slow_queries(),
        "errors": dashboard.get_error_analysis(),
        "suggestions": dashboard.get_optimization_suggestions()
    })
```

## 4. System Health Monitoring

### Use Built-in System Health Report

```bash
# Generate system health report
bench --site dev.veganisme.net execute frappe.desk.doctype.system_health_report.system_health_report.run_system_health_report
```

### Schedule Automated Health Checks

Add to `hooks.py`:

```python
scheduler_events = {
    "hourly": [
        "verenigingen.monitoring.health_checks.run_health_check"
    ],
    "daily": [
        "verenigingen.monitoring.health_checks.generate_daily_report"
    ]
}
```

## 5. Analytics Alerts Configuration

The Verenigingen app includes Analytics Alert Rules:

### Create Alert Rules

```python
# Create alert for high error rate
alert_rule = frappe.new_doc("Analytics Alert Rule")
alert_rule.alert_name = "High Error Rate"
alert_rule.metric_type = "Error Rate"
alert_rule.condition = ">"
alert_rule.threshold_value = 5.0
alert_rule.check_frequency = "Hourly"
alert_rule.is_active = 1
alert_rule.action = "Send Email"
alert_rule.recipients = "admin@example.com"
alert_rule.insert()
```

### Monitor Member Metrics

```python
# Create alert for member churn
churn_alert = frappe.new_doc("Analytics Alert Rule")
churn_alert.alert_name = "High Member Churn"
churn_alert.metric_type = "Member Churn Rate"
churn_alert.condition = ">"
churn_alert.threshold_value = 10.0
churn_alert.check_frequency = "Daily"
churn_alert.webhook_url = "https://your-webhook.com/alerts"
churn_alert.insert()
```

## 6. Prometheus & Grafana Setup (Optional)

### Option A: Use Frappe Press Exporter

If using Frappe Press:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'frappe_press'
    static_configs:
      - targets: ['your-press-instance:9100']
```

### Option B: Custom Metrics Exporter

Create custom exporter:

```python
# verenigingen/monitoring/prometheus_exporter.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest
import frappe

# Define metrics
member_count = Gauge('verenigingen_member_count', 'Total number of members')
volunteer_count = Gauge('verenigingen_volunteer_count', 'Total number of volunteers')
donation_total = Gauge('verenigingen_donation_total', 'Total donations amount')

request_duration = Histogram('verenigingen_request_duration_seconds',
                           'Request duration', ['method', 'endpoint'])

error_count = Counter('verenigingen_errors_total',
                     'Total number of errors', ['error_type'])

@frappe.whitelist(allow_guest=True)
def metrics():
    """Prometheus metrics endpoint"""
    # Update metrics
    member_count.set(frappe.db.count("Member", {"status": "Active"}))
    volunteer_count.set(frappe.db.count("Volunteer", {"is_active": 1}))

    total_donations = frappe.db.sql("""
        SELECT SUM(grand_total) FROM `tabDonation`
        WHERE docstatus = 1
    """)[0][0] or 0
    donation_total.set(float(total_donations))

    # Return metrics
    frappe.response["content_type"] = "text/plain"
    return generate_latest()
```

### Grafana Dashboard

Import this dashboard JSON:

```json
{
  "dashboard": {
    "title": "Verenigingen Monitoring",
    "panels": [
      {
        "title": "Active Members",
        "targets": [{
          "expr": "verenigingen_member_count"
        }]
      },
      {
        "title": "Request Duration",
        "targets": [{
          "expr": "rate(verenigingen_request_duration_seconds_sum[5m])"
        }]
      },
      {
        "title": "Error Rate",
        "targets": [{
          "expr": "rate(verenigingen_errors_total[5m])"
        }]
      }
    ]
  }
}
```

## 7. Monitoring Checklist

### Daily Monitoring Tasks

- [ ] Check System Health Report
- [ ] Review Error Logs
- [ ] Monitor slow queries
- [ ] Check analytics alerts

### Weekly Tasks

- [ ] Review performance trends
- [ ] Analyze error patterns
- [ ] Check resource usage
- [ ] Review user activity

### Monthly Tasks

- [ ] Generate performance report
- [ ] Review and adjust alert thresholds
- [ ] Analyze member/volunteer metrics
- [ ] Plan optimization based on metrics

## 8. Troubleshooting

### Common Issues

1. **Sentry not capturing errors**
   - Check DSN is correct
   - Verify `is_sentry_enabled()` returns True
   - Check network connectivity

2. **Monitor logs not appearing**
   - Ensure `monitor: 1` in site_config.json
   - Check Redis is running
   - Verify write permissions on log directory

3. **Performance metrics missing**
   - Run `bench migrate`
   - Check scheduled jobs are running
   - Verify Analytics Snapshot creation

## 9. Best Practices

1. **Set up alerts for critical metrics:**
   - Error rate > 1%
   - Response time > 2 seconds
   - Failed login attempts > 10/hour
   - Database size growth > 10%/week

2. **Regular monitoring routine:**
   - Morning: Check overnight alerts
   - Midday: Review real-time metrics
   - Evening: Check daily summary

3. **Performance benchmarks:**
   - API response time < 200ms
   - Page load time < 2 seconds
   - Database queries < 100ms
   - Background job completion < 5 minutes

## 10. Additional Resources

- [Frappe Monitoring Docs](https://frappeframework.com/docs/user/en/monitoring)
- [Sentry Python SDK](https://docs.sentry.io/platforms/python/)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [Grafana Dashboard Guide](https://grafana.com/docs/grafana/latest/dashboards/)

## Summary

With this setup, you'll have:
- **Error tracking** via Sentry
- **Performance monitoring** via Performance Dashboard
- **System health checks** via built-in reports
- **Business metrics** via Analytics Alerts
- **Custom metrics** via Prometheus/Grafana (optional)

This provides comprehensive monitoring without building new tools from scratch!

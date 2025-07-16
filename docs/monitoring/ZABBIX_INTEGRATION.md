# Zabbix Integration Guide for Frappe/Verenigingen

## Overview

This guide explains how to integrate your existing Zabbix monitoring system with Frappe Cloud and the Verenigingen application.

## Integration Architecture

```
┌─────────────┐     HTTP/API      ┌─────────────┐     Webhook    ┌─────────────┐
│   Zabbix    │ ←───────────────→ │   Frappe    │ ←────────────→ │   Alerts    │
│   Server    │                   │   Cloud     │                 │   System    │
└─────────────┘                   └─────────────┘                 └─────────────┘
      ↓                                  ↓                               ↓
   Metrics                            Business                      Notifications
   Storage                             Logic                         & Actions
```

## Integration Methods

### 1. Zabbix → Frappe (Pull Metrics)

Zabbix pulls metrics from Frappe using HTTP Agent items:

**Advantages:**
- No changes needed in Frappe Cloud
- Uses existing Frappe APIs
- Works with Frappe Cloud's security model
- Real-time metric collection

**Configuration:**
1. Import the Zabbix template
2. Configure host with Frappe URL
3. Set up API authentication
4. Monitor metrics

### 2. Frappe → Zabbix (Push Metrics)

Frappe pushes metrics to Zabbix using Zabbix Sender protocol:

**Advantages:**
- More control over what metrics to send
- Can send business-specific metrics
- Reduces load on Frappe API

**Requirements:**
- Zabbix sender access from Frappe
- Scheduled job in Frappe

### 3. Bidirectional Integration

Combines both approaches for comprehensive monitoring:
- Zabbix pulls system metrics
- Frappe pushes business metrics
- Alerts flow both ways

## Setup Instructions

### Step 1: Configure Frappe for Monitoring

1. **Add monitoring endpoints to hooks.py:**

```python
# In verenigingen/hooks.py
# Add to scheduler_events
scheduler_events = {
    "cron": {
        "*/5 * * * *": [
            "verenigingen.monitoring.zabbix_integration.send_metrics_to_zabbix_scheduled"
        ]
    }
}

# Add webhook endpoint
webhook_events = {
    "on_webhook": "verenigingen.monitoring.zabbix_integration.zabbix_webhook_receiver"
}
```

2. **Configure site_config.json:**

```json
{
  "zabbix_url": "https://zabbix.yourdomain.com",
  "zabbix_user": "api_user",
  "zabbix_password": "secure_password",
  "zabbix_host_name": "frappe-production",
  "alert_recipients": ["admin@yourdomain.com"]
}
```

3. **Enable API access:**

```python
# Whitelist the monitoring endpoints
# In zabbix_integration.py, already done with @frappe.whitelist()
```

### Step 2: Configure Zabbix

1. **Import the Template:**

```bash
# In Zabbix web interface
Configuration → Templates → Import
Select: zabbix_template_frappe.xml
```

2. **Create Host:**

```
Configuration → Hosts → Create Host
Host name: frappe-production
Groups: Frappe Applications
Interfaces: None (using HTTP agent)
Templates: Template Frappe Cloud Monitoring
```

3. **Configure Macros:**

```
Host → Macros
{$FRAPPE_URL} = https://your-site.frappe.cloud
{$FRAPPE_API_KEY} = your-api-key (if using authentication)
```

4. **Set up Actions:**

```
Configuration → Actions → Create Action
Name: Send Frappe Alerts to Webhook
Conditions: Trigger severity >= Warning
Operations: Send webhook to Frappe
```

### Step 3: Configure Authentication

#### Option A: Guest Access (Simple)

Allow guest access to monitoring endpoints:

```python
@frappe.whitelist(allow_guest=True)
def get_metrics_for_zabbix():
    # Your metrics code
```

#### Option B: API Key Authentication

1. Create API user in Frappe:

```python
# Create user with limited permissions
user = frappe.new_doc("User")
user.email = "zabbix@yourdomain.com"
user.first_name = "Zabbix"
user.user_type = "System User"
user.insert()

# Generate API keys
api_key = frappe.generate_hash()
api_secret = frappe.generate_hash()
```

2. Configure Zabbix HTTP Agent:

```
Headers:
Authorization: token {$FRAPPE_API_KEY}:{$FRAPPE_API_SECRET}
```

#### Option C: IP Whitelisting

Add to nginx configuration:

```nginx
location /api/method/verenigingen.scripts.monitoring {
    allow 10.0.0.100;  # Zabbix server IP
    deny all;
    proxy_pass http://frappe;
}
```

### Step 4: Create Custom Metrics

Add business-specific metrics to monitor:

```python
# In your monitoring script
def get_custom_metrics():
    return {
        # Membership metrics
        "new_members_today": get_new_members_count(),
        "pending_applications": get_pending_applications(),
        "member_retention_rate": calculate_retention(),

        # Financial metrics
        "monthly_revenue": get_monthly_revenue(),
        "outstanding_payments": get_outstanding_amount(),
        "donation_goal_progress": get_donation_progress(),

        # Volunteer metrics
        "active_volunteers": get_active_volunteers(),
        "volunteer_hours": get_volunteer_hours(),
        "pending_expenses": get_pending_expenses(),

        # System metrics
        "email_queue_size": get_email_queue(),
        "failed_jobs": get_failed_jobs_count(),
        "last_backup_age": get_backup_age_hours()
    }
```

### Step 5: Set up Alerting

1. **Zabbix Triggers:**

```
# Critical Triggers
- Frappe application is down
- Error rate > 10%
- Response time > 5 seconds
- No backup for 24 hours

# Warning Triggers
- Error rate > 5%
- Response time > 2 seconds
- Queue size > 1000
- Low member retention
```

2. **Frappe Alert Handler:**

```python
# Automatically create issues for critical alerts
def handle_zabbix_alert(alert_data):
    if alert_data["severity"] == "Disaster":
        create_critical_issue(alert_data)
        notify_on_call_team(alert_data)
    elif alert_data["severity"] == "High":
        create_issue(alert_data)
        notify_team(alert_data)
    else:
        log_alert(alert_data)
```

## Monitoring Dashboards

### Zabbix Dashboard Widgets

1. **Business Metrics:**
   - Active Members Graph
   - Daily Donations Chart
   - Volunteer Engagement Score
   - Member Churn Rate

2. **Performance Metrics:**
   - Response Time Graph
   - Error Rate Timeline
   - API Call Volume
   - Queue Length

3. **System Health:**
   - Overall Health Score
   - Component Status
   - Backup Status
   - Scheduler Status

### Grafana Integration (Optional)

If using Grafana with Zabbix:

```sql
-- Example Grafana query for member growth
SELECT
  clock as time,
  value as "Active Members"
FROM history_uint
WHERE itemid = (
  SELECT itemid FROM items
  WHERE key_ = 'frappe.members.active'
)
ORDER BY clock
```

## Troubleshooting

### Common Issues

1. **Connection Refused:**
   - Check Frappe URL is accessible
   - Verify firewall rules
   - Check SSL certificate

2. **Authentication Failed:**
   - Verify API credentials
   - Check user permissions
   - Test with curl

3. **No Data:**
   - Check scheduler is running
   - Verify endpoints are whitelisted
   - Check error logs

### Debug Commands

```bash
# Test Frappe endpoint
curl -X GET https://your-site.frappe.cloud/api/method/verenigingen.monitoring.zabbix_integration.get_metrics_for_zabbix

# Test Zabbix API
curl -X POST http://zabbix.server/api_jsonrpc.php \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'

# Check Frappe logs
bench --site your-site console
>>> frappe.get_all("Error Log", filters={"method": ["like", "%zabbix%"]})
```

## Best Practices

1. **Metric Collection:**
   - Keep polling intervals reasonable (5+ minutes for business metrics)
   - Use caching for expensive queries
   - Aggregate data where possible

2. **Security:**
   - Use HTTPS for all connections
   - Implement authentication
   - Limit API permissions
   - Monitor access logs

3. **Performance:**
   - Create database indexes for frequently queried fields
   - Use read replicas if available
   - Implement rate limiting

4. **Alerting:**
   - Set appropriate thresholds
   - Use alert dependencies
   - Implement escalation policies
   - Test alert paths regularly

## Advanced Integration

### Custom Zabbix Module

Create a custom Frappe app for deeper integration:

```python
# frappe_zabbix/hooks.py
app_include_js = "/assets/frappe_zabbix/js/zabbix_dashboard.js"

# Custom dashboard showing Zabbix data in Frappe
def get_zabbix_dashboard_data():
    # Fetch data from Zabbix API
    # Display in Frappe dashboard
    pass
```

### Automated Remediation

```python
# Auto-remediate certain issues
def auto_remediate_issue(trigger):
    if trigger == "high_queue_size":
        frappe.enqueue("process_queue_items", queue="long")
    elif trigger == "low_disk_space":
        cleanup_old_files()
    elif trigger == "high_error_rate":
        restart_workers()
```

## Conclusion

This integration provides:
- ✅ Real-time monitoring of Frappe applications
- ✅ Business metric tracking in Zabbix
- ✅ Automated alerting and issue creation
- ✅ Historical data analysis
- ✅ Proactive issue detection

The combination of Zabbix's powerful monitoring capabilities with Frappe's business logic creates a comprehensive monitoring solution for your Verenigingen application.

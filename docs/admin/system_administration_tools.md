# System Administration Tools Guide

## Overview

The Verenigingen app includes comprehensive system administration tools for monitoring performance, analyzing database health, and optimizing the application. These tools are available through both the Frappe desk interface and command line.

## Accessing Admin Tools

### 1. Web Interface (Recommended)

**Admin Tools Page**: Navigate to `/admin_tools` in your browser
- Requires: System Manager or Verenigingen Administrator role
- Features: Visual dashboard with one-click tool execution
- Real-time results display

**System Health Dashboard**: Available in Frappe desk under "Verenigingen"
- Path: Frappe Desk → Verenigingen → System Health Dashboard
- Features: Live monitoring, performance graphs, optimization suggestions, business metrics
- Auto-refreshes data on load with loading indicators
- Enhanced with subscription billing and scheduler monitoring

### 2. Command Line Interface

All tools can be executed via bench commands:

```bash
# Check system health
bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.get_system_health

# Get performance dashboard (24 hours)
bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.get_performance_dashboard

# Get business metrics for monitoring
bench --site dev.veganisme.net execute verenigingen.monitoring.zabbix_integration.get_metrics_for_zabbix

# Test SEPA notifications
bench --site dev.veganisme.net execute verenigingen.utils.sepa_notifications.test_mandate_notification --args '["MANDATE-ID", "created"]'

# Analyze database performance
bench --site dev.veganisme.net execute verenigingen.utils.database_query_analyzer.analyze_database_performance

# Generate API documentation
bench --site dev.veganisme.net execute verenigingen.utils.api_doc_generator.generate_api_documentation
```

## Available Tools

### 1. System Health Check
- **Purpose**: Monitor overall system status and business operations
- **Checks**: Database connectivity, cache status, API response times, subscription processing, invoice generation, scheduler health
- **Output**: Health status (healthy/degraded/critical) with detailed metrics
- **Business Metrics**: Active subscriptions, invoice generation rates, payment processing health
- **Alerting**: Critical alerts for subscription processing delays (25+ hours) and stuck scheduler jobs

### 2. Performance Dashboard
- **Purpose**: 24-hour performance analysis
- **Metrics**: API response times, success rates, slow endpoints
- **Insights**: Identifies performance bottlenecks

### 3. Database Analysis
- **Purpose**: Analyze database performance and structure
- **Features**:
  - Slow query detection
  - Table size analysis
  - Index coverage reports
  - Missing index recommendations

### 4. Index Recommendations
- **Purpose**: Optimize database queries
- **Output**: SQL statements to create missing indexes
- **Application**: Can be applied directly or saved for review

### 5. API Documentation Generator
- **Purpose**: Generate comprehensive API documentation
- **Formats**:
  - OpenAPI 3.0 specification
  - Postman collection
  - Markdown documentation
- **Coverage**: All whitelisted API endpoints

### 6. Optimization Suggestions
- **Purpose**: Get actionable optimization recommendations
- **Categories**:
  - Slow endpoints requiring optimization
  - Large tables needing indexes
  - Failing API endpoints
  - Cache optimization opportunities

### 7. API Endpoint Summary
- **Purpose**: Quick overview of all available APIs
- **Details**: Endpoint paths, HTTP methods, parameters

### 8. Fraud Detection Stats
- **Purpose**: Monitor fraud detection system
- **Metrics**: Detection rates, flagged activities, patterns

### 9. Business & System Metrics (Enhanced)
- **Purpose**: Real-time business and operational monitoring
- **Metrics**:
  - **Subscription Health**: Active subscriptions count (submitted only), processing status
  - **Invoice Generation**: Sales invoices, subscription invoices, total invoices (daily counts)
  - **Scheduler Monitoring**: Hours since last subscription run, stuck job detection
  - **System Performance**: Database response times, error rates
- **Color-Coded Alerts**:
  - 🟢 Green: Normal operations (subscription processing < 4 hours ago)
  - 🟠 Orange: Warning state (4-25 hours since last processing)
  - 🔴 Red: Critical state (25+ hours or stuck jobs detected)
- **Integration**: Connects with Zabbix monitoring for external alerting

### 10. Database Statistics (Enhanced)
- **Purpose**: Database health and growth monitoring
- **Features**:
  - Table size analysis with proper number formatting
  - Row count tracking (formatted as numbers, not currency)
  - Index coverage analysis
  - Growth trend monitoring
- **Display**: Clean formatting with proper thousand separators

### 11. Cleanup Imported Data
- **Purpose**: Clean up all e-Boekhouden imported data for fresh migration
- **Warning**: ⚠️ **DESTRUCTIVE OPERATION** - Permanently deletes all imported data
- **Use Case**: Preparing for fresh data migration from e-Boekhouden
- **Output**: Count of deleted Journal Entries, Payment Entries, GL Entries, etc.
- **Safety**: Includes confirmation dialog in web interface

## Tool Outputs and Actions

### System Health Output Example (Enhanced)
```json
{
  "status": "healthy",
  "timestamp": "2025-07-15T08:30:00.123456",
  "checks": {
    "database": {
      "status": "ok",
      "response_time_ms": 12.5
    },
    "cache": {
      "status": "ok",
      "response_time_ms": 0.8
    },
    "subscription_processing": {
      "status": "ok",
      "message": "Last processed 2.1 hours ago",
      "last_processed": "2025-07-15 06:15:00",
      "active_subscriptions": 22,
      "invoices_today": 3
    },
    "invoice_generation": {
      "status": "ok",
      "message": "Invoice generation healthy",
      "sales_invoices_today": 3,
      "subscription_invoices_today": 3,
      "total_invoices_today": 3,
      "active_subscriptions": 22
    },
    "scheduler": {
      "status": "ok",
      "message": "Scheduler healthy (15 recent jobs)",
      "stuck_jobs": 0,
      "recent_activity": 15
    },
    "api_performance": {
      "status": "ok",
      "avg_response_time_ms": 245.3,
      "active_endpoints": 5
    }
  }
}
```

### Database Index Recommendations
```sql
-- Example output
CREATE INDEX idx_tabGL_Entry_due_date ON `tabGL Entry` (due_date);
CREATE INDEX idx_tabPayment_Entry_posting_date ON `tabPayment Entry` (posting_date);
CREATE INDEX idx_tabCustomer_email_id ON `tabCustomer` (email_id);
```

### Business Metrics Output (New)
```json
{
  "timestamp": "2025-07-15T08:30:00.123456",
  "metrics": {
    "active_subscriptions": 22,
    "sales_invoices_today": 3,
    "subscription_invoices_today": 3,
    "total_invoices_today": 3,
    "subscriptions_processed_today": 0,
    "last_subscription_run": 2.1,
    "stuck_jobs": 0,
    "active_members": 33,
    "pending_expenses": 0,
    "daily_donations": 0.0,
    "system_health": 85,
    "error_rate": 0.1,
    "job_queue_size": 0
  }
}
```

### API Documentation Output
- `/sites/dev.veganisme.net/private/files/api_docs/openapi_spec.json`
- `/sites/dev.veganisme.net/private/files/api_docs/postman_collection.json`
- `/sites/dev.veganisme.net/private/files/api_docs/api_documentation.md`

### Cleanup Imported Data Output
```json
{
  "success": true,
  "message": "Cleanup completed successfully",
  "results": {
    "ledger_entries_deleted": 8542,
    "journal_entries_deleted": 2826,
    "payment_entries_deleted": 156,
    "sales_invoices_deleted": 3,
    "purchase_invoices_deleted": 89,
    "gl_entries_deleted": 0,
    "customers_deleted": 245,
    "suppliers_deleted": 67
  }
}
```

## Recent Enhancements (July 2025)

### 1. Subscription Billing Monitoring
- **Enhanced Health Checks**: Added comprehensive subscription processing monitoring
- **Business Metrics Integration**: Real-time tracking of active subscriptions and invoice generation
- **Scheduler Health**: Detection of stuck jobs that block subscription processing
- **Alert Thresholds**: Configurable warning (4+ hours) and critical (25+ hours) alerts

### 2. Zabbix Integration
- **External Monitoring**: Integration with Zabbix for enterprise monitoring
- **Metrics Export**: `/get_metrics_for_zabbix` endpoint for external monitoring systems
- **Authentication**: Optional API key authentication for secure access
- **Error Handling**: Graceful handling of missing request context (e.g., bench execute calls)

### 3. Dashboard Improvements
- **Loading States**: Proper loading indicators that resolve correctly
- **Number Formatting**: Fixed database statistics showing currency instead of numbers
- **Business Metrics Section**: New dedicated section for subscription and invoice tracking
- **Error Resolution**: Fixed JavaScript formatting issues and API endpoint errors

### 4. SEPA Notification Fixes
- **Template Rendering**: Fixed string formatting issues in email template paths
- **Error Logging**: Improved error message formatting for better debugging
- **URL Generation**: Fixed dynamic URL generation in notification emails
- **Subject Formatting**: Corrected f-string usage for proper subject line generation

### 5. Data Quality Improvements
- **Submitted Documents Only**: Correctly filter for `docstatus = 1` to show only submitted records
- **Accurate Counts**: Active subscription counts now reflect actual business state
- **Consistent Formatting**: Standardized number formatting across all dashboard components

## Best Practices

### 1. Regular Monitoring
- Check system health daily
- Review performance dashboard weekly
- Analyze slow queries monthly

### 2. Optimization Workflow
1. Run system health check
2. Identify issues via performance dashboard
3. Get optimization suggestions
4. Apply database indexes if recommended
5. Monitor improvements

### 3. Documentation Updates
- Generate API docs after adding new endpoints
- Review and update regularly
- Share with development team

### 4. Security Considerations
- Tools require elevated permissions
- Review all SQL before execution
- Monitor access logs
- Restrict to trusted administrators

## Troubleshooting

### Common Issues

**"Permission Denied" Error**
- Ensure user has System Manager or Verenigingen Administrator role
- Check site permissions

**"Module Not Found" Error**
- Restart bench after updates: `bench restart`
- Clear cache: `bench clear-cache`

**"Object is not bound" Error (Zabbix Integration)**
- This occurs when calling API endpoints via bench execute without HTTP request context
- Fixed in July 2025 update with proper error handling
- Normal operation when called via web interface

**Dashboard Loading Issues**
- Check browser console for JavaScript errors
- Verify all API endpoints are accessible
- Restart services if metrics endpoints fail: `bench restart`

**Incorrect Active Subscription Count**
- Ensure queries include `docstatus = 1` filter for submitted documents only
- Draft subscriptions (docstatus = 0) should not count as active
- Fixed in July 2025 update

**SEPA Notification Email Errors**
- Check string formatting in notification templates
- Verify email template files exist in `verenigingen/templates/emails/`
- Fixed template path and subject formatting issues in July 2025

**Slow Tool Execution**
- Database analysis may take time on large databases
- Consider running during off-peak hours
- Use time limits for long operations

### Getting Help

1. Check error logs: `bench --site dev.veganisme.net console`
2. Review system logs: `/home/frappe/frappe-bench/logs/`
3. Contact system administrator
4. Submit issues to repository

## Advanced Usage

### Scheduling Automated Checks

Create a scheduled job in Frappe:
```python
# In hooks.py
scheduler_events = {
    "daily": [
        "verenigingen.utils.performance_dashboard.daily_health_check"
    ],
    "weekly": [
        "verenigingen.utils.database_query_analyzer.weekly_optimization_check"
    ]
}
```

### Custom Monitoring

Extend the monitoring system:
```python
from verenigingen.utils.performance_dashboard import PerformanceDashboard

dashboard = PerformanceDashboard()
custom_metrics = dashboard.get_custom_metrics(
    metric_type="business",
    hours=168  # Last week
)
```

### Integration with External Monitoring

Export metrics to external systems:
```python
# Export to monitoring service
metrics = get_system_health()
send_to_monitoring_service(metrics)
```

## Maintenance Schedule

### Daily Tasks
- System health check (including subscription processing status)
- Review error logs
- Check API success rates
- Monitor active subscription count and invoice generation
- Verify scheduler job status (stuck job detection)

### Weekly Tasks
- Performance dashboard review
- Database optimization check
- API documentation update
- Review business metrics trends
- Check Zabbix integration health

### Monthly Tasks
- Full database analysis
- Apply index recommendations
- Security audit
- Documentation review
- SEPA notification system testing
- Subscription billing health audit

## Emergency Procedures

### System Degradation
1. Run immediate health check
2. Identify failing components (database, cache, subscription processing, scheduler)
3. Check recent changes
4. Review error logs
5. Apply quick fixes or rollback

### Subscription Processing Crisis
1. Check subscription processing health via dashboard
2. Identify stuck scheduler jobs: `stuck_jobs > 0`
3. Review last subscription run time (critical if 25+ hours)
4. Restart scheduler if needed: `bench restart`
5. Monitor active subscription count and invoice generation
6. Check Zabbix alerts for external notification

### Performance Crisis
1. Run performance dashboard
2. Identify slow endpoints
3. Apply emergency indexes
4. Enable additional caching
5. Scale resources if needed

### SEPA Notification Failures
1. Check email template existence and formatting
2. Verify string formatting in notification code
3. Test with known mandate ID
4. Review error logs for template rendering issues
5. Restart services to reload updated templates

### Database Issues
1. Run database analyzer
2. Check table locks
3. Optimize slow queries
4. Apply missing indexes
5. Consider maintenance window

## Conclusion

These administration tools provide comprehensive monitoring and optimization capabilities for the Verenigingen system. Regular use ensures optimal performance and early detection of issues. Always follow security best practices and test changes in development before applying to production.

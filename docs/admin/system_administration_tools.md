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
- Features: Live monitoring, performance graphs, optimization suggestions
- Auto-refreshes every 30 seconds

### 2. Command Line Interface

All tools can be executed via bench commands:

```bash
# Check system health
bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.get_system_health

# Get performance dashboard (24 hours)
bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.get_performance_dashboard

# Analyze database performance
bench --site dev.veganisme.net execute verenigingen.utils.database_query_analyzer.analyze_database_performance

# Generate API documentation
bench --site dev.veganisme.net execute verenigingen.utils.api_doc_generator.generate_api_documentation
```

## Available Tools

### 1. System Health Check
- **Purpose**: Monitor overall system status
- **Checks**: Database connectivity, cache status, API response times
- **Output**: Health status (healthy/degraded/critical) with detailed metrics

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

### 9. Cleanup Imported Data
- **Purpose**: Clean up all e-Boekhouden imported data for fresh migration
- **Warning**: ⚠️ **DESTRUCTIVE OPERATION** - Permanently deletes all imported data
- **Use Case**: Preparing for fresh data migration from e-Boekhouden
- **Output**: Count of deleted Journal Entries, Payment Entries, GL Entries, etc.
- **Safety**: Includes confirmation dialog in web interface

## Tool Outputs and Actions

### System Health Output Example
```json
{
  "status": "healthy",
  "timestamp": "2025-07-07 10:30:00",
  "checks": {
    "database": {
      "status": "ok",
      "response_time_ms": 12.5
    },
    "cache": {
      "status": "ok",
      "response_time_ms": 0.8
    },
    "api": {
      "status": "ok",
      "response_time_ms": 45.2
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
- System health check
- Review error logs
- Check API success rates

### Weekly Tasks
- Performance dashboard review
- Database optimization check
- API documentation update

### Monthly Tasks
- Full database analysis
- Apply index recommendations
- Security audit
- Documentation review

## Emergency Procedures

### System Degradation
1. Run immediate health check
2. Identify failing components
3. Check recent changes
4. Review error logs
5. Apply quick fixes or rollback

### Performance Crisis
1. Run performance dashboard
2. Identify slow endpoints
3. Apply emergency indexes
4. Enable additional caching
5. Scale resources if needed

### Database Issues
1. Run database analyzer
2. Check table locks
3. Optimize slow queries
4. Apply missing indexes
5. Consider maintenance window

## Conclusion

These administration tools provide comprehensive monitoring and optimization capabilities for the Verenigingen system. Regular use ensures optimal performance and early detection of issues. Always follow security best practices and test changes in development before applying to production.

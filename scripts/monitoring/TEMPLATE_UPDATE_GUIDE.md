# Zabbix Template Update Guide

## New Metrics Available After Consolidation

### Performance Metrics
```yaml
- key: frappe.performance.response_time_p50
  name: "Response Time - 50th Percentile"
  value_type: FLOAT
  units: "ms"
  description: "Median response time"

- key: frappe.performance.response_time_p95
  name: "Response Time - 95th Percentile"  
  value_type: FLOAT
  units: "ms"
  description: "95% of requests are faster than this"

- key: frappe.performance.response_time_p99
  name: "Response Time - 99th Percentile"
  value_type: FLOAT
  units: "ms"
  description: "99% of requests are faster than this"
```

### Error Breakdown Metrics
```yaml
- key: frappe.errors.permission
  name: "Permission Errors (1h)"
  value_type: UNSIGNED
  description: "Permission denied errors in last hour"

- key: frappe.errors.validation
  name: "Validation Errors (1h)"
  value_type: UNSIGNED
  description: "Data validation errors in last hour"

- key: frappe.errors.not_found
  name: "Not Found Errors (1h)"
  value_type: UNSIGNED
  description: "Document not found errors in last hour"

- key: frappe.errors.duplicate
  name: "Duplicate Entry Errors (1h)"
  value_type: UNSIGNED
  description: "Duplicate key errors in last hour"

- key: frappe.errors.timeout
  name: "Timeout Errors (1h)"
  value_type: UNSIGNED
  description: "Request timeout errors in last hour"

- key: frappe.errors.other
  name: "Other Errors (1h)"
  value_type: UNSIGNED
  description: "Uncategorized errors in last hour"
```

### Enhanced Health Check
The health check endpoint now returns:
```json
{
  "status": "healthy|degraded|unhealthy",
  "score": 85.5,  // 0-100 health score
  "checks": {
    "database": {
      "status": "healthy",
      "response_time_ms": 5.2
    },
    "redis": {
      "status": "healthy"
    },
    "scheduler": {
      "status": "healthy",
      "last_run_minutes_ago": 2.5
    },
    "disk_space": {
      "status": "healthy",
      "percent_used": 65.3,
      "gb_free": 125.4
    },
    "subscriptions": {
      "status": "healthy",
      "last_run_hours_ago": 3.2
    },
    "financial": {
      "status": "healthy"
    }
  }
}
```

## Recommended Triggers

### Performance Triggers
```yaml
- name: "High Response Time (p95)"
  expression: "{vereiningen:frappe.performance.response_time_p95.avg(5m)}>1000"
  priority: WARNING
  description: "95th percentile response time exceeds 1 second"

- name: "Critical Response Time (p99)"
  expression: "{vereiningen:frappe.performance.response_time_p99.last()}>5000"
  priority: HIGH
  description: "1% of requests taking longer than 5 seconds"
```

### Error Pattern Triggers
```yaml
- name: "High Permission Error Rate"
  expression: "{verenigingen:frappe.errors.permission.last()}>50"
  priority: WARNING
  description: "More than 50 permission errors in last hour"

- name: "Validation Error Spike"
  expression: "{verenigingen:frappe.errors.validation.change()}>100"
  priority: AVERAGE
  description: "Sudden increase in validation errors"
```

### Health Score Trigger
```yaml
- name: "System Health Degraded"
  expression: "{verenigingen:frappe.health.score.last()}<80"
  priority: WARNING
  description: "Overall system health below 80%"

- name: "System Health Critical"
  expression: "{verenigingen:frappe.health.score.last()}<50"
  priority: HIGH
  description: "Overall system health below 50%"
```

## Auto-Remediation Setup

For Zabbix 7.0+, add tags to enable auto-remediation:

```yaml
triggers:
  - name: "High Memory Usage"
    tags:
      - tag: "auto_remediate"
        value: "clear_cache"
  
  - name: "Stuck Background Jobs"
    tags:
      - tag: "auto_remediate"
        value: "clear_jobs"
```

## Migration Steps

1. **Export current template** as backup
2. **Add new item prototypes** for metrics above
3. **Create triggers** based on your thresholds
4. **Test with discovery** to ensure metrics appear
5. **Set up dashboards** for new performance metrics
6. **Configure actions** for auto-remediation triggers

## Dashboard Suggestions

### Performance Dashboard
- Graph: Response time percentiles over time
- Pie chart: Error breakdown by type
- Single stat: Current health score
- Table: Health check component status

### Business Metrics Dashboard
- Keep existing business metrics
- Add health score as prominent indicator
- Show error trends by type
- Display performance percentiles

## Notes

- Performance metrics require `enable_advanced_metrics: true` in site config
- Auto-remediation requires proper webhook configuration
- Health score provides quick overall system assessment
- Error categorization helps identify patterns
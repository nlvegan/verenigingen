# System Health Dashboard Updates - July 2025

## Overview
The System Health Dashboard has been significantly enhanced with business monitoring capabilities, subscription billing health checks, and integration with external monitoring systems.

## Key Enhancements

### 1. Business Metrics Integration ✅
- **Real-time Subscription Monitoring**: Active subscriptions count (22 currently)
- **Invoice Generation Tracking**: Daily counts for sales, subscription, and total invoices
- **Scheduler Health Monitoring**: Detection of stuck jobs that block subscription processing
- **Color-coded Alerts**: Green (normal), Orange (warning 4+ hours), Red (critical 25+ hours)

### 2. Zabbix Integration ✅
- **External Monitoring Endpoint**: `/get_metrics_for_zabbix`
- **Comprehensive Metrics Export**: Business and system metrics for enterprise monitoring
- **Authentication Support**: Optional API key authentication
- **Error Handling**: Graceful handling of missing request context (bench execute compatibility)

### 3. Dashboard Fixes ✅
- **Loading Issues Resolved**: Fixed "Please wait..." popup getting stuck forever
- **Number Formatting**: Fixed database statistics showing currency (€ 556,926) instead of numbers (556,926)
- **API Endpoint Errors**: Resolved "object is not bound" errors in metrics collection
- **Subscription Count Accuracy**: Now correctly shows 22 active subscriptions with proper `docstatus = 1` filtering

### 4. SEPA Notification System Fixes ✅
- **Template Path Resolution**: Fixed string formatting issues in email template paths
- **URL Generation**: Corrected dynamic URL generation for notification emails
- **Error Message Formatting**: Improved error logging with proper f-string formatting
- **Email Delivery**: Verified successful notification sending ("SEPA Direct Debit Mandate Activated")

## Technical Details

### Enhanced Health Checks
```json
{
  "subscription_processing": {
    "status": "ok",
    "message": "Last processed 2.1 hours ago",
    "active_subscriptions": 22,
    "invoices_today": 3
  },
  "scheduler": {
    "status": "ok",
    "stuck_jobs": 0,
    "recent_activity": 15
  }
}
```

### Business Metrics Endpoint
- **Path**: `verenigingen.monitoring.zabbix_integration.get_metrics_for_zabbix`
- **Output**: JSON with 13+ business and system metrics
- **Integration**: Used by both dashboard and external monitoring

### Dashboard Components
1. **System Health Status**: Overall health with detailed component checks
2. **Performance Metrics**: API response times and success rates
3. **Business Metrics**: Subscription and invoice tracking (NEW)
4. **Database Statistics**: Table sizes with proper number formatting (FIXED)
5. **Optimization Suggestions**: Actionable recommendations
6. **API Performance**: Endpoint analysis and charting

## Access Information
- **URL**: Frappe Desk → Verenigingen → System Health Dashboard
- **Permissions**: System Manager or Verenigingen Administrator
- **Refresh**: Manual refresh button available
- **Loading**: Proper loading indicators with error handling

## Monitoring Capabilities

### Alert Thresholds
- **Green**: Subscription processing < 4 hours ago
- **Orange**: Subscription processing 4-25 hours ago
- **Red**: Subscription processing 25+ hours ago OR stuck jobs detected

### External Integration
- **Zabbix Endpoint**: `/get_metrics_for_zabbix`
- **Metrics Available**: 13+ including subscriptions, invoices, scheduler health
- **Authentication**: Optional token-based auth
- **Error Handling**: Graceful degradation for missing request context

## Recent Bug Fixes

### 1. Loading Popup Issue
- **Problem**: Dashboard stuck on "Please wait..." loading screen
- **Cause**: API endpoint crashing with "object is not bound" error
- **Fix**: Added proper error handling for missing HTTP request context
- **Status**: ✅ Resolved

### 2. Database Statistics Formatting
- **Problem**: Total rows showing as currency "€ 556,926"
- **Cause**: JavaScript using `format_currency()` instead of number formatting
- **Fix**: Changed to `toLocaleString()` for proper number display
- **Status**: ✅ Resolved

### 3. Active Subscriptions Count
- **Problem**: Dashboard showing 0 active subscriptions
- **Cause**: Missing `docstatus = 1` filter in database queries
- **Fix**: Added filter to count only submitted subscriptions
- **Status**: ✅ Resolved - now shows 22 active subscriptions

### 4. SEPA Notification Errors
- **Problem**: Email templates failing with path resolution errors
- **Cause**: String formatting issues with Python placeholders
- **Fix**: Converted to f-string formatting throughout notification system
- **Status**: ✅ Resolved - emails now send successfully

## Future Enhancements

### Planned Improvements
1. **Real-time Updates**: WebSocket integration for live dashboard updates
2. **Historical Trends**: Trend analysis for business metrics
3. **Custom Alerting**: User-configurable alert thresholds
4. **Mobile Optimization**: Responsive design improvements
5. **Export Capabilities**: CSV/PDF export of dashboard data

### Integration Opportunities
1. **Prometheus/Grafana**: Additional external monitoring integration
2. **Slack/Teams**: Alert notification integrations
3. **Email Reports**: Scheduled health summary emails
4. **API Monitoring**: Automatic performance tracking instrumentation

## Maintenance Notes

### Daily Monitoring
- Check subscription processing status (should be < 4 hours)
- Monitor active subscription count (currently 22)
- Verify invoice generation (daily counts)
- Review stuck job alerts

### Weekly Review
- Performance trends analysis
- Business metrics review
- External monitoring integration health
- Documentation updates

### Emergency Procedures
- **Subscription Processing Crisis**: Check dashboard, restart scheduler if needed
- **Dashboard Loading Issues**: Verify API endpoints, restart services
- **SEPA Notification Failures**: Check templates, verify formatting

## Conclusion
The enhanced System Health Dashboard now provides comprehensive monitoring of both technical infrastructure and business operations, with particular focus on subscription billing health - the critical business process that was previously failing due to stuck scheduler jobs. The integration with external monitoring systems and improved error handling ensures reliable operation and early detection of issues.

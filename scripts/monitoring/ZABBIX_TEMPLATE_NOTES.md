# Zabbix Template Notes

## Issues Found and Fixed

### 1. Value Map Type Constants (Zabbix 7.2)
In Zabbix 7.2, value map types use these constants:
- `EQUAL` = exact match (note: not "EQUALS")
- `GREATER_EQUAL` = greater or equal
- `LESS_EQUAL` = less or equal  
- `IN_RANGE` = in range
- `REGEXP` = regular expression
- `DEFAULT` = default value

**Fixed**: Changed `type: EQUALS` to `type: EQUAL` and kept `type: DEFAULT`

### 2. Invalid UUIDs
Original templates contained invalid UUIDs with non-hexadecimal characters (g-z).
UUIDs must only contain: 0-9, a-f, A-F

**Fixed**: Generated proper RFC 4122 compliant UUIDs for all template elements

### 3. Version Mismatch
"Compatible" template showed version 6.4 but claimed Zabbix 7.x compatibility

**Fixed**: Updated version to '7.0' for proper Zabbix 7.2 compatibility

### 4. Template Structure Issues
- Self-referential template definitions
- Dashboard configurations with invalid item references
- Calculated item syntax errors

**Fixed**: Removed problematic dashboard configs, simplified template structure

### 5. Preprocessing Improvements
- Added proper error handling for JSON parsing
- Added IN_RANGE validation for health scores
- Improved DISCARD_UNCHANGED_HEARTBEAT usage

## Template Files

- `zabbix_template_frappe_v7.2_fixed.yaml` - **RECOMMENDED** - Working template with proper value maps for Zabbix 7.2
- `zabbix_template_frappe_v7.2_minimal.yaml` - Alternative template without value maps (simpler)
- `zabbix_template_frappe_v7_compatible.yaml` - Partially fixed template (UUIDs still need fixing)
- `zabbix_template_frappe_v7.yaml` - Original advanced template (has dashboard issues)
- `zabbix_template_frappe.xml` - Legacy XML format (may need similar fixes)

## Import Instructions

**For Zabbix 7.2, use the fixed template:**

1. Go to Configuration → Templates
2. Click Import
3. Select `zabbix_template_frappe_v7.2_fixed.yaml`
4. Click Import
5. Configure macros:
   - `{$FRAPPE_URL}` - Your Frappe site URL
   - `{$FRAPPE_API_KEY}` - API key from Frappe
   - `{$FRAPPE_API_SECRET}` - API secret from Frappe

## Prerequisites

The template requires the monitoring API endpoint to be available:
- Endpoint: `/api/method/verenigingen.scripts.monitoring.zabbix_integration.get_metrics_for_zabbix`
- Authentication: API token (key:secret)
- Response format: JSON with metrics object

## Monitored Metrics

- **Health Status**: Application health check (/health endpoint)
- **Active Members**: Current member count
- **Financial**: Daily donations total
- **Performance**: Error rate and response times
- **System Health**: Overall health score percentage
- **Business**: Pending volunteer expenses
- **Infrastructure**: Background job queue size, database connections

## Trigger Thresholds

- Error Rate: Warning >5%, Critical >10%
- Response Time: Warning >2000ms
- Health Score: Critical <50%
- Job Queue: Warning >100 jobs
- DB Connections: Warning >80 connections

## Troubleshooting

### Import Fails
- Verify UUIDs are valid hexadecimal
- Check Zabbix version compatibility
- Ensure no duplicate template names

### No Data Received
- Verify API endpoint is accessible
- Check API credentials in macros
- Test endpoint manually: `curl -H "Authorization: token key:secret" https://yoursite/api/method/...`
- Check Zabbix agent logs for HTTP errors

### Triggers Not Working
- Verify trigger expressions syntax
- Check macro values are properly set
- Test individual items for data collection
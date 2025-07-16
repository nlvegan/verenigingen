# Zabbix Monitoring Migration Notes

## Summary of Changes (July 2025)

### Consolidation Completed
The monitoring implementation has been consolidated from two locations into a single enhanced module.

### What Was Done

1. **Created Enhanced Integration**
   - Location: `vereinigingen/monitoring/zabbix_integration_enhanced.py`
   - Combines features from both implementations
   - Adds Zabbix 7.0 support from the advanced script
   - Maintains backward compatibility

2. **Features Integrated**
   - All metrics from the main implementation (including invoice/subscription tracking)
   - Performance percentile metrics from advanced implementation
   - Error categorization from advanced implementation
   - Auto-remediation capabilities from advanced implementation
   - Enhanced webhook security with signature validation
   - Zabbix 7.0 metadata and tagging support

3. **Scripts Directory Status**
   - `zabbix_integration.py` - Can be removed (duplicate of main implementation)
   - `zabbix_v7_advanced.py` - Features integrated, can be archived
   - Template files - Should remain for Zabbix configuration
   - Documentation - Should remain for reference

### Migration Steps

1. **Update the main integration to use enhanced version**:
   ```python
   # In vereinigingen/monitoring/zabbix_integration.py
   # Import from enhanced version instead
   from .zabbix_integration_enhanced import *
   ```

2. **Update site configuration** (if using advanced features):
   ```json
   {
     "enable_advanced_metrics": true,
     "zabbix_version": "7",
     "zabbix_webhook_secret": "your-secret-key"
   }
   ```

3. **Update Zabbix template** to include new metrics:
   - Performance percentiles (p50, p95, p99)
   - Error breakdown by type
   - Enhanced health check endpoint

4. **Remove duplicate scripts**:
   ```bash
   # Archive old scripts
   mv scripts/monitoring/zabbix_integration.py scripts/monitoring/archived/
   mv scripts/monitoring/zabbix_v7_advanced.py scripts/monitoring/archived/
   ```

### New Capabilities

1. **Auto-Remediation** (from Zabbix 7.0 alerts):
   - Clear cache on high memory
   - Clear stuck background jobs
   - Restart Redis (requires sudo setup)

2. **Enhanced Health Check**:
   - Database response time
   - Redis connectivity
   - Scheduler health
   - Disk space
   - Subscription processing
   - Financial health

3. **Performance Metrics**:
   - Response time percentiles
   - Error categorization
   - Detailed health scoring

### Template Updates Required

The Zabbix template should be updated to include:
- New performance metrics (response_time_p50, p95, p99)
- Error breakdown metrics (errors_permission, errors_validation, etc.)
- Enhanced health check triggers
- Auto-remediation tags for specific alerts

### Testing Checklist

- [ ] Verify all existing metrics still work
- [ ] Test new performance percentile metrics
- [ ] Verify webhook signature validation
- [ ] Test auto-remediation features
- [ ] Confirm health check endpoint returns all data
- [ ] Validate Zabbix 7.0 metadata format

### Rollback Plan

If issues occur:
1. Revert vereinigingen/monitoring/zabbix_integration.py to original
2. Keep enhanced version for gradual migration
3. Scripts in scripts/monitoring can be used as fallback
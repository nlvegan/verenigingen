# Monitoring Directory Structure (Simplified)

## Active Files

### Core Implementation
- `zabbix_integration.py` - All Zabbix integration code

### Zabbix Templates
- `zabbix_template_frappe_v7.2_fixed.yaml` - **RECOMMENDED** for Zabbix 7.2+
- `zabbix_template_frappe_v7.2_minimal.yaml` - Minimal template for testing
- Other templates for compatibility with different Zabbix versions

### Documentation
- `ZABBIX_TEMPLATE_NOTES.md` - Template usage notes
- `TEMPLATE_UPDATE_GUIDE.md` - How to use new metrics
- `MONITORING_STRUCTURE.md` - This file

## How It Works

1. All monitoring code is in `scripts/monitoring/zabbix_integration.py`
2. The module `vereinigingen/monitoring/zabbix_integration.py` imports everything from here
3. API endpoints are accessed via: `verenigingen.monitoring.zabbix_integration.*`

## Available Endpoints
- `/api/method/verenigingen.monitoring.zabbix_integration.get_metrics_for_zabbix`
- `/api/method/verenigingen.monitoring.zabbix_integration.health_check`
- `/api/method/vereiningen.monitoring.zabbix_integration.zabbix_webhook_receiver`

## Configuration
Enable advanced features in site config:
```json
{
  "enable_advanced_metrics": true,
  "zabbix_version": "7",
  "zabbix_webhook_secret": "your-secret-key"
}
```

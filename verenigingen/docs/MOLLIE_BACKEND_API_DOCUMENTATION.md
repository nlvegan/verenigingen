# Mollie Backend API Integration Documentation

## Overview

This document provides comprehensive documentation for the Mollie Backend API integration within the Verenigingen association management system. The integration enables financial reporting, reconciliation, and business management capabilities using Mollie's Organization Access Token (OAT) approach.

### Integration Status
- ✅ Payment processing via Mollie Payments API
- ✅ Subscription management for recurring payments
- ✅ Webhook handling for payment status updates
- ✅ Backend API integration with Organization Access Token
- ✅ Financial dashboard with real-time balance data
- ✅ Settlement tracking and reconciliation
- ✅ Mollie Balance Report implementation

### Key Features
- **Real-time Balance Monitoring**: Live balance data from Mollie accounts
- **Settlement Tracking**: Comprehensive settlement data with reconciliation
- **Financial Reporting**: Automated reports with filtering capabilities
- **Security Framework**: Encrypted API key storage and audit trails
- **Error Handling**: Resilient API communication with fallback mechanisms

## Current Technical Architecture

### Architecture Principles
- **Security First**: Encrypted API key storage with audit trails
- **Modularity**: Focused client classes for specific API operations
- **Error Handling**: Comprehensive error recovery and fallback mechanisms
- **Real-time Data**: Live financial data with caching for performance
- **Compliance**: Audit trails and secure data handling

### Implemented Components
```
verenigingen/
├── verenigingen_payments/
│   ├── core/
│   │   ├── http_client.py              # Base HTTP client with retry logic
│   │   ├── mollie_base_client.py       # Base Mollie API client
│   │   ├── models/                     # Data models for API responses
│   │   │   ├── balance.py
│   │   │   ├── settlement.py
│   │   │   └── base.py
│   │   └── security/
│   │       └── mollie_security_manager.py
│   ├── clients/                        # Specialized API clients
│   │   ├── balances_client.py          # Balance operations
│   │   ├── settlements_client.py       # Settlement data
│   │   ├── chargebacks_client.py       # Chargeback management
│   │   └── invoices_client.py          # Invoice operations
│   ├── dashboards/
│   │   └── financial_dashboard.py      # Main financial dashboard
│   ├── doctype/
│   │   └── mollie_settings/            # Configuration management
│   └── report/
│       └── mollie_balance_report/      # Balance reporting
```

## Configuration

### Mollie Settings DocType

The integration is configured through the **Mollie Settings** DocType with the following key fields:

- **Enable Backend API**: Toggle for Backend API integration
- **Organization Access Token**: Encrypted storage for OAT
- **Profile ID**: Mollie profile identifier
- **Gateway Settings**: Payment processing configuration

### API Authentication

The Backend API uses Organization Access Tokens (OAT) for authentication:

```python
# Authentication is handled automatically by the base client
class MollieBaseClient:
    def __init__(self, settings_name=None):
        self.settings = frappe.get_single("Mollie Settings")
        self.oat = self.settings.get_password("organization_access_token")
        self.base_url = "https://api.mollie.com/v2"
```

## API Clients

### Balances Client

Handles balance-related operations:

```python
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

# Initialize client
balances_client = BalancesClient()

# Get all balances
balances = balances_client.list_balances()

# Get specific balance
balance = balances_client.get_balance("bal_abc123")

# Get balance summary
summary = balances_client.get_all_balances_summary()
```

### Settlements Client

Manages settlement data and reconciliation:

```python
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient

# Initialize client
settlements_client = SettlementsClient()

# Get settlements with date filtering
settlements = settlements_client.list_settlements(
    from_date=datetime(2025, 1, 1),
    until_date=datetime(2025, 8, 18)
)

# Get settlement details
settlement = settlements_client.get_settlement("stl_abc123")

# Reconcile settlement
reconciliation = settlements_client.reconcile_settlement("stl_abc123")
```

### Chargebacks Client

Handles chargeback and dispute management:

```python
from verenigingen.verenigingen_payments.clients.chargebacks_client import ChargebacksClient

# Initialize client
chargebacks_client = ChargebacksClient()

# List chargebacks
chargebacks = chargebacks_client.list_all_chargebacks()

# Get chargeback details
chargeback = chargebacks_client.get_chargeback("chb_abc123")
```

## Financial Dashboard

### Dashboard API

The financial dashboard provides real-time financial metrics:

```python
# Access dashboard data via API endpoint
@frappe.whitelist()
def get_dashboard_data():
    """Get comprehensive financial dashboard data"""
    dashboard = FinancialDashboard()
    return dashboard.get_dashboard_summary()
```

### Dashboard Metrics

The dashboard provides:

- **Balance Overview**: Available and pending amounts across currencies
- **Settlement Metrics**: Recent settlements and reconciliation status
- **Revenue Analysis**: Weekly, monthly, and quarterly revenue tracking
- **Cost Breakdown**: Transaction fees and chargeback costs
- **Reconciliation Status**: Success rates and unmatched items

### Accessing the Dashboard

Navigate to: **Verenigingen Payments > Mollie Dashboard**

URL: `https://your-site.com/www/mollie_dashboard.html`

## Reports

### Mollie Balance Report

A comprehensive script report showing real-time balance data:

**Access**: `/app/query-report/Mollie%20Balance%20Report`

**Features**:
- Real-time balance data from Mollie API
- Multi-currency support
- Filtering capabilities
- Export functionality

**Columns**:
- Balance ID
- Currency
- Status
- Available Amount
- Pending Amount
- Total Balance
- Transfer Frequency
- Last Updated

### Revenue Reports

Additional revenue tracking through the financial dashboard:
- Weekly revenue trends
- Monthly revenue analysis
- Quarterly revenue summaries
- Settlement reconciliation reports

## Security

### Encryption

- Organization Access Tokens are encrypted using Frappe's built-in encryption
- Sensitive financial data is handled with appropriate security measures
- Audit trails are maintained for all financial operations

### API Security

```python
class MollieSecurityManager:
    """Handles security operations for Mollie integration"""

    def store_api_key(self, key):
        """Securely store API key with encryption"""
        frappe.db.set_value("Mollie Settings", None, "organization_access_token", key)

    def get_api_key(self):
        """Retrieve decrypted API key"""
        return frappe.get_single("Mollie Settings").get_password("organization_access_token")
```

## Error Handling

### API Error Recovery

The integration includes comprehensive error handling:

- **Retry Logic**: Automatic retry for transient failures
- **Fallback Mechanisms**: Graceful degradation when API is unavailable
- **Error Logging**: Comprehensive error logging for debugging
- **Circuit Breaker**: Prevents cascading failures

### Common Error Scenarios

1. **API Rate Limiting**: Handled with exponential backoff
2. **Network Timeouts**: Automatic retry with increased timeout
3. **Invalid Parameters**: Comprehensive validation before API calls
4. **Authentication Errors**: Automatic token refresh when applicable

## Performance

### Caching Strategy

The integration implements intelligent caching:

```python
class FinancialDashboard:
    def _get_settlements_data(self):
        """Get settlements data with caching to prevent redundant API calls"""
        if self._settlements_cache is None:
            self._settlements_cache = self.settlements_client.get("settlements", paginated=True)
        return self._settlements_cache
```

### API Optimization

- **Pagination**: Automatic handling of paginated responses
- **Batch Processing**: Efficient processing of large datasets
- **Memory Management**: Optimized data structures for large financial datasets

## Monitoring

### Health Checks

Monitor the integration health:

```python
# Test API connectivity
@frappe.whitelist()
def test_mollie_connectivity():
    """Test Mollie API connectivity"""
    try:
        balances_client = BalancesClient()
        balances = balances_client.list_balances()
        return {"status": "success", "balances_count": len(balances)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### Metrics Tracking

Key metrics to monitor:
- API response times
- Success/failure rates
- Balance sync accuracy
- Settlement reconciliation rates

## Troubleshooting

### Common Issues

1. **Missing Organization Access Token**
   - Check Mollie Settings configuration
   - Ensure token has appropriate permissions

2. **API Connection Errors**
   - Verify network connectivity
   - Check API endpoint availability
   - Validate authentication credentials

3. **Data Sync Issues**
   - Check scheduled task execution
   - Verify data mapping accuracy
   - Review error logs for specific failures

### Debug Mode

Enable debug logging:

```python
frappe.logger().setLevel(logging.DEBUG)
```

## API Reference

### Base Client Methods

```python
class MollieBaseClient:
    def get(self, endpoint, params=None, paginated=False)
    def post(self, endpoint, data=None)
    def put(self, endpoint, data=None)
    def delete(self, endpoint)
```

### Balance Operations

```python
class BalancesClient:
    def list_balances(self, currency=None)
    def get_balance(self, balance_id)
    def get_balance_report(self, balance_id, from_date, until_date)
    def check_balance_health(self)
```

### Settlement Operations

```python
class SettlementsClient:
    def list_settlements(self, from_date=None, until_date=None, limit=250)
    def get_settlement(self, settlement_id)
    def reconcile_settlement(self, settlement_id)
    def get_settlement_summary(self, from_date, until_date)
```

## Future Enhancements

### Planned Features
- Enhanced reconciliation algorithms
- Advanced chargeback management
- Multi-currency reporting improvements
- Real-time webhook processing
- Advanced analytics and insights

### Scalability Considerations
- Connection pooling for high-volume operations
- Background job processing for large data syncs
- Database optimization for financial data queries
- Horizontal scaling support

## Support

For technical support or questions about the Mollie Backend API integration:

1. Check the error logs in ERPNext Error Log DocType
2. Review this documentation for configuration guidance
3. Test API connectivity using the built-in test endpoints
4. Consult the Mollie API documentation for API-specific questions

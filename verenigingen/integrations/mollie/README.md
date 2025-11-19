# Mollie Payment Integration v2.0

Complete service-oriented architecture for Mollie payment processing in the Verenigingen app.

## Overview

This integration provides a clean, maintainable architecture for handling Mollie payments with comprehensive logging, monitoring, and error handling. The system preserves all existing functionality while providing better structure for future enhancements.

## Architecture

```
verenigingen/integrations/mollie/
├── api/                    # HTTP endpoints
│   ├── payment_webhook.py  # Original webhook (preserved)
│   ├── unified_payment_api.py  # New unified API
│   └── monitoring_api.py   # Health & monitoring endpoints
├── core/                   # Core components
│   └── client.py          # Simplified Mollie API client
├── services/               # Business logic layer
│   ├── webhook_wrapper_service.py  # Wrapper for existing webhook
│   ├── payment_service.py  # Core payment operations
│   └── complete_payment_service.py # Full workflow management
├── utils/                  # Utilities
│   ├── logging.py         # Structured logging
│   ├── monitoring.py      # Health checks & performance
│   └── data_validator.py  # Validation utilities
├── exceptions/             # Custom exceptions
│   └── __init__.py        # Exception hierarchy
└── tests/                  # Test suites
    └── [organized tests]
```

## Key Features

### 🔄 Gradual Migration Strategy
- **Backward Compatibility**: All existing functionality preserved
- **Wrapper Pattern**: New services wrap existing working code
- **No Breaking Changes**: Smooth transition without disruption

### 🔍 Comprehensive Logging
- **Structured Logging**: Consistent format across all operations
- **Security Filtering**: Automatic removal of sensitive data (API keys, tokens)
- **Performance Tracking**: Duration and success rate monitoring
- **Business Context**: Payment IDs, donation names, operation types

### 📊 Performance Monitoring
- **Operation Metrics**: Track duration, success rates, error patterns
- **Health Checks**: API connectivity, service availability, endpoint validation
- **Alert Thresholds**: Automatic warnings for slow operations (>2s)
- **Resource Usage**: Memory and processing time tracking

### 🛡️ Enhanced Security
- **API Security Framework**: Proper operation type classification
- **Input Validation**: Comprehensive data validation
- **Error Handling**: Secure error messages without information leakage
- **Audit Trail**: Complete operation logging for compliance

## Service Layer

### WebhookWrapperService
Preserves existing webhook functionality while adding enhanced logging and monitoring.

```python
from verenigingen.integrations.mollie.services import WebhookWrapperService

service = WebhookWrapperService()
result = service.process_webhook(payment_id="tr_123")
```

**Features:**
- Idempotency protection
- Comprehensive logging at each step
- Performance tracking
- Error handling with context

### CompletePaymentService
Full-featured service for all payment operations.

```python
from verenigingen.integrations.mollie.services import CompletePaymentService

service = CompletePaymentService()
# Create donation payment
result = service.create_donation_payment(donation_doc, form_data)
# Handle subscription
subscription = service.create_customer_subscription(customer_data, subscription_data)
```

**Capabilities:**
- Payment creation and processing
- Subscription management
- Webhook processing
- Status monitoring

### MollieClient
Simplified API client focused on essential operations.

```python
from verenigingen.integrations.mollie.core import MollieClient

client = MollieClient()
payment = client.get_payment("tr_123")
new_payment = client.create_payment(payment_data)
```

## API Endpoints

### Webhook Processing
```
POST /api/method/verenigingen.integrations.mollie.api.unified_payment_api.handle_payment_webhook
```

### Payment Operations
```
POST /api/method/verenigingen.integrations.mollie.api.unified_payment_api.create_donation_payment
POST /api/method/verenigingen.integrations.mollie.api.unified_payment_api.create_subscription
```

### Monitoring & Health
```
GET /api/method/verenigingen.integrations.mollie.api.monitoring_api.get_integration_health
GET /api/method/verenigingen.integrations.mollie.api.monitoring_api.get_performance_metrics
GET /api/method/verenigingen.integrations.mollie.api.monitoring_api.get_service_status
```

## Logging Features

### Security-First Logging
```python
# Automatic sanitization of sensitive data
logger.info("Processing payment", {
    "payment_id": "tr_123...",  # Truncated for security
    "api_key": "***REDACTED***",  # Automatically filtered
    "amount": 25.00  # Safe data preserved
})
```

### Performance Tracking
```python
# Automatic operation timing
@mollie_operation_logger("webhook_processing")
def process_webhook(payment_id):
    # Your code here - timing happens automatically
    return result
```

### Business Context
```python
# Rich context for debugging
log_payment_processing(payment_id, "find_donation", "success", {
    "donation_name": "DON-001",
    "member_id": "MEM-123"
})
```

## Monitoring Dashboard

The monitoring system provides real-time insights into:

### Health Status
- **API Connectivity**: Mollie API availability and latency
- **Service Layer**: All services importable and functional
- **Webhook Endpoints**: Endpoint registration and accessibility

### Performance Metrics
- **Operation Success Rates**: Track success/failure patterns
- **Response Times**: Identify slow operations and bottlenecks
- **Error Patterns**: Categorize and track error types
- **Usage Trends**: Monitor operation frequency and timing

### Alerts and Notifications
- **Slow Operations**: Automatic warnings for operations >2 seconds
- **High Error Rates**: Alerts when success rate drops below 85%
- **Service Degradation**: Notifications when health checks fail

## Error Handling

### Custom Exception Hierarchy
```python
from verenigingen.integrations.mollie.exceptions import (
    MollieWebhookError,
    MolliePaymentError,
    MollieValidationError,
    MollieSecurityError
)

try:
    service.process_webhook(payment_id)
except MollieWebhookError as e:
    # Specific webhook handling
    logger.error(f"Webhook failed: {e}")
except MolliePaymentError as e:
    # Payment-specific handling
    logger.error(f"Payment failed: {e}")
```

### Structured Error Responses
```python
{
    "status": "error",
    "error_type": "MollieWebhookError",
    "message": "No donation found for payment",
    "payment_id": "tr_123",
    "context": {
        "operation": "find_donation",
        "timestamp": "2024-01-01T12:00:00Z"
    }
}
```

## Usage Examples

### Basic Webhook Processing
```python
# Using the wrapper service (recommended)
from verenigingen.integrations.mollie.services import WebhookWrapperService

service = WebhookWrapperService()
result = service.process_webhook("tr_123")

if result["status"] == "success":
    print(f"Payment processed: {result['message']}")
else:
    print(f"Processing failed: {result['message']}")
```

### Health Monitoring
```python
# Check integration health
from verenigingen.integrations.mollie.utils.monitoring import get_mollie_health_status

health = get_mollie_health_status()
print(f"Overall status: {health['health_check']['overall_status']}")
print(f"API latency: {health['health_check']['details'][0]['latency']}ms")
```

### Performance Analysis
```python
# Get performance metrics
from verenigingen.integrations.mollie.utils.monitoring import performance_monitor

stats = performance_monitor.get_operation_stats("webhook_processing", hours=24)
print(f"Success rate: {stats['success_rate']:.1f}%")
print(f"Average duration: {stats['avg_duration']:.2f}s")
```

## Migration Guide

### From Existing Code
1. **No Immediate Changes Required**: Existing webhook endpoints continue working
2. **Gradual Adoption**: Start using new services for new features
3. **Enhanced Monitoring**: Automatic logging improvement with no code changes
4. **Optional Migration**: Move to new APIs when convenient

### Best Practices
1. **Use Services**: Prefer service layer over direct API calls
2. **Check Health**: Monitor health endpoints for operational insights
3. **Review Logs**: Use structured logging for debugging
4. **Handle Errors**: Use custom exceptions for better error handling

## Development

### Testing
```bash
# Test service imports
python3 -c "from verenigingen.integrations.mollie.services import WebhookWrapperService; print('✅ Services working')"

# Test health checks
curl /api/method/verenigingen.integrations.mollie.api.monitoring_api.get_service_status
```

### Debugging
1. **Check Logs**: Look for mollie logger entries
2. **Health Status**: Use monitoring endpoints to identify issues
3. **Performance**: Review operation metrics for bottlenecks
4. **Service Layer**: Verify service instantiation and imports

## Future Enhancements

### Planned Features
- [ ] Enhanced subscription management service
- [ ] Automated reconciliation workflows
- [ ] Advanced analytics and reporting
- [ ] Integration test automation
- [ ] Performance optimization based on metrics

### Extension Points
- **Custom Services**: Add new services following the same patterns
- **Enhanced Monitoring**: Extend health checks for specific business requirements
- **Custom Logging**: Add business-specific logging contexts
- **Error Handling**: Extend exception hierarchy for specific error types

## Support

For issues or questions:
1. Check the monitoring endpoints for health status
2. Review structured logs for error context
3. Use the debugging utilities in the utils package
4. Refer to the test suites for usage examples

The Mollie integration v2.0 provides a solid foundation for reliable, maintainable payment processing with comprehensive observability and monitoring capabilities.

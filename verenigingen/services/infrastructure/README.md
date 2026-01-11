# Service Infrastructure Framework

This directory contains the shared infrastructure for building consistent, maintainable services across the Verenigingen application. The framework provides base classes, utilities, and patterns that ensure uniform behavior, proper error handling, performance monitoring, and comprehensive testing capabilities.

## Architecture Overview

The service infrastructure follows these key principles:

- **Separation of Concerns**: Clear distinction between business logic and infrastructure code
- **Consistency**: Standardized patterns for service development, error handling, and configuration
- **Observability**: Comprehensive metrics, logging, and health monitoring
- **Testability**: Robust testing framework with mocking and performance validation
- **Configurability**: Environment-specific configuration with validation

## Components

### Base Services (`base_service.py`)

Abstract base classes that provide common functionality:

- **`BaseService`**: Abstract base class with error handling, logging, and metrics
- **`StatelessService`**: For utility functions and calculations
- **`StatefulService`**: For services that maintain state and use transactions
- **`APIService`**: For HTTP API endpoints with input validation
- **`DataService`**: For database operations with caching and bulk operations

#### Example Usage

```python
from verenigingen.services.infrastructure.base_service import StatelessService

class CalculationService(StatelessService):
    def __init__(self):
        super().__init__("calculation")

    def validate_configuration(self) -> bool:
        return True

    def calculate_something(self, value: int) -> Dict:
        def operation():
            return value * 2

        return self.execute_operation(operation)
```

### Service Factory (`service_factory.py`)

Centralized service instantiation with dependency injection:

- **`ServiceFactory`**: Creates and manages service instances
- **`ServiceRegistry`**: Registers services with configuration
- **Dependency Injection**: Automatic resolution of service dependencies
- **Singleton Management**: Configurable singleton pattern for services

#### Example Usage

```python
from verenigingen.services.infrastructure.service_factory import get_service_factory

# Register a service
factory = get_service_factory()
factory.register_service("my_service", MyServiceClass, config={"setting": "value"})

# Get service instance
service = factory.get_service("my_service")
```

### Configuration Management (`service_config.py`)

Environment-specific configuration with validation:

- **`ServiceConfig`**: Configuration container with type validation
- **`ConfigurationManager`**: Centralized configuration management
- **`EnvironmentConfig`**: Environment-specific settings (dev/test/prod)
- **Validation**: Built-in configuration validation with custom validators

#### Example Usage

```python
from verenigingen.services.infrastructure.service_config import get_service_config

config = get_service_config("my_service")
config.set("max_items", 100, required=True)
config.add_validator("max_items", lambda x: x > 0)

# Get configuration values with environment variable override
max_items = config.get("max_items", default=50)
```

### Performance Monitoring (`service_metrics.py`)

Comprehensive metrics and health monitoring:

- **`ServiceMetrics`**: Individual service performance tracking
- **`MetricsCollector`**: Centralized metrics aggregation
- **`HealthMonitor`**: Service health checks with thresholds
- **`PerformanceProfiler`**: Detailed operation profiling

#### Example Usage

```python
from verenigingen.services.infrastructure.service_metrics import record_operation, get_service_health

# Record operation metrics
start_time = time.time()
# ... perform operation ...
duration = time.time() - start_time
record_operation("my_service", "my_operation", duration, success=True)

# Check service health
health = get_service_health("my_service")
```

### Testing Framework (`service_testing.py`)

Standardized testing patterns for services:

- **`ServiceTestCase`**: Base test class with common setup
- **`ServicePerformanceTest`**: Performance testing utilities
- **`ServiceIntegrationTest`**: Integration testing with real dependencies
- **`MockServiceFactory`**: Mock factory for isolated testing

#### Example Usage

```python
from verenigingen.services.infrastructure.service_testing import ServiceTestCase

class TestMyService(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.service = self.register_test_service("my_service", MyServiceClass)

    def test_operation(self):
        result = self.service.my_operation(param=123)
        self.assert_service_result(result, success=True, has_data=True)
```

## Service Development Guidelines

### 1. Service Class Design

All services should inherit from the appropriate base class:

```python
class MyBusinessService(StatefulService):
    def __init__(self):
        super().__init__("my_business")
        self.config = get_service_config("my_business")

    def validate_configuration(self) -> bool:
        # Implement configuration validation
        return super().validate_configuration()

    def my_business_operation(self, data: Dict) -> Dict:
        # Use transaction management for data operations
        return self.execute_with_transaction(self._perform_operation, data)
```

### 2. Error Handling

Use standardized error handling patterns:

```python
def risky_operation(self, param: str) -> Dict:
    try:
        result = self._perform_risky_operation(param)
        return self.create_result(success=True, data=result)
    except Exception as e:
        return self.handle_error(e, "risky_operation", {"param": param}, raise_error=False)
```

### 3. Configuration

Define and validate service configuration:

```python
def __init__(self):
    super().__init__("my_service")
    self.config = get_service_config("my_service")

    # Set configuration with validation
    self.config.set("timeout", 30, required=True)
    self.config.add_validator("timeout", lambda x: x > 0 and x < 300)
```

### 4. Performance Monitoring

Instrument operations for monitoring:

```python
def monitored_operation(self, data: Dict) -> Dict:
    start_time = self._start_operation("monitored_operation")

    try:
        result = self._perform_operation(data)
        self._end_operation("monitored_operation", start_time, success=True)
        return self.create_result(success=True, data=result)
    except Exception as e:
        self._end_operation("monitored_operation", start_time, success=False)
        raise
```

### 5. Testing

Write comprehensive tests using the testing framework:

```python
class TestMyService(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.service = self.register_test_service("my_service", MyService)

    def test_successful_operation(self):
        result = self.service.my_operation(valid_data)
        self.assert_service_result(result, success=True)
        self.assert_performance_within_limits(self.service)

    def test_error_handling(self):
        with self.simulate_database_error():
            result = self.service.my_operation(data)
            self.assert_service_result(result, success=False, has_errors=True)
```

## API Integration

Services can be easily exposed as API endpoints:

```python
@frappe.whitelist()
def my_api_endpoint(param1: str, param2: int) -> Dict:
    service = get_service("my_service")
    return service.my_operation(param1, param2)
```

## Monitoring and Observability

### Metrics Collection

All services automatically collect:
- Operation count and timing
- Error rates and counts
- Resource utilization
- Throughput metrics

### Health Monitoring

Health checks include:
- Response time thresholds
- Error rate limits
- Dependency availability
- Configuration validation

### Accessing Metrics

```python
# Get metrics for a specific service
from verenigingen.services.infrastructure.service_metrics import get_service_health

health = get_service_health("my_service")
print(f"Service status: {health['status']}")

# Get system-wide metrics
from verenigingen.services.infrastructure.service_metrics import get_system_health

system_health = get_system_health()
print(f"Overall status: {system_health['overall_status']}")
```

## Environment Configuration

The framework supports different environments:

- **Development**: Debug logging, relaxed validation, short cache timeouts
- **Testing**: Strict validation, no caching, comprehensive logging
- **Production**: Optimized performance, error-only logging, long cache timeouts

Set the environment using the `VERENIGINGEN_ENVIRONMENT` environment variable.

## Migration Guide

To migrate existing services to use this infrastructure:

1. **Inherit from Base Class**: Change your service class to inherit from the appropriate base class
2. **Implement Required Methods**: Add `validate_configuration()` method
3. **Update Error Handling**: Use standardized error handling patterns
4. **Add Configuration**: Define service configuration with validation
5. **Instrument Operations**: Add performance monitoring to key operations
6. **Write Tests**: Create tests using the testing framework

## Performance Considerations

- **Caching**: Use built-in caching for expensive operations
- **Batch Operations**: Use bulk operation utilities for database operations
- **Connection Pooling**: Database connections are managed automatically
- **Memory Management**: Services are designed to be memory-efficient
- **Monitoring Overhead**: Minimal performance impact from monitoring (~1% overhead)

## Security

- **Input Validation**: Built-in input validation for API services
- **Authentication**: Integration with Frappe security framework
- **Authorization**: Proper permission checking for sensitive operations
- **Audit Logging**: Comprehensive logging for security auditing

## Troubleshooting

### Common Issues

1. **Service Not Found**: Ensure service is registered with the factory
2. **Configuration Errors**: Check configuration validation errors
3. **Performance Issues**: Use the profiler to identify bottlenecks
4. **Test Failures**: Ensure proper test isolation and cleanup

### Debug Mode

Enable debug mode by setting:
```bash
export VERENIGINGEN_ENVIRONMENT=development
```

This enables:
- Verbose logging
- Extended error messages
- Performance profiling
- Configuration validation warnings

## Future Enhancements

Planned infrastructure improvements:

- **Service Mesh**: Distributed service discovery and communication
- **Circuit Breakers**: Automatic failure handling and recovery
- **Rate Limiting**: Built-in rate limiting for API services
- **Distributed Tracing**: Cross-service request tracing
- **Auto-scaling**: Automatic service scaling based on load

## Contributing

When adding new infrastructure components:

1. Follow the established patterns and conventions
2. Add comprehensive documentation and examples
3. Include thorough test coverage
4. Update this README with new capabilities
5. Consider backward compatibility with existing services

For questions or suggestions, please contact the Verenigingen development team.

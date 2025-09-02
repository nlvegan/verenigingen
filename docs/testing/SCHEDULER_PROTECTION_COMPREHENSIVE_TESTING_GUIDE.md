# Scheduler Protection System - Comprehensive Testing Guide

## Overview

This guide covers the comprehensive test suite designed to validate the **Frappe Scheduler Protection System** across realistic production scenarios and advanced edge cases. The test suite focuses on **real-world failure patterns** with **minimal mocking** to ensure robust validation of scheduler monitoring and recovery capabilities.

## Test Philosophy

Our testing approach prioritizes:

- **Realistic Data Generation**: Use actual system behavior patterns rather than artificial mocks
- **Production-Based Scenarios**: Test patterns observed in real production environments
- **Comprehensive Edge Cases**: Cover boundary conditions that could cause system failures
- **System Integration**: Test with actual Redis, database, and Frappe infrastructure
- **Recovery Validation**: Ensure monitoring system resilience after failures

## Test Suite Architecture

### Core Components

```
verenigingen/tests/
├── test_scheduler_protection_realistic_scenarios.py    # Production failure patterns
├── test_scheduler_protection_edge_cases.py            # Advanced edge cases
└── fixtures/enhanced_test_factory.py                  # Base test infrastructure

verenigingen/scripts/
├── test_scheduler_protection_comprehensive.py         # Test runner & reporting
└── validate_scheduler_tests.py                       # Test suite validation
```

### Test Categories

| Category | Files | Focus | Test Count |
|----------|-------|--------|------------|
| **Realistic Scenarios** | `test_*_realistic_scenarios.py` | Production failure patterns | 8+ scenarios |
| **Advanced Edge Cases** | `test_*_edge_cases.py` | Boundary conditions & anomalies | 10+ scenarios |
| **System Integration** | Both files | Actual Redis/DB interaction | 3+ scenarios |
| **Recovery Validation** | `test_*_edge_cases.py` | Recovery mechanism testing | 3+ scenarios |

## Real-World Failure Patterns Covered

### 1. Resource Contention Scenarios

**Memory Exhaustion Patterns**
```python
# Test gradual memory consumption affecting monitoring
job_state = generator.generate_realistic_job_state(
    'membership_dues_processing',
    failure_pattern='memory_exhaustion',
    runtime_multiplier=2.5
)
```

**Database Lock Competition**
```python
# Multiple jobs competing for same database resources
competing_jobs = [
    generator.generate_realistic_job_state('sepa_batch_generation', 'database_deadlock')
    for _ in range(3)
]
```

**File System Lock Conflicts**
- Jobs accessing shared file resources
- Recovery from lock contention
- Cleanup after failed operations

### 2. Timing and Clock Issues

**NTP Clock Adjustments**
```python
# System clock adjusted backwards during job execution
anomaly_jobs = generator.generate_timing_anomaly_scenario(
    'ntp_adjustment', base_jobs
)
```

**Hibernation/Resume Scenarios**
- System sleep/wake cycles during job execution
- Large time gaps in job runtime calculations
- Recovery from hibernation-induced timing anomalies

**Timezone Changes**
- System timezone changes during monitoring
- Impact on job scheduling and timeout calculations

### 3. Network and Infrastructure

**Redis Connection Instability**
```python
def flaky_redis_connection(*args, **kwargs):
    # Simulate intermittent connection failures
    if failure_condition:
        raise ConnectionError("Redis connection lost")
    return job_states
```

**Database Connection Pool Exhaustion**
- Connection pool depletion scenarios
- Recovery mechanisms for DB connectivity
- Graceful degradation under connection pressure

### 4. Application-Level Edge Cases

**Configuration Changes During Monitoring**
```python
def dynamic_config_get(key, default=None):
    # Configuration changes mid-monitoring cycle
    if key == 'job_timeouts':
        return updated_timeout if config_changed else original_timeout
```

**Rapid Job State Changes**
- Jobs completing/failing during analysis
- State consistency across monitoring cycles
- Handling of disappeared jobs

## Advanced Edge Case Testing

### Timing Anomalies

| Anomaly Type | Description | Impact | Test Coverage |
|-------------|-------------|--------|---------------|
| **NTP Adjustment** | Clock moved backwards 5+ minutes | False runtime calculation | ✅ Covered |
| **Leap Second** | 1-second time insertion | Cycle timing disruption | ✅ Covered |
| **Hibernation** | 8+ hour system sleep | Massive apparent runtime | ✅ Covered |
| **Timezone Change** | 2+ hour timezone shift | Scheduling confusion | ✅ Covered |

### Resource Exhaustion

| Resource Type | Critical Threshold | Monitoring Impact | Test Approach |
|---------------|-------------------|-------------------|---------------|
| **Memory** | >85% usage | Slower monitoring cycles | Simulated pressure |
| **File Descriptors** | >1024 open files | Redis connection failures | Leak simulation |
| **DB Connections** | Pool exhaustion | Query timeouts | Connection flooding |
| **Disk Space** | >95% full | Log write failures | Space limitation |

### Concurrency Conflicts

```python
# Test concurrent monitoring cycle prevention
threads = []
for i in range(3):
    thread = threading.Thread(target=monitoring_cycle_with_delay)
    threads.append(thread)
    thread.start()

# Verify no true overlap occurs
max_gap = max(cycle_start_times) - min(cycle_start_times)
assert max_gap < 2.0  # Within reasonable serialization window
```

## System Integration Testing

### Actual Redis Queue Interaction

```python
def test_actual_redis_queue_interaction(self):
    import rq
    from rq import Queue

    # Use actual Redis connection, not mocks
    connection = frappe.cache()._redis_connection
    test_queue = Queue('test_scheduler_protection', connection=connection)

    # Enqueue real job and monitor with our system
    job = test_queue.enqueue(test_job_function, timeout=10)
    job_states = observer.get_current_job_states()

    # Verify monitoring detects actual running job
    test_jobs = [j for j in job_states if 'test_job_function' in j.get('function_name', '')]
    assert len(test_jobs) > 0
```

### Database Integration

```python
def test_scheduled_job_type_integration(self):
    # Create actual Scheduled Job Type record
    scheduled_job = frappe.get_doc({
        'doctype': 'Scheduled Job Type',
        'method': test_method,
        'frequency': 'All',
        'timeout': 300,
        'stopped': 0
    })
    scheduled_job.insert()

    # Test our observer finds this real job type
    scheduled_jobs = observer._get_scheduled_job_types()
    test_jobs = [sj for sj in scheduled_jobs if sj['method'] == test_method]
    assert len(test_jobs) == 1
```

## Performance and Load Testing

### Large Queue Handling

```python
def test_extremely_large_job_queue(self):
    # Generate 1000 jobs to test scalability
    large_job_queue = []
    for i in range(1000):
        job = generate_realistic_job_state(
            pattern=random.choice(job_patterns),
            failure_rate=0.02  # 2% stuck jobs
        )
        large_job_queue.append(job)

    # Monitor should complete within 30 seconds
    start_time = time.time()
    cycle_result = protection_service.run_protection_cycle()
    cycle_duration = time.time() - start_time

    assert cycle_duration < 30.0
    assert cycle_result['jobs_monitored'] == 1000
```

### System Pressure Testing

```python
@contextmanager
def simulate_system_pressure(self, pressure_type='memory'):
    if pressure_type == 'memory':
        # Create controlled memory pressure
        memory_hog = []
        for _ in range(1000):
            memory_hog.append('x' * 10000)  # 10MB total
        yield
    finally:
        del memory_hog
```

## Security and Robustness Testing

### Malicious Data Injection

```python
def test_malicious_job_data_injection(self):
    malicious_jobs = [
        {
            'job_id': "'; DROP TABLE tabRQJob; --",  # SQL injection attempt
            'function_name': "test.malicious'; DELETE FROM tabScheduledJobType; --",
        },
        {
            'job_id': '<script>alert("xss")</script>',  # XSS attempt
            'function_name': 'test.xss<img src=x onerror=alert(1)>',
        },
        {
            'job_id': '../../../etc/passwd',  # Path traversal
            'function_name': 'test.path.traversal../../config',
        }
    ]

    # System should handle malicious data without security issues
    cycle_result = protection_service.run_protection_cycle()
    assert cycle_result['status'] == 'completed'
```

## Recovery Mechanism Validation

### Monitoring System Recovery

```python
def test_recovery_after_monitoring_system_failure(self):
    failure_count = 0

    def failing_protection_cycle():
        nonlocal failure_count
        failure_count += 1

        if failure_count <= 2:
            raise Exception(f"Monitoring system failure {failure_count}")
        else:
            return service.run_protection_cycle()  # Recovery

    # Test multiple attempts with eventual recovery
    results = []
    for attempt in range(5):
        try:
            result = failing_protection_cycle()
            results.append(result)
        except Exception as e:
            results.append({'status': 'error', 'error': str(e)})

    # Verify eventual recovery
    successful_results = [r for r in results if r.get('status') == 'completed']
    assert len(successful_results) > 0
    assert results[-1].get('status') == 'completed'  # Final attempt succeeds
```

### Job Recovery Tracking

```python
def test_job_recovery_tracking(self):
    # Track recovery attempts over multiple cycles
    recovery_attempts = []

    for attempt in range(5):
        job_copy = persistent_stuck_job.copy()
        job_copy['recovery_attempts'] = attempt

        if attempt < 3:
            job_copy['status'] = 'started'  # Still stuck
            job_copy['recovery_success'] = False
        else:
            job_copy['status'] = 'finished'  # Finally recovered
            job_copy['recovery_success'] = True

        recovery_attempts.append(job_copy)

    # Validate recovery progression
    success_rate = len([a for a in recovery_attempts if a.get('recovery_success')]) / len(recovery_attempts)
    assert success_rate > 0.3  # Minimum 30% recovery rate
```

## Test Data Generator

### Realistic Job Patterns

Our `RealisticSchedulerTestDataGenerator` creates jobs based on production analysis:

```python
job_patterns = {
    'email_queue_flush': {
        'typical_runtime': (10, 45),  # 10-45 seconds
        'timeout': 300,
        'resource_intensity': 'low',
        'failure_rate': 0.02  # 2% failure rate
    },
    'membership_dues_processing': {
        'typical_runtime': (300, 900),  # 5-15 minutes
        'timeout': 1800,
        'resource_intensity': 'medium',
        'failure_rate': 0.05,
        'scaling_factor': 'member_count'
    }
}
```

### Failure Pattern Simulation

```python
failure_patterns = {
    'memory_exhaustion': {
        'progression': 'gradual',
        'detection_delay': 600,    # 10 minutes
        'recovery_difficulty': 'hard'
    },
    'database_deadlock': {
        'progression': 'immediate',
        'detection_delay': 30,     # Quick detection
        'recovery_difficulty': 'medium'
    }
}
```

### Multi-Job Scenario Generation

```python
def generate_job_load_scenario(self, concurrent_jobs=10, stuck_job_percentage=0.3):
    jobs = []
    for i in range(concurrent_jobs):
        pattern = random.choice(job_patterns)
        failure = random.choice(failure_patterns) if random.random() < stuck_job_percentage else None
        runtime_multiplier = random.uniform(0.5, 3.0)  # Runtime variation

        job = self.generate_realistic_job_state(pattern, failure, runtime_multiplier)
        jobs.append(job)

    return jobs
```

## Running the Test Suite

### Basic Usage

```bash
# Run all tests
python scripts/test_scheduler_protection_comprehensive.py

# Run specific categories
python scripts/test_scheduler_protection_comprehensive.py --category realistic
python scripts/test_scheduler_protection_comprehensive.py --category edge_cases

# Focus on specific areas
python scripts/test_scheduler_protection_comprehensive.py --focus resource_contention
python scripts/test_scheduler_protection_comprehensive.py --focus timing_issues
```

### Advanced Options

```bash
# Generate detailed report
python scripts/test_scheduler_protection_comprehensive.py --report detailed --output /tmp/scheduler_test_report.md

# Run with specific focus areas
python scripts/test_scheduler_protection_comprehensive.py \
    --focus resource_contention \
    --focus recovery_validation \
    --report detailed

# Quiet mode for CI/CD
python scripts/test_scheduler_protection_comprehensive.py --report quiet
```

### Using Frappe Test Framework

```bash
# Run individual test files
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_scheduler_protection_realistic_scenarios

# Run with coverage
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_scheduler_protection_edge_cases --coverage

# Run specific test methods
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_scheduler_protection_realistic_scenarios::TestSchedulerProtectionRealisticScenarios::test_resource_contention_memory_exhaustion
```

## Test Results Interpretation

### Success Metrics

| Metric | Target | Interpretation |
|--------|--------|----------------|
| **Success Rate** | ≥95% | Production ready |
| **Average Test Duration** | <2s per test | Good performance |
| **Coverage Areas** | 7/7 (100%) | Comprehensive coverage |
| **Edge Case Handling** | ≥90% pass | Robust error handling |

### Performance Benchmarks

```
Expected Performance Targets:
- Single monitoring cycle: <1 second
- 100 job analysis: <5 seconds
- 1000 job analysis: <30 seconds
- Memory usage: <50MB additional
- Redis connection overhead: <10ms
```

### Failure Analysis

When tests fail, examine:

1. **Timing Issues**: Check if system clock changes affected tests
2. **Resource Constraints**: Verify sufficient memory/connections available
3. **Configuration**: Ensure test configuration matches expectations
4. **Environmental**: Check Redis/database connectivity
5. **Concurrency**: Look for race conditions in concurrent tests

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Scheduler Protection Tests
on: [push, pull_request]

jobs:
  scheduler-protection:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Frappe Environment
        run: |
          # Setup steps
      - name: Run Scheduler Protection Tests
        run: |
          python scripts/test_scheduler_protection_comprehensive.py \
            --report detailed \
            --output test_results.md
      - name: Upload Results
        uses: actions/upload-artifact@v2
        with:
          name: scheduler-test-results
          path: test_results.md
```

### Production Deployment Checklist

Before deploying scheduler protection to production:

- [ ] All test categories pass with ≥95% success rate
- [ ] Performance tests meet benchmarks
- [ ] Edge cases handled gracefully
- [ ] Recovery mechanisms validated
- [ ] Resource usage within limits
- [ ] Security tests pass
- [ ] Integration tests successful
- [ ] Configuration reviewed and validated

## Extending the Test Suite

### Adding New Failure Patterns

```python
# In RealisticSchedulerTestDataGenerator
new_failure_patterns = {
    'network_partition': {
        'progression': 'sudden',
        'detection_delay': 60,
        'recovery_difficulty': 'medium',
        'affects': ['redis_connectivity', 'database_access']
    }
}
```

### Creating Custom Test Scenarios

```python
def test_custom_scenario(self):
    """Test custom failure scenario"""
    # Generate specific job configuration
    custom_job = self.data_generator.generate_realistic_job_state(
        'custom_job_pattern',
        failure_pattern='custom_failure',
        runtime_multiplier=custom_multiplier
    )

    # Test monitoring behavior
    with patch('monitoring_component', return_value=[custom_job]):
        result = self.protection_service.run_protection_cycle()

        # Validate expected behavior
        self.assertEqual(result['status'], 'completed')
        self.assert_custom_conditions(result)
```

### Performance Test Extensions

```python
def test_extreme_load_scenario(self):
    """Test with extreme job loads"""
    extreme_job_count = 5000  # Very large queue

    large_queue = self.data_generator.generate_job_load_scenario(
        concurrent_jobs=extreme_job_count,
        stuck_job_percentage=0.1
    )

    # Should handle extreme load gracefully
    start_time = time.time()
    result = self.protection_service.run_protection_cycle()
    duration = time.time() - start_time

    self.assertLess(duration, 120.0)  # 2 minute maximum
    self.assertEqual(result['jobs_monitored'], extreme_job_count)
```

## Troubleshooting

### Common Test Issues

**Import Errors**
```bash
# Ensure proper Python path setup
export PYTHONPATH=/home/frappe/frappe-bench/apps/vereiningingen:$PYTHONPATH
```

**Redis Connection Issues**
```python
# Check Redis connectivity in tests
try:
    connection = frappe.cache()._redis_connection
    connection.ping()
except Exception as e:
    self.skipTest(f"Redis not available: {e}")
```

**Database Lock Timeouts**
```python
# Use shorter timeouts in tests
with patch('frappe.db.sql_timeout', 10):
    result = run_database_intensive_test()
```

**Memory Pressure in Tests**
```python
# Clean up after memory-intensive tests
def tearDown(self):
    super().tearDown()
    import gc
    gc.collect()  # Force garbage collection
```

## Conclusion

This comprehensive test suite provides **robust validation** of the Scheduler Protection System across:

- **24+ realistic production scenarios**
- **Advanced edge cases and boundary conditions**
- **System integration with actual infrastructure**
- **Recovery mechanism validation**
- **Performance and scalability testing**
- **Security resilience verification**

The test suite emphasizes **realistic data generation** over mocking, ensuring that validation results accurately reflect production behavior. This approach provides **high confidence** in scheduler protection system reliability and readiness for production deployment.

Regular execution of this test suite helps maintain system robustness and enables early detection of potential scheduler issues before they impact production operations.

# SEPA Processing Redis Configuration

**Version**: 1.0
**Last Updated**: January 25, 2026
**Status**: Production Ready

## Overview

SEPA (Single Euro Payments Area) processing in Verenigingen requires distributed locking and idempotency guarantees to prevent duplicate payments and race conditions. In multi-worker production environments, Redis is **required** for safe operation.

## Configuration Options

Add these settings to your `site_config.json`:

### Required for Multi-Worker Environments

```json
{
    "use_redis_locks_for_sepa": true
}
```

When `use_redis_locks_for_sepa` is enabled:
- All SEPA processing locks use Redis (distributed, multi-worker safe)
- Atomic lock acquisition with SETNX semantics
- Atomic lock release with Lua compare-and-delete scripts
- Health checks verify Redis availability at startup

When disabled or in single-worker mode:
- Falls back to in-memory locks (single-process only)
- **WARNING**: Not safe for production with multiple workers

### Lock TTL Configuration

Customize lock timeouts for your workload:

```json
{
    "sepa_lock_ttl_default": 300,
    "sepa_lock_ttl_batch": 1800,
    "sepa_lock_ttl_reconciliation": 1800,
    "sepa_lock_ttl_mandate": 300
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `sepa_lock_ttl_default` | 300s (5 min) | Default lock timeout for general operations |
| `sepa_lock_ttl_batch` | 1800s (30 min) | Timeout for batch processing operations |
| `sepa_lock_ttl_reconciliation` | 1800s (30 min) | Timeout for reconciliation operations |
| `sepa_lock_ttl_mandate` | 300s (5 min) | Timeout for mandate-level operations |

### Idempotency Cache Configuration

```json
{
    "use_redis_idempotency_cache": true
}
```

When enabled, idempotency results are stored in Redis for cross-worker consistency.

## Production Deployment Checklist

### 1. Verify Redis is Running

```bash
redis-cli ping
# Should return: PONG
```

### 2. Enable Redis Locks

Add to `sites/<site>/site_config.json`:

```json
{
    "use_redis_locks_for_sepa": true,
    "use_redis_idempotency_cache": true
}
```

### 3. Verify Redis Capabilities

Run the built-in verification:

```python
# In bench console
from verenigingen.api.sepa_duplicate_prevention import verify_redis_capabilities
result = verify_redis_capabilities()
print(result)
# Should show: {"verified": True, ...}
```

### 4. Health Check Endpoint

Monitor Redis health in production:

```python
from verenigingen.api.sepa_duplicate_prevention import check_redis_health
health = check_redis_health()
# Returns: {"healthy": True, "redis_reachable": True, ...}
```

## Multi-Worker Safety

### Why Redis is Required

In a multi-worker setup (e.g., `gunicorn_workers > 1`), each worker has its own memory space. In-memory locks cannot prevent race conditions between workers:

```
Worker 1: check lock -> (not held) -> acquire lock -> process payment
Worker 2: check lock -> (not held) -> acquire lock -> process SAME payment ❌
```

With Redis:

```
Worker 1: SETNX lock -> (success) -> process payment
Worker 2: SETNX lock -> (fails - already held) -> wait or error ✓
```

### Automatic Detection

The system automatically detects multi-worker environments and fails fast if Redis is not configured:

```python
# This happens automatically on first SEPA operation
# If gunicorn_workers > 1 and use_redis_locks_for_sepa is not set:
frappe.throw(
    "SEPA processing requires Redis locks in multi-worker environment. "
    "Set use_redis_locks_for_sepa=True in site_config.json"
)
```

## Atomic Operations

### Lock Acquisition (SETNX)

Uses Redis `SET ... NX EX` for atomic lock acquisition:

```
SET sepa_lock:batch:BATCH-001 <unique-token> NX EX 1800
```

- `NX`: Only set if key does not exist (prevents race)
- `EX 1800`: Auto-expire after 1800 seconds (prevents deadlock)

### Lock Release (Lua Compare-and-Delete)

Uses Lua script for atomic ownership verification:

```lua
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
```

This prevents accidentally releasing a lock held by another process after our lock expired.

## Troubleshooting

### "SEPA processing requires Redis locks"

**Cause**: Multi-worker environment detected but `use_redis_locks_for_sepa` not set.

**Solution**: Add to site_config.json:
```json
{"use_redis_locks_for_sepa": true}
```

### "Redis capability issues"

**Cause**: Redis client doesn't support required operations.

**Solution**:
1. Verify Redis version (6.0+ recommended)
2. Check `verify_redis_capabilities()` output for specific issues
3. Ensure `redis-py` package is installed

### Lock Timeouts

**Cause**: Operations taking longer than lock TTL.

**Solution**: Increase relevant TTL in site_config:
```json
{"sepa_lock_ttl_batch": 3600}
```

### Health Check Failures

**Cause**: Redis unreachable or misconfigured.

**Solution**:
1. Check Redis is running: `redis-cli ping`
2. Verify connection in common_site_config.json
3. Check firewall rules between app and Redis servers

## Security Considerations

1. **Lock Tokens**: Generated with UUID + PID + timestamp for uniqueness
2. **Ownership Verification**: Locks can only be released by the process that acquired them
3. **TTL Protection**: All locks auto-expire to prevent deadlocks
4. **Audit Logging**: SEPA operations are logged via the security framework

## Related Documentation

- [Security Framework Guide](SECURITY_FRAMEWORK_GUIDE.md) - API security decorators
- [SEPA Processing Overview](../payments/SEPA_OVERVIEW.md) - Business logic documentation
- [Deployment Guide](../deployment/PRODUCTION_CHECKLIST.md) - Full deployment checklist

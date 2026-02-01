# SEPA Operations Runbook

**Version**: 1.0
**Last Updated**: February 2026
**Status**: Production Ready

## Overview

This runbook covers operational procedures for SEPA Direct Debit processing in Verenigingen. It includes daily workflows, error handling, and emergency procedures.

---

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Batch Processing Workflow](#batch-processing-workflow)
3. [Handling pain.002 Rejections](#handling-pain002-rejections)
4. [Reconciliation Procedures](#reconciliation-procedures)
5. [Health Check Monitoring](#health-check-monitoring)
6. [Duplicate Detection Procedures](#duplicate-detection-procedures)
7. [Redis Configuration](#redis-configuration)
8. [Sandbox Mode](#sandbox-mode)
9. [Emergency Procedures](#emergency-procedures)
10. [Escalation Paths](#escalation-paths)

---

## Daily Operations

### Morning Checklist

1. **Check SEPA Health Status**
   ```python
   # In bench console
   from verenigingen.api.sepa_health import get_sepa_health
   health = get_sepa_health()
   print(health)
   ```

   Expected: `"status": "healthy"`

2. **Review Pending Batches**
   - Navigate to: Direct Debit Batch List
   - Filter: Status in ["Pending Approval", "Approved", "Exported"]
   - Action: Process any batches awaiting action

3. **Check pain.002 Inbox**
   - Verify pain.002 ingestion job ran (hourly scheduler)
   - Check `/var/sepa/archive/` for processed files
   - Check `/var/sepa/error/` for any failed files

4. **Review Reconciliation Status**
   - Check for transactions pending > 7 days
   - Threshold: Warning at 25, Critical at 75

### End of Day Checklist

1. Ensure all approved batches are exported
2. Verify no batches stuck in intermediate states
3. Check health endpoint shows healthy status

---

## Batch Processing Workflow

### Complete Workflow

```
Draft → Pending Approval → Approved → Exported → Uploaded → Acknowledged → Processed
```

### Step-by-Step Processing

#### 1. Create Batch (Draft)
- Create new Direct Debit Batch
- Add transactions (mandates)
- Set collection date (minimum 5 business days ahead for FRST, 2 for RCUR)

#### 2. Submit for Approval (Pending Approval)
- Click "Submit for Approval"
- Batch enters approval queue

#### 3. Approve Batch (Approved)
- **Four-Eyes Principle**: Approver must be different from creator
- Required role: Accounts Manager
- Review all transactions before approving

#### 4. Export XML (Exported)
- Generate pain.008.001.08 XML
- File hash is recorded to prevent duplicates
- Download XML file for bank upload

#### 5. Upload to Bank Portal (Uploaded)
- Upload XML to bank portal manually
- Mark batch as "Uploaded" in system
- System blocks duplicate uploads via hash check

#### 6. Bank Acknowledgement (Acknowledged)
- Bank sends pain.002 status report
- System ingests automatically via hourly job
- Status updated to Acknowledged or Rejected

#### 7. Process Collection (Processed)
- Collection executed by bank
- Final reconciliation
- Mark as Processed

### State Transition Rules

| From State | Allowed Transitions |
|------------|---------------------|
| Draft | Pending Approval, Cancelled |
| Pending Approval | Approved, Draft, Cancelled |
| Approved | Exported, Draft, Cancelled |
| Exported | Uploaded, Cancelled |
| Uploaded | Acknowledged, Rejected |
| Acknowledged | Processed, Rejected |
| Processed | (Terminal) |
| Rejected | Draft |
| Cancelled | (Terminal) |

---

## Handling pain.002 Rejections

### Automatic Ingestion

The system automatically processes pain.002 files hourly:
- Inbox: `/var/sepa/inbox/` (configurable via `sepa_pain002_inbox`)
- Archive: `/var/sepa/archive/`
- Errors: `/var/sepa/error/`

### Manual Ingestion

```python
# In bench console
from verenigingen.services.payment.pain002_ingestion_service import Pain002IngestionService

service = Pain002IngestionService()
result = service.run_ingestion_job()
print(result)
```

### Rejection Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| ACCP | Accepted | No action needed |
| ACSP | Accepted Settlement in Process | Monitor for completion |
| ACTC | Accepted Technical | No action needed |
| PART | Partially Accepted | Review individual transactions |
| RJCT | Rejected | Investigate and re-submit |

### Handling Rejected Batches

1. **Review Rejection Reason**
   - Check `bank_error_message` in SEPA Batch Upload Log
   - Common reasons: Invalid IBAN, insufficient funds, expired mandate

2. **Correct Issues**
   - Return batch to Draft state
   - Fix identified issues
   - Re-submit through approval workflow

3. **Contact Bank if Unclear**
   - Escalate technical rejections to bank support
   - Reference the original MsgId in communications

---

## Reconciliation Procedures

### Daily Reconciliation

1. **Match Bank Statements**
   - Compare settled amounts with expected collections
   - Flag discrepancies immediately

2. **Handle Returns**
   - R-transactions (returns) appear within D+5
   - Update member records for failed collections
   - Consider mandate status updates

3. **Update Transaction Status**
   - Mark successful transactions as Processed
   - Mark failed transactions appropriately

### Reconciliation Alerts

The system monitors unreconciled transactions:

```python
from verenigingen.services.payment.alert_manager import AlertManager

manager = AlertManager()
result = manager.check_reconciliation_status(
    unreconciled_count=current_count,
    threshold=25,
    critical_threshold=75
)

if result.alert_triggered:
    print(f"ALERT: {result.severity} - {result.message}")
```

---

## Health Check Monitoring

### Health Check Endpoint

```python
from verenigingen.api.sepa_health import get_sepa_health
health = get_sepa_health()
```

### Response Structure

```json
{
    "status": "healthy" | "degraded",
    "timestamp": "2026-02-01 10:00:00",
    "checks": {
        "redis": {
            "healthy": true,
            "locks_enabled": true,
            "message": "Redis operational"
        },
        "pending_batches": {
            "healthy": true,
            "count": 3,
            "warning": false
        },
        "unreconciled": {
            "healthy": true,
            "count": 12,
            "threshold": 50
        },
        "recent_uploads": {
            "healthy": true,
            "count_24h": 2
        }
    }
}
```

### Monitoring Integration

Set up monitoring to poll health endpoint every 5 minutes:

```bash
# Example cron job
*/5 * * * * curl -s https://site/api/method/verenigingen.api.sepa_health.get_sepa_health | jq '.status'
```

Alert when status is "degraded".

---

## Duplicate Detection Procedures

### How Duplicate Prevention Works

1. **File Hash Check**: SHA256 hash of pain.008 XML content
2. **Pre-Upload Validation**: Check hash before bank upload
3. **Upload Log**: Record all uploads in SEPA Batch Upload Log

### Checking for Duplicates Manually

```python
from verenigingen.services.payment.sepa_upload_guard import SEPAUploadGuard

guard = SEPAUploadGuard()
with open("batch.xml", "rb") as f:
    content = f.read()

result = guard.check_upload_allowed(content, "BATCH-001")
if not result.success:
    print(f"DUPLICATE: {result.message}")
    print(f"Previous batch: {result.duplicate_batch}")
    print(f"Previous upload: {result.duplicate_upload_time}")
```

### Handling Suspected Duplicates

1. **DO NOT re-upload** - Contact bank first
2. Check SEPA Batch Upload Log for previous upload record
3. Verify with bank portal if upload was received
4. If confirmed duplicate in bank system, cancel one batch

---

## Redis Configuration

### Required Settings

Add to `site_config.json`:

```json
{
    "use_redis_locks_for_sepa": true,
    "use_redis_idempotency_cache": true
}
```

### Verify Redis Health

```python
from verenigingen.api.sepa_duplicate_prevention import check_redis_health, verify_redis_capabilities

health = check_redis_health()
print(f"Redis healthy: {health['healthy']}")

capabilities = verify_redis_capabilities()
print(f"Capabilities verified: {capabilities['verified']}")
```

### Multi-Worker Safety

**CRITICAL**: In multi-worker environments (gunicorn_workers > 1), Redis locks are REQUIRED:

- Without Redis: In-memory locks only protect single worker
- With Redis: Distributed locks protect all workers

The system will warn on startup if multi-worker is detected without Redis locks.

### Lock TTL Configuration

```json
{
    "sepa_lock_ttl_default": 300,
    "sepa_lock_ttl_batch": 1800,
    "sepa_lock_ttl_reconciliation": 1800,
    "sepa_lock_ttl_mandate": 300
}
```

---

## Sandbox Mode

### Enabling Sandbox Mode

Add to `site_config.json`:

```json
{
    "sepa_sandbox_mode": true
}
```

### What Sandbox Mode Does

1. **Prefixes Message IDs**: All MsgIds get "TEST-" prefix
2. **Blocks Bank Uploads**: Upload guard rejects all uploads
3. **Generates Test IBANs**: Safe IBAN generation for testing

### Verifying Sandbox Mode

```python
from verenigingen.utils.sepa_sandbox import get_sandbox

sandbox = get_sandbox()
print(f"Sandbox mode: {sandbox.is_sandbox_mode()}")

result = sandbox.check_upload_allowed()
print(f"Upload allowed: {result.allowed}")
print(f"Message: {result.message}")
```

### Disabling Sandbox Mode

Remove or set to false in `site_config.json`:

```json
{
    "sepa_sandbox_mode": false
}
```

**IMPORTANT**: Always verify sandbox mode is disabled before production operations.

---

## Emergency Procedures

### Duplicate Batch Submitted to Bank

**Severity**: CRITICAL

1. **Immediate**: Contact bank helpdesk
2. **Reference**: Provide MsgId from batch
3. **Request**: Cancel duplicate submission
4. **Document**: Record incident in system comments
5. **Follow-up**: Verify only one batch processed

### System Showing Degraded Health

**Severity**: HIGH

1. **Check Redis**: `redis-cli ping` should return PONG
2. **Check Workers**: Verify gunicorn workers are running
3. **Check Logs**: Review `frappe-bench/logs/` for errors
4. **Restart if needed**: `bench restart`

### pain.002 Files Not Processing

**Severity**: MEDIUM

1. **Check Inbox**: Files present in `/var/sepa/inbox/`?
2. **Check Scheduler**: `bench show-pending-jobs`
3. **Manual Run**:
   ```python
   from verenigingen.services.payment.pain002_ingestion_service import run_pain002_ingestion
   run_pain002_ingestion()
   ```
4. **Check Errors**: Review `/var/sepa/error/` for failed files

### Batch Stuck in Intermediate State

**Severity**: MEDIUM

1. **Identify Cause**: Check batch comments for errors
2. **State Machine Check**:
   ```python
   from verenigingen.services.payment.sepa_batch_state_machine import SEPABatchStateMachine
   sm = SEPABatchStateMachine()
   print(sm.get_allowed_transitions(current_state))
   ```
3. **Force Transition** (Admin only): Use state machine's `execute_transition`

---

## Escalation Paths

### Level 1: Operations Team
- Routine issues
- Daily monitoring alerts
- Standard batch processing questions
- Response time: < 4 hours

### Level 2: Technical Support
- System errors
- Integration issues
- Configuration changes
- Response time: < 2 hours

### Level 3: Development Team
- Code bugs
- Feature requests
- Architecture decisions
- Response time: < 1 business day

### Level 4: Management
- Financial discrepancies > €1000
- Regulatory concerns
- Bank relationship issues
- Response time: Immediate

### Contact Information

| Level | Contact | Method |
|-------|---------|--------|
| L1 Operations | operations@example.org | Email/Slack |
| L2 Technical | tech-support@example.org | Email/Phone |
| L3 Development | dev-team@example.org | Jira ticket |
| L4 Management | cfo@example.org | Direct call |

---

## Appendix: Quick Reference Commands

### Bench Console Commands

```python
# Health check
from verenigingen.api.sepa_health import get_sepa_health
get_sepa_health()

# Redis verification
from verenigingen.api.sepa_duplicate_prevention import check_redis_health
check_redis_health()

# Sandbox status
from verenigingen.utils.sepa_sandbox import get_sandbox
get_sandbox().is_sandbox_mode()

# Manual pain.002 ingestion
from verenigingen.services.payment.pain002_ingestion_service import run_pain002_ingestion
run_pain002_ingestion()

# Check upload allowed
from verenigingen.services.payment.sepa_upload_guard import SEPAUploadGuard
guard = SEPAUploadGuard()
guard.check_upload_allowed(content, batch_name)

# Reconciliation alert check
from verenigingen.services.payment.alert_manager import AlertManager
AlertManager().check_reconciliation_status(unreconciled_count=50)
```

### Configuration Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `use_redis_locks_for_sepa` | false | Enable Redis distributed locks |
| `sepa_sandbox_mode` | false | Enable sandbox testing mode |
| `sepa_pain002_inbox` | /var/sepa/inbox | pain.002 file inbox |
| `sepa_pain002_archive` | /var/sepa/archive | Processed file archive |
| `sepa_lock_ttl_default` | 300 | Default lock timeout (seconds) |
| `sepa_lock_ttl_batch` | 1800 | Batch processing timeout |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-01 | System | Initial creation |

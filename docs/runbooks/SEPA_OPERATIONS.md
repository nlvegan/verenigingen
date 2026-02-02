# SEPA Operations Runbook

**Version**: 1.1
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
8. [Encryption Key Management](#encryption-key-management)
9. [Sandbox Mode](#sandbox-mode)
10. [Phantom Hash Remediation](#phantom-hash-remediation)
11. [Emergency Procedures](#emergency-procedures)
12. [Escalation Paths](#escalation-paths)

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

## Encryption Key Management

### About Field Encryption

The system uses Fernet symmetric encryption (AES-128-CBC with HMAC) for sensitive field data like IBANs. The encryption key is stored in `site_config.json`.

**Production Requirement**: In production (developer_mode=False), the encryption key MUST be configured. The system will throw an error if no key is present, preventing silent data loss.

### Initial Key Setup

1. **Generate a key**:
   ```python
   from cryptography.fernet import Fernet
   print(Fernet.generate_key().decode())
   ```

2. **Add to site_config.json**:
   ```json
   {
       "field_encryption_key": "<your-generated-key>"
   }
   ```

3. **Verify**:
   ```python
   from verenigingen.utils.field_encryption import get_encryption
   enc = get_encryption()
   test = enc.encrypt("test-data")
   print(f"Encrypted: {test}")
   print(f"Decrypted: {enc.decrypt(test)}")
   ```

### Key Rotation Procedure

**Severity**: HIGH - Data loss risk if done incorrectly

**Pre-Rotation Steps**:

1. **Take a full backup**:
   ```bash
   bench --site veg11.veganisme.org backup
   ```

2. **Export encrypted data** (all IBANs):
   ```python
   # Run in bench console
   from verenigingen.utils.field_encryption import get_encryption
   enc = get_encryption()

   # Find all encrypted values
   members = frappe.get_all("Member", fields=["name", "iban"])
   export = []
   for m in members:
       if m.iban and m.iban.startswith("ENC:"):
           export.append({
               "member": m.name,
               "decrypted_iban": enc.decrypt(m.iban)
           })

   # Save to secure location (NOT in codebase)
   import json
   with open("/tmp/iban_export.json", "w") as f:
       json.dump(export, f)
   print(f"Exported {len(export)} IBANs")
   ```

3. **Verify export integrity**:
   - Spot-check several decrypted values
   - Confirm export file is readable

**Rotation Steps**:

1. **Generate new key**:
   ```python
   from cryptography.fernet import Fernet
   new_key = Fernet.generate_key().decode()
   print(f"New key: {new_key}")
   # SAVE THIS KEY SECURELY BEFORE PROCEEDING
   ```

2. **Re-encrypt all data with new key**:
   ```python
   # In bench console
   import json
   from cryptography.fernet import Fernet

   # Load export
   with open("/tmp/iban_export.json", "r") as f:
       export = json.load(f)

   # Create new encryptor
   new_key = "<paste-new-key-here>"
   new_fernet = Fernet(new_key.encode())

   # Re-encrypt each value
   for item in export:
       encrypted = "ENC:" + base64.urlsafe_b64encode(
           new_fernet.encrypt(item["decrypted_iban"].encode())
       ).decode()
       frappe.db.set_value("Member", item["member"], "iban", encrypted)

   frappe.db.commit()
   print(f"Re-encrypted {len(export)} IBANs")
   ```

3. **Update site_config.json**:
   - Replace `field_encryption_key` with new key
   - Clear cache: `bench clear-cache`

### Batch Processing for Large Datasets

For sites with >1000 encrypted records, use batch processing to avoid timeouts and memory issues:

```python
# In bench console
import json
from cryptography.fernet import Fernet
import base64

# Load export
with open("/tmp/iban_export.json", "r") as f:
    export = json.load(f)

# Create new encryptor
new_key = "<paste-new-key-here>"
new_fernet = Fernet(new_key.encode())

# Process in batches of 100
BATCH_SIZE = 100
total = len(export)

for i in range(0, total, BATCH_SIZE):
    batch = export[i:i + BATCH_SIZE]

    for item in batch:
        encrypted = "ENC:" + base64.urlsafe_b64encode(
            new_fernet.encrypt(item["decrypted_iban"].encode())
        ).decode()
        frappe.db.set_value("Member", item["member"], "iban", encrypted)

    # Commit after each batch
    frappe.db.commit()

    # Progress indicator
    processed = min(i + BATCH_SIZE, total)
    print(f"Progress: {processed}/{total} ({100*processed//total}%)")

print(f"Re-encrypted {total} IBANs in batches of {BATCH_SIZE}")
```

**Performance Tips:**
- Use batch size 50-100 for production to balance speed and safety
- Run during off-peak hours (scheduled maintenance window)
- Monitor database load during rotation
- Keep the export file secure until rotation is verified

4. **Verify rotation**:
   ```python
   from verenigingen.utils.field_encryption import get_encryption
   enc = get_encryption()

   # Test decryption with new key
   member = frappe.get_doc("Member", export[0]["member"])
   decrypted = enc.decrypt(member.iban)
   print(f"Decrypted: {decrypted}")
   assert decrypted == export[0]["decrypted_iban"]
   print("Rotation verified!")
   ```

5. **Secure cleanup**:
   ```bash
   # Securely delete export file
   shred -u /tmp/iban_export.json
   ```

**Post-Rotation Steps**:

1. Document the rotation in incident log with date
2. Update key escrow (if applicable)
3. Restart all workers to clear cached encryption instance

### Key Recovery

If the encryption key is lost:

**Severity**: CRITICAL - Data loss

1. **DO NOT** generate a new key immediately
2. Check for key backups:
   - Previous site_config.json versions
   - Configuration management system
   - Key escrow locations
3. If key is truly lost:
   - Encrypted data is NOT recoverable
   - Contact all affected members for IBAN re-entry
   - Generate new key and reconfigure
   - Document incident

### Testing Key Configuration

```python
from verenigingen.utils.field_encryption import get_encryption

try:
    enc = get_encryption()
    # Test round-trip
    test_value = "NL91ABNA0417164300"
    encrypted = enc.encrypt(test_value)
    decrypted = enc.decrypt(encrypted)
    assert decrypted == test_value
    print("Encryption key configured correctly!")
except Exception as e:
    print(f"Encryption configuration error: {e}")
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

## Phantom Hash Remediation

### What Are Phantom Hashes?

A "phantom hash" occurs when:
1. SEPA XML generation reserves a file hash to prevent duplicates
2. File attachment fails after reservation (disk error, permission issue, etc.)
3. The hash remains "reserved" but no file is attached

This is a safety feature - it prevents duplicate uploads even when attachment fails. However, phantom entries require manual investigation.

### Identifying Phantom Hashes

```python
# In bench console
from verenigingen.api.sepa_phantom_hash_admin import list_phantom_hashes, get_phantom_hash_stats

# Get statistics
stats = get_phantom_hash_stats()
print(f"Pending investigation: {stats['pending_investigation']}")
print(f"Older than 7 days: {stats['age_distribution']['older_than_7_days']}")

# List phantom entries
phantoms = list_phantom_hashes()
for entry in phantoms['entries']:
    print(f"Batch: {entry['batch_name']}, Created: {entry['creation']}")
```

### Investigation Workflow

1. **List phantom entries**:
   ```python
   phantoms = list_phantom_hashes(limit=10)
   ```

2. **Get details for each entry**:
   ```python
   from verenigingen.api.sepa_phantom_hash_admin import get_phantom_hash_details
   details = get_phantom_hash_details("LOG-ENTRY-NAME")
   print(details['recommendations'])
   ```

3. **Check the related batch**:
   - Does the batch exist? If not, the entry can be abandoned.
   - Does the batch have a SEPA file? If yes, use retry to resolve.
   - What is the batch status? Should it be regenerated?

### Resolution Options

#### Option 1: Retry Attachment (Recommended)

If the batch exists and needs a file:

```python
from verenigingen.api.sepa_phantom_hash_admin import retry_phantom_attachment

result = retry_phantom_attachment("LOG-ENTRY-NAME")
if result['success']:
    print(f"File attached: {result['file_url']}")
else:
    print(f"Failed: {result['error']}")
```

#### Option 2: Mark as Abandoned

If the batch was cancelled or recreated differently:

```python
from verenigingen.api.sepa_phantom_hash_admin import mark_phantom_hash_abandoned

result = mark_phantom_hash_abandoned(
    "LOG-ENTRY-NAME",
    reason="Batch BATCH-001 was cancelled and recreated as BATCH-002. "
           "Verified no duplicate upload risk - bank confirmed only BATCH-002 received."
)
```

**Important**: Abandoning deletes the log entry and frees the hash for re-upload.

### Monitoring Phantom Hashes

Add to daily checklist:

```python
stats = get_phantom_hash_stats()
if stats['pending_investigation'] > 0:
    print(f"WARNING: {stats['pending_investigation']} phantom entries need attention")
if stats['age_distribution']['older_than_7_days'] > 0:
    print(f"URGENT: {stats['age_distribution']['older_than_7_days']} entries older than 7 days")
```

### When to Escalate

| Condition | Action |
|-----------|--------|
| Phantom entry < 24 hours | Investigate and resolve |
| Phantom entry 1-7 days | Escalate to L2 Technical |
| Phantom entry > 7 days | Escalate to L3 Development |
| Multiple phantom entries same day | Check for systemic issue (disk space, permissions) |

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
| 1.1 | 2026-02-02 | System | Added Encryption Key Management and Phantom Hash Remediation sections |
| 1.0 | 2026-02-01 | System | Initial creation |

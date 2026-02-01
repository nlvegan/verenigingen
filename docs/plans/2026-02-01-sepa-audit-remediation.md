# SEPA Direct Debit Audit Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Address gaps identified in the SEPA DD audit - prevent duplicate batch uploads, add batch state tracking, automate pain.002 ingestion, and strengthen security.

**Architecture:** Extend existing SEPA infrastructure (sepa_duplicate_prevention.py, sepa_batch_processor.py) with pre-upload hash checking, a new SEPA Batch Upload Log DocType for bank portal state tracking, automated pain.002 file processing, and IBAN masking in UI.

**Tech Stack:** Python 3.11, Frappe 15, MariaDB, Redis, defusedxml, hashlib SHA256

---

## Reusable Utilities Identified

| Utility | Location | Reuse For |
|---------|----------|-----------|
| `_compute_file_hash()` | `document_portal_service.py` | SHA256 file hashing |
| `OperationResult` | `utils/operation_result.py` | Type-safe results |
| `StatelessService` | `services/infrastructure/base_service.py` | Service base class |
| `SEPANotificationManager` | `sepa_notification_manager.py` | Alerts/notifications |
| `advisory_lock_with_backend()` | `db_advisory_lock.py` | DB-level locking |
| `check_sepa_compliance_alert()` | `alert_manager.py` | Threshold alerts |
| Approval workflow pattern | `termination_approval_service.py` | Two-person batch approval |
| Audit trail pattern | `termination_audit_service.py` | Audit logging |

---

## P0 — Immediate (Critical Safety)

### Task 1: Pre-Upload File Hash Duplicate Detection

**Files:**
- Create: `verenigingen/services/payment/sepa_upload_guard.py`
- Modify: `verenigingen/api/sepa_duplicate_prevention.py:1-50`
- Test: `verenigingen/tests/services/payment/test_sepa_upload_guard.py`

**Step 1: Write the failing test**

```python
# tests/services/payment/test_sepa_upload_guard.py
import hashlib
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.services.payment.sepa_upload_guard import SEPAUploadGuard


class TestSEPAUploadGuard(IntegrationTestCase):
    def setUp(self):
        self.guard = SEPAUploadGuard()
        self.sample_xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08">
    <CstmrDrctDbtInitn>
        <GrpHdr><MsgId>TEST-001</MsgId></GrpHdr>
    </CstmrDrctDbtInitn>
</Document>"""

    def tearDown(self):
        frappe.db.delete("SEPA Batch Upload Log", {"file_hash": ("like", "test_%")})
        frappe.db.commit()

    def test_first_upload_allowed(self):
        """First upload of a file should be allowed."""
        result = self.guard.check_upload_allowed(self.sample_xml, "BATCH-001")
        self.assertTrue(result.success)
        self.assertIsNone(result.duplicate_batch)

    def test_duplicate_upload_blocked(self):
        """Second upload of identical file should be blocked."""
        # First upload
        self.guard.register_upload(self.sample_xml, "BATCH-001")

        # Second upload attempt
        result = self.guard.check_upload_allowed(self.sample_xml, "BATCH-002")
        self.assertFalse(result.success)
        self.assertEqual(result.duplicate_batch, "BATCH-001")

    def test_different_files_allowed(self):
        """Different files should both be allowed."""
        self.guard.register_upload(self.sample_xml, "BATCH-001")

        different_xml = self.sample_xml.replace(b"TEST-001", b"TEST-002")
        result = self.guard.check_upload_allowed(different_xml, "BATCH-002")
        self.assertTrue(result.success)
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_upload_guard`
Expected: FAIL with "No module named 'verenigingen.services.payment.sepa_upload_guard'"

**Step 3: Write minimal implementation**

```python
# verenigingen/services/payment/sepa_upload_guard.py
"""
Pre-upload hash checking to prevent duplicate SEPA batch uploads.

This guards against the scenario where an operator uploads the same pain.008 file
to the bank portal multiple times, causing duplicate debits.
"""
import hashlib
from dataclasses import dataclass
from typing import Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult


@dataclass
class UploadCheckResult:
    """Result of checking if a file upload is allowed."""
    success: bool
    file_hash: str
    duplicate_batch: Optional[str] = None
    duplicate_upload_time: Optional[str] = None
    message: str = ""


class SEPAUploadGuard(StatelessService):
    """
    Guards against duplicate SEPA batch uploads by tracking file hashes.

    Uses SHA256 hashing of file content to detect if the same pain.008 XML
    has been uploaded before. This is a critical safety control to prevent
    the same batch being submitted multiple times to the bank.
    """

    def _compute_file_hash(self, content: bytes) -> str:
        """Compute SHA256 hash of file content."""
        return hashlib.sha256(content).hexdigest()

    def check_upload_allowed(
        self, file_content: bytes, batch_name: str
    ) -> UploadCheckResult:
        """
        Check if uploading this file content is allowed.

        Args:
            file_content: Raw bytes of the pain.008 XML file
            batch_name: Name of the batch being uploaded

        Returns:
            UploadCheckResult indicating if upload is allowed
        """
        file_hash = self._compute_file_hash(file_content)

        # Check for existing upload with same hash
        existing = frappe.db.get_value(
            "SEPA Batch Upload Log",
            {"file_hash": file_hash},
            ["batch_name", "upload_time"],
            as_dict=True
        )

        if existing:
            return UploadCheckResult(
                success=False,
                file_hash=file_hash,
                duplicate_batch=existing.batch_name,
                duplicate_upload_time=str(existing.upload_time),
                message=f"This file was already uploaded for batch {existing.batch_name} "
                        f"at {existing.upload_time}. Duplicate upload blocked."
            )

        return UploadCheckResult(
            success=True,
            file_hash=file_hash,
            message="Upload allowed - no duplicate detected"
        )

    def register_upload(
        self,
        file_content: bytes,
        batch_name: str,
        uploaded_by: Optional[str] = None
    ) -> OperationResult[str]:
        """
        Register a file upload in the log.

        Args:
            file_content: Raw bytes of the pain.008 XML file
            batch_name: Name of the batch
            uploaded_by: User who performed the upload

        Returns:
            OperationResult with the log entry name
        """
        file_hash = self._compute_file_hash(file_content)

        try:
            log = frappe.get_doc({
                "doctype": "SEPA Batch Upload Log",
                "batch_name": batch_name,
                "file_hash": file_hash,
                "file_size": len(file_content),
                "upload_time": now_datetime(),
                "uploaded_by": uploaded_by or frappe.session.user
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()

            return OperationResult.ok(log.name)
        except Exception as e:
            return OperationResult.fail(f"Failed to register upload: {e}")

    def check_and_register(
        self,
        file_content: bytes,
        batch_name: str,
        uploaded_by: Optional[str] = None
    ) -> UploadCheckResult:
        """
        Atomic check-and-register operation.

        First checks if the file has been uploaded before. If not, registers
        the upload. This should be called just before uploading to the bank portal.

        Args:
            file_content: Raw bytes of the pain.008 XML file
            batch_name: Name of the batch
            uploaded_by: User who performed the upload

        Returns:
            UploadCheckResult indicating if upload was allowed and registered
        """
        check_result = self.check_upload_allowed(file_content, batch_name)

        if not check_result.success:
            return check_result

        # Register the upload
        register_result = self.register_upload(file_content, batch_name, uploaded_by)

        if not register_result.success:
            return UploadCheckResult(
                success=False,
                file_hash=check_result.file_hash,
                message=f"Upload check passed but registration failed: {register_result.error}"
            )

        return check_result
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_upload_guard`
Expected: FAIL - DocType "SEPA Batch Upload Log" does not exist (we need to create it in Task 2)

**Step 5: Commit progress**

```bash
git add verenigingen/services/payment/sepa_upload_guard.py verenigingen/tests/services/payment/test_sepa_upload_guard.py
git commit -m "feat(sepa): add pre-upload hash guard service (pending DocType)"
```

---

### Task 2: Create SEPA Batch Upload Log DocType

**Files:**
- Create: `verenigingen/verenigingen_payments/doctype/sepa_batch_upload_log/sepa_batch_upload_log.json`
- Create: `verenigingen/verenigingen_payments/doctype/sepa_batch_upload_log/sepa_batch_upload_log.py`
- Create: `verenigingen/verenigingen_payments/doctype/sepa_batch_upload_log/__init__.py`

**Step 1: Create the DocType JSON**

```json
{
    "actions": [],
    "autoname": "format:SEPA-UPL-{####}",
    "creation": "2026-02-01 10:00:00.000000",
    "doctype": "DocType",
    "engine": "InnoDB",
    "field_order": [
        "batch_section",
        "batch_name",
        "batch_status",
        "column_break_1",
        "upload_time",
        "uploaded_by",
        "file_section",
        "file_hash",
        "file_size",
        "column_break_2",
        "file_name",
        "bank_section",
        "bank_reference",
        "bank_acknowledgement_time",
        "column_break_3",
        "bank_status",
        "bank_error_message"
    ],
    "fields": [
        {
            "fieldname": "batch_section",
            "fieldtype": "Section Break",
            "label": "Batch Information"
        },
        {
            "fieldname": "batch_name",
            "fieldtype": "Link",
            "in_list_view": 1,
            "in_standard_filter": 1,
            "label": "Batch",
            "options": "Direct Debit Batch",
            "reqd": 1
        },
        {
            "default": "Pending Upload",
            "fieldname": "batch_status",
            "fieldtype": "Select",
            "in_list_view": 1,
            "in_standard_filter": 1,
            "label": "Status",
            "options": "Pending Upload\nUploaded\nAcknowledged\nRejected\nProcessed",
            "reqd": 1
        },
        {
            "fieldname": "column_break_1",
            "fieldtype": "Column Break"
        },
        {
            "fieldname": "upload_time",
            "fieldtype": "Datetime",
            "in_list_view": 1,
            "label": "Upload Time"
        },
        {
            "fieldname": "uploaded_by",
            "fieldtype": "Link",
            "label": "Uploaded By",
            "options": "User"
        },
        {
            "fieldname": "file_section",
            "fieldtype": "Section Break",
            "label": "File Details"
        },
        {
            "fieldname": "file_hash",
            "fieldtype": "Data",
            "label": "File Hash (SHA256)",
            "read_only": 1,
            "unique": 1
        },
        {
            "fieldname": "file_size",
            "fieldtype": "Int",
            "label": "File Size (bytes)"
        },
        {
            "fieldname": "column_break_2",
            "fieldtype": "Column Break"
        },
        {
            "fieldname": "file_name",
            "fieldtype": "Data",
            "label": "File Name"
        },
        {
            "fieldname": "bank_section",
            "fieldtype": "Section Break",
            "label": "Bank Response"
        },
        {
            "fieldname": "bank_reference",
            "fieldtype": "Data",
            "label": "Bank Reference"
        },
        {
            "fieldname": "bank_acknowledgement_time",
            "fieldtype": "Datetime",
            "label": "Bank Acknowledgement Time"
        },
        {
            "fieldname": "column_break_3",
            "fieldtype": "Column Break"
        },
        {
            "fieldname": "bank_status",
            "fieldtype": "Select",
            "label": "Bank Status",
            "options": "\nAccepted\nPartially Accepted\nRejected"
        },
        {
            "fieldname": "bank_error_message",
            "fieldtype": "Small Text",
            "label": "Bank Error Message"
        }
    ],
    "index_web_pages_for_search": 0,
    "links": [],
    "modified": "2026-02-01 10:00:00.000000",
    "modified_by": "Administrator",
    "module": "Verenigingen Payments",
    "name": "SEPA Batch Upload Log",
    "naming_rule": "Expression",
    "owner": "Administrator",
    "permissions": [
        {
            "create": 1,
            "delete": 0,
            "email": 0,
            "export": 1,
            "print": 1,
            "read": 1,
            "report": 1,
            "role": "System Manager",
            "share": 0,
            "write": 1
        },
        {
            "create": 1,
            "delete": 0,
            "email": 0,
            "export": 1,
            "print": 1,
            "read": 1,
            "report": 1,
            "role": "Accounts Manager",
            "share": 0,
            "write": 1
        }
    ],
    "sort_field": "upload_time",
    "sort_order": "DESC",
    "states": [],
    "track_changes": 1
}
```

**Step 2: Create the controller**

```python
# verenigingen/verenigingen_payments/doctype/sepa_batch_upload_log/sepa_batch_upload_log.py
"""SEPA Batch Upload Log controller."""
import frappe
from frappe.model.document import Document


class SEPABatchUploadLog(Document):
    def validate(self):
        self.validate_unique_hash()

    def validate_unique_hash(self):
        """Ensure file hash is unique to prevent duplicate uploads."""
        if not self.file_hash:
            return

        existing = frappe.db.get_value(
            "SEPA Batch Upload Log",
            {
                "file_hash": self.file_hash,
                "name": ("!=", self.name)
            },
            "name"
        )

        if existing:
            frappe.throw(
                f"A file with this hash was already uploaded (Log: {existing}). "
                "This appears to be a duplicate upload attempt.",
                frappe.DuplicateEntryError
            )
```

**Step 3: Create __init__.py**

```python
# verenigingen/verenigingen_payments/doctype/sepa_batch_upload_log/__init__.py
```

**Step 4: Run migration**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: DocType created successfully

**Step 5: Run the tests again**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_upload_guard`
Expected: PASS

**Step 6: Commit**

```bash
git add verenigingen/verenigingen_payments/doctype/sepa_batch_upload_log/
git commit -m "feat(sepa): add SEPA Batch Upload Log DocType for duplicate prevention"
```

---

### Task 3: Integrate Upload Guard into Batch Export Flow

**Files:**
- Modify: `verenigingen/verenigingen_payments/doctype/direct_debit_batch/direct_debit_batch.py:200-250`
- Test: `verenigingen/tests/services/payment/test_sepa_upload_guard.py` (add integration test)

**Step 1: Write the failing integration test**

```python
# Add to test_sepa_upload_guard.py
def test_batch_export_registers_upload(self):
    """Exporting a batch should register the upload hash."""
    # Create a minimal batch
    batch = frappe.get_doc({
        "doctype": "Direct Debit Batch",
        "batch_date": frappe.utils.today(),
        "requested_collection_date": frappe.utils.add_days(frappe.utils.today(), 5),
        "status": "Draft"
    })
    batch.insert()

    # Export the batch (mock the XML generation)
    from vereiningen.services.payment.sepa_upload_guard import SEPAUploadGuard
    guard = SEPAUploadGuard()

    xml_content = f"""<?xml version="1.0"?>
    <Document><CstmrDrctDbtInitn>
        <GrpHdr><MsgId>{batch.name}</MsgId></GrpHdr>
    </CstmrDrctDbtInitn></Document>""".encode()

    result = guard.check_and_register(xml_content, batch.name)
    self.assertTrue(result.success)

    # Verify log was created
    log = frappe.get_last_doc("SEPA Batch Upload Log", filters={"batch_name": batch.name})
    self.assertIsNotNone(log)
    self.assertEqual(log.batch_status, "Pending Upload")
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_upload_guard::TestSEPAUploadGuard::test_batch_export_registers_upload`
Expected: Test may pass or fail depending on existing batch flow

**Step 3: Add export hook in batch controller**

Read the current direct_debit_batch.py first, then add the integration point.

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_upload_guard`
Expected: PASS

**Step 5: Commit**

```bash
git add .
git commit -m "feat(sepa): integrate upload guard into batch export flow"
```

---

### Task 4: Redis Startup Verification

**Files:**
- Modify: `verenigingen/api/sepa_duplicate_prevention.py:1500-1515`
- Create: `verenigingen/startup_checks.py`
- Modify: `verenigingen/hooks.py` (add on_startup hook)
- Test: `verenigingen/tests/api/test_sepa_startup_check.py`

**Step 1: Write the failing test**

```python
# tests/api/test_sepa_startup_check.py
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.startup_checks import verify_sepa_redis_on_startup


class TestSEPAStartupCheck(IntegrationTestCase):
    def test_startup_check_logs_warning_when_redis_disabled(self):
        """When Redis locks disabled, startup should log a warning."""
        # Temporarily disable Redis locks
        original = frappe.conf.get("use_redis_locks_for_sepa")
        frappe.conf.use_redis_locks_for_sepa = False

        try:
            result = verify_sepa_redis_on_startup()
            # Should succeed but with warning
            self.assertTrue(result["checked"])
            self.assertFalse(result["redis_enabled"])
        finally:
            if original is not None:
                frappe.conf.use_redis_locks_for_sepa = original

    def test_startup_check_succeeds_with_redis(self):
        """With Redis locks enabled, startup check should pass."""
        original = frappe.conf.get("use_redis_locks_for_sepa")
        frappe.conf.use_redis_locks_for_sepa = True

        try:
            result = verify_sepa_redis_on_startup()
            self.assertTrue(result["checked"])
            self.assertTrue(result["redis_enabled"])
        finally:
            if original is not None:
                frappe.conf.use_redis_locks_for_sepa = original
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.api.test_sepa_startup_check`
Expected: FAIL - module not found

**Step 3: Write implementation**

```python
# verenigingen/startup_checks.py
"""
Startup verification checks for critical Verenigingen services.

These checks run on application startup to verify that critical
infrastructure is properly configured.
"""
import frappe
from frappe.utils import cint


def verify_sepa_redis_on_startup() -> dict:
    """
    Verify SEPA Redis configuration on startup.

    Checks if Redis locks are enabled for SEPA processing and logs
    appropriate warnings if not configured for multi-worker safety.

    Returns:
        dict with check results
    """
    result = {
        "checked": True,
        "redis_enabled": False,
        "multi_worker": False,
        "warning": None
    }

    # Check Redis locks configuration
    redis_enabled = frappe.conf.get("use_redis_locks_for_sepa", False)
    result["redis_enabled"] = redis_enabled

    # Check if multi-worker
    gunicorn_workers = cint(frappe.conf.get("gunicorn_workers", 1))
    result["multi_worker"] = gunicorn_workers > 1

    if result["multi_worker"] and not redis_enabled:
        warning = (
            "SEPA SAFETY WARNING: Multi-worker environment detected "
            f"({gunicorn_workers} workers) but Redis locks are not enabled. "
            "Set 'use_redis_locks_for_sepa': true in site_config.json to "
            "prevent duplicate payment processing."
        )
        result["warning"] = warning
        frappe.logger("sepa").warning(warning)

    if redis_enabled:
        # Verify Redis is actually reachable
        try:
            from verenigingen.api.sepa_duplicate_prevention import check_redis_health
            health = check_redis_health()
            if not health.get("healthy"):
                result["warning"] = "Redis locks enabled but Redis health check failed"
                frappe.logger("sepa").error(result["warning"])
        except Exception as e:
            result["warning"] = f"Redis health check error: {e}"
            frappe.logger("sepa").error(result["warning"])

    return result


def run_all_startup_checks():
    """Run all startup verification checks."""
    results = {}

    # SEPA Redis check
    results["sepa_redis"] = verify_sepa_redis_on_startup()

    return results
```

**Step 4: Add to hooks.py**

```python
# Add to hooks.py
on_startup = [
    "verenigingen.startup_checks.run_all_startup_checks"
]
```

**Step 5: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.api.test_sepa_startup_check`
Expected: PASS

**Step 6: Commit**

```bash
git add verenigingen/startup_checks.py verenigingen/hooks.py verenigingen/tests/api/test_sepa_startup_check.py
git commit -m "feat(sepa): add Redis verification on startup with multi-worker safety check"
```

---

## P1 — High Priority

### Task 5: Automate pain.002 File Ingestion

**Files:**
- Create: `verenigingen/services/payment/pain002_ingestion_service.py`
- Modify: `verenigingen/hooks.py` (add scheduled task)
- Test: `verenigingen/tests/services/payment/test_pain002_ingestion.py`

**Step 1: Write the failing test**

```python
# tests/services/payment/test_pain002_ingestion.py
import os
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.services.payment.pain002_ingestion_service import Pain002IngestionService


class TestPain002Ingestion(IntegrationTestCase):
    def setUp(self):
        self.service = Pain002IngestionService()
        self.test_dir = "/tmp/sepa_pain002_test"
        os.makedirs(self.test_dir, exist_ok=True)

        # Sample pain.002 content
        self.sample_pain002 = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
    <CstmrPmtStsRpt>
        <GrpHdr>
            <MsgId>RESP-001</MsgId>
            <CreDtTm>2026-02-01T10:00:00</CreDtTm>
        </GrpHdr>
        <OrgnlGrpInfAndSts>
            <OrgnlMsgId>BATCH-001</OrgnlMsgId>
            <OrgnlMsgNmId>pain.008.001.08</OrgnlMsgNmId>
            <GrpSts>ACCP</GrpSts>
        </OrgnlGrpInfAndSts>
    </CstmrPmtStsRpt>
</Document>"""

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_scan_directory_finds_pain002_files(self):
        """Scanner should find .xml files in the configured directory."""
        # Write test file
        test_file = os.path.join(self.test_dir, "pain002_test.xml")
        with open(test_file, "w") as f:
            f.write(self.sample_pain002)

        files = self.service.scan_directory(self.test_dir)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0], test_file)

    def test_process_file_parses_status(self):
        """Processing a pain.002 file should extract the batch status."""
        test_file = os.path.join(self.test_dir, "pain002_test.xml")
        with open(test_file, "w") as f:
            f.write(self.sample_pain002)

        result = self.service.process_file(test_file)
        self.assertTrue(result.success)
        self.assertEqual(result.data["original_msg_id"], "BATCH-001")
        self.assertEqual(result.data["group_status"], "ACCP")

    def test_processed_file_moved_to_archive(self):
        """After processing, file should be moved to archive directory."""
        test_file = os.path.join(self.test_dir, "pain002_test.xml")
        with open(test_file, "w") as f:
            f.write(self.sample_pain002)

        archive_dir = os.path.join(self.test_dir, "archive")
        result = self.service.process_and_archive(test_file, archive_dir)

        self.assertTrue(result.success)
        self.assertFalse(os.path.exists(test_file))
        self.assertTrue(os.path.exists(os.path.join(archive_dir, "pain002_test.xml")))
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_pain002_ingestion`
Expected: FAIL - module not found

**Step 3: Write implementation**

```python
# verenigingen/services/payment/pain002_ingestion_service.py
"""
Automated pain.002 (Bank Status Report) ingestion service.

Scans a configured directory for pain.002 XML files, parses them,
updates batch status in SEPA Batch Upload Log, and archives processed files.
"""
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult
from verenigingen.verenigingen_payments.utils.sepa_return_parser import SEPAReturnParser


class Pain002IngestionService(StatelessService):
    """
    Ingests pain.002 bank status report files.

    Configuration (site_config.json):
        sepa_pain002_inbox: Path to scan for incoming files
        sepa_pain002_archive: Path to move processed files
        sepa_pain002_error: Path for files that failed processing
    """

    def __init__(self):
        super().__init__()
        self.inbox_path = frappe.conf.get(
            "sepa_pain002_inbox",
            "/var/sepa/inbox"
        )
        self.archive_path = frappe.conf.get(
            "sepa_pain002_archive",
            "/var/sepa/archive"
        )
        self.error_path = frappe.conf.get(
            "sepa_pain002_error",
            "/var/sepa/error"
        )
        self.parser = SEPAReturnParser()

    def scan_directory(self, directory: Optional[str] = None) -> List[str]:
        """
        Scan directory for pain.002 XML files.

        Args:
            directory: Path to scan (defaults to configured inbox)

        Returns:
            List of file paths found
        """
        scan_path = directory or self.inbox_path

        if not os.path.exists(scan_path):
            return []

        files = []
        for entry in os.scandir(scan_path):
            if entry.is_file() and entry.name.endswith(".xml"):
                files.append(entry.path)

        return sorted(files)

    def process_file(self, file_path: str) -> OperationResult[dict]:
        """
        Process a single pain.002 file.

        Args:
            file_path: Path to the pain.002 XML file

        Returns:
            OperationResult with parsed data
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Use existing parser
            parse_result = self.parser.parse(content)

            if not parse_result.get("success"):
                return OperationResult.fail(
                    f"Failed to parse pain.002: {parse_result.get('error')}"
                )

            data = {
                "original_msg_id": parse_result.get("original_msg_id"),
                "group_status": parse_result.get("group_status"),
                "transactions": parse_result.get("transactions", []),
                "file_path": file_path,
                "processed_at": now_datetime()
            }

            return OperationResult.ok(data)

        except Exception as e:
            return OperationResult.fail(f"Error processing {file_path}: {e}")

    def update_batch_status(self, data: dict) -> OperationResult[str]:
        """
        Update the SEPA Batch Upload Log with bank response.

        Args:
            data: Parsed pain.002 data

        Returns:
            OperationResult with log name updated
        """
        original_msg_id = data.get("original_msg_id")

        if not original_msg_id:
            return OperationResult.fail("No original message ID in pain.002")

        # Find the upload log for this batch
        log_name = frappe.db.get_value(
            "SEPA Batch Upload Log",
            {"batch_name": original_msg_id},
            "name"
        )

        if not log_name:
            # Try matching by batch name pattern
            log_name = frappe.db.get_value(
                "SEPA Batch Upload Log",
                {"batch_name": ("like", f"%{original_msg_id}%")},
                "name"
            )

        if not log_name:
            return OperationResult.fail(
                f"No upload log found for batch {original_msg_id}"
            )

        # Map pain.002 status to our status
        status_map = {
            "ACCP": "Acknowledged",
            "ACSP": "Acknowledged",
            "ACTC": "Acknowledged",
            "PART": "Partially Accepted",
            "RJCT": "Rejected"
        }

        group_status = data.get("group_status", "")
        bank_status = status_map.get(group_status, "")

        frappe.db.set_value(
            "SEPA Batch Upload Log",
            log_name,
            {
                "bank_status": bank_status,
                "batch_status": "Acknowledged" if bank_status == "Acknowledged" else "Rejected",
                "bank_acknowledgement_time": data.get("processed_at"),
                "bank_reference": data.get("original_msg_id")
            },
            update_modified=True
        )
        frappe.db.commit()

        return OperationResult.ok(log_name)

    def process_and_archive(
        self,
        file_path: str,
        archive_dir: Optional[str] = None
    ) -> OperationResult[dict]:
        """
        Process a pain.002 file and move it to archive.

        Args:
            file_path: Path to the pain.002 file
            archive_dir: Archive directory (defaults to configured path)

        Returns:
            OperationResult with processing details
        """
        archive = archive_dir or self.archive_path

        # Process the file
        result = self.process_file(file_path)

        if not result.success:
            # Move to error directory
            error_dir = self.error_path
            os.makedirs(error_dir, exist_ok=True)
            error_path = os.path.join(error_dir, os.path.basename(file_path))
            shutil.move(file_path, error_path)
            return result

        # Update batch status
        update_result = self.update_batch_status(result.data)

        # Archive the file (even if update failed - we don't want to reprocess)
        os.makedirs(archive, exist_ok=True)
        archive_path = os.path.join(archive, os.path.basename(file_path))
        shutil.move(file_path, archive_path)

        result.data["archived_to"] = archive_path
        result.data["batch_updated"] = update_result.success

        return result

    def run_ingestion_job(self) -> dict:
        """
        Scheduled job entry point: scan and process all pain.002 files.

        Returns:
            Summary of processing results
        """
        files = self.scan_directory()

        results = {
            "scanned": len(files),
            "processed": 0,
            "failed": 0,
            "details": []
        }

        for file_path in files:
            result = self.process_and_archive(file_path)

            if result.success:
                results["processed"] += 1
            else:
                results["failed"] += 1

            results["details"].append({
                "file": os.path.basename(file_path),
                "success": result.success,
                "error": result.error if not result.success else None
            })

        # Log summary
        frappe.logger("sepa").info(
            f"pain.002 ingestion: {results['processed']} processed, "
            f"{results['failed']} failed out of {results['scanned']} files"
        )

        return results


def run_pain002_ingestion():
    """Scheduled task entry point."""
    service = Pain002IngestionService()
    return service.run_ingestion_job()
```

**Step 4: Add scheduled task to hooks.py**

```python
# Add to scheduler_events in hooks.py
scheduler_events = {
    # ... existing events ...
    "hourly": [
        "verenigingen.services.payment.pain002_ingestion_service.run_pain002_ingestion"
    ]
}
```

**Step 5: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_pain002_ingestion`
Expected: PASS

**Step 6: Commit**

```bash
git add verenigingen/services/payment/pain002_ingestion_service.py \
        verenigingen/tests/services/payment/test_pain002_ingestion.py \
        verenigingen/hooks.py
git commit -m "feat(sepa): add automated pain.002 ingestion with hourly scheduler"
```

---

### Task 6: Batch State Machine

**Files:**
- Create: `verenigingen/services/payment/sepa_batch_state_machine.py`
- Modify: `verenigingen/verenigingen_payments/doctype/direct_debit_batch/direct_debit_batch.py`
- Test: `verenigingen/tests/services/payment/test_sepa_batch_state_machine.py`

**Step 1: Write the failing test**

```python
# tests/services/payment/test_sepa_batch_state_machine.py
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.services.payment.sepa_batch_state_machine import SEPABatchStateMachine


class TestSEPABatchStateMachine(IntegrationTestCase):
    def setUp(self):
        self.state_machine = SEPABatchStateMachine()

    def test_valid_transition_draft_to_pending_approval(self):
        """Draft -> Pending Approval is a valid transition."""
        result = self.state_machine.can_transition("Draft", "Pending Approval")
        self.assertTrue(result.allowed)

    def test_valid_transition_pending_to_approved(self):
        """Pending Approval -> Approved is valid."""
        result = self.state_machine.can_transition("Pending Approval", "Approved")
        self.assertTrue(result.allowed)

    def test_invalid_transition_draft_to_uploaded(self):
        """Draft -> Uploaded should be blocked (must go through approval)."""
        result = self.state_machine.can_transition("Draft", "Uploaded")
        self.assertFalse(result.allowed)

    def test_invalid_transition_uploaded_to_draft(self):
        """Uploaded -> Draft should be blocked (no going back)."""
        result = self.state_machine.can_transition("Uploaded", "Draft")
        self.assertFalse(result.allowed)

    def test_complete_workflow(self):
        """Test the complete batch workflow."""
        states = ["Draft", "Pending Approval", "Approved", "Exported", "Uploaded", "Acknowledged"]

        for i in range(len(states) - 1):
            from_state = states[i]
            to_state = states[i + 1]
            result = self.state_machine.can_transition(from_state, to_state)
            self.assertTrue(
                result.allowed,
                f"Transition {from_state} -> {to_state} should be allowed"
            )
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_batch_state_machine`
Expected: FAIL - module not found

**Step 3: Write implementation**

```python
# verenigingen/services/payment/sepa_batch_state_machine.py
"""
SEPA Batch State Machine.

Enforces valid state transitions for Direct Debit Batches to prevent
invalid workflows and ensure audit trail integrity.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService


@dataclass
class TransitionResult:
    """Result of checking a state transition."""
    allowed: bool
    reason: str = ""
    required_role: Optional[str] = None


class SEPABatchStateMachine(StatelessService):
    """
    Enforces valid state transitions for SEPA Direct Debit Batches.

    States:
        Draft: Initial state, batch being prepared
        Pending Approval: Awaiting second-person approval
        Approved: Approved, ready for export
        Exported: XML generated and downloaded
        Uploaded: Confirmed uploaded to bank portal
        Acknowledged: Bank has acknowledged receipt (pain.002 received)
        Processed: Collection completed
        Rejected: Bank rejected the batch
        Cancelled: Manually cancelled

    Key constraints:
        - Must go through approval before export
        - Cannot go backwards from Uploaded
        - Cancelled is terminal
    """

    # Valid transitions: from_state -> set of allowed to_states
    TRANSITIONS: Dict[str, Set[str]] = {
        "Draft": {"Pending Approval", "Cancelled"},
        "Pending Approval": {"Approved", "Draft", "Cancelled"},
        "Approved": {"Exported", "Draft", "Cancelled"},
        "Exported": {"Uploaded", "Cancelled"},
        "Uploaded": {"Acknowledged", "Rejected"},
        "Acknowledged": {"Processed", "Rejected"},
        "Processed": set(),  # Terminal state
        "Rejected": {"Draft"},  # Can retry from scratch
        "Cancelled": set()  # Terminal state
    }

    # Roles required for certain transitions
    TRANSITION_ROLES: Dict[tuple, str] = {
        ("Pending Approval", "Approved"): "Accounts Manager",
        ("Approved", "Exported"): "Accounts User",
        ("Exported", "Uploaded"): "Accounts Manager",
    }

    def can_transition(
        self,
        from_state: str,
        to_state: str,
        user: Optional[str] = None
    ) -> TransitionResult:
        """
        Check if a state transition is allowed.

        Args:
            from_state: Current state
            to_state: Desired new state
            user: User attempting the transition (for role check)

        Returns:
            TransitionResult indicating if transition is allowed
        """
        # Check if from_state is valid
        if from_state not in self.TRANSITIONS:
            return TransitionResult(
                allowed=False,
                reason=f"Unknown state: {from_state}"
            )

        # Check if transition is in allowed set
        allowed_states = self.TRANSITIONS[from_state]
        if to_state not in allowed_states:
            return TransitionResult(
                allowed=False,
                reason=f"Cannot transition from {from_state} to {to_state}. "
                       f"Allowed: {', '.join(allowed_states) if allowed_states else 'none (terminal)'}"
            )

        # Check role requirements
        transition_key = (from_state, to_state)
        required_role = self.TRANSITION_ROLES.get(transition_key)

        if required_role and user:
            user_roles = frappe.get_roles(user)
            if required_role not in user_roles and "System Manager" not in user_roles:
                return TransitionResult(
                    allowed=False,
                    reason=f"Role '{required_role}' required for this transition",
                    required_role=required_role
                )

        return TransitionResult(
            allowed=True,
            reason=f"Transition {from_state} -> {to_state} allowed",
            required_role=required_role
        )

    def get_allowed_transitions(self, from_state: str) -> List[str]:
        """Get list of allowed next states from current state."""
        return list(self.TRANSITIONS.get(from_state, set()))

    def validate_transition(
        self,
        batch_name: str,
        to_state: str,
        user: Optional[str] = None
    ) -> TransitionResult:
        """
        Validate a transition for a specific batch.

        Args:
            batch_name: Name of the Direct Debit Batch
            to_state: Desired new state
            user: User attempting the transition

        Returns:
            TransitionResult
        """
        from_state = frappe.db.get_value("Direct Debit Batch", batch_name, "status")

        if not from_state:
            return TransitionResult(
                allowed=False,
                reason=f"Batch {batch_name} not found"
            )

        return self.can_transition(from_state, to_state, user or frappe.session.user)

    def execute_transition(
        self,
        batch_name: str,
        to_state: str,
        user: Optional[str] = None,
        comment: Optional[str] = None
    ) -> TransitionResult:
        """
        Execute a state transition with validation and audit.

        Args:
            batch_name: Name of the batch
            to_state: Desired new state
            user: User making the transition
            comment: Optional comment for audit trail

        Returns:
            TransitionResult
        """
        result = self.validate_transition(batch_name, to_state, user)

        if not result.allowed:
            return result

        # Get current state for audit
        from_state = frappe.db.get_value("Direct Debit Batch", batch_name, "status")

        # Update state
        frappe.db.set_value(
            "Direct Debit Batch",
            batch_name,
            "status",
            to_state,
            update_modified=True
        )

        # Add comment for audit trail
        batch = frappe.get_doc("Direct Debit Batch", batch_name)
        batch.add_comment(
            "Info",
            f"Status changed: {from_state} → {to_state}" +
            (f"\nComment: {comment}" if comment else "")
        )

        frappe.db.commit()

        return result
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_batch_state_machine`
Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/services/payment/sepa_batch_state_machine.py \
        verenigingen/tests/services/payment/test_sepa_batch_state_machine.py
git commit -m "feat(sepa): add batch state machine for workflow enforcement"
```

---

### Task 7: Two-Person Approval Workflow

**Files:**
- Create: `verenigingen/services/payment/sepa_batch_approval_service.py`
- Test: `verenigingen/tests/services/payment/test_sepa_batch_approval.py`

**Step 1: Write the failing test**

```python
# tests/services/payment/test_sepa_batch_approval.py
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.services.payment.sepa_batch_approval_service import SEPABatchApprovalService


class TestSEPABatchApproval(IntegrationTestCase):
    def setUp(self):
        self.service = SEPABatchApprovalService()

        # Create test users
        self.creator = "test_creator@example.com"
        self.approver = "test_approver@example.com"

        for email in [self.creator, self.approver]:
            if not frappe.db.exists("User", email):
                user = frappe.get_doc({
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "roles": [{"role": "Accounts Manager"}]
                })
                user.insert(ignore_permissions=True)

    def test_creator_cannot_approve_own_batch(self):
        """The person who created/submitted batch cannot approve it."""
        result = self.service.can_approve(
            batch_name="TEST-BATCH",
            submitted_by=self.creator,
            approver=self.creator
        )
        self.assertFalse(result.allowed)
        self.assertIn("cannot approve", result.reason.lower())

    def test_different_person_can_approve(self):
        """A different person with proper role can approve."""
        result = self.service.can_approve(
            batch_name="TEST-BATCH",
            submitted_by=self.creator,
            approver=self.approver
        )
        self.assertTrue(result.allowed)

    def test_approval_records_approver(self):
        """Approval should record who approved and when."""
        # Create a test batch first
        batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_date": frappe.utils.today(),
            "requested_collection_date": frappe.utils.add_days(frappe.utils.today(), 5),
            "status": "Pending Approval",
            "owner": self.creator
        })
        batch.insert(ignore_permissions=True)

        result = self.service.approve_batch(batch.name, self.approver)

        self.assertTrue(result.success)

        # Verify approval was recorded
        batch.reload()
        self.assertEqual(batch.status, "Approved")
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_batch_approval`
Expected: FAIL - module not found

**Step 3: Write implementation**

```python
# verenigingen/services/payment/sepa_batch_approval_service.py
"""
SEPA Batch Two-Person Approval Service.

Implements the four-eyes principle for SEPA batch approval:
- Creator/submitter cannot approve their own batch
- Approver must have appropriate role
- All approvals are logged for audit
"""
from dataclasses import dataclass
from typing import Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.payment.sepa_batch_state_machine import SEPABatchStateMachine
from verenigingen.utils.operation_result import OperationResult


@dataclass
class ApprovalCheckResult:
    """Result of checking if a user can approve a batch."""
    allowed: bool
    reason: str = ""


class SEPABatchApprovalService(StatelessService):
    """
    Implements two-person (four-eyes) approval for SEPA batches.

    Key rules:
    1. The person who submitted the batch cannot approve it
    2. Approver must have Accounts Manager role
    3. Batch must be in "Pending Approval" state
    4. All approvals are recorded with timestamp and user
    """

    APPROVAL_ROLE = "Accounts Manager"

    def __init__(self):
        super().__init__()
        self.state_machine = SEPABatchStateMachine()

    def can_approve(
        self,
        batch_name: str,
        submitted_by: str,
        approver: str
    ) -> ApprovalCheckResult:
        """
        Check if a user can approve a batch.

        Args:
            batch_name: Name of the batch
            submitted_by: User who submitted/created the batch
            approver: User attempting to approve

        Returns:
            ApprovalCheckResult
        """
        # Rule 1: Cannot approve own batch
        if submitted_by == approver:
            return ApprovalCheckResult(
                allowed=False,
                reason="Four-eyes principle: You cannot approve a batch you submitted. "
                       "Another authorized user must approve this batch."
            )

        # Rule 2: Must have approval role
        user_roles = frappe.get_roles(approver)
        if self.APPROVAL_ROLE not in user_roles and "System Manager" not in user_roles:
            return ApprovalCheckResult(
                allowed=False,
                reason=f"Approver must have '{self.APPROVAL_ROLE}' role"
            )

        return ApprovalCheckResult(
            allowed=True,
            reason="Approval allowed"
        )

    def approve_batch(
        self,
        batch_name: str,
        approver: Optional[str] = None,
        comment: Optional[str] = None
    ) -> OperationResult[str]:
        """
        Approve a SEPA batch.

        Args:
            batch_name: Name of the batch to approve
            approver: User approving (defaults to current user)
            comment: Optional approval comment

        Returns:
            OperationResult with batch name on success
        """
        approver = approver or frappe.session.user

        # Get batch details
        batch = frappe.db.get_value(
            "Direct Debit Batch",
            batch_name,
            ["status", "owner"],
            as_dict=True
        )

        if not batch:
            return OperationResult.fail(f"Batch {batch_name} not found")

        # Check current state
        if batch.status != "Pending Approval":
            return OperationResult.fail(
                f"Batch must be in 'Pending Approval' state. Current: {batch.status}"
            )

        # Check approval eligibility
        check = self.can_approve(batch_name, batch.owner, approver)
        if not check.allowed:
            return OperationResult.fail(check.reason)

        # Execute state transition
        transition = self.state_machine.execute_transition(
            batch_name,
            "Approved",
            approver,
            comment=f"Approved by {approver}" + (f": {comment}" if comment else "")
        )

        if not transition.allowed:
            return OperationResult.fail(transition.reason)

        # Record approval details
        frappe.db.set_value(
            "Direct Debit Batch",
            batch_name,
            {
                "approved_by": approver,
                "approved_on": now_datetime()
            },
            update_modified=True
        )
        frappe.db.commit()

        return OperationResult.ok(batch_name)

    def reject_batch(
        self,
        batch_name: str,
        rejector: Optional[str] = None,
        reason: str = ""
    ) -> OperationResult[str]:
        """
        Reject a batch and return it to Draft state.

        Args:
            batch_name: Name of the batch
            rejector: User rejecting
            reason: Reason for rejection

        Returns:
            OperationResult
        """
        rejector = rejector or frappe.session.user

        batch_status = frappe.db.get_value("Direct Debit Batch", batch_name, "status")

        if batch_status != "Pending Approval":
            return OperationResult.fail(
                f"Can only reject batches in 'Pending Approval'. Current: {batch_status}"
            )

        transition = self.state_machine.execute_transition(
            batch_name,
            "Draft",
            rejector,
            comment=f"Rejected by {rejector}: {reason}"
        )

        if not transition.allowed:
            return OperationResult.fail(transition.reason)

        return OperationResult.ok(batch_name)
```

**Step 4: Add approved_by/approved_on fields to Direct Debit Batch**

Add these fields to the Direct Debit Batch DocType JSON:
- `approved_by` (Link to User)
- `approved_on` (Datetime)

**Step 5: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_sepa_batch_approval`
Expected: PASS

**Step 6: Commit**

```bash
git add verenigingen/services/payment/sepa_batch_approval_service.py \
        verenigingen/tests/services/payment/test_sepa_batch_approval.py
git commit -m "feat(sepa): add two-person approval workflow for batches"
```

---

### Task 8: IBAN Masking in UI

**Files:**
- Create: `verenigingen/public/js/iban_masking.js`
- Modify: `verenigingen/hooks.py` (add client script)
- Modify: `verenigingen/public/js/verenigingen.bundle.js`

**Step 1: Create IBAN masking utility**

```javascript
// verenigingen/public/js/iban_masking.js
/**
 * IBAN Masking Utility
 *
 * Masks IBANs in the UI for privacy/security while keeping
 * them visible to authorized users.
 */

frappe.provide("verenigingen.iban");

verenigingen.iban = {
    /**
     * Mask an IBAN, showing only first 4 and last 4 characters.
     * Example: NL91ABNA0417164300 -> NL91****4300
     */
    mask: function(iban) {
        if (!iban || iban.length < 8) {
            return iban;
        }
        const first = iban.substring(0, 4);
        const last = iban.substring(iban.length - 4);
        return first + "****" + last;
    },

    /**
     * Check if current user can see unmasked IBANs.
     * Returns true for Accounts Manager and System Manager.
     */
    canViewFull: function() {
        return frappe.user_roles.includes("Accounts Manager") ||
               frappe.user_roles.includes("System Manager");
    },

    /**
     * Apply masking to an IBAN field based on user role.
     */
    applyMasking: function(frm, fieldname) {
        if (!verenigingen.iban.canViewFull()) {
            const value = frm.doc[fieldname];
            if (value) {
                // Store original for form submission
                frm._original_iban = frm._original_iban || {};
                frm._original_iban[fieldname] = value;

                // Display masked version
                frm.set_value(fieldname, verenigingen.iban.mask(value));
                frm.set_df_property(fieldname, "read_only", 1);
            }
        }
    },

    /**
     * Restore original IBAN before save.
     */
    restoreOriginal: function(frm, fieldname) {
        if (frm._original_iban && frm._original_iban[fieldname]) {
            frm.doc[fieldname] = frm._original_iban[fieldname];
        }
    }
};

// Auto-apply to SEPA mandate and member forms
$(document).on("form-refresh", function(e, frm) {
    if (frm.doctype === "SEPA Mandate") {
        verenigingen.iban.applyMasking(frm, "iban");
    }
    if (frm.doctype === "Member") {
        verenigingen.iban.applyMasking(frm, "iban");
    }
});
```

**Step 2: Add to bundle and hooks**

```python
# In hooks.py, ensure this is included
app_include_js = "/assets/verenigingen/js/verenigingen.bundle.js"
```

**Step 3: Commit**

```bash
git add verenigingen/public/js/iban_masking.js
git commit -m "feat(sepa): add IBAN masking in UI for non-privileged users"
```

---

## P2 — Medium Priority

### Task 9: IBAN Encryption at Rest

**Files:**
- Create: `verenigingen/utils/field_encryption.py`
- Modify: `verenigingen/membership/doctype/sepa_mandate/sepa_mandate.py`
- Test: `verenigingen/tests/utils/test_field_encryption.py`

**Step 1: Write the failing test**

```python
# tests/utils/test_field_encryption.py
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.utils.field_encryption import FieldEncryption


class TestFieldEncryption(IntegrationTestCase):
    def setUp(self):
        self.encryption = FieldEncryption()
        self.test_iban = "NL91ABNA0417164300"

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting and decrypting should return original value."""
        encrypted = self.encryption.encrypt(self.test_iban)
        decrypted = self.encryption.decrypt(encrypted)
        self.assertEqual(decrypted, self.test_iban)

    def test_encrypted_value_different(self):
        """Encrypted value should not be the same as plaintext."""
        encrypted = self.encryption.encrypt(self.test_iban)
        self.assertNotEqual(encrypted, self.test_iban)
        self.assertTrue(encrypted.startswith("ENC:"))

    def test_is_encrypted_check(self):
        """Should correctly identify encrypted vs plaintext values."""
        encrypted = self.encryption.encrypt(self.test_iban)
        self.assertTrue(self.encryption.is_encrypted(encrypted))
        self.assertFalse(self.encryption.is_encrypted(self.test_iban))
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.utils.test_field_encryption`
Expected: FAIL - module not found

**Step 3: Write implementation**

```python
# verenigingen/utils/field_encryption.py
"""
Field-level encryption for sensitive data.

Uses Fernet symmetric encryption with keys stored in site_config.json.
Encrypted values are prefixed with "ENC:" for identification.
"""
import base64
import os
from typing import Optional

import frappe
from cryptography.fernet import Fernet


class FieldEncryption:
    """
    Encrypts and decrypts sensitive field values.

    Configuration (site_config.json):
        field_encryption_key: Base64-encoded 32-byte key

    If no key is configured, generates one on first use.
    """

    PREFIX = "ENC:"

    def __init__(self):
        self._fernet = None

    def _get_key(self) -> bytes:
        """Get or generate the encryption key."""
        key = frappe.conf.get("field_encryption_key")

        if not key:
            # Generate new key (should be done once during setup)
            key = base64.urlsafe_b64encode(os.urandom(32)).decode()
            frappe.logger("encryption").warning(
                "No field_encryption_key configured. Generated new key. "
                "Add 'field_encryption_key' to site_config.json for persistence."
            )

        return key.encode() if isinstance(key, str) else key

    def _get_fernet(self) -> Fernet:
        """Get Fernet instance (lazy initialization)."""
        if self._fernet is None:
            self._fernet = Fernet(self._get_key())
        return self._fernet

    def encrypt(self, value: str) -> str:
        """
        Encrypt a string value.

        Args:
            value: Plaintext string to encrypt

        Returns:
            Encrypted string with "ENC:" prefix
        """
        if not value:
            return value

        if self.is_encrypted(value):
            return value  # Already encrypted

        fernet = self._get_fernet()
        encrypted = fernet.encrypt(value.encode())
        return self.PREFIX + base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, value: str) -> str:
        """
        Decrypt an encrypted value.

        Args:
            value: Encrypted string (with "ENC:" prefix)

        Returns:
            Decrypted plaintext string
        """
        if not value:
            return value

        if not self.is_encrypted(value):
            return value  # Not encrypted

        # Remove prefix and decode
        encrypted_b64 = value[len(self.PREFIX):]
        encrypted = base64.urlsafe_b64decode(encrypted_b64.encode())

        fernet = self._get_fernet()
        return fernet.decrypt(encrypted).decode()

    def is_encrypted(self, value: str) -> bool:
        """Check if a value is encrypted."""
        return value.startswith(self.PREFIX) if value else False


# Singleton instance
_encryption = None


def get_encryption() -> FieldEncryption:
    """Get the singleton FieldEncryption instance."""
    global _encryption
    if _encryption is None:
        _encryption = FieldEncryption()
    return _encryption
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.utils.test_field_encryption`
Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/utils/field_encryption.py \
        verenigingen/tests/utils/test_field_encryption.py
git commit -m "feat(security): add field-level encryption utility"
```

---

### Task 10: Reconciliation Threshold Alerts

**Files:**
- Modify: `verenigingen/services/payment/alert_manager.py`
- Test: `verenigingen/tests/services/payment/test_reconciliation_alerts.py`

**Step 1: Write the failing test**

```python
# tests/services/payment/test_reconciliation_alerts.py
import frappe
from frappe.tests import IntegrationTestCase
from verenigingen.services.payment.alert_manager import AlertManager


class TestReconciliationAlerts(IntegrationTestCase):
    def setUp(self):
        self.alert_manager = AlertManager()

    def test_alert_triggered_at_threshold(self):
        """Alert should trigger when unreconciled transactions exceed threshold."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=50,
            threshold=25
        )
        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "warning")

    def test_no_alert_below_threshold(self):
        """No alert when unreconciled count is below threshold."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=10,
            threshold=25
        )
        self.assertFalse(result.alert_triggered)

    def test_critical_alert_at_high_threshold(self):
        """Critical alert when unreconciled exceeds critical threshold."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=100,
            threshold=25,
            critical_threshold=75
        )
        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "critical")
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_reconciliation_alerts`
Expected: FAIL - method not found

**Step 3: Add implementation to AlertManager**

```python
# Add to verenigingen/services/payment/alert_manager.py

@dataclass
class ReconciliationAlertResult:
    """Result of reconciliation status check."""
    alert_triggered: bool
    severity: str = "info"  # info, warning, critical
    message: str = ""
    unreconciled_count: int = 0


class AlertManager:
    # ... existing code ...

    def check_reconciliation_status(
        self,
        unreconciled_count: int,
        threshold: int = 25,
        critical_threshold: int = 75
    ) -> ReconciliationAlertResult:
        """
        Check if reconciliation backlog exceeds thresholds.

        Args:
            unreconciled_count: Number of unreconciled transactions
            threshold: Warning threshold
            critical_threshold: Critical alert threshold

        Returns:
            ReconciliationAlertResult
        """
        if unreconciled_count >= critical_threshold:
            return ReconciliationAlertResult(
                alert_triggered=True,
                severity="critical",
                message=f"CRITICAL: {unreconciled_count} unreconciled transactions "
                        f"(threshold: {critical_threshold})",
                unreconciled_count=unreconciled_count
            )

        if unreconciled_count >= threshold:
            return ReconciliationAlertResult(
                alert_triggered=True,
                severity="warning",
                message=f"WARNING: {unreconciled_count} unreconciled transactions "
                        f"(threshold: {threshold})",
                unreconciled_count=unreconciled_count
            )

        return ReconciliationAlertResult(
            alert_triggered=False,
            severity="info",
            message=f"OK: {unreconciled_count} unreconciled transactions",
            unreconciled_count=unreconciled_count
        )
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.payment.test_reconciliation_alerts`
Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/services/payment/alert_manager.py \
        verenigingen/tests/services/payment/test_reconciliation_alerts.py
git commit -m "feat(sepa): add reconciliation threshold alerts"
```

---

### Task 11: SEPA Health Check Endpoint

**Files:**
- Create: `verenigingen/api/sepa_health.py`
- Test: `verenigingen/tests/api/test_sepa_health.py`

**Step 1: Write the failing test**

```python
# tests/api/test_sepa_health.py
import frappe
from frappe.tests import IntegrationTestCase


class TestSEPAHealthEndpoint(IntegrationTestCase):
    def test_health_check_returns_status(self):
        """Health endpoint should return overall status."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("status", result)
        self.assertIn("checks", result)
        self.assertIn("redis", result["checks"])
        self.assertIn("pending_batches", result["checks"])

    def test_health_check_detects_redis_issues(self):
        """Should detect Redis connectivity issues."""
        from vereinigen.api.sepa_health import get_sepa_health

        # Mock Redis failure would go here
        result = get_sepa_health()

        self.assertIn("redis", result["checks"])
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.api.test_sepa_health`
Expected: FAIL - module not found

**Step 3: Write implementation**

```python
# verenigingen/api/sepa_health.py
"""
SEPA Health Check API.

Provides a health status endpoint for monitoring SEPA infrastructure.
"""
import frappe
from frappe.utils import now_datetime, add_days

from verenigingen.api.sepa_duplicate_prevention import check_redis_health


@frappe.whitelist()
def get_sepa_health() -> dict:
    """
    Get SEPA infrastructure health status.

    Returns:
        dict with status and individual check results
    """
    checks = {}
    overall_healthy = True

    # Check 1: Redis connectivity
    try:
        redis_health = check_redis_health()
        checks["redis"] = {
            "healthy": redis_health.get("healthy", False),
            "message": redis_health.get("message", ""),
            "locks_enabled": frappe.conf.get("use_redis_locks_for_sepa", False)
        }
        if not checks["redis"]["healthy"]:
            overall_healthy = False
    except Exception as e:
        checks["redis"] = {"healthy": False, "error": str(e)}
        overall_healthy = False

    # Check 2: Pending batches
    try:
        pending_count = frappe.db.count(
            "Direct Debit Batch",
            filters={"status": ["in", ["Pending Approval", "Approved", "Exported"]]}
        )
        checks["pending_batches"] = {
            "healthy": True,
            "count": pending_count,
            "warning": pending_count > 5
        }
    except Exception as e:
        checks["pending_batches"] = {"healthy": False, "error": str(e)}

    # Check 3: Unreconciled transactions
    try:
        unreconciled = frappe.db.count(
            "Direct Debit Transaction",
            filters={
                "status": "Pending",
                "creation": ["<", add_days(now_datetime(), -7)]
            }
        )
        checks["unreconciled"] = {
            "healthy": unreconciled < 50,
            "count": unreconciled,
            "threshold": 50
        }
        if not checks["unreconciled"]["healthy"]:
            overall_healthy = False
    except Exception as e:
        checks["unreconciled"] = {"healthy": False, "error": str(e)}

    # Check 4: Recent upload logs
    try:
        recent_uploads = frappe.db.count(
            "SEPA Batch Upload Log",
            filters={"upload_time": [">=", add_days(now_datetime(), -1)]}
        )
        checks["recent_uploads"] = {
            "healthy": True,
            "count_24h": recent_uploads
        }
    except Exception as e:
        checks["recent_uploads"] = {"healthy": False, "error": str(e)}

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": str(now_datetime()),
        "checks": checks
    }
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.api.test_sepa_health`
Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/api/sepa_health.py \
        verenigingen/tests/api/test_sepa_health.py
git commit -m "feat(sepa): add health check endpoint for monitoring"
```

---

## P3 — Nice to Have

### Task 12: Sandbox Testing Mode

**Files:**
- Create: `verenigingen/utils/sepa_sandbox.py`
- Modify: `verenigingen/verenigingen_payments/utils/sepa_xml_enhanced_generator.py`

This task creates a sandbox mode that generates test XMLs with clearly marked test data and prevents accidental submission to production bank portals.

**Implementation outline:**
- Add `sepa_sandbox_mode: true` config option
- When enabled, prefix all MsgIds with "TEST-"
- Add validation that blocks bank upload if sandbox mode
- Create test IBAN generator for sandbox testing

---

### Task 13: Operations Runbook Documentation

**Files:**
- Create: `docs/runbooks/SEPA_OPERATIONS.md`

This task creates operational documentation for common SEPA scenarios:
- Daily batch processing workflow
- Handling pain.002 rejections
- Reconciliation procedures
- Emergency procedures for duplicate detection
- Escalation paths

---

## Summary

| Priority | Task | Status | Est. Complexity |
|----------|------|--------|-----------------|
| P0 | Pre-upload hash guard | 🔲 | Medium |
| P0 | SEPA Batch Upload Log DocType | 🔲 | Low |
| P0 | Integrate guard into export | 🔲 | Low |
| P0 | Redis startup verification | 🔲 | Low |
| P1 | pain.002 auto-ingestion | 🔲 | Medium |
| P1 | Batch state machine | 🔲 | Medium |
| P1 | Two-person approval | 🔲 | Medium |
| P1 | IBAN UI masking | 🔲 | Low |
| P2 | IBAN encryption | 🔲 | Medium |
| P2 | Reconciliation alerts | 🔲 | Low |
| P2 | Health check endpoint | 🔲 | Low |
| P3 | Sandbox mode | 🔲 | Low |
| P3 | Operations runbook | 🔲 | Low |

Total: 13 tasks across 4 priority levels

---

## Execution Options

**Plan saved to:** `docs/plans/2026-02-01-sepa-audit-remediation.md`

**Two execution options:**

1. **Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?

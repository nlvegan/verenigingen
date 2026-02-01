"""
Payment Services Package

Provides payment-related business logic separated from Member DocType.

Services:
- validation_service: Payment validation orchestration (IBAN, bank details, amounts)
- sepa_upload_guard: SEPA batch upload duplicate detection
- pain002_ingestion_service: Automated pain.002 bank status report ingestion
- sepa_batch_state_machine: State machine for batch workflow enforcement
- sepa_batch_approval_service: Two-person approval workflow for batches
- operations_service: Payment operations (create entries, process payments) [TODO]
"""

from verenigingen.services.payment.pain002_ingestion_service import (
    Pain002IngestionService,
    get_pain002_ingestion_service,
    run_pain002_ingestion,
)
from verenigingen.services.payment.sepa_batch_approval_service import (
    ApprovalCheckResult,
    SEPABatchApprovalService,
    get_sepa_batch_approval_service,
)
from verenigingen.services.payment.sepa_batch_state_machine import (
    SEPABatchStateMachine,
    TransitionResult,
    get_sepa_batch_state_machine,
)
from verenigingen.services.payment.sepa_upload_guard import (
    SEPAUploadGuard,
    UploadCheckResult,
    get_sepa_upload_guard,
)
from verenigingen.services.payment.validation_service import (
    PaymentValidationService,
    ValidationResult,
    get_payment_validation_service,
)

__all__ = [
    "PaymentValidationService",
    "ValidationResult",
    "get_payment_validation_service",
    "SEPAUploadGuard",
    "UploadCheckResult",
    "get_sepa_upload_guard",
    "Pain002IngestionService",
    "get_pain002_ingestion_service",
    "run_pain002_ingestion",
    "SEPABatchStateMachine",
    "TransitionResult",
    "get_sepa_batch_state_machine",
    "SEPABatchApprovalService",
    "ApprovalCheckResult",
    "get_sepa_batch_approval_service",
]

# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Billing services for membership dues processing.

Services:
- BillingDateService: Date management for dues schedules
- BulkInvoiceGenerationService: Bulk invoice generation with parallel processing
- DuesScheduleLifecycleService: Schedule lifecycle (pause/resume/cancel)
- DuesSchedulePermissionService: Permission management for schedules
- DuesScheduleValidationService: Validation logic for schedules
- FeeChangeTrackingService: Fee change history tracking
- InvoiceErrorHandlerService: Error handling for invoice generation
- InvoiceGenerator: Individual invoice generation
- ProgressiveDuesService: Income-based progressive dues calculation
- TemplateConfigurationService: Template value loading and validation
- TemplateCreationService: Template and schedule creation
"""

from verenigingen.services.billing.billing_date_service import (
    BillingDateService,
    get_billing_date_service,
)
from verenigingen.services.billing.bulk_invoice_generation_service import (
    BulkGenerationResult,
    BulkInvoiceGenerationService,
    ChunkResult,
    EligibilityDetails,
    get_bulk_invoice_generation_service,
    process_invoice_chunk,
)
from verenigingen.services.billing.coverage_overlap_detector import (
    OverlapCheckResult,
    check_coverage_overlap,
    find_exact_coverage_invoice,
    find_overlapping_invoices,
    get_member_coverage_gaps,
)
from verenigingen.services.billing.dues_schedule_lifecycle_service import (
    DuesScheduleLifecycleService,
    get_dues_schedule_lifecycle_service,
)
from verenigingen.services.billing.dues_schedule_permission_service import (
    DuesSchedulePermissionService,
    PermissionResult,
    get_dues_schedule_permission_service,
    get_permission_query_conditions,
    has_permission,
)
from verenigingen.services.billing.dues_schedule_validation_service import (
    DuesScheduleValidationService,
    get_dues_schedule_validation_service,
)
from verenigingen.services.billing.duplicate_invoice_detector import (
    DuplicateInvoiceDetectionResult,
    DuplicateInvoiceDetector,
)
from verenigingen.services.billing.fee_change_tracking_service import (
    FeeChangeTrackingService,
    get_fee_change_tracking_service,
)
from verenigingen.services.billing.invoice_error_handler_service import (
    InvoiceErrorHandlerService,
    get_invoice_error_handler_service,
)
from verenigingen.services.billing.progressive_dues_service import (
    ProgressiveDuesResult,
    ProgressiveDuesService,
    get_progressive_dues_service,
)
from verenigingen.services.billing.template_configuration_service import (
    TemplateConfigurationService,
    get_template_configuration_service,
)
from verenigingen.services.billing.template_creation_service import (
    TemplateCreationService,
    get_template_creation_service,
)

__all__ = [
    # Billing date service
    "BillingDateService",
    "get_billing_date_service",
    # Bulk invoice generation
    "BulkGenerationResult",
    "BulkInvoiceGenerationService",
    "ChunkResult",
    "EligibilityDetails",
    "get_bulk_invoice_generation_service",
    "process_invoice_chunk",
    # Coverage overlap detection (standalone functions)
    "OverlapCheckResult",
    "check_coverage_overlap",
    "find_overlapping_invoices",
    "find_exact_coverage_invoice",
    "get_member_coverage_gaps",
    # Lifecycle management
    "DuesScheduleLifecycleService",
    "get_dues_schedule_lifecycle_service",
    # Permission management
    "DuesSchedulePermissionService",
    "PermissionResult",
    "get_dues_schedule_permission_service",
    "get_permission_query_conditions",
    "has_permission",
    # Duplicate invoice detection (schedule-based)
    "DuplicateInvoiceDetector",
    "DuplicateInvoiceDetectionResult",
    # Fee change tracking
    "FeeChangeTrackingService",
    "get_fee_change_tracking_service",
    # Invoice error handling
    "InvoiceErrorHandlerService",
    "get_invoice_error_handler_service",
    # Progressive dues
    "ProgressiveDuesResult",
    "ProgressiveDuesService",
    "get_progressive_dues_service",
    # Validation
    "DuesScheduleValidationService",
    "get_dues_schedule_validation_service",
    # Template services
    "TemplateCreationService",
    "get_template_creation_service",
    "TemplateConfigurationService",
    "get_template_configuration_service",
]

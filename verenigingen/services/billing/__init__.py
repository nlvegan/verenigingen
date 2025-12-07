# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Billing services for membership dues processing.
"""

from verenigingen.services.billing.coverage_overlap_detector import (
    OverlapCheckResult,
    check_coverage_overlap,
    find_exact_coverage_invoice,
    find_overlapping_invoices,
    get_member_coverage_gaps,
)
from verenigingen.services.billing.dues_schedule_validation_service import (
    DuesScheduleValidationService,
    get_dues_schedule_validation_service,
)
from verenigingen.services.billing.duplicate_invoice_detector import (
    DuplicateInvoiceDetectionResult,
    DuplicateInvoiceDetector,
)
from verenigingen.services.billing.invoice_error_handler_service import (
    InvoiceErrorHandlerService,
    get_invoice_error_handler_service,
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
    # Coverage overlap detection (standalone functions)
    "OverlapCheckResult",
    "check_coverage_overlap",
    "find_overlapping_invoices",
    "find_exact_coverage_invoice",
    "get_member_coverage_gaps",
    # Duplicate invoice detection (schedule-based)
    "DuplicateInvoiceDetector",
    "DuplicateInvoiceDetectionResult",
    # Other services
    "DuesScheduleValidationService",
    "get_dues_schedule_validation_service",
    "InvoiceErrorHandlerService",
    "get_invoice_error_handler_service",
    "TemplateCreationService",
    "get_template_creation_service",
    "TemplateConfigurationService",
    "get_template_configuration_service",
]

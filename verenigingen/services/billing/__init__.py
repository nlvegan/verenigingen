# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Billing services for membership dues processing.

Import from the submodule that defines what you need, not from this package:

    from verenigingen.services.billing.billing_date_service import BillingDateService

This __init__ deliberately imports nothing. It used to re-export the whole
package, which made `import verenigingen.services.billing.<anything>` run
fourteen submodule imports first. Under a threaded web worker that opened a
wide window in which one thread held the package lock while a second thread
held a submodule lock and waited for the package - a cycle CPython reports as
`_frozen_importlib._DeadlockError` rather than hanging.

Modules:
- billing_date_service: Date management for dues schedules
- bulk_invoice_generation_service: Bulk invoice generation with parallel processing
- coverage_overlap_detector: Coverage overlap detection
- dues_schedule_lifecycle_service: Schedule lifecycle (pause/resume/cancel)
- dues_schedule_permission_service: Permission management for schedules
- dues_schedule_validation_service: Validation logic for schedules
- duplicate_invoice_detector: Duplicate invoice detection
- fee_change_tracking_service: Fee change history tracking
- invoice_error_handler_service: Error handling for invoice generation
- invoice_generation_orchestrator: Single-schedule invoice generation pipeline
- invoice_generator: Individual invoice generation
- progressive_dues_service: Income-based progressive dues calculation
- template_configuration_service: Template value loading and validation
- template_creation_service: Template and schedule creation
"""

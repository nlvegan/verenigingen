"""MijnRood Event Application Service — re-export shim.

This module's content has been moved to
verenigingen/mijnrood_sync/services/event_application/dispatcher.py
as Phase 1, PR #7 of the Tier C refactor (see
docs/plans/2026-05-12-event-application-service-refactor-design.md).

Existing callers (DocType controller, test suite, whitelist endpoint
references) import from this path; the re-exports below preserve those
import paths verbatim so no caller needs to change.
"""

from verenigingen.mijnrood_sync.services.event_application.dispatcher import (  # noqa: F401
    MijnRoodEventApplicationService,
    batch_apply,
    batch_approve,
    batch_approve_and_apply,
    get_event_application_service,
)

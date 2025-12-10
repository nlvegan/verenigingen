# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Document Services Module

Provides document upload portal functionality for organizations
(Chapters, Teams, Movements).
"""

from verenigingen.services.document.document_portal_service import (
    DocumentPortalService,
    get_document_portal_service,
)

__all__ = ["DocumentPortalService", "get_document_portal_service"]

# Communication Services Module
"""
Unified communication services for the Verenigingen application.

This module provides centralized email functionality. For document-triggered
notifications, use Frappe's native Notification DocType instead.

Usage patterns:
- Document events (New, Save, Submit, Value Change) → Notification DocType
- Programmatic/scheduled emails → EmailService.send_templated_email()
"""

from .email_service import EmailService

__all__ = ["EmailService"]

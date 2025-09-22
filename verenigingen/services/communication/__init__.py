# Communication Services Module
"""
Unified communication services for the Verenigingen application.

This module provides centralized email, notification, and communication
functionality to replace the scattered email implementations throughout
the codebase.
"""

from .email_service import EmailService
from .notification_dispatcher import NotificationDispatcher
from .template_manager import TemplateManager

__all__ = ["EmailService", "TemplateManager", "NotificationDispatcher"]

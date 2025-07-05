# verenigingen/verenigingen/doctype/chapter/managers/basemanager.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import frappe
from frappe import _


class BaseManager(ABC):
    """Base class for all chapter managers"""

    def __init__(self, chapter_doc):
        """
        Initialize manager with chapter document

        Args:
            chapter_doc: Chapter document instance
        """
        self.chapter_doc = chapter_doc
        self.context = {}
        self._cache = {}

    @property
    def chapter_name(self) -> str:
        """Get chapter name"""
        return self.chapter_doc.name if self.chapter_doc else ""

    def log_action(self, action: str, details: Dict = None, level: str = "info"):
        """
        Log manager actions for audit trail

        Args:
            action: Action description
            details: Additional details to log
            level: Log level (info, warning, error)
        """
        log_data = {
            "manager": self.__class__.__name__,
            "chapter": self.chapter_name,
            "action": action,
            "details": details or {},
            "context": self.context,
        }

        if level == "error":
            frappe.log_error(message=str(log_data), title=f"Chapter Manager Error: {action}")
        elif level == "warning":
            frappe.logger().warning(f"Chapter Manager Warning: {log_data}")
        else:
            frappe.logger().info(f"Chapter Manager Action: {log_data}")

    def validate_chapter_doc(self):
        """Validate that chapter document is available"""
        if not self.chapter_doc:
            frappe.throw(_("Chapter document not available"))

    def get_cached(self, key: str, default: Any = None) -> Any:
        """Get cached value"""
        return self._cache.get(key, default)

    def set_cached(self, key: str, value: Any):
        """Set cached value"""
        self._cache[key] = value

    def clear_cache(self, key: str = None):
        """Clear cache (specific key or all)"""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def send_notification(self, template: str, recipients: List[str], context: Dict, subject: str = None):
        """
        Send email notification using template

        Args:
            template: Email template name
            recipients: List of email addresses
            context: Template context variables
            subject: Email subject (optional)
        """
        if not recipients:
            return

        try:
            # Check if template exists
            if not frappe.db.exists("Email Template", template):
                self.log_action(
                    f"Email template '{template}' not found", {"recipients": len(recipients)}, "warning"
                )
                return

            # Send email using Email Template
            email_template_doc = frappe.get_doc("Email Template", template)
            frappe.sendmail(
                recipients=recipients,
                subject=email_template_doc.subject or subject or f"Notification from {self.chapter_name}",
                message=frappe.render_template(email_template_doc.response, context),
                header=[("Chapter Notification"), "blue"],
            )

            self.log_action(f"Notification sent via template '{template}'", {"recipients": len(recipients)})

        except Exception as e:
            self.log_action(
                f"Failed to send notification via template '{template}'",
                {"error": str(e), "recipients": len(recipients)},
                "error",
            )

    def create_comment(
        self, comment_type: str, content: str, reference_doctype: str = None, reference_name: str = None
    ):
        """
        Create a comment for audit trail

        Args:
            comment_type: Type of comment (Info, Update, etc.)
            content: Comment content
            reference_doctype: Reference document type (defaults to Chapter)
            reference_name: Reference document name (defaults to chapter name)
        """
        try:
            comment_doc = frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": comment_type,
                    "reference_doctype": reference_doctype or "Chapter",
                    "reference_name": reference_name or self.chapter_name,
                    "content": content,
                }
            )
            comment_doc.insert(ignore_permissions=True)

        except Exception as e:
            self.log_action("Failed to create comment", {"error": str(e), "content": content[:100]}, "error")

    def validate_permissions(self, action: str, user: str = None) -> bool:
        """
        Validate user permissions for an action

        Args:
            action: Action being performed
            user: User to check (defaults to current user)

        Returns:
            bool: Whether user has permission
        """
        if not user:
            user = frappe.session.user

        # System managers can do everything
        if "System Manager" in frappe.get_roles(user):
            return True

        # Association managers can manage chapters
        if "Verenigingen Administrator" in frappe.get_roles(user):
            return True

        # Check if user is a board member of this chapter
        if self.chapter_doc:
            try:
                board_member = self._is_user_board_member(user)
                if board_member:
                    return self._check_board_member_permissions(board_member, action)
            except Exception as e:
                self.log_action(
                    "Error checking board member permissions",
                    {"user": user, "action": action, "error": str(e)},
                    "error",
                )

        return False

    def _is_user_board_member(self, user: str) -> Optional[Dict]:
        """Check if user is a board member"""
        # Get member from user
        member = frappe.db.get_value("Member", {"user": user}, "name")
        if not member:
            return None

        # Find volunteer(s) for this member
        volunteers = frappe.get_all(
            "Volunteer", filters={"member": member, "status": "Active"}, fields=["name"]
        )

        if not volunteers:
            return None

        volunteer_ids = [v.name for v in volunteers]

        # Check if any volunteer is on the board
        for board_member in self.chapter_doc.board_members or []:
            if board_member.volunteer in volunteer_ids and board_member.is_active:
                return {
                    "volunteer": board_member.volunteer,
                    "role": board_member.chapter_role,
                    "member": member,
                }

        return None

    def _check_board_member_permissions(self, board_member: Dict, action: str) -> bool:
        """Check if board member has permission for action"""
        role_name = board_member.get("role")
        if not role_name:
            return False

        try:
            role_doc = frappe.get_doc("Chapter Role", role_name)

            # Define action permission mappings
            permission_map = {
                "add_board_member": ["Admin", "Financial"],
                "remove_board_member": ["Admin"],
                "manage_members": ["Admin", "Financial", "Basic"],
                "send_communication": ["Admin", "Financial", "Basic"],
                "view_reports": ["Admin", "Financial", "Basic"],
                "bulk_operations": ["Admin"],
            }

            required_levels = permission_map.get(action, [])
            return role_doc.permissions_level in required_levels

        except frappe.DoesNotExistError:
            return False

    def get_settings_value(self, setting_name: str, default_value: Any = None) -> Any:
        """
        Get setting value from Verenigingen Settings

        Args:
            setting_name: Setting field name
            default_value: Default value if setting not found

        Returns:
            Setting value or default
        """
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return getattr(settings, setting_name, default_value)
        except Exception:
            return default_value

    def execute_with_retry(self, func, max_retries: int = 3, delay: float = 1.0):
        """
        Execute function with retry logic

        Args:
            func: Function to execute
            max_retries: Maximum retry attempts
            delay: Delay between retries in seconds

        Returns:
            Function result
        """
        import time

        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return func()
            except Exception as e:
                last_exception = e

                if attempt < max_retries:
                    self.log_action(
                        f"Retry attempt {attempt + 1}/{max_retries}", {"error": str(e)}, "warning"
                    )
                    time.sleep(delay)
                else:
                    self.log_action("All retry attempts failed", {"error": str(e)}, "error")

        # Re-raise the last exception
        raise last_exception

    @abstractmethod
    def get_summary(self) -> Dict:
        """
        Get summary of manager's domain

        Returns:
            Dict with summary information
        """

    def cleanup(self):
        """Cleanup manager resources"""
        self.clear_cache()
        self.context.clear()

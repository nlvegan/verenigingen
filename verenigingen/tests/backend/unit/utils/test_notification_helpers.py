"""
Unit tests for notification_helpers module.

Tests the notification helper functions including:
- send_volunteer_email() - volunteer-specific email sending
- get_notification_recipients() - hierarchical recipient determination
- get_threshold_setting() - threshold value retrieval
- create_system_notification() - in-app notification creation
- notify_administrators() - admin notification convenience function
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.notification_helpers import (
    create_system_notification,
    get_notification_recipients,
    get_threshold_setting,
    notify_administrators,
    send_volunteer_email,
)


class TestSendVolunteerEmail(FrappeTestCase):
    """Test send_volunteer_email function."""

    def test_returns_failure_when_no_volunteer(self):
        """Test returns failure when volunteer is None or empty."""
        result = send_volunteer_email(
            volunteer=None,
            template_name="test_template",
            notification_key="test_key",
        )
        self.assertFalse(result["success"])
        self.assertIn("No volunteer", result["reason"])

        result = send_volunteer_email(
            volunteer="",
            template_name="test_template",
            notification_key="test_key",
        )
        self.assertFalse(result["success"])

    def test_returns_failure_when_volunteer_not_found(self):
        """Test returns failure when volunteer doesn't exist."""
        result = send_volunteer_email(
            volunteer="NON-EXISTENT-VOL",
            template_name="test_template",
            notification_key="test_key",
        )
        self.assertFalse(result["success"])
        self.assertIn("not found", result["reason"])

    def test_returns_failure_when_no_linked_member(self):
        """Test returns failure when volunteer has no linked member."""
        mock_volunteer = MagicMock()
        mock_volunteer.member = None

        with patch("frappe.get_doc", return_value=mock_volunteer):
            result = send_volunteer_email(
                volunteer="VOL-001",
                template_name="test_template",
                notification_key="test_key",
            )
            self.assertFalse(result["success"])
            self.assertIn("no linked member", result["reason"])

    def test_returns_failure_when_member_has_no_email(self):
        """Test returns failure when member has no email."""
        mock_volunteer = MagicMock()
        mock_volunteer.member = "MEM-001"

        mock_member = MagicMock()
        mock_member.email = None

        def get_doc_side_effect(doctype, name=None):
            if doctype == "Volunteer":
                return mock_volunteer
            elif doctype == "Member":
                return mock_member
            return MagicMock()

        with patch("frappe.get_doc", side_effect=get_doc_side_effect):
            result = send_volunteer_email(
                volunteer="VOL-001",
                template_name="test_template",
                notification_key="test_key",
            )
            self.assertFalse(result["success"])
            self.assertIn("no email", result["reason"])

    def test_sends_email_with_correct_context(self):
        """Test send_volunteer_email builds and forwards the real context.

        Rewritten: the previous version never called send_volunteer_email at
        all — it reimplemented the context-building dict inline and asserted
        against its own reimplementation (always passes; catches nothing).
        This calls the real function, mocking only the true I/O boundaries
        (frappe.get_doc for the DB lookups, EmailService for the send), and
        asserts on what the production code actually builds and forwards.
        """
        mock_member = MagicMock()
        mock_member.full_name = "Test Member"
        mock_member.first_name = "Test"
        mock_member.last_name = "Member"
        mock_member.email = "test@example.com"

        mock_volunteer = MagicMock()
        mock_volunteer.member = "MEM-001"
        mock_volunteer.volunteer_name = "Test Volunteer"

        def get_doc_side_effect(doctype, name=None):
            if doctype == "Volunteer":
                return mock_volunteer
            elif doctype == "Member":
                return mock_member
            return MagicMock()

        mock_email_service = MagicMock()
        mock_email_service.send_templated_email.return_value = {"success": True}

        with patch("frappe.get_doc", side_effect=get_doc_side_effect):
            with patch(
                "verenigingen.services.communication.email_service.get_email_service",
                return_value=mock_email_service,
            ):
                result = send_volunteer_email(
                    volunteer="VOL-001",
                    template_name="test_template",
                    notification_key="test_key",
                    extra_context={"custom_field": "custom_value"},
                )

        self.assertTrue(result["success"])
        call_kwargs = mock_email_service.send_templated_email.call_args.kwargs
        self.assertEqual(call_kwargs["recipients"], ["test@example.com"])
        self.assertEqual(call_kwargs["template_name"], "test_template")
        context = call_kwargs["context"]
        self.assertEqual(context["member_name"], "Test Member")
        self.assertEqual(context["volunteer_name"], "Test Volunteer")
        self.assertEqual(context["custom_field"], "custom_value")
        self.assertIs(context["member"], mock_member)
        self.assertIs(context["volunteer"], mock_volunteer)


class TestGetNotificationRecipients(FrappeTestCase):
    """Test get_notification_recipients function."""

    def test_returns_custom_emails_when_configured(self):
        """Test returns custom emails from Verenigingen Settings."""
        mock_settings = MagicMock()
        mock_settings.custom_email_field = "admin@test.com, support@test.com"

        with patch("frappe.get_single", return_value=mock_settings):
            result = get_notification_recipients("custom_email_field")
            self.assertEqual(result, ["admin@test.com", "support@test.com"])

    def test_falls_back_to_roles_when_no_custom_emails(self):
        """Test falls back to role-based lookup when no custom emails."""
        mock_settings = MagicMock()
        mock_settings.custom_email_field = None

        mock_users = [
            MagicMock(email="admin@test.com", full_name="Admin User"),
            MagicMock(email="manager@test.com", full_name="Manager User"),
        ]

        with patch("frappe.get_single", return_value=mock_settings):
            with patch("frappe.get_all", return_value=mock_users):
                result = get_notification_recipients("custom_email_field")
                self.assertEqual(result, ["admin@test.com", "manager@test.com"])

    def test_uses_default_roles_when_not_specified(self):
        """Test uses default roles (Roles.ADMIN_PAIR) when not specified.

        Rewritten: the previous version computed `filters` and then asserted
        nothing about it (dead local variable, 0 real assertions — would
        pass unchanged even if the default-roles fallback were deleted).
        """
        from verenigingen.utils.constants import Roles

        mock_settings = MagicMock()
        mock_settings.test_field = None

        with patch("frappe.get_single", return_value=mock_settings):
            with patch("frappe.get_all") as mock_get_all:
                mock_get_all.return_value = []
                get_notification_recipients("test_field")

                # The default-roles fallback query must actually use ADMIN_PAIR.
                call_args = mock_get_all.call_args
                self.assertEqual(call_args.args[0], "User")
                filters = call_args.kwargs["filters"]
                role_filter = next(f for f in filters if f[0] == "Has Role")
                self.assertEqual(set(role_filter[3]), set(Roles.ADMIN_PAIR))

    def test_emergency_fallback_to_system_manager(self):
        """Test falls back to System Manager emails when the primary lookup raises.

        Rewritten: the previous version wrapped the call in try/except and,
        on ANY exception, asserted `self.assertTrue(True)` — a tautology that
        passes no matter what the fallback does (or doesn't do). This forces
        the primary path to fail and asserts the actual System Manager
        fallback query result is returned.
        """
        from verenigingen.utils.constants import Roles

        real_get_all = frappe.get_all

        def get_all_side_effect(doctype, filters=None, **kwargs):
            # The emergency-fallback call queries by System Manager role —
            # intercept only that; anything else (e.g. frappe.log_error's own
            # internal lookups) must still hit the real implementation.
            if filters == [["Has Role", "role", "=", Roles.SYSTEM_MANAGER]]:
                return ["sysmgr1@test.com", "sysmgr2@test.com", None]
            return real_get_all(doctype, filters=filters, **kwargs)

        with patch("frappe.get_single", side_effect=Exception("Settings unavailable")):
            with patch("frappe.get_all", side_effect=get_all_side_effect):
                result = get_notification_recipients("nonexistent_field_12345")

        self.assertEqual(result, ["sysmgr1@test.com", "sysmgr2@test.com"])


class TestGetThresholdSetting(FrappeTestCase):
    """Test get_threshold_setting function."""

    def test_returns_setting_value_when_available(self):
        """Test returns setting value from Vereinigingen Settings."""
        mock_settings = MagicMock()
        mock_settings.payment_max_retries = 5

        with patch("frappe.get_single", return_value=mock_settings):
            result = get_threshold_setting("payment_max_retries", 3)
            self.assertEqual(result, 5)

    def test_returns_default_when_setting_not_found(self):
        """Test returns default value when setting doesn't exist."""
        mock_settings = MagicMock(spec=[])  # No attributes

        with patch("frappe.get_single", return_value=mock_settings):
            result = get_threshold_setting("nonexistent_setting", 10)
            self.assertEqual(result, 10)

    def test_returns_default_on_exception(self):
        """Test returns default value on any exception."""
        with patch("frappe.get_single", side_effect=Exception("Error")):
            result = get_threshold_setting("any_field", 42)
            self.assertEqual(result, 42)


class TestCreateSystemNotification(FrappeTestCase):
    """Test create_system_notification function."""

    _TEST_RECIPIENT = "notification-helper-test@example.com"

    def setUp(self):
        super().setUp()
        self._create_test_recipient()

    def _create_test_recipient(self):
        """Ensure a real, enabled User exists whose docname == email.

        A dedicated fixture user whose docname == email; the Administrator
        and name != email cases (#1958) have their own tests below.
        """
        if not frappe.db.exists("User", self._TEST_RECIPIENT):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self._TEST_RECIPIENT,
                    "first_name": "Notification",
                    "last_name": "Helper Test",
                    "enabled": 1,
                    "send_welcome_email": 0,
                }
            )
            user.insert(ignore_permissions=True)

    def _logs_for(self, subject):
        return frappe.get_all("Notification Log", filters={"subject": subject}, pluck="for_user")

    def _creation_error_count(self):
        """Error Log is MyISAM (no rollback), so tests compare the count before and after the call."""
        return frappe.db.count("Error Log", {"method": "Notification Creation Error"})

    def test_administrator_alone_is_dropped_silently_by_name_and_by_email_1958(self):
        """Staff alerts never go to Administrator (2026-11-01): no log, no Error Log row, no error entry."""
        admin_email = frappe.db.get_value("User", "Administrator", "email")
        self.assertTrue(admin_email, "control: Administrator has an email")
        self.assertNotEqual(admin_email, "Administrator", "control: its email is not its name")
        for label, recipient in (("name", "Administrator"), ("email", admin_email)):
            marker = f"adm1958 {label} {frappe.generate_hash(length=8)}"
            errors_before = self._creation_error_count()
            result = create_system_notification([recipient], marker, "m")
            self.assertEqual(result["notifications_created"], 0, (label, result))
            self.assertFalse(result["success"], (label, result))
            self.assertFalse(result.get("errors"), (label, result))
            self.assertEqual(self._logs_for(marker), [], label)
            self.assertEqual(self._creation_error_count(), errors_before, label)

    def test_a_user_whose_name_differs_from_their_email_is_addressed_by_name_1958(self):
        """Probe shortcut: Frappe's User.validate forces email = name for every non-standard user, so a
        real non-Administrator user cannot be made with name != email through insert/save/rename. The
        drift is written straight to the column (``db.set_value``), as legacy data or a raw write would.
        Reached both by the drifted email and by the name."""
        drifted_name = f"drift1958-{frappe.generate_hash(length=6)}@example.com".lower()
        drifted_email = f"other-{frappe.generate_hash(length=6)}@example.com".lower()
        frappe.get_doc(
            {
                "doctype": "User",
                "email": drifted_name,
                "first_name": "Drift",
                "enabled": 1,
                "send_welcome_email": 0,
            }
        ).insert()
        frappe.db.set_value("User", drifted_name, "email", drifted_email, update_modified=False)
        self.assertNotEqual(frappe.db.get_value("User", drifted_name, "email"), drifted_name, "control")
        for label, recipient in (("by-email", drifted_email), ("by-name", drifted_name)):
            marker = f"drift1958 {label} {frappe.generate_hash(length=8)}"
            errors_before = self._creation_error_count()
            result = create_system_notification([recipient], marker, "m")
            self.assertTrue(result["success"], (label, result))
            self.assertEqual(self._logs_for(marker), [drifted_name], label)
            self.assertEqual(self._creation_error_count(), errors_before, label)

    def test_administrator_mixed_with_a_real_user_only_the_real_user_gets_a_log_1958(self):
        admin_email = frappe.db.get_value("User", "Administrator", "email")
        marker = f"mixed1958 {frappe.generate_hash(length=8)}"
        errors_before = self._creation_error_count()
        result = create_system_notification(
            ["Administrator", admin_email, self._TEST_RECIPIENT, self._TEST_RECIPIENT], marker, "m"
        )
        self.assertEqual(result["notifications_created"], 1, result)
        self.assertTrue(result["success"], result)
        self.assertFalse(result.get("errors"), result)
        self.assertEqual(self._logs_for(marker), [self._TEST_RECIPIENT])
        self.assertEqual(self._creation_error_count(), errors_before)

    def test_returns_failure_when_no_recipients(self):
        """Test returns failure when no recipients provided."""
        result = create_system_notification(
            recipients=[],
            subject="Test",
            message="Test message",
        )
        self.assertFalse(result["success"])
        self.assertIn("No recipients", result["error"])

    def test_handles_string_recipient(self):
        """Test handles single string recipient."""
        # Should not crash on string input
        with patch("frappe.get_all", return_value=[]):
            result = create_system_notification(
                recipients="single@example.com",
                subject="Test",
                message="Test message",
            )
            # May fail due to invalid user, but should not crash
            self.assertIn("success", result)

    def test_truncates_long_subject(self):
        """Test create_system_notification truncates a >200-char subject.

        Rewritten: the previous version never called create_system_notification —
        it reimplemented the truncation slicing in-test and asserted against
        its own copy (would stay green even if the production truncation were
        deleted). This calls the real function against a real enabled user
        ("Administrator", guaranteed to exist on every site) and reads back
        the actually-stored Notification Log subject.
        """
        long_subject = "S" * 300

        result = create_system_notification(
            recipients=[self._TEST_RECIPIENT],
            subject=long_subject,
            message="Truncation test message",
        )
        self.assertTrue(result["success"], result)

        stored = frappe.get_all(
            "Notification Log",
            filters={"for_user": self._TEST_RECIPIENT, "subject": ["like", "SSS%"]},
            fields=["subject"],
            order_by="creation desc",
            limit=1,
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(len(stored[0].subject), 200)
        self.assertTrue(stored[0].subject.endswith("..."))

    def test_truncates_long_message(self):
        """Test create_system_notification truncates a >50KB message.

        Rewritten: the previous version never called create_system_notification —
        it reimplemented the truncation slicing in-test. This calls the real
        function and reads back the actually-stored email_content.
        """
        long_message = "M" * 60000

        result = create_system_notification(
            recipients=[self._TEST_RECIPIENT],
            subject="Truncate message test",
            message=long_message,
        )
        self.assertTrue(result["success"], result)

        stored = frappe.get_all(
            "Notification Log",
            filters={"for_user": self._TEST_RECIPIENT, "subject": "Truncate message test"},
            fields=["email_content"],
            order_by="creation desc",
            limit=1,
        )
        self.assertEqual(len(stored), 1)
        content = stored[0].email_content
        self.assertTrue(content.endswith("... [truncated]"))
        self.assertEqual(len(content), 50000 + len("... [truncated]"))

    def test_respects_notification_key_disable(self):
        """Test respects notification disabled via Verenigingen Email Configuration."""
        mock_config_service = MagicMock()
        mock_config_service.is_email_enabled.return_value = True
        mock_config_service.is_notification_enabled.return_value = False

        with patch(
            "verenigingen.utils.notification_helpers._get_email_config_service",
            return_value=mock_config_service,
        ):
            result = create_system_notification(
                recipients=["admin@test.com"],
                subject="Test",
                message="Test message",
                notification_key="disabled_notification",
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["skipped"])
            self.assertEqual(result["notifications_created"], 0)

    def test_respects_global_disable(self):
        """Test respects global email disable via Verenigingen Email Configuration."""
        mock_config_service = MagicMock()
        mock_config_service.is_email_enabled.return_value = False

        with patch(
            "verenigingen.utils.notification_helpers._get_email_config_service",
            return_value=mock_config_service,
        ):
            result = create_system_notification(
                recipients=["admin@test.com"],
                subject="Test",
                message="Test message",
                notification_key="any_key",
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["skipped"])

    def test_limits_recipients_to_max(self):
        """Test create_system_notification caps recipients to MAX_RECIPIENTS (100).

        Rewritten: the previous version reimplemented the slicing in-test
        instead of calling create_system_notification. This mocks only the
        true DB boundary (the recipient-validation query, and doc creation —
        creating 150 real Users would be excessive for a unit test) while
        exercising the REAL MAX_RECIPIENTS-limiting code path and asserting
        on its actual output.
        """
        many_emails = [f"user{i}@test.com" for i in range(150)]

        with patch("frappe.get_all", return_value=many_emails):
            with patch("frappe.new_doc", return_value=MagicMock()) as mock_new_doc:
                result = create_system_notification(
                    recipients=many_emails,
                    subject="Bulk recipient test",
                    message="Test message",
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["notifications_created"], 100)
        self.assertEqual(mock_new_doc.call_count, 100)


class TestNotifyAdministrators(FrappeTestCase):
    """Test notify_administrators convenience function."""

    def test_uses_email_configuration_for_recipients(self):
        """Test uses Verenigingen Email Configuration for recipient lookup."""
        mock_config_service = MagicMock()
        mock_config_service.get_category_recipients.return_value = ["admin@config.com"]
        mock_config_service.is_email_enabled.return_value = True
        mock_config_service.is_notification_enabled.return_value = True

        with patch(
            "verenigingen.utils.notification_helpers._get_email_config_service",
            return_value=mock_config_service,
        ):
            with patch("verenigingen.utils.notification_helpers.create_system_notification") as mock_create:
                mock_create.return_value = {"success": True, "notifications_created": 1}

                notify_administrators(
                    subject="Test",
                    message="Test message",
                    category="Admin",
                )

                # Verify create_system_notification was called with config recipients
                call_args = mock_create.call_args
                self.assertEqual(call_args.kwargs["recipients"], ["admin@config.com"])

    def test_falls_back_to_legacy_recipients(self):
        """Test falls back to legacy recipient lookup when no config."""
        with patch(
            "verenigingen.utils.notification_helpers._get_email_config_service",
            return_value=None,
        ):
            with patch(
                "verenigingen.utils.notification_helpers.get_notification_recipients",
                return_value=["legacy@test.com"],
            ):
                with patch(
                    "verenigingen.utils.notification_helpers.create_system_notification"
                ) as mock_create:
                    mock_create.return_value = {"success": True, "notifications_created": 1}

                    notify_administrators(
                        subject="Test",
                        message="Test message",
                    )

                    # Verify legacy recipients were used
                    call_args = mock_create.call_args
                    self.assertEqual(call_args.kwargs["recipients"], ["legacy@test.com"])

    def test_uses_notification_key_for_recipients(self):
        """Test uses notification_key for recipient lookup."""
        mock_config_service = MagicMock()
        mock_config_service.get_category_recipients.return_value = []
        mock_config_service.get_recipients_for_notification.return_value = ["notif@test.com"]
        mock_config_service.is_email_enabled.return_value = True
        mock_config_service.is_notification_enabled.return_value = True

        with patch(
            "verenigingen.utils.notification_helpers._get_email_config_service",
            return_value=mock_config_service,
        ):
            with patch("verenigingen.utils.notification_helpers.create_system_notification") as mock_create:
                mock_create.return_value = {"success": True, "notifications_created": 1}

                notify_administrators(
                    subject="Test",
                    message="Test message",
                    notification_key="test_notification",
                )

                # Verify notification key was used
                mock_config_service.get_recipients_for_notification.assert_called_with("test_notification")

    def test_passes_all_parameters_to_create_notification(self):
        """Test passes all parameters to create_system_notification."""
        with patch(
            "verenigingen.utils.notification_helpers._get_email_config_service",
            return_value=None,
        ):
            with patch(
                "verenigingen.utils.notification_helpers.get_notification_recipients",
                return_value=["test@test.com"],
            ):
                with patch(
                    "verenigingen.utils.notification_helpers.create_system_notification"
                ) as mock_create:
                    mock_create.return_value = {"success": True, "notifications_created": 1}

                    notify_administrators(
                        subject="Test Subject",
                        message="Test Message",
                        notification_type="Alert",
                        document_type="Member",
                        document_name="MEM-001",
                        notification_key="test_key",
                    )

                    call_args = mock_create.call_args
                    self.assertEqual(call_args.kwargs["subject"], "Test Subject")
                    self.assertEqual(call_args.kwargs["message"], "Test Message")
                    self.assertEqual(call_args.kwargs["notification_type"], "Alert")
                    self.assertEqual(call_args.kwargs["document_type"], "Member")
                    self.assertEqual(call_args.kwargs["document_name"], "MEM-001")
                    self.assertEqual(call_args.kwargs["notification_key"], "test_key")


if __name__ == "__main__":
    import unittest

    unittest.main()

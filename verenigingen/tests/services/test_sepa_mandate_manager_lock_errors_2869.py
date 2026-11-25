"""#2869: SEPAMandateManager must not flatten 1213/1205 into a ValidationResult.failure.

``create_mandate``, ``sync_member_mandates`` and ``deactivate_mandates_for_iban_change`` each end
in ``except Exception: return ValidationResult.failure(...)``. A deadlock (1213) means the server
already rolled the whole transaction back, so a caller reading ``result.valid == False`` carried
on against a transaction that no longer held its earlier writes; a lock wait timeout (1205) leaves
the unit of work half-applied. Both must propagate (#2700). Every other failure keeps the
result contract, which the control tests pin.

The lock errors are injected, not provoked (a real deadlock needs a second connection), BELOW the
swallowing handler: inside ``validate_mandate_creation`` (a ``frappe.db.exists``), at the
``SEPA Mandate`` insert (underneath ``secure_document_operation``, which itself re-raises these),
and at the ``get_all`` that the sync/deactivate paths issue. Each test asserts from the
traceback that the error was raised inside the manager module, so a neighbour re-raising cannot
make it pass.
"""

import traceback
from unittest.mock import patch

import frappe

from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban

LOCK_ERRORS = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)
MANAGER_FILE = "sepa_mandate_manager.py"
DRIVER_LOCK_ERRORS = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))


class TestSEPAMandateManagerLockErrors2869(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.manager = get_sepa_mandate_manager()
        self.member = self.create_test_member(
            first_name="Lock",
            last_name="Err",
            birth_date="1990-01-01",
            email=f"lock.err.{frappe.generate_hash(length=8)}@example.com",
        )
        self.iban = generate_test_iban("RABO", "0123456789")

    def _create(self, **kwargs):
        return self.manager.create_mandate(
            member=self.member.name,
            iban=self.iban,
            account_holder_name="Lock Err",
            mandate_id=f"M-2869-{frappe.generate_hash(length=8)}",
            **kwargs,
        )

    def _assert_propagates_from_manager(self, error, call):
        """``call()`` must raise *error*, with the manager module on the traceback.

        assertRaises strips the traceback (``with_traceback(None)``), so catch by hand.
        """
        try:
            call()
        except error as exc:
            frames = [f.filename for f in traceback.extract_tb(exc.__traceback__)]
            self.assertTrue(
                any(name.endswith(MANAGER_FILE) for name in frames),
                "the injected error must have passed through the manager module",
            )
        else:
            self.fail(f"{error.__name__} was swallowed")

    def _exists_raising(self, error):
        real = frappe.db.exists

        def exists(dt, *args, **kwargs):
            if dt == "SEPA Mandate":
                raise error("injected in validate_mandate_creation")
            return real(dt, *args, **kwargs)

        # Mock justified: fault injection, calls through for everything but SEPA Mandate
        return patch.object(frappe.db, "exists", exists)

    def _insert_raising(self, error):
        real = frappe.model.document.Document.insert

        def insert(doc, *args, **kwargs):
            if doc.doctype == "SEPA Mandate":
                raise error("injected at the SEPA Mandate insert")
            return real(doc, *args, **kwargs)

        return patch("frappe.model.document.Document.insert", insert)

    def _get_all_raising(self, error):
        real = frappe.get_all

        def get_all(doctype, *args, **kwargs):
            if doctype == "SEPA Mandate":
                raise error("injected in the SEPA Mandate query")
            return real(doctype, *args, **kwargs)

        # Mock justified: fault injection, calls through for everything but SEPA Mandate
        return patch("frappe.get_all", get_all)

    # -- the defect -------------------------------------------------------------------

    def test_create_mandate_propagates_lock_errors_from_validation(self):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__), self._exists_raising(error):
                self._assert_propagates_from_manager(error, lambda: self._create())

    def test_create_mandate_propagates_lock_errors_from_the_insert(self):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__), self._insert_raising(error):
                self._assert_propagates_from_manager(error, lambda: self._create())

    def test_sync_member_mandates_propagates_lock_errors(self):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__), self._get_all_raising(error):
                self._assert_propagates_from_manager(
                    error, lambda: self.manager.sync_member_mandates(self.member.name)
                )

    def test_deactivate_mandates_propagates_lock_errors(self):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__), self._get_all_raising(error):
                self._assert_propagates_from_manager(
                    error,
                    lambda: self.manager.deactivate_mandates_for_iban_change(self.member.name, self.iban),
                )

    # -- the opposite harm: everything else keeps the result contract -----------------

    def test_invalid_iban_still_returns_a_failure_result(self):
        result = self.manager.create_mandate(member=self.member.name, iban="NOT-AN-IBAN")
        self.assertFalse(result.valid)

    def test_duplicate_mandate_id_still_returns_a_failure_result(self):
        first = self._create()
        self.assertTrue(first.valid, first.message)
        result = self.manager.create_mandate(
            member=self.member.name,
            iban=self.iban,
            mandate_id=first.data["mandate_id"],
            allow_duplicate_iban=True,
        )
        self.assertFalse(result.valid)

    def test_an_ordinary_error_is_still_flattened_into_a_failure_result(self):
        with self._exists_raising(frappe.ValidationError):
            result = self._create()
        self.assertFalse(result.valid)
        self.assertIn("injected", result.message)
        with self._get_all_raising(frappe.ValidationError):
            self.assertFalse(self.manager.sync_member_mandates(self.member.name).valid)
            self.assertFalse(
                self.manager.deactivate_mandates_for_iban_change(self.member.name, self.iban).valid
            )

    # -- F1: the lock error is raised at the DRIVER, so it passes through every layer of the
    # real path: SEPA Mandate insert -> after_insert -> lifecycle service -> member integration
    # service (whose own ``except Exception`` turned it into ``{"success": False}`` + an Error
    # Log row, leaving create_mandate to report success with the Member link never written).

    def _driver_raising_on(self, code, fragment):
        """Cursor.execute raises a real driver OperationalError(code) on UPDATEs of *fragment*."""
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if isinstance(query, str) and query.lstrip().upper().startswith("UPDATE") and fragment in query:
                raise frappe.db.OperationalError(code, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute)

    def test_create_mandate_raises_when_the_member_link_write_hits_a_lock_error(self):
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                with self._driver_raising_on(code, "`tabMember`"):
                    self._assert_propagates_from_manager(error, lambda: self._create())

    def test_a_real_database_error_that_is_not_a_lock_error_still_flows_to_a_failure_result(self):
        """Control, real DB: a duplicate key is NOT a lock error and must keep the result contract."""
        self.expectErrorLog("Secure Operation Failed")
        first = self._create()
        self.assertTrue(first.valid, first.message)
        real_insert = frappe.model.document.Document.insert

        def insert(doc, *args, **kwargs):
            if doc.doctype == "SEPA Mandate":
                raise frappe.DuplicateEntryError("SEPA Mandate", doc.mandate_id, Exception("1062"))
            return real_insert(doc, *args, **kwargs)

        with patch("frappe.model.document.Document.insert", insert):
            result = self.manager.create_mandate(
                member=self.member.name, iban=self.iban, allow_duplicate_iban=True
            )
        self.assertFalse(result.valid)

    def test_refresh_sepa_mandates_endpoint_does_not_flatten_a_lock_error(self):
        """The sync path's first caller (api/member/sepa_api.refresh_sepa_mandates) used to turn the
        error the manager now propagates back into ``{"success": False}``."""
        from verenigingen.api.member.sepa_api import refresh_sepa_mandates

        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__), self._get_all_raising(error):
                with self.assertRaises(error):
                    refresh_sepa_mandates(self.member.name)

    def test_refresh_sepa_mandates_endpoint_still_flattens_an_ordinary_error(self):
        from verenigingen.api.member.sepa_api import refresh_sepa_mandates

        self.expectErrorLog("Error refreshing SEPA mandates")
        with self._get_all_raising(frappe.ValidationError):
            result = refresh_sepa_mandates(self.member.name)
        self.assertFalse(result["success"])

    # -- R1/R2: the audit row and the audit write ------------------------------------------

    def _audit_enabled(self):
        """_create_sepa_audit_log returns early under frappe.flags.in_test; switch that off."""
        return patch.dict(frappe.flags, {"in_test": False})

    def _audit_status(self, mandate_id):
        return frappe.db.get_value(
            "SEPA Operation Audit Log", {"mandate_reference": mandate_id}, "operation_status"
        )

    def test_a_lock_error_in_the_member_link_write_is_audited_as_failed(self):
        """The audit row of an operation that died of a lock error says ``failed``.

        Without a status ``operation_status`` (a Select with no default) auto-fills its first
        option, ``success``: an audit trail claiming the operation succeeded.
        """
        mandate_id = f"M-2869-{frappe.generate_hash(length=8)}"
        with self._audit_enabled(), self._driver_raising_on(1213, "`tabMember`"):
            with self.assertRaises(frappe.QueryDeadlockError):
                self.manager.create_mandate(
                    member=self.member.name,
                    iban=self.iban,
                    account_holder_name="Lock Err",
                    mandate_id=mandate_id,
                )
        self.assertEqual(self._audit_status(mandate_id), "failed")

    def _audit_insert_raising(self, error):
        real = frappe.model.document.Document.insert

        def insert(doc, *args, **kwargs):
            if doc.doctype == "SEPA Operation Audit Log":
                raise error("injected at the audit insert")
            return real(doc, *args, **kwargs)

        return patch("frappe.model.document.Document.insert", insert)

    def test_a_deadlock_on_the_audit_insert_propagates(self):
        """1213 rolled the whole transaction back: the best-effort audit must not carry on."""
        with self._audit_enabled(), self._audit_insert_raising(frappe.QueryDeadlockError):
            self._assert_propagates_from_manager(frappe.QueryDeadlockError, lambda: self._create())

    def test_a_lock_timeout_on_the_audit_insert_does_not_fail_the_operation(self):
        """1205 only failed the best-effort audit INSERT: the mandate was created and stays so."""
        self.expectErrorLog("SEPA Audit Log Creation Error")
        mandate_id = f"M-2869-{frappe.generate_hash(length=8)}"
        with self._audit_enabled(), self._audit_insert_raising(frappe.QueryTimeoutError):
            result = self.manager.create_mandate(
                member=self.member.name,
                iban=self.iban,
                account_holder_name="Lock Err",
                mandate_id=mandate_id,
            )
        self.assertTrue(result.valid, result.message)
        self.assertTrue(frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id}))

    # -- T2: a database error that is NOT a lock error keeps the result contract -------------
    # (pins against the over-broad fix, "re-raise every DatabaseError", at each layer)

    def test_a_non_lock_database_error_in_the_manager_still_gives_a_failure_result(self):
        error = frappe.db.OperationalError
        with self._exists_raising(error):
            self.assertFalse(self._create().valid)
        with self._get_all_raising(error):
            self.assertFalse(self.manager.sync_member_mandates(self.member.name).valid)
            self.assertFalse(
                self.manager.deactivate_mandates_for_iban_change(self.member.name, self.iban).valid
            )

    def test_a_non_lock_driver_error_on_the_member_write_is_contained_at_each_layer(self):
        """OperationalError(1064) at the cursor on ``UPDATE tabMember``: the integration service
        reports ``success: False`` and the lifecycle layers return, none raises."""
        self.expectErrorLog("SEPA Mandate Member Integration Error")
        from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
            sepa_mandate_member_integration_service as integration,
        )

        mandate, service = self._saved_mandate(), self._lifecycle()
        with self._driver_raising_on(1064, "`tabMember`"):
            self.assertFalse(integration.update_member_mandate_relationship(mandate)["success"])
            self.assertTrue(service._update_member_mandate_status(mandate, "Active"))  # errors returned (#3101)
            mandate.status = "Active"
            self.assertIn("success", service.handle_status_transition(mandate, "Draft"))

    def test_a_non_lock_database_error_inside_the_lifecycle_service_is_contained(self):
        """Raised INSIDE the lifecycle layer (the integration service contains the member write
        itself), so the lifecycle handlers' own ``except Exception`` are what must catch it."""
        from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
            sepa_mandate_member_integration_service as integration,
        )

        def boom(*args, **kwargs):
            raise frappe.db.OperationalError("injected non-lock database error")

        mandate, service = self._saved_mandate(), self._lifecycle()
        mandate.status = "Active"
        mandate.cancellation_date = frappe.utils.today()
        for label, call in (
            ("update_member_mandate_status", lambda: service._update_member_mandate_status(mandate, "x")),
            ("handle_status_transition", lambda: service.handle_status_transition(mandate, "Draft")),
            ("process_mandate_cancellation", lambda: service.process_mandate_cancellation(mandate)),
            ("handle_mandate_creation", lambda: service.handle_mandate_creation(mandate)),
            ("handle_mandate_update", lambda: service.handle_mandate_update(mandate)),
        ):
            with self.subTest(label), patch.object(integration, "update_member_mandate_relationship", boom):
                self.expectErrorLog("SEPA Mandate Lifecycle")
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 - the assertion below names it
                    self.fail(f"{label}: a non-lock database error escaped as {type(exc).__name__}")
        for method, call in (
            ("send_mandate_status_notification", lambda: service.process_mandate_cancellation(mandate)),
            ("send_mandate_created_notification", lambda: service.handle_mandate_creation(mandate)),
            ("send_mandate_created_notification", lambda: service.handle_mandate_update(mandate)),
        ):
            with self.subTest(method), patch.object(
                self._notifier_class(), method, boom, create=True
            ):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 - the assertion below names it
                    self.fail(f"{method}: a non-lock database error escaped as {type(exc).__name__}")

    def _notifier_class(self):
        from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager

        return SEPAMandateNotificationManager

    def test_a_non_lock_driver_error_during_create_mandate_does_not_escape(self):
        self.expectErrorLog("SEPA Mandate Member Integration Error")
        with self._driver_raising_on(1064, "`tabMember`"):
            try:
                result = self._create()
            except Exception as exc:  # noqa: BLE001 - the assertion below names it
                self.fail(f"a non-lock database error escaped as {type(exc).__name__}: {exc}")
        self.assertIsNotNone(result)

    # -- T1: every lifecycle handler, one driver-level 1213 each -----------------------------

    def _saved_mandate(self):
        mandate_id = f"M-2869-{frappe.generate_hash(length=8)}"
        result = self.manager.create_mandate(
            member=self.member.name,
            iban=self.iban,
            account_holder_name="Lock Err",
            mandate_id=mandate_id,
        )
        self.assertTrue(result.valid, result.message)
        return frappe.get_doc("SEPA Mandate", {"mandate_id": mandate_id})

    def _lifecycle(self):
        from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
            SEPAMandateLifecycleService,
        )

        return SEPAMandateLifecycleService()

    def _assert_1213_propagates(self, call):
        with self._driver_raising_on(1213, "`tabMember`"):
            with self.assertRaises(frappe.QueryDeadlockError):
                call()

    def test_lifecycle_update_member_mandate_status_propagates(self):
        mandate, service = self._saved_mandate(), self._lifecycle()
        self._assert_1213_propagates(lambda: service._update_member_mandate_status(mandate, "Active"))

    def test_lifecycle_handle_status_transition_propagates_for_each_target_status(self):
        service = self._lifecycle()
        for old_status, new_status in (("Draft", "Active"), ("Active", "Cancelled"), ("Active", "Expired")):
            with self.subTest(new_status=new_status):
                mandate = self._saved_mandate()
                mandate.status = new_status
                # SEPA Mandate has no cancellation_date field, so _handle_cancellation's read of it
                # raises AttributeError (swallowed into the result) before reaching the member write
                mandate.cancellation_date = frappe.utils.today()
                self._assert_1213_propagates(lambda: service.handle_status_transition(mandate, old_status))

    def test_lifecycle_process_mandate_cancellation_propagates(self):
        mandate, service = self._saved_mandate(), self._lifecycle()
        mandate.status = "Active"
        self._assert_1213_propagates(lambda: service.process_mandate_cancellation(mandate, "test"))

    def test_lifecycle_handle_mandate_creation_propagates(self):
        mandate, service = self._saved_mandate(), self._lifecycle()
        self._assert_1213_propagates(lambda: service.handle_mandate_creation(mandate))

    def test_lifecycle_handle_mandate_update_propagates(self):
        mandate, service = self._saved_mandate(), self._lifecycle()
        self._assert_1213_propagates(lambda: service.handle_mandate_update(mandate))

    def _notifier_raising(self, method):
        from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager

        def raiser(*args, **kwargs):
            raise frappe.QueryDeadlockError("injected in the notification")

        # Mock justified: fault injection into the notification step only
        return patch.object(SEPAMandateNotificationManager, method, raiser, create=True)

    def test_lifecycle_notification_steps_propagate(self):
        service = self._lifecycle()
        mandate = self._saved_mandate()
        mandate.status = "Active"
        with self._notifier_raising("send_mandate_status_notification"):
            with self.assertRaises(frappe.QueryDeadlockError):
                service.process_mandate_cancellation(mandate, "test")
        mandate = self._saved_mandate()
        mandate.status = "Active"
        with self._notifier_raising("send_mandate_created_notification"):
            with self.assertRaises(frappe.QueryDeadlockError):
                service.handle_mandate_creation(mandate)
        with self._notifier_raising("send_mandate_created_notification"):
            with self.assertRaises(frappe.QueryDeadlockError):
                service.handle_mandate_update(mandate)

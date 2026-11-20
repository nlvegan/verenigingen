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

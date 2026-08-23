"""`SingletonBackup.restore()` must put a Single back even when its controller
would reject that state on save (#537).

Measured on PR #525 (43/43 green, so this is `develop`, not a regression): across
all twelve shard logs there are **34** `Failed to restore` lines and every one of
them is `Failed to restore Ponto Settings: Sandbox Client ID is required when
Sandbox Mode is enabled`. No other doctype appears, and there are no
`Failed to backup` or `No backup found` lines at all. The restore went through
`doc.save()`, which gave `validate()` a veto over putting back a state that had
**already been persisted**.

The state it cannot put back is `Ponto Settings`' own factory default:
`sandbox_mode` carries `"default": "1"` and `sandbox_client_id` carries none, so
on a fresh site the very first `backup()` captures a state `doc.save()` rejects.
Nothing a test did wrong is required.

The consequence is not noise. `tests/sepa/test_ponto_client._setup_test_settings`
commits `sandbox_client_id = "test_client_id"`; the restore is swallowed; the
literal stays in the Single. Both `test_site_3` and the live site were measured
carrying exactly that value, and outside test mode
`PontoSettings.validate_no_test_credentials` then throws on it -- so the leaked
state also makes the Single unsavable through the UI.

These tests drive a real `FrappeTestCase` through `unittest`, the way
`test_harness_settings_restoration._run_case` does, because the property that
matters is class-scoped: the Single is back to its pre-class value once
`tearDownClass` has returned. A test that called `restore()` directly would also
pass against a version whose `frappe.db.commit()` was missing, and that commit is
load-bearing -- `FrappeTestCase` registers `_rollback_db` as a class cleanup.

These tests mutate a Single and commit; `setUp` snapshots its entire `tabSingles`
row set plus the Password field from `__Auth`, and `addCleanup` writes both back
and commits. Whole row set rather than the fields written, for the reason given
there.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from verenigingen.tests.fixtures.singleton_backup import SingletonBackup

DT = "Ponto Settings"
LEAKED_ID = "test_client_id"
LEAKED_SECRET = "leaked-secret-537"
PASSWORD_FIELD = "sandbox_client_secret"


def _raw(field):
    """Read straight out of `tabSingles`.

    `frappe.db.get_single_value` memoises on `frappe.local`, so it can report the
    pre-restore value; the row is the only ground truth here.
    """
    row = frappe.db.sql("select value from tabSingles where doctype=%s and field=%s", (DT, field))
    return row[0][0] if row else None


class TestSingletonBackupRestoresAStateSaveWouldReject(unittest.TestCase):
    def setUp(self):
        # The WHOLE row set, not the fields this test means to touch. Two reasons,
        # both measured. A Single with zero rows in `tabSingles` gets its declared
        # defaults applied (`Document.load_from_db` only calls `new_doc` when
        # `not single_doc`); write even one row and every other field reads as
        # None instead. So planting two rows on a fresh CI site would flip the
        # doctype to partial-row semantics, the nested `backup()` would capture
        # None for the other ~35 fields, and `restore()` would materialise them --
        # leaving e.g. `require_webhook_signature` at 0 against its declared
        # default of 1 for the rest of the shard. Restoring only the two fields
        # this test writes cannot undo that. Taking the whole row set also puts
        # back the Password field's star placeholder, whose LENGTH the nested
        # class's save() rewrites.
        self._rows = frappe.db.sql("select field, value from tabSingles where doctype=%s", DT)
        self._snapshot_secret = get_decrypted_password(DT, DT, PASSWORD_FIELD, raise_exception=False)
        self.addCleanup(self._restore_site_state)

    def _restore_site_state(self):
        frappe.db.sql("delete from tabSingles where doctype=%s", DT)
        for field, value in self._rows:
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, %s, %s)",
                (DT, field, value),
            )
        if self._snapshot_secret:
            set_encrypted_password(DT, DT, self._snapshot_secret, fieldname=PASSWORD_FIELD)
        else:
            frappe.db.sql(
                "delete from `__Auth` where doctype=%s and name=%s and fieldname=%s",
                (DT, DT, PASSWORD_FIELD),
            )
        frappe.clear_document_cache(DT, DT)
        frappe.db.commit()

    def _set_state(self, client_id, secret=None):
        """Establish the pre-class state, committed, without going through save().

        `set_single_value` is used deliberately: the whole point of the failing
        case is that `doc.save()` cannot produce it.
        """
        frappe.db.set_single_value(DT, {"sandbox_mode": 1, "sandbox_client_id": client_id})
        if secret is not None:
            set_encrypted_password(DT, DT, secret, fieldname=PASSWORD_FIELD)
        frappe.clear_document_cache(DT, DT)
        frappe.db.commit()

    def _run_a_class_that_leaks(self, also_set_secret=False, plant_caches=None):
        """Run a real class shaped like the eight modules that hit this.

        backup() in setUpClass, a committed mutation in the body, restore() in
        tearDownClass -- and the mutation is the verbatim one from
        `test_ponto_client._setup_test_settings`.
        """
        seen = {}

        class _Case(FrappeTestCase):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                cls._singleton_backup = SingletonBackup(DT)
                cls._singleton_backup.backup()

            @classmethod
            def tearDownClass(cls):
                cls._singleton_backup.restore()
                super().tearDownClass()

            def test_body(inner):
                settings = frappe.get_single(DT)
                settings.sandbox_mode = 1
                settings.sandbox_client_id = LEAKED_ID
                if also_set_secret:
                    settings.sandbox_client_secret = LEAKED_SECRET
                settings.save()
                frappe.db.commit()
                seen["during"] = _raw("sandbox_client_id")
                # AFTER the last save, because that save fires on_update and
                # clears these itself -- planting them earlier made the cache
                # assertions pass with the invalidation deleted. This is also the
                # real shape: test_ponto_client plants the token key once and
                # never saves again.
                if plant_caches:
                    plant_caches()

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_Case).run(result)
        self.assertEqual(result.errors, [], f"the nested class errored: {result.errors}")
        self.assertEqual(result.failures, [], f"the nested class failed: {result.failures}")
        frappe.clear_document_cache(DT, DT)
        return seen

    def test_the_precondition_is_a_state_that_save_rejects(self):
        """Guards the guard: without this the failing test could go vacuous.

        If `validate_credentials_configured` were relaxed, the state below would
        become savable and the test underneath would pass against the unfixed
        restore. This is also the state a fresh site starts in --
        `sandbox_mode` defaults to 1 and `sandbox_client_id` to nothing.

        Matched on the message, not just the exception class: a `validate()` that
        started throwing for some unrelated reason would keep this green while the
        premise it guards had silently changed. No rollback afterwards -- a
        `validate()` throw on a Single writes nothing, and a bare
        `frappe.db.rollback()` from a plain `unittest.TestCase` body would discard
        whatever uncommitted work the process is carrying (#433).
        """
        self._set_state(None)

        doc = frappe.get_single(DT)
        with self.assertRaisesRegex(frappe.ValidationError, "Sandbox Client ID"):
            doc.save()

    def test_a_state_save_rejects_is_restored_anyway(self):
        """The defect. `sandbox_client_id` was empty and must be empty again."""
        self._set_state(None)

        seen = self._run_a_class_that_leaks()

        self.assertEqual(
            seen["during"],
            LEAKED_ID,
            "the nested class never actually changed the single, so this proves nothing",
        )
        self.assertIn(
            _raw("sandbox_client_id"),
            (None, ""),
            "SingletonBackup left the test's credential in Ponto Settings: restore() "
            "went through doc.save(), whose validate() rejects the state that was "
            "captured -- see #537",
        )

    def test_a_state_save_accepts_is_restored(self):
        """The control. Distinguishes 'restore works' from 'restore is quiet'."""
        self._set_state("pristine-client-id")

        seen = self._run_a_class_that_leaks()

        self.assertEqual(seen["during"], LEAKED_ID)
        self.assertEqual(_raw("sandbox_client_id"), "pristine-client-id")

    def test_the_password_field_is_restored_too(self):
        """A Password field lives in `__Auth`, not in `tabSingles`.

        `tabSingles` holds only a `***` placeholder for one, so the row proves
        nothing and only the decrypted value discriminates. Two ways to fail
        this: a bypass that writes captured values to `tabSingles` and forgets
        `set_encrypted_password`, or -- the current defect -- an exception on the
        field pass that aborts before the password pass is reached. Hence the
        unsavable state here as well.
        """
        self._set_state(None, secret="pristine-secret-537")

        self._run_a_class_that_leaks(also_set_secret=True)

        self.assertEqual(
            get_decrypted_password(DT, DT, PASSWORD_FIELD, raise_exception=False),
            "pristine-secret-537",
            "the Password field was not restored from __Auth",
        )

    def test_the_caches_keyed_off_the_single_are_dropped(self):
        """Restoring the row is not enough while a stale cache still answers.

        `PontoSettings.on_update` is nothing but these two cache drops, and going
        round `doc.save()` skipped it. `test_ponto_client` plants the token key in
        SHARED redis with a 3600s TTL and never clears it, so losing this would
        trade one contamination vector for another (#537 review).
        """
        from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
            PontoConfigurationService,
        )
        from verenigingen.verenigingen_payments.ponto.utils.token_manager import PontoTokenManager

        self._set_state("pristine-client-id")
        cache = frappe.cache()

        def plant():
            cache.set_value(PontoConfigurationService.CACHE_KEY, {"probe": 1})
            cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "PROBE-TOKEN")

        self._run_a_class_that_leaks(plant_caches=plant)
        self.addCleanup(PontoTokenManager.clear_cache)
        self.addCleanup(PontoConfigurationService.clear_cache)

        self.assertIsNone(
            cache.get_value(PontoConfigurationService.CACHE_KEY),
            "the config cache still holds a value the restored row disagrees with",
        )
        self.assertIsNone(
            cache.get_value(PontoTokenManager.TOKEN_CACHE_KEY),
            "the OAuth token cache outlived the class that planted it",
        )

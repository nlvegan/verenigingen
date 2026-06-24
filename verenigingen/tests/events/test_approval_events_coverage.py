"""
Integration coverage for the member-approval event chain.

Covers:
  * ``verenigingen/events/approval_events.py`` -- emitters + registry + dispatch
  * ``verenigingen/events/subscribers/approval_subscribers.py`` -- the six
    ``handle_*`` background-job handlers + ``get_approval_background_job_status``
  * the shared dispatch core ``verenigingen/events/event_emitter.py``

Every subscriber wraps its body in ``try/except: frappe.log_error()`` and swallows,
so a "must not raise" smoke test is worthless -- a broken handler would still pass.
Two techniques are used throughout:

1. ``self.assertNoErrorLog()`` around the happy path (frappe.log_error commits
   outside the test transaction, so a swallowed exception flips a silent green
   into a real failure), combined with an assertion on the REAL side effect
   (Customer row created, Volunteer activated, ...).
2. ``frappe.flags.run_events_synchronously`` makes ``emit_event`` call the real
   subscribers inline (instead of enqueueing with a delay) so the emitter ->
   registry -> subscriber chain can be exercised end-to-end.
"""

from contextlib import contextmanager

import frappe

from verenigingen.events import approval_events as ae
from verenigingen.events.event_emitter import emit_event
from verenigingen.events.subscribers import approval_subscribers as asub
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestApprovalEventsCoverage(EnhancedTestCase):
    """Real integration coverage for the approval event system."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _events_sync(self):
        """Run emitted subscribers inline instead of enqueueing them."""
        prev = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True
        try:
            yield
        finally:
            frappe.flags.run_events_synchronously = prev

    def _make_member(self, **kwargs):
        defaults = dict(first_name="Appr", last_name="Member", birth_date="1990-01-01")
        defaults.update(kwargs)
        return self.create_test_member(**defaults)

    # ====================================================================
    # emit_member_approval_initiated / completed -- guard + payload
    # ====================================================================
    def test_emit_initiated_no_member_is_noop(self):
        """Falsy member_name returns before touching the event bus (no error, no enqueue)."""
        with self.assertNoErrorLog():
            self.assertIsNone(ae.emit_member_approval_initiated(None, {}))
            self.assertIsNone(ae.emit_member_approval_initiated("", {"chapter": "X"}))

    def test_emit_completed_no_member_is_noop(self):
        with self.assertNoErrorLog():
            self.assertIsNone(ae.emit_member_approval_completed(None, {}))

    def test_emit_initiated_builds_full_payload_and_dispatches_to_registry(self):
        """The initiated emitter forwards a complete payload to EXACTLY the four
        initiated-event subscribers in the registry."""
        member = self._make_member()
        captured = {}

        def fake_emit(event_name, event_data, subscribers, **kw):
            captured["event_name"] = event_name
            captured["event_data"] = event_data
            captured["subscribers"] = subscribers
            captured["kw"] = kw

        # _emit_approval_event imports emit_event lazily from the emitter module,
        # so patch it at the source the function resolves.
        import verenigingen.events.event_emitter as ee

        ee.emit_event, saved = fake_emit, ee.emit_event
        try:
            with self.assertNoErrorLog():
                ae.emit_member_approval_initiated(
                    member.name,
                    {"membership_type": "MT", "chapter": "CH", "notes": "hi", "create_invoice": False},
                )
        finally:
            ee.emit_event = saved

        self.assertEqual(captured["event_name"], "member_approval_initiated")
        data = captured["event_data"]
        self.assertEqual(data["member"], member.name)
        self.assertEqual(data["membership_type"], "MT")
        self.assertEqual(data["chapter"], "CH")
        self.assertEqual(data["notes"], "hi")
        self.assertEqual(data["create_invoice"], False)
        self.assertEqual(data["approved_by"], frappe.session.user)
        self.assertIn("approval_timestamp", data)
        # Registry: exactly the four initiated subscribers, in order.
        self.assertEqual(
            captured["subscribers"],
            [
                "verenigingen.events.subscribers.approval_subscribers.handle_customer_creation",
                "verenigingen.events.subscribers.approval_subscribers.handle_chapter_assignment",
                "verenigingen.events.subscribers.approval_subscribers.handle_iban_history_creation",
                "verenigingen.events.subscribers.approval_subscribers.handle_user_account_creation",
            ],
        )
        self.assertEqual(captured["kw"].get("entity_key"), "member")
        self.assertEqual(captured["kw"].get("job_prefix"), "approval")

    def test_emit_completed_payload_and_registry(self):
        member = self._make_member()
        captured = {}
        import verenigingen.events.event_emitter as ee

        ee.emit_event, saved = (
            lambda en, ed, subs, **kw: captured.update(en=en, ed=ed, subs=subs)
        ), ee.emit_event
        try:
            with self.assertNoErrorLog():
                ae.emit_member_approval_completed(
                    member.name, {"invoice": "INV-1", "user_account_status": "ok"}
                )
        finally:
            ee.emit_event = saved

        self.assertEqual(captured["en"], "member_approval_completed")
        self.assertEqual(captured["ed"]["invoice"], "INV-1")
        self.assertEqual(captured["ed"]["user_account_status"], "ok")
        self.assertEqual(
            captured["subs"],
            [
                "verenigingen.events.subscribers.approval_subscribers.handle_approval_notification",
                "verenigingen.events.subscribers.approval_subscribers.handle_volunteer_activation",
            ],
        )

    def test_registry_unknown_event_returns_empty(self):
        self.assertEqual(ae._get_approval_event_subscribers("does_not_exist"), [])

    def test_emitter_swallows_dispatch_exception(self):
        """If the dispatch core blows up, the emitter logs and does NOT propagate
        (event emission must never block the approval transaction)."""
        member = self._make_member()
        import verenigingen.events.event_emitter as ee

        def boom(*a, **k):
            raise RuntimeError("dispatch exploded")

        ee.emit_event, saved = boom, ee.emit_event
        # expectErrorLog registers the title so the automatic tearDown check
        # ignores it (the emitter is SUPPOSED to log here). It is not a context
        # manager. We assert the call returns normally (does not propagate).
        self.expectErrorLog("Approval Event Emission Error")
        try:
            before = frappe.db.count("Error Log")
            self.assertIsNone(ae.emit_member_approval_initiated(member.name, {}))
            # The dispatch exception was swallowed AND logged.
            self.assertEqual(frappe.db.count("Error Log"), before + 1)
        finally:
            ee.emit_event = saved

    # ====================================================================
    # event_emitter.emit_event core
    # ====================================================================
    def test_emit_event_run_sync_calls_subscriber_inline(self):
        """With run_events_synchronously the subscriber executes inline (no enqueue)."""
        calls = []

        def _probe(event_name=None, event_data=None, **kw):
            calls.append((event_name, event_data))

        # Register the probe under a real dotted path so frappe.call can resolve it.
        path = f"{__name__}._sync_probe"
        globals()["_sync_probe"] = _probe
        with self._events_sync():
            with self.assertNoErrorLog():
                emit_event(
                    "probe_event",
                    {"member": "M-1"},
                    [path],
                    entity_key="member",
                    job_prefix="probe",
                )
        self.assertEqual(calls, [("probe_event", {"member": "M-1"})])

    def test_emit_event_enqueues_when_not_sync(self):
        """Outside sync mode the subscriber is enqueued (not called inline)."""
        calls = []
        path = f"{__name__}._enqueue_probe"
        globals()["_enqueue_probe"] = lambda **kw: calls.append(kw)
        enqueued = {}

        import verenigingen.events.event_emitter as ee

        def fake_enqueue(method=None, **kw):
            enqueued["method"] = method
            enqueued["job_name"] = kw.get("job_name")
            enqueued["delay"] = kw.get("delay")

        ee.frappe.enqueue, saved = fake_enqueue, ee.frappe.enqueue
        try:
            emit_event("evt", {"member": "M-9"}, [path], entity_key="member", job_prefix="px", delay=5)
        finally:
            ee.frappe.enqueue = saved
        self.assertEqual(calls, [])  # NOT called inline
        self.assertEqual(enqueued["method"], path)
        self.assertEqual(enqueued["job_name"], "px_evt_M-9")
        self.assertEqual(enqueued["delay"], 5)

    # ====================================================================
    # handle_customer_creation
    # ====================================================================
    def test_handle_customer_creation_creates_real_customer(self):
        """End-to-end: handler (re)creates/links a Customer on the Member.

        The Enhanced factory auto-creates a Customer for every Member, so we
        clear the link first to force the handler down its creation branch and
        assert a real Customer ends up linked.
        """
        member = self._make_member(first_name="Cust")
        member.db_set("customer", None, update_modified=False)
        member.reload()
        self.assertFalse(member.customer)

        with self.assertNoErrorLog():
            result = asub.handle_customer_creation("member_approval_initiated", {"member": member.name})

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "created")
        member.reload()
        self.assertTrue(member.customer, "Member.customer should be set after handler")
        self.assertTrue(frappe.db.exists("Customer", member.customer))

    def test_handle_customer_creation_idempotent_when_customer_exists(self):
        """Second call short-circuits to 'already_exists' (idempotency)."""
        member = self._make_member(first_name="Cust2")
        with self.assertNoErrorLog():
            asub.handle_customer_creation("e", {"member": member.name})
        member.reload()
        existing = member.customer
        self.assertTrue(existing)
        with self.assertNoErrorLog():
            result = asub.handle_customer_creation("e", {"member": member.name})
        self.assertEqual(result["action"], "already_exists")
        self.assertEqual(result["customer"], existing)

    def test_handle_customer_creation_no_member_key_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(asub.handle_customer_creation("e", {}))

    # ====================================================================
    # handle_chapter_assignment
    # ====================================================================
    def test_handle_chapter_assignment_skips_without_chapter(self):
        member = self._make_member()
        with self.assertNoErrorLog():
            result = asub.handle_chapter_assignment("e", {"member": member.name})
        self.assertEqual(result["action"], "skipped")

    def test_handle_chapter_assignment_skips_without_member(self):
        with self.assertNoErrorLog():
            result = asub.handle_chapter_assignment("e", {"chapter": "X"})
        self.assertEqual(result["action"], "skipped")

    def test_handle_chapter_assignment_nonexistent_member_logs_error(self):
        """A missing Member makes get_doc raise; the handler swallows + logs +
        returns success=False (documented failure branch)."""
        # expectErrorLog registers the expected title for the tearDown check.
        self.expectErrorLog("Approval Background Job Error")
        before = frappe.db.count("Error Log")
        result = asub.handle_chapter_assignment(
            "e", {"member": "Member-does-not-exist-zzz", "chapter": "Some-Chapter"}
        )
        self.assertFalse(result["success"])
        # Proves the swallow-and-log failure branch actually fired.
        self.assertEqual(frappe.db.count("Error Log"), before + 1)

    # ====================================================================
    # handle_iban_history_creation
    # ====================================================================
    def test_handle_iban_history_no_member_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(asub.handle_iban_history_creation("e", {}))

    def test_handle_iban_history_member_without_iban(self):
        """A member with no IBAN: create_member_iban_history is a clean no-op
        (success True, nothing logged)."""
        member = self._make_member()
        # ensure no iban
        member.db_set("iban", None, update_modified=False)
        with self.assertNoErrorLog():
            result = asub.handle_iban_history_creation("e", {"member": member.name})
        self.assertTrue(result["success"])

    def test_handle_iban_history_nonexistent_member_returns_failure(self):
        """get_doc raises for a missing member; handler returns success=False.
        This handler does NOT log_error (it treats failure as non-critical)."""
        with self.assertNoErrorLog():
            result = asub.handle_iban_history_creation("e", {"member": "Member-missing-iban-xyz"})
        self.assertFalse(result["success"])
        self.assertEqual(result["critical"], False)

    # ====================================================================
    # handle_user_account_creation
    # ====================================================================
    def test_handle_user_account_creation_no_member_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(asub.handle_user_account_creation("e", {}))

    def test_handle_user_account_creation_nonexistent_member_returns_failure(self):
        """Missing member -> success=False, non-critical, no Error Log row."""
        with self.assertNoErrorLog():
            result = asub.handle_user_account_creation("e", {"member": "Member-no-user-xyz"})
        self.assertFalse(result["success"])
        self.assertEqual(result["critical"], False)

    # ====================================================================
    # handle_approval_notification
    # ====================================================================
    def test_handle_approval_notification_no_member_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(asub.handle_approval_notification("e", {}))

    def test_handle_approval_notification_nonexistent_member_returns_failure(self):
        with self.assertNoErrorLog():
            result = asub.handle_approval_notification("e", {"member": "Member-notify-missing"})
        self.assertFalse(result["success"])
        self.assertEqual(result["critical"], False)

    # ====================================================================
    # handle_volunteer_activation
    # ====================================================================
    def test_handle_volunteer_activation_skipped_when_not_interested(self):
        """interested_in_volunteering falsy -> skipped, no volunteer touched."""
        member = self._make_member()
        member.db_set("interested_in_volunteering", 0, update_modified=False)
        with self.assertNoErrorLog():
            result = asub.handle_volunteer_activation("e", {"member": member.name})
        self.assertEqual(result["action"], "skipped")

    def test_handle_volunteer_activation_activates_real_volunteer(self):
        """End-to-end: an interested member with a (non-active) volunteer record
        gets that volunteer set to Active."""
        member = self._make_member(first_name="VolAct")
        member.db_set("interested_in_volunteering", 1, update_modified=False)
        volunteer = self.create_test_volunteer(member_name=member.name)
        # Force a non-active starting state so the activation is observable.
        volunteer.db_set("status", "New", update_modified=False)
        member.reload()

        result = asub.handle_volunteer_activation("e", {"member": member.name})

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "volunteer_activated")
        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "status"), "Active")

    def test_handle_volunteer_activation_no_member_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(asub.handle_volunteer_activation("e", {}))

    # ====================================================================
    # get_approval_background_job_status
    # ====================================================================
    def test_job_status_requires_member(self):
        self.assertIn("error", asub.get_approval_background_job_status(None))

    def test_job_status_shape_for_member(self):
        member = self._make_member()
        status = asub.get_approval_background_job_status(member.name)
        self.assertEqual(status["member"], member.name)
        for key in ("active_jobs", "completed_jobs", "failed_jobs", "jobs"):
            self.assertIn(key, status)
        self.assertEqual(set(status["jobs"].keys()), {"active", "completed", "failed"})

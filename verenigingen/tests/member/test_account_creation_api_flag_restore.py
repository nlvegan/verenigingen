"""#2559: the account-creation endpoints raise frappe.flags and must put them back.

``process_account_creation_request``, ``queue_bulk_account_creation_for_members``,
``process_bulk_account_creation_batch`` and ``retry_all_failed_requests`` set
``in_background_job`` / ``bulk_account_creation`` / ``in_import`` for the work they do.
In an RQ job that dies with the job's ``frappe.local``; in a long-lived process (a test
run, ``bench execute``, a synchronous caller) it stayed set and ``in_import`` silently
switched off defaults, Select validation and User-creation throttling for later work.

What is asserted, for each endpoint and for the early-return, failure and propagating-raise
exits: the flags are back to what the CALLER had. A flag that was True before the call must
still be True afterwards (a ``finally: flag = False`` fix fails that), and a flag that was
absent must be absent again.
"""

from unittest.mock import patch

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase

FLAGS = ("in_background_job", "bulk_account_creation", "in_import")


class _Boom(BaseException):
    """Not an Exception, so the endpoints' own ``except Exception`` cannot absorb it."""


def _snapshot():
    return {name: (name in frappe.flags, frappe.flags.get(name)) for name in FLAGS}


class TestAccountCreationFlagRestore(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        original = _snapshot()
        self.addCleanup(self._put_back, original)
        for name in FLAGS:
            frappe.flags.pop(name, None)

    @staticmethod
    def _put_back(original):
        for name, (present, value) in original.items():
            if present:
                frappe.flags[name] = value
            else:
                frappe.flags.pop(name, None)

    def _assert_unset(self):
        self.assertEqual(_snapshot(), {name: (False, None) for name in FLAGS})

    # --- the four endpoints, each driven down a real exit -------------------------

    def _process_request_missing(self):
        return api.process_account_creation_request("ACR-Member-9999-99-99-deadbeefdead")

    def _queue_bulk_no_valid_members(self):
        return api.queue_bulk_account_creation_for_members(["MEM-does-not-exist-2559"])

    def _process_batch_not_found(self):
        return api.process_bulk_account_creation_batch(
            request_names=["ACR-Member-9999-99-99-cafebabe0000"],
            batch_id="flags_2559",
            batch_number=1,
            tracker_name="no-such-tracker-2559",
        )

    def _a_failed_request(self):
        """A real Account Creation Request, forced to Failed with a reason no filter below matches.

        PROBE SHORTCUT: ``status`` / ``failure_reason`` / ``retry_count`` are written with
        ``db.set_value`` instead of driving a pipeline failure. Only the endpoint's own flag
        handling is under test, not how a request comes to fail.
        """
        uid = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Flags2559",
            last_name=f"Member{uid}",
            email=f"flags2559.{uid}@test.invalid",
            status="Active",
        )
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": member.email,
                "full_name": member.full_name,
                "priority": "Normal",
                "role_profile": "Verenigingen Member",
                "business_justification": "test",
                "requested_roles": [{"role": "Verenigingen Member"}],
            }
        ).insert()
        self.track_doc("Account Creation Request", request.name)
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "unrelated 2559", "retry_count": 0},
        )

    def _retry_all_with_nothing_matching(self):
        # The employee_exists filter drops the row above, so nothing is retried; the endpoint
        # still gets past its "no failed requests" early return and sets the flag.
        self._assert_no_stale_employee_exists_failures()
        self._a_failed_request()
        return api.retry_all_failed_requests(failure_type="employee_exists")

    def _assert_no_stale_employee_exists_failures(self):
        """The endpoint retries EVERY Failed request (retry_count < 3) the filter selects, not only
        ours: a stale row mentioning "already assigned to Employee" would get a real
        ``retry_processing()`` and an enqueued job. Refuse to run rather than touch it.
        (Chosen over a filter that selects nothing: every ``failure_type`` either applies a
        filter that can match site rows, or none, which selects them all.)"""
        stale = frappe.get_all(
            "Account Creation Request",
            filters={
                "status": "Failed",
                "retry_count": ["<", 3],
                "failure_reason": ["like", "%already assigned to Employee%"],
            },
            pluck="name",
        )
        self.assertEqual(stale, [], "stale Failed ACRs on this site would be retried by the test")

    def _exits(self):
        return {
            "process_account_creation_request": self._process_request_missing,
            "queue_bulk_account_creation_for_members": self._queue_bulk_no_valid_members,
            "process_bulk_account_creation_batch": self._process_batch_not_found,
            "retry_all_failed_requests": self._retry_all_with_nothing_matching,
        }

    def test_flags_are_unset_after_a_normal_call(self):
        for label, call in self._exits().items():
            with self.subTest(endpoint=label):
                call()
                self._assert_unset()

    def test_flags_are_unset_after_the_function_raises(self):
        # Mock justified: Infrastructure - force an exit that propagates out of the endpoint.
        patches = {
            "process_account_creation_request": patch.object(api, "AccountCreationManager", side_effect=_Boom),
            "queue_bulk_account_creation_for_members": patch(
                "verenigingen.services.account.account_creation_service.get_account_creation_service",
                side_effect=_Boom,
            ),
            "process_bulk_account_creation_batch": patch(
                "concurrent.futures.ThreadPoolExecutor", side_effect=_Boom
            ),
        }
        calls = self._exits()
        for label, patcher in patches.items():
            with self.subTest(endpoint=label):
                with patcher, self.assertRaises(_Boom):
                    calls[label]()
                self._assert_unset()

        with self.subTest(endpoint="retry_all_failed_requests"):
            self._a_failed_request()
            # Mock justified: Infrastructure - raise from the first statement after the flag is set.
            with patch.object(frappe, "logger", side_effect=_Boom), self.assertRaises(_Boom):
                api.retry_all_failed_requests(failure_type="employee_exists")
            self._assert_unset()

    def test_a_flag_the_caller_already_set_is_still_set_afterwards(self):
        for label, call in self._exits().items():
            with self.subTest(endpoint=label):
                frappe.flags.in_import = True
                frappe.flags.in_background_job = False
                call()
                self.assertTrue(frappe.flags.get("in_import"))
                self.assertIs(frappe.flags.get("in_background_job"), False)
                self.assertNotIn("bulk_account_creation", frappe.flags)
                for name in FLAGS:
                    frappe.flags.pop(name, None)

    def _record(self, seen):
        seen.update({name: frappe.flags.get(name) for name in FLAGS})

    def _flags_seen_inside(self, label):
        """Run endpoint ``label`` and return the flags as seen from a call it makes AFTER setting them."""
        seen = {}
        record = lambda: self._record(seen)  # noqa: E731

        if label == "process_account_creation_request":

            class Spy:
                cancelled = False

                def __init__(self, request_name):
                    pass

                def process_complete_pipeline(self):
                    record()

            # Mock justified: Infrastructure - observe the flags from inside the pipeline.
            with patch.object(api, "AccountCreationManager", Spy):
                api.process_account_creation_request("ACR-spy-2559")
        elif label == "queue_bulk_account_creation_for_members":

            class Service:
                def queue_bulk_requests(self, **kwargs):
                    record()
                    return {}

            # Mock justified: Infrastructure - observe the flags from inside the service call.
            with patch(
                "verenigingen.services.account.account_creation_service.get_account_creation_service",
                return_value=Service(),
            ):
                api.queue_bulk_account_creation_for_members(["MEM-spy-2559"])
        elif label == "process_bulk_account_creation_batch":

            def spy_executor(*args, **kwargs):
                record()
                raise _Boom

            # Mock justified: Infrastructure - observe the flags when the executor is created.
            with patch("concurrent.futures.ThreadPoolExecutor", side_effect=spy_executor):
                with self.assertRaises(_Boom):
                    self._process_batch_not_found()
        else:
            self._assert_no_stale_employee_exists_failures()
            self._a_failed_request()
            real_logger = frappe.logger

            def spy_logger(*args, **kwargs):
                record()
                return real_logger(*args, **kwargs)

            # Mock justified: Infrastructure - first call the endpoint makes after setting its flag.
            with patch.object(frappe, "logger", side_effect=spy_logger):
                api.retry_all_failed_requests(failure_type="employee_exists")
        return seen

    def test_each_endpoint_sets_its_own_flags_while_it_runs(self):
        """Control: restoring must not have been achieved by never setting them. Each endpoint's OWN
        set is asserted (queue: bulk + background, no in_import; retry_all: bulk only)."""
        expected = {
            "process_account_creation_request": {"in_background_job", "bulk_account_creation", "in_import"},
            "queue_bulk_account_creation_for_members": {"in_background_job", "bulk_account_creation"},
            "process_bulk_account_creation_batch": {"in_background_job", "bulk_account_creation", "in_import"},
            "retry_all_failed_requests": {"bulk_account_creation"},
        }
        for label, names in expected.items():
            with self.subTest(endpoint=label):
                seen = self._flags_seen_inside(label)
                self.assertEqual({n for n, v in seen.items() if v is True}, names)
                self._assert_unset()

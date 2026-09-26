"""#1411 class sweep: frappe.has_permission(doctype, ptype, name)'s
DoesNotExistError-vs-False asymmetry, beyond #1401's Team fix.

frappe.has_permission(doctype, ptype, name) loads the named document internally
(frappe.get_lazy_doc) before consulting the permission tables whenever `name` is
a raw string/int rather than an already-loaded Document object. That load raises
frappe.DoesNotExistError for an unknown name, while the identical call returns
plain False for a real-but-forbidden one -- two different outcomes for the
identical "can I access this id" question, for any non-Administrator caller who
clears the endpoint's own security tier.

#1411's census found this idiom repeated, uncaught, at several more call sites
after #1401 (PR #1416) fixed it for Team. This file covers:

- The shared helper itself (verenigingen.utils.security.permission_existence_guard.
  permission_allowed_without_oracle), extracted so every site below -- and
  verenigingen.api.team_management._require_team_permission -- shares one
  implementation instead of a fourth copy of the same few lines.
- verenigingen.utils.address_formatter.format_member_address (2 call sites: Member,
  then the member's Address).
- verenigingen.utils.member_performance_optimizer.get_member_dashboard (the
  `throw=True` shape -- throw=True only changes the False-case behaviour; the
  DoesNotExistError from the internal document load happens before that check
  and was unaffected by it).
- The 9 Chapter-name guards across verenigingen/email/{advanced_segmentation,
  automated_campaigns,simplified_email_manager,newsletter_templates}.py, which
  all share one 2-line idiom. Two representative call sites are exercised
  end-to-end here (one "read" gate, one "write" gate); the other 7 were verified
  by grep to use byte-identical logic (see the class sweep in the PR description),
  not independently dispatched.

Not touched by this PR (see PR description / issue #1411 comment for the full
per-row reachability writeup): dues_schedule_repository.py (internal
repository methods; every traced caller -- member_merge_service.py,
membership.py, contribution_amendment_request.py, and
contribution_amendment_approval_service.py -- either calls a DIFFERENT,
unguarded method (get_schedules_for_members/get_active_schedule) or passes a
schedule name already confirmed to exist immediately before the call; none
reaches any of the 5 guarded methods with a caller-supplied unchecked name),
member_history_integrity.py (self.member is already a loaded Document, not a
raw name -- frappe.has_permission never reloads it, so the census's
classification there does not hold), services/infrastructure/base_service.py:421
(APIService has zero subclasses in the app -- dead code),
services/billing/invoice_generator.py (self.schedule is an already-loaded,
already-validated Document; member_name/schedule_name are its own
confirmed-to-exist fields), and member_duplicate_detection_service.py:460
(existence is checked explicitly via frappe.db.exists BEFORE the permission
check, so frappe.has_permission never sees an unknown name here at all -- a
different, already-mitigated mechanism).

DISCLOSURE (frappe 16.35, this bench -- matching test_core_client_permission_
oracle.py's identical disclosure for #1436): the nested has_permission(doc.
doctype) call frappe.permissions.has_permission makes internally, to decide
whether to name the document in its own diagnostic, now passes print_logs=
False explicitly, so it queues nothing on the FORBIDDEN path on this Frappe
version. None of this file's scenarios independently queues a message on
that path either. So every *_message_log_has_no_residue /
message_log_trimmed_symmetric test here was measured (by mutating the
helper's `finally: del frappe.message_log[log_len:]` to a bare
`frappe.clear_last_message()` inside the except branch only, dropping the
unconditional trim) to stay 14/14 GREEN even without the length-trim this
file's helper performs -- because message_log is already empty on the
forbidden path regardless, on THIS Frappe version. These tests are therefore
a REGRESSION GUARD on 16.35, not a red/green discriminator for the trim vs.
clear_last_message() choice: they protect against a FUTURE Frappe version (or
an added hook) reopening the leak the trim exists to close, exactly as
frappe/permissions.py did on 16.30.
"""

from unittest import mock

import frappe
from frappe import _

from verenigingen.email.advanced_segmentation import get_segment_suggestions
from verenigingen.email.simplified_email_manager import SimplifiedEmailManager, send_chapter_email
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.address_formatter import format_member_address
from verenigingen.utils.member_performance_optimizer import get_member_dashboard
from verenigingen.utils.security.permission_existence_guard import permission_allowed_without_oracle


class TestPermissionAllowedWithoutOracleHelper(EnhancedTestCase):
    """Unit-level coverage of the shared helper every #1411 fix site now calls."""

    def setUp(self):
        super().setUp()
        self.outsider = f"peog-helper-outsider-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.outsider, roles=["Verenigingen Volunteer"])
        self.chapter = self.create_test_chapter()
        self.unknown_chapter = f"Totally-Fake-Chapter-{frappe.generate_hash()[:8]}"

    def test_unknown_and_forbidden_name_both_refuse_without_raising(self):
        """The whole point of the helper: neither branch raises DoesNotExistError."""
        with self.as_user(self.outsider):
            real = permission_allowed_without_oracle("Chapter", "write", self.chapter.name)
            unknown = permission_allowed_without_oracle("Chapter", "write", self.unknown_chapter)
        self.assertFalse(real)
        self.assertFalse(unknown)

    def test_message_log_trimmed_symmetric_between_unknown_and_forbidden(self):
        """REGRESSION GUARD on this bench's Frappe 16.35, not a red/green
        discriminator for trim-vs-clear_last_message() -- see the module
        docstring's DISCLOSURE section."""
        with self.as_user(self.outsider):
            frappe.clear_messages()
            permission_allowed_without_oracle("Chapter", "write", self.chapter.name)
            real_log = list(frappe.message_log)

            frappe.clear_messages()
            permission_allowed_without_oracle("Chapter", "write", self.unknown_chapter)
            unknown_log = list(frappe.message_log)

        for entry in unknown_log:
            self.assertNotIn(
                "not found",
                entry.get("message", ""),
                msg=f"unknown-chapter message_log still carries an existence-revealing entry: {entry}",
            )
        self.assertEqual(
            [e.get("message") for e in real_log],
            [e.get("message") for e in unknown_log],
            "unknown and forbidden refusals must leave identical message logs",
        )

    def test_administrator_and_permitted_caller_still_get_true(self):
        """Control: the helper must not overcorrect into a blanket refusal."""
        self.assertTrue(permission_allowed_without_oracle("Chapter", "write", self.chapter.name))

        staff = f"peog-helper-staff-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(staff, roles=["Verenigingen Staff"])
        with self.as_user(staff):
            self.assertTrue(permission_allowed_without_oracle("Chapter", "write", self.chapter.name))

    # NOTE: a test asserting "any exception OTHER than DoesNotExistError still
    # propagates" (matching #1436's Finding B) would need to mock
    # frappe.has_permission itself to inject e.g. a QueryDeadlockError -- this
    # app's test-quality-enforcer (Tier 3) explicitly bans mocking the
    # permission boundary in a security test, with no justification-comment
    # escape hatch, since that defeats the point of testing it. Verified
    # instead by reading the helper: its only `except` clause names
    # `frappe.DoesNotExistError` specifically (not a bare `except Exception:`),
    # so any other exception propagates by construction. Confirmed by mutation
    # during self-review, done manually and reverted (not committed as a
    # test): widening that clause to `except Exception:` left every test in
    # this file green (frappe.DoesNotExistError is itself an Exception, so a
    # wider catch changes nothing for the cases exercised here) -- the only
    # thing that would redden it is a dedicated non-DoesNotExistError-raising
    # test, which is exactly the mocked test this comment replaces.


class TestFormatMemberAddressExistenceOracle(EnhancedTestCase):
    """address_formatter.format_member_address: Member, then Address, guards."""

    def setUp(self):
        super().setUp()
        self.owner, self.owner_user = self._make_addr_oracle_test_member_with_user("Owner1411")
        self.intruder, self.intruder_user = self._make_addr_oracle_test_member_with_user("Intruder1411")
        # format_member_address is @high_security_api: HIGH tier is only
        # grantable through an assigned role PROFILE (Rule 4 in
        # authorization_policy), not a bare role -- grant both, matching
        # test_address_formatter_auth_gate.py's own setUp for this function.
        grant_matching_role_profiles(self.owner_user, "Verenigingen Chapter Board Member")
        grant_matching_role_profiles(self.intruder_user, "Verenigingen Chapter Board Member")

        self.address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": self.owner.name,
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": self.owner.name}],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Address", self.address.name)
        self.owner.db_set("primary_address", self.address.name)
        self.owner.reload()

        self.unknown_member = f"NONEXISTENT-MEMBER-{frappe.generate_hash()[:8]}"

    def _make_addr_oracle_test_member_with_user(self, label):
        email = f"addrfmt1411-{label.lower()}-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name=label, last_name="Portal", email=email, birth_date="1985-06-15"
        )
        email = member.email
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": label,
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member.db_set("user", email)
        member.reload()
        return member, email

    def _unwrap_api_payload(self, result):
        return result.get("data", result) if isinstance(result, dict) and "data" in result else result

    def test_unknown_and_foreign_member_identical_refusal(self):
        with self.as_user(self.intruder_user):
            unknown = self._unwrap_api_payload(format_member_address(self.unknown_member))
            foreign = self._unwrap_api_payload(format_member_address(self.owner.name))

        self.assertFalse(unknown["has_address"])
        self.assertFalse(foreign["has_address"])
        self.assertEqual(unknown["message"], foreign["message"])
        self.assertEqual(foreign["message"], "Access denied to member information")

    def test_unknown_address_gets_a_clean_refusal_not_a_raw_exception(self):
        """Regression for the Address guard (2nd call site) without mocking
        the permission boundary itself (this app's test-quality-enforcer
        (Tier 3) bans that in a security test -- no justification-comment
        escape hatch).

        Every real identity in this app's role catalog that clears
        format_member_address's HIGH security tier also ends up with real
        Address read access (measured: "Verenigingen Staff" bypasses via
        has_address_permission's admin check, and every OTHER HIGH-granting
        role profile -- Chapter Board Member, Treasurer, National Board
        Member -- bundles core Frappe's "Sales User"/"Accounts User"/
        "Purchase User" roles, which carry a blanket Address read=1 DocPerm
        grant of their own) -- so a REAL "denied but tier-cleared" caller
        cannot be constructed for the FOREIGN-address comparison the way it
        can for Member (test_unknown_and_foreign_member_identical_refusal
        above) or for Chapter (TestChapterEmailGuardsExistenceOracle below).
        The owner's own primary_address is instead pointed at a name that
        does not exist at all, exercising the REAL Address guard for real:
        pre-fix this raised an unhandled frappe.DoesNotExistError; post-fix
        it must degrade to the same clean refusal dict a real-but-forbidden
        address gives (proven, with a REAL denied caller, doctype-agnostically,
        by TestPermissionAllowedWithoutOracleHelper above).
        """
        unknown_address = f"NONEXISTENT-ADDRESS-{frappe.generate_hash()[:8]}"

        with self.as_user(self.owner_user):
            self.owner.db_set("primary_address", unknown_address)
            result = self._unwrap_api_payload(format_member_address(self.owner.name))

        self.assertFalse(result["has_address"])
        self.assertEqual(result["message"], "Access denied to address information")

    def test_owner_still_gets_their_own_address(self):
        """Control: legitimate self-service access is unaffected by the fix."""
        with self.as_user(self.owner_user):
            result = self._unwrap_api_payload(format_member_address(self.owner.name))
        self.assertTrue(result["has_address"])
        self.assertIn("Teststraat 1", result["formatted_address"])


class TestMemberDashboardExistenceOracle(EnhancedTestCase):
    """member_performance_optimizer.get_member_dashboard's throw=True-shaped guard."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Dashboard", last_name="Target1411", birth_date="1985-06-15"
        )
        self.unknown_member = f"NONEXISTENT-MEMBER-{frappe.generate_hash()[:8]}"

        # A Chapter Board Member profile clears the HIGH security tier but, per
        # has_member_permission, is refused for a member outside their own
        # chapter -- this board member is not assigned to any chapter, so
        # get_user_chapter_memberships_cached returns nothing and the member
        # check falls through to a plain refusal, exactly like a real
        # out-of-scope board member.
        self.board_outsider = f"dash1411-board-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.board_outsider, roles=["Verenigingen Chapter Board Member"])
        grant_matching_role_profiles(self.board_outsider, "Verenigingen Chapter Board Member")

        self.staff = f"dash1411-staff-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.staff, roles=["Verenigingen Staff"])
        grant_matching_role_profiles(self.staff, "Verenigingen Staff")

    def test_unknown_and_foreign_member_identical_refusal(self):
        with self.as_user(self.board_outsider):
            with self.assertRaises(frappe.PermissionError) as unknown_ctx:
                get_member_dashboard(self.unknown_member)
            with self.assertRaises(frappe.PermissionError) as foreign_ctx:
                get_member_dashboard(self.member.name)

        # Both are frappe.PermissionError with the SAME message shape
        # ("No permission for Member {name}") -- the message legitimately
        # echoes the caller's own supplied member_name (not a leak: the caller
        # already knows what they passed), so compare shape, not the literal
        # string, exactly like team_management's own equivalent test.
        self.assertTrue(str(unknown_ctx.exception).startswith("No permission for Member "))
        self.assertTrue(str(foreign_ctx.exception).startswith("No permission for Member "))

    def test_message_log_has_no_existence_revealing_residue(self):
        """REGRESSION GUARD on this bench's Frappe 16.35, not a red/green
        discriminator for trim-vs-clear_last_message() -- see the module
        docstring's DISCLOSURE section."""
        with self.as_user(self.board_outsider):
            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError):
                get_member_dashboard(self.unknown_member)
            unknown_log = list(frappe.message_log)

        for entry in unknown_log:
            self.assertNotIn("not found", entry.get("message", ""))

    def test_staff_still_gets_a_real_members_dashboard(self):
        """Control: a legitimate caller with real access is unaffected."""
        with self.as_user(self.staff):
            result = get_member_dashboard(self.member.name)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("name"), self.member.name)


class TestChapterEmailGuardsExistenceOracle(EnhancedTestCase):
    """The 9-site Chapter guard idiom in verenigingen/email/*.py. Two
    representative call sites: a "read" gate (get_segment_suggestions, MEDIUM
    tier) and a "write" gate (send_chapter_email, HIGH tier). The other 7 sites
    (advanced_segmentation.py x3 more, automated_campaigns.py x1 more,
    newsletter_templates.py) share the identical
    `if chapter_name and not permission_allowed_without_oracle(...)` line,
    verified by grep, not independently dispatched here.
    """

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.unknown_chapter = f"Totally-Fake-Chapter-{frappe.generate_hash()[:8]}"

        # Chapter has its OWN doc-level has_permission hook
        # (has_chapter_permission -> ChapterPermissionService), which explicitly
        # DENIES a "Verenigingen Chapter Board Member" role-holder who is not
        # actually seated on THAT chapter's board (row-level security -- see
        # that service's docstring: "board members can only access their own
        # chapters"). Its role PROFILE clears BOTH @standard_api's MEDIUM tier
        # and @high_security_api's HIGH tier (ROLE_PROFILE_SECURITY_MAPPING),
        # so one user exercises both gates below with a REAL refusal (not a
        # security-tier refusal) on either read or write.
        self.outsider_board = f"chapmail1411-outsider-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.outsider_board, roles=["Verenigingen Chapter Board Member"])
        grant_matching_role_profiles(self.outsider_board, "Verenigingen Chapter Board Member")

        # Verenigingen Staff: has_chapter_permission's _is_admin_or_staff
        # branch grants unconditional access -- a simple, legitimate-access
        # control that must keep working.
        self.staff = f"chapmail1411-staff-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.staff, roles=["Verenigingen Staff"])
        grant_matching_role_profiles(self.staff, "Verenigingen Staff")

    def test_get_segment_suggestions_unknown_and_foreign_chapter_identical_refusal(self):
        with self.as_user(self.outsider_board):
            with self.assertRaises(frappe.ValidationError) as unknown_ctx:
                get_segment_suggestions(self.unknown_chapter)
            with self.assertRaises(frappe.ValidationError) as foreign_ctx:
                get_segment_suggestions(self.chapter.name)

        self.assertEqual(str(unknown_ctx.exception), str(foreign_ctx.exception))
        self.assertIn("permission to view this chapter's data", str(foreign_ctx.exception))

    def test_get_segment_suggestions_message_log_has_no_residue(self):
        """REGRESSION GUARD on this bench's Frappe 16.35, not a red/green
        discriminator for trim-vs-clear_last_message() -- see the module
        docstring's DISCLOSURE section."""
        with self.as_user(self.outsider_board):
            frappe.clear_messages()
            with self.assertRaises(frappe.ValidationError):
                get_segment_suggestions(self.unknown_chapter)
            unknown_log = list(frappe.message_log)

        for entry in unknown_log:
            self.assertNotIn("not found", entry.get("message", ""))

    def test_get_segment_suggestions_succeeds_for_a_caller_with_real_access(self):
        """Control: legitimate (Staff) access still gets data."""
        with self.as_user(self.staff):
            result = get_segment_suggestions(self.chapter.name)
        self.assertIsInstance(result, dict)

    def test_send_chapter_email_unknown_and_foreign_chapter_identical_refusal(self):
        with mock.patch.object(
            SimplifiedEmailManager, "send_to_chapter_segment", return_value={"success": True}
        ) as spy:
            with self.as_user(self.outsider_board):
                with self.assertRaises(frappe.ValidationError) as unknown_ctx:
                    send_chapter_email(self.unknown_chapter, "all", "Subject", "Content")
                with self.assertRaises(frappe.ValidationError) as foreign_ctx:
                    send_chapter_email(self.chapter.name, "all", "Subject", "Content")

        spy.assert_not_called()
        self.assertEqual(str(unknown_ctx.exception), str(foreign_ctx.exception))
        self.assertIn("permission to send emails for this chapter", str(foreign_ctx.exception))

    def test_send_chapter_email_succeeds_for_a_caller_with_real_write_access(self):
        """Control: the permission gate does not overcorrect into a refusal
        for legitimate (Staff) write access."""
        with mock.patch.object(
            SimplifiedEmailManager, "send_to_chapter_segment", return_value={"success": True}
        ) as spy:
            with self.as_user(self.staff):
                result = send_chapter_email(self.chapter.name, "all", "Subject", "Content")

        spy.assert_called_once()
        self.assertEqual(result, {"success": True})

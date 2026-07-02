"""
Coverage for the authorization engine, policy, and self-service access controller.

Targets:
- verenigingen/utils/security/authorization_engine.py (AuthorizationEngine)
- verenigingen/utils/security/authorization_policy.py (AuthorizationPolicy.decide)
- verenigingen/utils/security/self_service_access_controller.py

AuthorizationPolicy is a PURE decision function (no Frappe I/O), so its rule chain
is exercised by passing role/profile lists directly -- this is the legitimate way
to test the policy and does NOT mock any auth primitive.

AuthorizationEngine and SelfServiceAccessController do real Frappe I/O, so they
are driven with real Users, real Role Profiles, real Member/Volunteer records,
and identity switching via self.as_user(...). No patching of frappe.get_roles /
frappe.session / frappe.db.exists / the function-under-test.

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.security.test_authorization_engine_policy_coverage
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.authorization_engine import (
    AuthorizationEngine,
    get_authorization_engine,
    invalidate_user_role_cache,
)
from verenigingen.utils.security.authorization_policy import (
    AuthorizationPolicy,
    get_authorization_policy,
)
from verenigingen.utils.security.self_service_access_controller import (
    SelfServiceAccessController,
    get_self_service_controller,
)
from verenigingen.utils.security.types import AuthResult, SecurityLevel


# ===========================================================================
# AuthorizationPolicy -- pure decision table (no I/O, direct inputs are correct)
# ===========================================================================
class TestAuthorizationPolicy(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.policy = AuthorizationPolicy()

    def test_rule_1_public_grants_without_authentication(self):
        result = self.policy.decide(
            required_level=SecurityLevel.PUBLIC,
            user_profiles=[],
            user_roles=[],
            is_authenticated=False,
        )
        self.assertTrue(result.granted)
        self.assertEqual(result.rule_matched, "rule_1_public")

    def test_rule_2_guest_denied_for_non_public(self):
        result = self.policy.decide(
            required_level=SecurityLevel.LOW,
            user_profiles=[],
            user_roles=[],
            is_authenticated=False,
        )
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_2_guest_denied")

    def test_rule_3_low_allows_any_authenticated_user(self):
        result = self.policy.decide(
            required_level=SecurityLevel.LOW,
            user_profiles=[],
            user_roles=[],
            is_authenticated=True,
        )
        self.assertTrue(result.granted)
        self.assertEqual(result.rule_matched, "rule_3_any_authenticated")

    def test_rule_4_role_profile_grants_high(self):
        result = self.policy.decide(
            required_level=SecurityLevel.HIGH,
            user_profiles=["Verenigingen Treasurer"],
            user_roles=[],
            is_authenticated=True,
        )
        self.assertTrue(result.granted)
        self.assertEqual(result.rule_matched, "rule_4_role_profile")
        self.assertIn("Verenigingen Treasurer", result.auth_path)

    def test_rule_5_individual_role_matches_profile_name(self):
        """No matching profile, but an individual role name matches a mapping key.

        Rule 5 is capped at MEDIUM (see below), so it grants MEDIUM but not HIGH.
        """
        result = self.policy.decide(
            required_level=SecurityLevel.MEDIUM,
            user_profiles=[],
            user_roles=["Verenigingen Staff"],
            is_authenticated=True,
        )
        self.assertTrue(result.granted)
        self.assertEqual(result.rule_matched, "rule_5_individual_role")

    def test_rule_5_individual_role_cannot_reach_high(self):
        """SECURITY: a bare role must NOT grant HIGH (member-data) access.

        Staff maps to HIGH in the mapping, but without an assigned role profile
        the HIGH tier requires Rule 4 — Rule 5 is capped at MEDIUM, so this denies.
        """
        result = self.policy.decide(
            required_level=SecurityLevel.HIGH,
            user_profiles=[],
            user_roles=["Verenigingen Staff"],
            is_authenticated=True,
        )
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_7_deny")

    def test_rule_5_individual_role_cannot_reach_critical(self):
        """SECURITY: a bare admin role must NOT grant CRITICAL (financial/admin) access."""
        result = self.policy.decide(
            required_level=SecurityLevel.CRITICAL,
            user_profiles=[],
            user_roles=["Verenigingen Administrator"],
            is_authenticated=True,
        )
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_7_deny")

    def test_rule_6_system_manager_gets_medium(self):
        """System Manager has no profile mapping but is granted MEDIUM by rule 6."""
        result = self.policy.decide(
            required_level=SecurityLevel.MEDIUM,
            user_profiles=[],
            user_roles=["System Manager"],
            is_authenticated=True,
        )
        self.assertTrue(result.granted)
        self.assertEqual(result.rule_matched, "rule_6_system_manager")

    def test_rule_6_system_manager_does_not_get_high(self):
        """The System Manager exception is MEDIUM-only: HIGH falls through to DENY."""
        result = self.policy.decide(
            required_level=SecurityLevel.HIGH,
            user_profiles=[],
            user_roles=["System Manager"],
            is_authenticated=True,
        )
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_7_deny")

    def test_rule_7_deny_by_default(self):
        """Authenticated user with no qualifying profile/role is denied CRITICAL."""
        result = self.policy.decide(
            required_level=SecurityLevel.CRITICAL,
            user_profiles=["Verenigingen Member"],
            user_roles=["Verenigingen Member"],
            is_authenticated=True,
        )
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_7_deny")
        self.assertIn("critical", result.reason)

    def test_member_profile_cannot_reach_medium(self):
        """Privilege-boundary guard: Member profile only grants LOW, so MEDIUM denies."""
        result = self.policy.decide(
            required_level=SecurityLevel.MEDIUM,
            user_profiles=["Verenigingen Member"],
            user_roles=[],
            is_authenticated=True,
        )
        self.assertFalse(result.granted)

    def test_role_profile_grants_access_helper(self):
        self.assertTrue(
            self.policy.role_profile_grants_access("Verenigingen Treasurer", SecurityLevel.CRITICAL)
        )
        self.assertFalse(
            self.policy.role_profile_grants_access("Verenigingen Member", SecurityLevel.CRITICAL)
        )
        # Unknown profile grants nothing.
        self.assertFalse(self.policy.role_profile_grants_access("No Such Profile", SecurityLevel.LOW))

    def test_get_authorization_policy_singleton(self):
        self.assertIs(get_authorization_policy(), get_authorization_policy())


# ===========================================================================
# AuthorizationEngine -- real I/O against Frappe users/role profiles
# ===========================================================================
class TestAuthorizationEngine(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.engine = AuthorizationEngine()

    def _make_user_with_role_profile(self, role_profile, prefix="eng"):
        email = f"{prefix}-{frappe.generate_hash(length=8).lower()}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": prefix.title(),
                "last_name": "EngUser",
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        user.set("role_profiles", [{"role_profile": role_profile}])
        user.role_profile_name = role_profile
        user.save(ignore_permissions=True)
        self.engine.invalidate_user_cache(email)
        return user

    def test_authorize_grants_for_qualified_role_profile(self):
        """Engine.authorize fetches real roles/profiles and delegates to the policy:
        a Treasurer is granted CRITICAL."""
        user = self._make_user_with_role_profile("Verenigingen Treasurer", prefix="engtreas")
        with self.as_user(user.name):
            result = self.engine.authorize(user.name, SecurityLevel.CRITICAL)
        self.assertIsInstance(result, AuthResult)
        self.assertTrue(result.granted)
        self.assertEqual(result.rule_matched, "rule_4_role_profile")

    def test_authorize_denies_member_for_high(self):
        user = self._make_user_with_role_profile("Verenigingen Member", prefix="engmbr")
        with self.as_user(user.name):
            result = self.engine.authorize(user.name, SecurityLevel.HIGH)
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_7_deny")

    def test_authorize_defaults_to_session_user(self):
        """authorize(None, ...) resolves the user from the live session."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="engsess")
        with self.as_user(user.name):
            result = self.engine.authorize(None, SecurityLevel.HIGH)
        self.assertTrue(result.granted)

    def test_authorize_administrator_break_glass(self):
        """The literal Administrator bootstrap account is granted every level
        (Rule 0) without any role profile -- break-glass / bootstrap identity."""
        for level in (SecurityLevel.CRITICAL, SecurityLevel.HIGH, SecurityLevel.MEDIUM):
            result = self.engine.authorize("Administrator", level)
            self.assertTrue(result.granted, f"Administrator should be granted {level.value}")
            self.assertEqual(result.rule_matched, "rule_0_administrator_break_glass")

    def test_authorize_guest_denied_for_low(self):
        """Guest is unauthenticated -> rule 2 denial even for LOW."""
        with self.as_user("Guest"):
            result = self.engine.authorize("Guest", SecurityLevel.LOW)
        self.assertFalse(result.granted)
        self.assertEqual(result.rule_matched, "rule_2_guest_denied")

    def test_get_user_role_profiles_returns_assigned_profile(self):
        user = self._make_user_with_role_profile("Verenigingen Auditor", prefix="engprof")
        profiles = self.engine.get_user_role_profiles(user.name)
        self.assertEqual(profiles, ["Verenigingen Auditor"])

    def _make_plain_user(self, prefix="engnone"):
        email = f"{prefix}-{frappe.generate_hash(length=8).lower()}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Eng",
                "last_name": "None",
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    def test_get_user_role_profiles_empty_for_unassigned_user(self):
        user = self._make_plain_user()
        self.engine.invalidate_user_cache(user.name)
        self.assertEqual(self.engine.get_user_role_profiles(user.name), [])

    def test_role_profile_cache_is_used(self):
        """Second lookup returns the cached list (cache populated on first call)."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="engcache")
        first = self.engine.get_user_role_profiles(user.name)
        cache_key = self.engine._get_versioned_cache_key(user.name)
        self.assertIsNotNone(frappe.cache.get_value(cache_key))
        second = self.engine.get_user_role_profiles(user.name)
        self.assertEqual(first, second)

    def test_invalidate_specific_user_clears_cache_entry(self):
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="enginval")
        self.engine.get_user_role_profiles(user.name)
        cache_key = self.engine._get_versioned_cache_key(user.name)
        self.assertIsNotNone(frappe.cache.get_value(cache_key))
        self.engine.invalidate_user_cache(user.name)
        self.assertIsNone(frappe.cache.get_value(cache_key))

    def test_invalidate_all_bumps_version(self):
        """Global invalidation increments the shared Redis version, changing the
        versioned key namespace for all users."""
        before = AuthorizationEngine.get_cache_version()
        self.engine.invalidate_user_cache(None)
        after = AuthorizationEngine.get_cache_version()
        self.assertEqual(after, before + 1)

    def test_versioned_cache_key_includes_version_and_user(self):
        version = self.engine._get_cache_version()
        key = self.engine._get_versioned_cache_key("someone@example.com")
        self.assertEqual(key, f"user_role_profiles_v{version}:someone@example.com")

    def test_get_authorization_engine_singleton(self):
        self.assertIs(get_authorization_engine(), get_authorization_engine())

    def test_invalidate_user_role_cache_convenience(self):
        """Module-level convenience wrapper delegates to the singleton engine."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="engconv")
        get_authorization_engine().get_user_role_profiles(user.name)
        cache_key = get_authorization_engine()._get_versioned_cache_key(user.name)
        self.assertIsNotNone(frappe.cache.get_value(cache_key))
        invalidate_user_role_cache(user.name)
        self.assertIsNone(frappe.cache.get_value(cache_key))


# ===========================================================================
# SelfServiceAccessController -- real Member/Volunteer ownership boundary
# ===========================================================================
class TestSelfServiceAccessController(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.controller = SelfServiceAccessController()

    def _make_member_user(self, prefix="ssc"):
        """Create a Member linked (via Member.user) to a real enabled User."""
        member = self.create_test_member(birth_date="1990-01-01")
        email = f"{prefix}-{frappe.generate_hash(length=8).lower()}@example.com"
        user = self.create_test_user(email=email, roles=["Verenigingen Member"])
        member.user = user.name
        member.save(ignore_permissions=True)
        return member, user

    # --- get_user_member ----------------------------------------------------
    def test_get_user_member_resolves_linked_member(self):
        member, user = self._make_member_user(prefix="resolve")
        with self.as_user(user.name):
            self.assertEqual(self.controller.get_user_member(), member.name)

    def test_get_user_member_none_for_unlinked_user(self):
        user = self.create_test_user(
            email=f"nolink-{frappe.generate_hash(length=8).lower()}@example.com",
            roles=["Verenigingen Member"],
        )
        with self.as_user(user.name):
            self.assertIsNone(self.controller.get_user_member())

    # --- validate_access: system users -------------------------------------
    def test_administrator_bypasses_validation(self):
        with self.as_user("Administrator"):
            self.assertTrue(self.controller.validate_access(member="any-member"))

    def test_guest_bypasses_validation(self):
        with self.as_user("Guest"):
            self.assertTrue(self.controller.validate_access(member="any-member"))

    # --- validate_access: explicit target ----------------------------------
    def test_owner_explicit_target_allowed(self):
        member, user = self._make_member_user(prefix="owner")
        with self.as_user(user.name):
            self.assertTrue(self.controller.validate_access(member=member.name))

    def test_cross_user_explicit_target_denied(self):
        owner, _owner_user = self._make_member_user(prefix="victim")
        _intruder_member, intruder_user = self._make_member_user(prefix="intruder")
        with self.as_user(intruder_user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.controller.validate_access(member=owner.name)
        self.assertIn("only perform this operation on your own data", str(ctx.exception))

    def test_explicit_target_denied_when_user_has_no_member(self):
        """A user with no Member record cannot pass an explicit-target check."""
        owner, _ = self._make_member_user(prefix="hastarget")
        nomember_user = self.create_test_user(
            email=f"nomember-{frappe.generate_hash(length=8).lower()}@example.com",
            roles=["Verenigingen Member"],
        )
        with self.as_user(nomember_user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.controller.validate_access(member=owner.name)
        self.assertIn("Unable to verify member access", str(ctx.exception))

    # --- validate_access: implicit self-service ----------------------------
    def test_implicit_disallowed_by_default(self):
        member, user = self._make_member_user(prefix="implicitdef")
        with self.as_user(user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.controller.validate_access()
        self.assertIn("explicit member parameter", str(ctx.exception))

    def test_implicit_allowed_passes_for_user_with_member(self):
        member, user = self._make_member_user(prefix="implicitok")
        with self.as_user(user.name):
            self.assertTrue(self.controller.validate_access(implicit_allowed=True))

    def test_implicit_allowed_rejects_user_without_member(self):
        nomember_user = self.create_test_user(
            email=f"implicitno-{frappe.generate_hash(length=8).lower()}@example.com",
            roles=["Verenigingen Member"],
        )
        with self.as_user(nomember_user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.controller.validate_access(implicit_allowed=True)
        self.assertIn("No member record found", str(ctx.exception))

    # --- volunteer target resolution ---------------------------------------
    def test_volunteer_target_resolves_to_owner_member(self):
        """A volunteer kwarg resolves to its linked member; owner is allowed."""
        member, user = self._make_member_user(prefix="vol")
        volunteer = self.create_test_volunteer(member=member.name)
        with self.as_user(user.name):
            self.assertTrue(self.controller.validate_access(volunteer=volunteer.name))

    def test_volunteer_target_of_other_member_denied(self):
        owner, _ = self._make_member_user(prefix="volowner")
        owner_volunteer = self.create_test_volunteer(member=owner.name)
        _intruder_member, intruder_user = self._make_member_user(prefix="volintruder")
        with self.as_user(intruder_user.name):
            with self.assertRaises(VPermissionError):
                self.controller.validate_access(volunteer=owner_volunteer.name)

    def test_get_volunteer_member_returns_linked_member(self):
        member, _ = self._make_member_user(prefix="getvol")
        volunteer = self.create_test_volunteer(member=member.name)
        self.assertEqual(self.controller.get_volunteer_member(volunteer.name), member.name)

    def test_get_volunteer_member_none_for_missing_volunteer(self):
        self.assertIsNone(self.controller.get_volunteer_member("Nonexistent-Volunteer"))

    # --- validate_request_content (deep TOCTOU inspection) -----------------
    def test_request_content_allows_own_member_reference(self):
        member, _ = self._make_member_user(prefix="content")
        self.assertTrue(
            self.controller.validate_request_content(
                member.name, payload={"member": member.name, "note": "fine"}
            )
        )

    def test_request_content_rejects_foreign_member_reference(self):
        member, _ = self._make_member_user(prefix="contentown")
        other, _ = self._make_member_user(prefix="contentother")
        with self.assertRaises(VPermissionError) as ctx:
            self.controller.validate_request_content(member.name, payload={"member": other.name})
        self.assertIn("only be performed on your own data", str(ctx.exception))

    def test_request_content_rejects_nested_foreign_reference(self):
        """Deep inspection catches a foreign member buried in a nested list/dict."""
        member, _ = self._make_member_user(prefix="nestown")
        other, _ = self._make_member_user(prefix="nestother")
        payload = {"records": [{"inner": {"member_id": other.name}}]}
        with self.assertRaises(VPermissionError):
            self.controller.validate_request_content(member.name, payload=payload)

    def test_request_content_rejects_foreign_volunteer_reference(self):
        """A nested volunteer linked to another member is flagged as a violation."""
        member, _ = self._make_member_user(prefix="volcontent")
        other, _ = self._make_member_user(prefix="volcontentother")
        other_volunteer = self.create_test_volunteer(member=other.name)
        payload = {"data": {"volunteer": other_volunteer.name}}
        with self.assertRaises(VPermissionError):
            self.controller.validate_request_content(member.name, payload=payload)

    def test_request_content_missing_volunteer_treated_as_no_link(self):
        """A volunteer name that simply does not exist resolves to no member link
        (frappe.db.get_value returns None without raising), so it is NOT a violation.

        Documents actual behaviour: the "invalid" sentinel branch in
        _check_volunteer_member only triggers if the lookup itself raises, which a
        plain missing document does not. So an unknown volunteer reference passes.
        """
        member, _ = self._make_member_user(prefix="volmissing")
        payload = {"data": {"volunteer": "Definitely-Not-A-Volunteer"}}
        self.assertTrue(self.controller.validate_request_content(member.name, payload=payload))

    def test_request_content_allows_own_volunteer_reference(self):
        member, _ = self._make_member_user(prefix="volownref")
        own_volunteer = self.create_test_volunteer(member=member.name)
        payload = {"data": {"volunteer": own_volunteer.name}}
        self.assertTrue(self.controller.validate_request_content(member.name, payload=payload))

    def test_self_service_violation_is_durably_audited(self):
        """REGRESSION (security observability): a self-service violation must be
        persisted as an API Audit Log row with event_type 'self_service_violation'.

        Before the fix the API Audit Log 'event_type' Select did NOT include
        'self_service_violation', so the audit insert failed validation and the
        violation row was silently dropped (only a generic 'Failed to store API
        audit event' Error Log remained). This asserts the structured security
        record actually lands in the DB.
        """
        member, _ = self._make_member_user(prefix="auditrow")
        other, _ = self._make_member_user(prefix="auditother")

        before = frappe.utils.now()
        with self.assertRaises(VPermissionError):
            self.controller.validate_request_content(member.name, payload={"member": other.name})

        rows = frappe.get_all(
            "API Audit Log",
            filters={
                "event_type": "self_service_violation",
                "creation": [">=", before],
            },
            fields=["name", "event_type"],
        )
        self.assertTrue(
            rows,
            "Self-service violation was not stored as an API Audit Log row — the "
            "structured security audit record is being dropped.",
        )
        for r in rows:
            self.track_doc("API Audit Log", r.name)

    def test_get_self_service_controller_singleton(self):
        self.assertIs(get_self_service_controller(), get_self_service_controller())

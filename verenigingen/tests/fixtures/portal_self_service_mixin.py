"""
Shared test helpers for member/volunteer self-service portal tests.

Consolidates the ``_link_member_to_user`` / ``_as_user`` helpers that were
copy-pasted (and had begun to fork) across six portal and self-service test
suites. Mix into an EnhancedTestCase subclass:

    class TestX(PortalSelfServiceTestMixin, EnhancedTestCase):
        ...

The mixin relies on EnhancedTestCase providing ``self.factory`` and ``self.uid``.
Suites with different linking policy (volunteer tier, email-only ownership) keep a
one-line override that delegates to ``_link_member_to_user`` with the right flags,
so the duplicated body lives here once.
"""

import frappe


class _UserSwitcher:
    """Context manager that runs its with-block as ``user_name`` and restores the
    previous session user on exit."""

    def __init__(self, user_name):
        self.user_name = user_name
        self.original = None

    def __enter__(self):
        self.original = frappe.session.user
        frappe.set_user(self.user_name)
        return self

    def __exit__(self, *_):
        frappe.set_user(self.original)


class PortalSelfServiceTestMixin:
    """Helpers to link a User to a Member record and invoke code as that user."""

    def _link_member_to_user(
        self,
        member,
        roles=("Verenigingen Member",),
        *,
        role_profile="Verenigingen Member",
        link_user=True,
    ):
        """Create a User with ``roles``, link it to ``member``, and return the User.

        Args:
            member: the Member document to link.
            roles: roles granted to the new User.
            role_profile: v16 role-profile to assign (the canonical LOW-tier store
                real members carry). Pass ``None`` to skip — e.g. volunteer-tier
                tests that must not gain a Member profile.
            link_user: also set ``Member.user`` (the strict user-link ownership
                path) in addition to ``Member.email``. Pass ``False`` for tests that
                exercise the email-only lookup in SelfServiceAccessController.

        ``Member.email`` is always set (the fallback lookup field). The member is
        reloaded first because after_insert / membership creation may have bumped
        its modified timestamp since the caller fetched it.
        """
        user = self.factory.create_user_with_roles(
            email=f"selfsvc-{member.name}-{self.uid}@example.com",
            roles=list(roles),
        )
        if role_profile:
            user.reload()
            user.set("role_profiles", [{"role_profile": role_profile}])
            user.save(ignore_permissions=True)

        member.reload()
        if link_user:
            member.user = user.name
        member.email = user.name
        member.save(ignore_permissions=True)
        return user

    def _as_user(self, user_name):
        """Context manager: run the with-block as ``user_name``."""
        return _UserSwitcher(user_name)

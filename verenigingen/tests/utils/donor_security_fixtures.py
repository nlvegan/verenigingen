"""Shared fixture for donor/SEPA permission-query SQL-injection tests.

Extracted from ``test_donor_security_core.py`` (#1542 review) so
``test_donor_permissions_security.py`` (#1558) can reuse it instead of a second,
near-identical copy -- the exact clone-family hazard
``duplicate_helper_validator.py`` exists to catch.
"""

import frappe


def create_member_named(test_case, payload, roles=("Verenigingen Member",)):
    """Create a REAL User + Member, then rename the Member onto `payload`.

    #1542 review: SQL-injection tests used to fake
    frappe.db.get_value()/frappe.get_roles() to simulate "a member record
    whose docname is the attacker's payload". A Member docname is not
    actually restricted to that shape -- validate_name() only forbids
    `<`/`>` (frappe/model/naming.py) -- so the scenario is reproducible for
    real: create an ordinary Member, then frappe.rename_doc() it onto the
    payload (force=True, since Member has no allow_rename). Every later
    call in the test reaches this row through the exact
    frappe.db.get_value("Member", {"user": ...}) / frappe.get_roles(...)
    calls production uses; nothing about the lookup path itself is faked.

    This is a defense-in-depth check of the query-construction/escaping
    boundary with a real docname containing SQL metacharacters -- NOT a
    live attack path. `frappe.rename_doc(force=True)` is a test-only way to
    reach this docname shape: Member.allow_rename is unset,
    validate_rename() throws without force=True or ignore_permissions=True,
    the desk's update_document_title calls doc.rename(force=False), and
    there are 0 non-test frappe.rename_doc calls on Member anywhere in the
    app. No role can rename a Member through any UI or API path today.

    Trailing digit in the email's local part matches
    create_test_board_member's convention: the factory rewrites
    Member.email unless the local part's last 5 characters contain one,
    which would otherwise silently decouple Member.email from Member.user.

    Args:
        test_case: the calling TestCase instance (needs .factory and
            .track_doc(), both provided by VereningingenTestCase).
        payload: the string to make the Member's docname.
        roles: roles to grant the linked User (default: plain member access).

    Returns:
        The linked User's email.
    """
    run = f"{frappe.generate_hash(length=8)}0"
    email = f"security_core_{run}@example.com"
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": "Security",
            "send_welcome_email": 0,
            "enabled": 1,
            "roles": [{"role": role} for role in roles],
        }
    )
    user.insert(ignore_permissions=True)
    test_case.track_doc("User", user.name)

    member = test_case.factory.create_test_member(
        first_name="Security", last_name=f"Core{run[:6]}", email=email, birth_date="1990-01-01"
    )
    member.db_set("user", email)

    frappe.rename_doc("Member", member.name, payload, force=True)
    test_case.track_doc("Member", payload)

    return email

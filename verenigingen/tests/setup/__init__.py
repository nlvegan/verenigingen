"""
Test setup hooks for Verenigingen app.

This module provides the before_tests hook that ensures ERPNext test fixtures
(Company, etc.) are created before our tests run.
"""
import frappe


def disable_workflow_action_emails():
    """Neutralize synchronous workflow-action emails for the whole test run.

    Frappe's ``process_workflow_actions()`` enqueues ``send_workflow_action_email``
    with ``now=frappe.in_test``, so in test mode it runs SYNCHRONOUSLY inside
    ``doc.insert()``/``doc.save()``. That email renders a PDF of the document
    (BeautifulSoup + the pure-Python html5lib parser), which is pathologically
    slow — tens of seconds per document.

    The production ``Membership Application Workflow`` is active on the Member
    doctype with email alerts enabled on every state, so every test that inserts
    a Member paid this cost. Modules creating ~12 Members in setUp hung for
    13+ minutes; the whole suite was slowed and made flaky by it.

    We replace the email function with a no-op for the test process. The
    ``Workflow Action`` DocType rows are still created — that happens *before*
    the email call in ``process_workflow_actions`` — so workflow behaviour tests
    remain valid. Only the email + PDF side effect is suppressed.

    NOTE: this ``before_tests`` hook only runs for the ``integration`` test
    category. ``EnhancedTestCase`` tests are categorized ``unspecified-category``
    (because ``FrappeTestCase`` is not their *direct* base), so they never reach
    this hook — for them the same patch is applied at import time of
    ``verenigingen.tests.fixtures.enhanced_test_factory``. The patch is
    idempotent, so applying it from both places is harmless.
    """
    try:
        from frappe.workflow.doctype.workflow_action import workflow_action

        def _noop_send_workflow_action_email(*args, **kwargs):
            return None

        workflow_action.send_workflow_action_email = _noop_send_workflow_action_email
    except Exception as e:  # pragma: no cover - defensive: never block the test run
        frappe.logger().warning(f"Could not disable workflow action emails for tests: {e}")


def before_tests():
    """
    Hook called before running tests for this app.

    Ensures ERPNext's test fixtures (Company, Item, etc.) are set up,
    since our app depends on ERPNext DocTypes.
    """
    # Suppress slow synchronous workflow-action emails (see function docstring)
    disable_workflow_action_emails()

    # Call ERPNext's before_tests to ensure basic setup
    try:
        from erpnext.setup.utils import before_tests as erpnext_before_tests
        erpnext_before_tests()
    except ImportError:
        frappe.logger().warning("ERPNext not installed, skipping ERPNext test setup")
    except Exception as e:
        frappe.logger().info(f"ERPNext before_tests: {e}")

    # Ensure all test companies exist by loading Company test records
    # ERPNext Account fixtures require: _Test Company, _Test Company 1,
    # _Test Company with perpetual inventory
    try:
        from frappe.test_runner import make_test_records

        required_companies = [
            "_Test Company",
            "_Test Company 1",
            "_Test Company with perpetual inventory",
        ]
        missing = [c for c in required_companies if not frappe.db.exists("Company", c)]

        if missing:
            # Force recreate to ensure all companies are created
            # (test record log may be stale)
            make_test_records("Company", verbose=False, force=True, commit=True)
            frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(f"Company test record creation failed: {e}")

    # Ensure Customer test records exist (needed by Item Price and other ERPNext fixtures)
    try:
        from frappe.test_runner import make_test_records

        if not frappe.db.exists("Customer", "_Test Customer"):
            make_test_records("Customer", verbose=False, force=True, commit=True)
            frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(f"Customer test record creation failed: {e}")

    # Seed the Mode of Payment records the app and many tests depend on
    # (Bank Transfer, SEPA Direct Debit, Mollie, Manual, Cash). The same helper
    # is wired into after_migrate for production sites; CI sites are bench-new
    # without migrate, so the records are missing at test-time and
    # Member.payment_method / Donation.mode_of_payment link validation fails
    # with "Could not find Payment Method: <name>" across ~119 tests.
    try:
        from verenigingen.services.member.approval.application_helpers import (
            ensure_payment_modes_exist,
        )

        ensure_payment_modes_exist()
    except Exception as e:
        frappe.logger().warning(f"Payment mode seeding failed: {e}")

    # Seed Verenigingen Settings.creation_user (reqd=1) with a dedicated
    # non-Administrator test user. Required by utils.secure_operations
    # `get_system_user_for_operation`, which raises ConfigurationError when the
    # field is empty (~91 fails) and cascades MandatoryError on any later
    # .save() of the Singles doc (~71 fails). The install path normally seeds
    # this via setup/__init__.py:412 but the seed silently fails on fresh CI
    # sites; the test-side seed makes the setup deterministic.
    #
    # IMPORTANT: do NOT default to "Administrator" — PR #81 was closed for
    # silently re-enabling an Administrator fallback that secure_operations.py
    # had been hardened to refuse. We create a dedicated test user instead.
    # Use db.set_single_value to bypass the Singles .save() validation chain
    # (System Settings / Verenigingen Settings both have other reqd fields
    # that would cascade their own MandatoryError).
    try:
        _seed_verenigingen_test_system_user()
    except Exception as e:
        frappe.logger().warning(f"Verenigingen Settings creation_user seeding failed: {e}")

    # Reset Selling Settings.customer_group away from the root "All Customer
    # Groups" that erpnext_before_tests() sets. ERPNext's Customer controller
    # rejects any Customer Group with is_group=1 with "Cannot select a Group
    # type Customer Group" (~72 fails). Production code already uses
    # services.customer_group_resolver.resolve_non_group_customer_group() to
    # work around the bad default; this matches the resolver's behaviour for
    # tests that bypass it by writing customer.customer_group directly.
    try:
        _seed_default_leaf_customer_group()
    except Exception as e:
        frappe.logger().warning(f"Customer Group default reset failed: {e}")

    # Seed dummy values for MijnRood Sync Settings reqd fields (ssh_host,
    # ssh_username, db_name, db_username, db_password). The event_application
    # service tests use a StatusMappingSetupMixin that calls
    # `settings.save(ignore_permissions=True)` in setUp — and on a fresh CI
    # site where the Singles row is empty, the .save() cascades MandatoryError
    # across ~33 tests. Production sites configure these via the install/setup
    # UI; tests just need the validation to pass.
    #
    # SSH/DB credentials are never actually consumed during tests — the
    # event_application path doesn't open an SFTP connection unless a sync
    # job is triggered, which no test does. Dummy values are safe.
    try:
        _seed_mijnrood_sync_settings_dummy_credentials()
    except Exception as e:
        frappe.logger().warning(f"MijnRood Sync Settings seeding failed: {e}")


def _seed_verenigingen_test_system_user():
    """Create a test system user and wire it into Verenigingen Settings.

    The user is enabled, has the System Manager role (sufficient for
    ``utils.secure_operations.get_system_user_for_operation`` which only
    gates on user-exists + enabled), and uses a non-routable email domain
    so any test email leak is harmless.

    Deliberately does NOT add the ``Verenigingen Administrator`` role:
    it is a custom-fixture role loaded by ``bench migrate`` / ``bench
    import-fixtures``, neither of which runs on fresh CI sites created
    via ``bench new-site``. Appending a non-existent role link would make
    ``user.insert()`` throw and the outer ``try/except`` would silently
    log — leaving ``creation_user`` empty and reproducing the very B1
    failure this helper exists to fix.
    """
    test_user_email = "verenigingen-test-system@example.invalid"
    if not frappe.db.exists("User", test_user_email):
        user = frappe.new_doc("User")
        user.email = test_user_email
        user.first_name = "Verenigingen"
        user.last_name = "Test System"
        user.enabled = 1
        user.user_type = "System User"
        user.send_welcome_email = 0
        user.append("roles", {"role": "System Manager"})
        user.insert(ignore_permissions=True)
        frappe.db.commit()

    current = frappe.db.get_single_value("Verenigingen Settings", "creation_user")
    if current != test_user_email:
        # set_single_value writes the Singles row directly without firing
        # validate (which would trip on other reqd fields on a fresh site).
        frappe.db.set_single_value(
            "Verenigingen Settings", "creation_user", test_user_email
        )
        frappe.db.commit()


def _seed_default_leaf_customer_group():
    """Ensure Selling Settings.customer_group and the user default both
    point at a leaf (is_group=0).

    Creates "Individual" (or reuses any leaf) under the root if needed.

    Both the Single and the user-level default must agree on a leaf:
    - The Single is read by `services.customer_group_resolver` and by
      ERPNext's Customer form defaults.
    - The user-level default (`frappe.db.set_default("customer_group", ...)`)
      is what `frappe.new_doc("Customer")` inherits when the caller doesn't
      set the field explicitly. ERPNext's Customer controller would reject
      a root-group inherited value with "Cannot select a Group type
      Customer Group".
    """
    leaf = frappe.db.get_value(
        "Customer Group", {"name": "Individual", "is_group": 0}, "name"
    ) or frappe.db.get_value(
        "Customer Group", {"is_group": 0}, "name", order_by="name asc"
    )

    if not leaf:
        # No leaf exists — create "Individual" under the root.
        root = frappe.db.get_value(
            "Customer Group", {"is_group": 1, "parent_customer_group": ["in", ("", None)]}, "name"
        )
        if not root:
            # No tree at all (unlikely after erpnext_before_tests, but safe).
            return
        group = frappe.new_doc("Customer Group")
        group.customer_group_name = "Individual"
        group.parent_customer_group = root
        group.is_group = 0
        group.insert(ignore_permissions=True)
        leaf = group.name
        frappe.db.commit()

    current_single = frappe.db.get_single_value(
        "Selling Settings", "customer_group"
    )
    current_default = frappe.db.get_default("customer_group")
    needs_commit = False
    if current_single != leaf:
        frappe.db.set_single_value("Selling Settings", "customer_group", leaf)
        needs_commit = True
    if current_default != leaf:
        frappe.db.set_default("customer_group", leaf)
        needs_commit = True
    if needs_commit:
        frappe.db.commit()


def _seed_mijnrood_sync_settings_dummy_credentials():
    """Populate the reqd fields on MijnRood Sync Settings with placeholder
    test-fixture values.

    Fields seeded: ssh_host, ssh_username, db_name, db_username, db_password.
    Tests that mutate the Single via ``.save(ignore_permissions=True)``
    (mainly the StatusMappingSetupMixin in event_application tests) cascade
    MandatoryError on a fresh CI site where the Singles row is empty.

    ``flags.ignore_mandatory = True`` is set on the seeder's save only —
    it bypasses ``_validate_mandatory`` so we can populate any subset of
    empty reqd fields in one pass. It has nothing to do with how the
    password is stored: ``Document._save_passwords`` always runs as part
    of ``save()`` and writes the value encrypted to the ``__Auth`` table,
    replacing the in-memory attribute with the masked asterisk string.
    Plaintext never lands in ``tabSingles``. Subsequent test ``.save()``
    calls don't carry the flag but validate cleanly because all five
    fields are now populated.

    The credentials are placeholders, not "nowhere-used dummies": they
    are written to the DB. They're safe because the event_application
    test path never opens an SFTP/DB connection — the only consumer is
    the scheduled sync job, which is gated by ``settings.enabled=0``
    (the default and not touched here).

    Idempotent: returns early if all reqd fields already have values.
    """
    if not frappe.db.exists("DocType", "MijnRood Sync Settings"):
        # mijnrood_sync module not installed on this site; nothing to do.
        return

    settings = frappe.get_single("MijnRood Sync Settings")
    defaults = {
        "ssh_host": "test.mijnrood.invalid",
        "ssh_username": "test_user",
        "db_name": "test_db",
        "db_username": "test_user",
    }

    dirty = False
    for field, dummy in defaults.items():
        if not settings.get(field):
            settings.set(field, dummy)
            dirty = True

    if not settings.get_password("db_password", raise_exception=False):
        settings.db_password = "test_db_password"
        dirty = True

    if not dirty:
        return

    settings.flags.ignore_mandatory = True
    settings.save(ignore_permissions=True)
    frappe.db.commit()

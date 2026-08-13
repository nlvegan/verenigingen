"""
Test setup hooks for Verenigingen app.

This module provides the before_tests hook that ensures ERPNext test fixtures
(Company, etc.) are created before our tests run.
"""
import frappe

from verenigingen.tests.harness_logger import get_harness_logger

# Not `frappe.logger()`: that one sits at ERROR under `bench run-tests`, so every
# warning below was discarded. See verenigingen/tests/harness_logger.py.
logger = get_harness_logger("setup")

# Marks the workflow-action-email no-op so the patch can be recognised whichever
# of its two application sites installed it. See disable_workflow_action_emails.
_NOOP_MARKER = "_verenigingen_test_noop"


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

    Raises rather than logging on failure. A test run in which this did not take
    is not a degraded test run, it is a test run where every Member insert
    renders a PDF and can raise ``OSError: ... HostNotFoundError`` — a storm of
    unrelated failures far from this cause, which is the #291 shape exactly
    (#314).
    """
    from frappe.workflow.doctype.workflow_action import workflow_action

    def _noop_send_workflow_action_email(*args, **kwargs):
        return None

    setattr(_noop_send_workflow_action_email, _NOOP_MARKER, True)
    workflow_action.send_workflow_action_email = _noop_send_workflow_action_email

    # Assert the postcondition instead of trusting the assignment. The entire
    # purpose of this function is a side effect on another module's namespace,
    # and "it did not raise" is not evidence that the side effect took.
    if not workflow_action_emails_disabled():
        raise RuntimeError(
            "disable_workflow_action_emails() ran but "
            "workflow_action.send_workflow_action_email is not the test no-op. "
            "Every Member insert will render a PDF synchronously."
        )


def workflow_action_emails_disabled() -> bool:
    """True when the workflow-action email function is this module's no-op.

    Identified by a marker attribute rather than by object identity: the patch is
    applied from two places (this hook and the enhanced factory's import) and
    idempotency must not depend on which function object won.
    """
    from frappe.workflow.doctype.workflow_action import workflow_action

    return getattr(workflow_action.send_workflow_action_email, _NOOP_MARKER, False)


def _erpnext_before_tests_v16():
    """Create ERPNext's base test masters the v16.20 way.

    erpnext v16.20 removed ``erpnext.setup.utils.before_tests`` and replaced it
    with ``BootStrapTestData``, which is instantiated at *module import* of
    ``erpnext.tests.utils`` (a module-level ``BootStrapTestData()`` call). That
    creates the base masters once per process: Company, Territory tree, Customer
    Groups, Chart of Accounts, Fiscal Year, price lists, Modes of Payment, etc.
    Importing the module here triggers it before our tests need those masters.

    IMPORTANT: do NOT call ``setup_complete`` to create these — it duplicates the
    same records and then collides with ``BootStrapTestData``'s non-idempotent
    ``make_price_list``/``make_company`` (e.g. DuplicateEntryError on the
    "Standard Buying" Price List). ``BootStrapTestData`` must be the single
    creator. The import is cached, so triggering it from here and/or from a test
    module only runs it once.
    """
    import erpnext.tests.utils  # noqa: F401  (module-level BootStrapTestData() runs on import)

    # These helpers still exist in erpnext.setup.utils (only before_tests was
    # removed). Not guarded: this seeds the global default Company and fiscal
    # year for the whole suite, and continuing without them means every later
    # Customer / Member / Donation creation fails somewhere else with a message
    # that does not name this cause (#309, #314). If a future erpnext drops or
    # renames them, an ImportError naming them is the outcome worth having.
    from erpnext.setup.utils import enable_all_roles_and_domains, set_defaults_for_tests

    enable_all_roles_and_domains()
    set_defaults_for_tests()

    frappe.db.commit()


def before_tests():
    """
    Hook called before running tests for this app.

    Ensures ERPNext's test fixtures (Company, Item, etc.) are set up,
    since our app depends on ERPNext DocTypes.
    """
    # Suppress slow synchronous workflow-action emails (see function docstring)
    disable_workflow_action_emails()

    # Ensure ERPNext's base test masters (Company, Territory tree, Chart of
    # Accounts, Fiscal Year, Customer Groups, default roles) exist. erpnext used
    # to expose this as erpnext.setup.utils.before_tests, but v16.20 removed it,
    # so prefer that entry point for older erpnext and otherwise reimplement it
    # inline against the v16 setup wizard (see _erpnext_before_tests_v16).
    try:
        from erpnext.setup.utils import before_tests as erpnext_before_tests

        erpnext_before_tests()
    except ImportError:
        # Version dispatch, not a swallow: erpnext v16.20 removed this entry
        # point, and the ImportError branch is the one that runs on this bench
        # (measured). The generic `except Exception` that used to sit below it
        # WAS a swallow -- it hid a failure of the whole ERPNext base-master
        # bootstrap at log level INFO, and everything seeded after it assumes
        # that bootstrap succeeded.
        _erpnext_before_tests_v16()

    # Ensure all test companies exist by loading Company test records
    # ERPNext Account fixtures require: _Test Company, _Test Company 1,
    # _Test Company with perpetual inventory
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

    # NOTE: the current-year Fiscal Year company-restriction fix is applied from
    # EnhancedTestCase.setUp (once per session), NOT here. before_tests runs too
    # early: frappe's before_test_setup runs make_test_records(global_test_dependencies)
    # -- including "Company", which triggers erpnext's set_defaults_for_tests and
    # RE-restricts the current FY -- AFTER this hook returns. See
    # ensure_test_fiscal_year_for_all_companies() docstring.

    # Ensure Customer test records exist (needed by Item Price and other ERPNext fixtures)
    from frappe.test_runner import make_test_records

    if not frappe.db.exists("Customer", "_Test Customer"):
        make_test_records("Customer", verbose=False, force=True, commit=True)
        frappe.db.commit()

    # Seed the Mode of Payment records the app and many tests depend on
    # (Bank Transfer, SEPA Direct Debit, Mollie, Manual, Cash). The same helper
    # is wired into after_migrate for production sites; CI sites are bench-new
    # without migrate, so the records are missing at test-time and
    # Member.payment_method / Donation.mode_of_payment link validation fails
    # with "Could not find Payment Method: <name>" across ~119 tests.
    from verenigingen.services.member.approval.application_helpers import (
        ensure_payment_modes_exist,
    )

    ensure_payment_modes_exist()

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
    _seed_verenigingen_test_system_user()

    # Reset Selling Settings.customer_group away from the root "All Customer
    # Groups" that erpnext_before_tests() sets. ERPNext's Customer controller
    # rejects any Customer Group with is_group=1 with "Cannot select a Group
    # type Customer Group" (~72 fails). Production code already uses
    # services.customer_group_resolver.resolve_non_group_customer_group() to
    # work around the bad default; this matches the resolver's behaviour for
    # tests that bypass it by writing customer.customer_group directly.
    _seed_default_leaf_customer_group()

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
    _seed_mijnrood_sync_settings_dummy_credentials()

    # Seed the default Team Role master records (Team Leader, Team Member,
    # Coordinator, Secretary, Treasurer, Verenigingen Auditor) once for the whole
    # test run. Team / Team Member tests reference these by name; on a fresh CI
    # site they don't exist, so several test modules created them ad-hoc in setUp.
    # The production seeder (setup/__init__.py:create_default_team_roles) is
    # idempotent (existence-checked per role), so this is safe to run every run.
    #
    # Not guarded, for the same reason as the call in ensure_member_test_masters:
    # a missing Team Role surfaces as a link-validation failure in an unrelated
    # test, and the seeder being existence-checked means raising cannot cause a
    # spurious failure (#309, #314).
    _seed_default_team_roles()


def ensure_member_test_masters():
    """Idempotently seed the master records member-domain tests depend on.

    The app's ``before_tests`` hook seeds these for a full suite run, but it is
    UNRELIABLE for single-module runs in the current erpnext-v16 setup (its
    bootstrap raises an uncaught error), so any module run in ISOLATION must
    seed its own masters. This helper bundles the individual idempotent seeders
    so a test module only needs one call in ``setUpClass``.

    Seeds:
    - Verenigingen Settings.creation_user (a real, enabled non-Administrator
      system user) — required by ``utils.secure_operations`` for the
      customer<->donor link, application submission, etc.
    - Payment modes (Bank Transfer, SEPA Direct Debit, ...) — Member.payment_method
      and Donation.mode_of_payment link validation.
    - Default Team Role masters.

    Every called seeder is existence-checked / idempotent, so this is safe to
    call from every module's ``setUpClass`` (it short-circuits when masters are
    already present).
    """
    # ERPNext base masters (Company, Territory tree, Customer Groups, ...) must
    # exist before any of the seeders/tests below that create Customers, Members
    # or Donations — otherwise customer creation fails with
    # "Could not find Territory: All Territories".
    ensure_erpnext_base_masters()

    _seed_verenigingen_test_system_user()

    from verenigingen.services.member.approval.application_helpers import (
        ensure_payment_modes_exist,
    )

    ensure_payment_modes_exist()

    # A leaf Customer Group WITH a default selling Price List is required for the
    # membership-application invoice path (Sales Invoice.selling_price_list is a
    # reqd field resolved from the Customer Group). Without this, isolated module
    # runs fail invoice creation. Idempotent / existence-checked internally.
    _seed_default_leaf_customer_group()

    # Not guarded. Team Role is hardcoded-by-name master data that tests resolve
    # by that name; a missing one surfaces as a link-validation failure in an
    # unrelated test rather than here. The seeder is existence-checked and
    # idempotent, so raising cannot cause a spurious failure (#309, #314).
    _seed_default_team_roles()


def ensure_erpnext_base_masters():
    """Idempotently ensure ERPNext's base test masters exist for isolated runs.

    The ``before_tests`` hook seeds the ERPNext base masters (Company, the
    Territory tree incl. "All Territories", Customer Groups, Chart of Accounts,
    Modes of Payment, ...) via ``_erpnext_before_tests_v16`` for full-suite runs.
    A single-module ``run-tests --module`` run does NOT execute ``before_tests``,
    so on a fresh/snapshot site those masters are absent and any Customer/Member/
    Donation creation fails with "Could not find Territory: All Territories".

    Importing ``erpnext.tests.utils`` runs its module-level ``BootStrapTestData()``
    once per process (the import is cached), which creates all of the above. We
    only trigger it when the root Territory is missing, so this is a cheap no-op
    once seeded.
    """
    if frappe.db.exists("Territory", "All Territories"):
        ensure_netherlands_territory()
        return

    import erpnext.tests.utils  # noqa: F401  (module-level BootStrapTestData() runs on import)

    # set_defaults_for_tests wires the global default Company / fiscal year etc.
    #
    # Not guarded. This runs only on the branch where the Territory tree was
    # absent, i.e. a site with no ERPNext base masters at all; continuing past a
    # failure here leaves the global defaults unset and every later Customer /
    # Member / Donation creation fails somewhere else with a message that does
    # not name this cause (#309, #314). If a future erpnext drops or renames
    # these, an ImportError naming them is the outcome worth having.
    from erpnext.setup.utils import enable_all_roles_and_domains, set_defaults_for_tests

    enable_all_roles_and_domains()
    set_defaults_for_tests()

    frappe.db.commit()

    # set_defaults_for_tests restricts the current-year Fiscal Year to the default
    # company; undo that here too so --module self-seeding matches before_tests.
    ensure_test_fiscal_year_for_all_companies()

    ensure_netherlands_territory()


def ensure_netherlands_territory():
    """Guarantee the "Netherlands" Territory exists. Idempotent.

    Nothing else creates it. ERPNext's country Territory comes from the setup
    wizard, and the only ``before_tests`` hook on this bench is hrms's, which calls
    ``setup_complete()`` with ``country="India"`` -- so a fresh site gets the
    *India* territory (this is also where the site's Asia/Kolkata timezone comes
    from). Meanwhile fixtures across this app hardcode ``territory="Netherlands"``.

    It used to be created only inside ``EnhancedTestDataFactory._ensure_master_data``,
    behind two nested swallows that logged to a file rather than stdout. When a
    shard reshuffle moved a test that builds a Customer to position 1 of its shard,
    the missing territory surfaced as ``LinkValidationError: Could not find
    Territory: Netherlands`` in a test that had nothing to do with the change that
    triggered it (#291). Owning it here means both harnesses get it -- the factory
    covers the 780 EnhancedTestCase files, but the 289 VereningingenTestCase files
    never called it.

    Deliberately NOT tracked for cleanup: a country-level Territory is shared with
    production Customer/Supplier records, so per-test drains must not delete it.
    """
    if frappe.db.exists("Territory", "Netherlands"):
        return

    frappe.get_doc(
        {
            "doctype": "Territory",
            "territory_name": "Netherlands",
            "parent_territory": "All Territories",
        }
    ).insert(ignore_permissions=True)


def ensure_root_department():
    """Guarantee the root ``All Departments`` exists, named exactly that. Idempotent.

    ``Chapter.after_insert()`` calls ``_sync_department()``, which parents its
    department under the hardcoded name ``All Departments``. Same shape as the
    Territory above: hardcoded name, ``db.exists``-gated, untracked, and shared
    with production data, so per-test drains must not delete it (#309).

    It must be created WITHOUT a company. ``Department.autoname`` reads::

        if self.company:
            self.name = get_abbreviated_name(self.department_name, self.company)
        else:
            self.name = self.department_name

    so passing a company yields ``All Departments - _TC``, which satisfies nobody:
    not the ``db.exists("Department", "All Departments")`` guard that precedes the
    insert, and not ``_sync_department``'s parent lookup. The factory's version did
    pass a company, so on any site where its branch actually fired it created the
    wrong record and then re-created it on every subsequent call. Nobody saw that,
    because the whole block sat behind a swallow whose warning went nowhere.
    ERPNext's own ``create_default_departments`` omits company on this record for
    the same reason; ``company`` is ``reqd``, hence ``ignore_mandatory``.
    """
    if frappe.db.exists("Department", "All Departments"):
        return

    frappe.get_doc(
        {
            "doctype": "Department",
            "department_name": "All Departments",
            "is_group": 1,
            "parent_department": "",
        }
    ).insert(ignore_permissions=True, ignore_mandatory=True)

    # "It did not raise" is not evidence the record landed under the name every
    # caller hardcodes -- that is exactly how the company-suffixed version went
    # unnoticed.
    if not frappe.db.exists("Department", "All Departments"):
        raise RuntimeError(
            "Root Department 'All Departments' still does not exist after creating it; "
            "Chapter.after_insert() -> _sync_department() will fail for every chapter."
        )


def ensure_test_fiscal_year_for_all_companies():
    """Guarantee a Fiscal Year covers today() and applies to EVERY company.

    Two date-driven failure modes this prevents -- both recur every new calendar
    year, which is why there is deliberately NO hardcoded year here:

    1. Company-restricted current FY. erpnext's ``set_defaults_for_tests`` links
       the current calendar year's Fiscal Year to the default company
       (``_Test Company``) via the FY ``companies`` child table, which RESTRICTS
       the FY to that one company. Any test that posts a dated document against a
       different company (e.g. ``_Test Company 2``) then fails with
       "Date <today> is not in any active Fiscal Year for <company>". Clearing the
       child table makes the FY apply to all companies (erpnext treats an empty
       ``companies`` table as "all companies").
    2. Missing FY. On a fresh site, or once the wall clock passes the bootstrap's
       pre-seeded range, no Fiscal Year covers today(). The production helper
       ``ensure_fiscal_year_exists`` creates the calendar-year FY for today().

    Idempotent and date-driven, so it self-heals every January with zero edits --
    no recurrence in 2027 and beyond.
    """
    # Unguarded deliberately. The swallow here was worse than a silent skip: the
    # un-restriction below and its commit ran ONLY on the success path, so a
    # failure part-way through left a company-RESTRICTED Fiscal Year in place --
    # strictly worse than no FY at all, and the exact trap documented at
    # `tests/setup/__init__.py` for the re-restriction cascade. Failing here says
    # so; logging produced an order-dependent "Posting Date ... not in any active
    # Fiscal Year" across whole shards instead (#309).
    from frappe.utils import today

    from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
        ensure_fiscal_year_exists,
    )

    company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
        "Company", {}, "name"
    )
    fy_name = ensure_fiscal_year_exists(today(), company)
    # Drop any single-company restriction so the current FY covers every
    # company the tests use (multi-company tests post against _Test Company 2).
    cleared = 0
    if fy_name and frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
        cleared = frappe.db.count("Fiscal Year Company", {"parent": fy_name})
        frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
    frappe.db.commit()
    logger.info(
        f"ensure_test_fiscal_year_for_all_companies: fy={fy_name} cleared_company_restrictions={cleared}"
    )


def ensure_default_company():
    """Guarantee a global default Company is set for the test session.

    Several code paths rely on the framework default company being set:
    - the Opportunity ``company`` field's ``:Company`` default (mandatory on
      erpnext v16 -- an empty default raises MandatoryError, breaking CRM
      opportunity creation from contact requests);
    - Mollie payment-gateway cash-account resolution ("No cash account found for
      company ''").

    On a fresh CI site erpnext's ``set_defaults_for_tests`` does not reliably
    leave a global default company set, so those paths get an empty company.
    Production sites always have one; set it here for parity. Idempotent.
    """
    if frappe.defaults.get_global_default("company"):
        return
    company = frappe.db.get_value("Company", "_Test Company", "name") or frappe.db.get_value(
        "Company", {}, "name"
    )
    if not company:
        return
    frappe.db.set_single_value("Global Defaults", "default_company", company)
    frappe.db.set_default("company", company)
    frappe.db.commit()
    logger.info(f"ensure_default_company: set global default company={company}")


def _seed_verenigingen_test_system_user():
    """Create a test system user and wire it into Verenigingen Settings.

    The user is enabled, has the System Manager role (sufficient for
    ``utils.secure_operations.get_system_user_for_operation`` which only
    gates on user-exists + enabled), and uses a non-routable email domain
    so any test email leak is harmless.

    Roles: System Manager (for ``get_system_user_for_operation``) PLUS
    ``Verenigingen Staff`` — the latter grants Customer create/write, which
    ``Member.after_insert`` -> ``create_customer_for_member`` needs when an
    application is submitted as this user (without it, submit_application fails
    with "Insufficient permissions to create Customer" and the whole
    membership-application test cohort errors).

    ``Verenigingen Staff`` is a custom-fixture role loaded by ``bench migrate`` /
    ``bench import-fixtures``, which do NOT run on fresh CI sites created via
    ``bench new-site``. Appending a non-existent role link would make
    ``user.insert()`` throw, so it is added only when the Role actually exists.
    (We must NOT add ``Verenigingen Administrator`` — same fixture-role caveat.)
    """
    test_user_email = "verenigingen-test-system@example.invalid"
    desired_roles = ["System Manager"]
    if frappe.db.exists("Role", "Verenigingen Staff"):
        desired_roles.append("Verenigingen Staff")

    if not frappe.db.exists("User", test_user_email):
        user = frappe.new_doc("User")
        user.email = test_user_email
        user.first_name = "Verenigingen"
        user.last_name = "Test System"
        user.enabled = 1
        user.user_type = "System User"
        user.send_welcome_email = 0
        for role in desired_roles:
            user.append("roles", {"role": role})
        user.insert(ignore_permissions=True)
        frappe.db.commit()
    else:
        # Roles aren't re-applied to an already-existing (reused) user above, so
        # ensure the desired roles are present.
        user = frappe.get_doc("User", test_user_email)
        existing_roles = {r.role for r in user.roles}
        missing = [r for r in desired_roles if r not in existing_roles]
        if missing:
            for role in missing:
                user.append("roles", {"role": role})
            user.save(ignore_permissions=True)
            frappe.db.commit()

    # After the audit #2 Rule-5 cap, HIGH/CRITICAL API access is grantable ONLY
    # through an assigned role PROFILE -- a bare role (even System Manager) tops out
    # at MEDIUM. The creation_user drives automated privileged operations that call
    # decorated endpoints in-process (e.g. create_volunteer_from_member
    # @high_security_api during application approval, assign_member_to_chapter
    # @critical_api during chapter assignment), so it must carry a profile granting
    # those tiers or those operations fail closed. Assign the highest-tier profile
    # that exists as a fixture on this site (guarded like the roles above; a
    # non-existent profile -- or its synced roles -- would make save() throw on a
    # bare CI site).
    for profile_name in ("Verenigingen Administrator", "Verenigingen Staff"):
        if not frappe.db.exists("Role Profile", profile_name):
            continue
        user = frappe.get_doc("User", test_user_email)
        assigned = {rp.role_profile for rp in (user.get("role_profiles") or [])}
        if profile_name not in assigned:
            user.set("role_profiles", [{"role_profile": profile_name}])
            user.role_profile_name = profile_name
            user.save(ignore_permissions=True)
            frappe.db.commit()
            try:
                from verenigingen.utils.security.api_security_framework import get_security_framework

                get_security_framework().auth_engine.invalidate_user_cache(test_user_email)
            except Exception as cache_error:
                # Genuinely best-effort: the cache TTL bounds how long a stale
                # entry can last. Logged rather than silent, so a systematic
                # failure here is at least visible (#309).
                logger.warning(f"Security cache invalidation failed: {cache_error}")
        break

    current = frappe.db.get_single_value("Verenigingen Settings", "creation_user")
    if current != test_user_email:
        # set_single_value writes the Singles row directly without firing
        # validate (which would trip on other reqd fields on a fresh site).
        frappe.db.set_single_value(
            "Verenigingen Settings", "creation_user", test_user_email
        )
        frappe.db.commit()

        # "It did not raise" is not evidence the write took. `set_single_value`
        # writes the Singles row directly, and an empty `creation_user` makes
        # `get_system_user_for_operation` raise ConfigurationError (~91 tests)
        # and cascades MandatoryError on any later `.save()` of the Single
        # (~71 more) -- none of which name this seeding step (#309).
        if frappe.db.get_single_value("Verenigingen Settings", "creation_user") != test_user_email:
            raise RuntimeError(
                "Verenigingen Settings.creation_user did not take after seeding; "
                "get_system_user_for_operation will raise ConfigurationError in every "
                "test that reaches it."
            )

    # Seed Verenigingen Settings.company. The membership-application invoice path
    # (services/member/approval/application_payments.create_membership_invoice_with_amount)
    # stamps Sales Invoice.company from this Single; on a fresh/snapshot site it
    # is empty, so the invoice insert fails and approval returns invoice=None.
    # Full-suite/production runs configure this via setup; an isolated --module
    # run does not, so seed it here. Prefer a EUR company (SEPA/currency-clean),
    # matching the canonical pattern in the chapter edge-case test.
    #
    # Self-heal a STALE value too (not just an empty one): a co-located test can
    # delete the company this Single points at, after which the chapter
    # cost-center resolver's frappe.db.exists() check fails and it falls through
    # to the ambiguous "Multiple active companies found" branch and returns None
    # (with ERPNext's 20 test companies present, the single-company shortcut never
    # fires). Re-seed whenever the configured company is missing or gone.
    #
    # NB: deliberately do NOT also seed Global Defaults.default_company. The
    # resolver's FIRST source (Verenigingen Settings.company) is enough, and
    # seeding the framework-wide default company has side effects on unrelated
    # code that reads it -- e.g.
    # services.volunteer.volunteer_expense_setup.get_organization_cost_center,
    # which then takes its create-cost-center branch and flips tests that assert
    # "no default company configured" into a different (and currently buggy)
    # path. Keep the heal scoped to the field the chapter resolver prefers.
    configured_company = frappe.db.get_single_value("Verenigingen Settings", "company")
    if not configured_company or not frappe.db.exists("Company", configured_company):
        company = (
            frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
            or frappe.db.get_value("Company", {}, "name")
        )
        if company:
            frappe.db.set_single_value("Verenigingen Settings", "company", company)
            frappe.db.commit()

    # Clear a stale global ``default_warehouse`` default that belongs to a
    # company OTHER than Verenigingen Settings.company. ERPNext auto-fills the
    # ItemDefault.default_warehouse Link field from this global default when it
    # is left empty; if that warehouse belongs to a different company, the
    # membership Item insert (a non-stock service item that needs no warehouse)
    # fails with "Warehouse <x> doesn't belong to Company <y>", which surfaces
    # as "Unable to create membership item" and breaks the whole
    # approval -> invoice path. A snapshot/CI site can carry a leftover default
    # from an unrelated company's tests (e.g. "Stores - TQC" from "Test Quality
    # Company"). Production sites set this default to a warehouse of their own
    # company, so this only bites isolated test runs.
    # Unguarded: every statement is a read or an existence-gated clear, so there
    # is no expected failure to absorb. If this does not take, the leftover
    # default stays and the membership Item insert fails with "Warehouse <x>
    # doesn't belong to Company <y>" -- which is the failure the comment above
    # describes, arriving without naming this cause (#309).
    ver_company = frappe.db.get_single_value("Verenigingen Settings", "company")
    global_wh = frappe.defaults.get_global_default("default_warehouse")
    if global_wh:
        wh_company = frappe.db.get_value("Warehouse", global_wh, "company")
        if wh_company and ver_company and wh_company != ver_company:
            frappe.defaults.clear_default("default_warehouse")
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

    # Give the leaf Customer Group a default selling Price List. ERPNext resolves
    # Sales Invoice.selling_price_list (a reqd field) from the Customer's, then
    # the Customer Group's, default_price_list — NOT from Selling Settings (see
    # erpnext.accounts.party.set_price_list / get_default_price_list). On a fresh
    # CI/snapshot site the seeded "Individual" group has none, so the membership
    # invoice insert fails with a MandatoryError on selling_price_list /
    # price_list_currency / plc_conversion_rate, which surfaces as the swallowed
    # "Failed to create membership invoice". Prefer a selling Price List whose
    # currency matches the company configured in Verenigingen Settings so the
    # conversion rate resolves to 1.0.
    if not frappe.db.get_value("Customer Group", leaf, "default_price_list"):
        company_currency = None
        ver_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if ver_company:
            company_currency = frappe.db.get_value("Company", ver_company, "default_currency")
        price_list = None
        if company_currency:
            price_list = frappe.db.get_value(
                "Price List",
                {"selling": 1, "enabled": 1, "currency": company_currency},
                "name",
                order_by="name asc",
            )
        price_list = price_list or frappe.db.get_value(
            "Price List", {"selling": 1, "enabled": 1}, "name", order_by="name asc"
        )
        if price_list:
            frappe.db.set_value(
                "Customer Group", leaf, "default_price_list", price_list, update_modified=False
            )
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


def _seed_default_team_roles():
    """Create the default Team Role master records for the test run.

    Delegates to the production seeder
    ``verenigingen.setup.create_default_team_roles``, which is idempotent (it
    checks ``frappe.db.exists("Team Role", name)`` per role and commits once).
    The production function prints progress to stdout; we suppress that here to
    keep test output clean.
    """
    if not frappe.db.exists("DocType", "Team Role"):
        # Team Role doctype not installed on this site; nothing to do.
        return

    import contextlib
    import io

    from verenigingen.setup import create_default_team_roles

    with contextlib.redirect_stdout(io.StringIO()):
        create_default_team_roles()

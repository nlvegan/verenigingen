"""Apply the SEPA creditor identity a test class needs -- and prove it landed.

Why this exists
---------------
Five test classes each carried their own ``_setup_sepa_*`` helper that wrote SEPA
settings from ``setUpClass`` inside a ``try/except``. Three of them had never once
succeeded, and the ``except`` is what made that invisible:

* ``test_direct_debit_batch_refactoring`` (#513) -- 12 swallowed failures in a
  single 14-test run on test_site_4, every one of them
  ``Could not find Webhook User: webhook-user@test-site-4.local``. The Single
  carries a **dangling** ``webhook_user`` Link, so ``save()`` fails link
  validation on a field the SEPA configuration does not own and never reaches
  the fields it does. Measured source of the dangling link:
  ``verenigingen.tests.test_webhook_user_setup`` took test_site_4 from
  ``referent_exists=True`` to ``referent_exists=False`` across 21 green tests
  (it deletes the site's canonical webhook User and then restores the Single to
  the value that named it). Fixed at that end too.
* ``test_sepa_xml_compliance`` (#466) and ``test_service_layer_validation`` --
  both wrote ``sepa_creditor_id`` / ``company_iban`` / ``company_bic`` /
  ``enable_strict_sepa_validation`` onto *Verenigingen Settings*, where **none of
  those four fields exist** (#466 reported two of them; the meta check found
  four). Assigning a nonexistent field on a Frappe Document is a silent no-op,
  so the only assignment that did anything was ``company = "Test Vereniging"``
  -- a Company that does not exist either, which made ``save()`` throw and took
  the rest of the helper down with it.

Nothing here catches. A test class that believes it is configured and is not is
worse than a red one, and both issues are cases of exactly that.

How it defends against both shapes
----------------------------------
1. **Writes bypass document validation** (``frappe.db.set_single_value``), so a
   broken Link in a field this configuration does not own -- ``webhook_user`` --
   cannot defeat it. ``Verenigingen Payments Settings`` has no ``on_update``, so
   no hook is lost; ``validate()`` is the only thing skipped, and it is
   validating somebody else's field.
2. **Every fieldname is checked against ``frappe.get_meta`` before it is
   written**, and every Link value is checked to exist. That is what turns
   #466's silent no-op into a named failure. Measured on test_site_4, the write
   paths do not report it and only the read path does: ``doc.attr = value`` is a
   silent no-op (#466's own path), ``frappe.db.set_single_value`` writes a
   ``tabSingles`` row for any fieldname with no error, and
   ``get_single_value`` raises ``Field <x> does not exist on <doctype>``. Doing
   the check up front means the failure names the field instead of surfacing as
   an unrelated read error later.
3. **Values are read back from the database afterwards**, so a write that was
   rolled back or overwritten is reported rather than assumed.

Deliberately NOT done here
--------------------------
* ``enable_strict_sepa_validation`` (#466) has **no** counterpart on either
  Single. The nearest real fields are ``Verenigingen Settings``
  ``.sepa_strict_mandate_validation`` and ``Verenigingen Payments Settings``
  ``.sepa_strict_period_mode``; neither is plainly what that name intended, and
  turning either on changes the behaviour of the modules under test. It is left
  unset and reported rather than guessed at.
* No restore. These five helpers have always left the values on the site's
  Single and the modules are written around that; adding a class-scoped restore
  is a separate change with its own blast radius. ``own_settings_company``
  (``tests/support/verenigingen_settings.py``) is the tool for that when it is
  wanted.

Usage::

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_company = apply_sepa_test_configuration()
"""

import frappe

from verenigingen.tests.support.sepa_test_company import get_eur_test_company

SETTINGS = "Verenigingen Settings"
PAYMENTS_SETTINGS = "Verenigingen Payments Settings"

SEPA_TEST_CREDITOR_ID = "NL12ZZZ123456789"
SEPA_TEST_IBAN = "NL91ABNA0417164300"
SEPA_TEST_BIC = "ABNANL2A"
SEPA_TEST_ACCOUNT_HOLDER = "SEPA Test Account Holder"

# The complete set of fields this helper writes, as {doctype: {fieldname: value}}.
# Exported as a constant because tests/support/test_sepa_test_configuration.py
# asserts every fieldname here exists on its doctype -- the check #466 needed and
# that no caller was doing.
SEPA_TEST_FIELDS = {
    PAYMENTS_SETTINGS: {
        "creditor_id": SEPA_TEST_CREDITOR_ID,
        "company_iban": SEPA_TEST_IBAN,
        "company_bic": SEPA_TEST_BIC,
        "company_account_holder": SEPA_TEST_ACCOUNT_HOLDER,
    }
}


class SEPAConfigurationNotApplied(RuntimeError):
    """The SEPA test configuration could not be applied.

    Raised, never logged: every test in the calling class runs against this
    configuration, so a swallowed failure here is what makes a whole module pass
    without testing what it names (#513, #466).
    """


def apply_sepa_test_configuration(company: str | None = None) -> str:
    """Configure the SEPA creditor identity for a test class and return the company.

    Points ``Verenigingen Settings.company`` at a EUR company (SEPA invoice
    validation rejects non-EUR invoices) and writes the creditor id / IBAN / BIC
    / account holder onto ``Verenigingen Payments Settings``.

    Raises ``SEPAConfigurationNotApplied`` if anything did not land.
    """
    company = company or get_eur_test_company()

    _write_single(SETTINGS, {"company": company})
    for doctype, values in SEPA_TEST_FIELDS.items():
        _write_single(doctype, values)

    # Commit: EnhancedTestCase.tearDown rolls back after every test method, so an
    # uncommitted class fixture is gone by the time the second test runs.
    frappe.db.commit()

    # The config service caches the resolved settings (organization_name etc.) on
    # a module-level singleton, and Frappe caches the Single documents. Clear both
    # so the values written above are what the code under test reads.
    #
    # NOT frappe.clear_cache(): wiping the DocType meta cache mid-test drops field
    # defaults (e.g. SEPA Batch Upload Log.batch_status) and breaks inserts.
    frappe.clear_document_cache(SETTINGS, SETTINGS)
    frappe.clear_document_cache(PAYMENTS_SETTINGS, PAYMENTS_SETTINGS)
    from verenigingen.verenigingen_payments.services.sepa_configuration_service import (
        sepa_config_service,
    )

    sepa_config_service.refresh_settings_cache()

    verify_sepa_configuration(company)
    return company


def verify_sepa_configuration(company: str) -> None:
    """Read every configured value back from the database, raising on a mismatch.

    Separate from the write so a caller (or a pin) can ask "is this site actually
    configured?" without writing anything.
    """
    expected = {SETTINGS: {"company": company}}
    expected.update(SEPA_TEST_FIELDS)

    wrong = []
    for doctype, values in expected.items():
        for fieldname, value in values.items():
            actual = frappe.db.get_single_value(doctype, fieldname)
            if actual != value:
                wrong.append(f"{doctype}.{fieldname} is {actual!r}, expected {value!r}")
    if wrong:
        raise SEPAConfigurationNotApplied(
            "SEPA test configuration did not land: " + "; ".join(wrong)
        )


def _write_single(doctype: str, values: dict) -> None:
    """Write ``values`` onto a Single, after proving every field is real.

    ``frappe.db.set_single_value`` writes a ``tabSingles`` row for whatever
    fieldname it is given, and ``get_single_value`` reads that row straight back
    -- so a misspelled or removed field round-trips cleanly and a read-back check
    cannot see it. The meta check is the only thing that can (#466).
    """
    meta = frappe.get_meta(doctype)
    for fieldname, value in values.items():
        field = meta.get_field(fieldname)
        if not field:
            raise SEPAConfigurationNotApplied(
                f"{doctype} has no field {fieldname!r}. Assigning a nonexistent field on a "
                "Frappe Document is a silent no-op, which is how #466 configured nothing "
                "for months -- so this is raised, not skipped."
            )
        if field.fieldtype == "Link" and value and not frappe.db.exists(field.options, value):
            raise SEPAConfigurationNotApplied(
                f"{doctype}.{fieldname} would point at {field.options} {value!r}, "
                "which does not exist."
            )
        frappe.db.set_single_value(doctype, fieldname, value)

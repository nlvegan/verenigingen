"""Plant a EUR ``Company`` row newer than every real one, to pin company resolution.

Why this exists
---------------
``frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")`` has no
``order_by``, so it defaults to ``creation DESC`` and returns the **newest** match --
i.e. whatever EUR company the last co-tenant suite in the shard happened to create.
Test setup that resolves its company that way is the #394 bug class ("scan for a
fixture instead of owning one"), with the ordering trap on top.

Measured on ``test_site_2``, 2026-08-23: **30** EUR companies present, and that
expression returned ``'TEST EBkh Cleanup Cov Co'`` -- an e_boekhouden fixture -- while
``get_eur_test_company()`` returned the app's own ``'TEST-Payment-Integration-Company'``.
One of the 30 (``'EBH Migration Test Co'``) has no ``default_receivable_account`` and no
``default_income_account`` at all, which is exactly the chart-less company the borrow used
to hand to SEPA tests (#237, 101 failures).

Why a pin needs this
--------------------
A warm site under-reports in one direction and over-reports in the other: with 30 EUR
companies the assertion "the resolved company is the owned one" is red before the fix, but
on a **fresh** CI site where the owned company is the only EUR one it would be green
either way -- green for the wrong reason. Planting a decoy that is guaranteed newest makes
the pin discriminating on any site.

Why raw SQL and not ``frappe.new_doc("Company").insert()``
---------------------------------------------------------
* The doc path builds a Chart of Accounts. Measured in this repo: one test company inserts
  94 Accounts, 5 Warehouses, 2 Cost Centers, the Company and a Property Setter -- every one
  of which the captured-insert drain would then have to claim (or leak).
* The defect under test reads ``tabCompany`` and nothing else, so a bare row is exactly the
  surface it needs. If fixed code ever *dereferences* the decoy it fails loudly rather than
  passing quietly, which is the behaviour a pin wants.
* Nothing is committed, so the row cannot outlive the transaction even if a test dies
  between the insert and the delete -- the harness rollback removes it. The explicit
  ``DELETE`` in ``finally`` is belt-and-braces for the same-transaction case.

``test_eur_company_decoy.py`` is the control: it proves the decoy actually wins the buggy
query. A decoy that did not win would make every pin built on it pass vacuously.
"""

import uuid
from contextlib import contextmanager

import frappe

# Far enough ahead that no real fixture row can be newer, and obviously synthetic in a
# `SELECT * FROM tabCompany` if one ever escapes. MariaDB's NOW() truncates microseconds
# while real rows carry them, so "now" is not reliably "newest" -- a fixed future date is.
_DECOY_CREATION = "2099-01-01 00:00:00.000000"


@contextmanager
def newest_eur_company():
    """Yield the name of a EUR ``Company`` row that is newer than every other one.

    Deleted on the way out. Use it to wrap the *single call* whose company resolution is
    under test, not a whole test body -- the narrower the window, the less other code can
    stumble over a bare row.
    """
    name = f"ZZ Decoy EUR Co {uuid.uuid4().hex[:8]}"
    frappe.db.sql(
        """
        INSERT INTO `tabCompany`
            (`name`, `creation`, `modified`, `owner`, `modified_by`, `docstatus`,
             `company_name`, `abbr`, `default_currency`, `country`)
        VALUES (%(name)s, %(creation)s, %(creation)s, 'Administrator', 'Administrator', 0,
                %(name)s, %(abbr)s, 'EUR', 'Netherlands')
        """,
        {"name": name, "creation": _DECOY_CREATION, "abbr": f"ZD{uuid.uuid4().hex[:4]}"},
    )
    try:
        yield name
    finally:
        frappe.db.sql("DELETE FROM `tabCompany` WHERE `name` = %s", name)


def scan_by_currency() -> str:
    """The defective expression, in one place, so pins can name what they are pinning.

    Deliberately NOT called by any production or fixture code -- see
    ``test_no_company_scan_by_currency`` for the guard that keeps it that way.
    """
    return frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")

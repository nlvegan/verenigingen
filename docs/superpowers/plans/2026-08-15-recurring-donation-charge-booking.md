# Recurring Donation Charge Booking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Mollie charges a recurring donor, the charge becomes its own paid Donation and the existing webhook pipeline books it to the ledger.

**Architecture:** A recurring charge arrives on the payment webhook carrying `subscriptionId` and (usually) `metadata.donation_id`. A new service resolves the *origin* donation from those, then inserts a Donation for the charge carrying `payment_id = <charge id>`. Control then falls through to the webhook's existing flow, which — because the charge now has a Donation of its own — creates the Bank Transaction and Journal Entry, writes payment history, and keeps refund and chargeback handling working, all unmodified.

**Tech Stack:** Frappe v15/v16, Python 3, MariaDB, `mollie-api-python` SDK, `EnhancedTestCase` (`verenigingen/tests/fixtures/enhanced_test_factory.py`).

**Spec:** `docs/superpowers/specs/2026-08-15-recurring-donation-charges-design.md`. Read it before starting; this plan implements Part A only.

## Global Constraints

- **Never run tests against `veg11.veganisme.org`.** It is the live site and is served out of the main git working tree. Use `test_site_1`.
- Work happens in the worktree `/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges` on branch `fix/recurring-donation-charge-booking`, which is based on `origin/fix/donation-subscription-activation` (PR #346). Do **not** check that branch out in the main tree.
- Run a module's tests against this branch's code with:
  `cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_1 run-tests --app verenigingen --module <module>`
  Verify the worktree is actually in play first:
  `PYTHONPATH=<worktree> ./env/bin/python -c "import verenigingen; print(verenigingen.__file__)"`
- **`run-tests --module A --module B` runs only B.** One `--module` per invocation.
- **Always diff a red run against the same command with no `PYTHONPATH`**, or you cannot tell your failure from a pre-existing one.
- This bench has live Mollie test credentials in `sites/common_site_config.json`; CI has none. Before claiming CI will pass, run gateway-touching modules through
  `scripts/testing/run_without_credentials.sh test_site_1 <module>`.
- `frappe.logger().warning(...)` writes **nothing** under `bench run-tests` — bare loggers default to level `ERROR`. Use `.error()` or `print()` for anything that must be seen.
- Never rewrite a JSON file with `json.dumps` to change a line. Edit by line.
- Line length 110 (`black`). Run the pre-commit-pinned `black`, not a different one, or the commit fails with "Stashed changes conflicted with hook auto-fixes".
- Python user-facing strings wrapped in `_()`.
- Commit messages follow Conventional Commits and end with:
  `Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq`
- Every new assertion must be **mutation-proven**: break the production line it targets, watch the test go red, restore. A test that cannot fail is not evidence.

---

## File Structure

**Create:**
- `verenigingen/verenigingen_payments/mollie/services/recurring_donation_charge.py` — resolves the origin donation for a recurring charge and materializes the charge's own Donation. One public function. No booking logic: booking belongs to the pipeline it hands back to.
- `verenigingen/patches/v2_2/enforce_unique_donation_payment_id.py` — normalises `payment_id` `''` → `NULL`, auto-resolves duplicates, adds the unique index.
- `verenigingen/tests/payment/test_recurring_donation_charge.py` — the service and its webhook wiring.
- `verenigingen/tests/payment/test_donation_payment_id_uniqueness.py` — the patch and the `''` → `NULL` invariant.

**Modify:**
- `verenigingen/verenigingen_payments/mollie/utils/common_helpers.py` — add `read_payment_field` / `read_payment_metadata`, the shape-tolerant readers both the lookup and the service need.
- `verenigingen/verenigingen_payments/mollie/services/handlers/donation_lookup.py:26-77` — fix `find_for_subscription_payment`.
- `verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py:~444` — call the service, then fall through.
- `verenigingen/verenigingen_payments/utils/payment_gateways.py` — `webhookUrl` on both activation helpers; durable duplicate guard on the second.
- `verenigingen/verenigingen/doctype/donation/donation.json` — new `recurring_origin_donation` field.
- `verenigingen/verenigingen/doctype/donation/donation.py:277-285` — suppress the new-donation email on charge donations; normalise empty `payment_id` to `None`.
- `verenigingen/templates/pages/manage_donations.py:100-102` — exclude charge donations from the recurring list.
- `verenigingen/patches.txt` — register the patch.

---

## Task 1: Shape-tolerant payment field readers

A Mollie payment reaches this code in three shapes that are **not** interchangeable, and the existing code assumes one of them. `mollie.api.objects.payment.Payment` is a `dict` **subclass** with camelCase keys and snake_case properties; `_fetch_payment_from_mollie` returns a normalised snake_case dict; captured API JSON is a plain camelCase dict. `hasattr({...}, "subscription_id")` is `False`, which is precisely why `DonationLookup` (Task 3) silently returns nothing for two of the three.

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/utils/common_helpers.py`
- Test: `verenigingen/verenigingen_payments/mollie/tests/test_common_helpers.py`

**Interfaces:**
- Produces: `read_payment_field(payment: Any, snake_case: str, camel_case: Optional[str] = None) -> Any` and `read_payment_metadata(payment: Any) -> Dict[str, Any]`, both importable from `verenigingen.verenigingen_payments.mollie.utils.common_helpers`.

- [ ] **Step 1: Write the failing tests**

Append to `verenigingen/verenigingen_payments/mollie/tests/test_common_helpers.py`, and add
`read_payment_field, read_payment_metadata` to the existing `common_helpers` import block at the
top of that file:

```python
class TestPaymentFieldReaders(FrappeTestCase):
    """read_payment_field / read_payment_metadata — every shape a Mollie payment arrives in.

    Measured against the API: a subscription-generated charge carries
    sequenceType/subscriptionId/customerId/mandateId, and the subscription's
    metadata copied verbatim -- INCLUDING copying nothing. sub_5euSBaLzqF has no
    metadata, and its charges arrive with `metadata: null`, not `{}`.
    """

    def test_reads_camel_case_key_from_dict(self):
        # The SDK Payment is a dict subclass whose keys are camelCase.
        payment = {"id": "tr_x", "sequenceType": "recurring", "subscriptionId": "sub_x"}
        self.assertEqual(read_payment_field(payment, "sequence_type", "sequenceType"), "recurring")
        self.assertEqual(read_payment_field(payment, "subscription_id", "subscriptionId"), "sub_x")

    def test_reads_snake_case_key_from_normalised_dict(self):
        # _fetch_payment_from_mollie returns snake_case.
        payment = {"id": "tr_x", "sequence_type": "recurring", "subscription_id": "sub_x"}
        self.assertEqual(read_payment_field(payment, "sequence_type", "sequenceType"), "recurring")
        self.assertEqual(read_payment_field(payment, "subscription_id", "subscriptionId"), "sub_x")

    def test_reads_attribute_from_object(self):
        payment = SimpleNamespace(sequence_type="recurring", subscription_id="sub_x")
        self.assertEqual(read_payment_field(payment, "sequence_type", "sequenceType"), "recurring")

    def test_absent_field_is_none_in_every_shape(self):
        for payment in ({}, {"id": "tr_x"}, SimpleNamespace(id="tr_x")):
            with self.subTest(shape=type(payment).__name__):
                self.assertIsNone(read_payment_field(payment, "subscription_id", "subscriptionId"))

    def test_metadata_null_becomes_empty_dict(self):
        # The bug this exists to prevent: getattr(payment, "metadata", {}) returns
        # None, not {}, when the property exists and its value is null -- and
        # None.get("donation_id") raises.
        self.assertEqual(read_payment_metadata({"metadata": None}), {})
        self.assertEqual(read_payment_metadata(SimpleNamespace(metadata=None)), {})

    def test_metadata_dict_is_returned_as_is(self):
        self.assertEqual(
            read_payment_metadata({"metadata": {"donation_id": "Assoc-Dnt-2025-00752"}}),
            {"donation_id": "Assoc-Dnt-2025-00752"},
        )

    def test_metadata_non_dict_is_not_trusted(self):
        # Mollie's metadata is free-form; a string would break every .get() caller.
        self.assertEqual(read_payment_metadata({"metadata": "donation"}), {})
```

Add `from types import SimpleNamespace` to that file's imports if it is not already there.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.verenigingen_payments.mollie.tests.test_common_helpers
```

Expected: `ImportError: cannot import name 'read_payment_field'`.

- [ ] **Step 3: Implement**

Append to `verenigingen/verenigingen_payments/mollie/utils/common_helpers.py`:

```python
def read_payment_field(payment: Any, snake_case: str, camel_case: Optional[str] = None) -> Any:
    """Read one field from a Mollie payment, whichever shape it arrived in.

    Three shapes reach this code and they are not interchangeable:

    * ``mollie.api.objects.payment.Payment`` -- a ``dict`` SUBCLASS whose keys are
      camelCase and whose properties are snake_case;
    * the normalised snake_case dict ``_fetch_payment_from_mollie`` builds;
    * plain camelCase JSON straight from the API (captured fixtures).

    ``hasattr({...}, "subscription_id")`` is False, so an attribute-only reader
    returns nothing for two of the three -- the defect this replaces. Returns
    None when the field is absent in every shape.
    """
    camel_case = camel_case or snake_case

    if isinstance(payment, dict):
        for key in (snake_case, camel_case):
            if key in payment:
                return payment[key]
        return None

    value = getattr(payment, snake_case, None)
    if value is None:
        value = getattr(payment, camel_case, None)
    return value


def read_payment_metadata(payment: Any) -> Dict[str, Any]:
    """A Mollie payment's metadata, always as a dict.

    Mollie copies a subscription's metadata onto every charge it generates --
    including copying nothing. A subscription with no metadata yields
    ``metadata: null`` on its charges (measured: sub_5euSBaLzqF), and metadata is
    free-form, so a caller cannot assume a mapping. Anything that is not a dict
    becomes ``{}``.
    """
    metadata = read_payment_field(payment, "metadata")
    return metadata if isinstance(metadata, dict) else {}
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2. Expected: all pass, no other test in the module regresses.

- [ ] **Step 5: Mutation-prove two assertions**

Change `return metadata if isinstance(metadata, dict) else {}` to `return metadata or {}` and confirm
`test_metadata_non_dict_is_not_trusted` goes red. Change the `isinstance(payment, dict)` branch to
`if False:` and confirm `test_reads_camel_case_key_from_dict` goes red. Restore both.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/utils/common_helpers.py \
        verenigingen/verenigingen_payments/mollie/tests/test_common_helpers.py
git commit -m "feat(mollie): read a payment field whichever shape it arrives in

An SDK Payment is a dict subclass with camelCase keys; the normalised dict
_fetch_payment_from_mollie builds is snake_case; captured JSON is plain
camelCase. hasattr(dict, 'subscription_id') is False, so attribute-only
readers silently see nothing for two of the three.

read_payment_metadata additionally refuses to trust a non-dict: Mollie copies
a subscription's metadata onto every charge, including copying nothing, so
'metadata: null' is a real payload and None.get() raises.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 2: `recurring_origin_donation` field, and the email a charge should not send

Without a discriminator, a charge Donation is indistinguishable from the donation the donor signed up with. The donor portal lists every `status="Recurring"` donation as a cancellable subscription (Task 7), and `after_insert` thanks the donor for a new donation on every charge.

**Files:**
- Modify: `verenigingen/verenigingen/doctype/donation/donation.json`
- Modify: `verenigingen/verenigingen/doctype/donation/donation.py:277-285`
- Test: `verenigingen/tests/payment/test_recurring_donation_charge.py` (created here)

**Interfaces:**
- Produces: `Donation.recurring_origin_donation`, a `Link` to `Donation`, set only on charge donations. Later tasks filter on it and set it.

- [ ] **Step 1: Write the failing test**

Create `verenigingen/tests/payment/test_recurring_donation_charge.py`:

```python
"""Booking a recurring Mollie donation charge — issue #345 part A.

Mollie charges a recurring donor every period and posts the subscription's
webhookUrl with a NEW payment id. Nothing matched that id to a donation, so
every charge after the first went unbooked. A charge now gets its own Donation,
carrying payment_id = the charge's id, and the existing webhook pipeline books
it from there.

Run with:
    cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_1 \\
      run-tests --app verenigingen \\
      --module verenigingen.tests.payment.test_recurring_donation_charge
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChargeDonationEmails(EnhancedTestCase):
    """A charge must not re-thank the donor for donating."""

    def _donation(self, **overrides):
        donor = self.factory.create_test_donor()
        values = {
            "doctype": "Donation",
            "donor": donor.name,
            "donation_date": frappe.utils.nowdate(),
            "amount": 25,
            "mode_of_payment": "Mollie",
            "paid": 0,
            "status": "One-time",
        }
        values.update(overrides)
        return frappe.get_doc(values)

    def test_recurring_origin_donation_field_exists(self):
        meta = frappe.get_meta("Donation")
        field = meta.get_field("recurring_origin_donation")
        self.assertIsNotNone(field, "Donation.recurring_origin_donation is missing")
        self.assertEqual(field.fieldtype, "Link")
        self.assertEqual(field.options, "Donation")

    def test_origin_donation_sends_the_donation_confirmation(self):
        # Control. Without this, the next test passes even if the email was
        # never sent for any donation at all.
        with patch("frappe.enqueue") as enqueued:
            self._donation().insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            methods,
        )

    def test_charge_donation_does_not_send_the_donation_confirmation(self):
        origin = self._donation().insert()
        with patch("frappe.enqueue") as enqueued:
            self._donation(recurring_origin_donation=origin.name, status="Recurring").insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertNotIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            methods,
        )

    def test_charge_donation_still_sends_the_payment_confirmation(self):
        # The donor keeps a receipt per period; only the "welcome" mail is dropped.
        origin = self._donation().insert()
        with patch("frappe.enqueue") as enqueued:
            self._donation(
                recurring_origin_donation=origin.name, status="Recurring", paid=1
            ).insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_payment_confirmation_email",
            methods,
        )
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_recurring_donation_charge
```

Expected: `test_recurring_origin_donation_field_exists` fails ("is missing"); the two charge tests
fail on an unknown fieldname at insert.

If `self.factory.create_test_donor()` does not exist, find the donor helper actually used by
`verenigingen/tests/payment/test_donation_subscription_activation.py` and use that instead — do not
invent a fixture.

- [ ] **Step 3: Add the field to `donation.json`**

Edit **by line**, never by rewriting the file with `json.dumps` — that reformats all 57 fields and
buries the change.

In `"fields"`, immediately after the `mollie_subscription_id` object, insert:

```json
  {
   "fieldname": "recurring_origin_donation",
   "fieldtype": "Link",
   "label": "Recurring Origin Donation",
   "options": "Donation",
   "read_only": 1,
   "description": "Set on donations created from a Mollie subscription charge. Points at the donation the donor originally made. Empty on that original."
  },
```

In `"field_order"`, insert `"recurring_origin_donation"` immediately after `"mollie_subscription_id"`.

- [ ] **Step 4: Guard the confirmation email**

In `verenigingen/verenigingen/doctype/donation/donation.py`, replace `after_insert`:

```python
    def after_insert(self):
        """Called after donation is created"""
        # A donation created from a Mollie subscription charge is not a new
        # donation from the donor's point of view -- they were thanked when they
        # set the subscription up. The per-period receipt is
        # send_payment_confirmation_email, which on_update still sends. Guarding
        # on the field rather than a flag means no future insert path can
        # forget it.
        if self.recurring_origin_donation:
            return

        # Send confirmation email for new donations using EmailService
        frappe.enqueue(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            donation_id=self.name,
            queue="short",
            timeout=300,
        )
```

- [ ] **Step 5: Reload the doctype and re-run**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 reload-doctype "Donation"
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_recurring_donation_charge
```

Expected: all four pass.

- [ ] **Step 6: Mutation-prove the guard**

Change `if self.recurring_origin_donation:` to `if False:` and confirm
`test_charge_donation_does_not_send_the_donation_confirmation` goes red while
`test_origin_donation_sends_the_donation_confirmation` stays green. Restore.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/verenigingen/doctype/donation/donation.json \
        verenigingen/verenigingen/doctype/donation/donation.py \
        verenigingen/tests/payment/test_recurring_donation_charge.py
git commit -m "feat(donation): mark a subscription charge's donation and stop re-thanking the donor

recurring_origin_donation distinguishes a donation created from a Mollie
subscription charge from the one the donor actually made. Without it the two
are indistinguishable: the donor portal lists every status='Recurring'
donation as a cancellable subscription, so a monthly donor would accumulate
one identical row per charge.

after_insert now skips the 'thank you for your donation' mail on a charge --
the donor was thanked at signup. The per-period receipt still goes out from
on_update.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 3: Uniqueness on `Donation.payment_id`

Two concurrent Mollie deliveries both read "no donation for this charge" and both insert. The money still books once — the Bank Transaction and Journal Entry creators are idempotent by reference — but two Donation rows mean two donor-history entries and, because `PeriodicDonationAgreement.link_donation` appends one child row per donation name, **`total_donated` doubles for that period**.

The constraint is also what lets Task 5 skip locking entirely: insert, and treat a duplicate-key error as "someone else won the race".

**Files:**
- Create: `verenigingen/patches/v2_2/enforce_unique_donation_payment_id.py`
- Modify: `verenigingen/patches.txt`
- Modify: `verenigingen/verenigingen/doctype/donation/donation.py` (`validate`)
- Test: `verenigingen/tests/payment/test_donation_payment_id_uniqueness.py`

**Interfaces:**
- Produces: unique index `idx_donation_payment_id_unique` on `` `tabDonation`(payment_id) ``, and the invariant that an empty `payment_id` is stored as `NULL`, never `''`.

- [ ] **Step 1: Establish the `''` → `NULL` behaviour empirically before designing around it**

A unique index on a `Data` column is only safe if empty values are `NULL` — MariaDB allows many
NULLs but only one `''`. 55 of 60 donations on veg11 have an empty `payment_id`, so getting this
wrong would block every manually created donation.

Frappe preserves `None` as `NULL` (`base_document.get_valid_dict`), but whether a Donation inserted
without a `payment_id` arrives as `None` or `''` is the question. Measure it:

```bash
cd ~/frappe-bench && bench --site test_site_1 console
```
```python
d = frappe.get_doc({"doctype": "Donation", "donor": frappe.db.get_value("Donor", {}, "name"),
                    "donation_date": frappe.utils.nowdate(), "amount": 1,
                    "mode_of_payment": "Mollie"}).insert()
print(repr(frappe.db.sql("select payment_id from `tabDonation` where name=%s", d.name)[0][0]))
frappe.db.rollback()
```

Record the result. If it prints `''`, Step 4's `validate` normalisation is required. If it prints
`None`, keep the normalisation anyway — it costs one line and makes the invariant explicit rather
than dependent on framework behaviour that could change — but note the finding in the commit body.

- [ ] **Step 2: Write the failing tests**

Create `verenigingen/tests/payment/test_donation_payment_id_uniqueness.py`:

```python
"""Donation.payment_id is unique — issue #345 part A.

A Mollie charge id identifies exactly one donation. Without a database
constraint, two concurrent webhook deliveries each read 'no donation for this
charge' and both insert; PeriodicDonationAgreement.link_donation then counts
the period twice and total_donated doubles.

Empty payment_ids must be NULL, not '': 55 of 60 donations on veg11 have no
payment_id at all, and MariaDB permits many NULLs but only one ''.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationPaymentIdUniqueness(EnhancedTestCase):
    def _donation(self, **overrides):
        donor = self.factory.create_test_donor()
        values = {
            "doctype": "Donation",
            "donor": donor.name,
            "donation_date": frappe.utils.nowdate(),
            "amount": 25,
            "mode_of_payment": "Mollie",
        }
        values.update(overrides)
        return frappe.get_doc(values)

    def test_empty_payment_id_is_stored_as_null(self):
        donation = self._donation().insert()
        stored = frappe.db.sql(
            "SELECT payment_id FROM `tabDonation` WHERE name = %s", donation.name
        )[0][0]
        self.assertIsNone(stored, "an empty payment_id must be NULL or the unique index blocks it")

    def test_many_donations_may_have_no_payment_id(self):
        # The case the constraint must NOT break: manually entered donations.
        # 55 of 60 donations on veg11 have no payment_id at all.
        first = self._donation().insert()
        second = self._donation().insert()  # raises if '' is stored rather than NULL
        self.assertEqual(
            frappe.db.count("Donation", {"name": ["in", [first.name, second.name]]}),
            2,
            "both payment_id-less donations must persist",
        )

    def test_the_unique_index_exists(self):
        rows = frappe.db.sql("SHOW INDEX FROM `tabDonation` WHERE Key_name = 'idx_donation_payment_id_unique'")
        self.assertTrue(rows, "unique index missing — has the patch run on this site?")
        self.assertEqual(int(rows[0][1]), 0, "index must be UNIQUE (Non_unique = 0)")

    def test_a_second_donation_with_the_same_payment_id_is_rejected(self):
        self._donation(payment_id="tr_uniqueness_probe").insert()
        with self.assertRaises(Exception) as caught:
            self._donation(payment_id="tr_uniqueness_probe").insert()
        self.assertTrue(
            frappe.db.is_duplicate_entry(caught.exception)
            or isinstance(caught.exception, frappe.UniqueValidationError),
            f"expected a duplicate-key error, got {caught.exception!r}",
        )
```

- [ ] **Step 3: Run to verify it fails**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_donation_payment_id_uniqueness
```

Expected: `test_the_unique_index_exists` fails ("index missing") and
`test_a_second_donation_with_the_same_payment_id_is_rejected` fails because the insert succeeds.

- [ ] **Step 4: Normalise empty `payment_id` in the controller**

In `verenigingen/verenigingen/doctype/donation/donation.py`, at the top of `validate`, before the
donor check:

```python
    def validate(self):
        # MariaDB permits many NULLs in a unique index but only one ''. Most
        # donations have no Mollie payment at all, so an empty payment_id must
        # be absent, not blank, or the second manually entered donation would
        # collide with the first. See patches/v2_2/enforce_unique_donation_payment_id.
        if not self.payment_id:
            self.payment_id = None

        if not self.donor or not frappe.db.exists("Donor", self.donor):
```

- [ ] **Step 5: Write the patch**

Create `verenigingen/patches/v2_2/enforce_unique_donation_payment_id.py`:

```python
"""Make Donation.payment_id unique.

A Mollie payment id identifies exactly one donation. Without a database
constraint two concurrent webhook deliveries both insert, and because
PeriodicDonationAgreement.link_donation appends one child row per donation,
the agreement's total_donated doubles for that period.

Three steps, in order:

1. Normalise '' -> NULL. MariaDB permits many NULLs in a unique index but only
   one ''; most donations have no Mollie payment at all (55 of 60 on veg11).
2. Auto-resolve duplicates: the earliest-created row keeps its payment_id and
   later ones have theirs cleared. NO ROW IS EVER DELETED and no other field is
   touched -- every cleared value is written to a comment on the donation it
   came from, so the change is auditable and reversible by hand.
3. Create the index.

The alternative -- halting migrate for a human to resolve -- was considered and
not taken (see the design spec, decision D4).
"""

import frappe

INDEX_NAME = "idx_donation_payment_id_unique"


def execute():
    if _index_exists():
        print(f"{INDEX_NAME} already exists on tabDonation")
        return

    blanked = _normalise_empty_payment_ids()
    cleared = _resolve_duplicates()
    _create_index()

    print(
        f"Donation.payment_id is now unique "
        f"({blanked} blank values normalised to NULL, {cleared} duplicates cleared)"
    )


def _index_exists() -> bool:
    return bool(frappe.db.sql("SHOW INDEX FROM `tabDonation` WHERE Key_name = %s", INDEX_NAME))


def _normalise_empty_payment_ids() -> int:
    count = frappe.db.sql("SELECT COUNT(*) FROM `tabDonation` WHERE payment_id = ''")[0][0]
    if count:
        frappe.db.sql("UPDATE `tabDonation` SET payment_id = NULL WHERE payment_id = ''")
    return count


def _resolve_duplicates() -> int:
    """Keep the earliest donation's payment_id; clear the rest, recording each."""
    duplicated = frappe.db.sql(
        """
        SELECT payment_id
        FROM `tabDonation`
        WHERE payment_id IS NOT NULL
        GROUP BY payment_id
        HAVING COUNT(*) > 1
        """,
        as_dict=True,
    )

    cleared = 0
    for row in duplicated:
        names = frappe.db.sql(
            """
            SELECT name FROM `tabDonation`
            WHERE payment_id = %s
            ORDER BY creation ASC, name ASC
            """,
            row.payment_id,
            as_dict=True,
        )
        keeper, losers = names[0].name, [n.name for n in names[1:]]
        for name in losers:
            # Comment first: if the UPDATE fails, the record of what was there
            # still exists. print() rather than logger().warning(), which writes
            # nothing under bench run-tests.
            print(f"  {name}: clearing payment_id {row.payment_id} (kept on {keeper})")
            frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Donation",
                    "reference_name": name,
                    "content": (
                        f"payment_id '{row.payment_id}' cleared by "
                        f"enforce_unique_donation_payment_id; it is kept on donation {keeper}."
                    ),
                }
            ).insert(ignore_permissions=True)
            frappe.db.set_value("Donation", name, "payment_id", None, update_modified=False)
            cleared += 1

    return cleared


def _create_index():
    # sql_ddl(), not sql(): DDL implicitly commits, and Frappe's guard raises
    # ImplicitCommitError if it goes through the ordinary path during migrate.
    frappe.db.sql_ddl(f"CREATE UNIQUE INDEX `{INDEX_NAME}` ON `tabDonation` (payment_id)")
```

- [ ] **Step 6: Register the patch**

Append to `verenigingen/patches.txt`, as the last line:

```
verenigingen.patches.v2_2.enforce_unique_donation_payment_id
```

- [ ] **Step 7: Run the patch and the tests**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 migrate
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_donation_payment_id_uniqueness
```

Expected: migrate prints the summary line and exits 0; all four tests pass.

- [ ] **Step 8: Prove the duplicate resolver actually resolves**

Re-running the patch on a clean site proves nothing — there are no duplicates. Build the condition
first, then run it, in `bench --site test_site_1 console`:

```python
donor = frappe.db.get_value("Donor", {}, "name")
frappe.db.sql_ddl("DROP INDEX `idx_donation_payment_id_unique` ON `tabDonation`")
names = []
for _ in range(2):
    d = frappe.get_doc({"doctype": "Donation", "donor": donor, "donation_date": frappe.utils.nowdate(),
                        "amount": 5, "mode_of_payment": "Mollie"}).insert()
    frappe.db.set_value("Donation", d.name, "payment_id", "tr_dup_probe", update_modified=False)
    names.append(d.name)
frappe.db.commit()

from verenigingen.patches.v2_2.enforce_unique_donation_payment_id import execute
execute()
frappe.db.commit()

print([frappe.db.get_value("Donation", n, "payment_id") for n in names])   # expect ['tr_dup_probe', None]
print(frappe.db.count("Comment", {"reference_name": names[1], "comment_type": "Info"}))  # expect >= 1
for n in names:
    frappe.delete_doc("Donation", n, force=True)
frappe.db.commit()
```

Both donations must still exist when the patch finishes — the resolver clears a field, it does not
delete rows. Record the observed output.

- [ ] **Step 9: Commit**

```bash
git add verenigingen/patches/v2_2/enforce_unique_donation_payment_id.py \
        verenigingen/patches.txt \
        verenigingen/verenigingen/doctype/donation/donation.py \
        verenigingen/tests/payment/test_donation_payment_id_uniqueness.py
git commit -m "feat(donation): make payment_id unique so a charge cannot book twice

Two concurrent Mollie deliveries both read 'no donation for this charge' and
both insert. The ledger survives -- the Bank Transaction and Journal Entry
creators are idempotent by reference -- but link_donation appends one child
row per donation, so the agreement's total_donated doubles for that period.

Empty payment_ids are normalised to NULL, in the patch and from now on in
validate(): MariaDB permits many NULLs in a unique index but only one '', and
most donations have no Mollie payment at all.

Duplicates are auto-resolved rather than halting migrate: the earliest row
keeps the value, later ones have theirs cleared, and every cleared value is
written to a comment on its donation first. No row is deleted.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 4: Fix `DonationLookup.find_for_subscription_payment`

The function already implements the right strategy — metadata `donation_id`, falling back to
`Donation.mollie_subscription_id` — and is not called from the live path. It is **not correct as
written**, and its tests do not show that because they build payments with `SimpleNamespace` and
`kwargs.setdefault("metadata", {})`: a fake more permissive than reality in the dimension under test.

Three defects:
1. `hasattr(payment, "subscription_id")` is `False` for any dict, so line 39 returns `None`.
2. `getattr(payment, "metadata", {})` returns `None` — not `{}` — for a real charge whose
   subscription has no metadata, and `None.get(...)` raises.
3. The `mollie_subscription_id` fallback has no ordering, and `Donation`'s meta sorts
   `modified DESC` — once charges share the subscription id it would return the newest **charge**,
   so each charge would be copied from the previous copy.

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/services/handlers/donation_lookup.py:26-77`
- Test: `verenigingen/verenigingen_payments/mollie/tests/test_donation_lookup_integration.py`

**Interfaces:**
- Consumes: `read_payment_field`, `read_payment_metadata` (Task 1); `Donation.recurring_origin_donation` (Task 2).
- Produces: `DonationLookup().find_for_subscription_payment(payment_id, payment=None, with_lock=False)` returns the **origin** Donation document, never a charge donation, for dict and object payloads alike.

- [ ] **Step 1: Write the failing tests**

Append to `verenigingen/verenigingen_payments/mollie/tests/test_donation_lookup_integration.py`.
Read the file's existing fixture helpers first and reuse them rather than inventing new ones; the
class below assumes a `_donation(**kwargs)` helper exists on the test case — if it does not, write
one modelled on the neighbouring classes.

```python
class TestSubscriptionLookupPayloadShapes(EnhancedTestCase):
    """The three shapes a charge actually arrives in, and the origin it must resolve to."""

    def setUp(self):
        super().setUp()
        self.lookup = DonationLookup()

    def test_resolves_from_a_plain_snake_case_dict(self):
        origin = self._donation(mollie_subscription_id="sub_shape_a")
        payment = {"id": "tr_a", "subscription_id": "sub_shape_a", "metadata": {"donation_id": origin.name}}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_a", payment=payment).name, origin.name)

    def test_resolves_from_a_camel_case_dict(self):
        # This is the SDK Payment's own shape: a dict subclass with camelCase keys.
        origin = self._donation(mollie_subscription_id="sub_shape_b")
        payment = {"id": "tr_b", "subscriptionId": "sub_shape_b", "metadata": {"donation_id": origin.name}}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_b", payment=payment).name, origin.name)

    def test_metadata_null_falls_back_to_the_subscription_id(self):
        # Measured: sub_5euSBaLzqF has no metadata, so its charges carry
        # metadata: null. The old code raised AttributeError here.
        origin = self._donation(mollie_subscription_id="sub_shape_c")
        payment = {"id": "tr_c", "subscriptionId": "sub_shape_c", "metadata": None}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_c", payment=payment).name, origin.name)

    def test_metadata_naming_an_absent_donation_falls_back_rather_than_giving_up(self):
        origin = self._donation(mollie_subscription_id="sub_shape_d")
        payment = {
            "id": "tr_d",
            "subscriptionId": "sub_shape_d",
            "metadata": {"donation_id": "Assoc-Dnt-does-not-exist"},
        }
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_d", payment=payment).name, origin.name)

    def test_never_returns_a_charge_donation(self):
        # The ordering defect: Donation sorts modified DESC, so without an
        # explicit order and an origin-only filter this returns the newest charge.
        origin = self._donation(mollie_subscription_id="sub_shape_e")
        charge = self._donation(mollie_subscription_id="sub_shape_e", recurring_origin_donation=origin.name)
        charge.db_set("payment_id", "tr_earlier_charge")
        payment = {"id": "tr_e", "subscriptionId": "sub_shape_e", "metadata": None}
        self.assertEqual(self.lookup.find_for_subscription_payment("tr_e", payment=payment).name, origin.name)

    def test_no_subscription_id_is_not_a_subscription_payment(self):
        self.assertIsNone(
            self.lookup.find_for_subscription_payment("tr_f", payment={"id": "tr_f", "metadata": None})
        )
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.verenigingen_payments.mollie.tests.test_donation_lookup_integration
```

Expected: the dict tests return `None` (the `hasattr` short-circuit); `test_metadata_null_...`
raises `AttributeError: 'NoneType' object has no attribute 'get'` if it gets past that.

- [ ] **Step 3: Implement**

In `donation_lookup.py`, add to the imports:

```python
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    read_payment_field,
    read_payment_metadata,
)
```

Replace the body of `find_for_subscription_payment` (keep the docstring's first line, extend it):

```python
    def find_for_subscription_payment(
        self, payment_id: str, payment: Optional[Any] = None, with_lock: bool = False
    ) -> Optional[Any]:
        """Find the ORIGIN donation for a subscription-generated charge.

        Mollie copies a subscription's metadata onto every charge it generates,
        so a donation subscription's charge normally carries
        ``metadata.donation_id`` outright. When the subscription has no metadata
        the charge carries ``metadata: null`` (measured: sub_5euSBaLzqF), and the
        subscription id is the only join left.

        Returns the donation the donor originally made -- never one of the
        donations created from earlier charges. ``Donation`` sorts
        ``modified DESC``, so an unordered lookup on ``mollie_subscription_id``
        would return the most recently touched charge and every charge would be
        copied from the previous copy.

        Args:
            payment_id: Mollie payment ID
            payment: Full Mollie payment object or dict (None when unavailable)
            with_lock: If True, acquire FOR UPDATE lock

        Returns:
            Donation document or None if not found
        """
        if not payment:
            return None

        subscription_id = read_payment_field(payment, "subscription_id", "subscriptionId")
        if not subscription_id:
            return None

        donation_id = read_payment_metadata(payment).get("donation_id")
        if donation_id:
            frappe.logger().info(f"Found donation_id in subscription payment metadata: {donation_id}")
            if frappe.db.exists("Donation", donation_id):
                return self._locked(donation_id, with_lock)
            # Not fatal: the subscription id below is an independent join, and a
            # metadata id naming a deleted donation should not cost us the charge.
            frappe.logger().error(
                f"Donation {donation_id} from payment {payment_id} metadata not found; "
                f"falling back to subscription {subscription_id}"
            )

        frappe.logger().info(f"Trying fallback lookup by subscription_id: {subscription_id}")
        donation_name = frappe.db.get_value(
            "Donation",
            {"mollie_subscription_id": subscription_id, "recurring_origin_donation": ["is", "not set"]},
            "name",
            order_by="creation asc",
        )
        if donation_name:
            return self._locked(donation_name, with_lock)

        return None

    def _locked(self, donation_name: str, with_lock: bool) -> Any:
        """Return the donation, optionally holding a row lock on it."""
        if with_lock:
            frappe.db.sql("SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE", (donation_name,))
        return frappe.get_doc("Donation", donation_name)
```

- [ ] **Step 4: Run the whole lookup module**

Same command as Step 2. Expected: the six new tests pass **and** every pre-existing test in the
module still passes.

One pre-existing test asserts the old "metadata names a missing donation → `None`" behaviour. The
new behaviour falls through to the subscription id, which is strictly better. If that test now
fails, update it to assert `None` only when *neither* join resolves, and say so in the commit body —
do not weaken the new tests to preserve it.

- [ ] **Step 5: Confirm this is not a pre-existing failure**

```bash
cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.verenigingen_payments.mollie.tests.test_donation_lookup_integration
```

(No `PYTHONPATH` — this runs untouched `develop`.) Record both results. A red run on the branch
means nothing until you know the same command is green without it.

- [ ] **Step 6: Mutation-prove the ordering guard**

Remove `"recurring_origin_donation": ["is", "not set"]` from the filter and confirm
`test_never_returns_a_charge_donation` goes red. Restore. Then remove `order_by="creation asc"`
alone and record whether the test still catches it — if it does not, the filter is doing all the
work and the ordering is belt-and-braces; note that in the commit body rather than pretending both
are load-bearing.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/services/handlers/donation_lookup.py \
        verenigingen/verenigingen_payments/mollie/tests/test_donation_lookup_integration.py
git commit -m "fix(mollie): make the subscription donation lookup work on real payloads

The function implemented the right strategy and had tests, but could not have
worked on the live path: hasattr(dict, 'subscription_id') is False, so it
returned None for both dict shapes, and getattr(payment, 'metadata', {})
returns None -- not {} -- for a charge whose subscription has no metadata,
where None.get() raises. Its tests passed because they used SimpleNamespace
with metadata defaulted to {}: a fake more forgiving than reality in exactly
the dimension under test.

The subscription-id fallback now excludes charge donations and orders by
creation. Donation sorts modified DESC, so it would otherwise return the most
recently touched charge and each charge would be copied from the last copy.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 5: `ensure_donation_for_recurring_charge`

The service that turns a recurring charge into a Donation. It creates a document and nothing else —
no Bank Transaction, no Journal Entry, no status juggling. Booking is the caller's existing pipeline
(Task 6).

**Files:**
- Create: `verenigingen/verenigingen_payments/mollie/services/recurring_donation_charge.py`
- Test: `verenigingen/tests/payment/test_recurring_donation_charge.py` (extend)

**Interfaces:**
- Consumes: `read_payment_field`, `read_payment_metadata` (Task 1); `Donation.recurring_origin_donation` (Task 2); the unique index (Task 3); `DonationLookup.find_for_subscription_payment` (Task 4).
- Produces:
  - `ensure_donation_for_recurring_charge(payment: Any) -> Optional[str]` — the Donation name, or `None` when this payment is not a bookable recurring charge.
  - `class RecurringChargeOriginMissing(frappe.ValidationError)` — raised when the origin cannot be resolved, so the caller can turn it into a retryable webhook error.

- [ ] **Step 1: Write the failing tests**

Append to `verenigingen/tests/payment/test_recurring_donation_charge.py`:

```python
from verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge import (
    RecurringChargeOriginMissing,
    ensure_donation_for_recurring_charge,
)


def _charge(origin_name=None, subscription_id="sub_book", payment_id="tr_charge", **overrides):
    """A recurring charge in the shape Mollie actually sends.

    Measured on a real subscription payment: sequenceType 'recurring',
    subscriptionId, customerId, mandateId, method 'directdebit', and the
    subscription's metadata copied verbatim -- metadata.payment_id being the
    FIRST payment's id, not this charge's.
    """
    payload = {
        "id": payment_id,
        "status": "paid",
        "sequenceType": "recurring",
        "subscriptionId": subscription_id,
        "customerId": "cst_book",
        "mandateId": "mdt_book",
        "method": "directdebit",
        "description": "Recurring donation",
        "amount": {"value": "25.00", "currency": "EUR"},
        "createdAt": "2026-08-01T00:10:00+00:00",
        "paidAt": "2026-08-03T09:00:00+00:00",
        "metadata": {"donation_id": origin_name, "payment_id": "tr_the_first_one"} if origin_name else None,
    }
    payload.update(overrides)
    return payload


class TestEnsureDonationForRecurringCharge(EnhancedTestCase):
    def _origin(self, **overrides):
        donor = self.factory.create_test_donor()
        values = {
            "doctype": "Donation",
            "donor": donor.name,
            "donation_date": "2026-07-01",
            "amount": 25,
            "mode_of_payment": "iDEAL",
            "status": "Recurring",
            "paid": 1,
            "payment_id": "tr_the_first_one",
            "mollie_subscription_id": "sub_book",
            "mollie_customer_id": "cst_book",
            "recurring_frequency": "Monthly",
        }
        values.update(overrides)
        return frappe.get_doc(values).insert()

    # --- what it declines to touch -------------------------------------------------

    def test_first_payment_is_not_a_charge(self):
        self.assertIsNone(ensure_donation_for_recurring_charge(_charge(sequenceType="first")))

    def test_payment_without_a_subscription_is_not_a_charge(self):
        self.assertIsNone(ensure_donation_for_recurring_charge(_charge(subscriptionId=None)))

    def test_unpaid_charge_creates_nothing(self):
        # Charges are created 'pending' and settle days later; only a paid one books.
        origin = self._origin()
        self.assertIsNone(
            ensure_donation_for_recurring_charge(_charge(origin.name, status="pending"))
        )
        self.assertFalse(frappe.db.exists("Donation", {"payment_id": "tr_charge"}))

    def test_failed_charge_creates_nothing_but_is_audited(self):
        origin = self._origin()
        before = frappe.db.count("Mollie Audit Log")
        self.assertIsNone(ensure_donation_for_recurring_charge(_charge(origin.name, status="failed")))
        self.assertFalse(frappe.db.exists("Donation", {"payment_id": "tr_charge"}))
        self.assertGreater(
            frappe.db.count("Mollie Audit Log"), before, "a failed charge must leave a trace"
        )

    # --- the happy path -------------------------------------------------------------

    def test_creates_a_donation_for_the_charge(self):
        origin = self._origin()
        name = ensure_donation_for_recurring_charge(_charge(origin.name))
        charge = frappe.get_doc("Donation", name)
        self.assertEqual(charge.payment_id, "tr_charge")
        self.assertEqual(charge.recurring_origin_donation, origin.name)
        self.assertEqual(charge.donor, origin.donor)
        self.assertEqual(float(charge.amount), 25.00)
        self.assertEqual(str(charge.donation_date), "2026-08-03")
        self.assertEqual(charge.paid, 1)
        self.assertEqual(charge.status, "Recurring")
        self.assertEqual(charge.mollie_subscription_id, "sub_book")

    def test_mode_of_payment_reflects_the_charge_not_the_origin(self):
        # The origin was iDEAL; the charge is always a direct debit.
        origin = self._origin(mode_of_payment="iDEAL")
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(_charge(origin.name)))
        self.assertEqual(charge.mode_of_payment, "SEPA Direct Debit")

    def test_designation_fields_are_carried_over(self):
        origin = self._origin(
            donation_purpose_type="Chapter",
            chapter_reference=self.factory.create_test_chapter().name,
            fund_designation="Sanctuary fund",
        )
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(_charge(origin.name)))
        self.assertEqual(charge.donation_purpose_type, "Chapter")
        self.assertEqual(charge.chapter_reference, origin.chapter_reference)
        self.assertEqual(charge.fund_designation, "Sanctuary fund")

    def test_campaign_recorded_only_in_notes_still_validates(self):
        # validate_donation_purpose accepts purpose_type Campaign without a
        # campaign link only when "Campaign:" appears in the notes. Dropping
        # donation_notes would make every charge of such a donation throw.
        origin = self._origin(
            donation_purpose_type="Campaign", donation_notes="Campaign: Zomeractie 2026"
        )
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(_charge(origin.name)))
        self.assertIn("Campaign:", charge.donation_notes)

    def test_resolves_the_origin_by_subscription_when_metadata_is_null(self):
        origin = self._origin()
        name = ensure_donation_for_recurring_charge(_charge(origin_name=None))
        self.assertEqual(frappe.get_doc("Donation", name).recurring_origin_donation, origin.name)

    # --- idempotency ----------------------------------------------------------------

    def test_redelivery_does_not_create_a_second_donation(self):
        origin = self._origin()
        first = ensure_donation_for_recurring_charge(_charge(origin.name))
        second = ensure_donation_for_recurring_charge(_charge(origin.name))
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Donation", {"payment_id": "tr_charge"}), 1)

    def test_a_lost_race_adopts_the_winner(self):
        # Simulates the interleaving the unique index exists for: the existence
        # check passes, then another worker inserts before we do.
        origin = self._origin()
        winner = ensure_donation_for_recurring_charge(_charge(origin.name))
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge"
            "._donation_for_charge",
            return_value=None,
        ):
            adopted = ensure_donation_for_recurring_charge(_charge(origin.name))
        self.assertEqual(adopted, winner)
        self.assertEqual(frappe.db.count("Donation", {"payment_id": "tr_charge"}), 1)

    # --- failures -------------------------------------------------------------------

    def test_unknown_subscription_raises_so_mollie_retries(self):
        with self.assertRaises(RecurringChargeOriginMissing):
            ensure_donation_for_recurring_charge(_charge(subscription_id="sub_nobody_knows"))

    def test_cancelled_agreement_does_not_block_the_booking(self):
        # validate_periodic_donation_agreement throws for a non-Active agreement.
        # A donor who cancels the agreement while Mollie keeps charging must not
        # turn every charge into an unbooked retry loop.
        agreement = self.factory.create_test_periodic_donation_agreement()
        origin = self._origin(periodic_donation_agreement=agreement.name)
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "status", "Cancelled")
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(_charge(origin.name)))
        self.assertFalse(charge.periodic_donation_agreement)

    # --- the agreement total, which is the whole reason for Donation-per-charge ---

    def test_each_charge_is_counted_in_the_agreement_total(self):
        """The justification for the data model, asserted rather than assumed.

        update_donation_tracking sums the agreement's `donations` child table,
        and only link_donation appends to it -- setting
        Donation.periodic_donation_agreement does not. link_donation has no
        production callers, so if the service does not call it this number never
        moves and a Donation per charge buys nothing.
        """
        agreement = self.factory.create_test_periodic_donation_agreement()
        origin = self._origin(periodic_donation_agreement=agreement.name)
        frappe.get_doc("Periodic Donation Agreement", agreement.name).link_donation(origin.name)

        ensure_donation_for_recurring_charge(_charge(origin.name, payment_id="tr_c1"))
        ensure_donation_for_recurring_charge(_charge(origin.name, payment_id="tr_c2"))

        agreement.reload()
        self.assertEqual(agreement.donations_count, 3, "origin plus two charges")
        self.assertEqual(float(agreement.total_donated), 75.00)

    def test_a_redelivered_charge_is_not_counted_twice(self):
        agreement = self.factory.create_test_periodic_donation_agreement()
        origin = self._origin(periodic_donation_agreement=agreement.name)

        ensure_donation_for_recurring_charge(_charge(origin.name))
        ensure_donation_for_recurring_charge(_charge(origin.name))

        agreement.reload()
        self.assertEqual(agreement.donations_count, 1)
        self.assertEqual(float(agreement.total_donated), 25.00)
```

`self.factory.create_test_chapter()` and `create_test_periodic_donation_agreement()` are assumed to
exist. Check `verenigingen/tests/fixtures/enhanced_test_factory.py` first; if either is absent,
build the fixture inline in the test rather than adding a factory helper (a new shared helper would
need `@shared_fixture`, which is out of scope here).

- [ ] **Step 2: Run to verify they fail**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_recurring_donation_charge
```

Expected: `ModuleNotFoundError: ...recurring_donation_charge`.

- [ ] **Step 3: Implement**

Create `verenigingen/verenigingen_payments/mollie/services/recurring_donation_charge.py`:

```python
"""Turn a Mollie subscription charge into a Donation of its own.

Mollie charges a recurring donor every period and posts the subscription's
webhookUrl with a NEW payment id. The webhook resolved donations by
``Donation.payment_id``, which holds the FIRST payment's id, so no charge after
the first matched anything: no Bank Transaction, no Journal Entry, no record.
Issue #345.

This module creates a document and nothing else. Once the charge has a Donation
carrying ``payment_id = <charge id>``, the existing webhook pipeline books it --
financial entries, payment history, donor history, refunds and chargebacks --
with no changes at all. That is the whole reason a charge gets its own Donation
rather than a payment row on the original.

Measured against the Mollie API: a subscription-generated charge carries
``sequenceType: "recurring"``, ``subscriptionId``, ``customerId``, ``mandateId``,
``method: "directdebit"``, and the subscription's metadata copied verbatim --
where ``metadata.payment_id`` is the FIRST payment's id, not the charge's.
Charges are created ``pending`` and settle days later.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from ..utils.common_helpers import read_payment_field, read_payment_metadata
from .handlers.donation_lookup import DonationLookup

# Mollie's method for a subscription charge, mapped to a Mode of Payment that
# exists. Copying the origin's method would misreport the charge: the donor
# signed up with iDEAL or a card, but the recurring charge is always a debit.
_METHOD_TO_MODE_OF_PAYMENT = {"directdebit": "SEPA Direct Debit"}

# Copied from the origin donation onto every charge. Designation and ANBI facts
# belong to the standing arrangement, not to one period's payment.
_INHERITED_FIELDS = (
    "donor",
    "company",
    "donor_email",
    "donation_purpose_type",
    "campaign",
    "chapter_reference",
    "specific_goal_description",
    "fund_designation",
    # Load-bearing, not cosmetic: validate_donation_purpose accepts
    # purpose_type "Campaign" without a campaign link only when "Campaign:"
    # appears here.
    "donation_notes",
    "anbi_agreement_number",
    "anbi_agreement_date",
    "belastingdienst_reportable",
    "recurring_frequency",
)

_UNBOOKABLE_STATUSES = ("failed", "expired", "canceled")


class RecurringChargeOriginMissing(frappe.ValidationError):
    """No donation could be found for a charge's subscription.

    Raised rather than returned so the webhook fails and Mollie re-delivers: a
    charge we cannot attribute is money we have received and not recorded, and
    it must not be swallowed into a 200.
    """


def ensure_donation_for_recurring_charge(payment: Any) -> Optional[str]:
    """Return the Donation for this subscription charge, creating it if needed.

    Returns None when the payment is not a bookable recurring charge -- a first
    payment, a payment with no subscription, or a charge that has not been paid.
    Raises RecurringChargeOriginMissing when it is one but cannot be attributed.
    """
    if read_payment_field(payment, "sequence_type", "sequenceType") != "recurring":
        return None

    subscription_id = read_payment_field(payment, "subscription_id", "subscriptionId")
    if not subscription_id:
        return None

    payment_id = read_payment_field(payment, "id")
    status = read_payment_field(payment, "status")
    if status != "paid":
        if status in _UNBOOKABLE_STATUSES:
            _audit(
                payment_id,
                "recurring_charge_not_paid",
                f"Charge on subscription {subscription_id} arrived '{status}' and was not booked",
                {"subscription_id": subscription_id, "charge_status": status},
                severity="warning",
            )
        return None

    existing = _donation_for_charge(payment_id)
    if existing:
        return existing

    origin = DonationLookup().find_for_subscription_payment(payment_id, payment=payment)
    if not origin:
        _audit(
            payment_id,
            "recurring_charge_origin_missing_error",
            f"No donation found for subscription {subscription_id}; charge not booked",
            {"subscription_id": subscription_id},
            severity="error",
        )
        raise RecurringChargeOriginMissing(
            _("No donation found for Mollie subscription {0}").format(subscription_id)
        )

    return _insert_charge_donation(payment, origin, payment_id, subscription_id)


def _donation_for_charge(payment_id: str) -> Optional[str]:
    return frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")


def _insert_charge_donation(payment, origin, payment_id: str, subscription_id: str) -> str:
    charge = frappe.new_doc("Donation")
    charge.update(_charge_values(payment, origin, payment_id, subscription_id))

    try:
        charge.insert(ignore_permissions=True)
    except Exception as e:
        # The unique index on payment_id is the real concurrency guard, which is
        # why no lock is taken: another worker inserting between the check above
        # and this line is a duplicate-key error, not a duplicate donation.
        if not frappe.db.is_duplicate_entry(e):
            raise
        winner = _donation_for_charge(payment_id)
        if not winner:
            raise
        frappe.logger().info(f"Charge {payment_id} was booked concurrently as {winner}; adopting it")
        return winner

    _link_to_agreement(charge.name, origin, payment_id)

    frappe.logger().info(
        f"Created donation {charge.name} for recurring charge {payment_id} "
        f"on subscription {subscription_id}"
    )
    return charge.name


def _charge_values(payment, origin, payment_id: str, subscription_id: str) -> Dict[str, Any]:
    amount = read_payment_field(payment, "amount") or {}
    values = {
        "payment_id": payment_id,
        "recurring_origin_donation": origin.name,
        "mollie_subscription_id": subscription_id,
        "mollie_customer_id": read_payment_field(payment, "customer_id", "customerId"),
        "mollie_mandate_id": read_payment_field(payment, "mandate_id", "mandateId"),
        "amount": frappe.utils.flt(amount.get("value")),
        "donation_date": frappe.utils.getdate(
            read_payment_field(payment, "paid_at", "paidAt")
            or read_payment_field(payment, "created_at", "createdAt")
        ),
        "paid": 1,
        "status": "Recurring",
        "mode_of_payment": _mode_of_payment(payment, origin),
    }
    for fieldname in _INHERITED_FIELDS:
        values[fieldname] = origin.get(fieldname)

    # periodic_donation_agreement is deliberately NOT set here. link_donation()
    # sets it, and doing it that way is what keeps the agreement's total_donated
    # correct -- see _link_to_agreement.
    return values


def _link_to_agreement(charge_name: str, origin, payment_id: str) -> None:
    """Register the charge with the origin's periodic agreement, if it has one.

    This call is load-bearing, not bookkeeping. ``update_donation_tracking``
    sums the agreement's ``donations`` child table, and only ``link_donation``
    ever appends to it -- setting ``Donation.periodic_donation_agreement``
    directly does not. ``link_donation`` has no production callers today, so
    without this the agreement's ``total_donated`` stays at whatever it was, and
    Donation-per-charge buys nothing over a payment child row.

    Never fatal. The money is already booked by the time this runs; a linkage
    problem is reported, not thrown.
    """
    agreement = origin.get("periodic_donation_agreement")
    if not agreement:
        return

    # validate_periodic_donation_agreement throws for anything other than
    # Active/Completed. A donor who cancels the agreement while the Mollie
    # subscription keeps charging must not turn every subsequent charge into a
    # hard failure -- Mollie retries, charge unbooked, which is the exact state
    # this issue exists to prevent.
    status = frappe.db.get_value("Periodic Donation Agreement", agreement, "status")
    if status not in ("Active", "Completed"):
        _audit(
            payment_id,
            "recurring_charge_agreement_inactive",
            f"Agreement {agreement} is '{status}'; charge booked without the link",
            {"agreement": agreement, "agreement_status": status},
            severity="warning",
        )
        return

    try:
        frappe.get_doc("Periodic Donation Agreement", agreement).link_donation(charge_name)
    except Exception as e:
        _audit(
            payment_id,
            "recurring_charge_agreement_link_error",
            f"Charge booked as {charge_name} but linking it to agreement {agreement} failed: {e}",
            {"agreement": agreement, "donation": charge_name},
            severity="error",
        )


def _mode_of_payment(payment, origin) -> str:
    """A Mode of Payment that exists, for a Donation field that is mandatory."""
    mapped = _METHOD_TO_MODE_OF_PAYMENT.get(read_payment_field(payment, "method"))
    if mapped and frappe.db.exists("Mode of Payment", mapped):
        return mapped
    # Deliberately not donation.create_mode_of_payment(), which would insert a
    # Mode of Payment literally named "directdebit" as a side effect of a webhook.
    return origin.get("mode_of_payment")


def _audit(payment_id, event_type, description, details, severity="info"):
    """Record on the Mollie Audit Log; never let logging break the booking."""
    try:
        from ..utils.audit import MollieAuditLogger

        MollieAuditLogger()._create_audit_log(
            event_type=event_type,
            event_category="webhook_processing",
            description=f"[{payment_id}] {description}",
            data={"payment_id": payment_id, **details},
            severity=severity,
        )
    except Exception as e:
        # .error(), not .warning(): a bare logger's level is ERROR under
        # bench run-tests, so a warning here would be discarded entirely.
        frappe.logger().error(f"Failed to write Mollie audit log for {payment_id}: {e}")
```

- [ ] **Step 4: Run the tests**

Same command as Step 2. Expected: all pass. Fix real failures; do not relax an assertion to make one
go away.

- [ ] **Step 5: Mutation-prove four assertions**

For each, break the line, confirm the named test goes red, restore:

| line | test that must go red |
|---|---|
| `if status != "paid"` → `if False:` | `test_unpaid_charge_creates_nothing` |
| drop `"donation_notes"` from `_INHERITED_FIELDS` | `test_campaign_recorded_only_in_notes_still_validates` |
| `_mode_of_payment` → `return origin.get("mode_of_payment")` | `test_mode_of_payment_reflects_the_charge_not_the_origin` |
| the agreement-status branch → always call `link_donation` | `test_cancelled_agreement_does_not_block_the_booking` |
| delete the `_link_to_agreement(...)` call in `_insert_charge_donation` | `test_each_charge_is_counted_in_the_agreement_total` |

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/services/recurring_donation_charge.py \
        verenigingen/tests/payment/test_recurring_donation_charge.py
git commit -m "feat(mollie): give each recurring donation charge its own Donation

Mollie posts a new payment id for every subscription charge, and the webhook
matched donations on Donation.payment_id -- the FIRST payment's id -- so no
charge after the first resolved to anything.

The service creates a document and nothing else. Once the charge has a
Donation carrying its own payment_id, the existing pipeline books it:
financial entries, payment history, donor history, refunds and chargebacks,
all unchanged. That is what a Donation per charge buys.

Three things the charge does not simply inherit: mode_of_payment reflects the
debit rather than the origin's iDEAL; a non-Active periodic agreement is
audited and dropped rather than thrown on, because a cancelled agreement must
not turn every charge into an unbooked retry loop; and donation_notes is
carried because validate_donation_purpose reads it.

No lock is taken. The unique index on payment_id is the guard, and a lost race
adopts the winner.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 6: Wire the service into the webhook, without returning

The branch must run **before** the idempotency check — which is keyed on `Donation.payment_id` and
would otherwise be asking about a donation that does not exist yet — and must then **fall through**.

Returning early would be a silent regression: `check_payment_processing_state(..., include_mollie_api=True)`
(`webhook_wrapper_service_unified.py:448`) is not only an idempotency check. Steps 3 and 4 inside it
(`unified_idempotency_manager.py:108-112`) are the **only** discovery of pending refunds and
chargebacks on the webhook Mollie actually calls, and Mollie signals a refund by posting the
payment's webhookUrl with the same `id=tr_...`. An early return would strand every refund of every
recurring charge while first payments kept theirs.

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py` (immediately after the classification `try/except`, before the STEP 1 comment)
- Test: `verenigingen/tests/payment/test_recurring_donation_charge.py` (extend)

**Interfaces:**
- Consumes: `ensure_donation_for_recurring_charge`, `RecurringChargeOriginMissing` (Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `verenigingen/tests/payment/test_recurring_donation_charge.py`. The company constant and
the settings capture in `setUpClass` must match
`verenigingen/tests/payment/test_donation_subscription_activation.py` — read that file's
`TestDonationSubscriptionActivation.setUpClass`/`setUp` and copy the same arrangement, or the
Journal Entry will fail ERPNext's single-currency validation.

```python
COMPANY = "_Test Company 2"   # EUR: the donation Journal Entry posts single-currency


class _FakeRecurringPayment(dict):
    """A subscription charge in the shape a real one arrives in.

    A real ``mollie.api.objects.Payment`` subclasses dict with camelCase keys,
    and ``_fetch_payment_from_mollie`` branches on ``isinstance(payment, dict)``
    -- so production takes the camelCase branch. A plain object would exercise
    the branch production never takes and leave the camelCase key names covered
    by nothing. Attributes are kept too, because the classifier and the
    idempotency manager read by attribute.
    """

    def __init__(self, payment_id, origin_name, subscription_id="sub_wire", refunds=()):
        metadata = {"donation_id": origin_name, "payment_id": "tr_the_first_one"}
        super().__init__(
            {
                "id": payment_id,
                "status": "paid",
                "amount": {"value": "25.00", "currency": "EUR"},
                "description": f"Recurring donation {origin_name}",
                "createdAt": "2026-08-01T00:10:00+00:00",
                "paidAt": "2026-08-03T09:00:00+00:00",
                "method": "directdebit",
                "metadata": metadata,
                "sequenceType": "recurring",
                "customerId": "cst_wire",
                "mandateId": "mdt_wire",
                "subscriptionId": subscription_id,
            }
        )
        self.id = payment_id
        self.status = "paid"
        self.amount = {"value": "25.00", "currency": "EUR"}
        self.description = f"Recurring donation {origin_name}"
        self.created_at = "2026-08-01T00:10:00+00:00"
        self.paid_at = "2026-08-03T09:00:00+00:00"
        self.method = "directdebit"
        self.metadata = metadata
        self.sequence_type = "recurring"
        self.customer_id = "cst_wire"
        self.mandate_id = "mdt_wire"
        self.subscription_id = subscription_id
        self.refunds = SimpleNamespace(list=lambda: {"_embedded": {"refunds": list(refunds)}})
        self.chargebacks = SimpleNamespace(list=lambda: [])


class _FakeClient:
    def __init__(self, payment):
        self.payments = SimpleNamespace(get=lambda pid: payment)

    def set_api_key(self, _key):
        return None


class TestRecurringChargeWebhookWiring(EnhancedTestCase):
    """The charge must book AND keep the refund discovery it falls through to."""

    def _origin(self):
        donor = self.factory.create_test_donor()
        return frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "company": COMPANY,
                "donation_date": "2026-07-01",
                "amount": 25,
                "mode_of_payment": "iDEAL",
                "status": "Recurring",
                "paid": 1,
                "payment_id": "tr_the_first_one",
                "mollie_subscription_id": "sub_wire",
                "mollie_customer_id": "cst_wire",
                "recurring_frequency": "Monthly",
            }
        ).insert()

    def _deliver(self, payment):
        """Drive the real webhook service with Mollie faked at the HTTP boundary."""
        client = _FakeClient(payment)
        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings"
            ".MollieSettings.get_mollie_client",
            return_value=client,
        ), patch("mollie.api.client.Client", return_value=client), patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient.sdk_client",
            new_callable=lambda: property(lambda self: client),
        ):
            return UnifiedWebhookWrapperService().process_payment_webhook(payment["id"], {})

    def test_a_recurring_charge_books_end_to_end(self):
        origin = self._origin()
        result = self._deliver(_FakeRecurringPayment("tr_wire_1", origin.name))

        self.assertEqual(result["status"], "success", result.get("message"))
        charge_name = frappe.db.get_value("Donation", {"payment_id": "tr_wire_1"}, "name")
        self.assertTrue(charge_name, "the charge produced no Donation")
        charge = frappe.get_doc("Donation", charge_name)
        self.assertEqual(charge.recurring_origin_donation, origin.name)
        self.assertTrue(charge.journal_entry, "the charge produced no Journal Entry")

    def test_the_charge_branch_does_not_skip_the_refund_check(self):
        """The regression this task exists to prevent.

        check_payment_processing_state is the ONLY discovery of pending refunds
        and chargebacks on this webhook. Returning from the charge branch would
        strand every refund of every recurring charge. Asserting the refund is
        seen -- not that the service was called -- is what makes this a test of
        the fall-through rather than of the branch.
        """
        origin = self._origin()
        payment = _FakeRecurringPayment(
            "tr_wire_2", origin.name, refunds=[{"id": "re_wire", "status": "refunded"}]
        )

        seen = {}
        real_check = (
            UnifiedWebhookWrapperService().idempotency_manager.check_payment_processing_state
        )

        def _spy(payment_id, **kwargs):
            state = real_check(payment_id, **kwargs)
            seen["pending_refunds"] = list(state.pending_refunds)
            return state

        with patch.object(
            UnifiedWebhookWrapperService().idempotency_manager.__class__,
            "check_payment_processing_state",
            side_effect=lambda payment_id, **kw: _spy(payment_id, **kw),
            autospec=False,
        ):
            self._deliver(payment)

        self.assertIn(
            "pending_refunds", seen, "control never reached the refund/chargeback discovery"
        )

    def test_an_unattributable_charge_returns_an_error_so_mollie_retries(self):
        # No origin donation exists for this subscription.
        result = self._deliver(
            _FakeRecurringPayment("tr_wire_3", "Assoc-Dnt-nope", subscription_id="sub_orphan")
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("sub_orphan", result["message"])

    def test_a_first_payment_is_untouched_by_the_new_branch(self):
        """Control. Without it, the tests above pass even if the branch swallowed
        every payment: a first payment must still take the #346 path."""
        origin = self._origin()
        first = _FakeRecurringPayment("tr_the_first_one", origin.name)
        first["sequenceType"] = "first"
        first.sequence_type = "first"
        first["subscriptionId"] = None
        first.subscription_id = None

        result = self._deliver(first)

        self.assertNotEqual(result["status"], "error", result.get("message"))
        self.assertFalse(
            frappe.db.exists("Donation", {"recurring_origin_donation": origin.name}),
            "a first payment must not spawn a charge donation",
        )
```

Add `from types import SimpleNamespace` and the `UnifiedWebhookWrapperService` import to the file's
header.

The three `patch` targets in `_deliver` cover the three ways this chain reaches Mollie
(`Mollie Settings.get_mollie_client`, a direct `mollie.api.client.Client()` in
`_create_donation_financial_entries`, and `MollieClient.sdk_client` in the router). Run the test
once before implementing: if it errors on a *fourth* path, add it rather than working around it.

- [ ] **Step 2: Run to verify they fail**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_recurring_donation_charge
```

Expected: the end-to-end test fails with "No donation found for payment tr_charge".

- [ ] **Step 3: Implement**

In `process_payment_webhook`, after the `except Exception as classification_error:` block closes and
before the `# STEP 1: UNIFIED IDEMPOTENCY CHECK` comment, insert:

```python
            # A recurring donation charge has no Donation yet, and STEP 1 below
            # is keyed on Donation.payment_id -- it would ask about a record that
            # does not exist. Materialise it first, then FALL THROUGH: the charge
            # now carries its own payment_id, so everything below works on it
            # unchanged.
            #
            # Do not return from here. check_payment_processing_state is also the
            # only discovery of pending refunds and chargebacks on this webhook
            # (Mollie signals a refund by re-posting the same payment id), so an
            # early return would strand every refund of every recurring charge
            # while first payments kept theirs. Issue #345.
            try:
                from .recurring_donation_charge import (
                    RecurringChargeOriginMissing,
                    ensure_donation_for_recurring_charge,
                )

                charge_donation = ensure_donation_for_recurring_charge(
                    self._fetch_payment_from_mollie(payment_id)
                )
                if charge_donation:
                    self.logger.info(
                        f"💶 Recurring charge {payment_id} booked to donation {charge_donation}"
                    )
            except RecurringChargeOriginMissing as e:
                # Money received and unattributable. Report failure so Mollie
                # re-delivers rather than swallowing it into a 200.
                duration = time.time() - start_time
                record_operation_performance("unified_webhook_processing", duration, False)
                return {
                    "status": "error",
                    "message": str(e),
                    "payment_id": payment_id,
                    "duration_seconds": duration,
                }
```

`self._fetch_payment_from_mollie` is used rather than the `payment` object bound inside the
classification `try`: that name is unbound when classification raised, and the normalised dict is a
shape `read_payment_field` handles. It costs one extra API call on the charge path only.

- [ ] **Step 4: Run the tests**

Same command as Step 2. Expected: all four pass.

- [ ] **Step 5: Prove the fall-through is real**

The whole task. Change the new block to `return {"status": "success", "payment_id": payment_id}`
immediately after `ensure_donation_for_recurring_charge` and confirm
`test_the_charge_branch_does_not_skip_the_refund_check` goes red. Restore.

If it stays green, the test is not testing the fall-through — fix the test before continuing.

- [ ] **Step 6: Run the #346 regression suite unchanged**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_donation_subscription_activation
```

Then the same for `verenigingen.tests.payment.test_mollie_integration_invariants`. Both must be
green; this branch changes the webhook entry point they exercise.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py \
        verenigingen/tests/payment/test_recurring_donation_charge.py
git commit -m "fix(mollie): book recurring donation charges on the webhook Mollie calls

A recurring charge has no Donation yet and the idempotency check is keyed on
Donation.payment_id, so it asked about a record that does not exist and the
handler 500ed until Mollie gave up 26 hours later.

The charge's Donation is now materialised first and control FALLS THROUGH.
Not returning is the point: check_payment_processing_state is also the only
discovery of pending refunds and chargebacks on this webhook, so an early
return would have stranded every refund of every recurring charge while first
payments kept theirs.

An unattributable charge returns an error so Mollie re-delivers -- money
received and unrecorded must not be swallowed into a 200.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 7: A half-created ledger must not report success

Spec F3. `_create_donation_financial_entries` returns a **truthy** dict when the Bank Transaction
succeeded and the Journal Entry did not:
`{"bank_transaction_name": ..., "journal_entry_name": None, "partial_success": True}`
(`webhook_wrapper_service_unified.py:1618-1622` and `:1636-1640`). Its only caller tests
`if not financial_result` (`:662`), so that case is reported as success.

For a recurring charge that is the worst outcome available: Mollie gets a 200 and never
re-delivers, the Donation exists with no `journal_entry`, and Part B's sweep — which is not shipping
yet — is the only thing that would ever notice. The donor has been debited and the ledger has half
an entry.

This also changes first-payment behaviour, because they share the path. That is intended: a
donation with a Bank Transaction and no Journal Entry is not a processed donation, and reporting it
as one is the defect.

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py:661-667`
- Test: `verenigingen/tests/payment/test_recurring_donation_charge.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `TestRecurringChargeWebhookWiring`:

```python
    def test_a_journal_entry_failure_is_not_reported_as_success(self):
        """A Bank Transaction with no Journal Entry is half a booking.

        _create_donation_financial_entries returns a TRUTHY dict for it, so the
        `if not financial_result` guard lets it through. Mollie would get a 200
        and never re-deliver, leaving the donor debited against half an entry.
        """
        origin = self._origin()
        partial = {
            "bank_transaction_name": "BT-partial",
            "journal_entry_name": None,
            "partial_success": True,
        }
        with patch.object(
            UnifiedWebhookWrapperService, "_create_donation_financial_entries", return_value=partial
        ):
            result = self._deliver(_FakeRecurringPayment("tr_wire_4", origin.name))

        self.assertEqual(result["status"], "error", "a missing Journal Entry must fail the webhook")
        self.assertIn("journal", result["message"].lower())

    def test_a_complete_booking_is_still_reported_as_success(self):
        """Control. Without it the assertion above passes even if every webhook
        started returning an error."""
        origin = self._origin()
        result = self._deliver(_FakeRecurringPayment("tr_wire_5", origin.name))
        self.assertEqual(result["status"], "success", result.get("message"))

    def test_redelivery_after_a_journal_entry_failure_completes_the_booking(self):
        """The other half of the guarantee: the error must be recoverable.

        Failing the first delivery is only correct if the retry finishes the job.
        The charge donation already exists by then, so this exercises the path
        that must resume rather than create -- and asserts on the Journal Entry,
        not on the status, because 'no second donation' and 'the ledger is whole'
        are different claims.
        """
        origin = self._origin()
        payment = _FakeRecurringPayment("tr_wire_6", origin.name)
        partial = {
            "bank_transaction_name": "BT-partial",
            "journal_entry_name": None,
            "partial_success": True,
        }

        with patch.object(
            UnifiedWebhookWrapperService, "_create_donation_financial_entries", return_value=partial
        ):
            self._deliver(payment)

        charge_name = frappe.db.get_value("Donation", {"payment_id": "tr_wire_6"}, "name")
        self.assertTrue(charge_name)
        self.assertFalse(frappe.db.get_value("Donation", charge_name, "journal_entry"))

        self._deliver(payment)  # Mollie re-delivers; nothing is faked this time

        self.assertEqual(
            frappe.db.count("Donation", {"payment_id": "tr_wire_6"}), 1, "the retry created a second donation"
        )
        self.assertTrue(
            frappe.db.get_value("Donation", charge_name, "journal_entry"),
            "the retry did not complete the Journal Entry",
        )
```

If the second delivery does not complete the Journal Entry, the resume lives in
`_handle_partial_processing` and that is what Step 5 is for — fix it there rather than weakening
this test.

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_recurring_donation_charge
```

Expected: `test_a_journal_entry_failure_is_not_reported_as_success` fails —
`'success' != 'error'`.

- [ ] **Step 3: Implement**

In `_handle_new_payment_processing`, replace the financial-result guard:

```python
            # Step 1-2: Create Bank Transaction and Journal Entry
            financial_result = self._create_donation_financial_entries(donation, payment_data)
            if not financial_result:
                return {
                    "status": "error",
                    "message": "Failed to create financial entries (Bank Transaction / Journal Entry)",
                    "payment_id": payment_id,
                }

            # A partial result is TRUTHY: the Bank Transaction landed and the
            # Journal Entry did not. Letting it through returns 200, Mollie never
            # re-delivers, and the donor is debited against half a booking.
            # Reported as an error so the delivery is retried -- both creators are
            # idempotent per payment id, so a retry completes the missing half
            # rather than duplicating the finished one.
            if financial_result.get("partial_success"):
                return {
                    "status": "error",
                    "message": (
                        f"Payment {payment_id} recorded a Bank Transaction "
                        f"({financial_result.get('bank_transaction_name')}) but no Journal Entry"
                    ),
                    "payment_id": payment_id,
                    "bank_transaction": financial_result.get("bank_transaction_name"),
                }
```

- [ ] **Step 4: Run the tests**

Same command as Step 2. Expected: both pass.

- [ ] **Step 5: Check the sibling path**

`_handle_partial_processing` also calls `_create_donation_financial_entries` (around `:794-802`).
Read it. If it has the same "truthy means done" assumption, fix it the same way and add a test; if
it already distinguishes them, note that in the commit body. Do not guess — read it.

- [ ] **Step 6: Mutation-prove**

Delete the `partial_success` branch, confirm `test_a_journal_entry_failure_is_not_reported_as_success`
goes red and `test_a_complete_booking_is_still_reported_as_success` stays green. Restore.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py \
        verenigingen/tests/payment/test_recurring_donation_charge.py
git commit -m "fix(mollie): a Bank Transaction with no Journal Entry is not a success

_create_donation_financial_entries returns a TRUTHY dict when the Bank
Transaction succeeded and the Journal Entry did not, and the caller only
tested 'if not financial_result'. Mollie got a 200 and never re-delivered,
leaving the donor debited against half a booking with nothing to notice it.

Now an error, so the delivery is retried. Both creators are idempotent per
payment id, so the retry completes the missing half rather than duplicating
the finished one.

This changes first payments too, since they share the path. Intended: a
donation with no Journal Entry is not a processed donation.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 8: `webhookUrl` on new subscriptions, and a durable guard on the second helper

None of this matters if Mollie never tells us. Both activation helpers create subscriptions with no
`webhookUrl`, so no charge is ever announced.

**Files:**
- Modify: `verenigingen/verenigingen_payments/utils/payment_gateways.py` — `_activate_direct_subscription_after_first_payment` (~1440-1495) and `_activate_donation_subscription_after_first_payment` (~1524-1608)
- Test: `verenigingen/tests/payment/test_donation_subscription_activation.py`

**Interfaces:**
- Consumes: `_find_subscription_for_payment` (already present in `payment_gateways.py`).

- [ ] **Step 1: Write the failing tests**

Append to `verenigingen/tests/payment/test_donation_subscription_activation.py`, reusing that file's
`_FakeCustomersResource` / `_FakePayment` and its recorder-and-`seen_keys` arrangement. `recorder`
is the list `_FakeSubscriptionsResource.create` appends `{"id", "data", "key"}` to, so
`recorder[0]["data"]` is the payload production actually sent.

```python
class TestSubscriptionCarriesAReachableWebhook(EnhancedTestCase):
    """Without a webhookUrl Mollie charges the donor and tells nobody. Issue #345."""

    def _create_direct_subscription(self, recorder, seen_keys, live):
        """Run _activate_direct_subscription_after_first_payment against the fakes."""
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        payment = _FakePayment(
            "tr_hook_1", "50.00", "Assoc-Dnt-hook", sequence_type="first", subscription_setup=True
        )
        gateway = SimpleNamespace(
            client=SimpleNamespace(
                customers=_FakeCustomersResource(recorder, seen_keys, None, live)
            )
        )
        return pg._activate_direct_subscription_after_first_payment(gateway, payment)

    def test_direct_subscription_payload_carries_the_payment_webhook(self):
        recorder, seen_keys, live = [], {}, {}
        result = self._create_direct_subscription(recorder, seen_keys, live)

        self.assertEqual(result["status"], "success", result.get("message"))
        self.assertEqual(len(recorder), 1)
        self.assertEqual(
            recorder[0]["data"].get("webhookUrl"),
            frappe.get_single("Mollie Settings").get_webhook_url(),
            "Mollie has nowhere to announce this subscription's charges",
        )

    def test_direct_subscription_payload_does_not_use_the_subscription_webhook(self):
        # get_subscription_webhook_url() is the member-dues endpoint: not
        # allow_guest (measured 403), only accepts a sub_ id where Mollie posts
        # id=tr_..., and gates on a Member plus an unpaid Sales Invoice a donor
        # need not have (#343). Pointing subscriptions there looks like a fix and
        # delivers nothing.
        recorder, seen_keys, live = [], {}, {}
        self._create_direct_subscription(recorder, seen_keys, live)

        settings = frappe.get_single("Mollie Settings")
        self.assertNotEqual(
            recorder[0]["data"].get("webhookUrl"), settings.get_subscription_webhook_url()
        )

    def test_donation_agreement_subscription_payload_carries_it_too(self):
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        donor = self.factory.create_test_donor()
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": frappe.utils.nowdate(),
                "amount": 50,
                "mode_of_payment": "Mollie",
                "status": "Recurring",
                "recurring_frequency": "Monthly",
                "mollie_customer_id": "cst_FAKECUSTOMER",
            }
        ).insert()

        recorder, seen_keys, live = [], {}, {}
        payment = _FakePayment(
            "tr_hook_2", "50.00", donation.name, sequence_type="first", subscription_setup=True
        )
        gateway = SimpleNamespace(
            client=SimpleNamespace(
                customers=_FakeCustomersResource(recorder, seen_keys, None, live)
            )
        )

        result = pg._activate_donation_subscription_after_first_payment(gateway, payment)

        self.assertEqual(result["status"], "success", result.get("message"))
        self.assertEqual(
            recorder[0]["data"].get("webhookUrl"),
            frappe.get_single("Mollie Settings").get_webhook_url(),
        )

    def test_donation_agreement_helper_adopts_an_existing_subscription(self):
        """The durable guard, tested across idempotency-key expiry.

        Mollie caches keys for one hour against a retry ladder that runs
        twenty-six, so attempts 8-10 arrive unprotected. Clearing seen_keys while
        `live` survives is exactly that: a fake whose key cache never expires
        would report this guard as working when it is not.
        """
        from verenigingen.verenigingen_payments.utils import payment_gateways as pg

        donor = self.factory.create_test_donor()
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": frappe.utils.nowdate(),
                "amount": 50,
                "mode_of_payment": "Mollie",
                "status": "Recurring",
                "recurring_frequency": "Monthly",
                "mollie_customer_id": "cst_FAKECUSTOMER",
            }
        ).insert()

        recorder, seen_keys, live = [], {}, {}
        payment = _FakePayment(
            "tr_hook_3", "50.00", donation.name, sequence_type="first", subscription_setup=True
        )

        def _deliver():
            gateway = SimpleNamespace(
                client=SimpleNamespace(
                    customers=_FakeCustomersResource(recorder, seen_keys, None, live)
                )
            )
            return pg._activate_donation_subscription_after_first_payment(gateway, payment)

        first = _deliver()
        seen_keys.clear()  # the key cache expires; the subscription does not
        second = _deliver()

        self.assertEqual(first["subscription_id"], second["subscription_id"])
        self.assertEqual(len(recorder), 1, "a late retry created a second subscription")
```

`_FakePayment`'s metadata carries `donation_id`, which is what
`_activate_donation_subscription_after_first_payment` reads; pass the real donation name so its
`frappe.get_doc("Donation", donation_id)` resolves.

- [ ] **Step 2: Run to verify they fail**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_donation_subscription_activation
```

Expected: `KeyError: 'webhookUrl'`; the adoption test creates two subscriptions.

- [ ] **Step 3: Add `webhookUrl` to both payloads**

In `_activate_direct_subscription_after_first_payment`, inside `subscription_data`, after
`"description"`:

```python
            # Without this Mollie charges the donor every period and announces it
            # to nobody -- issue #345. Deliberately get_webhook_url(), the
            # guest-reachable payment webhook, NOT get_subscription_webhook_url():
            # that one is the member-dues endpoint, which is not allow_guest,
            # only accepts a sub_ id where Mollie posts id=tr_..., and gates on a
            # Member plus an unpaid Sales Invoice a donor need not have (#343).
            "webhookUrl": frappe.get_single("Mollie Settings").get_webhook_url(),
```

Add the same key to `_activate_donation_subscription_after_first_payment`'s `subscription_data`,
with a one-line comment pointing at the fuller one above.

- [ ] **Step 4: Give the second helper the durable guard**

In `_activate_donation_subscription_after_first_payment`, replace the bare create:

```python
        customer = gateway.client.customers.get(customer_id)

        # Same durable guard as the direct path: Mollie caches idempotency keys
        # for one hour against a webhook retry ladder that runs twenty-six, so
        # attempts 8-10 arrive unprotected. metadata.payment_id never expires.
        # Adding a payload field (webhookUrl, above) widens the window where a
        # mid-ladder deploy changes the payload, which makes the key less
        # reliable still.
        subscription = _find_subscription_for_payment(customer, payment.id)
        if subscription is not None:
            frappe.logger().info(
                f"Mollie already has subscription {subscription.id} for payment {payment.id}; adopting it"
            )
        else:
            subscription = customer.subscriptions.create(
                data=subscription_data, idempotency_key=f"donagr-{payment.id}"
            )
```

For that guard to find them, this helper's subscriptions must carry the fingerprint it matches on.
Add `"payment_id": payment.id` to its `metadata` dict.

- [ ] **Step 5: Run the tests**

Same command as Step 2. Expected: all pass, plus every pre-existing test in the module.

- [ ] **Step 6: Confirm it holds without gateway credentials**

```bash
cd ~/frappe-bench/apps/verenigingen && scripts/testing/run_without_credentials.sh test_site_1 \
  verenigingen.tests.payment.test_donation_subscription_activation
```

This bench has live Mollie test keys and CI has none, so a green run here otherwise proves nothing
about CI. Confirm the tests skip or pass — an **erroring** test without credentials is a broken CI
gate, not a skipped one.

- [ ] **Step 7: Mutation-prove**

Change `get_webhook_url()` to `get_subscription_webhook_url()` and confirm both
`test_direct_subscription_payload_carries_the_payment_webhook` and
`..._does_not_use_the_subscription_webhook` go red. Restore.

- [ ] **Step 8: Commit**

```bash
git add verenigingen/verenigingen_payments/utils/payment_gateways.py \
        verenigingen/tests/payment/test_donation_subscription_activation.py
git commit -m "fix(mollie): tell Mollie where to announce a recurring donation charge

Both activation helpers created subscriptions with no webhookUrl -- every
direct_subscription subscription in the test account has webhookUrl: None --
so Mollie charged the donor every period and notified nobody.

The URL is get_webhook_url(), the guest-reachable payment webhook, and
explicitly not get_subscription_webhook_url(): that endpoint is not
allow_guest, only accepts a sub_ id where Mollie posts id=tr_..., and gates on
a Member plus an unpaid Sales Invoice a donor need not have (#343).

The donation-agreement helper also gains the durable duplicate guard the
direct path already has, and the metadata.payment_id fingerprint it matches
on. It had only the one-hour idempotency key against a twenty-six hour retry
ladder, and adding a payload field widens the window where a mid-ladder deploy
changes the payload.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Task 9: Keep charge donations out of the donor portal's subscription list

`get_recurring_donations` lists every `status="Recurring"` donation as an active, cancellable
subscription. Charge donations carry that status, so a monthly donor would grow one identical row
per charge, each with its own Cancel button, and the page makes two live Mollie calls per row for
what is one subscription.

**Files:**
- Modify: `verenigingen/templates/pages/manage_donations.py:100-102`
- Test: `verenigingen/tests/payment/test_recurring_donation_charge.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
class TestDonorPortalRecurringList(EnhancedTestCase):
    def test_three_charges_show_as_one_recurring_donation(self):
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        member = self.factory.create_test_member()
        donor = self.factory.create_test_donor(donor_email=member.email)
        origin = frappe.get_doc({
            "doctype": "Donation", "donor": donor.name, "donor_email": member.email,
            "donation_date": "2026-06-01", "amount": 25, "mode_of_payment": "iDEAL",
            "status": "Recurring", "paid": 1, "mollie_subscription_id": "sub_portal",
        }).insert()
        for month, charge_id in (("07", "tr_p1"), ("08", "tr_p2"), ("09", "tr_p3")):
            frappe.get_doc({
                "doctype": "Donation", "donor": donor.name, "donor_email": member.email,
                "donation_date": f"2026-{month}-01", "amount": 25,
                "mode_of_payment": "SEPA Direct Debit", "status": "Recurring", "paid": 1,
                "payment_id": charge_id, "mollie_subscription_id": "sub_portal",
                "recurring_origin_donation": origin.name,
            }).insert()

        rows = get_recurring_donations(member.name)
        self.assertEqual(
            [r["name"] for r in rows], [origin.name],
            "the portal must show the subscription once, not once per charge",
        )
```

If `get_recurring_donations` calls Mollie for each row, patch `get_mollie_subscription_info` in that
module to return a plain dict so the test does not depend on the gateway.

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/frappe-bench && PYTHONPATH=/tmp/claude-1000/-home-frappeuser-frappe-bench-apps-verenigingen/0a31f0fd-e145-470c-aed6-7ca913c8b71a/scratchpad/wt-charges \
  bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_recurring_donation_charge
```

Expected: four rows returned, one expected.

- [ ] **Step 3: Implement**

In `verenigingen/templates/pages/manage_donations.py`, in `get_recurring_donations`:

```python
            filters={
                "donor_email": member.email,
                "status": "Recurring",
                # A donation created from a subscription charge is a past gift,
                # not a standing arrangement the donor can cancel. Without this
                # a monthly donor accumulates one identical row per charge.
                "recurring_origin_donation": ["is", "not set"],
            },
```

- [ ] **Step 4: Run the test**

Same command as Step 2. Expected: pass.

- [ ] **Step 5: Mutation-prove**

Remove the new filter line, confirm the test goes red, restore.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/templates/pages/manage_donations.py \
        verenigingen/tests/payment/test_recurring_donation_charge.py
git commit -m "fix(portal): show a recurring donation once, not once per charge

get_recurring_donations lists every status='Recurring' donation as an active
cancellable subscription. Charge donations carry that status, so a monthly
donor would see a new identical row every month -- each with its own Cancel
button, and each costing two live Mollie calls for the same subscription.

Claude-Session: https://claude.ai/code/session_01HE9bqEov4eTKrv7iu9N2gq"
```

---

## Final verification

- [ ] **Run every touched module against the branch and against untouched `develop`**

Both columns, one `--module` per invocation. A red run means nothing until the same command without
`PYTHONPATH` is known green.

```
verenigingen.tests.payment.test_recurring_donation_charge
verenigingen.tests.payment.test_donation_payment_id_uniqueness
verenigingen.tests.payment.test_donation_subscription_activation
verenigingen.tests.payment.test_mollie_integration_invariants
verenigingen.tests.payment.test_payment_gateways_unit
verenigingen.tests.payment.test_payment_gateways_coverage
verenigingen.tests.payment.test_payment_gateways_sweep2_coverage
verenigingen.tests.payment.test_mollie_subscription_consolidation
verenigingen.verenigingen_payments.mollie.tests.test_common_helpers
verenigingen.verenigingen_payments.mollie.tests.test_donation_lookup_integration
verenigingen.verenigingen_payments.mollie.tests.test_mollie_debug_service
verenigingen.tests.test_donation (or the Donation doctype's own test module, if named differently)
```

Do not trim this list because it is slow. The last session's CI failure came from cutting a control
matrix from 12 modules to 10 and dropping exactly the two that mattered.

- [ ] **Run the gateway-touching ones without credentials**

```bash
cd ~/frappe-bench/apps/verenigingen && scripts/testing/run_without_credentials.sh test_site_1 \
  verenigingen.tests.payment.test_recurring_donation_charge
```

- [ ] **Lint**

```bash
cd <worktree> && pre-commit run --files $(git diff --name-only origin/fix/donation-subscription-activation)
```

`whitelist-type-safety` has pre-existing failures; `SKIP=whitelist-type-safety` if it blocks. Do not
add a pragma or bump a baseline to silence `error_swallow_validator` — fix the swallow.

- [ ] **Open the PR against `fix/donation-subscription-activation`**, not `develop`, and note in the
      body that it and #346 land together: #346 restores subscription creation, this makes the
      resulting charges bookable, and #346 must not merge without it.

---

## Deviations from the spec, recorded

- The spec says the insert is taken "under a named lock keyed on the charge id, with D4's unique
  index as the real guard". The plan drops the lock: catching the duplicate-key error and adopting
  the winner is the same guarantee with less machinery, and holding a lock across a document insert
  buys nothing the index does not already give. `test_a_lost_race_adopts_the_winner` covers it.
- The spec's Task-5 field list did not mention `company`; it is included, since `Donation.company`
  drives the Journal Entry's company and the origin is the only source for it.

"""Donation.payment_id is unique — issue #345 part A.

A Mollie charge id identifies exactly one donation. Without a database
constraint, two concurrent webhook deliveries each read 'no donation for this
charge' and both insert; PeriodicDonationAgreement.link_donation then counts
the period twice and total_donated doubles.

Empty payment_ids must be NULL, not '': 55 of 60 donations on veg11 have no
payment_id at all, and MariaDB permits many NULLs but only one ''.

Run with:
    cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_1 \\
      run-tests --app verenigingen \\
      --module verenigingen.tests.payment.test_donation_payment_id_uniqueness
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationPaymentIdUniqueness(EnhancedTestCase):
    def _create_donor(self):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory). Build the donor the same way
        # test_donation_subscription_activation.py and
        # test_recurring_donation_charge.py do, rather than adding a new shared
        # fixture helper, which would need @shared_fixture treatment.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Uniqueness Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"uniq.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _donation(self, **overrides):
        values = {
            "doctype": "Donation",
            "donor": self._create_donor(),
            "donation_date": frappe.utils.nowdate(),
            "amount": 25,
            "mode_of_payment": "Mollie",
        }
        values.update(overrides)
        return frappe.get_doc(values)

    def test_empty_payment_id_is_stored_as_null(self):
        donation = self._donation().insert()
        stored = frappe.db.sql("SELECT payment_id FROM `tabDonation` WHERE name = %s", donation.name)[0][0]
        self.assertIsNone(stored, "an empty payment_id must be NULL or the unique index blocks it")

    def test_validate_normalises_an_explicitly_blank_payment_id_in_memory(self):
        """What Donation.validate()'s normalisation hunk actually adds.

        The earlier version of this test asserted the STORED value was NULL and
        credited validate() for it. That claim is false: base_document.py:566-568
        maps '' -> None for any field the meta marks unique, so the row is NULL
        with the validate() hunk deleted. The test passed either way.

        What the hunk does add is the in-memory document: after validate(), the
        object a caller still holds reads None rather than '', so a subsequent
        db_set/save round-trip cannot re-introduce ''. The framework guarantee is
        pinned separately below, as a framework guarantee.
        """
        donation = self._donation(payment_id="")
        donation.insert()
        self.assertIsNone(donation.payment_id, "validate() must blank '' on the in-memory document")

    def test_the_framework_stores_a_blank_unique_field_as_null(self):
        # Not this branch's doing: base_document.py:566-568 maps '' -> None for
        # any `unique` field, which is what keeps a second payment_id-less
        # donation from colliding. Pinned because the whole NULL-vs-'' design
        # rests on it, not because our code implements it.
        donation = self._donation(payment_id="").insert()
        stored = frappe.db.sql("SELECT payment_id FROM `tabDonation` WHERE name = %s", donation.name)[0][0]
        self.assertIsNone(stored, "an explicitly blank payment_id must be stored as NULL")

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
        # seq_in_index = 1 plus a one-column count, not merely "some unique index
        # touches this column": a composite UNIQUE (payment_id, donor) would
        # satisfy the looser query while permitting exactly the duplicate charge
        # this constraint exists to block.
        rows = frappe.db.sql(
            """
            SELECT index_name
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'tabDonation'
              AND column_name = 'payment_id'
              AND non_unique = 0
              AND seq_in_index = 1
            """
        )
        self.assertTrue(rows, "no unique index led by Donation.payment_id — has the schema sync run?")
        widths = frappe.db.sql(
            """
            SELECT index_name, COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'tabDonation'
              AND index_name IN (%s)
            GROUP BY index_name
            """
            % ", ".join(["%s"] * len(rows)),
            tuple(row[0] for row in rows),
        )
        self.assertTrue(
            any(width == 1 for _name, width in widths),
            f"the unique index on payment_id is composite ({widths}); a composite one constrains "
            "the pair, not the charge id, so two donations could still share a payment_id",
        )

    def test_a_second_donation_with_the_same_payment_id_is_rejected(self):
        # Randomised, not a fixed literal: payment_id is now unique site-wide, so
        # a hard-coded probe left behind by one interrupted run would make this
        # test error permanently on that site -- and would collide with any other
        # module using the same literal in the same shard.
        probe = f"tr_uniqueness_probe_{frappe.generate_hash(length=8)}"
        self._donation(payment_id=probe).insert()
        with self.assertRaises(Exception) as caught:
            self._donation(payment_id=probe).insert()
        self.assertTrue(
            frappe.db.is_duplicate_entry(caught.exception)
            or isinstance(caught.exception, frappe.UniqueValidationError),
            f"expected a duplicate-key error, got {caught.exception!r}",
        )

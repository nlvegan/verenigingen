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

    def test_an_explicitly_blank_payment_id_is_normalised_to_null(self):
        # Frappe leaves a field NULL only when the key is absent from the
        # document; an explicitly assigned '' is persisted verbatim (measured).
        # validate() must turn it into None, or the second such donation
        # collides under the unique index.
        donation = self._donation(payment_id="").insert()
        stored = frappe.db.sql("SELECT payment_id FROM `tabDonation` WHERE name = %s", donation.name)[0][0]
        self.assertIsNone(stored, "an explicitly blank payment_id must be normalised to NULL")

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
        rows = frappe.db.sql(
            """
            SELECT index_name, non_unique
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'tabDonation'
              AND column_name = 'payment_id'
              AND non_unique = 0
            """
        )
        self.assertTrue(rows, "no unique index on Donation.payment_id — has the schema sync run?")

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

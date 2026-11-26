"""#3020: a VereningingenTestCase subclass that REPLACES ``self.factory`` after ``super().setUp()``
must not lose the base's ``factory.on_track = self.track_doc`` wiring.

Without it ``_test_docs`` stays empty, ``_rollback_once_before_draining`` returns early, and rows
the factory builds (an auto Chapter + Member + Customer) outlive a test whose body committed.
The base now owns the wiring in a ``factory`` property setter, so no subclass has to remember it.

The leak itself needs a test body that commits, which a bare ``frappe.db.commit()`` here would add
to the order-dependence baseline; so these tests assert the cause instead (what reaches
``_test_docs``, which is exactly what the drain and the rollback guard read).
"""

import unittest

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class _ReplacingProbe3020(VereningingenTestCase):
    """Replaces the factory the way test_invoice_validation_safeguards does."""

    def setUp(self):
        super().setUp()
        self.factory = CoreTestDataFactory()

    def test_noop(self):
        pass


class TestFactoryReplacementIsRewired(unittest.TestCase):
    def _make_probe_3020(self):
        probe = _ReplacingProbe3020("test_noop")
        probe.setUp()
        self.addCleanup(probe.tearDown)
        return probe

    def test_replaced_core_factory_is_wired_to_track_doc(self):
        probe = self._make_probe_3020()
        self.assertEqual(probe.factory.on_track, probe.track_doc)

    def test_rows_built_by_the_replaced_factory_reach_the_drain(self):
        probe = self._make_probe_3020()
        member = probe.factory.create_test_member(
            email=f"rewire3020.{frappe.generate_hash(length=6)}@test.invalid"
        )
        tracked = {(d["doctype"], d["name"]) for d in probe._test_docs}
        # The auto Chapter is built INSIDE the factory, never by the test, so only the on_track
        # callback can put it on the drain list.
        auto_chapters = [c for c in probe.factory.created_records if c["doctype"] == "Chapter"]
        self.assertTrue(auto_chapters, "fixture no longer builds an auto Chapter; the control is void")
        for record in auto_chapters:
            self.assertIn(("Chapter", record["name"]), tracked)
        self.assertIn(("Member", member.name), tracked)

    def test_replacement_with_a_core_subclass_is_wired(self):
        class _Sub(CoreTestDataFactory):
            pass

        probe = self._make_probe_3020()
        probe.factory = _Sub()
        self.assertEqual(probe.factory.on_track, probe.track_doc)

    def test_non_core_replacement_is_left_alone(self):
        # Control: SEPA/Mollie-style factories do not speak the on_track protocol; the setter
        # must not write an attribute onto them.
        class _Other:
            pass

        probe = self._make_probe_3020()
        other = _Other()
        probe.factory = other
        self.assertIs(probe.factory, other)
        self.assertFalse(hasattr(other, "on_track"))

    def test_class_level_factory_attribute_is_untouched(self):
        # Classes that build ``cls.factory`` in setUpClass (the #1307 shape) shadow the property
        # with a plain class attribute; the base must neither wire nor break them.
        class _ClassLevel(VereningingenTestCase):
            factory = None

            def test_noop(self):
                pass

        probe = _ClassLevel("test_noop")
        probe.setUp()
        self.addCleanup(probe.tearDown)
        self.assertIsInstance(probe.factory, CoreTestDataFactory)

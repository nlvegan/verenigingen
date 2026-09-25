"""Regression test for #1404: force_unique_name collides deterministically
across fresh EnhancedTestDataFactory instances.

EnhancedTestCase.setUp() builds a brand-new
``EnhancedTestDataFactory(seed=12345, ...)`` for *every* test method. Because
the seed is a hardcoded literal, ``test_run_id`` (derived from the seed alone)
is identical across every instance built in the same process, and
``sequence_counters`` starts fresh at 1 in every instance too. So
``force_unique_name()``, called with the SAME literal base_name from two
different test methods (e.g. ``create_test_team(team_name="Members Page
Team")`` in ``TestTeamMembersPage.setUp()``), computes the exact same
uniqueness hash every time -- not a rare probabilistic draw (contrast the
different mechanism fixed by #1254/#1265), a *guaranteed* collision by
construction. Its own collision-resolution fallback (``collision_seq``) is
subject to the identical problem, so a SECOND collision in the same run
reproduces the FIRST collision-resolved name exactly and raises
DuplicateEntryError -- reported against TestTeamMembersPage on test_site_13.
"""

from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase,
    EnhancedTestDataFactory,
)


class TestForceUniqueNameCrossInstance(EnhancedTestCase):
    def test_fresh_factory_instances_do_not_collide_on_same_base_name(self):
        """Simulates 3 test methods, each building its own fresh factory (as
        EnhancedTestCase.setUp() does) and asking for the same literal
        base_name while the earlier instances' rows still exist -- exactly
        the shape of TestTeamMembersPage's 8 setUp() calls in one run.
        """
        base_name = "Force Unique Name Collision Team"
        created_names = []

        for _ in range(3):
            factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
            team = factory.create_team(team_name=base_name)
            # Piggyback on this test's own factory so the real harness drain
            # cleans these up in tearDown, regardless of pass/fail.
            self.factory.track_document("Team", team.name, priority=1)
            created_names.append(team.name)

        self.assertEqual(
            len(created_names),
            len(set(created_names)),
            f"force_unique_name produced duplicate names across fresh factory "
            f"instances asked for the same base_name: {created_names}",
        )

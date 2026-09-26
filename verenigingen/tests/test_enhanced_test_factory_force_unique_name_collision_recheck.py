"""Regression test for #1415: force_unique_name's collision-resolution branch
never re-checked the name it constructed against the database.

#1404 (commit deae970e9) removed the *guaranteed* collision in
``EnhancedTestDataFactory.force_unique_name()`` by mixing the process-global
``_global_unique_seq`` counter into the primary candidate's uniqueness hash.
It left a smaller, pre-existing gap in the same method: once the primary
candidate collides and the method builds a SECOND candidate (the
``collision_seq`` branch), the old code reused the SAME
``short_deterministic_id`` computed for the primary candidate and returned
the new name directly -- it never checked whether *that* name already existed.
Two factory instances that both land in the collision branch on their first
attempt (same ``clean_base``, same ``seq``) could, via a coincidental hash
match between their two different ``_global_unique_seq`` draws (about
1-in-1e6 per colliding pair), construct the identical collision-resolved
name. Rare, but a certainty is what #1404 removed, not a certainty
re-introduced one level down -- and this test does not wait for the 1-in-1e6
draw: it forces the coincidence by patching the *sequence source*
(``_global_unique_seq``, a plain ``itertools`` counter -- not business logic)
to a fixed value, so the hash the method draws is predictable, then plants
real rows for both the primary and the collision-branch candidate names
before calling the method under test.
"""

import itertools
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase,
    EnhancedTestDataFactory,
)

# Fixed value the patched _global_unique_seq will yield on every draw. Using
# itertools.repeat (rather than itertools.count) means it is safe to consume
# it once in the test (to predict the candidate names) and any further times
# inside force_unique_name itself -- every draw returns this SAME value, so
# there is no ordering dependency between the test's prediction and the
# method's own internal consumption.
_PATCHED_GLOBAL_DRAW = 777


class TestForceUniqueNameCollisionBranchRecheck(EnhancedTestCase):
    def _create_test_role(self, role_name):
        """Plant a real Role row under an exact, pre-computed name.

        Role autonames on `field:role_name`, so this is a straightforward
        fixture insert -- not a bypass of any permission boundary under test.
        """
        role = frappe.get_doc({"doctype": "Role", "role_name": role_name})
        role.insert(ignore_permissions=True)
        self.factory.track_document("Role", role_name, priority=1)

    def _predict_candidate_names(self, factory, base_name, doctype, max_length=50):
        """Replicate force_unique_name's own candidate-name construction so
        this test can plant colliding rows in advance of the real call.

        This mirrors the PRODUCTION formula on purpose -- it is not what is
        under test (the method's behaviour when a name it constructs already
        exists in the DB is what's asserted below); it's how the test derives
        a name it can be sure the method will compute, given the patched
        sequence source and a fresh factory instance (empty
        sequence_counters, so `seq` and `collision_seq` both start at 1).
        """
        clean_base = base_name.replace("TEST ", "").replace("Test ", "")
        max_base_length = max_length - 20
        clean_base = clean_base[:max_base_length] if len(clean_base) > max_base_length else clean_base

        seq = 1  # first "forced_{clean_base}" call on a fresh factory
        short_deterministic_id = (
            hash(f"{factory.test_run_id}_{clean_base}_{seq}_{_PATCHED_GLOBAL_DRAW}") % 1000000
        )
        primary_name = f"TEST {clean_base} {seq:03d}_{short_deterministic_id}"
        # collision_seq == 1: first "collision_{clean_base}" call
        collision_name = f"TEST {clean_base[:10]} {seq:02d}_{1:02d}_{short_deterministic_id}"
        return primary_name[:max_length], collision_name[:max_length]

    def test_collision_branch_candidate_is_rechecked_against_the_db(self):
        doctype = "Role"
        base_name = "Force Unique Name 1415 Collision Branch"

        with patch.object(
            EnhancedTestDataFactory,
            "_global_unique_seq",
            itertools.repeat(_PATCHED_GLOBAL_DRAW),
        ):
            factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
            primary_name, collision_name = self._predict_candidate_names(factory, base_name, doctype)

            # Plant BOTH candidates the method will construct: the primary one
            # (forcing entry into the collision-resolution branch) and the
            # collision-resolved one itself (the name the pre-#1415 code
            # returned unchecked).
            for planted_name in (primary_name, collision_name):
                self._create_test_role(planted_name)

            returned_name = factory.force_unique_name(base_name, doctype=doctype)

        if returned_name not in (primary_name, collision_name):
            self.factory.track_document("Role", returned_name, priority=1)

        self.assertFalse(
            frappe.db.exists(doctype, returned_name),
            f"force_unique_name returned a name that already exists in the "
            f"database: {returned_name!r} (planted primary={primary_name!r}, "
            f"collision={collision_name!r})",
        )

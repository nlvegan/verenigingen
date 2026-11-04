"""#2012: the registry carries the v15 per-key cooldowns (maintainer ruling 2026-11-03).

Expected values are READ from the two v15 patches (``tests/utils/v15_cooldowns.py``), not typed
here: the migrate patch wins where the two disagree, except the #1999 reminder keys.
"""

from frappe.tests.utils import FrappeTestCase

from verenigingen.notification_registry import DEFAULT_COOLDOWN_MINUTES, NOTIFICATION_KEYS
from verenigingen.tests.utils.v15_cooldowns import (
    MIGRATE_PATCH,
    RULED_ON_1999,
    TEAM_PATCH,
    patch_cooldowns,
    ruled_v15_cooldowns,
)


def _registry_cooldown(key):
    return NOTIFICATION_KEYS[key].get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)


class TestRegistryMatchesV15Patches(FrappeTestCase):
    def test_every_ruled_key_has_its_v15_value(self):
        ruled = ruled_v15_cooldowns(NOTIFICATION_KEYS)
        self.assertGreater(len(ruled), 40, "control: the AST walk found the patch entries")
        wrong = {k: (_registry_cooldown(k), v) for k, v in ruled.items() if _registry_cooldown(k) != v}
        self.assertEqual(wrong, {}, "registry vs v15 (registry, v15)")

    def test_transactional_keys_are_not_throttled(self):
        for key in (
            "member_application_approved",
            "member_application_rejected",
            "expense_approved",
            "dues_amendment_approved",
            "payment_plan_approved",
            "periodic_donation_confirmation",
            "sepa_batch_error",
        ):
            self.assertEqual(_registry_cooldown(key), 0, key)

    def test_reminder_keys_get_the_longer_v15_value(self):
        self.assertEqual(_registry_cooldown("anbi_consent_request"), 43200)
        self.assertEqual(_registry_cooldown("membership_renewal_reminder"), 1440)
        self.assertEqual(_registry_cooldown("termination_overdue"), 1440)

    def test_migrate_patch_wins_over_the_team_patch(self):
        migrate, team = patch_cooldowns(MIGRATE_PATCH), patch_cooldowns(TEAM_PATCH)
        disagree = [k for k in migrate if k in team and migrate[k] != team[k] and k in NOTIFICATION_KEYS]
        self.assertIn("anbi_consent_request", disagree, "control: the patches do disagree somewhere")
        for key in disagree:
            if key not in RULED_ON_1999:
                self.assertEqual(_registry_cooldown(key), migrate[key], key)

    def test_the_1999_reminder_keys_keep_their_ruled_value(self):
        self.assertEqual(_registry_cooldown("payment_reminder_friendly"), 10080)
        self.assertEqual(_registry_cooldown("payment_reminder_urgent"), 4320)

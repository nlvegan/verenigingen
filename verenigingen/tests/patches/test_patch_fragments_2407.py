"""#2407: post_model_sync patches registered as one fragment file each, not appended to patches.txt.

Every patch-adding PR used to append a line at the same place in patches.txt, so each conflicted
with the next one to merge and the merge queue dropped it (#2376: 13 drops in two days). A new
post_model_sync patch is now one file in verenigingen/patches.d/post_model_sync/, named
<YYYYMMDDTHHMM>-<slug>.txt and holding exactly the line it would have added.

Frappe has no hook for extra patches. `get_patches_from_app` is the one function both `bench migrate`
(run_all -> get_all_patches) and `install-app` (set_all_patches_as_completed) read, so the app wraps it.
The tests below go through those same lookup paths, so a Frappe change that bypasses the wrapper reddens
them. Fragment files written here are real files in the app tree, removed again by addCleanup.
"""

import uuid
from pathlib import Path

import frappe
from frappe.modules import patch_handler
from frappe.modules.patch_handler import PatchType
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import patch_fragments

FRAGMENT_DIR = Path(frappe.get_app_path("verenigingen", "patches.d", "post_model_sync"))


class PatchFragmentCase(FrappeTestCase):
    def setUp(self):
        patch_fragments.install()
        self.tag = uuid.uuid4().hex[:10]

    def fragment(self, stamp, text, slug=None):
        path = FRAGMENT_DIR / f"{stamp}-{slug or 'test-' + self.tag}.txt"
        self.assertFalse(path.exists(), path)
        path.write_text(text)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def entry(self, n=0):
        # An `execute:` entry with a unique `#tag` suffix: a valid Patch Log key that nothing runs here.
        return f'execute:frappe.db.get_value("User", "Administrator") #2407-{self.tag}-{n}'


class TestFragmentsReachFrappesPatchList(PatchFragmentCase):
    def test_migrate_path_runs_fragments_after_patches_txt_in_filename_order(self):
        self.fragment("99991231T2359", self.entry(1) + "\n", slug="z-" + self.tag)
        self.fragment("99991231T2358", "# why: ordering control\n" + self.entry(0) + "\n")
        post = patch_handler.get_all_patches(PatchType.post_model_sync)
        txt = patch_handler.parse_as_configfile(frappe.get_app_path("verenigingen", "patches.txt"), PatchType.post_model_sync)
        # get_all_patches concatenates apps in install order (hrms follows verenigingen on the test
        # sites), so the fragments are checked against THIS app's block: straight after its last
        # patches.txt entry, earlier timestamp first.
        last = post.index(txt[-1])
        self.assertEqual(post[last + 1 : last + 3], [self.entry(0), self.entry(1)])

    def test_fragments_are_never_pre_model_sync(self):
        self.fragment("99991231T2359", self.entry() + "\n")
        self.assertNotIn(self.entry(), patch_handler.get_all_patches(PatchType.pre_model_sync))
        # untyped (what install-app reads): pre entries first, fragments last
        self.assertEqual(patch_handler.get_patches_from_app("verenigingen")[-1], self.entry())

    def test_install_path_marks_fragments_complete(self):
        # set_all_patches_as_completed() imports get_patches_from_app INSIDE the function at call time
        # and inserts a Patch Log row per entry (then commits, so it is not called here). Resolve it
        # the same way it does.
        self.fragment("99991231T2359", self.entry() + "\n")
        from frappe.modules.patch_handler import get_patches_from_app

        self.assertIn(self.entry(), get_patches_from_app("verenigingen"))

    def test_other_apps_are_untouched(self):
        self.fragment("99991231T2359", self.entry() + "\n")
        self.assertNotIn(self.entry(), patch_handler.get_patches_from_app("frappe"))

    def test_install_is_idempotent(self):
        self.fragment("99991231T2359", self.entry() + "\n")
        patch_fragments.install()
        patch_fragments.install()
        self.assertEqual(patch_handler.get_patches_from_app("verenigingen").count(self.entry()), 1)

    def test_wrapper_is_installed_by_the_migrate_and_install_hooks(self):
        # bench migrate runs before_migrate hooks before either patch pass; install-app runs
        # before_install hooks before set_all_patches_as_completed (frappe/migrate.py, installer.py).
        target = "verenigingen.setup.patch_fragments.install"
        self.assertIn(target, frappe.get_hooks("before_migrate", app_name="verenigingen"))
        self.assertIn(target, frappe.get_hooks("before_install", app_name="verenigingen"))


class TestBadFragmentsFailLoudly(PatchFragmentCase):
    def assertRejected(self, needle):
        with self.assertRaises(frappe.ValidationError) as ctx:
            patch_handler.get_all_patches(PatchType.post_model_sync)
        self.assertIn(needle, str(ctx.exception))

    def test_name_without_timestamp(self):
        path = FRAGMENT_DIR / f"test-{self.tag}.txt"
        path.write_text(self.entry() + "\n")
        self.addCleanup(path.unlink, missing_ok=True)
        self.assertRejected(path.name)

    def test_two_entries_in_one_fragment(self):
        p = self.fragment("99991231T2359", self.entry(0) + "\n" + self.entry(1) + "\n")
        self.assertRejected(p.name)

    def test_fragment_with_no_entry(self):
        p = self.fragment("99991231T2359", "# only a comment\n\n")
        self.assertRejected(p.name)

    def test_fragment_repeating_a_patches_txt_entry(self):
        txt = patch_handler.parse_as_configfile(frappe.get_app_path("verenigingen", "patches.txt"), PatchType.post_model_sync)
        self.fragment("99991231T2359", txt[-1] + "\n")
        self.assertRejected(txt[-1])

    def test_two_fragments_with_the_same_entry(self):
        self.fragment("99991231T2358", self.entry() + "\n", slug="a-" + self.tag)
        self.fragment("99991231T2359", self.entry() + "\n", slug="b-" + self.tag)
        self.assertRejected(self.entry())

    def test_dotted_entry_must_import_with_an_execute(self):
        missing = f"verenigingen.patches.v2_2.no_such_patch_{self.tag}"
        self.fragment("99991231T2359", missing + "\n")
        self.assertRejected(missing)


class TestCommittedFragmentsAreValid(FrappeTestCase):
    def test_every_committed_fragment_parses(self):
        # The same reader migrate uses; a bad committed fragment fails here instead of mid-migrate.
        patch_fragments.read_fragments()

    def test_patches_txt_post_model_sync_is_frozen(self):
        # New post_model_sync patches go in patches.d/post_model_sync/ (see patches.d/README.md).
        # Appending here again would bring back the merge-queue conflicts of #2376.
        post = patch_handler.parse_as_configfile(frappe.get_app_path("verenigingen", "patches.txt"), PatchType.post_model_sync)
        self.assertEqual(post[FROZEN_COUNT - 1], FROZEN_LAST_ENTRY, "entries before the freeze point changed")
        added = [e for e in post[FROZEN_COUNT:] if e not in IN_FLIGHT_AT_FREEZE]
        self.assertEqual(added, [], "add a fragment in verenigingen/patches.d/post_model_sync/ instead")


# patches.txt [post_model_sync] on develop 3ed920773, when the freeze was written.
FROZEN_COUNT = 82
FROZEN_LAST_ENTRY = "verenigingen.patches.v2_2.remove_dead_critical_rules_matching_no_function_2306"
# Open PRs that already appended an entry when the freeze landed. They may still merge in any order,
# and keep-both puts each after the freeze point. Do not add to this list: write a fragment.
IN_FLIGHT_AT_FREEZE = {
    "verenigingen.patches.v2_2.delete_dead_donation_form_web_form_813",  # #2293
    "verenigingen.patches.v2_2.route_manual_dues_summary_to_administrators_2169",  # #2262
    "verenigingen.patches.v2_2.zero_ponto_hand_booking_cooldown_2248",  # #2389
    "verenigingen.patches.v2_2.remove_dead_get_member_home_page_critical_operation_rule_2253",  # #2403
}

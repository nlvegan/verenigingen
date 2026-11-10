"""#2407: post_model_sync patches registered as one fragment file each, not appended to patches.txt.

Every patch-adding PR used to append a line at the same place in patches.txt, so each conflicted
with the next one to merge and the merge queue dropped it (#2376: 13 drops in two days). A new
post_model_sync patch is now one file in verenigingen/patches.d/post_model_sync/, named
<YYYYMMDDTHHMM>-<slug>.txt and holding exactly the line it would have added.

Frappe has no hook for extra patches. `get_patches_from_app` is the one function both `bench migrate`
(run_all -> get_all_patches) and `install-app` (set_all_patches_as_completed) read, so the app wraps it.
The tests below go through those same lookup paths, so a Frappe change that bypasses the wrapper reddens
them.

Fragments are written to a per-test temporary directory (`fragment_dir` points there), never into
the app tree: that tree is shared by every process on the bench, veg11's included, and a malformed
or leftover fragment there would break or run in someone else's migrate.
"""

import inspect
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import frappe
import frappe.installer
from frappe.modules import patch_handler
from frappe.modules.patch_handler import PatchType
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import patch_fragments


def patches_txt_post():
    return patch_handler.parse_as_configfile(
        frappe.get_app_path("verenigingen", "patches.txt"), PatchType.post_model_sync
    )


class PatchFragmentCase(FrappeTestCase):
    def setUp(self):
        patch_fragments.install()
        self.tag = uuid.uuid4().hex[:10]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        redirect = patch.object(patch_fragments, "fragment_dir", return_value=self.dir)
        redirect.start()
        self.addCleanup(redirect.stop)

    def fragment(self, stamp, text, slug="test"):
        path = self.dir / f"{stamp}-{slug}.txt"
        path.write_text(text)
        return path

    def entry(self, n=0):
        # An `execute:` entry with a unique `#tag` suffix: a valid Patch Log key that nothing runs here.
        return f'execute:frappe.db.get_value("User", "Administrator") #2407-{self.tag}-{n}'


class TestFragmentsReachFrappesPatchList(PatchFragmentCase):
    def test_migrate_path_runs_fragments_after_patches_txt_in_filename_order(self):
        # Written later-timestamp first, so directory order alone would not give the right answer.
        self.fragment("20261110T1501", self.entry(1) + "\n", slug="b")
        self.fragment("20261110T1500", "# why: ordering control\n" + self.entry(0) + "\n", slug="a")
        post = patch_handler.get_all_patches(PatchType.post_model_sync)
        # get_all_patches concatenates apps in install order (hrms follows verenigingen on the test
        # sites), so position is checked against THIS app's last patches.txt entry, not the list end.
        first, second = post.index(self.entry(0)), post.index(self.entry(1))
        self.assertGreater(first, post.index(patches_txt_post()[-1]))
        self.assertEqual(second, first + 1)

    def test_fragments_are_never_pre_model_sync(self):
        self.fragment("20261110T1500", self.entry() + "\n")
        self.assertNotIn(self.entry(), patch_handler.get_all_patches(PatchType.pre_model_sync))
        # untyped (what install-app reads): pre entries first, fragments after this app's post entries
        untyped = patch_handler.get_patches_from_app("verenigingen")
        self.assertGreater(untyped.index(self.entry()), untyped.index(patches_txt_post()[-1]))

    def test_install_path_marks_fragments_complete(self):
        # set_all_patches_as_completed() imports get_patches_from_app INSIDE the function at call time
        # and inserts a Patch Log row per entry (then commits, so it is not called here). Resolve it
        # the same way it does.
        self.fragment("20261110T1500", self.entry() + "\n")
        from frappe.modules.patch_handler import get_patches_from_app

        self.assertIn(self.entry(), get_patches_from_app("verenigingen"))

    def test_other_apps_are_untouched(self):
        self.fragment("20261110T1500", self.entry() + "\n")
        self.assertNotIn(self.entry(), patch_handler.get_patches_from_app("frappe"))

    def test_install_is_idempotent(self):
        self.fragment("20261110T1500", self.entry() + "\n")
        patch_fragments.install()
        patch_fragments.install()
        self.assertEqual(patch_handler.get_patches_from_app("verenigingen").count(self.entry()), 1)

    def test_wrapper_is_installed_by_the_migrate_and_install_hooks(self):
        target = "verenigingen.setup.patch_fragments.install"
        self.assertIn(target, frappe.get_hooks("before_migrate", app_name="verenigingen"))
        self.assertIn(target, frappe.get_hooks("before_install", app_name="verenigingen"))

    def test_frappe_runs_before_install_before_marking_patches_complete(self):
        # The install path depends on this order inside frappe.installer.install_app. If a Frappe
        # update marks patches before running before_install, fragments would be missing from the
        # marking and a fresh site would RUN them all on its first migrate.
        source = inspect.getsource(frappe.installer.install_app)
        self.assertLess(source.index("before_install"), source.index("set_all_patches_as_completed("))


class TestBadFragmentsFailLoudly(PatchFragmentCase):
    def assertRejected(self, needle):
        with self.assertRaises(frappe.ValidationError) as ctx:
            patch_handler.get_all_patches(PatchType.post_model_sync)
        self.assertIn(needle, str(ctx.exception))

    def test_name_without_timestamp(self):
        path = self.dir / "no-timestamp.txt"
        path.write_text(self.entry() + "\n")
        self.assertRejected(path.name)

    def test_two_entries_in_one_fragment(self):
        p = self.fragment("20261110T1500", self.entry(0) + "\n" + self.entry(1) + "\n")
        self.assertRejected(p.name)

    def test_fragment_with_no_entry(self):
        p = self.fragment("20261110T1500", "# only a comment\n\n")
        self.assertRejected(p.name)

    def test_fragment_repeating_a_patches_txt_entry(self):
        self.fragment("20261110T1500", patches_txt_post()[-1] + "\n")
        self.assertRejected(patches_txt_post()[-1])

    def test_two_fragments_with_the_same_entry(self):
        self.fragment("20261110T1500", self.entry() + "\n", slug="a")
        self.fragment("20261110T1501", self.entry() + "\n", slug="b")
        self.assertRejected(self.entry())

    def test_a_deleted_patch_module_does_not_break_the_runtime_read(self):
        # Like a patches.txt line, an executed fragment whose module was later deleted must not
        # break every migrate; the import check is a CI test over committed fragments instead.
        missing = f"verenigingen.patches.v2_2.no_such_patch_{self.tag}"
        self.fragment("20261110T1500", missing + "\n")
        self.assertIn(missing, patch_handler.get_all_patches(PatchType.post_model_sync))
        self.assertEqual(patch_fragments.unimportable_entries([missing, self.entry()]), [missing])


class TestCommittedFragmentsAreValid(FrappeTestCase):
    def test_every_committed_fragment_parses_and_imports(self):
        # The same reader migrate uses, over the real directory; plus the import check it skips.
        # Deleting a patch module means deleting its fragment too (patches.d/README.md).
        self.assertEqual(patch_fragments.unimportable_entries(patch_fragments.read_fragments()), [])

    def test_patches_txt_post_model_sync_is_frozen(self):
        # New post_model_sync patches go in patches.d/post_model_sync/ (see patches.d/README.md).
        # Appending here again would bring back the merge-queue conflicts of #2376.
        post = patches_txt_post()
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

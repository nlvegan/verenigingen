"""post_model_sync patches registered as one fragment file each (#2407).

Every PR that appended a line to the end of patches.txt conflicted with the next one to merge, so the
merge queue dropped it and its CI ran again (#2376). A new post_model_sync patch is instead one file:

    verenigingen/patches.d/post_model_sync/<YYYYMMDDTHHMM>-<slug>.txt

holding exactly the line it would have added to patches.txt (comment lines starting with # allowed).
Fragments run after every patches.txt post_model_sync entry, in filename (= timestamp) order.

Frappe reads patches only from patches.txt and has no hook for more. Both `bench migrate`
(patch_handler.run_all -> get_all_patches) and `install-app` (installer.set_all_patches_as_completed)
get the list from patch_handler.get_patches_from_app, so `install()` wraps that function. It is
registered as a before_migrate and a before_install hook, which Frappe runs before either caller.
Wrapping there, rather than running fragments from after_migrate, keeps them inside the
post_model_sync pass (before fixtures and customizations sync) and keeps fresh installs marking them
complete instead of running them.
"""

import importlib
import re
from pathlib import Path

import frappe
from frappe import _
from frappe.modules import patch_handler

APP = "verenigingen"
FRAGMENT_NAME = re.compile(r"^\d{8}T\d{4}-[a-z0-9][a-z0-9-]*\.txt$")


def install():
    """Make patch_handler.get_patches_from_app also return this app's fragments. Idempotent."""
    original = patch_handler.get_patches_from_app
    if getattr(original, "_verenigingen_fragments", False):
        return

    def get_patches_from_app(app, patch_type=None):
        patches = original(app, patch_type=patch_type)
        if app == APP and patch_type in (None, patch_handler.PatchType.post_model_sync):
            patches = patches + read_fragments()
        return patches

    get_patches_from_app._verenigingen_fragments = True
    get_patches_from_app.__wrapped__ = original
    patch_handler.get_patches_from_app = get_patches_from_app


def read_fragments():
    """This app's fragment entries in run order. Throws on any malformed fragment."""
    directory = Path(frappe.get_app_path(APP, "patches.d", "post_model_sync"))
    if not directory.is_dir():
        return []
    seen = set(_patches_txt_entries())
    entries = []
    for path in sorted(p for p in directory.iterdir() if not p.name.startswith(".")):
        entry = _read_one(path)
        if entry in seen:
            frappe.throw(_("Patch fragment {0}: {1} is already registered").format(path.name, entry))
        _check_importable(path.name, entry)
        seen.add(entry)
        entries.append(entry)
    return entries


def _patches_txt_entries():
    return patch_handler.parse_as_configfile(frappe.get_app_path(APP, "patches.txt"))


def _read_one(path):
    if not FRAGMENT_NAME.match(path.name):
        frappe.throw(_("Patch fragment {0}: name must be <YYYYMMDDTHHMM>-<slug>.txt").format(path.name))
    lines = [line.strip() for line in path.read_text().splitlines()]
    entries = [line for line in lines if line and not line.startswith("#")]
    if len(entries) != 1:
        frappe.throw(
            _("Patch fragment {0}: expected exactly one patch entry, found {1}").format(
                path.name, len(entries)
            )
        )
    return entries[0]


def _check_importable(name, entry):
    """A dotted entry must name a module with execute(), as patch_handler.execute_patch requires."""
    if entry.startswith(("execute:", "finally:")):
        return
    module = entry.split(maxsplit=1)[0]
    try:
        importable = callable(getattr(importlib.import_module(module), "execute", None))
    except ImportError:
        importable = False
    if not importable:
        frappe.throw(_("Patch fragment {0}: {1} has no importable execute()").format(name, module))

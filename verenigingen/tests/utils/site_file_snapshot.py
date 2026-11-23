"""Restore a site file a test class is about to rewrite, exactly as it found it (#2963).

Saving Brand Settings (or calling `force_rebuild_css`) writes
`sites/<site>/public/css/brand_colors.css`. Frappe's DB rollback cannot reach a file,
so without this the file outlives the class and every later brand test on that site
takes the static-file branch, never the file-less fallback.
"""

import os

import frappe


def brand_colors_css_path():
    """Where the static brand CSS lives; deliberately does not create the directory."""
    return frappe.get_site_path("public", "css", "brand_colors.css")


def restore_file_state_on_class_cleanup(test_class, path):
    """Snapshot `path` now and register a class cleanup that puts that state back.

    Absent before -> deleted afterwards. Present before -> same bytes afterwards.
    A class cleanup also runs when setUpClass or a test fails.
    """
    existed = os.path.exists(path)
    original = None
    if existed:
        with open(path, "rb") as handle:
            original = handle.read()
    test_class.addClassCleanup(_put_file_state_back, path, original)


def _put_file_state_back(path, original):
    if original is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "wb") as handle:
        handle.write(original)

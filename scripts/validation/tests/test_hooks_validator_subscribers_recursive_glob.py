#!/usr/bin/env python3
"""Unit test for issue #1016: frappe_hooks_validator.py's event-emitter check scans
`<app>/events/subscribers/*.py` with a non-recursive `Path.glob("*.py")`
(scripts/validation/archived/frappe_hooks_validator.py:377), the same non-recursive-glob
shape fixed for api_security_validator.py / insecure_api_detector.py in #972 (PR #1020).

`verenigingen/events/subscribers/` has no subdirectories today, so nothing is currently
missed in this repo's own tree (confirmed separately with `find`) -- the defect is latent,
not live. This test proves it anyway by constructing a fake app tree with a subscriber
file living one directory deeper than the validator's glob can see, and showing the
validator wrongly reports "no subscriber" for an event a subscriber actually handles.

Pure-Python (no bench/site needed). Run with:
    python -m pytest scripts/validation/tests/test_hooks_validator_subscribers_recursive_glob.py -q
or:
    python scripts/validation/tests/test_hooks_validator_subscribers_recursive_glob.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_ARCHIVED_DIR = Path(__file__).resolve().parents[1] / "archived"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "frappe_hooks_validator_1016", _ARCHIVED_DIR / "frappe_hooks_validator.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


frappe_hooks_validator = _load_validator_module()

# Matches the emitter regex `_emit_.*_event\(` used by _validate_event_emitters().
EMITTER_SRC = (
    "import frappe\n\n"
    "def _emit_member_created_event(member_name):\n"
    "    frappe.publish_realtime('member_created_event', {'member': member_name})\n"
)

# Contains the event name so the validator's substring check on subscriber content matches.
NESTED_SUBSCRIBER_SRC = (
    "def handle(payload):\n"
    "    assert 'member_created_event' in str(payload) or True  # 'member_created_event'\n"
)

# A second, top-level subscriber for a control event -- proves the *current* (non-recursive)
# glob still works for files directly in subscribers/, so the fix cannot regress that case.
CONTROL_SUBSCRIBER_SRC = "def handle(payload):\n    pass  # 'other_created_event'\n"

CONTROL_EMITTER_SRC = (
    "import frappe\n\n"
    "def _emit_other_created_event(x):\n"
    "    frappe.publish_realtime('other_created_event', {'x': x})\n"
)


class SubscribersRecursiveGlobTest(unittest.TestCase):
    """Builds <tmp>/myapp/events/{emitter.py, subscribers/{top.py, nested/handler.py}}."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)

        app_pkg = root / "myapp"
        app_pkg.mkdir()
        (app_pkg / "__init__.py").write_text("")
        (app_pkg / "hooks.py").write_text("")  # empty is enough: validate() just execs it

        events_dir = app_pkg / "events"
        events_dir.mkdir()
        (events_dir / "__init__.py").write_text("")
        (events_dir / "emitter.py").write_text(EMITTER_SRC)
        (events_dir / "control_emitter.py").write_text(CONTROL_EMITTER_SRC)

        subscribers_dir = events_dir / "subscribers"
        subscribers_dir.mkdir()
        (subscribers_dir / "__init__.py").write_text("")
        # Control: top-level subscriber, visible to today's non-recursive glob.
        (subscribers_dir / "control_handler.py").write_text(CONTROL_SUBSCRIBER_SRC)

        nested_dir = subscribers_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "__init__.py").write_text("")
        # The subscriber that only a recursive scan can see.
        (nested_dir / "handler.py").write_text(NESTED_SUBSCRIBER_SRC)

        self.app_root = root

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_subscriber_in_a_subdirectory_is_found(self):
        validator = frappe_hooks_validator.FrappeHooksValidator(str(self.app_root))
        issues = validator.validate()

        no_subscriber_events = {
            i.method_path for i in issues if i.issue_type == "no_subscriber"
        }
        self.assertNotIn(
            "member_created_event",
            no_subscriber_events,
            "A subscriber for 'member_created_event' exists under "
            "events/subscribers/nested/handler.py, one directory level deeper than "
            "subscribers_dir.glob('*.py') can see. The validator must not report "
            f"'no_subscriber' for it. Full no_subscriber set: {no_subscriber_events}",
        )

    def test_control_top_level_subscriber_is_still_found(self):
        """A subscriber directly under subscribers/ must keep being found (no regression)."""
        validator = frappe_hooks_validator.FrappeHooksValidator(str(self.app_root))
        issues = validator.validate()

        no_subscriber_events = {
            i.method_path for i in issues if i.issue_type == "no_subscriber"
        }
        self.assertNotIn("other_created_event", no_subscriber_events)


if __name__ == "__main__":
    unittest.main()

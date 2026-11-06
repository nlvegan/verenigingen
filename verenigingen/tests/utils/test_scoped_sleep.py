"""The scoped sleep patches keep a stray thread's ``time.sleep`` out of the recorder (#2156).

Each test runs a REAL second thread that calls ``time.sleep(1.0)`` while the patch is active
(and checks it did, so the claim is not vacuous), with a control showing the old global patch
does record it.
"""

import threading
import time
import unittest
from unittest.mock import patch

from verenigingen.tests.utils.scoped_sleep import patch_module_sleep, patch_thread_sleep


class _Module:
    """Stand-in for a module under test that holds its own ``time`` reference."""

    time = time

    @classmethod
    def nap(cls, seconds):
        cls.time.sleep(seconds)


def _stray_thread_sleeps_once(seconds):
    """Sleep ``seconds`` on another thread and wait for it; return whether it ran."""
    ran = threading.Event()

    def stray():
        time.sleep(seconds)
        ran.set()

    thread = threading.Thread(target=stray, daemon=True)
    thread.start()
    thread.join(10)
    return ran.is_set()


class TestScopedSleep(unittest.TestCase):
    def test_control_global_patch_records_the_stray_thread(self):
        """The old shape: patching ``<module>.time.sleep`` is the global ``time.sleep``."""
        with patch.object(_Module.time, "sleep") as slept:
            self.assertTrue(_stray_thread_sleeps_once(1.0))
        self.assertEqual(slept.call_count, 1, "control: the stray thread's sleep must land here")

    def test_module_patch_records_only_the_module(self):
        with patch_module_sleep(_Module) as fake_time:
            _Module.nap(1.0)
            stray_ran = _stray_thread_sleeps_once(0.01)  # real sleep on the other thread
        self.assertTrue(stray_ran)
        self.assertEqual(fake_time.sleep.call_args_list, [unittest.mock.call(1.0)])

    def test_module_patch_restores_and_delegates_other_attributes(self):
        original = _Module.time
        with patch_module_sleep(_Module) as fake_time:
            self.assertAlmostEqual(fake_time.time(), time.time(), delta=5)
        self.assertIs(_Module.time, original)

    def test_module_patch_by_dotted_path_and_custom_recorder(self):
        recorded = []
        with patch_module_sleep(f"{__name__}._Module", recorded.append):
            _Module.nap(2.0)
            stray_ran = _stray_thread_sleeps_once(0.01)
        self.assertTrue(stray_ran)
        self.assertEqual(recorded, [2.0])

    def test_thread_patch_records_only_the_calling_thread(self):
        recorded = []
        with patch_thread_sleep(recorded.append):
            time.sleep(3)  # this thread: recorded, not slept
            stray_ran = _stray_thread_sleeps_once(0.01)  # other thread: real sleep
        self.assertTrue(stray_ran)
        self.assertEqual(recorded, [3])

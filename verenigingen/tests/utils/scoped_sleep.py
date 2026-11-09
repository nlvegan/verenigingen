"""Patch ``time.sleep`` for ONE module (or ONE thread), not for the whole process (#2156).

``patch("time.sleep")`` and ``patch.object(<module>.time, "sleep")`` both replace the
attribute on the stdlib ``time`` module itself, because every module's ``time`` IS that
module. A mock that records or counts calls then also records a stray thread's
``time.sleep``, and a mock that returns at once turns that thread's ``while ...: sleep()``
loop into a busy loop (#2155).

``patch_module_sleep`` replaces only the module's own ``time`` reference with a
``Mock(wraps=time)`` whose ``.sleep`` is the recorder; every other ``time`` attribute still
delegates to the real module and other threads keep the real ``time.sleep``. The patch
yields that fake ``time``, so the recorder is ``fake_time.sleep``.

``patch_thread_sleep`` is for code that imports ``time`` inside the function (nothing to
re-point on the module): the patched ``time.sleep`` runs the recorder for the calling
thread only and hands every other thread to the real ``time.sleep``.
"""

import threading
import time
from contextlib import contextmanager
from functools import partial
from unittest.mock import Mock, patch


def _wrapped_time(sleep=None, **sleep_kwargs):
    fake_time = Mock(wraps=time)
    fake_time.sleep = sleep if sleep is not None else Mock(**sleep_kwargs)
    return fake_time


def patch_module_sleep(module_or_path, sleep=None, **sleep_kwargs):
    """Patcher (context manager AND decorator) for ``module.time``.

    ``module_or_path`` is the module object, or its dotted path for decorator use
    (``"pkg.mod"``, not ``"pkg.mod.time"``). Entering yields the fake ``time``; use
    ``fake_time.sleep`` for ``call_count`` / ``call_args_list``. Pass ``sleep`` to
    substitute your own callable (e.g. ``recorded.append``).
    """
    factory = partial(_wrapped_time, sleep, **sleep_kwargs)
    if isinstance(module_or_path, str):
        return patch(f"{module_or_path}.time", new_callable=factory)
    return patch.object(module_or_path, "time", new_callable=factory)


@contextmanager
def patch_thread_sleep(recorder):
    """Route ``time.sleep`` to ``recorder`` for the calling thread only.

    The owner is the thread that ENTERS the patch. Sleeps on any other thread, including
    threads the code under test starts itself (e.g. a ThreadPoolExecutor), run for real
    and are not recorded, so assert only on sleeps taken on the calling thread.
    """
    owner = threading.get_ident()
    real_sleep = time.sleep

    def sleep(seconds):
        if threading.get_ident() == owner:
            return recorder(seconds)
        return real_sleep(seconds)

    with patch("time.sleep", sleep):
        yield

"""Filesystem anchors for tests that read the app's own source.

`APP_ROOT` is computed from *this* module's location, not the caller's. Tests
that walk the tree previously each re-derived it from their own `__file__`,
which made the parent count a function of how deeply the test file happened to
sit: `parents[2]` from `tests/`, `parents[4]` from `tests/backend/validation/`.
Moving a test file then silently changed which directory it scanned. Anchoring
here makes the depth this module's problem rather than every caller's.

Careful when migrating a caller: not every such expression targets the app root.
From `tests/backend/portal/`, `parents[3]` is the **`verenigingen` package**, and
two files there use it that way deliberately. Print what the old and the new
expression resolve to before swapping one for the other -- a silent retarget one
directory up is the bug this module removes, reintroduced.
"""

import pathlib

# verenigingen/tests/utils/paths.py -> parents[3] is the app root: the directory
# holding the `verenigingen` package and `scripts/`.
APP_ROOT = pathlib.Path(__file__).resolve().parents[3]

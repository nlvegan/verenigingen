"""#1785: a patch started in setUp (or a setUp helper) must be stopped via addCleanup.

unittest does not run tearDown when setUp raises, and a skipTest counts as a raise.
A patch started in setUp and stopped only in tearDown therefore outlives a test whose
setUp fails after the .start(), and every later test in the shard process runs with
the stub installed (the #1782 shape, found again in ~25 concrete classes).

Ratchet: no function that is not a test method (setUp, setUpClass, helpers) may call
.start() on a patcher without an addCleanup/addClassCleanup that stops it. A cleanup
whose argument mentions "patch" or "mock" (e.g. a ``_cleanup_test_mocks`` method that
stops a list) is accepted for the whole function. A function that RETURNS the patcher
hands ownership to its caller, which is then checked in turn. Context-manager
``__enter__`` methods are exempt: ``__exit__`` owns the stop.
"""

import ast
import re
import unittest
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_CLEANUP_NAMES = {"addCleanup", "addClassCleanup", "enterContext", "enterClassContext"}
_EXEMPT_FUNCTIONS = {"__enter__", "__exit__"}


def _is_patch_call(node):
    """True for patch(...), patch.object(...), mock.patch.dict(...), _patch(...)."""
    if not isinstance(node, ast.Call):
        return False
    return "patch" in ast.unparse(node.func).lower()


def _patcher_names(func):
    """Receivers assigned from a patch(...) call, plus anything named like a patcher."""
    names = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and _is_patch_call(node.value):
            names.update(ast.unparse(t) for t in node.targets)
    return names


def _is_patcher(receiver, names):
    text = ast.unparse(receiver)
    return (
        _is_patch_call(receiver)
        or text in names
        or re.search(r"patch|mock", text, re.IGNORECASE) is not None
    )


def _cleanup_args(func):
    args = []
    for node in ast.walk(func):
        is_cleanup = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _CLEANUP_NAMES
        )
        if is_cleanup:
            args.extend(ast.unparse(a) for a in node.args)
    return args


def _returned_names(func):
    return {
        ast.unparse(part)
        for node in ast.walk(func)
        if isinstance(node, ast.Return) and node.value is not None
        for part in (node.value.elts if isinstance(node.value, ast.Tuple) else [node.value])
    }


def find_uncleaned_starts(source):
    """(function, lineno, receiver) for every patcher .start() with no matching cleanup."""
    found = []
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name.startswith("test") or func.name in _EXEMPT_FUNCTIONS:
            continue
        names, cleanups, returned = _patcher_names(func), _cleanup_args(func), _returned_names(func)
        for node in ast.walk(func):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "start"
                and _is_patcher(node.func.value, names)
            ):
                continue
            receiver = ast.unparse(node.func.value)
            covered = f"{receiver}.stop" in cleanups or any(
                re.search(r"patch|mock", c, re.IGNORECASE) for c in cleanups
            )
            if not covered and receiver not in returned:
                found.append((func.name, node.lineno, receiver))
    return found


def _test_files():
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if "tests" in path.parts or path.name.startswith("test_"):
            yield path


class TestSetupPatchesHaveCleanup(unittest.TestCase):
    def test_no_setup_starts_a_patch_without_addcleanup(self):
        offenders = []
        for path in _test_files():
            try:
                source = path.read_text()
            except UnicodeDecodeError:
                continue
            for name, lineno, receiver in find_uncleaned_starts(source):
                offenders.append(f"{path.relative_to(_PACKAGE_ROOT.parent)}:{lineno} {name}() {receiver}")
        self.assertEqual(
            offenders,
            [],
            "patch started without self.addCleanup(<patcher>.stop) (tearDown is skipped when "
            "setUp raises or skips, #1785):\n" + "\n".join(offenders),
        )

    def test_the_scan_covers_the_tree(self):
        # Control: an empty file list would make the test above vacuously green.
        self.assertGreater(len(list(_test_files())), 100)

    def test_flags_the_leaking_shapes(self):
        leaking = {
            "attribute receiver": "def setUp(self):\n    self.p = patch('a.b')\n    self.p.start()\n"
            "def tearDown(self):\n    self.p.stop()\n",
            "local receiver": "def setUp(self):\n    p = patch.object(A, 'b')\n    p.start()\n",
            "chained": "def setUp(self):\n    patch('a.b').start()\n",
            "setUpClass": "def setUpClass(cls):\n    cls.p = mock.patch('a.b')\n    cls.p.start()\n",
            "helper": "def _install(self):\n    p = patch('a.b')\n    p.start()\n",
            "wrong patcher stopped": "def setUp(self):\n    self.p = patch('a')\n    self.q = patch('b')\n"
            "    self.p.start()\n    self.q.start()\n    self.addCleanup(self.p.stop)\n",
        }
        for label, source in leaking.items():
            with self.subTest(label):
                self.assertTrue(find_uncleaned_starts(source), label)

    def test_accepts_the_safe_shapes(self):
        safe = {
            "addCleanup": "def setUp(self):\n    self.p = patch('a')\n    self.p.start()\n"
            "    self.addCleanup(self.p.stop)\n",
            "addClassCleanup": "def setUpClass(cls):\n    cls.p = patch('a')\n    cls.p.start()\n"
            "    cls.addClassCleanup(cls.p.stop)\n",
            "list cleanup": "def setUp(self):\n    self.mocks = [patch('a')]\n    m = patch('b')\n"
            "    m.start()\n    self.addCleanup(self._cleanup_test_mocks)\n",
            "returned to caller": "def _make():\n    p = patch('a')\n    p.start()\n    return p\n",
            "context manager": "def __enter__(self):\n    self.p = patch('a')\n    self.p.start()\n",
            "thread, not a patcher": "def setUp(self):\n    t = Thread(target=f)\n    t.start()\n",
            "test body": "def test_x(self):\n    p = patch('a')\n    p.start()\n",
        }
        for label, source in safe.items():
            with self.subTest(label):
                self.assertEqual(find_uncleaned_starts(source), [], label)

"""#1785: a patch started in setUp (or a setUp helper) must be stopped via addCleanup.

unittest does not run tearDown when setUp raises, and a skipTest counts as a raise.
A patch started in setUp and stopped only in tearDown therefore outlives a test whose
setUp fails after the .start(), and every later test in the shard process runs with
the stub installed (the #1782 shape, found again in ~25 concrete classes).

Ratchet: no function that is not a test method (setUp, setUpClass, helpers) may call
.start() on a patcher unless the function registers a cleanup that is either
``<receiver>.stop`` or a method of the same class that calls ``.stop()`` and names that
receiver (or shares a ``self.<container>`` attribute with the starting function, the
``_cleanup_test_mocks`` list case). ``addClassCleanup`` does not count for a per-test
setUp. Cleanups inside nested functions or ``if False:`` do not count. Context-manager
``__enter__`` methods are exempt: ``__exit__`` owns the stop.

Known limits (0 hits on today's tree): a function that RETURNS the patcher is exempt and
its caller is NOT checked unless it calls ``.start()`` itself; loop-variable patchers are
accepted through the shared-container rule; aliased ``patch`` imports and patchers built
by helpers under names without "patch"/"mock" are not recognised.
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


def _own_nodes(func):
    """Nodes of ``func`` that always run when it does: no nested defs, no ``if False:``."""
    stack = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not node.test.value:
            stack.extend(node.orelse)
            continue
        stack.extend(ast.iter_child_nodes(node))


def _cleanup_calls(func):
    """(registering method name, unparsed first argument) for each own-level cleanup call."""
    return [
        (node.func.attr, ast.unparse(node.args[0]))
        for node in _own_nodes(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CLEANUP_NAMES
        and node.args
    ]


def _returned_names(func):
    return {
        ast.unparse(part)
        for node in _own_nodes(func)
        if isinstance(node, ast.Return) and node.value is not None
        for part in (node.value.elts if isinstance(node.value, ast.Tuple) else [node.value])
    }


def _self_attributes(func):
    return {
        ast.unparse(n)
        for n in ast.walk(func)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ("self", "cls")
    }


def _stops_something(method):
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "stop"
        for n in ast.walk(method)
    )


def _is_stopper_for(method, func, receiver):
    """A sibling method that calls .stop() and demonstrably owns this patcher.

    It owns it when its body names the receiver, or when it shares a ``self.<container>``
    attribute with the starting function (a list the patchers were appended to).
    """
    if not _stops_something(method):
        return False
    if receiver in ast.unparse(method):
        return True
    shared = _self_attributes(method) & _self_attributes(func)
    shared -= {f"self.{method.name}", f"cls.{method.name}"}
    return bool(shared)


def _is_covered(func, siblings, receiver, is_class_scope):
    for registrar, arg in _cleanup_calls(func):
        # addClassCleanup runs once per CLASS: for a patch started per test it is too late.
        if registrar in ("addClassCleanup", "enterClassContext") and not is_class_scope:
            continue
        if arg == f"{receiver}.stop":
            return True
        name = arg.split(".", 1)[1] if arg.startswith(("self.", "cls.")) else None
        if name in siblings and _is_stopper_for(siblings[name], func, receiver):
            return True
    return False


def _functions_with_context(tree):
    """(function, {method name: node} of its class, is setUpClass-like)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            siblings = {
                m.name: m for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for method in siblings.values():
                yield method, siblings
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, {}


def find_uncleaned_starts(source):
    """(function, lineno, receiver) for every patcher .start() with no matching cleanup."""
    found = []
    for func, siblings in _functions_with_context(ast.parse(source)):
        if func.name.startswith("test") or func.name in _EXEMPT_FUNCTIONS:
            continue
        is_class_scope = func.name in ("setUpClass", "setUpModule") or any(
            ast.unparse(d) == "classmethod" for d in func.decorator_list
        )
        names, returned = _patcher_names(func), _returned_names(func)
        for node in _own_nodes(func):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "start"
                and _is_patcher(node.func.value, names)
            ):
                continue
            receiver = ast.unparse(node.func.value)
            if receiver in returned or _is_covered(func, siblings, receiver, is_class_scope):
                continue
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
        head = "class T:\n  def setUp(self):\n    self.p = patch('a')\n    self.p.start()\n"
        leaking = {
            "attribute receiver": head + "  def tearDown(self):\n    self.p.stop()\n",
            "local receiver": "def setUp(self):\n    p = patch.object(A, 'b')\n    p.start()\n",
            "chained": "def setUp(self):\n    patch('a.b').start()\n",
            "setUpClass": "def setUpClass(cls):\n    cls.p = mock.patch('a.b')\n    cls.p.start()\n",
            "helper": "def _install(self):\n    p = patch('a.b')\n    p.start()\n",
            "wrong patcher stopped": "def setUp(self):\n    self.p = patch('a')\n    self.q = patch('b')\n"
            "    self.p.start()\n    self.q.start()\n    self.addCleanup(self.p.stop)\n",
            # review round: cleanups that merely MENTION patch/mock must not count
            "cleanup without .stop": head + "    self.addCleanup(self.mock_thing)\n",
            "cleanup of a string": head + "    self.addCleanup(print, 'patch')\n",
            "unrelated mock method": head + "    self.addCleanup(self.mock_db.rollback)\n",
            "cleanup in a never-called nested def": head + "    def later():\n      self.addCleanup(self.p.stop)\n",
            "cleanup under if False": head + "    if False:\n      self.addCleanup(self.p.stop)\n",
            "sibling method that does not stop": head + "    self.addCleanup(self._cleanup_mocks)\n"
            "  def _cleanup_mocks(self):\n    self.x = 1\n",
            # addClassCleanup runs once per class: a per-test patch leaks across its tests
            "addClassCleanup in setUp": head + "    self.addClassCleanup(self.p.stop)\n",
        }
        for label, source in leaking.items():
            with self.subTest(label):
                self.assertTrue(find_uncleaned_starts(source), label)

    def test_accepts_the_safe_shapes(self):
        safe = {
            "addCleanup": "def setUp(self):\n    self.p = patch('a')\n    self.p.start()\n"
            "    self.addCleanup(self.p.stop)\n",
            "addClassCleanup in setUpClass": "def setUpClass(cls):\n    cls.p = patch('a')\n    cls.p.start()\n"
            "    cls.addClassCleanup(cls.p.stop)\n",
            "stopper method naming the receiver": "class T:\n  def setUp(self):\n    self.p = patch('a')\n"
            "    self.p.start()\n    self.addCleanup(self._undo)\n"
            "  def _undo(self):\n    self.p.stop()\n",
            "stopper method over a shared list": "class T:\n  def setUp(self):\n    self.ms = []\n"
            "    m = patch('b')\n    m.start()\n    self.ms.append(m)\n    self.addCleanup(self._undo)\n"
            "  def _undo(self):\n    for m in self.ms:\n      m.stop()\n",
            "returned to caller": "def _make():\n    p = patch('a')\n    p.start()\n    return p\n",
            "context manager": "def __enter__(self):\n    self.p = patch('a')\n    self.p.start()\n",
            "thread, not a patcher": "def setUp(self):\n    t = Thread(target=f)\n    t.start()\n",
            "test body": "def test_x(self):\n    p = patch('a')\n    p.start()\n",
        }
        for label, source in safe.items():
            with self.subTest(label):
                self.assertEqual(find_uncleaned_starts(source), [], label)

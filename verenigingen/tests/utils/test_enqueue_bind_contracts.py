"""Every frappe.enqueue call in this app must be callable as enqueued.

frappe.enqueue consumes its own named parameters and forwards everything else to
the job: execute_job does `retval = method(**kwargs)` with no filtering
(frappe/utils/background_jobs.py). So a kwarg the target does not accept -- or a
required one that enqueue swallowed because the names collide -- is a TypeError
raised in the worker, long after the request that enqueued it returned 200.

Nothing else catches this class:

* The `now=True` / `is_async=False` path goes through frappe.call -> get_newargs,
  which SILENTLY DROPS unsupported kwargs. The identical bad call is invisible
  when run inline and fatal only on a real queue.
* Unit tests call job functions directly, which bypasses the kwarg split entirely.

This is a static check over the source: it never enqueues anything, so it costs
no worker time and needs no Redis.

Defect classes covered, all four found live in this app at least once:
  1. a kwarg enqueue has no parameter for (`delay=`) reaching the job
  2. a kwarg the target does not accept (`mollie_settings_name=`)
  3. a kwarg enqueue STEALS because it shares one of its own parameter names
     (`job_name=`), leaving the job missing a required argument
  4. a dotted target that does not exist at all -> AttributeError in the worker
"""

import ast
import inspect
import os
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

APP_ROOT = Path(frappe.get_app_path("verenigingen"))

# Anything outside frappe.enqueue's own signature is forwarded to the job.
ENQUEUE_PARAMS = set(inspect.signature(frappe.enqueue).parameters) - {"kwargs"} | {"async"}


def _iter_enqueue_calls():
    """Yield (path, lineno, dotted_target, job_kwargs, has_splat) for literal targets."""
    for dirpath, dirnames, filenames in os.walk(APP_ROOT):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", "__pycache__", ".git"}]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = Path(dirpath) / fname
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Cheap pre-filter: parsing every file in the app is the expensive part.
            if "enqueue" not in source:
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name != "enqueue":  # enqueue_doc resolves against a Document, not a path
                    continue

                target = node.args[0] if node.args else None
                if target is None:
                    for kw in node.keywords:
                        if kw.arg == "method":
                            target = kw.value
                if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
                    continue  # dynamic target; cannot be checked statically

                job_kwargs, all_kwargs, has_splat = set(), set(), False
                for kw in node.keywords:
                    if kw.arg is None:
                        has_splat = True
                        continue
                    all_kwargs.add(kw.arg)
                    if kw.arg not in ENQUEUE_PARAMS:
                        job_kwargs.add(kw.arg)

                yield path, node.lineno, target.value, job_kwargs, all_kwargs, has_splat


def check_call(signature, job_kwargs, all_kwargs, has_splat):
    """Return a list of problems for one enqueue call site. Pure, so it is testable.

    Split out because the repo currently has no literal-target instance of the
    "stolen kwarg" class, so the repo-wide sweep below cannot exercise that branch.
    An unexercised check is not a check -- TestStolenKwargDetection covers it.
    """
    problems = []

    try:
        # bind_partial when a **splat supplies arguments we cannot see statically;
        # a full bind would report them as missing.
        if has_splat:
            signature.bind_partial(**{k: None for k in job_kwargs})
        else:
            signature.bind(**{k: None for k in job_kwargs})
    except TypeError as exc:
        problems.append(str(exc))

    # Defect class 3: a kwarg enqueue STEALS. If the call passes a name that is both
    # one of enqueue's own parameters and a declared parameter of the target, enqueue
    # consumes it and the target silently gets its default. This BINDS successfully,
    # so the check above cannot see it.
    stolen = sorted(k for k in all_kwargs & ENQUEUE_PARAMS if k in signature.parameters)
    if stolen:
        problems.append(
            f"enqueue consumes {', '.join(stolen)} -- the job declares the same "
            f"name(s) and will receive its default instead. Rename the kwarg "
            f"(e.g. tracking_job_name)."
        )

    return problems


class TestStolenKwargDetection(FrappeTestCase):
    """Direct coverage for check_call, including the branch the sweep cannot reach."""

    @staticmethod
    def _sig(fn):
        return inspect.signature(fn)

    def test_flags_a_kwarg_enqueue_would_steal(self):
        def job(member_name, job_name=None, **kwargs):
            pass

        problems = self._sig(job), {"member_name"}, {"member_name", "job_name", "queue"}
        result = check_call(*problems, has_splat=False)
        self.assertEqual(len(result), 1, result)
        self.assertIn("enqueue consumes job_name", result[0])

    def test_does_not_flag_job_name_when_the_target_has_no_such_parameter(self):
        def job(member_name, **kwargs):
            pass

        # job_name here is only an enqueue-level label; the target never expects it.
        result = check_call(self._sig(job), {"member_name"}, {"member_name", "job_name"}, False)
        self.assertEqual([], result)

    def test_flags_an_unexpected_kwarg(self):
        def job(member_name):
            pass

        result = check_call(self._sig(job), {"member_name", "delay"}, {"member_name", "delay"}, False)
        self.assertEqual(len(result), 1, result)
        self.assertIn("unexpected keyword argument 'delay'", result[0])

    def test_flags_a_missing_required_argument(self):
        def job(target_job_name, delay):
            pass

        result = check_call(self._sig(job), {"delay"}, {"delay", "job_name"}, False)
        self.assertTrue(any("missing a required argument" in p for p in result), result)

    def test_clean_call_is_silent(self):
        def job(member_name, payment_entry=None, tracking_job_name=None, **kwargs):
            pass

        result = check_call(
            self._sig(job),
            {"member_name", "tracking_job_name"},
            {"member_name", "tracking_job_name", "queue", "timeout"},
            False,
        )
        self.assertEqual([], result)


class TestEnqueueCallsBindToTheirJobs(FrappeTestCase):
    def test_every_literal_enqueue_target_resolves_and_binds(self):
        checked, failures = 0, []

        for path, lineno, dotted, job_kwargs, all_kwargs, has_splat in _iter_enqueue_calls():
            rel = path.relative_to(APP_ROOT.parent)
            where = f"{rel}:{lineno} -> {dotted}"

            # Resolving the dotted path is itself the check for defect class 4:
            # frappe.get_attr is exactly what execute_job calls in the worker.
            try:
                target = frappe.get_attr(dotted)
            except Exception as exc:
                failures.append(f"{where}\n    unresolvable target: {type(exc).__name__}: {exc}")
                continue

            try:
                signature = inspect.signature(target)
            except (TypeError, ValueError):
                continue

            checked += 1
            for problem in check_call(signature, job_kwargs, all_kwargs, has_splat):
                failures.append(f"{where}\n    {problem}")

        # 38 literal targets resolve today. A floor well under that catches a total
        # sweep failure (broken walk, the "enqueue" prefilter regressing, a wrong
        # app root) without tripping on ordinary churn.
        self.assertGreater(checked, 35, "bind check found suspiciously few enqueue call sites")
        self.assertEqual(
            [],
            failures,
            "enqueue call sites that would raise in the worker:\n\n" + "\n\n".join(failures),
        )

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

                job_kwargs, has_splat = set(), False
                for kw in node.keywords:
                    if kw.arg is None:
                        has_splat = True
                    elif kw.arg not in ENQUEUE_PARAMS:
                        job_kwargs.add(kw.arg)

                yield path, node.lineno, target.value, job_kwargs, has_splat


class TestEnqueueCallsBindToTheirJobs(FrappeTestCase):
    def test_every_literal_enqueue_target_resolves_and_binds(self):
        checked, failures = 0, []

        for path, lineno, dotted, job_kwargs, has_splat in _iter_enqueue_calls():
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
            try:
                # bind_partial when a **splat supplies arguments we cannot see
                # statically; a full bind would report them as missing.
                if has_splat:
                    signature.bind_partial(**{k: None for k in job_kwargs})
                else:
                    signature.bind(**{k: None for k in job_kwargs})
            except TypeError as exc:
                failures.append(f"{where}\n    {exc}")

        self.assertGreater(checked, 20, "bind check found suspiciously few enqueue call sites")
        self.assertEqual(
            [],
            failures,
            "enqueue call sites that would raise in the worker:\n\n" + "\n\n".join(failures),
        )

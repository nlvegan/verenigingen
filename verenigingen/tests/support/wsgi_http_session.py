"""
Drive whitelisted endpoints through the real in-process WSGI app (#2370).

``werkzeug.test.Client(frappe.app.application)`` runs the whitelist dispatch, the session cookie
from a real ``POST /api/method/login``, Frappe's native CSRF check and this app's security
decorators, without a live web server (a CI runner has none, so ``requests`` against
``frappe.utils.get_url()`` always skipped).

Why a subprocess: ``frappe.app.application`` calls ``frappe.destroy()`` per request, which would
pull the running test's ``frappe.local`` (and its DB transaction) out from under it. The child has
its own ``frappe.local``; it inherits this process's PYTHONPATH, so it exercises whichever
verenigingen is importable. The login users and their passwords are committed first because the
child is a separate DB connection; ``cleanup_committed_login_users`` removes them again.
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path
from frappe.utils.password import update_password

from verenigingen.tests.harness_logger import get_harness_logger

# Runs in the child. Each case is {"name", "endpoint", "login": None | {"usr", "pwd"},
# "csrf": False | "valid" | "wrong" | "missing", "json": dict}. A False csrf never loads the desk,
# so the session has no token yet (and Frappe does not enforce CSRF until one exists, #2367).
# ``patches`` are dotted targets patched to a MagicMock for the whole child run (outbound side effects).
_CHILD = textwrap.dedent(
    r"""
    import json, re, sys, time
    from contextlib import ExitStack
    from unittest.mock import patch

    import frappe

    site, cases, patches = {site!r}, json.loads({cases!r}), {patches!r}
    frappe.init(site=site)
    frappe.connect()
    frappe.destroy()

    import frappe.app
    from werkzeug.test import Client

    out = {{}}
    with ExitStack() as stack:
        for target in patches:
            stack.enter_context(patch(target))
        for case in cases:
            client = Client(frappe.app.application)  # keeps the session cookie
            headers = {{"X-Frappe-Site-Name": site}}
            if case["login"]:
                login = client.post("/api/method/login", data=case["login"], headers=headers)
                assert login.status_code == 200, login.get_data(as_text=True)
                if case["csrf"]:
                    # Loading the desk page is where a browser's session gets its token
                    # (frappe.csrf_token = "..."); Frappe only enforces CSRF once one exists.
                    desk = client.get("/desk", headers=headers)
                    token = re.search(r'frappe\.csrf_token = "([^"]+)"', desk.get_data(as_text=True)).group(1)
                    if case["csrf"] == "valid":
                        headers["X-Frappe-CSRF-Token"] = token
                    elif case["csrf"] == "wrong":
                        headers["X-Frappe-CSRF-Token"] = "not-" + token
            started = time.time()
            response = client.post(case["endpoint"], json=case["json"], headers=headers)
            out[case["name"]] = {{
                "status": response.status_code,
                "body": response.get_data(as_text=True),
                "ms": (time.time() - started) * 1000,
            }}
    print("RESULT" + json.dumps(out))
    """
)


def run_wsgi_cases(*cases, patches=()):
    """Run the cases through the WSGI app in a child process; return {name: {"status", "body", "ms"}}."""
    script = _CHILD.format(site=frappe.local.site, cases=json.dumps(list(cases)), patches=list(patches))
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        cwd=os.path.join(get_bench_path(), "sites"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)
    line = next((x for x in result.stdout.splitlines() if x.startswith("RESULT")), None)
    if line is None:
        raise AssertionError(
            f"child printed no RESULT line\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(line[len("RESULT") :])


def api_path(dotted):
    return f"/api/method/{dotted}"


def _create_committed_login_user(label, password, role_profile, extra_roles=()):
    """Create and COMMIT a login user; return its email. Pair with cleanup_committed_login_users.

    Load-bearing commit: the child runs on another DB connection, which sees none of these
    rows until they are committed. A critical_api grants CRITICAL only through a vetted Role
    Profile (a bare role is not enough), hence ``role_profile``.
    """
    email = f"http-int-{label}-{frappe.generate_hash()[:8]}@test.invalid"
    user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "HTTP", "send_welcome_email": 0})
    user.append("role_profiles", {"role_profile": role_profile})
    user.insert(ignore_permissions=True)
    for role in extra_roles:  # direct roles, added after the profile sync would strip them
        frappe.get_doc(
            {"doctype": "Has Role", "parent": email, "parenttype": "User", "parentfield": "roles", "role": role}
        ).insert(ignore_permissions=True)
    update_password(email, password)
    frappe.db.commit()
    return email


def _cleanup_committed_login_users(emails):
    """Remove the committed users and the rows their logins left; re-raise the first failure."""
    frappe.db.rollback()
    failures = []
    for email in filter(None, emails):
        try:
            # Creating the User also creates its Contact; remove it here rather than leaning on the drain.
            # Found by email as well as by `user`: deleting the User first unlinks the Contact, which
            # then matched neither filter and leaked one Contact per login user (#2385).
            contacts = set(frappe.get_all("Contact", filters={"user": email}, pluck="name"))
            contacts |= set(frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent"))
            frappe.delete_doc("User", email, force=True, ignore_permissions=True)
            for contact in contacts:
                if frappe.db.exists("Contact", contact):
                    frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
            # The logins in the child process leave rows delete_doc does not remove.
            frappe.db.delete("Activity Log", {"user": email})
            frappe.db.delete("Sessions", {"user": email})  # doctype-ok: core table tabSessions, no DocType record
            # Endpoints log refusals naming the caller's email; the child writes those rows. This app
            # calls log_error(message, title), so the text lands in `method`, not `error`.
            frappe.db.delete("Error Log", {"method": ["like", f"%{email}%"]})
        except Exception as exc:
            get_harness_logger("wsgi-http").warning(f"cleanup of {email} failed: {exc!r}")
            failures.append(exc)
            frappe.db.rollback()
    frappe.db.commit()
    if failures:
        raise failures[0]


def operation_result(response):
    """The OperationResult dict an endpoint returned (the ``message`` of a 200 response)."""
    return json.loads(response["body"])["message"]


class CommittedLoginUsersMixin:
    """Test-case mixin: ``self.password`` plus committed login users removed again afterwards."""

    def _create_login_users(self, **role_profile_by_label):
        self.password = f"Probe-{frappe.generate_hash()[:12]}!"
        self._login_users = []
        self.addCleanup(self._cleanup_login_users)
        emails = {}
        for label, spec in role_profile_by_label.items():
            # A role profile name, or (role profile, extra direct roles).
            role_profile, extra_roles = (spec, ()) if isinstance(spec, str) else spec
            emails[label] = _create_committed_login_user(label, self.password, role_profile, extra_roles)
            self._login_users.append(emails[label])
        return emails

    def _cleanup_login_users(self):
        _cleanup_committed_login_users(self._login_users)

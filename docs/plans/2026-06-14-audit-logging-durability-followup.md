# Follow-up: audit-logging durability vs. transaction safety

**Date:** 2026-06-14
**Status:** decision needed (maintainer)
**Touches:** `verenigingen/utils/security/audit_logging.py`
**Related commit:** `3b79f7b5` (fix: repair payment/permission bugs surfaced by coverage work)

## What changed and why

`SecurityAuditLogger._store_sepa_audit_event` and `_store_api_audit_event` each
called `frappe.db.commit()` unconditionally right after inserting the audit row.
A `commit()` acts on the **whole shared transaction**, so calling it mid-operation:

- prematurely persisted the caller's in-flight, not-yet-finished work, and
- cleared **all** of the caller's savepoints.

This is what broke the MT940 import: it wraps each batch in a savepoint, and the
audit log written during party creation committed the transaction out from under
it, so the later `release_savepoint` hit "SAVEPOINT does not exist". (The MT940
code was also made savepoint-tolerant as belt-and-suspenders.)

The same footgun applies to **any** flow that relies on savepoints/atomicity and
happens to emit an audit event (e.g. the `FOR UPDATE` termination path).

### The fix applied

Removed the two per-event commits. The audit row now rides the request-level
transaction, exactly like Frappe core's own durable logger `frappe.log_error`
(which inserts the Error Log **without** committing). The scheduled
retention-cleanup commits (`_cleanup_sepa_logs` / `_cleanup_api_logs`) were left
intact — those run as standalone jobs where committing is appropriate.

This matches the project's documented rule (CLAUDE.md, "Transaction Handling"):
> Don't add commits to hook-context code — let Frappe manage the request-level
> transaction.

## The residual tradeoff (the actual open decision)

Removing the commit changes one durability property:

- **Before:** an audit DB row survived even if the *caller* later rolled back.
- **After:** if the caller's transaction rolls back, the audit **DB row** is
  discarded along with it.

Mitigation already in place: `log_event` **also** writes every event to the
file-system sink (`_log_to_file`), which is unaffected by DB rollback. So the
audit *trail* is never lost — only its queryable DB representation for events
that occurred inside a rolled-back transaction (most often: blocked/failed
operations, which are exactly the security-interesting ones).

For typical security-audit use this is acceptable. **If compliance requires the
DB audit row to persist independently of the caller's transaction**, the commit
removal alone is not sufficient and the option below should be implemented.

## Option: autonomous-connection write (preserves DB durability, no side effects)

Write the audit row on a **separate, short-lived DB connection** that commits
independently — so the row persists regardless of the caller's transaction, and
the caller's transaction/savepoints are never touched.

- **Pros:** preserves the original "audit survives caller rollback" guarantee
  *and* fixes the savepoint-clobbering bug.
- **Cons:** non-trivial and risky in security-critical code — connection
  lifecycle/pooling, site-config-dependent connection params, and the failure
  mode (a botched autonomous write silently dropping audit events) is worse than
  the current state. Needs careful implementation + tests across web request,
  background job, and CLI/console contexts. Frappe has no first-class autonomous
  transaction, so this is hand-rolled.
- An alternative middle-ground is `Document.deferred_insert()` (Frappe's
  queue-and-flush-later mechanism for logs), but its flush timing relative to the
  caller's transaction needs verification before relying on it for compliance.

## Recommendation

Keep the commit removal (it fixes a real, broad bug and matches framework
convention). Only invest in the autonomous-connection write if there is a
concrete compliance requirement that the **DB** audit row survive caller
rollback — in which case treat it as its own scoped task with dedicated tests,
not a drive-by change.

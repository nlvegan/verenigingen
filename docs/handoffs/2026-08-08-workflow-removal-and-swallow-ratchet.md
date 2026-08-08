# Handoff — 2026-08-08

Supersedes nothing; extends `docs/handoffs/2026-08-07-overpayments-and-1630-upgrade.md`,
whose §10 closed the shard-weighting arc. Everything here happened after that.

Five PRs merged, five are open, one issue filed. **Nothing open is ready to merge as-is**
— a skeptical review round found defects in four of the five, two of which are already
corrected. Read §6 before touching any of them.

---

## 1. State

### Merged to `develop`

| PR | Merge commit | Subject |
|---|---|---|
| #241 | `1fda9939` | swallowed-exception ratchet (validator + baseline + pre-commit hook) |
| #242 | `c4b2dd15` | foreign-currency overpayment fixture |
| #243 | `7552121c` | handoff update for #237 |
| #244 | `999a9616` | ratchet promoted to a hard CI gate |
| #245 | `e930d33f` | condition (3) widened; `frappe.throw` taught to condition (2) |

### Open

| PR | Branch | State | Blocking work |
|---|---|---|---|
| #246 | `fix/money-critical-swallows` | corrections landed (`bcb8a9cf`) | re-verify CI |
| #247 | `fix/member-email-sync-workflow-transition` | CLEAN | **decide**: close in favour of #251, or land |
| #249 | `chore/remove-workflow-demo-page` | red (2 shards, see §5) | needs a COR data patch |
| #250 | `fix/board-member-application-approval` | corrections landed (`d568e8d7`) | re-verify CI |
| #251 | `chore/remove-membership-application-workflow` | red | **3 fixes required — see §6.4** |
| — | issue **#248** | open | test-suite order-dependence |
| — | `fix/error-swallow-log-names` @ `953e3416` | **local only, never pushed** | stacked on #246; rebase after it merges |

---

## 2. What we are doing, and why

Four arcs, each caused by the previous one.

### 2a. The swallowed-exception ratchet (#241 → #244 → #245 → log_names)

A broad `except` that logs and returns a falsy value destroys the cause: the caller
cannot tell "this failed" from "there is legitimately nothing here", and on CI the real
exception dies with the database. This repo has been bitten repeatedly — board members
got org-wide project access when a permission hook returned `""` (PR #191).

The validator is a **ratchet**: it fails only on sites not already in
`scripts/validation/error_swallow_baseline.txt`, so existing debt does not block commits.
It grew across four changes:

- **#241** built it. Review found `_is_falsy_return` tested `v.value in (None, False)`, so
  `return ""` — the exact value of the flagship incident — was invisible, and `return 0`
  passed only via `0 == False`. Also added the implicit-`None` arm, restricted to a
  trailing `try` (falling off a mid-function handler *resumes* it).
- **#244** made it a hard CI gate. It had been pre-commit only, so `git commit -n`
  bypassed it, and its `exclude` skipped `scripts/` so it never scanned itself.
- **#245** widened condition (3) from a whitelist ("only logs and returns") to a set of
  disqualifiers. One `cleanup()` call had been hiding 56 live sites.
- **log_names** (unpushed) teaches it this repo's own error helpers.

### 2b. Repaying the debt (#246)

432 baselined sites is too many to fix wholesale, and the population turned out to be
**far less dangerous than expected** — see §4.1. The selection criterion was *"the
swallowed value is also a plausible answer"*: `None`/`[]` look like nothing, but a
monetary `0.0` looks like a settled account.

### 2c. Test-suite order-dependence (#248)

#246 added a test module. CI went red on 3 shards, 8 tests, none touching the changed
code — see §4.2. That investigation is what exposed the workflow.

### 2d. The Frappe Workflow (#247, #249, #250, #251)

Chasing 2c led to a native Frappe `Workflow` on `Member` that nobody knew was live, that
gated membership approval on a **global role**, and that structurally could not express
the rule the app actually wants ("board member of *this* chapter"). Removing it exposed
that the app-side permission check had never worked either.

---

## 3. Production bugs found

### 3.1 Chapter board members could never approve applications — FIXED (#250)

`chapter_security.get_user_manageable_chapters` resolved the caller's **Member** name and
compared it against `Chapter Board Member.volunteer`, which holds a **Volunteer** name.
Different namespaces, proven on live data:

```
matching on Member name   (what the code did) -> 0 rows
matching on Volunteer name (what it meant)    -> 1 row
Assoc-Member-2026-01-32851  vs  Assoc-Vol-2026-02-36238
```

That function gates `validate_chapter_permission_or_throw`, so board members were refused
on **every** route — including the chapter dashboard, which checks the roster correctly
via `get_user_board_chapters` and then delegates to `approve_membership_application`,
which re-checked through the broken lookup. It only ever appeared to work for users who
also held an admin/staff role, which short-circuits to `"all"`.

Invisible because veg11 has exactly **one** active board member and that account holds
`Verenigingen Staff`. No test covered a non-admin board member.

### 3.2 The Member form's board check was an unimplemented stub — FIXED (#250)

```js
function is_chapter_board_member_with_permissions(frm) {
	// This would need a server call to check properly
	// For now, returning false - you'd implement the actual check
	return false;
}
```

So board members never saw Approve/Reject on the Member record at all. Replaced with a
server call to a new read-only `can_review_application(member_name)` rather than porting
the rule into JS.

### 3.3 `execute_workflow_action` is an unguarded status mutation — CRITICAL, see §6.4

`templates/pages/workflow_demo.py` exposed a whitelisted endpoint that does
`member.application_status = next_state; member.save()`, guarded **only** by
`frappe.has_permission("Member", "write")` — called with no doc, so the chapter permission
hook never runs. No `validate_chapter_permission_or_throw`, and no check that the
transition is legal.

Today the Workflow rejects the save. **#251 removes the only thing stopping it.** #249
deletes the page, which closes it — so #249 is a hard prerequisite for #251, not a nicety.

### 3.4 `ServiceFieldValidator.get_doctype_meta` poison-cached failures — FIXED (#246)

Wrote `self._doctype_cache[doctype] = None` in its handler, making one transient error
permanent for the process lifetime on a module-level singleton. Worse, its caller reads a
falsy result as `"DocType {x} does not exist"` — a DB error reported as a confidently
wrong diagnosis.

### 3.5 `get_valid_fields` has the identical bug — **NOT FIXED, issue #253**

Eleven lines below 3.4, same class:

```python
except Exception as e:
    self.logger.warning(...)
    self._field_cache[cache_key] = set()
    return set()
```

`validate_fields` calls **both**. Invisible to the ratchet because `set()` is a call node,
not a falsy literal — the same blind spot `""` had. Worth fixing with the same shape.

### 3.6 Zabbix metrics were all-or-nothing — FIXED (#246)

`_get_batch_metrics` wrapped seven metrics in one `try/except` returning `{}`. Only three
carry Zabbix triggers (`success_rate`, `stuck_count`, `count.daily`); neither `amount`
metric does. So a failure in an unalerted metric silently removed the alerted ones — and
with **no `nodata()` trigger defined anywhere in the file**, Zabbix's `last()` keeps
evaluating the frozen previous value. Now collects per-metric and reports
`sepa.batch.collection_errors`.

### 3.7 Mollie `process_failed_payment` rolls back its own audit record — **NOT FIXED (dead code)**

`_get_subscription_failure_count` is called *inside* a `try` whose handler does
`frappe.db.rollback()`, before `member.save()`/`commit()`. Any exception there discards the
payment-failure history row. The module-level function has **no production caller** (the
three same-named functions in `payment_processors.py` are unrelated class methods; the live
webhook routes through `unified_payment_api`), so this was documented rather than
restructured.

### 3.8 `create_customer_for_member` — dead `return None`, aborts Member insert — **NOT FIXED, issue #254**

`self.handle_error(e, op)` defaults to `raise_error=True` (§4.8), so the `return None`
below it is unreachable. But it is annotated `-> Optional[str]` and
`Member.after_insert` does `if customer_name:` — expecting `None`. It instead gets a
`ServiceError` propagating out of `after_insert`, aborting the Member insert. Deserves
its own issue.

### 3.9 `get_member_payment_matcher()` singleton is never invalidated — **NOT FIXED, issue #255**

A process-global whose `_customer_id_map` loads once behind a `_loaded` flag. Whichever
module in a shard warms it first freezes the snapshot; Members created later are invisible.
`reset_member_payment_matcher()` exists and **no test calls it**. This is one of the two
shard-5 CI failures. Add to #248.

### 3.10 Fourteen tests insert a forbidden `application_status` — mooted by #251

`application_status: "Approved"` at insert is a `Pending → Approved` transition the
Workflow rejects. #247 fixes one file; five others carry it. **#251 removes the workflow,
which fixes the class at the root** — verified: `test_member_user_email_sync_sweep` passes
on unmodified code once the workflow is gone.

---

## 4. Strange findings — the ones that cost time

### 4.1 The scary swallow subset was already gone

The ratchet's premise was that the dangerous case is "falsy means UNRESTRICTED". Measured
across all 432:

| value returned | count |
|---|---|
| `None` | 154 |
| `False` | 148 |
| `[]` | 67 |
| `{}` | 28 |
| `0` / `0.0` | 31 |
| `""` | **1** |

Exactly one `""`, and it is an audit-log helper, not a permission hook. PR #191 had
already removed the real one. The remaining debt is overwhelmingly *diagnosability*, not
security — which is why the recommendation was **not** to plan a 432-site remediation.

### 4.2 Adding ONE test file moves 702 of 1307 modules between shards

Frappe's parallel runner splits by LPT bin-packing (heaviest first into the currently
lightest chunk), weighted from `verenigingen/tests/test_timings.json`. **A module absent
from that table falls back to a `def test_` count.** Simulated locally: adding one file
reshuffles more than half the suite.

Consequence: **adding tests to an existing module changes nothing; adding a new module
reshuffles everything.** That is why #246's tests were distributed into five existing
modules rather than a new one.

Corollary: "keep `test_timings.json` updated" does **not** fix this. Any change re-runs the
packing; adding a weight entry just selects a different reshuffle. And the table is
generated from measured CI logs — hand-adding estimates puts fabricated numbers into a
measured dataset.

### 4.3 `frappe.db.delete` does NOT cascade child tables

`frappe.db.delete("Workflow Action", {...})` is a raw `DELETE`. Only `delete_doc`
cascades. Measured on veg11: deleting the Member Workflow Actions would orphan **7,352**
`Workflow Action Permitted Role` rows, in a table that currently has **zero** orphans.

### 4.4 `validate_workflow()` is not gated on `ignore_permissions`

`frappe/model/document.py:888` — it skips only when `frappe.flags.in_install == "frappe"`.
So a native Workflow validates **every** `doc.save()`, including `ignore_permissions=True`
and including the app's own `_system_update` flag.

### 4.5 The Workflow was live while the code said it was not

`hooks/lifecycle.py` had the setup call commented out with *"DISABLED: Workflow not in
use, has bugs in action master creation"*. The database disagreed: the row was present and
`is_active = 1` on veg11 **and** on test sites, with 748 Members carrying
`application_status` (697 Approved, 51 Pending) and 17 role-gated transitions. The app had
stopped *creating* it; Frappe never stopped *enforcing* it.

### 4.6 A Frappe Workflow's `allowed` is a global role

It cannot express "board member of *this* chapter". No role added to the transition table
encodes that — adding a board role grants it for **every** chapter. That is why the
workflow could not be corrected, only removed.

### 4.7 `Critical Operation Rule` is excluded from the `fixtures` hook

Editing `verenigingen/fixtures/critical_operation_rule.json` does **not** remove
already-imported rows — `bench migrate` never re-imports or prunes them. A data patch is
required (precedent: `patches/v2_2/remove_dead_portal_critical_operation_rules.py`).
Verified: the two `workflow_demo` rules are still `enabled=1` on veg11 despite #249's
fixture edit.

By contrast, `Custom HTML Block` **is** in the fixtures hook, so that edit self-heals.

### 4.8 `handle_service_error(raise_error=True)` is the DEFAULT

`BaseService.handle_error` delegates straight to it, so a bare `self.handle_error(e, op)`
**re-raises**. Any tooling that treats the name as pure logging will invent swallows where
the failure actually escapes. (Exception: `FinancialErrorHandler.handle_error` does *not*
always raise — unknown code, WARNING/INFO severity, or `user_facing=False` all return.
Used only in tests today.)

### 4.9 `Chapter Role` cannot express what the code checks for

The acceptance predicate reads
`can_approve_memberships or permissions_level in ["Admin", "Membership"]`. In reality:
`Chapter Role` has **no** `can_approve_memberships` field (and no Custom Field for it), and
`permissions_level` offers only `Basic / Financial / Admin`. So **`Admin` is the only level
that grants approval**, and both other arms are dead. Left unchanged in #250 — widening it
is an authorization decision, not a bug fix.

### 4.10 `get_member_name_for_user` has an email fallback — an identity widening

It matches `Member.user` first, then **`Member.email`**. Delegating to
`get_user_board_chapters` silently inherited that, admitting a User who merely *shares an
address* with a Member they are not linked to. On veg11, **126** Members have an email
equal to an existing User while their `user` field is empty or points elsewhere — and for
one of them, that Member's volunteer holds the only active board seat.

Resolved in #250 with a keyword-only `strict_user_link`: the dashboard keeps the fallback,
the approval gate does not.

### 4.11 The `workflow` name is memoized in Redis and `delete_doc` does not clear it

`get_workflow_name()` caches in `frappe.cache.hset("workflow", doctype, ...)`. The
`Workflow` controller has no `on_trash`, and `migrate` calls `frappe.clear_cache()` in
`setUp` — **before** patches — never after. So a patch deleting a Workflow can leave a
stale key, and the next `Member.save()` raises `DoesNotExistError`. Presents as "every
Member save is broken after deploy".

### 4.12 A pre-commit hook can abort a commit while `git push` says "Everything up-to-date"

Hit once this session: Black reformatted one line, the hook aborted the commit, the tail of
the output looked green, and the subsequent push reported success with nothing new on the
branch. **Always verify with `git log -1` and compare local vs `origin/<branch>` heads.**

### 4.13 Assorted

- `delete_doc(..., force=True)` still records to `tabDeleted Document` (recoverable);
  `frappe.db.delete` does not.
- `safe_log_error` has **five** definitions; `safe_error_logging.py` takes
  `(title, message)` while the other four take `(message, title)`. A live bug magnet.
- Only 3 of 7 `sepa.batch.*` metrics carry triggers, and no `nodata()` trigger exists, so a
  missing metric is silent rather than alerting.

---

## 5. CI status of the open PRs

- **#249** red on shards 5 and 9. Both traced and both are #248-family: shard 5 is a
  dues-rate contamination already named in #248; shard 9 is the matcher singleton (§3.9).
- **#251** red — same family, plus it deletes a test module (§4.2).
- **#246, #250** were green before the correction commits; **re-verify**.

Merging on red must be an evidenced decision naming the failures, not a generic
"#248" hand-wave.

---

## 6. Required work before merge

### 6.1 #246 — DONE (`bcb8a9cf`)
Both net-negative hunks reverted (Mollie, Zabbix); the live Zabbix caller fixed to degrade
per-metric. Three wrong-target/tautological tests fixed or removed. Baseline 425 → 427,
still below develop's 432 so the no-growth gate holds.

### 6.2 #250 — DONE (`d568e8d7`)
`strict_user_link` added; the two missing tests added (`Basic`-role denial, email-collision
denial). The identity test is verified to fail without the flag.

### 6.3 #249 — TODO
1. Add a COR removal patch for `execute_workflow_action` / `get_workflow_actions` (§4.7).
2. Delete `scripts/workspace_reorganization.py:44`, which recreates the dead link.
3. Replace the generic #248 disclaimer with the two named failures.

### 6.4 #251 — TODO, contains the critical item
1. **Make #249 a hard prerequisite** (or fold the page deletion in). Alone, #251 opens
   §3.3.
2. Delete `Workflow Action Permitted Role` children explicitly, and correct the patch
   comment that claims they cascade (§4.3).
3. Add `frappe.clear_cache(doctype="Member")` at the end of the patch (§4.11).
4. State in the PR body that the desk Member form becomes **editable** for Staff and board
   members once the workflow's `allow_edit` states are gone.

### 6.5 log_names — TODO
Document the `FinancialErrorHandler` exception in `KNOWN FALSE NEGATIVES` (§4.8). Then
rebase onto `develop` after #246 merges and push.

---

## 7. Decisions taken (owner: foppe)

- Remove the Workflow — after being shown it is live and gates approval on a global role.
- Fix the board-member lookup by **delegating**, not reimplementing.
- Route permission checks through the backend; do not reimplement rules in JS.
- #250 identity: **strict user-link only**, not the email fallback.
- #246: drop both bad hunks, fix the live caller properly.
- Debt: fix the money-critical tranche only; do not attempt a 432-site remediation.
- Silent swallows (~1,383, of which ~244 match the ratchet's shape): **measure first** —
  measurement done, no validator built.

---

## 8. Not done / open questions

- §3.5, §3.8, §3.9 have no fix. Each now has an issue so they survive this document:
  **#253** (`get_valid_fields`), **#254** (`create_customer_for_member`),
  **#255** (matcher singleton). #254 is a *decision*, not a mechanical fix — the issue
  states the two coherent options. #253 should land after #246, which edits the same file.
- #247: close in favour of #251, or land it? Its comment becomes false once #251 lands.
- Issue #248 items 1 and 2 are resolved by #251; item 3 (the "not in use" comment) is
  answered — it was in use. #255 is the shard-9 half of it, split out because it is a
  production defect and not only a test-isolation artifact.
- The reviewer-agent instructions (`.claude/agents/skeptical-code-reviewer.md`) gained an
  exception-handler section this session. **`.claude/` and `CLAUDE.md` are gitignored**, so
  that guidance is local to this machine and reaches no contributor. *Decision (foppe,
  2026-08-08): leave it local.* Recorded here so the next reader knows it was chosen, not
  overlooked — if a contributor's review misses the exception-handler cases this section
  covers, that is the reason.

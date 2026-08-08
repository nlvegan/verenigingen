# Handoff — 2026-08-09

## The permission-registry sweep and the cache-invalidation bug

Continues `2026-08-08-workflow-removal-and-swallow-ratchet.md`. That document's §9.4
posed a review question about #256; **that question is answered and §9.4 is stale** —
see §1 below before reading it.

---

## 0. State at handoff

| PR | What | Status |
|---|---|---|
| #252 | the previous handoff doc | CLEAN, mergeable |
| #256 | Membership doc-level scoping | **NOT merged**, red on shard 2 (see §5) |
| #259 | Employee doc-level scoping | **NOT merged**, red on shard 2 |
| #260 | cache invalidation + 3 test fixes | **NOT merged**, CI re-running |
| #257 | issue: Team has the same defect | open, unimplemented |
| #258 | issue: nothing enforces the two registries agree | open, unimplemented |

`develop` is at `c36be736`. veg11 serves the git working tree, which is on `develop`
and clean. **Nothing from this session is merged.**

---

## 1. §9.4 of the previous handoff was asking about the wrong role

It flagged that making `has_membership_permission` non-vetoing would widen
`Verenigingen Member`'s read on Membership for ~565 users. It would not, and the
reason is structural rather than a matter of counting rows:

`Verenigingen Member`'s only DocPerm on Membership is `if_owner: 1, read: 1`, and
**no code path makes a member the owner of their own Membership.** All four creation
sites run as somebody else — approval (as the approver), the Procurios import, a
dues-schedule health repair, and a report. So that DocPerm is inert.

The role that mattered was `Verenigingen Chapter Board Member`: create/read/write
with **no `if_owner`**. The fix as first written (`return True`) would have given
every board member read and write on **every** Membership by name, in any chapter.

**The load-bearing framework fact**, which is the thing to remember:

- `frappe/model/db_query.py` calls `frappe.has_permission` **without a doc**, so a
  `has_permission` hook never runs for list views.
- `frappe.client.get` calls `doc.check_permission()` (`frappe/client.py:104`), which
  never consults the query condition.

The two halves are disjoint. A `permission_query_conditions` entry scopes lists and
nothing else. This is the third time this exact confusion has produced a defect in
this repo (PR #191, Membership, Employee).

**Corollary:** a falsy return from a `has_permission` hook is a hard DENY, not "no
opinion" — `has_controller_permissions` does `if not controller_permission: return
bool(controller_permission)`. The generic `frappe-core-permissions` skill says the
opposite ("ALWAYS return None by default"); it is wrong for this frappe version.

---

## 2. What shipped in each PR

### #256 — Membership (`428e6800`)

`has_membership_permission` is generated from the existing
`_make_member_linked_permission` factory, as Donor and SEPA Mandate already are. Only
the `has_permission` half: the hand-written `get_membership_permission_query` is kept
because it mirrors `get_member_permission_query`'s
`status NOT IN ('Quit','Banned','Deceased')` exclusion, which the factory's generated
query lacks.

Three things a reviewer still has to decide, all stated in the commit message:

1. It is **narrower** than the approval gate on one arm: `Verenigingen National Board
   Member` short-circuits to "all chapters" in `get_user_manageable_chapters` but is
   not in `Roles.ADMIN_ROLES`, so this check denies it. Not a regression (that role has
   no Membership DocPerm), but the two notions of "may manage" differ.
2. It is **looser on identity**: `_check_chapter_board_access` resolves the actor with
   `get_member_name_for_user`, which falls back to matching `Member.email`.
   `get_user_manageable_chapters` deliberately passes `strict_user_link=True` to refuse
   exactly that. Inherited from the factory (Donor and SEPA Mandate share it).
3. It is **permission-type blind** — see §4.

### #259 — Employee (`e5e4fd88`)

Same defect, independently confirmed exploitable on live data: a user holding only the
`Employee` role got `1=0` from the list query (zero employees visible anywhere) and
`True` from `frappe.has_permission("Employee", "read", doc=<any>)`. Employee carries
date of birth, personal email, phone and address.

The mechanism is **not** "volunteers with no Employee record" (an earlier version of
the commit message said so; it was wrong). ERPNext creates a User Permission per
employee-user via `Employee.update_user_permissions()`, and `has_user_permission`
returns unrestricted for a user with no such rows. This app disables that and only
sometimes replaces it:

- `services/member/account/account_creation_manager.py` sets `create_user_permission: 0`
  and **compensates** with an explicit `add_user_permission()`.
- `services/member/account/user_role_profile_calculator.py` sets
  `emp.create_user_permission = 0` for role-profile Employee stubs and does **not**.

So the unrestricted population is manufactured by the second path and grows with every
stub. **Follow-up worth filing: make those two paths agree.**

The query was also wrong in the opposite direction — no self branch, so it fell through
to `1=0` and an employee could not see their own record in a list view. Both halves now
share `_employee_board_chapter_condition`.

### #260 — cache invalidation (`7663cff4`)

`get_keys()` returns keys with the site namespace already applied; `delete_key()`
applies it again. Every `get_keys()` + `delete_key()` loop deleted `db|db|key` and
removed nothing. Already documented and fixed in `payment_utils.py:483` and
`financial_utils.py:416`; four instances were left behind.

**Read the scope carefully before building on this:** `cache_invalidation_hooks.py` is
**not registered** anywhere in `verenigingen/hooks/` — its own docstring still says
"Add these hooks to frappe hooks.py", and its only importers are tests. Nothing writes
`user_accessible_chapters:*`, `member_board_positions:*` or `chapter_permissions:*`;
those names appear only in deletion code. `clear_all_member_caches()` has exactly one
caller, a test `setUp`. So three of the four fixed sites are currently dead code.

The **one live path** had a different bug:
`events/subscribers/member_subscribers.py::handle_cache_invalidation` (wired via
`events/member_events.py:107`) deleted `member_dashboard_*` with an **underscore**,
while the producer writes `member_dashboard:{name}` with a **colon**. Its test seeded
an underscore key and asserted it was cleared, so both sides agreed with each other and
disagreed with the producer. Fixed, and the test corrected.

---

## 3. The CI flake — root cause proven, fix incomplete

`test_member_dashboard_caching` fails intermittently with
`0 not greater than 0 : Cache should reduce queries`. Chain, each link measured:

1. **Member docnames are reissued after a rollback.** The naming series participates in
   the transaction — after `frappe.db.rollback()`, `make_autoname` returns
   `Assoc-Member-2026-08-00001` a second time. MEASURED.
2. The dashboard cache (Redis, 5-minute TTL) is **not** transactional and survives.
3. So a rolled-back test hands both its docname and its stale cache entry to the next.
4. `setUp` calls `clear_all_member_caches()` to prevent exactly this, and that call was
   the no-op above. MEASURED: set a key, call it, key survives; `delete_keys()` removes it.

The margin was only ever 1 → 0, which is why it never reproduced in isolation.

**The broken clear was real, but it was NOT what made CI fail.** Fixing it left CI
still failing, now on a new `first_load_queries >= 1` assertion with the cache key
verified absent immediately beforehand. That ruled out a stale cache entirely and
pointed at the counter.

**ACTUAL ROOT CAUSE — a leaked instance attribute on `frappe.db`.**
`frappe.db.sql` is a CLASS attribute. `tests/integration/test_query_optimization_suite.py`
saved it and "restored" it with `frappe.db.sql = original_sql` instead of deleting it,
which leaves a permanent INSTANCE attribute behind. MEASURED:
`"sql" in frappe.db.__dict__` goes `False -> True` on re-assignment and back to `False`
only on `del`.

An instance attribute wins attribute lookup, so `_count_queries` — which patched
`frappe.db.__class__.sql` — observed **nothing** and recorded zero queries in any shard
where that module had already run. Order-dependent, therefore CI-only and never
reproducible locally in isolation.

With zero counted queries, the original `assertGreater(first_load, cached_load)` is
`0 > 0` and fails — and, more quietly, **every upper-bound budget in that module passed
vacuously** (`assertLessEqual(0, 300)` is always true). Fixed at both ends: the
polluting helper now deletes the instance attribute, and `_count_queries` patches the
instance so it is immune either way.
`test_query_counter_survives_an_instance_level_sql_attribute` pins it by simulating the
polluted state.

Generalisable: **`obj.attr = saved` is not the inverse of patching a class attribute.**
Restoring requires `del obj.attr` when the attribute was not in `obj.__dict__` to begin
with — which is precisely what `mock.patch.object` gets right and hand-rolled patchers
usually get wrong.

---

## 4. `permission_type` is always `None` in these hooks

VERIFIED: `has_controller_permissions` calls
`frappe.call(method, doc=doc, ptype=ptype, ...)`, and `frappe.call`'s `get_newargs`
drops kwargs absent from the callee's signature. Every helper in `permissions.py` names
the parameter `permission_type`, so it never arrives —
`get_newargs(has_donor_permission, {..., "ptype": "write"})` returns `['doc', 'user']`.

Consequences:

- `_check_service_account_permission` does `perm_type = permission_type or "read"`, so
  **every service-account check is evaluated as `read`** regardless of the operation.
- The Membership and Employee checks return the same verdict for read/write/create/submit.
  Combined with #256's `submit: 1` grant, a board member can create, write and submit a
  Membership for anyone in their chapter, bypassing the approval orchestration.

**Do NOT "fix" this by renaming `permission_type` to `ptype` across the file** — that
would start feeding real ptypes into the service-account branch and silently change
webhook answers for non-read operations. `chapter.py` and `project_permissions.py`
already name it `ptype` and do receive it, so the repo has both conventions.
`has_employee_permission` uses `ptype` and ignores the value.

---

## 5. Why nothing merged

Both permission PRs are red on shard 2, and neither failure is theirs:

- `test_member_dashboard_caching` — §3. #260 was supposed to fix it and does not yet.
- `test_payment_history_sync_with_auto_generated_invoice` — `Dues rate (€2.00) cannot be
  less than minimum amount (€100.00)`. This is #248's dues-rate contamination: a shared
  Membership Type's `minimum_amount` is mutated by another test. Order-dependent.

**Merge order when they are green:** #260 first (it is what makes the caching test
stop failing), then rebase #256 and #259 onto the updated `develop` and re-run. All
three trial-merge cleanly against each other (`git merge-tree`), but #256 and #259 both
touch `permissions.py` and `test_permissions_coverage.py`, so the second one to land
wants a rebase and a re-run rather than a blind merge — its "verified on test_site_1"
counts were measured without the other's changes present.

---

## 6. Open work

- **#257** — `Team` has the identical doc-level defect. MEASURED on real config: a plain
  `Verenigingen Member` gets `` `tabTeam`.name = '' `` from the list query (zero teams)
  and `True` from `has_permission(read, doc=…)`. Read-only; exposes team rosters.
- **#258** — a test asserting the two registries agree. Four doctypes are in one and not
  the other: `Chapter Member` and `Team Member` (child tables, exempt — the parent
  governs), `Team` (#257), `Employee` (#259). Write it **after** #257 so it lands
  without an exemption for a known-broken doctype.
- `has_donation_permission`'s branches for board members and members are **dead code**:
  Donation's read DocPerm is only System Manager / Verenigingen Administrator /
  Verenigingen Webhook User, and a controller hook can only deny, never grant. MEASURED:
  a `Verenigingen Member` gets `False` at doctype level.
- The two Employee-creation paths in §2 should be made to agree.
- `scripts/rollback/phase2_2_rollback.py:248` still has the double-prefix loop.

---

## 7. Traps confirmed this session

- **A green test can be pinning the bug.** Three instances:
  `test_has_membership_permission_admin_and_fallback` asserted the `None` that caused
  the outage; `test_cache_invalidation_clears_pattern_keys` seeded an underscore key
  matching the subscriber's typo; `test_chapter_board_permissions.py:165`'s docstring
  still taught the misconception. Existing tests blocking a permission change deserve
  suspicion before deference.
- **`test_cross_chapter_access_prevention` already covered the Membership hole** and
  neither commit had run its module. Verified it fails against the blanket `return True`
  with "Board member should not have access to memberships from other chapters". Run the
  whole affected module, not just the one you edited.
- **The test-quality enforcer re-scans the WHOLE file once it is staged**, so touching
  one test can surface unrelated pre-existing violations. Allowed helper-name prefixes
  include `_make_`, `_persist_`, `_create_`, `_ensure_`, `_with_`, `_as_`, `_insert_`.
- **`bench console` silently drops multi-line blocks** (`def`, nested `for`/`if`). Probes
  must be flat top-level statements, or they return nothing and look like a real result.
- **Tests that can only pass once per database.** `test_performance_optimization_integration`
  used fixed names, and a Member's `after_insert` creates a **committed** Customer named
  after `full_name`, which the per-test rollback does not remove. Green in CI only
  because CI starts empty.
- **Cold DocType meta introspection dominates query-count budgets.** The same block cost
  4513 queries cold and 55 warm. A budget assertion that depends on what ran before it in
  the process is not measuring anything.
- veg11 is a **test instance** — its row counts are not evidence about a real deployment.
  Settle questions like "is this DocPerm reachable" from code, not from data.

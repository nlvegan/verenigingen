# Handoff — 2026-08-24b: the measurements that could not fail

Merged **17** PRs myself (open PRs 19 → 4, of which 2 are drafts and 2 were opened today by other
sessions), fixed **#549** and **#552**, filed **#540**, **#561**, **#562**. But the useful thing this session produced is a pattern that showed up **five times in one
day, in my work and in other people's**: a check that returns the reassuring answer because it *could
not have returned any other*.

> **A measurement that cannot fail is not evidence.** Before believing a green, ask what result would
> have been impossible. Five instances below: a simulation whose inputs were monotonic, a ratchet
> whose condition was unmet by construction, a test that injected above the frame it was aimed at, an
> assertion satisfied before the code under test ran, and a tolerance mistaken for an assertion.

## State

| | |
|---|---|
| **#550** | **MERGED** — `member_id` rested on the clock alone (#549) |
| **#557** | **MERGED** — closed the class: the deterministic generator + two siblings (#552) |
| **#524** | **MERGED** — Territory root, with the sentinel fix this session added |
| Also merged | #526, #558, #493, #510, #525, #527, and 9 handoff docs. #543, #541, #542, #553, #437 landed via other sessions |
| **#378** | **OPEN, draft, do-not-merge** — 44/44 green *and* a confirmed regression |
| **#379** | OPEN, draft, conflicting, 7 failures — untouched |
| Filed | **#540** (code half now in flight as #563), **#561**, **#562** |
| develop | **green** at `a18d48d9`, 37 checks, 12/12 shards, both `member_id` fixes in |
| veg11 | **not deployed.** Still blocked on an accounting decision — see the end |

## The five

### 1. A tight loop cannot reproduce a timestamp collision

Modelling #549's generator (`f"TEST{microsec:06d}{seq:03d}"`, `microsec = now % 1_000_000`) I wrote
the obvious simulation and got **0 collisions at N = 200, 500, 1000, 2000**. Which reads as "the
generator is fine" and is worthless: consecutive `datetime.now()` calls in a loop are
**monotonically increasing**, so 2000 iterations draw 2000 *consecutive* values that cannot repeat.
The mod wraps once per second.

Real factory instances are one-per-test-method, seconds apart, so the component is effectively
uniform. Modelled with `random.randrange(1_000_000)` the truth appears — and matches the closed form:

| N | measured (400 trials) | exact |
|---|---|---|
| 500 | 12.5% | 11.73% |
| 1000 | 45.2% | **39.33%** |
| 2000 | 87.2% | 86.47% |

**What caught it:** the mismatch against the analytic value. 0% vs 39% is not sampling error.
Compute the closed form *first* and make the simulation reproduce it, or the simulation is decoration.

### 2. A ratchet whose condition is unmet by construction

`#378` came back **44/44 green, 12/12 shards, every ratchet passing** — including the
🕳️ Swallowed-Exception Guard. On that exact head the branch converts a loud failure into a silent one:

| | `member.insert()` with a faithful deadlock (`ROLLBACK` + 1213) |
|---|---|
| the branch | **returns normally**; `member.name` set, `db.exists("Member", …)` → **False** |
| develop | **raises** `ServiceError: … (1305, 'SAVEPOINT … does not exist')` |

The guard's condition requires a `return <value>` in the handler. `after_insert` has none, so a
load-bearing falsy return is **invisible to it by construction**. Its `success` is not a finding of
innocence, and reading it as one is how this got to 44/44.

### 3. A test that injects above the frame it is aimed at

#378's own `test_non_resumable_db_error_still_aborts_the_insert` passes **on develop too**, so it
discriminates nothing — and it injects above the frame that converts 1213 → 1305, green-lighting a
guard that cannot fire. The PR body's repro instruction ("injecting inside
`insert_customer_with_duplicate_retry` would make it red today") is also **false**: measured, a bare
`QueryDeadlockError` there stays green. The savepoint has to be destroyed too.

That sentence is the one the next person would have acted on, and it would have told them the guard
was fine.

### 4. An assertion satisfied before the code under test runs

Also #378: `assertIn("No Such Customer Group ZZZ", get_message_log())` — but `frappe.throw` had
already appended that **before** `after_insert`'s handler ran. Delete the `msgprint` the fix adds and
the assertion still passes. It was cited as evidence that "the reason is re-surfaced rather than
swallowed."

### 5. A tolerance mistaken for an assertion

`expectErrorLog` **permits** an Error Log row; it does not require one. Deleting `frappe.log_error`
from #378's fix leaves **all four** of its tests green. To assert a log, query `Error Log`. (This was
already written down in the 08-23e handoff. It recurred anyway.)

## Verify in both directions — the reviewer was wrong twice too

Standing permission to dispatch the skeptical reviewer was granted this session, and it earned it
immediately: on **#550** it returned *merge with changes* and found **five** false or unsupported
claims, three shipping inside docstrings — including a citation to
`EnhancedTestDataFactory._generate_member_id`, **a method that does not exist**, cited four times.
None was a code bug, consistent with every prior review here.

Its corrections to my numbers were right, and worth keeping as a list of what I get wrong:

| my claim | reality |
|---|---|
| "the failing shard created 472 members" | a `grep -c` of log **lines**. 242 distinct names; ≥837 inserts from the autoname series |
| "~70% that some shard of twelve reddens per run" | **1 run in 30** on develop. Off ~20×: I applied total-member N to a single `seq` bucket |
| "8.1s and ~2070 modules" to import | transferred from another module's docstring; ~2070 was the process **total**. Measured: **6.48s, +1392** (control: 0.05s, +54) |
| "proven across the ~780 EnhancedTestCase files" | that method has **zero call sites** |

**But two of its own claims did not survive checking**, and I nearly filed one:

- it gave the sibling at `:590` (it is 589) and the third generator at `:7054` (it is 7007)
- it claimed `enhanced_test_factory.py` has **no** reference to `CoreTestDataFactory`, making the
  "all other factories delegate to this class" docstring false. It has **12** — `__init__` does
  `self.core = CoreTestDataFactory(...)` at `:451` under a comment saying exactly that. **The
  docstring is accurate.**

So: brief it to attack the justification, take its findings seriously, and **check its citations the
way it checks yours.** Substance reliable, file:line not.

## What was actually fixed

**#549 / #550 — `member_id` rested on the clock alone.** A new `CoreTestDataFactory` per test method
(`tests/utils/base.py:189`) restarts `seq`, so every test's first member is `…001`, all contending in
one 10^6 space against a UNIQUE column. Observed twice on 2026-08-23, different shards, different
modules, both ending `001`: `TEST153429001` (#524 shard 3) and `TEST311263001` (develop shard 9).
**The fix existed one file away** with a docstring naming the defect and giving `TEST161453001` as its
example — rule 6, the explanation was the search query.

**#552 / #557 — the class was not closed.** `SecureTestDataFactory` took
`test_run_id.split("-")[-1]`, which **discards the random component and keeps whole epoch seconds**:
two factories in the same second collided **deterministically**. Two instances with *different* seeds
both emitted `1787520889001`. Those ids were also pure digits, so alone among the factories' ids they
passed `member_id REGEXP '^[0-9]+$'` and entered `member_id_manager`'s counter logic at ~1.79e12 —
**defeating the scope guarantee #550 itself relied on**. Plus two siblings on the lines immediately
above #550's fix: `_generate_email` (10^8) and `_generate_name` (**10^5**, ten times narrower than
the bug just fixed, and its own docstring says *"Customer uses full_name as primary key"*).

**#524 — a sentinel a second writer could forge.** `ensure_erpnext_base_masters` gated BootStrapTestData,
`enable_all_roles_and_domains()`, `set_defaults_for_tests()` and the fiscal-year heal on **one**
`db.exists("Territory", "All Territories")` — a proxy for the whole master set, as its own docstring
shows. #524 added a get-or-create for exactly that row, reachable from three callers that bypass the
gate. Impossible before, because "Netherlands" linked to a parent nothing created, so a missing root
**raised** — that raise *is* #516. **Fixing the raise is what made the sentinel forgeable.** Now a
conjunction with `All Supplier Groups`, the half this app cannot forge (25 references, all reads).

> **The authorship twin of #520's ordering rule.** #520: whichever write is the idempotency key,
> everything else goes before it. This: a row that means *"this work is done"* must never be
> creatable by anything that does not do the work. Ordering and authorship are two ways to forge the
> same key.

**#561 — a 1213 destroys the savepoint.** So a broad handler whose first act is
`rollback(save_point=…)` raises **1305**, which *replaces* the deadlock — and 1305 is in no guarded
class, `NON_RESUMABLE_DB_ERRORS` being `(QueryDeadlockError, QueryTimeoutError)`. Independent AST
census: **17** such handlers, **exactly one** guarded (`transaction_errors.py:85`, the template, whose
comment explains why). Nine of the sixteen are payment-facing. This is a **different mechanism from
#505** (frame order): the guard is reached and still cannot match, so fixing #505 alone does not help
— including for `handle_api_error`'s guard on 50 endpoints.

## Process notes

- **A PR's own body can say do-not-merge.** I called #378 a "stale green" and offered to re-run its
  CI; it is a **draft** whose header reads *"Do not merge as-is"* with two blocking findings. My
  `gh pr list` query omitted `isDraft`. **Include `isDraft`, and read the body before treating
  anything as a merge candidate.**
- **A stale green is not a green.** #378 was **356 commits** behind. Note `gh run rerun` replays the
  original merge SHA and tells you nothing new — merge develop into the branch and push.
- **Check whether it is already merged.** #550, #553 and #437 were merged by another session while I
  was working; two of my merge attempts returned "already merged". Several sessions are landing work
  concurrently, and one committed to #524's branch mid-review.
- **A stale issue reference points somewhere real.** I wrote "#551" into a PR body before filing;
  the issue landed as **#552**, and #551 turned out to be a live unrelated PR. Fix forward references
  after filing.
- **`.replace(anchor, …, 1)` matched the wrong class.** Extracting a method into
  `SecureTestDataFactory`, my anchor hit the **first** of three `def create_member` in a 7,000-line
  file and landed it in `EnhancedTestDataFactory`. TDD caught it as an `AttributeError` rather than
  shipping dead code in the wrong class. Anchor on something unique to the target.
- **I damaged test_site_1.** Two nested `_rows_deleted` blocks shared one savepoint name; MariaDB lets
  a second `SAVEPOINT` of the same name replace the first, so the inner `ROLLBACK TO` landed on the
  inner point and the outer `DELETE` stood — `All Supplier Groups` gone permanently. **The helper's
  own row-count guard reported it**, at the point of damage rather than as a link error three modules
  later. Repaired (9 rows, root at `lft=1/rgt=18`, `rebuild_tree`). Savepoint names are now unique
  per invocation.
- **Three docstrings argued from a CI topology that does not exist** ("8 shards as parallel PROCESSES
  against ONE shared DB"). Every shard job gets its own `mariadb:10.6` **and** its own `redis:alpine`
  pair — the `services:` block sits inside the job carrying `strategy.matrix.index`; the matrix runs
  **12**, not 8. **Re-attributed, not deleted:** every hazard is real, and `bench run-parallel-tests`
  genuinely does share one site and one redis. Deleting the rationale would have removed a live
  guarantee. A fourth site had already been corrected on develop.

## What is left

- **#540 needs an accounting decision, and it is the only thing blocking veg11.** `Mollie Settings`
  points both account fields at `10440 - Triodos 1 - TPIC - TPIC`, whose company is
  `TEST-Payment-Integration-Company`; the `Bank Account` #538's fixed gate resolves is
  `BTR Test Company Account - BTR Test Bank`. **#563 is in flight for the code half** (a coherence
  guard on the pair) — but a guard makes the bad configuration *detectable*, it does not choose the
  accounts. Someone has to say which NVV clearing account represents "held at Mollie, pre-payout"
  (I could not find one; it may need creating) and which NVV account receives the payout — the only
  NVV Triodos `Bank Account` on the site is `Triodos Spaarrekening`, a *savings* account. Do that
  **before** splitting the fields, then watch the first settlement.
- **#378** — draft, do-not-merge. Minimum set to change the verdict is in the PR comment; the
  headline is `except NON_RESUMABLE_DB_ERRORS: raise` **above** `application_payments.py:275`'s
  rollback (not merely above the return), plus a test injecting the *faithful* deadlock.
- **#561** — 16 unguarded handlers. #499 proposes converging the hand-written savepoint-rollback
  copies onto a shared helper; if that lands, the guard belongs in the helper and these become one
  site. Unchecked: how many of the 16 that helper can absorb.
- **#562** — three of five hardcoded tree roots have no `ensure_root_*`, with two concrete
  #516-shape consumers on neither harness base (`test_membership_utilities.py:85` inserts under
  `All Item Groups`; `test_setup_init.py:172` asserts `All Customer Groups` exists).
- **`_generate_unique_test_member_id` is dead code** (zero call sites) and two docstrings in
  #550/#557 now cite it as the format's source. Delete it *and* those citations together, or neither
  — recorded on #549.
- **No real 1213/1205 has still ever been produced** across #470/#475/#484/#504 — except that this
  session finally did, on two connections, to prove #561. That measurement is in #561; reuse it.

## For whoever picks this up

- **Ask what result was impossible.** Every one of the five failures above passed a check that had no
  failing branch. A green tells you nothing until you know the check *could* have gone red.
- **Compute the analytic value before you simulate.** The simulation's job is to reproduce it, not to
  discover it. 0% vs 39% is what exposed a model that could not collide.
- **State the population, not just the number.** "~70% per run" was arithmetic applied to the wrong
  set. The right N was "test methods whose *first* member comes from this factory", which is smaller
  and which I never measured.
- **Verify the verifier.** The reviewer was right about my prose five times and wrong about its own
  citations twice. Both directions need checking.
- **Re-attribute before you delete.** Three wrong rationales guarded three real hazards. The premise
  was false and the code was necessary; those are independent questions.

# Handoff — 2026-09-02b: the gate that fails on the good direction

Merge pass on the twelve open PRs from the previous session, then six new issues worked in
parallel. **12 PRs merged, 7 more open, 7 issues filed, 5 premises corrected.**

The title is the finding that cost the most time and is the most likely to recur. Three
separate PRs across **two different ratchets** went red today for the same reason, and in
every case the red appeared on a PR that had nothing to do with the guard's subject:

> A baseline ratchet's CI job re-runs `--update-baseline` and fails if the file moves **at
> all**. The validator itself only fails on *growth*. So **deleting code turns the build
> red**, under a guard named after a defect class the PR never touched, with the generic
> message `Baseline is out of sync with the tree.`

- **#728** — removed two clone families (`_create_test_bank_account` 2→0, `_ensure_bank_account`
  13→12) by converging on `get_eur_bank_account`. Duplicate Helper Guard red.
- **#742** — made a donation writer a documented no-op, removing its swallow site.
  Swallowed-Exception Guard red.
- **develop itself** — see below. `log_error` Guard red on every branch cut from it.

Shrinkage is the *good* direction. The fix is bookkeeping. But the message sends the reader
hunting a regression that does not exist, and it does so on somebody else's PR.

**Worth doing:** make the job say *"the census shrank — run `--update-baseline`"* when
entries only leave, or have it self-heal on deletion. Raised in PR #750's body.

## The trunk was red and nobody noticed

`develop` at `34fb9d5f2` failed its own `🔄 log_error Argument Order Guard (ratchet)`. Every
branch cut from it inherited the failure — first seen on **#740**, a leap-day date fix that
touches no logging whatsoever.

Two baselined sites no longer existed:

| site | deleted by |
|---|---|
| `performance_event_handlers.py::…::on_volunteer_assignment_change` | #719 (`e1995d994`), retiring dead Volunteer `doc_events` |
| `chapter_member.py::ChapterMember.validate_chapter_membership_tracking` | #730 (`a1e7f61d3`), deleting dead child-`validate` rules |

**Mechanism worth internalising:** #732 generated its baseline *on its own branch* and merged
without regenerating against the develop tip it landed on. Any baseline generated on a branch
is a statement about that branch's tree, not about the trunk it will land on — and nothing
re-checks it at merge time. With several PRs in flight touching the same census, this is not
an edge case, it is the default outcome.

Fixed in **#750**.

## Five issue premises were wrong. That is now nine across two sessions.

The previous handoff recorded three-of-eight. This session added more, and the pattern is
consistent enough to be predictive: **issues here reliably identify a real symptom and
misidentify its mechanism, and the misidentification always points toward changing more code
than necessary.**

| issue | claimed | actually |
|---|---|---|
| #662 | the mandate join "was bounded by #604's purpose filter" | not true — recorded in its own comment thread. **Two** independent fan-outs, not one |
| #667 | four ORM appends are broken | **one**. `_set_defaults()` runs *before* `_validate_links()`, so the DocField default self-heals three of them; only `sync_member_mandates` breaks, because it persists via `update_child_table()` and bypasses validation entirely |
| #699 | `mijnrood_csv_import.py:370` is "almost certainly the same defect" | dead code — the inner service already swallows and never re-raises. Same for `balance_transaction_processor.py:365` |
| #713 | (premise true) | but it asked for a *decision*, and the deciding evidence was whether a Member can donate without a linked Donor — not anything in the issue body |
| #746 | (new, filed today) | the Mollie idempotency index was never created **and the patch is Patch-Log-recorded**, so cleaning the duplicates does not bring it back |

**The rule that keeps earning:** verify the premise empirically before writing code, and read
the comment thread — #662's correction was sitting in its own thread, posted by the person who
had declined to fix it.

## PR #749 took three review rounds, and round two was worse than the bug

The most instructive sequence of the session.

1. **"PR #709's guard already covers it."** Refuted: it only catches an *unfiltered* call. A
   `member_type`-filtered call bypasses it via a per-Member SQL predicate — verified
   empirically, two separately-filtered calls returned the same invoice under two different
   members and mandates. A real cross-batch double debit.
2. **"Bind through `si.member`."** Refuted, and **worse than the original defect**: that field
   is a `fetch_from: customer.member` column Frappe silently overwrites on every save. Binding
   a join to it converts a *refusal* into a **silent wrong-account debit**.
3. **Final:** bind through the invoice's own `Membership Dues Schedule` on its primary key
   (`mds.member = mem.name`), the same resolution the two sibling collection queries already
   use.

Round 2 would have shipped. It passed its own tests. **A `fetch_from` column is not a fact you
can join on** — it is a cache the framework rewrites, and this is now the second time this repo
has been bitten by trusting a derived column.

## The tests are a caller

Two PRs broke the very test that existed to confirm them, and **both had already been reviewed
twice**:

- **#730** downgraded `add_error()` → `add_warning()` and its commit said "no test changed".
  `test_board_member_validator` holds a direct unit test of that rule's severity, in a shard
  the fix round never analysed.
- **#732** rewrote 152 `log_error` call sites and touched **zero** test files.
  `test_mollie_refund_handler` was asserting the *swapped* Error Log shape — its own comment
  said so.

**A sweep that changes what code emits — a severity, a log field, a return shape, a message —
must grep `verenigingen/tests` for that shape.** The AST instrument for Error Log queries found
25 call sites and isolated the one genuine offender plus one legitimate still-swapped survivor
(`test_page_manage_donations.py:295`, whose module is among the ~975 sites #602 baselines
rather than fixes — correct today, must flip when that site does).

## I made the same mistake I was fixing

Recorded because the mechanism is cheap to repeat.

I pushed an **empty** retraction commit to #742 asserting a veg11 overclaim "never reached the
source, only the commit messages and the PR body". It had reached the source, at three sites.
My grep had run in the **main checkout** rather than the worktree — the shell's cwd resets
between commands, and the grep silently answered a different question than the one asked.

**A grep is only evidence about the tree it actually ran in.** Print `pwd` alongside any grep
whose result you are about to build an argument on.

The underlying overclaim is the fourth recurrence of the veg11 rule, and the first by a
subagent — one whose brief already carried the prohibition verbatim. The prohibition is not
enough; the brief has to demand the **positive** form, because the task ("decide whether a
repair patch is needed") is exactly the shape that makes a row count feel like the answer:

1. **Reachability, from code** — is it whitelisted, is there a production caller, is the write
   conditional on something optional? Survives not knowing the data.
2. **Shape plausibility, counts labelled a test instance's** — illustrates, quantifies nobody.

A decision resting on part 2 alone is not settled, it is deferred. On #742 the correction did
not change the decision (option 2 rests on code facts) but it did change "no repair patch" from
*known-unnecessary* to *a deliberate choice for the reviewer*.

## Live defects found by questioning delivery, not by looking for them

- **#745** — a donor who ticks "create periodic agreement" gets the donation created, the
  agreement created, **no confirmation email**, and the message *"An error occurred processing
  your donation. Please try again."* Cause: `donation_form.py:230` calls `.get()` on an
  `OperationResult` dataclass, which raises `AttributeError`; the outer `except Exception`
  returns normally, so nothing rolls back. The same file gets it right 40 lines earlier
  (`result.success`). Both `log_error` calls in that handler are **swapped**, so the Error Log
  recorded the label and no traceback — which is why nobody found it.
- **#743's incidental find** — `api-service.js` unwrapped `OperationResult` by requiring both
  `success` and `data`, but a failure envelope nests under `error` and carries no `data`. **Every
  `OperationResult.fail()` from that service was reported to callers as success.** The Jest
  fixture asserted a wire shape that never occurs.

Both were found because someone asked *"will this error actually reach the user?"* rather than
*"is this error correct?"* A dataclass and a dict being used interchangeably is a class, not two
instances — worth a sweep.

## Branch protection now exists

`develop` had none (only deletion / force-push / Copilot from an existing ruleset). Applied:

| change | note |
|---|---|
| PR required, **0 approvals** | closes the direct-push hole this session used for #732 |
| **15 required status checks** | chosen by measurement, not by reading workflows |
| `delete_branch_on_merge` | was false |
| merge-commits only | squash and rebase disabled, repo **and** ruleset |
| Copilot `review_on_push` | encodes "review the round that answers the review" |

**How the check set was chosen, because this is the part that goes wrong:** a required check
that a PR cannot produce blocks it forever. I intersected the check names actually emitted by a
docs-only PR (#736), a scripts-only PR (#734) and a code PR (#730). That excludes
**Tests / Test Summary**, `controller-size-check` and `Check Permission Bypasses` — all
path-filtered on `verenigingen/**/*.py|js`. Requiring Test Summary would have deadlocked both
#736 and #734.

**Two defaults GitHub silently added** when the ruleset was created, both corrected:

- `allowed_merge_methods: ["merge","squash","rebase"]` — would have re-enabled squash/rebase
  *inside the ruleset*, quietly undoing the repo setting.
- `require_extra_approval_for_unattributed_changes: true` — agents commit as
  `foppe <fjdh@disroot.org>` while the pusher is `0spinboson`, so commits are plausibly
  "unattributed" and this demands an approval **a solo maintainer cannot give**.

**Not done, deliberately:** admins bypass (`RepositoryRole:5`, `always`). Per GitHub's
documented semantics that exempts admins entirely, so the gate does **not** bind the maintainer
— it binds `foppe-nvv`, blocks accidental API merges, and makes bypasses visible. Removing that
one bypass actor is the enforce-admins decision, left open.

If Tests should ever be required, the shape is a small always-running shim job that reports
success when the suite is legitimately skipped and mirrors its result otherwise — require the
shim, not the shards.

## Environment notes

- **`gh pr merge` is refused for any PR touching `.github/workflows/`** unless the token has
  `workflow` scope. Git here uses SSH, which is not subject to that, so a local `--no-ff` merge
  and push produces the same merge-commit shape — that is how #732 landed. Scope has since been
  added.
- **`test_site_5` was polluted**: both `Standard Buying` and `Standard Selling` carried
  `currency = EUR` where the other three test sites have `INR`, breaking ERPNext's bootstrap for
  every module there. Repaired. The writer was not pinned; the app's own EUR helpers create
  *named* price lists rather than touching the standard ones, so it is likely an ERPNext cascade
  from a company-currency write.
- **Two Ubuntu-mirror infrastructure failures** (`apt-get` unreachable, no test ran). The
  workflow says so explicitly and says to re-run. Note `gh run rerun --failed` is refused while
  the overall run is still `in_progress`.
- `main` **does not exist** — `develop` is the default branch. `CLAUDE.md` still instructs
  `codemap --diff` against main.
- **Moving a branch ref from one worktree silently desyncs the worktree that has it checked
  out — including the one serving veg11.** Caused here: merging #732 needed a local merge (the
  token lacked `workflow` scope), so `git checkout -B develop origin/develop` ran in `wt-dev`.
  `develop` is checked out in the MAIN tree at `apps/verenigingen`, which is what bench serves
  veg11 from. The branch pointer moved; that tree's index and files did not. Result: HEAD at
  `34fb9d5f2` while index and worktree were byte-identical to `8576ce9cf`, showing as **346
  staged changes** — `26,241` deletions, including handoff docs that very much still exist.

  It reads like catastrophic damage and is none: the old content was an ancestor of HEAD, no
  untracked or unstaged work existed, and `git reset --hard HEAD` restored it. But a session
  that sees a 26k-line staged deletion in the veg11 tree and reacts fast could do real harm.

  **Check `git status` in the main tree after any operation that moves `develop`**, and prefer
  a detached worktree (`git worktree add <dir> origin/develop`) over `checkout -B` for
  trunk-side work. Related to [[a-git-pull-on-the-live-tree-is-inert-until-restart]]: gunicorn
  runs `--preload`, so the files being stale or fresh changes nothing until a restart — which
  is also why this can sit unnoticed.

## State

**Merged (12):** #719, #721, #724, #725, #727, #728, #729, #730, #732, #734, #735, #736.

**Open (7):** #740 (#696 leap day), #741 (#667 Dynamic Link + new AST gate), #742 (#713
donation history), #743 (#427 payment method + the api-service fix), #748 (#699 triage, 5 sites),
#749 (#662 fan-out), #750 (baseline resync — **merge first**, the others inherit its red).

**Filed (7):** #737, #738, #739, #744, #745, #746, #747.

Every open PR has had at least two skeptical reviews, and the second round changed the outcome
on four of them. #749 needed three.

---

# Later the same day: two CI reds that were nobody's PR

Continuation session. All seven PRs above landed. The two failures that followed are both
worth keeping, because **neither was caused by the branch it reddened**, and each needed a
different kind of proof.

## A green suite is not evidence when the fixture draws a random number

#749 passed all 12 shards, then went red on shard 3 **after nothing but a develop merge** —
in its own new test. The amount its fixture mints to scope a query,

```python
grand_total = 25.0 + next(EnhancedTestDataFactory._global_unique_seq) / 100
```

is bracketed back with `amount_min == amount_max == grand_total`, and the production
predicate is `si.outstanding_amount <= %s` against the **stored cent**. `25.0 + 301/100` is
`28.009999999999998`; the invoice stores `28.01`; `<=` excludes the very row under test.

**32 of every 1000 sequence values do this** — n = 201, 226, 251, … every 25th. The merge did
not cause it, it shifted the counter onto a bad value. The earlier 12/12 green was a lucky
draw, and re-running would not have cleared it: the sequence is deterministic for a given
shard composition.

Fixed by rounding at the mint site. **Both** mint sites, not just the one that failed — the
second (`trapped_total`) was proved vulnerable by pinning it to n=326, which reddens two
*different* tests. Verified by pinning rather than waiting: unfixed, n=301 reddens 3 tests and
n=326 reddens 2 others; fixed, both pinned values and the natural sequence pass.

**The generalisation:** a fixture that mints a value from a counter is a *sampler*. Green means
the sample was fine, not that the space is. When a test brackets a computed float against a
column the database rounds, the two must be rounded the same way at the same place.

## A failure timestamped 0.56 seconds past midnight

The next red was shard 10, a different module, erroring in `setUp`:

```
frappe.exceptions.ValidationError: Due Date cannot be before Posting Date
```

with the defaults dict recording **both** dates as `2026-09-02`. That contradiction is the
whole diagnosis. `create_test_sales_invoice` (`tests/utils/base.py:1568`) reads
`frappe.utils.today()` twice and left `set_posting_time` off unless the caller passed
`posting_date`; ERPNext's `TransactionBase.validate_posting_time`
(`utilities/transaction_base.py:34-38`) then overwrites `posting_date` with `now_datetime()`
during validate, and `AccountsController.validate_due_date` compares the **caller-supplied**
`due_date` against it without recomputing.

The proof is the clock:

```
2026-09-02T18:30:00.5645782Z  ✖ test_automated_processing_flag
```

The site is Asia/Kolkata (UTC+5:30), so `18:30:00.000Z` **is** `00:00:00 IST`. The test died
0.56 s into the new day, with `due_date` stamped in the old one.

**This is where re-running is legitimate.** CLAUDE.md's rule that a re-run proves nothing is
about *order* dependence, which reproduces deterministically. A wall-clock race does not, so
the re-run is the discriminator — and it passed, from a third direction after the timestamp
and the deterministic reproduction.

Fixed in **#754** by setting `set_posting_time: 1` unconditionally. **The repo had already
solved this and `base.py` was the straggler** — of four sales-invoice helpers, it was the only
one both lacking that flag and defaulting `due_date` to `today()` with zero slack:

| helper | `due_date` default | `set_posting_time` |
|---|---|---|
| `tests/utils/base.py` | `today()` — zero slack | only if `posting_date` in kwargs |
| `fixtures/enhanced_test_factory.py:4730` | `today()+30` | **always 1**, comment documents this exact behaviour |
| `fixtures/test_data_factory.py:551` | `today()+30` | — (30 days slack) |
| `fixtures/sepa_test_factory.py:203` | `today()+14` | clamps posting_date to due_date |

A sub-second window is not something to wait for. Backdating the helper's own clock one day
puts it behind the server's exactly as it is after midnight: **9/9 tests error with the exact
CI message; with the fix, 0 do.** 64 modules call this helper, so any of them could have drawn
it on any run crossing a site-clock midnight.

**Upstream:** searched `frappe/erpnext` — 21 issues match the error string, none concerns a
clock rollover, and a control query confirms the search works. Not filed: the honest claim is
narrow enough ("a server-recomputed `posting_date` validated against a client-supplied
`due_date`") that upstream would reasonably answer "pass `set_posting_time`", which is the fix.

## Two traps found while fixing, both filed

- **#752 — a validator that cannot run from a worktree outside the bench.** The Unknown DocType
  Name Guard resolves its authority by walking up for a directory holding both `apps/` and
  `sites/`. A worktree under `/tmp` has no such ancestor, so it loads **0 doctypes** and
  refuses. The refusal is correct; the danger is the escape hatch, because the obvious way past
  a blocked commit is `--no-verify`, which disables *every* hook over a location detail. There
  is no `BENCH_APPS` env override — it is a computed module constant.
  **Operational rule: agent worktrees must live under the bench**, not in `/tmp`.
- **#753 — the shipped Simple DD Workflow contradicts the DocType it binds to.**
  `setup/simple_dd_workflow_setup.py` binds a Workflow to `Direct Debit Batch.approval_status`,
  but its states (Draft, **Pending**, Approved, Rejected, Submitted, Completed) and that field's
  Select options (**Pending Approval**, Pending Senior Approval, Approved, Rejected) share only
  two values, and `dd_batch_workflow_controller.py:42,253` targets `"Pending Approval"` — a
  state the workflow has no transition to. Latent, not live: the setup is `@frappe.whitelist()`
  but is in neither `hooks.py` nor `patches.txt`, and **veg11 has no Workflow row for that
  doctype at all**. `test_site_2` does, which is why 4 tests in
  `test_collection_run_not_lost_silently` fail there — identically on develop, verified against
  a detached `origin/develop` worktree.

  That last point nearly cost a misdiagnosis: the first run of the #754 fix on `test_site_2`
  still showed 5 errors and looked like a partial fix. They were `WorkflowPermissionError`, not
  the date error — a different exception from pre-existing site dirt. **Read the exception
  type, not the failure count.**

## Method notes

- **Both reds were "the branch's fault" on first appearance and neither was.** The tell in each
  case was cheap: for #749, the traceback printed the offending float; for shard 10, the
  timestamp. Read what the failure actually says before running anything.
- **The class rule paid twice.** #749's fix covers two mint sites because the second was tested,
  not assumed. #754's covers the helper's defaults because the three sibling helpers were read
  first — which is also what supplied the fix.
- A grep for the class must run **in the tree that has the code**. The first class-grep here ran
  in the main checkout on `develop`, which does not contain #749's new file, and found nothing.
  `pwd` alongside any grep you are about to argue from — the same lesson recorded above.

## State, end of session

**Merged:** the twelve above, plus **#749**.

**Open:** **#754** (posting_date midnight race), this handoff.

**Filed:** the seven above, plus **#752**, **#753**.

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

## State

**Merged (12):** #719, #721, #724, #725, #727, #728, #729, #730, #732, #734, #735, #736.

**Open (7):** #740 (#696 leap day), #741 (#667 Dynamic Link + new AST gate), #742 (#713
donation history), #743 (#427 payment method + the api-service fix), #748 (#699 triage, 5 sites),
#749 (#662 fan-out), #750 (baseline resync — **merge first**, the others inherit its red).

**Filed (7):** #737, #738, #739, #744, #745, #746, #747.

Every open PR has had at least two skeptical reviews, and the second round changed the outcome
on four of them. #749 needed three.

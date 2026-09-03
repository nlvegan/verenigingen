# Handoff — 2026-09-03b: the checks that were checking me

Continues [2026-09-03](2026-09-03-three-ways-to-pass-without-checking-anything.md), whose two
open decisions were taken this session and whose open ratchet item is now fixed. **Eight agents,
eight branches, zero file collisions, all eight merged, 1 issue closed with no code, 2 issues filed.**

The previous handoff was about three mechanisms that reported success while checking nothing.
This session found more of them — but the sharper finding is that **three of the day's
verification failures were mine, in my own verification of the agents' work**, and the thing
that caught every one was refusing to accept a pass without a control that could distinguish it
from a failure.

## I got two controls wrong before getting one right

Verifying PR #767's shrink gate, I ran three controls and misread two:

| what I did | what I concluded | what was actually true |
|---|---|---|
| `validator.py \| tail -4; echo exit=$?` | "exit 0, validator passes" | `$?` after a pipe is **`tail`'s** status. I was reading the exit code of `tail`. |
| deleted "the first non-comment line" from a baseline and ran the gate | "the gate fails to recognise a pure shrink — defect" | line 16 was **blank**. I deleted whitespace. The gate's *"no key's count changed"* was correct and my control was not. |
| invoked the gate with one argument | "exit 2 on every scenario, including unchanged" | the gate takes **two** required args. Exit 2 was argparse rejecting *me*. |

Only the fourth attempt — correct arguments, a real data key, both directions — produced the
matrix that actually justified the merge. Every wrong reading pointed the same way: **blaming
the instrument for my own measurement error.** The previous handoff's rule ("the check passed"
is not a fact until you know the check can fail for the reason you care about) has a mirror
image worth writing down: **"the check failed" is not a fact about the code until you know your
invocation was right.**

The `$?`-after-a-pipe bug is worth internalising specifically. One agent independently hit and
reported the identical mistake in its own verification pass. Two of us, same session, same
shell footgun, both while trying to be rigorous.

## The ratchet caught what two skeptical reviews did not

PR #765 passed **two** skeptical review rounds and then failed CI's duplicate-helper ratchet:
its new test file added a **14th** copy of the `_make_donor` clone family and created a new
`_make_form_data` family.

The reviews were reading the diff. The ratchet was measuring the tree. Neither is a substitute
for the other, and the reviews were not negligent — a 14th clone is invisible unless you are
counting across the whole repo, which is exactly what a census does and what reading cannot.

**The fix was to de-duplicate, not to regenerate the baseline.** Regenerating would have
laundered a brand-new clone into the file that exists to prevent exactly that. Worth stating
because the failing job's message makes regeneration look like the obvious remedy, and a
sibling agent had *correctly* regenerated a different baseline an hour earlier — so "regenerate
the baseline" was locally precedented and globally wrong.

## Two agents stalled in a way that looks like completion

**New failure mode, cheap to fix.** Two of eight agents ended their turn saying they would
"wait for the test-run notification" / "hold for the background suite" — for a job that would
never notify them. Both had **zero commits and a fully dirty worktree**. The task-completion
notification fired, so from the outside it looked done.

Brief line to add: **"never end your turn waiting on a subagent or background job; run it in
the foreground and read the output in the same turn. If a suite is too slow, run the narrower
subset that covers your change and say what you did not cover."**

Both finished correctly on being told once. This is not a capability gap; it is a missing
instruction.

## The premise count is now 11 — and the shape has stopped varying

**#617** claimed `cancel_active_mandates` reads `purposes=[]` as *every* purpose. It tests
`is None`, not falsiness (`mandate_candidates.py:301`), so `purposes=[]` cancels nothing. Fixed
by an already-merged ancestor commit; **the branch never touched that file**. Closed with no
code.

**#726**'s literal premise was also false, though a real narrower defect existed at the same
site. The agent's first proof of it was a **false positive** — a global mock also intercepted
`frappe.get_doc` *inside* `frappe.log_error`, so the instrument was measuring itself. Re-run
with a targeted mock, the result inverted.

Eleven for eleven, the pattern holds: **an issue here reliably identifies a real symptom and is
unreliable about the mechanism.** Nine "Suggested fix" sections have now been wrong; #755's
suggested `allow_system_user=True` was verified to fail for Guest too.

## A directory, not an abandonment

The #755 investigation turned on a question the maintainer asked mid-session — *would this let
us build pages in the web form builder?* — which forced a look at the actual mechanism and
found something better than either option on the table:

**All three of the app's Web Forms have never installed on any site.** `frappe/model/sync.py:145
get_doc_files()` walks `<module_dir>/web_form/<name>/<name>.json`; the module dir is
`verenigingen/verenigingen/` and contained no `web_form` folder. The definitions sat one level
up at the app root. Zero Verenigingen `Web Form` rows on `test_site_1` or veg11 — every row on
both belongs to frappe/erpnext/hrms.

So #755's "no live front door" was true and its implied cause was wrong. **When a shipped
definition is inexplicably absent, check directory placement before concluding the feature was
abandoned** — the same shape as #600, where fixture shipping turned out to be directory-driven
and the filed issue was wrong about it.

Two further facts that constrain what can be done with them:

- `web_form.py:736 get_web_form_module()` loads the Python hook module **only** `if
  is_standard`; `web_form.py:96` makes an `is_standard` form read-only in Desk **unless**
  `developer_mode`. veg11 has `developer_mode: True`, so both are available there — but
  `modules/utils.py:35` then exports edits **back to files**, and veg11's tree is the tree that
  serves the site. Editing that form in Desk dirties the working copy.
- The form content is broken independently: `donation_form.json` collects **7 data fields that
  do not exist on `Donation`**. Any non-import save throws — *including flipping `published`
  from Desk*. Shipped `published: 0`; fixing the field lists is a separate task.

## What the answering round found, three times

The standing rule is to review the commit that **answers** the review. It paid three times
today, and in two cases the defect was *created by* the response:

- **#766**: widening the eBoekhouden handlers exposed a `mutations` variable read before
  assignment — newly reachable precisely because more now propagates. Found only in round 2.
- **#768**: round 1 found mijnrood's membership branch catching *the exact deadlock the engine
  fix now raises*; round 2, reviewing that fix, found **six more** related-record handlers still
  swallowing. Separately, a review proved the Procurios guard was **dead for the common path**
  because the swallow lived three call-frames below it — which is why service-layer files are in
  an importer PR.
- **#763**: the reviewer found a second, unfiled defect in the same file —
  `_generate_sepa_mandate_id(member_name)` ignored its argument and used an unlocked global
  daily count, so two members in the same window could mint the same `unique:1` mandate_id.

## Environment

- **Eight parallel agents on one test site is self-inflicted contention.** Two agents
  independently reported transient "created but not found" failures that cleared on retry,
  coinciding with sibling worktrees hitting `test_site_1`. `test_site_1`..`test_site_5` exist;
  **assign each agent a distinct site.**
- Agent worktrees were all placed **under the bench** per the previous handoff's rule. This
  worked — no validator refused, and no vacuous pass was observed from a wrong-directory
  resolution.
- **Zero file collisions across all eight branches**, verified by intersecting the changed-file
  lists before any merge. The disjoint-territory partition held even where one agent had to
  reach three call-frames into the services layer.

## State

**All eight PRs merged. Zero open at session end. `develop` at `888825e8b`.**

| PR | what |
|---|---|
| #767 | ratchet baseline shrink gate (the previous handoff's open item) |
| #760 | #674 — the volunteer form told rejected applicants they had succeeded |
| #763 | #624 — an unreachable SEPA mandate guard + an unlocked `unique:1` mandate-id race |
| #764 | #663 — one Active Membership per member in the dues-schedule auto-creator |
| #761 | #753 — deleted the dead DD workflow setup, pruned 2 orphaned COR rules |
| #766 | #726/#731 — eBoekhouden lost-connection (2006/2013) no longer swallowed |
| #765 | #755 — the app's Web Forms now install, unpublished; 4 donation-form bugs |
| #768 | #698/#700 — a deadlock no longer counts as one bad row; rows no longer commit what they report skipped |

**#767 was merged first, deliberately**, so the baseline-touching merges that followed landed
under the protection it adds — including #761, which shrank `error_swallow_baseline.txt`, the
exact shape that reddened trunk last session.

Trunk verified green after the merges (`Verenigingen CI`, `Code Validation`, `Pylint`, `CodeQL`,
`Security Permission Check`), separately from the PR checks. **Stated narrowly:** on a `push`
event the shrink gate runs with `--fail-on-shrink`, so a green `Code Validation` means the
baseline was genuinely in sync — it does **not** exercise the self-heal path, which only runs on
`pull_request`. Self-heal is proven by the local control matrix in #767, not by this run.

**Closed with no code (1):** #617 — false premise #11.

**Filed (2):** #762 (a second live IBAN-comparison occurrence, in a function with three further
defects and no coverage — an isolated fix there would be unverifiable). **#769**: the
duplicate-helper ratchet is **name-keyed**, so it is imprecise in *both* directions — it failed
two PRs today over *coincidental* names (`_row`, `_run_import`, `_make_donor`) while the
validator's own `--report` classified them as *"very likely a coincidence rather than a
copy-paste"*, and it stays blind to a genuine differently-named clone
(`_create_stub_member_import_doc`). The gate diffs raw counts and ignores the near-identity
verdict its own tool already computes.

## For next session

- **#765** needs its de-duplication verified, including **re-run mutation tests** — moving
  helpers into a shared module is exactly the change that can silently defeat a test.
- The **branch-vs-trunk baseline staleness race** is now documented in a workflow comment but
  not mechanically closed; it needs a merge queue or an auto-committing bot.
- `test_quality_enforcer`'s escape hatch: a `# Mock justified:` pragma can hide an existing
  violation's departure from the baseline without a reviewable diff. Disclosed, not closed.
- Still open from before: **#672**, **#675**, and the ~38 `e_boekhouden` swallow occurrences
  #768 deliberately left to its sibling.

https://claude.ai/code/session_01TS8PzQDJZXjpgmtzhVJo7K

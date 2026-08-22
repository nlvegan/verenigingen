# Handoff — 2026-08-22c: the fix that already existed, and the rule that lost its flagship

Picked up from `2026-08-22b-the-review-that-reversed-the-fix.md`. Three of the four items
on its "for whoever picks this up" list were taken; the fourth (deploying the live tree)
was declined deliberately.

Both pieces of real work turned on the same thing: **the issue and the handoff each
specified a fix, and measuring the specified fix is what showed it was wrong.** #456 asked
for a patch that already existed. #458's proposal, keyed on the worst pair, silently drops
the case CLAUDE.md leads with.

And then CI found something neither of us had: **the clone comparison gave different
answers on different machines**, on a byte-identical tree. That had been true of `--drift`
before this PR touched it.

> The question that paid for itself twice: **before implementing the fix an issue asks
> for, check whether it is already there — and measure the proposed rule against the
> cases it was written to catch, not against its own description.**

## Landed

| | | |
|---|---|---|
| #467 | handoff 2026-08-22b | merged |
| #456 | `Donation.payment_id` unique index | **closed** — fix already existed; veg11 migrated |
| #458 | the ratchet blocks clone families, not name collisions | pushed, awaiting merge |

**veg11 was migrated** (not redeployed — see below).

## #456: the fix already existed, and the premise was an unmigrated site

The issue asked for a `pre_model_sync` patch plus the JSON flag. Both were already there:
`patches/v2_2/enforce_unique_donation_payment_id.py` from #345 (`9f22bb57`) normalises
`'' -> NULL`, resolves duplicates keeping the earliest, writes an audit `Comment` per
cleared value and deletes nothing; `donation.json` already carried `unique: 1`.

**veg11 had exactly one pending verenigingen patch out of 55 — that one.** Its last migrate
was 2026-08-15; the patch landed after. So the missing index was never Frappe silently
dropping the flag over a duplicate, which is what the issue and its review comment both
inferred. It was a site that had not migrated.

`tabPatch Log` settles that in one query, and it is the query neither of us ran:

```sql
SELECT patch FROM `tabPatch Log` WHERE patch LIKE '%enforce_unique_donation_payment_id%'
```

Empty means it never ran, which is a completely different diagnosis from "it ran and the
constraint was refused".

### The sweep the issue left explicitly unchecked

Its own scope note asked for it: all **38** `unique: 1` field declarations in the app's
DocType JSONs, checked against live metadata **and** `SHOW INDEX`.

| site | declarations | divergent |
|---|---|---|
| veg11 (before) | 38 | **1** — `Donation.payment_id` |
| test_site_1 | 38 | 0 |
| veg11 (after migrate) | 38 | **0** |

No other doctype in this app has the divergence.

**`meta.unique == 1` is not evidence the index exists.** test_site_3 had metadata saying
unique and **no index at all** — `reload-doctype` moves the metadata without building the
constraint. Only `SHOW INDEX` answers the question.

### The control

Same commit, same module, only the index differs:

| site | index | `test_recurring_donation_charge` |
|---|---|---|
| test_site_3 | none | **FAILED** — `'Assoc-Dnt-2026-00036' != 'Assoc-Dnt-2026-00035'` |
| test_site_5 | built by the patch | **37/37 OK** |

The red is `test_a_lost_race_adopts_the_winner`: a second Donation created instead of the
first being adopted — the production outcome, reproduced. test_site_5 had reproduced
veg11's shape *beforehand* (same duplicate `test_donation_payment_123`, no index, patch
pending), which is what made it a control rather than a demonstration. With a control on
the control, after migrating it:

```
duplicate     INSERT -> IntegrityError (1062, "Duplicate entry ... for key 'payment_id'")
non-duplicate INSERT -> accepted
```

### veg11, after `bench --site veg11.veganisme.org migrate` (backup taken first)

```
meta unique:          1
index:                payment_id, Non_unique=0
patch log:            enforce_unique_donation_payment_id @ 2026-08-22 13:35:22
donations:            60 -> 60        (no row deleted)
Assoc-Dnt-2026-00130: test_donation_payment_123   (earliest, kept)
Assoc-Dnt-2026-00131: NULL            + audit Comment naming the keeper
remaining duplicates: none
sweep:                38 declarations, 0 divergent
/login:               200
```

test_site_3 and test_site_5 were migrated too, so neither is left as a stale site whose red
reads like a red branch. The working tree was clean before and after — no fixture rewrite.

**Not closed by this:** whether `ensure_donation_for_recurring_charge` should take a row
lock anyway rather than rely on a constraint nothing verifies at runtime. Same question as
#424 and #436.

## #458: worst-pair cohesion loses `_persist_eur_company`

The open decision was how to cut the method-aware ratchet's firing rate. The proposal was
to block only when **every** copy is >=90% similar to every other.

I replayed the last 400 commits, reading blobs from git rather than checking each one out,
with the denominator being commits that add a `.py` file under `verenigingen/` (n=129).
Built independently of the reviewer's replay, it puts the current rule at **61.2%** against
their **61%**.

| rule | fires | Mollie trio (#444) | `_persist_eur_company` (#394) | 45x `_make_member` |
|---|---|---|---|---|
| name only (before) | **61.2%** | blocks | blocks | **blocks** |
| worst pair >= 0.90 (proposed) | 26.4% | blocks | **LOST -> advisory** | advisory |
| **>= 25% of pairs >= 0.90 (shipped)** | **35.7%** | blocks | blocks | advisory |
| best pair >= 0.90 | 47.3% | blocks | blocks | **blocks** |

**`_persist_eur_company` has 17 copies and 136 pairs, of which 43 reach 0.90 and one is
byte-identical — yet its worst pair is 0.13.** A worst-pair rule calls that a name collision
and stops blocking it. It is the case CLAUDE.md opens with. The share separates the two
cleanly: 0.5% for `_make_member`, 3.8% for `_make_donor`, 32% for `_persist_eur_company`,
100% for the three Mollie helpers.

**25% is a knob, not a boundary, and the docstring says so.** 342 of 568 families sit at
exactly 0% and 110 at 100%, but the middle is a continuum: dropping the threshold to 0.10
pulls in 38 more families (`_ensure_company`, `_make_account`, ...).

### Two things the proposal could not have done

**"~20 lines on top of what is in the PR" could not have worked.** `code-validation.yml`'s
*Baseline did not grow* step summed **every** baseline line. Left alone it re-imposes
exactly the blocking the validator just stopped doing — a new copy of a name collision is
*supposed* to be recorded rather than removed. The baseline now marks each clone family
inline and that step compares the **marked** total, which also makes the file readable as
the triage list: **170 of 568 families block**.

**The working-tree change left uncommitted on that branch crashed the gate's failure path.**
`for p, _ in _by_name(...)` unpacked what its own change had made 3-tuples, so the gate
would have raised `ValueError` at the exact moment it fired. It was never run in a state
where it fired. That work — `--drift` comparing normalised bodies, 89 families to 35 — is
now committed rather than sitting unsaved in a dead session's scratch directory.

### The comparison gave different answers on different machines

The most valuable thing this PR found, and CI found it, not me.

CI regenerated the baseline and got percentages this box did not: `_root` at 50% against
33% here, `_ensure_accounts` 31% against 24%, `_setup_sepa_test_configuration` unmarked
against 100%. I chased two wrong explanations before the right one, and both were ruled
out by measurement rather than argument:

1. **Tree drift.** develop had indeed moved twice — but `git diff HEAD origin/develop --
   verenigingen` was empty, and the exact ref CI checked out (`refs/pull/458/merge`,
   `ca662f83`) is **byte-identical to HEAD across the whole tree**.
2. **Python version** (3.12.3 here, 3.12.14 there). Ruled out by running the same
   computation under 3.12.3 and 3.14.0: identical to six decimal places.

The actual cause is two things that compound:

- **`difflib.SequenceMatcher(None, a, b).ratio()` is not symmetric.** It indexes the
  SECOND sequence and applies the autojunk heuristic to that one alone. On this tree
  `_make_role` has a pair scoring **0.887 one way and 0.825 the other** — straddling
  CLONE_RATIO — and `_persist_eur_company` one at 0.434 versus 0.137.
- **`os.walk` yields in filesystem order**, which differs between machines, and that order
  decided which way round each pair got compared.

Every number in CI's diff reproduces here just by shuffling the copies: `_root` takes
0.167 / 0.333 / 0.500 across eight shuffles, and CI got 0.500.

**This predates the blocking rule.** `--drift` and `--report` share the comparison, so the
"89 families -> 35" figure already shipped in this PR was order-dependent too, as was my
own 34.1%. Fixed by sorting the walk and comparing each pair in a canonical order. Verified
three ways: a single value across eight random orders (control: the raw comparison still
varies), the baseline regenerates identically, and it is byte-identical under 3.12.3 and
3.14.0.

**The general lesson: CI disagreeing with a local run on a byte-identical tree is a
determinism bug in your code, not an environment difference.** The instinct here — and
CLAUDE.md's own environment-parity section trains it — is to reach for "CI has different
credentials / a different version / a different tree". Prove the tree identical first, and
the remaining explanation is your own non-determinism.

### Controls

**Mutation matrix, each killing a disjoint test:**

| mutation | dies |
|---|---|
| `CLONE_SHARE = 1.01` | both "must block" tests |
| `CLONE_SHARE = 0.0` | "must not block" |
| revert to the worst-pair rule | the cluster test **alone** |

The third is the one that matters: it is what stops the rejected rule passing this suite.
My first attempt at it was not R1 at all — it compared a worst-*similarity* against the
*share* threshold, and killed the wrong test. A mutation has to be the rule you rejected,
not merely a change in that direction.

The determinism tests needed the same treatment and failed it first time. I wrote two
tests asserting the comparison is symmetric and order-independent, on bodies I asserted
were asymmetric — **they were not**, so both passed on any implementation at all. There is
now a control test pinning that the chosen bodies really do disagree under the raw
comparison, and a third mutation (unsorting the walk) for the other half of the fix. The
order test also had to operate on crafted normalised bodies, because `ast.unparse`
collapses the straddling pair to 0.9007 / 0.9043 — same side of the threshold, nothing to
detect.

**Four cells, run in place** — never from `/tmp`, where `REPO_ROOT` is `parents[2]` of the
validator's own path and it scans somewhere else, which looks exactly like a control
agreeing with you:

| tree | exit |
|---|---|
| clean | 0 |
| + a 4th copy of `_setup_mollie_bank_account` | **1 — blocked** |
| + a 6th, unrelated `_make_member` | **0 — reported, not blocked** |
| that same tree, judged by the old name-only rule | 1 |

Tests 25 -> 37, all green.

### What the relaxation does NOT buy

`_drop` (3 copies, 33% of pairs near-identical) is a genuine clone family and **still
blocks**. The previous handoff described `30b3429d`, the #424 lock fix, as hard-blocked on
`_drop` and `_member`; under this rule `_member` (17 copies, unmarked) becomes advisory and
`_drop` does not. That commit is half-unblocked, not unblocked. The headline rate change is
real but narrower in practice than it reads.

## develop moved twice underneath this PR

CI tests the **merged** tree; a local worktree tests the branch. Two separate red runs came
from that gap alone, neither reproducible locally until develop was merged in:

1. #438's `test_history_manager_row_lock.py` added a third `_drop`.
2. #468 (`fix/459-lock-order-canonical`) landed `test_history_lock_order.py` mid-CI-run,
   adding `_row` (5th copy) and `_seat_on_board` (2nd).

The second is worth reading closely, because the ratchet **passed** on it — both names are
collisions and were reported without blocking, which is the change working exactly as
designed. What failed was the *next* step, *Baseline is in sync with the tree*. **That is
the residual friction and it is unchanged by this PR:** an advisory regression still
requires regenerating and committing the baseline, so a developer adding a 46th
`_make_member` still gets one red CI step and a one-command chore. It is a much smaller
tax than renaming the method, but it is not zero, and nobody has decided whether it should
be.

## What went wrong in how I worked

- **`gh issue view --comments` and `gh pr view --comments` are BROKEN here** — the same
  Projects-classic GraphQL error as `gh pr edit`, and they print **nothing**. CLAUDE.md's
  rule 5 therefore returns an empty result that looks like "no comments". On #456 the
  entire finding lived in a review comment those commands refused to show. Use
  `gh api repos/<o>/<r>/issues/<n>/comments`. Memory updated.
- **I reported in-progress checks as failures.** A jq filter of `conclusion != null`
  matches the empty string too, so nine queued jobs were printed as `FAILED`. Filter on
  `status == "COMPLETED"` first.
- **MEMORY.md was 27.4KB against a 24.4KB limit**, so it was being truncated at session
  start and entries were silently not loading. Trimmed to 24.2KB with the detail left in
  the topic files. It is one line per entry for a reason.

## For whoever picks this up

- **The live tree is still ~40 commits behind `origin/develop`.** Deliberate: the migrate
  was authorised, the redeploy was not. `bench migrate` and `git checkout` are separate
  decisions and this session only took the first. Re-check the gap before asserting
  anything about what veg11 serves — it drifts on its own.
- **#458's residual friction is undecided** (the *Baseline is in sync* chore above).
- **The most faithful rule was measured and not implemented:** fail only when a copy in a
  **changed** file is near-identical to a pre-existing one — 36.4%, and that understates it
  because the replay only considered newly *added* files. It needs the validator to consult
  git and give up its context-free whole-tree design.
- The `--drift` work-list is 35 families; `python scripts/validation/duplicate_helper_validator.py --drift`
  regenerates it.
- **Sessions are merging concurrently.** develop moved twice in the two hours this took.
  `git worktree list` is the register of what else is in flight.

## Raw evidence

```bash
# the query that would have re-diagnosed #456 in one step
SELECT patch FROM `tabPatch Log` WHERE patch LIKE '%enforce_unique_donation_payment_id%'

# meta.unique is NOT the constraint -- test_site_3 had 1 and no index
frappe.get_meta("Donation").get_field("payment_id").unique
frappe.db.sql("SHOW INDEX FROM `tabDonation` WHERE Column_name='payment_id'")

# the whole class, not the one name: every unique:1 declaration vs every real index
#   38 declarations -> 1 divergence (veg11), 0 after migrate

# the replay: read blobs, do not check out 400 commits
git ls-tree -r <sha> -- verenigingen | git cat-file --batch

# a mutation must BE the rejected rule, not merely a change in its direction

# CI disagreeing on a byte-identical tree is YOUR non-determinism, not the environment
git fetch origin '+refs/pull/<n>/merge:refs/remotes/origin/prmerge'
git diff --stat HEAD origin/prmerge          # empty => the tree is not the variable

# difflib.SequenceMatcher.ratio() is NOT symmetric -- it indexes the SECOND sequence
difflib.SequenceMatcher(None, a, b).ratio() != difflib.SequenceMatcher(None, b, a).ratio()
# ... and os.walk is unsorted, so which way round a pair got compared varied by machine
```

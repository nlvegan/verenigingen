# Server Tests Red-Baseline Triage & Remediation Plan

**Date:** 2026-05-29
**Status:** Draft / actionable
**Scope:** `Server Tests (GitHub Hosted)` workflow (the full `bench run-parallel-tests` suite, 4 shards)
**Related:** [[ci-failure-sweep-2026-05-28]], `docs/plans/2026-05-27-test-failure-triage-plan.md` (superseded data)

---

## 1. Executive summary

`Server Tests (GitHub Hosted)` is **red on `develop` and has been for weeks** — this is a **long-standing multi-root-cause baseline, not a regression**.

- On `develop@2f0db748` (current HEAD region) the suite has **~2,336 unique failing tests** across the 4 shards, spread over **~170 distinct error signatures**.
- This is **stable run-to-run** (shard 2 ≈ 666 across 5 separate develop runs: 663/667/666/666/666; union ≈ 2,333–2,349).
- CI history disproves the earlier "PR #106 passed full suite" claim — `39399e4d` (#106), `6e485a65`, `d807bd79`, etc. **all failed**. The handoff was wrong on that point.
- `2,336` ≈ the "~600 remaining (Groups A/C/F/G)" the prior CI-sweep sessions tracked, having already cleared ~1,100+.

**This is a program of work — many small, independently-verified PRs — not a single fix.** The original task this session ("dues-rate regression") does not exist as a distinct regression; the dues-rate error is one minor tail signature.

---

## 2. Verification constraints (read this first)

These constraints dictate the entire methodology. Ignoring them produces MAJOR reviewer findings and false "fixed it" claims.

1. **The full suite cannot be run cleanly locally.** Three independent blockers:
   - Lock contention when another `bench run-tests` / coverage run holds the DB (`tabSeries FOR UPDATE` → `Lock wait timeout exceeded`).
   - Pre-existing BOM Secondary Item `ImportError` for any test that triggers ERPNext test-record creation (does **not** affect CI).
   - **The local DB is dirty.** Leftover seed records (e.g. `Monthly Membership Template`, stray Customers) **mask the clean-CI failures** — many CI failures simply do not reproduce locally. This is the single most dangerous trap: "passes locally" means nothing here.

2. **CI is the only oracle, and it's expensive & noisy.**
   - ~13–18 min per shard; **shard 3 ≈ 38 min** (it carries ~1,781 tests). Full run ≈ 40 min.
   - The **union failure count varies run-to-run** when a shared setUp/early test cascades; individual buckets (esp. shard 2 / Customer dups) can swing ±300. *However, per-shard counts on develop are tight (±2), so a clear jump on a PR is signal, not noise.*

3. **Shard assignment is per-file and may differ between runs.** Therefore **never compare shard-N vs shard-N directly** — compare the **union across all 4 shards**. (This session's near-miss: shard 3 looked clean in isolation while the union showed +302.)

### 2.1 The canonical "does my PR help?" recipe

Measure a PR's true delta against a **same-base-commit** develop run, by union, with verified-complete fetches:

```bash
# For each of the 4 shard jobs in a run, extract the unique failing-test set:
gh api repos/nlvegan/verenigingen/actions/jobs/<JOB_ID>/logs 2>/dev/null \
  | grep -aoE "(FAIL|ERROR) \x1b\[0m test_[a-zA-Z0-9_]+ \([a-zA-Z0-9_.]+\)" \
  | sed -E 's/.*\x1b\[0m //' | sort -u
# Concatenate all 4 shards -> sort -u -> union set per run.
# IMPORTANT: verify each shard log fetch is non-empty (>100 fails); gh api can
#            return empty on rate-limit and silently undercount the union.
comm -13 base_union.fails pr_union.fails   # NEW failures introduced by the PR (must be ~0)
comm -23 base_union.fails pr_union.fails   # FIXED by the PR
```

Get the same-base develop run id: `gh run list --workflow "Server Tests (GitHub Hosted)" --branch develop --json databaseId,headSha`. Job ids: `gh run view <RUN> --json jobs`.

A bucket fix is **good** only if `NEW ≈ 0` (allow ~2/shard flake noise) **and** `FIXED > 0`. A reviewer-approved, locally-"correct" fix can still be **net-negative** if it unblocks setUps that cascade into other buckets (see §5, PR #113).

---

## 3. Root-cause buckets (authoritative, from `develop@2f0db748` all 4 shards)

Counts are **raw error-signature occurrences** (a single failing test can contribute several, via traceback frames + the member→customer cascade), so treat them as **relative leverage**, not exact test counts. Normalised (names/hashes/amounts masked).

| # | Bucket | ~Occ. | Root cause | Risk to fix |
|---|--------|------:|-----------|-------------|
| **B1** | **Entity-name collision / test isolation** — `DuplicateEntryError ('Customer'/'Chapter'/'Role Profile', …)`, `UniqueValidationError ('Volunteer', email)` | **400+** | Member creation auto-creates a Customer named `member.full_name` (`services/member/approval/application_payments.py:171`). ~10+ test files pass **fixed** `first_name`/`last_name` (`"Dues"/"Tester"/"PerfTest"/"Payment"/"Portal"/…`), bypassing factory uniqueness → identical `full_name` → Customer PK collision across tests. Chapter/Volunteer have the same fixed-name pattern. The dedup in `customer_handling_service.py:96-116` only **warns**, never reuses. | **HIGH** — uniquifying `last_name` in the factory breaks **47** `assertEqual(…last_name, "…")` sites. Needs a surgical approach (see §4). |
| **B2** | **Missing seed records** — `Could not find Default Dues Schedule Template: Monthly Membership Template` (55), `Could not find Membership Type: Monthly Standard` (25) / `Regular` (14) / `Daglid` | **110+** | Factories/tests reference ambient seed docs that exist in dirty-local but **not clean CI**. | MIXED. The `Monthly Membership Template` slice is **already fixed** by PR #113 (factory lets the controller auto-create). The hardcoded `Monthly Standard`/`Regular`/`Daglid` membership-type names need per-test factory use or a seed fixture. |
| **B3** | **Missing/invalid environment config** — `Company Account is mandatory` (39), `Subscriptions are not enabled in Mollie Settings` (24), `[Item …]: stock_uom` (36), `Target Exchange Rate is mandatory`, root-account-must-be-group | **120+** | Test bootstrap doesn't provision a complete Company/accounts, Mollie Settings, or Item UOM defaults. | MEDIUM — likely a shared `setUp`/fixture/install-hook fix; needs care not to mask real product behaviour. |
| **B4** | **Test/factory schema drift** — `Field 'email_address' does not exist in DocType 'Member'` (16), `Field 'chapter_name'/'name' does not exist in 'Chapter'`, `Membership Type Name is required` (19), `[Membership Termination Request …]: status` (24), `[Membership Type …]: role_profile` (37) | **110+** | Tests/factories use stale field names or omit now-mandatory fields after schema changes (cf. the `Calculator`-mode removal pattern). | LOW–MEDIUM — mechanical, per-site; verify each field against current DocType JSON. |
| **B5** | **Legacy `contribution_mode = "Calculator"`** — `Contribution Mode cannot be "Calculator". It should be one of "Fixed", "Income-Based", "Flexible"` | 21 | Mode removed 2026-02-06 in `160d0929`; ~19 test files + `tests/utils/base.py:create_test_dues_schedule` still set it. | **LOW** — mechanical `Calculator → Income-Based` (confirmed mapping). A few sites *assert* `=="Calculator"` (testing removed behaviour) and need judgement, not a blind replace. **Good first PR.** |
| **B6** | **Product/validation + real bugs** — `IBAN is required for SEPA Direct Debit` (19), `Member … does not have an active membership` (35), `Failed to create user: 'bool' object has no attribute 'message'` (14) | 70+ | Mix of test-setup ordering and at least one **real product bug** (`'bool' object has no attribute 'message'`). | MEDIUM — triage individually; the `'bool'.message` one is a genuine bug worth its own fix. |
| **B7** | **Bare assertions** — `AssertionError: False is not true` (40), `unexpectedly None` (17), `0 != N` | 80+ | Heterogeneous; many are downstream of B1–B4 (setUp produced wrong/empty state). | Re-measure **after** B1–B4 land — most should evaporate. |

**Leverage ordering:** B1 ≫ B3 ≈ B2 ≈ B4 > B7 > B6 > B5. **Risk ordering (safest first):** B5 < B4 < B3 < B2 < B6 < B1.

---

## 4. Bucket B1 (isolation) — the crux, design notes

B1 is the largest bucket **and** the reason PR #113 is net-negative (fixing B2's template error unblocks setUps that then collide on B1). It must be solved before B2-style "unblocking" fixes pay off.

Options considered:

- **(a) Uniquify `last_name` in the factories** — append the run-unique member sequence even when `last_name` is passed explicitly. *Blocker:* 47 `assertEqual(member.last_name, "…")` sites. **Rejected as-is.**
- **(b) Make production customer creation reuse same-name customers** — *Rejected:* wrong in production (distinct people may share a name; must not share a Customer).
- **(c) Make the auto-created Customer name robustly unique** — e.g. ensure ERPNext's duplicate-name suffixing actually applies (the `IntegrityError` on the Customer **PK** suggests the name isn't being de-duplicated as ERPNext normally would; investigate `cust_master_name` / how `customer.insert()` names the PK at `application_payments.py:168-178`). If this is a genuine non-idempotency, fixing it helps **both** test and production with **no test-file churn**. **Most promising — investigate first.**
- **(d) Per-test-file uniqueness** — fix the ~10 files passing fixed names to use unique suffixes. *Viable but wide; only the files that don't assert the name.*

**Recommended B1 approach:** investigate (c) first (one well-scoped production-robustness fix, CI-verified). If (c) is not the cause, fall back to (a) **scoped to only the email/customer-name derivation** (leave `last_name` field intact for assertions — derive the Customer name from `full_name + member_id` or similar so the PK is unique while the displayed name fields are unchanged), which sidesteps the 47 assertions.

---

## 5. PR #113 status (open) — hold, don't merge

`fix/test-factory-membership-type-template` (commit `2eb9bd90`): removes the hardcoded `Monthly Membership Template` link from `create_test_membership_type` (the B2 slice). Reviewer-approved (senior + skeptical), correct in isolation, eliminates the 55-occurrence `Monthly Membership Template` error and fixes **16–21** tests in shard 3.

**But the same-base union diff shows +323 NEW / −21 fixed (net +302), concentrated in shard 2** — the fix unblocks setUps that then cascade into **B1**. A confirmation re-run (`gh run rerun 26622975573`) is in flight to prove the shard-2 jump is deterministic (develop shard 2 is rock-stable, so it almost certainly is).

**Decision:** keep PR #113 open but **do not merge** until **B1 lands**. After B1, re-run #113's diff — it should flip to net-positive (clean) and merge then. It is a correct prerequisite-blocked fix, not a bad one.

---

## 6. Recommended sequence

Each step = one PR, CI-verified via the §2.1 union recipe (`NEW ≈ 0`, `FIXED > 0`) against a same-base develop run.

1. **B5 (Calculator → Income-Based)** — safest, mechanical, builds the verify-loop muscle. Handle the `assert =="Calculator"` sites by updating them to the new value or deleting tests of removed behaviour.
2. **B1 (isolation)** — investigate option (c); if not viable, option (a)-scoped. Highest leverage; unblocks everything downstream and PR #113.
3. **Re-measure** — land PR #113 now that B1 removes the cascade; confirm net-positive.
4. **B3 (environment config)** — shared `setUp`/fixture for Company/accounts/Mollie/UOM.
5. **B4 (schema drift)** — mechanical field corrections, verified against DocType JSON.
6. **B2 remainder (`Monthly Standard`/`Regular`/`Daglid`)** — seed fixture or per-test creation.
7. **B6 (product bugs)** — fix `'bool'.message`; triage IBAN/active-membership.
8. **B7** — re-measure; fix the residue.

Re-baseline the bucket table (§3) after every 2–3 PRs — counts shift as cascades clear.

---

## 7. Gotchas / canonical references

- **SKIP list** (pushing while suite is red): `SKIP=jest-testing,test-quality-enforcer,frappe-hooks-validator,whitelist-type-safety,pytest-coverage-critical,make-test-quick`. The last two are the DB-touching test hooks that lock-timeout while any full run holds the DB; `frappe-hooks-validator` has an intermittent `BlockingIOError` — retry once.
- **Branch protection** blocks force-push to `develop` (feature branches are fine).
- **Subagents must not run git** writes; commit from the main conversation.
- **Double-review** every non-trivial PR (senior + skeptical in parallel).
- Log-parse format: failures print as `<ANSI>FAIL<ANSI> test_name (full.dotted.path)`; strip ANSI with `sed -E 's/\x1b\[[0-9;]*m//g'`.

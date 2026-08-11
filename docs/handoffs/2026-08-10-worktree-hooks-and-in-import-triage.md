# Handoff — 2026-08-10 (second session of the day)

## Worktree hooks fixed, and the in_import harness branch finally has CI

Follow-on from `2026-08-10-shard-repartition-landmines-and-pr-hygiene.md`, which was
merged as #278 at the start of this session.

---

## 0. State at handoff

**Merged:** #278 (`3095b724`, the previous handoff), #279 (`7bb0c41b`, worktree hooks).

**Open:**

| PR | Branch | State |
|---|---|---|
| #281 | `fix/audit-log-severity-normalisation` | 3 commits, CI running, **ready to review** |
| #280 | `test/harness-production-fidelity` | 8 commits, **draft**, triage in progress |

`develop` is at `7bb0c41b`. Both open branches have develop merged in, so neither is stale.

The bench default site is now **test_site_1** (`bench use test_site_1`), and both CLAUDE.md
files were updated to match — see §4, this changes what a bare `bench` command does.

---

## 1. #273 is closed: ten hooks, not seven, and `npx` was the sting in the tail

The issue reported seven pre-commit/pre-push hooks failing inside a git worktree. The real
number is **ten**. The extra three only fire when the commit touches JavaScript, which is
why the first pass looked complete — the fix's own commits touched no `.js`.

Four causes, all the same shape: **a tool inferring a path from the checkout's own name or
depth.**

1. **`node_modules` is gitignored**, so it is absent from every worktree. Eight npm-based
   hooks died on `sh: 1: jest: not found`.
2. **`import_path_validator`** assumed the app sits exactly two levels below the bench, and
   resolved first-party imports against the *installed* app rather than the checkout.
3. **`frappe_hooks_validator` and `hooks_parser`** took the app's Python *package* name from
   the checkout *directory* name, so a worktree looked for `<checkout>/<checkout>/hooks.py`.
4. **`make test-quick`** made the same fixed-depth assumption about the bench.

### The trap worth remembering: `npx` ignores `PATH`

Putting the main checkout's `node_modules/.bin` on `PATH` fixes `jest`. It does **not** fix
`npx eslint`. npx resolves a package from the *current directory's* `node_modules` and
ignores `PATH` entirely — so in a worktree it silently fell through to `~/.npm/_npx`,
downloading **eslint 10.8.1** and running it against `eslint-plugin-vue` loaded from this
repo's install. Result: `context.getSourceCode is not a function`.

**This is not worktree-specific.** In the main checkout `npx eslint` only ever found the
pinned **v9.37.0** because `node_modules` happened to be cwd-local. With it absent, npx
downloads a different major and lints against it, silently. The hooks now invoke the
binaries directly via `scripts/testing/with-node-modules.sh`.

### Two things found only because the fix made the tools run

- **`hooks_parser` only *warns* when it finds no hooks.** So `ast-field-analyzer` had been
  running hook-blind in every worktree instead of failing, while its banner still read
  "Enhanced Version with Hook File Support". A validator that degrades silently is worse
  than one that fails.
- **`frappe_hooks_validator` did `import importlib` but used `importlib.util`.** That works
  under the system interpreter, where something else on the default path imports it first,
  and **not under the bench's `env/bin/python`** — which is what CI and the tests use. The
  whole hooks-parsing path was dead there. Caught by the new tests on CI, not locally.

### `make test-quick` would have lied, not just failed

Once the bench is found by walking up, `bench` runs the app it has **installed** —
`verenigingen.pth` points at `apps/verenigingen`, the main checkout — **not** the worktree.
So a worktree run reports on develop's code while appearing to test the branch. It now
skips with a reason, and carries `verbose: true`, because pre-commit hides the stdout of
*passing* hooks and the skip would otherwise read as a successful test run.

**Verification that counts:** the merge commit on #280 was made and pushed from a worktree
with **no `SKIP=` at all** — the entire pre-commit and pre-push suite ran and passed.

---

## 2. #280: the in_import harness branch, 180 commits stale, now measured

The branch removes `frappe.flags.in_import = True` from `EnhancedTestCase.setUp` in favour
of raising `throttle_user_limit`. It had **no PR and no CI since 2026-07-31**.

**The predicted conflict did not materialise.** #271's `DRAIN_EXEMPT_DOCTYPES` /
`_drain_captured_inserts` and this branch's `setUp` change sit in different regions of
`enhanced_test_factory.py`. Verified semantically, not by exit code: develop still has
`frappe.flags.in_import = True` at line 1973, the merged branch has no live assignment
anywhere (only comments), and #271's additions are intact.

### The real failure count is 168, not 236

Down from the 236 recorded in July — develop fixed some of the underlying bugs in the
intervening commits. Anchor on `^\s*(FAIL|ERROR)\s+test_\S+ \(` with ANSI stripped; the
bogus "169" in the original handoff came from grepping without stripping colour codes.

**168 failures are not 168 problems.** By terminal exception, in units of *tests*:

| Cluster | Tests | Status |
|---|---|---|
| `Contribution Mode cannot be "Tier"` | 42 | **fixed** (`552d06b3`) |
| `Due Date cannot be before Posting Date` | 30 | open — next up |
| `Could not find Member: Test Member` | 9 | open |
| `Permissions Level cannot be "Membership"` | 8 | **fixed** (`b6ddd30d`) |
| `Contribution Mode cannot be "Custom"` | 8 | open |
| `Campaign Type cannot be "General"` | 6 | open |
| `Status cannot be "Pending"` | 5 | open |
| `Payment Type cannot be "One-off"` | 5 | open |
| assorted `AssertionError` + long tail | ~55 | open |

**50 of 168 addressed.** The remaining Select clusters are likely the same shape and should
go quickly; the `AssertionError` tail is where the real production bugs will be.

### Method that worked, for whoever picks this up

Parse each failure block down to its *terminal exception* and group by that — grouping by
log line count is misleading (the `"Tier"` cluster is 42 tests but 294 log lines). The
parser lives in this session's scratchpad approach: split on
`^\s*(FAIL|ERROR)\s+(test_\S+)\s+\((.+)\)$`, take the last line matching
`^([\w.]+(?:Error|Exception)):`.

Then, for each cluster, **find who writes the offending value and check production vs test
before touching anything.** Both clusters resolved so far turned out to be test fixtures
writing values production cannot produce — but that was established by grep, not assumed.

### Two clusters, two different lessons

**`permissions_level = "Membership"` (8).** `Chapter Role` allows `Basic/Financial/Admin`.
The value persisted only because `_validate_selects()` was suppressed — which meant these
tests were reaching a production branch that is **dead in reality**: five sites test
`permissions_level in ("Admin", "Membership")` and every one reduces to `Admin` alone
(`chapter_security.py:79`, `member_management.py:106/127/219`,
`membership_application_review.py:792`). Switched the fixtures to `"Admin"`.
**Deliberately did not remove the dead arm** — `chapter_security.py` already carries a
comment from a previous session saying whether Financial-level board members *should* be
included is an authorization decision, not a bug fix. Worth its own issue.

**`contribution_mode = "Tier"` (42).** A pre-v2_0 Membership Type value, removed when
billing moved to Dues Schedule templates. All 42 traced to three places — the shared default
in `sepa_test_factory.py` (reached by `test_member_utils` via
`enhanced_test_factory.create_test_dues_schedule`), two local defaults in
`test_dues_schedule_repository`, one explicit argument in `test_sepa_batch_processor_logic`.
The factory's comment even asserted `"Valid options: Tier, Calculator, Custom"` — all three
gone. Switched to `"Fixed"`, the field's own default; behaviour-preserving because the only
branch reading the field tests `in ("Income-Based", "Flexible")`, which `"Tier"` also failed.

**Left alone deliberately:** `test_membership_dues_enhanced_features` and
`test_membership_dues_system` also write `"Tier"`, but are already skipped under
`skip_reasons.DUES_SCHEMA_GONE` as written against the removed schema. They need a rewrite,
not a value swap — changing the string would silently un-defer work someone chose to defer.

Measured on test_site_1: `test_member_utils` 70/70 OK (was 17 failing);
`test_dues_schedule_repository` 22 → 2.

### The develop control is cheap and settles attribution

The 2 residual `test_dues_schedule_repository` failures
(`test_cancel_schedule_updates_correct_fields`, `test_pause_schedule_updates_status`)
reproduce **identically on develop with `in_import` still set** — so they are not
harness-caused. Running the same module in the main checkout (no `PYTHONPATH`) is a
2-minute control and should be the first move on any ambiguous failure.

To run a *worktree's* code under bench: `PYTHONPATH=<worktree> bench --site test_site_1
run-tests --module ...`, and verify with `print(module.__file__)` — bench otherwise executes
the main tree regardless of which branch the worktree has checked out.

---

## 3. #281: audit rows were being dropped, silently

Found while triaging #280 but **independent of it** — it reproduces on develop today,
because `VereningingenTestCase` does not set `in_import`.

`SEPAAuditLogger.log_event()` advertises `severity: Union[AuditSeverity, str]` but converted
only the enum branch. `API Audit Log.severity` is a Select of `info|warning|error|critical`,
so a string in any other case produced a rejected value — and the insert sits inside a broad
`except` that logs and continues. **The row was discarded while the caller saw success.**

Two quieter consequences fixed by the same change: `_map_severity_for_sepa()` keys on
lowercase, so `"INFO"` fell through to `"Pending Review"` instead of `"Compliant"`; and the
escalation in `_log_to_file()` compares against `"critical"`/`"error"`/`"warning"`, so an
uppercase severity **skipped the critical alarm entirely** — the same shape as #197.

Normalisation reads `.value` off anything that has one rather than isinstance-checking
`AuditSeverity`, because **there are two `AuditSeverity` enums** —
`utils/security/types.py:141` and `verenigingen_payments/core/compliance/audit_trail.py:54` —
and a member of the second is invisible to an isinstance check against the first.

**CI then found the caller.** `bulk_payment_checker._log_bulk_operation_audit()` set
`severity = "INFO"`/`"WARNING"`, so every audit row it produced was discarded — that is
**#197's missing compliance row, with a confirmed cause**. Its two tests asserted the
uppercase value, i.e. they were *passing on develop for the wrong reason*: the row persisted
only because validation was skipped. Fixed the caller to emit lowercase and corrected the
assertions.

### Still open, and NOT in #281

The same CI run drops audit rows for out-of-vocabulary **`event_type`** values too:
`invalid_member_access`, `api_classification_started`/`_completed`,
`api_classifier_initialized`, four `sepa_*` ones, `test_operation`. `invalid_member_access`
is emitted from `api/membership_application_review.py:46`,
`api/background_approval_api.py:88` and
`services/member/validation/member_duplicate_detection_service.py:447`, each on a failed
lookup of a non-existent Member — **a security event whose audit row never reaches the
database.** Some paths map unknown types to `other`, others do not.

Fixing it means either extending the Select's 28 options or making the map-to-`other`
fallback universal. That is a data-model decision and should not ride along in a
normalisation fix. **Worth its own issue.**

---

## 4. The default site changed — read this before running bench

`sites/currentsite.txt` did not exist, and the Makefile read *only* that file, so `SITE`
always fell through to the hardcoded `veg11.veganisme.org`. **`make test-quick` on pre-push
was running the suite against the live site** regardless of what `bench use` had been told.

This version of bench does not write `currentsite.txt` at all — `bench use` records the
choice as **`default_site` in `sites/common_site_config.json`**. The Makefile now reads
`default_site` first, `currentsite.txt` second for older benches, and `veg11` only as a last
resort.

**The bench default is now `test_site_1`.** A bare `bench <command>` no longer lands on the
live site. Both CLAUDE.md files were updated: the testing commands now name a test site, and
the "Working with Sites" section states the split explicitly. Commands that genuinely mean
the live site (`console`, `mariadb`, `migrate`, backups) still pass `--site
veg11.veganisme.org` explicitly, which matters *more* now that the default has moved.

---

## 5. Working practices worth keeping

- **Read the comment around the code before declaring a bug.** Two candidate "production
  bugs" this session turned out to be documented deliberate decisions
  (`chapter_security.py:79`) or correct against a different doctype (`alert_manager.py`
  writes `LOW/MEDIUM/HIGH/CRITICAL`, which is exactly what System Alert.severity offers —
  I posted that as a finding and had to retract it on #280).
- **A test that fails after a fix is not automatically a regression.** `'info' != 'INFO'`
  meant the fix had started *persisting* a row that used to vanish. The test encoded the bug.
- **Assert the row lands, not that nothing raised.** Every dropped-audit-row bug here was
  invisible precisely because the old behaviour did not raise.
- **Add tests to an existing module rather than a new file** where reasonable — a new test
  file re-partitions all 12 shards (#248).
- **A formatter hook can abort a commit while the tail of the output looks green.** It
  happened once this session ("Stashed changes conflicted with hook auto-fixes... Rolling
  back"). Run `black` first, and always confirm with `git log`.

---

## 6. Suggested next steps

1. **Review and merge #281.** Self-contained, has failing-first tests, closes half of #197.
2. **File two issues** from §2 and §3: the dead `("Admin", "Membership")` arm across five
   sites, and the audit-log `event_type` vocabulary gap.
3. **Continue #280** with the `Due Date cannot be before Posting Date` cluster (30) — likely
   one root cause in the `set_posting_time` territory the branch already partly addresses,
   not 30 separate problems.
4. Older items still open from the previous handoff: **#248** (shard order-dependence, the
   generator of the repartition landmines), **#272** (dead `resolutions` block), **#208**,
   and the paused Dependabot updates.

# 2026-11-01b: the refusal event was rolled back with the refusal

This session (verenigingen-2b, 2026-10-31 into 11-01) started from the 2026-10-31 handoff (PR #1816,
merged here). Two other sessions ran in parallel and shared `dispatch/ledger.md`, the dispatch
queue and the test-site pool: **verenigingen-ed** and **verenigingen-e4** ("aanmeldformulier").

The maintainer's instructions, in order:

1. "handoff is up as PR #1816 < please read", then merge #1816 and resume #1765 Task 4.
2. "general note: push anything that's done testing locally" (now a standing memory).
3. Rulings:
   - #1874: option 1 (request more info on the application).
   - #1860: refuse an unknown chapter.
   - #1855: yes (MijnRood applicants become applications).
   - Staff see all applicant data.
4. "launch 6 more agents to work on open issues".
5. #1775: "close it for now".
6. #1777's import marker: a real provenance field. Then "make it agnostic though, imports from Procurios should also be recordable".
7. "merge when green"; "look into ed's red PRs #1887 and #1893" (ed was already on both; stopped).
8. "generate a handoff when done".

## #1765: application as its own record — Tasks 4-9 done

**Branch:** `feat/1765-application-record`, worktree `~/frappe-bench/worktrees/plan-1765`.
**Ledger:** `.superpowers/sdd/2026-10-30-application-as-record/progress.md` (git-excluded). It holds every
ruling, A to AP, the deferred minors and the commit ranges. **Read it before resuming.**

| Task | State | Commits |
|---|---|---|
| merge develop (#1776) | done (Ruling P: merge, not rebase) | `a91f06802` |
| 4 approval materialises the Member | complete, reviewed, 1 fix round | `cb7778af5`..`0cf0da1c0` |
| 5 rejection touches only the application | complete, reviewed, 1 fix round | `c11f0efdc`..`7d498a1d5` |
| 6 change preview | complete, reviewed, 1 fix round | `cf4937914`..`5f8ba5651` |
| 7 review surfaces read applications | complete, reviewed, 3 fix rounds | `02114597d`..`04fc9d285` |
| 7b(a) request more info (#1874) | complete, reviewed, 1 fix round | `61a5578b9`..`d2023e2c3` |
| 8 status page, template guard, retention | complete, reviewed, 2 fix rounds | `0c7388e7e`..`aaa7bfce7` |
| 9 remove member-keyed writers/endpoints | complete, reviewed, 2 fix rounds (rate-limit rows restored, lost protections restored, refusal events enqueued so they survive the rollback) | `0926f9a84`..`73c260c40` |
| 7b(b) refuse an unknown chapter (#1860) | **not started**: waits on ed's develop helper `_refuse_unknown_chapter` (after #1862) | |

**Remaining before the #1765 PR:**
1. 7b(b): after ed's #1860 PR merges, merge develop and call the shared helper from `approve_application`.
2. Merge develop into the branch. Expected conflicts and carries, all in the ledger:
   - #1797's admin-picks-a-chapter red test via `approve_application`;
   - #1917's `invoice_failed` handling must move onto `approve_application`'s callers (review page, `quick_approve_application`, bulk);
   - `chapter_dashboard.html` conflicts with #1914, which escapes it on develop too;
   - #1930 (board-approver approval creates no dues schedule/invoice/user) is in the shared core, so the branch inherits its fix.
3. Final whole-branch review. Its listed must-fix: for an external `http(s)` File, the purge's disk delete can remove an unrelated `private/files/<basename>`. Then triage every `Task N: minor (deferred)` line in the ledger.
4. Open the PR, which closes #1765, #1740, #1874, #1837, #1915, #1928 and #1859 (check each).

Product rulings made on the maintainer's behalf (each in the ledger, overrulable):
- **AK:** a rejected applicant's status page shows only the "Reason:", not the whole `review_notes`, which also hold internal notes.
- **AO:** a rejection no longer marks the CRM Lead "Do Not Contact".
- **Y:** IBAN masking uses the app's `mask_iban` (country code plus last 4).
- **AH:** request-more-info is recorded as a timeline Comment, not as fields.

## Round of 6 issues (maintainer request) — outcome

| Issue | Outcome | PR |
|---|---|---|
| #1775 | not reproducible through any real flow; closed (maintainer) | none |
| #1777 | integrity check + importer-agnostic provenance (`Member.import_source_type` / `import_source`, set by Mijnrood CSV, Member Import, VIP Import; backfill patch from review_notes) | #1906 |
| #1839 | DocTypeLoader resolves this app from the tree it runs in | #1905 |
| #1873 | per-request seat memo + explicit invalidation; swallows removed | #1910 |
| #1890 | 750+ outputs escaped across 57 templates; context-aware validator (script, `on*=`, quoted attributes, chains, macros) as a hard gate + CI job | #1914 |
| #1773 + #1774 | first invoice period follows the dues schedule; Item read grant via CORE_GRANTS; `invoice_failed` surfaced in every wired caller | #1917 |

All five PRs had their head equal to the reviewed SHA and sat in `dispatch/approved_prs.txt`. See Final state for their CI status.

## Coordinator notes: what this session taught

- **A security event written in the request transaction dies with the refusal.** Frappe rolls back on the PermissionError (`app.py:155-159`), so a `log_security_event` row written beside a refusal never persists. The test passed because it read its own uncommitted row. The "existence oracle" that justified turning alerts off was the same artefact: the test transaction counted its own rows. Fix shape: enqueue the event (not after-commit). Test it by rolling back before counting.
- **A mass escape sweep has an opposite harm.** #1890's first round broke `personal_details` (JSON put through `|e` inside `<script>`), double-escaped the tax receipt, and showed Team descriptions as raw tags. Only rendering through the REAL controllers caught it: 70 renders with `node --check`. A hand-built context test cannot.
- **Removing endpoints removes their protections.** #1765 Task 9's deletion dropped the rate-limit rows, the name sanitising and the security events, and the review had to list "what the old endpoint enforced" to find them. Diff the decorators and guards, not just the callers.
- **A raw purge orphans dependents both ways.** Too little: Comments, Communications, reply attachments. Too much: another document's activity log, a global unsubscribe, Error Log evidence. A same-name decoy of another doctype per table is the test that discriminates.
- **Ledger claims are notes, not locks.** I claimed test_site_3 and the next ledger line re-took it. Later I put a develop-based reviewer on test_site_12 while a #1765 agent used it, and that agent's s12 results were invalid. Re-read the tail and message the peers before each dispatch.
- **The bench's RQ workers run develop against test sites** and share the Redis hooks cache on s1-5 (memory note). Re-confirm a surprising one-off there on a developer_mode site.
- **The "exits early" unittest discover was stdout buffering.** The full log has "Ran N tests … OK" (#1839 review).

## Filed this session (open)

#1836, #1837, #1839, #1855, #1873, #1874, #1890, #1897, #1899, #1900, #1901, #1902, #1903, #1909, #1912, #1915, #1928, #1930 (comment). Several were filed by dispatched agents; each has an established/not-established section.

## Final state

- **#1765 branch:** `feat/1765-application-record` at **`73c260c40`** on origin. Tasks 1-9 and 7b(a) are complete and reviewed; 7b(b), the develop merge and the final review remain (see above). No PR yet.
- **My PRs (all in `dispatch/approved_prs.txt`; head == reviewed SHA; none red at session end).** CI was saturated (80+ queued jobs across sessions). Last counts:
  - #1905 (#1839): 38 pass, 1 pending
  - #1906 (#1777): 54 pass, 1 pending
  - #1910 (#1873): 53 pass, 2 pending
  - #1914 (#1890): 53 pass, 2 pending
  - #1917 (#1773/#1774): 44 pass, 8 pending
  The shared `automerge.sh` (restarted by ed's session) merges them when green. **Nobody is watching them for red now.** A red one stops the shared loop: pull it from `approved_prs.txt` with `sed -i` and ping ed.
- **ed's PRs:** #1887 was fixed by ed (`a2acdb4de`, re-queued). #1893's test fix `c2ce56338` was in independent review. #1862 (#1797) was still in CI, and ed's #1860 work follows it.
- **Merged this session:** #1816 (previous handoff).
- **Sites held:** test_site_5 (the #1765 implementer site; idle, migrated from the branch) and test_site_12 (the #1765 reviewer site; idle, migrated from the branch). Release both in the ledger if not resuming.
- **Worktrees:**
  - `worktrees/plan-1765`: the live #1765 branch. Keep it.
  - `~/agent-worktrees/fix-1773-1774-approval-invoice`, `fix-1777-quit-integrity-check`, `fix-1839-analyzer-worktree-doctypes`, `fix-1873-seat-cache`, `fix-1890-template-escaping`: remove each once its PR merges.
  - `worktrees/issue-1741`, `issue-1782` (from 10-31): removable.
  - `worktrees/handoff-1101b`: this handoff.
- **Agents:** none running.
- **Live tree:** untouched by this session apart from automerge fast-forwards. `ONBOARDING.md` and `email_brand.css` are still untracked/modified (not mine).

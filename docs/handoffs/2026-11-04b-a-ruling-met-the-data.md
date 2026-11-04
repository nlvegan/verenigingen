# 2026-11-04b: a ruling met the data

Session `0104s` (verenigingen, 2026-11-04). It started from `2026-11-03b-two-green-prs-made-develop-red.md`. Every item that note left open had already been resolved by the time this session began:
- #2033 and #2047 were merged;
- develop was green;
- the #1989 worktree was gone.

Sessions 1102b and 1103b shared the bench, the ledger and the test sites.

The maintainer's instructions, in order:
1. Read the handoff.
2. Rulings on #2021-#2024, and update the test sites.
3. Evaluate Malveon, an external "verify the agent's claims" tool. Then file an issue for its weakened-tests idea and put an agent on it.
4. Put 8 agents on open membership-application issues. This explicitly lifted the 2-agent cap for that round.
5. Rulings: #2022 refinement (default the holder on import), and #2023 simplify.
6. Close #1300, #1595, #1870 and #1868.
7. "generate a handoff while we wait".

## The one lesson to carry forward

**A ruling given in the abstract can break a real flow. Check it against real data before building it.**

- #2022's ruling was: "refuse an IBAN change when the account holder is blank".
- The first review found that the CSV/MijnRood import path never sets a holder. On veg11, **138 of 139** Members with an IBAN have none.
- Under a plain refusal, every MijnRood update that changes such a member's IBAN would fail as a whole, losing the name and address changes in the same event too.
- One `SELECT count(*)` turned this into a clear question for the maintainer. The answer was to default the holder on import and refuse elsewhere.
- Ask "who produces the state this rule fires on, and how many rows are in it?" **before** the author builds the rule, not after review.

Two smaller lessons from the same round:

- **Premise checks remove work.** 2 of 8 dispatched issues were stale: #1300 and #1595, both made obsolete by #1765. A third, #2023, proved that develop already did the safe thing. The safety lived in the savepoint rollback; only the message was vague. The reviewer's "SIMPLIFY" turned ~60 lines plus a member preview into a 5-line message fix.
- **A test can be satisfied by an earlier gate.** #2021's rejoin test passed because a permission check refused the caller before the new guard ran. A mutant that moved the guard below the rejoin branch stayed 6/6 green. Call the guarded function directly, or the test proves nothing about the guard. This is the same shape as dispatch README rule 17, applied to refusals.

## Merged / open

| PR | Closes | What | State at writing |
|---|---|---|---|
| #2065 | #1963 | The review page's single-application view: Clear filters and a "Show all" link leave it, and `?application=` is dropped from the URL. Jest tests. | **MERGED** `096fe02b7` |
| #2068 | #1825 | MijnRood: a Failed (still retryable) blocking Account Creation Request is logged, once per event, and reported to staff instead of being skipped silently. | CI running |
| #2071 | #2022 | Refuse an IBAN change with a blank holder (normalised compare). The import path defaults the holder to the full name. | CI running |
| #2072 | #2021 | `request_to_join` / `Chapter.join_chapter` refuse non-Active members. | CI running |
| #2073 | #1962 | The guest full form refuses a disabled Membership Type, identically to an unknown one. The type check now runs before the amount check (an oracle on the custom-fee path), and an `isinstance` guard is pinned by a test. | CI running |
| #2074 | #2023 | The bank-details refusal lists every reason. The dialog title is "Invalid bank details". | CI running |

- Every PR had an author self-review, an independent `skeptical-code-reviewer` pass, and a coordinator delta check of the final round.
- **Before merging**:
  - Rule 24: run the modules of PRs merged since the base. `#2071` and `#2074` both edit `payment_mixin.py`, in different functions, so run each other's IBAN modules on the merged tree.
  - Then `premerge.sh`, then merge pinned to the head.
- The watch list is `dispatch/watch_prs.txt`.

**#2061** (the weakened-tests advisory validator, from the Malveon evaluation) is committed locally as `e751943f7` in `~/agent-worktrees/feat-2061-weakened-test-check` and not pushed. Its independent reviewer had not reported at the time of writing; its first hand-back was the literal text "PLACEHOLDER". On 250 merged PRs the author found **no certain true weakening**:
- 89 "tests removed" findings, mostly rewrites;
- 9 skips, all environment guards;
- 0 constant asserts.

Expect a "noise" verdict. Decide then whether to tighten it or drop it.

## Maintainer rulings (each recorded on its issue and in `dispatch/author_brief_common.md`)

- **#2021:** only Active members may join or move chapters. Refuse at write time.
- **#2024:** no reject action for boards. Closed as not planned.
- **#2022:** refuse a blank-holder IBAN change, **except** on the import path, which defaults the holder to the full name.
- **#2023:** no pre-flight. The existing refusal names the real reason.

## Issues

**Filed:**
- #2061: weakened-tests check.
- #2064: approval activates EVERY Pending Chapter Member row of the member. **Product question:** activate, leave, or remove a Pending row in another chapter? No real writer of that start state was found.
- #2066: `AccountCreationRequest.mark_failed` logs only to `frappe.logger` (the root cause of #1825).
- #2067: a MijnRood changed-member event commits the chapter transfer even when the member update in the same event fails.
- #2069: `ChapterMembershipManager` identifies the member by `Member.email` (a #1853 residual).
- #2070: the confirm step accepts a Membership Type disabled after submit.

**Closed (maintainer):** #1300 and #1595 (stale since #1765); #1870 and #1868 (fixed by `b235c9dfd`); #2024.

**Not dispatched, application-related, still open:** #2055 and #2041. Both overlap the 1102b session's open PR #2042 (#1900).

## Mistakes, worth knowing

- **I migrated all 14 test sites without reading the ledger's claims.** test_site_12 was held by 1102b's #2060 reviewer. All 14 migrated cleanly (76 app patches each), and a note was left in the ledger. Check claims before any bench-wide site operation, not only before a dispatch.
- **Two sessions claimed one site.** I claimed s2 for #2061 at the same time 1103b claimed it for #2043. #2061 needed no site, so I released it. The ledger is append-only, so read the tail immediately before writing a claim.
- **Agents still background their own long runs** despite the brief: the #2061 author's 6.5-minute validator suite, and two `git push` calls past ~180 s. One reviewer's hand-back came back as "PLACEHOLDER" while its job ran. When a report is missing a result line, ask for it; do not infer it.

## Housekeeping

- **Worktrees left** (each removed after its PR merges): `fix-2021-…`, `fix-2022-…`, `fix-2023-…`, `fix-1962-…` and `fix-1825-…` under `~/agent-worktrees/`.
- `feat-2061-weakened-test-check` is still awaiting review. It holds untracked `.hist250.txt` / `.prs*.json` (the PR-history data).
- **Removed:** the worktrees for #1300, #1595 and #1963.
- **Test sites:** all 14 were migrated at ~12:30. This session holds no site claim at the time of writing.

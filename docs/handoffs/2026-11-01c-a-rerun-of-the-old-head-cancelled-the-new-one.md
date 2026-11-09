# 2026-11-01c: a re-run of the old head cancelled the new one

This continues session ed's work, after `2026-11-01-the-admin-tests-hid-the-board-approver.md` (PR #1933). Read that note first. This session (ledger tag `ee`) ran ed's to-do list, then took nine issues through author, independent review, fix rounds and push.

## Lessons

1. **Re-running a superseded CI run of an open PR cancels the current head's run.** Server tests use a per-ref concurrency group. A background `gh run rerun <old run> --failed` from ed's dead session fired after #1913 got a new head and cancelled its whole test matrix (`Generate Test Matrix` CANCELLED, not a code failure). Fix: cancel the old run, force-cancel the stalled head run (`gh api -X POST .../actions/runs/<id>/force-cancel`: a plain cancel left it "queued" behind the runner backlog), then re-run the head's run. Now README rule 23.
2. **`gh issue view <n> --comments` prints ONLY comments, and nothing at all when there are none.** It never shows the body. The brief told authors to run only that, so two authors (#1898, #1902) worked without the issue text. Both briefs and README rule 7 now say to run both forms.
3. **A guard-shaped fix keeps producing opposite harms in review.** #1911's no-read gate refused admins' unknown names; #1909's membership-aware rule followed the Type while the old schedule still billed (see #1938); #1831's button flag mirrored only half the endpoint's gate. Each was caught by asking "what legitimate caller or state does this now get wrong?"

## Done this session

- **ed's to-do:** the #1853/#1894 rulings were already on the issues (comments 2026-10-31 23:53Z). They are now in `dispatch/author_brief_common.md`, together with the least-privileged-caller rule. veg11 was migrated at bc68a0852 (exit 0).
- **#1913** shard 1 was a REAL failure: the `@handle_api_error` census still pinned 52 endpoints after the PR deleted one. Re-pinned to 51 with an `assertNotIn` control (710685320), independently reviewed and pushed. Its CI was then cancelled by lesson 1, and a re-run of the head is in progress.
- **#1887** shard 8: infra (apt mirror). Pulled from the queue, and a re-run is set to fire when the run completes.
- **Concurrency cap is now 2** (user, 2026-11-01). README updated.

| Issue | PR | head | notes |
|---|---|---|---|
| #1898 ING savepoint 1064 | #1942 | bdd3bfffd | shared `safe_savepoint_name`; one 5-line import conflict with #1927 |
| #1909 coverage report frequency | #1943 | 4a5cb32b2 | rule (a)/(b)/(c); (b) reflects #1938's current behaviour |
| #1902 volunteer lookup cache | #1944 | b1224e3bd | per-request memo; fold into #1910's `_request_memo` later |
| #1894 chapter transfer | #1946 | 407cfd77c | DELETE branch: the staff move already tells both boards |
| #1911 suspension preview scope | #1948 | 284d3a22c | unknown = forbidden for no-read callers; admins keep DOES_NOT_EXIST |
| #1853 join_chapter requires link | #1949 | 7f42759cf | per ruling |
| #1831 board-profile button | #1951 | ea8b23afa | `__onload` flag mirrors tier + `is_profile_admin` |
| #1899 JS validator path | #1952 | 771744ac2 | advisory scope; the rest is in #1950 |
| #1922 REST board row sync | #1954 | 1cf733940 | **stacked on #1893**; queue only after #1893 merges |

**Filed:** #1934, #1935, #1936 (needs a product decision: should the self-service gate be `Member.user` only?), #1937, #1938, #1939, #1945, #1947, #1950, #1953.

## State at hand-off

- **Queue** (`approved_prs.txt`): 1917 1893 1923 1862 1941 1942 1943 1944 1946 1948 1949 1951 1952, shared with other sessions. `automerge.sh` was restarted by ee.
- **Pending queue additions** come from a background watcher in ee's session (it dies with the session). If it is dead, do these by hand:
  - #1954 once #1893 is MERGED and its head is still 1cf733940.
  - #1932 once #1862 is MERGED.
  - #1913 once all its checks are green at head 710685320.
  - #1887 once green.
- **Not done:** #1881. The user did not approve a re-run, but ed's leftover job re-ran it anyway (run 41229549241 attempt 2). It is NOT queued.
- **veg11:** migrate again once the queue drains.
- **Test sites:** test_site_9 holds leaked rows from #1922 review teardowns (test data only).

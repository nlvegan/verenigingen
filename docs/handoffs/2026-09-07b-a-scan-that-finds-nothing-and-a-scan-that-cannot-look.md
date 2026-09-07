# 2026-09-07b — a scan that finds nothing and a scan that cannot look

**State at handoff:** `develop` at `6e6b3c7da`, CI running. **36 PRs merged**, **47 issues
filed** (19 closed, 28 open), **zero PRs open**. Code Validation was green on the last
completed run; the new Critical Operation Rule Orphan Guard passed its first real
push-event exercise.

The session started with one instruction: *"develop's Code Validation has been red for four
pushes, and #998 fixes it in one file."* It was red because `--fail-on-shrink` is push-only,
so no PR event had ever run the step that was failing.

That turned out to be the theme of the whole day.

---

## The through-line

**A scan that finds nothing and a scan that cannot look produce identical output.** Nearly
every real defect found today was an instrument that reported success without having
examined anything:

| what reported success | what it had actually done |
|---|---|
| `test_public_api_guest_access.py` (#1027) | scanned **0 files** — hardcoded `/home/frappe/...`, wrong on every machine including CI |
| `test_public_api_has_allow_guest` (#1046) | could not see **34 of 35** real endpoints — matched one decorator order |
| 5 scripts under `scripts/` (#1036) | one returned a **silent 0-count**; four could not run at all, failing five different ways |
| both API security validators (#1069) | never scanned **121** dispatch-reachable whitelisted functions |
| `duplicate_helper_validator --report` (#1008/#1022) | printed a truncated directory list *instead of* the near-identical pair it exists to surface |
| 35 `@shared_fixture` decorations (#1073) | **9 were no-ops** — tests green, fixture gone from the database |
| PR #1078's own refactor | printed `✅ All API endpoints pass` and **exited 0** having found no scan root |

The last one is the sharpest: a PR fixing this class reintroduced it, in a security gate,
and only a review caught it.

**The operational consequence:** a green result from any gate is worthless until you know
what it looked at. Every useful finding today came from *planting something* — an unguarded
endpoint, a violation in the other decorator order, a synthetic drift entry, a fresh
competing-cleanup registration — and never from reading a diff.

---

## What the review layer caught before merge

Reviews ran on every PR. They were not ceremony:

- **3 blocking defects**: a bare `frappe.db.commit()` reddening a hard gate (#1021); a
  measured 30–400× timing oracle plus a rate-limit bucket shared by every anonymous visitor
  (#1028); the fail-open regression above (#1078).
- **A money bug in new code**: PR #1061's `_resolve_reference_amount` returned `grand_total`
  when `outstanding_amount <= 0`, so a **settled invoice re-charged in full** — fail-open,
  with the largest possible value, contradicting the function's own docstring.
- **4 tests that passed with their fix removed** — two on #1028 (this bench has gateway
  credentials CI lacks), #1043's file-count floor, #1059's substring assertion.
- **5 false claims**, including a *fabricated corroboration*: PR #1038 said "9 found,
  matching #1021's own count" when #1021 states no count at all.

**The `@shared_fixture` finding is the one to carry forward.** `@shared_fixture` suspends
only the **captured-insert** drain. `_drain_tracked_documents` runs *first* and never
consults the suspend flag, and `addCleanup` / a bespoke `tearDown()` are unconditional. So a
helper that also registers its row with one of those has a decoration that does **nothing** —
28 tests green while the "shared" rows vanish. Three separate rounds under-counted this
before an AST walk closed it (#1073), and its remaining limit is #1086.

---

## Corrections to my own work — read these before trusting anything above

I got things wrong and they are recorded on the issues, but they belong here too:

1. **#1068's census was mine and was wrong.** I claimed 13 un-wired test files; 5 were
   already covered by a wildcard step added three weeks earlier (`89a6f6cff`). My grep
   searched for each *filename* and could not see a `-p 'test_*.py'` pattern. Real answer: 8.
   The instrument was blind to the shape it did not expect — the same failure the issue was
   about.
2. **I diagnosed #1082's CI red as "the job installs no frappe."** Wrong. The agent
   reproduced with and without frappe installed: the real cause is **checkout topology**, six
   tests needing frappe/erpnext/hrms/payments as *sibling apps*. The error string listed
   several causes and I picked one instead of discriminating.
3. **I reported a single-sample negative about `scripts/`.** `create_sepa_indexes` carries
   `@frappe.whitelist` and is *not* registered, so I said the hypothesis was unsupported.
   Widening to 40 gave 40/40 registered; the real figure is **121 of 123**. One sample
   settles nothing in either direction.
4. **`gh run watch --exit-status` returned 0 for a run whose jobs were CANCELLED.** Three
   develop runs were cancelled by rapid successive merges. I nearly reported the new orphan
   gate as passing its first push exercise when it had not run. Poll until
   `status == completed`, then read `conclusion` and the job list.
5. **My own advice caused the failure it was meant to prevent.** I told agents to foreground
   pushes with `timeout 900`. The harness's Bash-tool timeout defaults to **120s** and bounds
   the call regardless, so the push was killed at two minutes — which *looks like a hang* and
   is exactly what pushes an agent toward backgrounding it. Set the **tool's** `timeout`
   parameter (900000), not a shell-level one.
6. **Backticks inside a double-quoted bash string got command-substituted**, silently
   deleting five identifiers from a posted issue comment. Every issue body today used a
   heredoc file for this reason; I shortcut it once for a comment and it bit.

---

## The standing-instruction change

`frappe-bench/CLAUDE.md` gained **"A dispatched agent reviews its OWN work BEFORE it
pushes."**

This rule already existed in memory in two places and I inverted it the moment I delegated:
all 13 initial briefs said *push, open a PR, then stop*, with review afterwards. Diagnosed by
grep, not introspection:

- it lived **only** in memory — zero hits for `skeptical|code-review|review before` in either
  CLAUDE.md;
- both memory files describe the agent as the **reviewer**, never the **implementer**, so the
  delegated case matched nothing;
- it was in my loaded context, so truncation was not the cause.

**The generalisable part:** the rule was phrased *"before opening a PR"*, which keys it to a
surface event. Every failure has been a situation that did not look like that event — branch
mechanics (instance 4), delegation (instance 5). It is now keyed to a question that cannot be
dodged by rephrasing: **is code about to become visible to anyone else?**

---

## The highest-value open issues

**Live defects:**
- **#1084** — `populate_coverage_dates`: bare `@frappe.whitelist()`, any authenticated user,
  rewrites coverage dates on **50 Sales Invoices** via `frappe.db.set_value` (bypasses
  permission checks) then commits. Coverage dates are the ledger of which running period an
  invoice discharges, not decoration.
- **#1074** — **66 endpoints declare `allow_guest` and are refused at runtime.** The adapter
  re-syncs `frappe.whitelisted` but never `frappe.guest_methods`. ⚠️ **The obvious fix
  exposes all 66 at once**, including `apply_optimizations` and `sepa_security_health_check`.
  The desync is currently an accidental safety net. Separate the two populations first.
- **#1051/#1052/#1053/#1055** — four guest-reachable disclosures. #1055 is worst: a
  `# SECURITY: prevents IDOR` comment on a check the app's own primary Mollie flow walks past
  by omitting an optional parameter.

**Gates that do not run:**
- **#1083** — neither security validator's `scripts/` scan runs in CI *at all* (zero workflow
  references). #1078 made them correct; nothing executes them.
- **#1042** — two ratchets are pre-commit-only. **#1023**, **#1079**, **#1080** similar.
- **#1044** — both duplication gates hardcode `SCAN_ROOT=verenigingen`; 320 files unscanned.

**Backlogs:** #1075 (90 of 99 baselined security findings unexamined), #1070 (151 unaudited
`@shared_fixture` decorations), #1026's remainder.

---

## Traps worth knowing

- **`scripts/` is live code**: a real importable package, **121** whitelisted functions, every
  ratchet, 320 files. Three validators were found hardcoding a `verenigingen` root today —
  and `log_error_arg_order_validator.py` already used both roots, so the correct shape was
  in-tree the whole time and nobody copied it.
- **`--fail-on-shrink` is push-only.** A PR's green checks say nothing about it. Prove such
  changes locally, the way the push event runs them, with a clean-tree control.
- **`gh` was 2.45.0**, which is why `--comments`, `--json` and `run view --log` had "failed"
  for three weeks. Now **2.100.0** in `~/.local/bin/gh`. It refuses escape sequences without
  `--allow-escape-sequences` — a log fetch returns ~99 bytes and exit 0.
- **Mutate toward the property, not away from the feature.** Deleting a feature reddens
  almost any test touching it. #1059's author mutation-verified a test that was blind to two
  distinct wrong caps.
- **`assertIn(value, whole_output)`** passes when the value appears in the very summary line
  that proves the bug.
- CI infra failures are real: an unreachable Ubuntu mirror reddened two shards. The
  workflow's own guard says so explicitly — read it before bisecting.

---

## If you do one thing

Work **#1074** — but read the warning first. It is the only open item where the naive fix
converts a latent functional bug into a live security incident.

https://claude.ai/code/session_01TS8PzQDJZXjpgmtzhVJo7K

# Handoff — ESLint pre-commit hook + lint backlog (2026-06-12, session 3)

> ## ✅ DONE in session 4 (2026-06-12) — commits `2a981445..1b92dc86` on `develop` (NOT pushed)
> Foppe chose **check-only hook** + **batched-by-directory sweep**.
> - **Task A done** (`8b35710c`): eslint pre-commit hook → check-only, `--`
>   sentinel + dropped masking echo. Verified: exit code propagates, only the
>   passed file is linted (no whole-tree scan).
> - **Task B done**: backlog **5504 → 1336** (686 errors / 650 warnings).
>   - 6 `style(js)` batches (`2a981445..d1040a2d`) = `eslint --fix` per directory
>     (public/js, doctype, mijnrood_sync, pages+reports, payments+eboekhouden,
>     tests/utils). Coverage gate (674) re-verified green after public/js batch.
>   - `b41914db`: registered app globals (`unwrapOperationResult`,
>     `getErrorMessage`, `moment`, `cur_page`) + extended test-globals override to
>     `verenigingen/tests/**` → **no-undef 315 → 0** (all were config gaps).
>   - `1b92dc86`: high-signal production fixes — eqeqeq ×8 (report formatters),
>     no-empty/dead-code (member.js), no-case-declarations (CommunicationManager),
>     no-useless-escape (ChapterConfig regex), no-var (mijnrood_sync_event),
>     prefer-const (membership_application).
>
> **Residual 1336 (no CI gate on it; only the check-only pre-commit hook on
> staged files):**
> - `no-mixed-spaces-and-tabs` **573** — pure whitespace, **no ESLint fixer**.
>   Tried strip-spaces-before-tab + `eslint --fix`: production files clean up but
>   the `indent` fixer oscillates/reverts on the big `tests/setup/*` files
>   (api-contract-simple 285, api-contract-testing 69, controller-loader 51), so
>   it cleared only ~11 net — **reverted**. Needs a **dedicated holistic reindent
>   pass** (Prettier `useTabs` / editorconfig retab) reviewed on its own, NOT
>   piecemeal through eslint --fix. Bulk is rarely-edited test scaffolding.
> - `no-unused-vars` 307 / `no-console` 261 / `no-redeclare` 115 — almost all
>   **warnings** in public/js & tests (non-blocking). no-unused-vars needs
>   per-case review (some are intentional API shapes); no-console mostly tolerable.
> - Tail: radix 22, max-len 20, id-match 11, no-shadow 9, + 5 test-file findings
>   (no-eval/no-global-assign/no-case-declarations/no-useless-escape in test
>   scaffolding — leave or `// eslint-disable` per-case).
>
> ### Error-bucket follow-up (same session 4) — commits `12c28df5..27cd3d5b`
> Drove the **error** count 686 → **584** (every remaining error is now the
> `no-mixed` config conflict below; all other error buckets = 0). Coverage gate
> (674) green throughout.
> - `12c28df5` radix ×9 (base-10 parseInt) + id-match ×11 (config: allow
>   `_camelCase` privates and `$snake_case` jQuery vars).
> - `5b066f5e` no-shadow ×8 (rename inner frappe.call `r`→`resp`, `filters`→
>   `report_filters`, test `frm`→`testFrm`) + 4 test one-offs (no-useless-escape,
>   no-eval disable, no-global-assign → `window.cur_frm`).
> - `d73233f1` no-unused-vars config: ignore Frappe/jQuery framework signature
>   args (frm/cdt/cdn/doc/df/field/listview/page/xhr/status) + caught errors.
>   Cleared 41.
> - `7b549999` **real bug**: vip-import `show_completion_message` built the
>   import summary but never displayed it → added `frappe.msgprint`.
> - `27cd3d5b` removed dead vars + 5 dead member.js functions (~170 LOC, params
>   already `_frm`-parked, 0 refs); prefixed unused params; annotated onclick=
>   handlers (retry/queue/cancel/fix_single/fix_all) ESLint can't see; TODO-flagged
>   2 unwired-but-coherent features (`generate_anbi_report`, `format_processed`)
>   for a product call.
>
> **`no-mixed-spaces-and-tabs` (584) is the only remaining error bucket and is an
> ESLint rule conflict, NOT a whitespace bug.** Proven: the active
> `indent: ["error","tab"]` rule's own `--fix` *emits* `<spaces>\t` indentation for
> deeply-nested object literals / multi-line ternaries (e.g. tests/setup fixtures,
> report formatters) and considers it correct (0 `indent` errors), while
> `no-mixed-spaces-and-tabs` flags the same lines. Retab + `--fix` converges back to
> the mix (diff -w empty). **Needs a policy decision** — (A) disable the redundant
> `no-mixed-spaces-and-tabs` (the `indent` rule already owns indentation; one-line,
> clears all 584), (B) migrate formatting to Prettier + `eslint-config-prettier`
> (large diff), (C) restructure the offending constructs, or (D) leave it (no CI
> gate; check-only hook flags only staged files).
>
> **Not pushed.** Push needs `SKIP=whitelist-type-safety,test-quality-enforcer,import-path-validator`
> and (for JS, until the backlog clears) `--no-verify` / the check-only hook will
> fail on files that still carry pre-existing errors (notably the mixed-tab files).
>
> ---
> ### Original handoff (session 3) below — for context.

Two related follow-ups left after migrating ESLint to flat config this session.
**Both need a Foppe policy call before doing the work** (auto-fix vs check-only).
Everything below is on `develop`; nothing here is started yet.

## What already landed this session (context)

Pushed to `develop` (`705cff47..a926de6e`), **CI green incl. the previously
false-red API Security Audit**:

| Commit | What |
|--------|------|
| `f317a7cc` | fix(security): unbreak the API Security Audit CI gate (added `@self_service_api`/`@api_security_framework` to the audit's decorator list; gave the 4 procurios CSV-import endpoints explicit `@critical_api(ADMIN)`) |
| `93163a3d` | build(eslint): **migrate to flat config** (`.eslintrc.js`+`.eslintignore` → `eslint.config.js`); this is what made `npm run lint` work again — and what surfaced both problems below |
| `a926de6e` | test(js): delete copy-based `validation-service.test.js`; port its cases to the real-import test |

(Earlier same-day, separate session: `2dfbe66f` scratch-script delete, `3d72c9d0`
ajv ReDoS, `705cff47` JS coverage ratchet 7.6%→96.5%.)

---

## Task A — fix the pre-commit ESLint hook mechanics (BUGGY, currently dangerous)

**File:** `.pre-commit-config.yaml:144-150`, hook `id: eslint`, `stages: [pre-commit]`.
Current entry:

```yaml
entry: bash -c 'echo "Running ESLint on JavaScript files..."; npx eslint --fix --max-warnings=1000 "$@"; echo "✅ ESLint completed (auto-fixed issues where possible)"'
```

While the ESLint config was broken (pre-`93163a3d`) this hook was a silent no-op
(`eslint` exited 2 immediately). **Now that lint works it actively reformats
files on every JS commit**, and it has two bugs:

1. **`$0` consumption / whole-tree fix.** pre-commit appends staged filenames as
   args. In `bash -c 'script' FILE1 FILE2`, `FILE1` becomes `$0`, so `"$@"` =
   `FILE2…` — the **first** staged file is dropped. When only one JS file is
   staged, `"$@"` is **empty** and `eslint --fix` runs against the **whole tree**.
   (This session it `--fix`-churned **107 committed files** as a side effect of an
   item-3 amend; I reverted with `git checkout HEAD -- $(git diff --name-only)`
   and finished the commit with `--no-verify`. Nothing leaked into the commits.)
2. **Masked exit code.** The trailing `echo "✅…"` is the last command in the
   `bash -c`, so the hook **always exits 0** regardless of ESLint. Combined with
   `--fix`, that means fix edits are written to the working tree but the commit
   "passes" anyway, leaving them **unstaged and silently uncommitted**.

**The mechanical fix** (independent of the policy question below):

```yaml
# add a `--` sentinel so $0='--' and "$@" = the real staged files;
# drop the masking trailing echo so the hook's exit code is ESLint's.
entry: bash -c 'npx eslint --fix --max-warnings=1000 "$@"' --
```

**Foppe decision needed — auto-fix or check-only?**
- **check-only** (recommended until the backlog is dealt with): drop `--fix`, so the
  hook *reports* problems on staged files and fails the commit; the dev fixes them.
  Avoids piecemeal reformatting churn.
- **scoped auto-fix**: keep `--fix` but correctly limited to staged files (the `--`
  fix above does that). Note: a `--fix` pre-commit hook that modifies files should
  *fail* the commit so the dev re-stages — which the `echo` removal restores.

Either way, **with the current ~5500-problem backlog (below), a fresh JS commit will
trip the hook**. Until Task A lands, commit JS with `--no-verify` (as I did).

---

## Task B — the lint backlog (~5,500 problems)

`npm run lint` now runs and reports (whole app):

```
✖ 5504 problems (4775 errors, 729 warnings)
  3775 errors + 77 warnings auto-fixable with --fix
```

Rule histogram (top):

| Rule | Count | Auto-fixable? | Notes |
|------|------:|---------------|-------|
| `indent` | 1843 | ✅ | tabs |
| `quotes` | 1095 | ✅ | → single |
| `no-mixed-spaces-and-tabs` | 570 | ✅ | |
| `no-undef` | 315 | ❌ manual | missing globals / real bugs — TRIAGE |
| `no-unused-vars` | 308 | ❌ manual | dead code — review, don't blind-delete |
| `no-console` | 261 | ❌ (warn in many paths) | mostly tolerable |
| `comma-dangle` | 193 | ✅ | |
| `object-shorthand` | 158 | ✅ | code change, not whitespace |
| `no-redeclare` | 115 | ❌ manual | possible real bugs |
| `prefer-arrow-callback`/`prefer-template`/`no-var`/`quote-props`/`curly`/… | ~500 | ✅ | |

So roughly **~3,850 auto-fixable** (overwhelmingly formatting) and **~1,650 needing
human judgement** (dominated by `no-undef` 315, `no-unused-vars` 308, `no-redeclare`
115 — the rest is `no-console` noise).

**Recommended approach (do NOT one-shot `--fix` the whole tree into one commit):**
1. **Dedicated, reviewed auto-fix sweep** — `npm run lint:fix`, committed on its own
   as `style(js): apply eslint --fix across the app` (or in a few batches by
   directory: `public/js`, `verenigingen/**/doctype`, `cypress/`, reports/pages).
   Keep it greppable and revertable. Re-run the **jest coverage gate (674 tests)**
   after — `--fix` touches the instrumented modules' style but must not change
   behaviour. Confirm `npm run test:coverage` stays green.
2. **Triage the manual remainder** after the sweep shrinks it: `no-undef` first
   (each is either a missing entry in `eslint.config.js` `globals`/`frappeGlobals`
   or a genuine undefined-reference bug), then `no-unused-vars` (review before
   deleting — some are intentional API shapes), then `no-redeclare`.
3. Only after the backlog is manageable, flip Task A's hook to the desired mode.

**Nothing currently gates on this backlog** — CI's only ESLint job is
`deploy-to-press.yml.disabled` (`npm run lint || true`). So it's purely a
code-health effort; no red CI pressure.

---

## Safety notes / gotchas for the next session

- **No committed lockfile.** `npm install` recreates `package-lock.json` and
  rewrites `yarn.lock` — `rm -f package-lock.json yarn.lock` after. Transitive pins
  live in `package.json` `overrides`.
- **Flat config layout** (`eslint.config.js`): `js.configs.recommended` +
  `eslint-plugin-vue` `flat/recommended` (Vue 3) + one base object (globals from the
  `globals` pkg + app `frappeGlobals`, the full rule set) + 9 ordered per-path
  override objects + a leading `ignores` block (folded in from the old
  `.eslintignore`). `*.config.js` is in `ignores`, so ESLint won't lint itself.
- The lint scripts no longer pass `--ext` (removed in flat config): `npm run lint` =
  `eslint verenigingen`, `npm run lint:fix` = `+ --fix`.
- **Push** still needs `SKIP=whitelist-type-safety,test-quality-enforcer,import-path-validator`.
  Until Task A, also commit JS with `--no-verify` (or the eslint hook will churn).
- jest coverage gate lives in `jest.coverage.config.js` (674 tests); per-file
  thresholds need the `@jest/reporters > glob@7` nested override.

## Memory
- `package-manager-npm-and-jest-coverage-2026-06-11.md` (has the full session-3 update
  incl. the hook gotcha and the API-audit fix).

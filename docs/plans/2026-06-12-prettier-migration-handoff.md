# Handoff — migrate JS formatting to Prettier (2026-06-12, for next session)

## Why this exists

After the ESLint flat-config migration + lint-backlog cleanup (sessions 3–4,
commits `2a981445..27cd3d5b` on `develop`, **not pushed**), the JS error count is
down to **584 — and every one of them is `no-mixed-spaces-and-tabs`.** All other
error buckets are at **0**. Warnings (~615: no-console, no-redeclare, max-len,
prefer-const, etc.) are non-blocking and out of scope here.

Those 584 are **not a whitespace bug you can reformat away** — they are an ESLint
*rule conflict*. Foppe chose to fix it properly by **migrating formatting to
Prettier** (rather than the one-line `no-mixed-spaces-and-tabs: 'off'` stopgap).

### The conflict, proven (so the next session doesn't re-litigate it)

The config has both `indent: ["error","tab"]` and `no-mixed-spaces-and-tabs:
"error"`. On deeply-nested object literals and multi-line ternaries (e.g.
`tests/setup/api-contract-simple.js` (285), `api-contract-testing.js` (69),
`controller-loader.js` (51), several report formatters), **ESLint's own `indent`
fixer emits `<4 spaces>\t…` and reports 0 `indent` errors** — i.e. it considers
that mix correct — while `no-mixed-spaces-and-tabs` flags the exact same lines.

Verified empirically this session:
- `eslint --fix` run repeatedly **converges to the mixed state** (it re-emits the
  spaces+tab). `git diff -w` stays empty across the round-trip → it's purely a
  whitespace oscillation, no code change.
- A retab (expand leading whitespace → `round(cols/4)` tabs) clears `no-mixed`
  but trades it 1:1 for `indent` errors (the blocks are genuinely mis-depthed vs
  their AST), and the next `--fix` reverts it.
- Joining `'long-key':\n  {` → `'long-key': {` (a suspected trigger) does **not**
  fix it — the indent fixer still emits the mix.

Conclusion: ESLint's `indent` fixer is buggy on these constructs; Prettier
formats them correctly. So the real fix is to let Prettier own formatting.

Distribution of the 584 (for batching): ~417 in 4 `tests/setup/*` fixture files,
~167 spread thin across ~36 production/test files (chapter.js, BoardManager.js,
system_health_dashboard.js, membership_application.js, event_contact_campaign.js,
several doctype/report/page scripts).

---

## Goal

Adopt Prettier as the formatter for the JS tree and stop the stylistic ESLint
rules from fighting it. End state: `npm run lint` reports **0 formatting errors**
because formatting is owned by Prettier, and ESLint keeps only its
*correctness* rules (no-undef, no-unused-vars, eqeqeq, no-eval, the Frappe
field/doctype validators, etc.).

## Recommended approach

1. **Install + pin** (npm; see gotchas):
   - `npm i -D prettier eslint-config-prettier`
   - Prettier 3.6.2 is already present transitively (`node_modules/.bin/prettier`
     exists), but add it as a real devDependency. After install, `rm -f
     package-lock.json yarn.lock` (this repo intentionally has no committed
     lockfile; pins live in `package.json` `overrides`).

2. **Config to match the codebase's existing style** (`.prettierrc.json`), so the
   diff is indentation-normalization, not a full restyle:
   ```json
   {
     "useTabs": true,
     "tabWidth": 4,
     "singleQuote": true,
     "semi": true,
     "trailingComma": "none",
     "bracketSpacing": true,
     "printWidth": 120,
     "endOfLine": "lf"
   }
   ```
   These mirror the current ESLint rules (`indent: tab` tabWidth 4, `quotes:
   single`, `semi: always`, `comma-dangle: never`, `object-curly-spacing:
   always`, `max-len` 120). Verify against `eslint.config.js` `mainRules` before
   committing — the closer they match, the smaller the diff and the fewer new
   ESLint disagreements.
   Add a `.prettierignore` mirroring the `ignores` block in `eslint.config.js`
   (node_modules, dist/build, `*.min.js`/`*.bundle.js`, `**/lib/**`, `**/vendor/**`,
   `archived_*`, `verenigingen/tests/fixtures/**`, `**/__mocks__/**`, the
   pre-built `verenigingen/public/css/**`, etc.).

3. **Wire `eslint-config-prettier` LAST in the flat config** so it turns off every
   stylistic rule that could conflict with Prettier:
   ```js
   const prettier = require("eslint-config-prettier");
   module.exports = [ /* …existing… */, prettier ];  // must be the final entry
   ```
   This disables `indent`, `no-mixed-spaces-and-tabs`, `quotes`, `semi`,
   `comma-dangle`, `object-curly-spacing`, `max-len`, etc. Keep all the
   *non-stylistic* rules (no-undef, no-unused-vars [with this session's
   argsIgnorePattern], eqeqeq, no-eval, id-match, no-shadow, the Frappe
   validators). After this, re-run `npm run lint` — the only things left should be
   genuine warnings/errors, not formatting.

4. **Reformat in reviewed batches** (do NOT one-shot the whole tree into one
   commit — same lesson as the `eslint --fix` sweep this session):
   - `npx prettier --write verenigingen/public/js` → commit `style(js): prettier public/js`
   - …then `verenigingen/verenigingen/doctype`, `…/page`, `…/report`,
     `verenigingen/mijnrood_sync`, `verenigingen_payments`, `e_boekhouden`,
     `verenigingen/tests`, `cypress`.
   - **After the `public/js` batch, re-run the jest coverage gate** —
     `npm run test:coverage` must stay **674/674 green** (Prettier reformats the
     instrumented modules' style but must not change behaviour). The gate config is
     `jest.coverage.config.js`; per-file thresholds need the `@jest/reporters >
     glob@7` nested override.
   - Each batch should be `git diff -w`-empty (whitespace-only). If a batch shows
     non-whitespace changes, inspect before committing.

5. **Add scripts + hook**:
   - `package.json`: `"format": "prettier --write ."`, `"format:check": "prettier --check ."`.
   - Optionally flip the pre-commit hook (currently the corrected **check-only**
     `eslint` hook at `.pre-commit-config.yaml:144`) to also run
     `prettier --check` on staged files, or add a `prettier --write` pre-commit
     entry using the SAME `bash -c '… "$@"' --` sentinel pattern (see that hook —
     the `--` is required so pre-commit's filenames land in `"$@"`, not `$0`).

6. **Verify end state**: `npm run lint` → 0 formatting errors; `npm run
   test:coverage` → 674 green; `npx prettier --check .` → clean.

## Risks / watch-fors

- **Big diff / git blame churn** — that's expected and the whole point; keep
  batches per-directory and labelled `style(js): …` so they're greppable/skippable
  in blame.
- **Prettier vs remaining ESLint rules** — if after step 3 ESLint still flags
  formatting Prettier produced, `eslint-config-prettier` is missing a rule or
  ordered wrong (it MUST be last). Run `npx eslint-config-prettier
  path/to/file.js` (its CLI checks for conflicts).
- **Vue files** — `expense_claim_form.vue` and any `.vue` are linted via
  `eslint-plugin-vue`. Prettier formats `.vue` too; make sure `eslint-config-prettier`
  + the vue plugin coexist (config order) and the coverage gate (which doesn't
  load `.vue`) is unaffected.
- **No committed lockfile** — after any `npm i`, `rm -f package-lock.json yarn.lock`.
- **Build CSS untouched** — this is JS only; don't run `bench build`/touch Tailwind.

## Push / commit mechanics (unchanged this branch)

- Branch `develop`. 14 commits from sessions 3–4 are **local, not pushed**
  (`a926de6e..27cd3d5b`). Decide whether to push those before/with the Prettier
  work.
- Push needs `SKIP=whitelist-type-safety,test-quality-enforcer,import-path-validator`.
- Commit JS with `--no-verify` while the 584 `no-mixed` errors still exist (the
  check-only eslint hook will fail on any staged file that still carries them) —
  once the Prettier batches + `eslint-config-prettier` land, this is no longer
  needed and the hook can run normally.

## Open product decisions carried over (not formatting)

Two coherent-but-unwired features were **kept and TODO-flagged** this session
(commit `27cd3d5b`), not deleted — they need a product call, independent of the
Prettier work:
- `generate_anbi_report` (`verenigingen/verenigingen/doctype/donor/donor.js`) — a
  complete ANBI-report dialog flow (→ `show_anbi_report` → `download_anbi_report`)
  with **no button/trigger wiring it**. Wire it to a button or remove the flow.
- `format_processed` (`…/verenigingen_payments/page/mollie_bulk_payment_discovery/
  mollie_bulk_payment_discovery.js`) — a column-formatter helper referenced by no
  table config. Wire or remove.

## State at handoff

- `npm run lint` → **1199 problems (584 errors, 615 warnings)**; all 584 errors are
  `no-mixed-spaces-and-tabs`.
- Coverage gate **674/674 green**.
- Working tree clean; all session work committed (not pushed).
- Memory: `package-manager-npm-and-jest-coverage-2026-06-11.md` (full session-3/4
  detail incl. the rule-conflict proof and the hook fix).
- Prior handoff (hook + backlog, with the DONE annotations):
  `docs/plans/2026-06-12-eslint-hook-and-backlog-handoff.md`.

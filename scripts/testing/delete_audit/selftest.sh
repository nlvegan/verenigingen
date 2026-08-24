#!/bin/bash
# Prove the auditor can read non-zero, and can read zero, before trusting a census.
#
# A run reporting no survivors is worthless unless a planted resurrection reads non-zero
# -- that is the whole lesson of the instruments this tool replaces. Four planted cases,
# all four verdicts.
#
#   ./selftest.sh [site] [bench-dir]
#
# Works from a git worktree as well as the installed app: the app root is derived from
# this script's location and put on PYTHONPATH, so the control module is the one next to
# THIS copy of the tool, not whichever copy bench happens to have installed.
set -euo pipefail

SITE="${1:-test_site_1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$HERE/../../.." && pwd)"

if [ -n "${2:-}" ]; then
  BENCH="$2"
else
  # Walk up looking for a real bench; do NOT guess by path arithmetic, which is what
  # broke this script the first time it was run from a worktree.
  BENCH="$APP_ROOT"
  while [ "$BENCH" != "/" ] && [ ! -f "$BENCH/sites/common_site_config.json" ]; do
    BENCH="$(dirname "$BENCH")"
  done
  if [ ! -f "$BENCH/sites/common_site_config.json" ]; then
    echo "FAIL: no bench found above $APP_ROOT -- pass one as the second argument" >&2
    exit 1
  fi
fi
echo "== app=$APP_ROOT bench=$BENCH site=$SITE"

LOG="$(mktemp)"; rm -f "$LOG"   # the recorder refuses a non-empty log
cd "$BENCH"
DELETE_AUDIT_LOG="$LOG" DELETE_AUDIT_SELFTEST=1 PYTHONPATH="$HERE:$APP_ROOT" \
  bench --site "$SITE" run-tests --app verenigingen \
  --module verenigingen.tests.test_delete_audit_selftest > "$LOG.run" 2>&1 || {
    echo "FAIL: the control module did not pass"; tail -30 "$LOG.run"; exit 1; }

cd "$BENCH/sites"
# stderr is NOT discarded: a missing log makes the checker exit 2 with a reason, and
# hiding it turned that into four unexplained FAIL lines.
../env/bin/python "$HERE/check_survivors.py" "$SITE" "$LOG" > "$LOG.audit" 2>"$LOG.err"
audit_rc=$?
cat "$LOG.audit"; [ -s "$LOG.err" ] && cat "$LOG.err" >&2
if [ "$audit_rc" != 0 ]; then echo "FAIL: the checker exited $audit_rc"; exit 1; fi

fail=0
check() {  # check <pattern> <expected-count> <what>
  got=$(grep -c "$1" "$LOG.audit" || true)
  if [ "$got" != "$2" ]; then echo "FAIL: $3 (expected $2, got $got)"; fail=1
  else echo "ok: $3"; fi
}
# These two come FIRST, and they are what make the zero-expecting checks below mean
# anything. Measured: stubbing out `_install_frappe_hooks` left "a delete that stuck is
# NOT reported" and "an already-gone row is not a delete" both GREEN -- they are
# `grep -c == 0` assertions with no positive requirement, so a completely dead recorder
# satisfied them.
#
# Asserted against the LOG, not the audit report: a delete that was recorded and really
# did go prints nothing in the report, so the report cannot show that it was seen. And
# NOT as a total -- arming from TestSuite.run also catches the framework's own setup
# deletes, which vary by site.
# `|| true` on BOTH, and note that the pipeline needs it too: `set -o pipefail` is on,
# and `grep -o` exits 1 when it matches nothing -- which is exactly the mutated-recorder
# case these two lines exist to catch. Without it the script died here instead of
# reporting FAIL, so the guard against a vacuous check was itself vacuous. Measured.
armed=$(grep -c '"kind": "armed"' "$LOG" || true)
planted=$({ grep -o '"name": "zzaudit-[a-z]*-[0-9a-f]*"' "$LOG" || true; } | sort -u | wc -l)
if [ "$armed" != 1 ]; then echo "FAIL: no armed marker in the log (got $armed)"; fail=1
else echo "ok: the recorder armed and said so"; fi
if [ "$planted" != 5 ]; then echo "FAIL: the recorder saw $planted of 5 planted deletes"; fail=1
else echo "ok: the recorder saw all five planted deletes"; fi
check "SURVIVED Territory::zzaudit-positive"   1 "a delete undone by a rollback is reported"
check "SURVIVED Territory::zzaudit-negative"   0 "a delete that stuck is NOT reported"
check "SURVIVED Territory::zzaudit-absent"     0 "a delete of an already-gone row is not a delete"
check "RECREATED Territory::zzaudit-fixedname" 1 "same docname + new row reads RECREATED"
check "UNVERIFIABLE Territory::zzaudit-unverifiable" 1 "a failed pre-delete read is UNVERIFIABLE, not a resurrection"

../env/bin/python - "$SITE" <<'PY' 2>/dev/null
import sys
import frappe
frappe.init(site=sys.argv[1]); frappe.connect()
rows = frappe.get_all("Territory", filters={"territory_name": ["like", "zzaudit-%"]}, pluck="name")
for r in rows:
    frappe.delete_doc("Territory", r, force=True, ignore_permissions=True)
frappe.db.commit()
print(f"cleaned {len(rows)} control rows")
frappe.destroy()
PY

rm -f "$LOG" "$LOG.run" "$LOG.audit"
[ "$fail" = 0 ] && echo "SELFTEST PASSED" || { echo "SELFTEST FAILED"; exit 1; }

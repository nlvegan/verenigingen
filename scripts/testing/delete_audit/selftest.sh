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

LOG="$(mktemp)"
cd "$BENCH"
DELETE_AUDIT_LOG="$LOG" PYTHONPATH="$HERE:$APP_ROOT" \
  bench --site "$SITE" run-tests --app verenigingen \
  --module verenigingen.tests.test_delete_audit_selftest > "$LOG.run" 2>&1 || {
    echo "FAIL: the control module did not pass"; tail -30 "$LOG.run"; exit 1; }

cd "$BENCH/sites"
../env/bin/python "$HERE/check_survivors.py" "$SITE" "$LOG" > "$LOG.audit" 2>/dev/null
cat "$LOG.audit"

fail=0
check() {  # check <pattern> <expected-count> <what>
  got=$(grep -c "$1" "$LOG.audit" || true)
  if [ "$got" != "$2" ]; then echo "FAIL: $3 (expected $2, got $got)"; fail=1
  else echo "ok: $3"; fi
}
check "SURVIVED Territory::zzaudit-positive"   1 "a delete undone by a rollback is reported"
check "SURVIVED Territory::zzaudit-negative"   0 "a delete that stuck is NOT reported"
check "SURVIVED Territory::zzaudit-absent"     0 "a delete of an already-gone row is not a delete"
check "RECREATED Territory::zzaudit-fixedname" 1 "same docname + new row reads RECREATED"

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

#!/usr/bin/env bash
# Find TESTS that read the naive PROCESS clock while the code under test reads
# the SITE clock (#628, #637, and the two SEPA boundary tests that reddened
# every PR opened after 18:30 UTC).
#
# Production code is already ratcheted against this shape by
# `TestNoNaiveProcessClockCalendarReads` in tests/test_site_timezone_naive_now.py.
# That ratchet walks production modules only, and it cannot be pointed at tests:
# 38 of the 60 test files that touch a naive clock also touch the site clock, so
# a static rule over tests would need an allowlist covering most of the corpus --
# the kind of allowlist this repo has already watched cover nothing. Whether a
# naive clock in a TEST is a defect depends on whether the value crosses into
# code that measures from getdate(), which is not statically decidable.
#
# So this is an INSTRUMENT, not a gate: it decides empirically, by running each
# module twice.
#
#   red under a skewed clock AND green with the clocks aligned -> offender
#   red under both                                             -> pre-existing, not this class
#   no result at all                                           -> INCONCLUSIVE, never a pass
#
# The aligned re-run is the control. Without it a module that is simply broken
# looks identical to one that is clock-sensitive.
#
# Usage (from anywhere):
#   bash apps/verenigingen/scripts/testing/sweep_naive_process_clock.sh modules.txt
#   # modules.txt: one dotted module per line. To build the candidate list:
#   #   grep -rlE 'date\.today\(\)|datetime\.now\(\)' --include=test_*.py verenigingen/ \
#   #     | sed 's|/|.|g; s|\.py$||'
#
# Env: SWEEP_SITE (default test_site_1), PER_MODULE_TIMEOUT (default 600),
#      SWEEP_PYTHONPATH (a worktree to test instead of the installed app).
set -uo pipefail
cd /home/frappeuser/frappe-bench

MODLIST="${1:?pass a file listing one dotted module per line}"
SITE="${SWEEP_SITE:-test_site_1}"
PER_MODULE_TIMEOUT="${PER_MODULE_TIMEOUT:-600}"
PP="${SWEEP_PYTHONPATH:-}"
OUT="${SWEEP_OUT:-/tmp/clock-sweep}"
mkdir -p "$OUT"

site_tz=$(cd sites && ../env/bin/python -c "
import frappe
frappe.init(site='$SITE'); frappe.connect()
print(frappe.db.get_single_value('System Settings', 'time_zone') or 'UTC')
" 2>/dev/null | tail -1)
[ -n "$site_tz" ] || { echo "could not read System Settings.time_zone for $SITE"; exit 2; }

# Choose a process timezone that is demonstrably on a DIFFERENT calendar day from
# the site right now. No single fixed zone works around the clock -- the largest
# real offset span is 26 hours, so for part of every day any given pair agrees --
# hence: try, verify, and refuse rather than assume. A sweep whose lever silently
# did nothing would report "0 offenders" and mean nothing by it.
site_day=$(TZ="$site_tz" date +%F)
skew_tz=""
for cand in Pacific/Midway Etc/GMT+12 Etc/GMT+8 Etc/GMT-14 Pacific/Kiritimati Asia/Tokyo; do
  if [ "$(TZ="$cand" date +%F)" != "$site_day" ]; then skew_tz="$cand"; break; fi
done
if [ -z "$skew_tz" ]; then
  echo "REFUSING: no candidate process timezone is on a different calendar day"
  echo "from the site ($site_tz, $site_day) at this instant. Re-run later; a sweep"
  echo "with no divergence installed proves nothing."
  exit 3
fi
echo "site tz $site_tz -> $site_day | skewed process tz $skew_tz -> $(TZ="$skew_tz" date +%F)"

run_module() {  # $1 module, $2 TZ -> prints the runner's verdict line
  PYTHONPATH="$PP" TZ="$2" timeout "$PER_MODULE_TIMEOUT" \
    bench --site "$SITE" run-tests --app verenigingen --module "$1" 2>&1 \
    | grep -E "^(OK|FAILED)|^Ran [0-9]+ tests" | tr '\n' ' '
}

offenders=(); preexisting=(); inconclusive=()
while IFS= read -r mod; do
  [ -z "$mod" ] && continue
  # Re-verify the lever BEFORE every module, not once at startup. A sweep can
  # easily outlive its own divergence: a long run started while Los_Angeles and
  # Kolkata were a day apart keeps going after Los_Angeles rolls over, and every
  # module after that point runs with the clocks ALIGNED and reports OK for a
  # reason that has nothing to do with the code. That is not a hypothetical --
  # it happened to the first version of this sweep, which would have reported
  # "no further offenders" and meant nothing by it.
  if [ "$(TZ="$skew_tz" date +%F)" = "$(TZ="$site_tz" date +%F)" ]; then
    echo "ABORTING at $mod: $skew_tz and $site_tz are now both on"
    echo "$(TZ="$site_tz" date +%F). The lever is gone, so every remaining result"
    echo "would be a vacuous pass. Modules already reported above are still valid."
    exit 4
  fi
  skew=$(run_module "$mod" "$skew_tz")
  echo "$mod :: SKEW $skew" | tee -a "$OUT/skew.txt"
  case "$skew" in
    *FAILED*)
      aligned=$(run_module "$mod" "$site_tz")
      echo "$mod :: ALIGNED $aligned" | tee -a "$OUT/aligned.txt"
      case "$aligned" in
        *FAILED*) preexisting+=("$mod") ;;
        *OK*)     offenders+=("$mod") ;;
        *)        inconclusive+=("$mod (aligned run produced no verdict)") ;;
      esac
      ;;
    *OK*) ;;
    *) inconclusive+=("$mod (skewed run produced no verdict)") ;;
  esac
done < "$MODLIST"

echo
echo "=== clock-sensitive (red skewed, green aligned) ==="; printf '  %s\n' "${offenders[@]:-none}"
echo "=== red under both -- NOT this class ==="        ; printf '  %s\n' "${preexisting[@]:-none}"
echo "=== inconclusive -- investigate, do not read as pass ==="; printf '  %s\n' "${inconclusive[@]:-none}"
[ ${#offenders[@]} -eq 0 ]

#!/usr/bin/env bash
# Solo-classification sweep for order-dependence.
#
# For each candidate test module, RESET the site to the clean snapshot (so no
# prior module's committed leftovers contaminate it -- critical given the
# suite-wide 'Test Verenigingen Volunteer' shared-identity collision) and run it
# SOLO through the order-dependence detector. A module that:
#   * PASSES solo but failed in a real shard  -> ORDER-DEPENDENT (needs a neighbour)
#   * FAILS solo                              -> GENUINE bug / under-seeding (self-contained)
#
# Usage (from frappe-bench root):
#   MARIADB_ROOT_PASSWORD='...' bash apps/verenigingen/scripts/testing/sweep_solo_classify.sh \
#       /tmp/sweep_modules.txt
set -uo pipefail
cd /home/frappeuser/frappe-bench

MODLIST="${1:?pass a file listing one dotted module per line}"
SITE="${SWEEP_SITE:-test_site_1}"
OUT="/tmp/sweep"
PER_MODULE_TIMEOUT="${PER_MODULE_TIMEOUT:-900}"
mkdir -p "$OUT"
: > "$OUT/summary.tsv"
DET="apps/verenigingen/scripts/testing/order_dependence_detector.py"

n=0
total=$(grep -cve '^[[:space:]]*$' "$MODLIST")
while IFS= read -r mod; do
  [ -z "$mod" ] && continue
  n=$((n+1))
  safe=$(echo "$mod" | tr '.' '_')
  json="$OUT/${safe}.json"
  echo "==================== [$n/$total] $mod ===================="

  MARIADB_ROOT_PASSWORD="$MARIADB_ROOT_PASSWORD" bash reset_test_sites.sh "$SITE" >/dev/null 2>&1 \
    || { echo "RESET_FAILED $mod"; echo -e "${mod}\tRESET_FAILED\t-\t-" >> "$OUT/summary.tsv"; continue; }

  ( cd sites && timeout "$PER_MODULE_TIMEOUT" ../env/bin/python "../$DET" \
      --site "$SITE" --modules "$mod" --json-out "$json" ) \
      > "$OUT/${safe}.log" 2>&1
  rc=$?

  if [ "$rc" -eq 124 ]; then
    verdict="TIMEOUT"; nf="-"; ne="-"
  elif [ ! -f "$json" ]; then
    verdict="NO_JSON(rc=$rc)"; nf="-"; ne="-"
  else
    nf=$(python3 -c "import json;print(json.load(open('$json'))['n_failures'])")
    ne=$(python3 -c "import json;print(json.load(open('$json'))['n_errors'])")
    if [ "$nf" = "0" ] && [ "$ne" = "0" ]; then verdict="PASS_SOLO->ORDER_DEP"; else verdict="FAIL_SOLO->GENUINE"; fi
  fi
  echo "  -> $verdict (fail=$nf err=$ne)"
  echo -e "${mod}\t${verdict}\t${nf}\t${ne}" >> "$OUT/summary.tsv"
done < "$MODLIST"

echo "SWEEP_COMPLETE"
echo "==================== SUMMARY ===================="
column -t -s $'\t' "$OUT/summary.tsv"

#!/usr/bin/env bash
#
# Run test modules as CI sees them: with no payment-gateway credentials.
#
# WHY THIS EXISTS
# ---------------
# This bench carries live test credentials in sites/common_site_config.json
# (Mollie, PayNL, Stripe). CI runners do not. Any test that touches a gateway
# therefore takes a *different code path* here than in CI, and a green local run
# says nothing about the branch CI will execute.
#
# That is not hypothetical. A test built a MollieGateway to check its interval
# allow-list, passed locally 137 times across seven modules, and went red on two
# CI shards with "Mollie test secret key not configured" -- the constructor threw
# before the assertion was ever reached. The signal was available locally the
# whole time; nothing made it visible.
#
# Blanking a key is also the cheap way to answer "does this test SKIP when it
# should, or does it ERROR?" -- a live test that errors without credentials is a
# broken CI gate, not a skipped one.
#
# HOW IT WORKS
# ------------
# Credentials are shadowed as empty strings in the SITE config, which takes
# precedence over common_site_config.json. Nothing bench-wide is touched, so
# other sites (including the live one) are unaffected. Gateway settings stored in
# the site database are blanked too, since those are seeded from the config and
# would otherwise keep working. Everything is restored on exit, including on
# failure or Ctrl-C.
#
# USAGE
#   scripts/testing/run_without_credentials.sh <site> <module> [<module>...]
#
#   scripts/testing/run_without_credentials.sh test_site_1 \
#       verenigingen.tests.payment.test_mollie_subscription_service_coverage
#
# Only ever run this against a disposable test site (test_site_1-13, test_site_fresh).
# NEVER against veg11.veganisme.org: it carries a production data copy, and
# this script mutates site config and clears stored gateway Password fields.

set -uo pipefail

BENCH="$HOME/frappe-bench"
SITE="${1:-}"
shift || true

if [[ -z "$SITE" || $# -eq 0 ]]; then
    echo "usage: $0 <site> <module> [<module>...]" >&2
    exit 2
fi

case "$SITE" in
    # test_site_1..13. Enumerated by pattern rather than by name so that adding
    # a disposable site does not silently fall through to the refusal -- which is
    # what happened when sites 6-13 were created and every agent on them got
    # "REFUSING" instead of a credential check.
    test_site_[1-9]|test_site_1[0-3]|test_site_fresh) ;;
    *)
        echo "REFUSING: '$SITE' is not a disposable test site (test_site_1-13, test_site_fresh)." >&2
        echo "This script mutates site config and gateway settings; never point it at a live site." >&2
        exit 2
        ;;
esac

SITE_CONFIG="$BENCH/sites/$SITE/site_config.json"
BACKUP="$(mktemp "${TMPDIR:-/tmp}/site_config.$SITE.XXXXXX.json")"

restore() {
    local rc=$?
    if [[ -f "$BACKUP" ]]; then
        cp "$BACKUP" "$SITE_CONFIG"
        rm -f "$BACKUP"
    fi
    # Re-seed the gateway settings rows that were blanked in the database.
    (cd "$BENCH/sites" && "$BENCH/env/bin/python" - "$SITE" <<'PY' >/dev/null 2>&1
import sys
import frappe

frappe.init(site=sys.argv[1])
frappe.connect()
try:
    from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import (
        ensure_mollie_test_credentials,
    )

    ensure_mollie_test_credentials()
    frappe.db.commit()
except Exception:
    pass
PY
    )
    echo "[run_without_credentials] restored $SITE config and gateway settings"
    exit $rc
}
trap restore EXIT INT TERM

cp "$SITE_CONFIG" "$BACKUP"

# Shadow every credential-shaped key from common_site_config in the site config.
"$BENCH/env/bin/python" - "$SITE_CONFIG" "$BENCH/sites/common_site_config.json" <<'PY'
import json
import re
import sys

site_path, common_path = sys.argv[1], sys.argv[2]
pattern = re.compile(r"key|secret|token|password|api|credential", re.I)

# Framework-critical secrets that match the pattern but must never be blanked:
# `encryption_key`/`secret_key` decrypt every stored password on the site, and
# blanking the db/admin passwords locks the run out of its own database. These
# are not gateway credentials and CI has its own.
NEVER_SHADOW = {
    "encryption_key",
    "secret_key",
    "db_password",
    "admin_password",
    "root_password",
    "maintenance_password",
}

common = json.load(open(common_path))
site = json.load(open(site_path))

shadowed = [k for k in common if pattern.search(k) and common[k] and k not in NEVER_SHADOW]
for key in shadowed:
    site[key] = ""

json.dump(site, open(site_path, "w"), indent=1, sort_keys=True)
print(f"[run_without_credentials] shadowed {len(shadowed)} credential keys: {', '.join(sorted(shadowed))}")
PY

# Blank the database-side copies, which are seeded from the config above and
# would otherwise still satisfy a gateway constructor.
(cd "$BENCH/sites" && "$BENCH/env/bin/python" - "$SITE" <<'PY'
import sys
import frappe

frappe.init(site=sys.argv[1])
frappe.connect()

# These are Password fields: their values live in the `__Auth` table, NOT in
# tabSingles, so frappe.db.set_value(...) on them is a silent no-op and the key
# keeps working. Deleting the __Auth row is what actually clears it -- verified
# via MollieSettings.get_active_api_key() flipping True -> False.
PASSWORD_FIELDS = (
    ("Mollie Settings", "test_secret_key"),
    ("Mollie Settings", "live_secret_key"),
)
cleared = 0
for doctype, field in PASSWORD_FIELDS:
    if not frappe.db.exists("DocType", doctype):
        continue
    try:
        frappe.db.sql(
            "DELETE FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname=%s",
            (doctype, doctype, field),
        )
        cleared += 1
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"[run_without_credentials] could not clear {doctype}.{field}: {exc}")
frappe.db.commit()
frappe.clear_cache()
print(f"[run_without_credentials] cleared {cleared} stored gateway password field(s)")
PY
)

echo "[run_without_credentials] running ${#@} module(s) against $SITE with no credentials"
status=0
for module in "$@"; do
    echo "--- $module"
    if ! (cd "$BENCH" && bench --site "$SITE" run-tests --app verenigingen --module "$module"); then
        status=1
    fi
done

exit $status

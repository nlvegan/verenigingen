#!/usr/bin/env bash
# Sourced by the "Install JS Dependencies" step of action.yml (#853).
#
#   ci_retry_js_install <label> <command> [args...]
#
# Runs the command (a shell function in the caller is fine). A failure whose output shows a
# NETWORK/registry problem (npm E404 on a tarball that just got published, ECONNRESET, ETIMEDOUT,
# EAI_AGAIN, 5xx, yarn's "trouble with your network connection") is retried with backoff; if it
# is still failing after the last attempt, an ::error:: names it an infrastructure failure, using
# the standard wording that automerge_supervise.sh / classify_queue_drop.sh match.
# Any other failure (ERESOLVE, a bad lockfile, a script error) is a real dependency error: it is
# NOT retried, gets NO infrastructure wording, and the command's own exit code is returned.
#
# Env: CI_JS_INSTALL_ATTEMPTS (default 4), CI_JS_INSTALL_BACKOFF seconds, doubled per retry (default 15).

_CI_JS_TRANSIENT='npm error code (E404|ECONNRESET|ETIMEDOUT|ECONNREFUSED|EAI_AGAIN|ENOTFOUND|ESOCKETTIMEDOUT|EPIPE)|npm error network|npm ERR! (code (E404|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND)|network)|trouble with your network connection|ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up|(Unexpected|Bad) (HTTP )?(response|status)[^0-9]*5[0-9][0-9]|50[0234] (Bad Gateway|Service Unavailable|Gateway Time-out)'

ci_retry_js_install() {
  local label="$1"; shift
  local attempts="${CI_JS_INSTALL_ATTEMPTS:-4}" delay="${CI_JS_INSTALL_BACKOFF:-15}"
  local log n=1 rc
  log="$(mktemp)"
  while :; do
    rc=0
    "$@" >"$log" 2>&1 || rc=$?
    cat "$log"
    if [ "$rc" -eq 0 ]; then rm -f "$log"; return 0; fi
    if ! grep -Eq "$_CI_JS_TRANSIENT" "$log"; then
      echo "JS install for ${label} failed (exit ${rc}) with no network signature: a real dependency error, not retried."
      rm -f "$log"
      return "$rc"
    fi
    if [ "$n" -ge "$attempts" ]; then
      echo "::error::JS dependency install for ${label} failed after ${attempts} attempts with a registry/network error. This is an infrastructure failure, not a code failure - no test has run at this point. Re-run the job. (If the error above is an E404 for a version that does not exist, it is a real pin problem instead.)"
      rm -f "$log"
      return "$rc"
    fi
    echo "JS install for ${label} hit a network error (attempt ${n}/${attempts}); retrying in ${delay}s."
    sleep "$delay"
    delay=$((delay * 2))
    n=$((n + 1))
  done
}

#!/usr/bin/env bash
# Sourced by the "Install JS Dependencies" step of action.yml (#853).
#
#   ci_retry_js_install <label> <command> [args...]
#
# Runs the command (a shell function in the caller is fine). A failure whose output shows a
# NETWORK/registry problem (a 404 on a package TARBALL (`.../-/x.tgz`), which is a just-published version not yet propagated, ECONNRESET, ETIMEDOUT,
# EAI_AGAIN, 5xx, yarn's "trouble with your network connection") is retried with backoff; if it
# is still failing after the last attempt, an ::error:: names it an infrastructure failure, using
# the standard wording that automerge_supervise.sh / classify_queue_drop.sh match.
# Any other failure (ERESOLVE, a bad lockfile, a script error) is a real dependency error: it is
# NOT retried, gets NO infrastructure wording, and the command's own exit code is returned.
#
# Env: CI_JS_INSTALL_ATTEMPTS (default 4), CI_JS_INSTALL_BACKOFF seconds, doubled per retry (default 15).

_CI_JS_TRANSIENT='npm error code (ECONNRESET|ETIMEDOUT|ECONNREFUSED|EAI_AGAIN|ENOTFOUND|ESOCKETTIMEDOUT|EPIPE)|npm error network|npm ERR! (code (ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND)|network)|trouble with your network connection|404 Not Found - GET [^ ]*/-/[^ ]*\.tgz|ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up|(Unexpected|Bad) (HTTP )?(response|status)[^0-9]*5[0-9][0-9]|50[0234] (Bad Gateway|Service Unavailable|Gateway Time-out)'

# pip (#2910). pip's own --retries (default 5) retries connection errors and 5xx, but when it gives up
# on an index 5xx it prints only "No matching distribution found" (measured against a local 502 server:
# output identical to a real missing pin), so that case has no network signature and is not retried
# here. What does leave a signature: connection resets/timeouts/DNS and a failed git fetch.
_CI_PIP_TRANSIENT='Retrying \(Retry|ReadTimeoutError|ConnectTimeoutError|ConnectionResetError|Connection reset by peer|Connection aborted|RemoteDisconnected|IncompleteRead|Read timed out|Temporary failure in name resolution|Network is unreachable|Could not fetch URL|Max retries exceeded|Could not resolve host|RPC failed|early EOF|fatal: unable to access|HTTP error 5[0-9][0-9]|50[0234] (Bad Gateway|Service Unavailable|Gateway Time-out)'

# Set to 1 when the last ci_retry_* call gave up on a network error, so a caller's `|| fallback` can skip
# a second, equally doomed round.
CI_RETRY_GAVE_UP_ON_NETWORK=0

ci_retry_js_install() {
  local label="$1"; shift
  _ci_retry_install "JS dependency" "$_CI_JS_TRANSIENT" "$label" "$@"
}

ci_retry_pip_install() {
  local label="$1"; shift
  _ci_retry_install "Python dependency" "$_CI_PIP_TRANSIENT" "$label" "$@"
}

_ci_retry_install() {
  local kind="$1" pattern="$2" label="$3"; shift 3
  local attempts="${CI_JS_INSTALL_ATTEMPTS:-4}" delay="${CI_JS_INSTALL_BACKOFF:-15}"
  local log n=1 rc
  CI_RETRY_GAVE_UP_ON_NETWORK=0
  log="$(mktemp)"
  while :; do
    rc=0
    "$@" >"$log" 2>&1 || rc=$?
    cat "$log"
    if [ "$rc" -eq 0 ]; then rm -f "$log"; return 0; fi
    if ! grep -Eq "$pattern" "$log"; then
      echo "${kind} install for ${label} failed (exit ${rc}) with no network signature: a real dependency error, not retried."
      rm -f "$log"
      return "$rc"
    fi
    if [ "$n" -ge "$attempts" ]; then
      CI_RETRY_GAVE_UP_ON_NETWORK=1
      echo "::error::${kind} install for ${label} failed after ${attempts} attempts with a registry/network error. This is an infrastructure failure, not a code failure - no test has run at this point. Re-run the job. (A 404 on a package name, or a version that does not exist (ETARGET / No matching distribution), is a real pin problem instead and is not retried.)"
      rm -f "$log"
      return "$rc"
    fi
    echo "${kind} install for ${label} hit a network error (attempt ${n}/${attempts}); retrying in ${delay}s."
    sleep "$delay"
    delay=$((delay * 2))
    n=$((n + 1))
  done
}

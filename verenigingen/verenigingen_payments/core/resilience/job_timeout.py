"""A job timeout must never be retried (#1919).

RQ enforces a job's timeout by raising ``JobTimeoutException`` once, from a SIGALRM
handler, inside whatever the job is running. It is an ``Exception`` subclass, so a retry
loop with ``except Exception`` treats it as a transient failure, sleeps and calls again:
the one signal is spent and the job runs past its timeout.

Every retry wrapper calls ``reraise_if_job_timeout`` first in its handler.
"""

from rq.timeouts import BaseTimeoutException


def exception_chain(exc):
    """``exc`` and everything on its ``__cause__``/``__context__`` chain."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        yield exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__


def is_job_timeout(exc) -> bool:
    """True when ``exc`` is, or was raised while handling or from, an RQ timeout.

    The chain is walked because client wrappers re-raise a fresh exception from the
    original (the Ponto clients do, #1924), which hides the timeout one level down.
    """
    return any(isinstance(e, BaseTimeoutException) for e in exception_chain(exc))


def reraise_if_job_timeout(exc):
    """Re-raise ``exc`` unchanged when it is a job timeout. Call inside ``except``."""
    if is_job_timeout(exc):
        raise exc

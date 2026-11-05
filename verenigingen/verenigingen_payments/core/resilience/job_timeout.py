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
    """True when ``exc`` is an RQ timeout, or has one on its ``__cause__``/``__context__`` chain.

    The chain is walked because a client wrapper catches the timeout and raises a fresh
    exception inside its ``except`` (the Ponto clients do, without ``from``, #1924), so
    the timeout survives only as ``__context__``.

    Consequence: a retry-wrapped call made from inside an ``except JobTimeoutException:``
    block fails fast, because ``__context__`` holds the timeout. That fails closed.
    """
    return any(isinstance(e, BaseTimeoutException) for e in exception_chain(exc))


def reraise_if_job_timeout(exc):
    """Re-raise ``exc`` unchanged when it is a job timeout. Call inside ``except``."""
    if is_job_timeout(exc):
        raise exc

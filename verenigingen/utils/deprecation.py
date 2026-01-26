"""
Deprecation utilities for the Verenigingen app.

Provides decorators for marking functions and classes as deprecated,
issuing warnings when they are used.
"""

import functools
import warnings
from typing import Optional, Type, TypeVar, Union

T = TypeVar("T")


def deprecated(
    message: str,
    *,
    category: Type[Warning] = DeprecationWarning,
    stacklevel: int = 2,
):
    """
    Decorator to mark functions or classes as deprecated.

    When the decorated function is called or the decorated class is instantiated,
    a deprecation warning will be issued.

    Args:
        message: The deprecation message explaining what to use instead.
        category: The warning category to use (default: DeprecationWarning).
        stacklevel: Stack level for the warning (default: 2).

    Examples:
        @deprecated("Use new_function() instead")
        def old_function():
            pass

        @deprecated("Use NewClass instead")
        class OldClass:
            pass
    """

    def decorator(obj: T) -> T:
        if isinstance(obj, type):
            # Decorating a class - wrap __init__
            return _deprecate_class(obj, message, category, stacklevel)
        else:
            # Decorating a function
            return _deprecate_function(obj, message, category, stacklevel)

    return decorator


def _deprecate_function(func, message: str, category: Type[Warning], stacklevel: int):
    """Wrap a function to issue a deprecation warning when called."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        warnings.warn(
            f"{func.__qualname__} is deprecated. {message}",
            category=category,
            stacklevel=stacklevel,
        )
        return func(*args, **kwargs)

    return wrapper


def _deprecate_class(cls: Type[T], message: str, category: Type[Warning], stacklevel: int) -> Type[T]:
    """Wrap a class to issue a deprecation warning when instantiated."""
    original_init = cls.__init__

    @functools.wraps(original_init)
    def new_init(self, *args, **kwargs):
        warnings.warn(
            f"{cls.__qualname__} is deprecated. {message}",
            category=category,
            stacklevel=stacklevel + 1,  # +1 for the wrapper
        )
        original_init(self, *args, **kwargs)

    cls.__init__ = new_init
    return cls

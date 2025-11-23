"""
Type stubs for Frappe Framework.

Since Frappe doesn't provide official type stubs, this file provides
basic type hints for commonly used Frappe functions.
"""

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Literal, Optional, TypeVar, Union, overload

# Type variables
T = TypeVar("T")
DocType = TypeVar("DocType", bound="Document")

# Document class
class Document:
    """Base class for all Frappe documents."""

    name: str
    doctype: str
    owner: str
    creation: datetime
    modified: datetime
    modified_by: str
    docstatus: int

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def insert(self, ignore_permissions: bool = False, ignore_if_duplicate: bool = False) -> Document: ...
    def save(self, ignore_permissions: bool = False, ignore_version: bool = False) -> Document: ...
    def submit(self) -> Document: ...
    def cancel(self) -> Document: ...
    def delete(self, ignore_permissions: bool = False) -> None: ...
    def reload(self) -> Document: ...
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def db_set(self, key: str, value: Any, update_modified: bool = True) -> None: ...
    def db_get(self, key: str) -> Any: ...
    def as_dict(
        self, no_default_fields: bool = False, no_child_table_fields: bool = False
    ) -> Dict[str, Any]: ...

# Core functions
def get_doc(doctype: Union[str, Dict[str, Any]], name: Optional[str] = None) -> Document: ...
def new_doc(doctype: str) -> Document: ...
def delete_doc(
    doctype: str,
    name: str,
    force: bool = False,
    ignore_permissions: bool = False,
) -> None: ...
def rename_doc(
    doctype: str,
    old_name: str,
    new_name: str,
    force: bool = False,
    merge: bool = False,
) -> str: ...
def copy_doc(doc: Document, ignore_no_copy: bool = True) -> Document: ...

# Database functions
class _DBNamespace:
    """Database namespace."""

    def get_value(
        self,
        doctype: str,
        filters: Union[str, Dict[str, Any], List[Any], None] = None,
        fieldname: Union[str, List[str]] = "name",
        as_dict: bool = False,
        order_by: Optional[str] = None,
        cache: bool = False,
    ) -> Any: ...
    def get_all(
        self,
        doctype: str,
        filters: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        start: int = 0,
        as_list: bool = False,
        group_by: Optional[str] = None,
        pluck: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...
    def get_list(
        self,
        doctype: str,
        filters: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        start: int = 0,
        ignore_permissions: bool = False,
    ) -> List[Dict[str, Any]]: ...
    def get_single_value(self, doctype: str, fieldname: str) -> Any: ...
    def set_value(
        self,
        doctype: str,
        name: str,
        fieldname: Union[str, Dict[str, Any]],
        value: Optional[Any] = None,
        update_modified: bool = True,
    ) -> None: ...
    def exists(self, doctype: str, name: Optional[Union[str, Dict[str, Any]]] = None) -> Optional[str]: ...
    def count(self, doctype: str, filters: Optional[Dict[str, Any]] = None) -> int: ...
    def sql(
        self,
        query: str,
        values: Optional[Union[tuple, list, dict]] = None,
        as_dict: bool = False,
        as_list: bool = False,
    ) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def begin(self) -> None: ...

db: _DBNamespace

# Utility functions
def throw(
    msg: str,
    exc: type = Exception,
    title: Optional[str] = None,
    is_minimizable: bool = False,
) -> None: ...
def msgprint(
    msg: str,
    title: Optional[str] = None,
    raise_exception: bool = False,
    as_table: bool = False,
    indicator: Literal["green", "blue", "orange", "red"] = "blue",
) -> None: ...
def log_error(title: Optional[str] = None, message: Optional[str] = None) -> None: ...

# Translation
def _(text: str, context: Optional[str] = None) -> str: ...

# Sessions and users
def get_user() -> str: ...
def get_fullname(user: Optional[str] = None) -> str: ...
def has_permission(
    doctype: str,
    ptype: str = "read",
    doc: Optional[Union[str, Document]] = None,
    user: Optional[str] = None,
) -> bool: ...

# Validation
def validate_email_address(email: str, throw: bool = False) -> bool: ...
def validate_url(url: str, throw: bool = False) -> bool: ...
def validate_phone_number(number: str, throw: bool = False) -> bool: ...

# API decorators
def whitelist(
    allow_guest: bool = False, methods: Optional[List[str]] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]: ...

# Enqueue functions
def enqueue(
    method: Union[str, Callable],
    queue: str = "default",
    timeout: Optional[int] = None,
    is_async: bool = True,
    **kwargs: Any,
) -> Any: ...
def enqueue_doc(
    doctype: str,
    name: str,
    method: str,
    queue: str = "default",
    timeout: Optional[int] = None,
    **kwargs: Any,
) -> Any: ...

# Flags
class _Flags:
    """Global flags namespace."""

    in_test: bool
    in_install: bool
    in_migrate: bool
    in_import: bool
    ignore_permissions: bool

flags: _Flags

# Local namespace
class _Local:
    """Thread-local namespace."""

    form_dict: Dict[str, Any]
    request: Any
    response: Dict[str, Any]
    message_log: List[str]
    lang: str

local: _Local

# Utils namespace (most commonly used utilities)
class utils:
    """Frappe utilities namespace."""

    @staticmethod
    def now() -> str: ...
    @staticmethod
    def nowdate() -> str: ...
    @staticmethod
    def nowtime() -> str: ...
    @staticmethod
    def today() -> str: ...
    @staticmethod
    def get_datetime(datetime_str: Optional[str] = None) -> datetime: ...
    @staticmethod
    def get_date(date_str: Optional[str] = None) -> date: ...
    @staticmethod
    def add_days(date: Union[str, date], days: int) -> Union[str, date]: ...
    @staticmethod
    def add_months(date: Union[str, date], months: int) -> Union[str, date]: ...
    @staticmethod
    def add_years(date: Union[str, date], years: int) -> Union[str, date]: ...
    @staticmethod
    def getdate(date_str: Union[str, date, datetime, None] = None) -> date: ...
    @staticmethod
    def cint(value: Any, default: int = 0) -> int: ...
    @staticmethod
    def cstr(value: Any, default: str = "") -> str: ...
    @staticmethod
    def flt(value: Any, precision: int = 2) -> float: ...
    @staticmethod
    def get_url(uri: Optional[str] = None) -> str: ...
    @staticmethod
    def validate_email_address(email: str, throw: bool = False) -> bool: ...

# Module exports
__all__ = [
    "Document",
    "get_doc",
    "new_doc",
    "delete_doc",
    "rename_doc",
    "db",
    "throw",
    "msgprint",
    "log_error",
    "_",
    "get_user",
    "has_permission",
    "whitelist",
    "enqueue",
    "flags",
    "local",
    "utils",
]

"""
Frappe Framework Mock for Testing
Provides mock Frappe functionality for testing without full framework
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from unittest.mock import MagicMock, Mock


class ValidationError(Exception):
    """Mock Frappe validation error"""
    pass


class DoesNotExistError(Exception):
    """Mock Frappe does not exist error"""
    pass


class PermissionError(Exception):
    """Mock Frappe permission error"""
    pass


class MockDB:
    """Mock Frappe database"""
    
    def __init__(self):
        self.data = {}
    
    def get_value(self, doctype: str, filters: Dict, fieldname: Union[str, List[str]] = None, **kwargs):
        """Mock get_value"""
        if kwargs.get("as_dict"):
            return {"name": f"test_{doctype}"}
        return f"test_{doctype}"
    
    def get_all(self, doctype: str, **kwargs):
        """Mock get_all"""
        return []
    
    def set_value(self, doctype: str, name: str, fieldname: str, value: Any):
        """Mock set_value"""
        pass
    
    def commit(self):
        """Mock commit"""
        pass
    
    def rollback(self):
        """Mock rollback"""
        pass
    
    def sql(self, query: str, values: tuple = None, **kwargs):
        """Mock SQL execution"""
        return []
    
    def exists(self, doctype: str, name: str = None):
        """Mock exists check"""
        return False


class MockDoc:
    """Mock Frappe document"""
    
    def __init__(self, doctype: str, **kwargs):
        self.doctype = doctype
        self.name = kwargs.get("name", f"test_{doctype}")
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def get_password(self, fieldname: str = None, raise_exception: bool = False):
        """Mock password retrieval"""
        return "test_password_12345"
    
    def save(self, ignore_permissions: bool = False):
        """Mock save"""
        return self
    
    def insert(self, ignore_permissions: bool = False):
        """Mock insert"""
        return self
    
    def delete(self, ignore_permissions: bool = False):
        """Mock delete"""
        pass


class MockSession:
    """Mock Frappe session"""
    
    def __init__(self):
        self.user = "test@example.com"
        self.sid = "test_session_id"


class MockUtils:
    """Mock Frappe utils"""
    
    @staticmethod
    def get_url(path: str = "") -> str:
        """Mock get_url"""
        return f"https://test.example.com{path}"
    
    @staticmethod
    def now_datetime() -> datetime:
        """Mock now_datetime"""
        return datetime.now()
    
    @staticmethod
    def add_days(date: datetime, days: int) -> datetime:
        """Mock add_days"""
        from datetime import timedelta
        return date + timedelta(days=days)
    
    @staticmethod
    def get_datetime(date_str: str) -> datetime:
        """Mock get_datetime"""
        return datetime.fromisoformat(date_str)


# Create mock frappe module
class MockFrappe:
    """Mock Frappe module"""
    
    def __init__(self):
        self.db = MockDB()
        self.session = MockSession()
        self.utils = MockUtils()
        
        # Mock error classes
        self.ValidationError = ValidationError
        self.DoesNotExistError = DoesNotExistError
        self.PermissionError = PermissionError
    
    def get_doc(self, doctype: str, name: str = None, **kwargs) -> MockDoc:
        """Mock get_doc"""
        if doctype == "Mollie Settings":
            return MockDoc(
                doctype="Mollie Settings",
                name=name or "Test Settings",
                enabled=1,
                gateway_name="Test",
                profile_id="pfl_test123",
                webhook_url="https://test.example.com/webhook",
                webhook_secret="test_webhook_secret",
                enable_backend_api=True,
                enable_encryption=True,
                enable_audit_trail=True,
                circuit_breaker_failure_threshold=5,
                circuit_breaker_timeout=60,
                rate_limit_requests_per_second=25,
                retry_max_attempts=3,
                retry_backoff_base=2,
                auto_reconcile=True,
                reconciliation_hour=2,
                reconciliation_tolerance=0.01,
                low_balance_threshold=1000.00,
                enable_balance_alerts=True,
                alert_recipients="test@example.com"
            )
        return MockDoc(doctype, name=name, **kwargs)
    
    def new_doc(self, doctype: str) -> MockDoc:
        """Mock new_doc"""
        return MockDoc(doctype)
    
    def get_all(self, doctype: str, **kwargs) -> List[Dict]:
        """Mock get_all"""
        if doctype == "Mollie Settings" and kwargs.get("pluck") == "name":
            return ["Test Settings"]
        if doctype == "Mollie Settings":
            return [{"name": "Test Settings"}]
        return []
    
    def throw(self, message: str, exc: type = None):
        """Mock throw"""
        raise (exc or Exception)(message)
    
    def whitelist(self, *args, **kwargs):
        """Mock whitelist decorator"""
        def decorator(func):
            return func
        return decorator if not args else args[0]
    
    def _(self, message: str) -> str:
        """Mock translation"""
        return message
    
    def log_error(self, message: str, title: str = None):
        """Mock log_error"""
        print(f"ERROR [{title}]: {message}")
    
    def msgprint(self, message: str, title: str = None, indicator: str = "blue"):
        """Mock msgprint"""
        print(f"[{title or 'Message'}]: {message}")
    
    def publish_realtime(self, event: str, message: Any = None, **kwargs):
        """Mock publish_realtime"""
        pass
    
    def generate_hash(self, length: int = 10) -> str:
        """Mock generate_hash"""
        import random
        import string
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    
    def has_permission(self, doctype: str, ptype: str = "read", **kwargs) -> bool:
        """Mock has_permission"""
        return True
    
    def cache(self):
        """Mock cache"""
        return MagicMock()


# Create global mock instance
frappe = MockFrappe()

# Make frappe importable as a module
import sys
sys.modules['frappe'] = frappe
sys.modules['frappe.utils'] = frappe.utils

# Export all necessary components
__all__ = [
    'frappe',
    'ValidationError',
    'DoesNotExistError', 
    'PermissionError',
    'MockDoc',
    'MockDB',
    'MockSession'
]
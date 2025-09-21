"""
Service Factory - Centralized service instantiation and dependency injection.

This module provides a factory pattern for creating and managing services
with proper dependency injection, configuration, and lifecycle management.

Classes:
    - ServiceFactory: Factory for creating and managing service instances
    - ServiceRegistry: Registry for service discovery and configuration
    - ServiceDependency: Dependency injection utilities
"""

import logging
import threading
from typing import Any, Dict, List, Optional, Type, TypeVar

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import BaseService
from verenigingen.utils.service_error_handler import ServiceError

T = TypeVar("T", bound=BaseService)


class ServiceRegistry:
    """Registry for service discovery and configuration management."""

    def __init__(self):
        self._services = {}
        self._configurations = {}
        self._singletons = {}
        self._lock = threading.Lock()
        self.logger = logging.getLogger("verenigingen.services.registry")

    def register_service(
        self, service_name: str, service_class: Type[BaseService], config: Dict = None, singleton: bool = True
    ):
        """Register a service class with the registry.

        Args:
            service_name: Unique name for the service
            service_class: Service class to register
            config: Configuration dictionary for the service
            singleton: Whether to use singleton pattern for this service
        """
        with self._lock:
            self._services[service_name] = {
                "class": service_class,
                "config": config or {},
                "singleton": singleton,
            }

            if config:
                self._configurations[service_name] = config

        self.logger.info(f"Registered service: {service_name}")

    def get_service_info(self, service_name: str) -> Dict:
        """Get information about a registered service.

        Args:
            service_name: Name of the service

        Returns:
            Service information dictionary
        """
        with self._lock:
            if service_name not in self._services:
                raise ServiceError(f"Service not registered: {service_name}")

            return self._services[service_name].copy()

    def list_services(self) -> List[str]:
        """Get list of all registered service names.

        Returns:
            List of service names
        """
        return list(self._services.keys())

    def get_configuration(self, service_name: str) -> Dict:
        """Get configuration for a service.

        Args:
            service_name: Name of the service

        Returns:
            Configuration dictionary
        """
        return self._configurations.get(service_name, {})

    def update_configuration(self, service_name: str, config: Dict):
        """Update configuration for a service.

        Args:
            service_name: Name of the service
            config: New configuration dictionary
        """
        with self._lock:
            if service_name in self._services:
                self._services[service_name]["config"].update(config)
                self._configurations[service_name] = self._services[service_name]["config"]

                # Clear singleton instance to force reconfiguration
                if service_name in self._singletons:
                    del self._singletons[service_name]

    def clear_singletons(self):
        """Clear all singleton instances (useful for testing)."""
        with self._lock:
            self._singletons.clear()


class ServiceFactory:
    """Factory for creating and managing service instances with dependency injection."""

    def __init__(self, registry: ServiceRegistry = None):
        self.registry = registry or ServiceRegistry()
        self.logger = logging.getLogger("verenigingen.services.factory")
        self._dependency_graph = {}

    def register_service(
        self,
        service_name: str,
        service_class: Type[T],
        config: Dict = None,
        singleton: bool = True,
        dependencies: List[str] = None,
    ) -> "ServiceFactory":
        """Register a service with the factory.

        Args:
            service_name: Unique name for the service
            service_class: Service class to register
            config: Configuration dictionary
            singleton: Whether to use singleton pattern
            dependencies: List of dependent service names

        Returns:
            Self for method chaining
        """
        self.registry.register_service(service_name, service_class, config, singleton)

        if dependencies:
            self._dependency_graph[service_name] = dependencies

        return self

    def create_service(self, service_name: str, **kwargs) -> BaseService:
        """Create a service instance with dependency injection.

        Args:
            service_name: Name of the service to create
            **kwargs: Additional arguments for service construction

        Returns:
            Service instance

        Raises:
            ServiceError: If service is not registered or creation fails
        """
        service_info = self.registry.get_service_info(service_name)

        # Check if singleton instance exists (thread-safe)
        with self.registry._lock:
            if service_info["singleton"] and service_name in self.registry._singletons:
                return self.registry._singletons[service_name]

        # Resolve dependencies
        dependencies = self._resolve_dependencies(service_name)

        # Merge configuration with kwargs
        config = service_info["config"].copy()
        config.update(kwargs)

        try:
            # Create service instance
            service_class = service_info["class"]
            service_instance = service_class(service_name=service_name)

            # Inject dependencies
            for dep_name, dep_instance in dependencies.items():
                setattr(service_instance, f"_{dep_name}_service", dep_instance)

            # Validate configuration
            service_instance.validate_configuration()

            # Store singleton if configured (thread-safe)
            if service_info["singleton"]:
                with self.registry._lock:
                    # Double-check pattern - another thread might have created it
                    if service_name not in self.registry._singletons:
                        self.registry._singletons[service_name] = service_instance
                    else:
                        # Return existing instance and cleanup the one we just created
                        if hasattr(service_instance, "cleanup"):
                            service_instance.cleanup()
                        return self.registry._singletons[service_name]

            self.logger.info(f"Created service: {service_name}")
            return service_instance

        except Exception as e:
            raise ServiceError(f"Failed to create service {service_name}: {str(e)}")

    def get_service(self, service_name: str) -> BaseService:
        """Get a service instance (create if doesn't exist).

        Args:
            service_name: Name of the service

        Returns:
            Service instance
        """
        service_info = self.registry.get_service_info(service_name)

        with self.registry._lock:
            if service_info["singleton"] and service_name in self.registry._singletons:
                return self.registry._singletons[service_name]

        return self.create_service(service_name)

    def _resolve_dependencies(self, service_name: str) -> Dict[str, BaseService]:
        """Resolve service dependencies recursively.

        Args:
            service_name: Name of the service

        Returns:
            Dictionary of dependency instances

        Raises:
            ServiceError: If circular dependencies are detected
        """
        dependencies = {}
        visited = set()

        def resolve_recursive(name: str, path: List[str]):
            if name in path:
                raise ServiceError(f"Circular dependency detected: {' -> '.join(path + [name])}")

            if name in visited:
                return

            visited.add(name)

            if name in self._dependency_graph:
                for dep_name in self._dependency_graph[name]:
                    resolve_recursive(dep_name, path + [name])
                    dependencies[dep_name] = self.get_service(dep_name)

        resolve_recursive(service_name, [])
        return dependencies

    def shutdown_services(self):
        """Shutdown all services and clear singletons."""
        with self.registry._lock:
            singletons_copy = dict(self.registry._singletons)

        for service_name, service_instance in singletons_copy.items():
            try:
                if hasattr(service_instance, "cleanup"):
                    service_instance.cleanup()
                elif hasattr(service_instance, "shutdown"):
                    service_instance.shutdown()
                self.logger.info(f"Shutdown service: {service_name}")
            except Exception as e:
                self.logger.error(f"Error shutting down service {service_name}: {str(e)}")

        self.registry.clear_singletons()

    def get_service_metrics(self) -> Dict[str, Dict]:
        """Get metrics for all active services.

        Returns:
            Dictionary mapping service names to their metrics
        """
        metrics = {}
        for service_name, service_instance in self.registry._singletons.items():
            try:
                metrics[service_name] = service_instance.get_metrics()
            except Exception as e:
                self.logger.error(f"Error getting metrics for {service_name}: {str(e)}")
                metrics[service_name] = {"error": str(e)}

        return metrics


# Global service factory instance with thread-safe initialization
_global_factory = None
_factory_lock = threading.Lock()


def get_service_factory() -> ServiceFactory:
    """Get the global service factory instance.

    Returns:
        Global ServiceFactory instance
    """
    global _global_factory
    if _global_factory is None:
        with _factory_lock:
            # Double-checked locking pattern
            if _global_factory is None:
                _global_factory = ServiceFactory()
                _register_core_services(_global_factory)
    return _global_factory


def get_service(service_name: str) -> BaseService:
    """Convenience function to get a service from the global factory.

    Args:
        service_name: Name of the service

    Returns:
        Service instance
    """
    return get_service_factory().get_service(service_name)


def _register_core_services(factory: ServiceFactory):
    """Register core Verenigingen services with the factory.

    Args:
        factory: ServiceFactory instance to register services with
    """
    # Import services to register them
    try:
        from verenigingen.services.customer_handling_service import CustomerHandlingService

        # Register customer handling service (migrated to infrastructure)
        factory.register_service("customer_handling", CustomerHandlingService, singleton=True)

    except ImportError as e:
        logging.getLogger("verenigingen.services.factory").info(
            f"Customer handling service not available: {str(e)}"
        )

    try:
        from verenigingen.services.member.core.member_id_service import MemberIdService
        from verenigingen.services.member.core.member_status_service import MemberStatusService
        from verenigingen.services.member.utils.member_age_service import MemberAgeService

        # Register member services
        factory.register_service("member_id", MemberIdService, singleton=True)
        factory.register_service("member_status", MemberStatusService, singleton=True)
        factory.register_service("member_age", MemberAgeService, singleton=True)

    except ImportError as e:
        # Services may not be class-based yet, that's okay
        logging.getLogger("verenigingen.services.factory").info(
            f"Some member services not yet available for registration: {str(e)}"
        )


def configure_service(service_name: str, **config):
    """Configure a service in the global factory.

    Args:
        service_name: Name of the service to configure
        **config: Configuration parameters
    """
    factory = get_service_factory()
    factory.registry.update_configuration(service_name, config)


def list_available_services() -> List[str]:
    """Get list of all available services.

    Returns:
        List of service names
    """
    return get_service_factory().registry.list_services()


def get_service_metrics() -> Dict[str, Dict]:
    """Get metrics for all active services.

    Returns:
        Dictionary of service metrics
    """
    return get_service_factory().get_service_metrics()


def shutdown_all_services():
    """Shutdown all services in the global factory."""
    global _global_factory
    with _factory_lock:
        if _global_factory:
            _global_factory.shutdown_services()
            _global_factory = None

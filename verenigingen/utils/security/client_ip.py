"""
Client IP Detection Utility for API Security Framework

Provides secure client IP detection with trusted proxy support.
This module handles the complexity of extracting real client IPs
when requests pass through reverse proxies and load balancers.

SECURITY CONSIDERATIONS:
- X-Forwarded-For can be spoofed by clients
- Only trust X-Forwarded-For when REMOTE_ADDR is a known trusted proxy
- Configure trusted proxies in site_config.json under "trusted_proxies"

DEPENDENCY RULES:
- This is a low-level utility module
- MAY import frappe for config and request access
- MUST NOT import from other security modules (to avoid circular imports)
"""

import ipaddress
from typing import List, Optional, Set

import frappe

# Default private network ranges commonly used by proxies/load balancers
DEFAULT_TRUSTED_RANGES = [
    "127.0.0.0/8",  # Loopback
    "10.0.0.0/8",  # Private Class A
    "172.16.0.0/12",  # Private Class B
    "192.168.0.0/16",  # Private Class C
    "::1/128",  # IPv6 loopback
    "fc00::/7",  # IPv6 private
    "fe80::/10",  # IPv6 link-local
]


def _parse_ip_network(network_str: str) -> Optional[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Parse an IP network string safely.

    Args:
        network_str: IP address or CIDR notation (e.g., "192.168.1.1" or "10.0.0.0/8")

    Returns:
        Parsed network object or None if invalid
    """
    try:
        # Handle single IPs by converting to /32 or /128 network
        if "/" not in network_str:
            try:
                addr = ipaddress.ip_address(network_str.strip())
                if isinstance(addr, ipaddress.IPv4Address):
                    return ipaddress.IPv4Network(f"{network_str}/32")
                else:
                    return ipaddress.IPv6Network(f"{network_str}/128")
            except ValueError:
                return None
        return ipaddress.ip_network(network_str.strip(), strict=False)
    except ValueError:
        return None


def _get_trusted_proxy_networks() -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Get list of trusted proxy networks from configuration.

    Configuration in site_config.json:
        {
            "trusted_proxies": ["10.0.0.0/8", "192.168.1.100"],
            "trust_private_networks": true  // Optional, defaults to true
        }

    Returns:
        List of parsed network objects
    """
    networks = []

    # Check if we should trust private networks (default: true for backward compatibility)
    trust_private = frappe.conf.get("trust_private_networks", True)
    if trust_private:
        for net_str in DEFAULT_TRUSTED_RANGES:
            net = _parse_ip_network(net_str)
            if net:
                networks.append(net)

    # Add explicitly configured trusted proxies
    configured_proxies = frappe.conf.get("trusted_proxies", [])
    if isinstance(configured_proxies, str):
        configured_proxies = [configured_proxies]

    for proxy in configured_proxies:
        net = _parse_ip_network(proxy)
        if net:
            networks.append(net)

    return networks


def _is_trusted_proxy(ip_str: str, trusted_networks: List) -> bool:
    """
    Check if an IP address is within trusted proxy networks.

    Args:
        ip_str: IP address string to check
        trusted_networks: List of trusted network objects

    Returns:
        True if IP is in a trusted network
    """
    if not ip_str or ip_str in ("unknown", "test_environment"):
        return False

    try:
        addr = ipaddress.ip_address(ip_str)
        for network in trusted_networks:
            # Handle IPv4/IPv6 mismatch
            if isinstance(addr, ipaddress.IPv4Address) and isinstance(network, ipaddress.IPv4Network):
                if addr in network:
                    return True
            elif isinstance(addr, ipaddress.IPv6Address) and isinstance(network, ipaddress.IPv6Network):
                if addr in network:
                    return True
    except ValueError:
        # Invalid IP address format
        return False

    return False


def _parse_x_forwarded_for(header_value: str) -> List[str]:
    """
    Parse X-Forwarded-For header into list of IPs.

    Format: "client, proxy1, proxy2"
    The leftmost IP is the original client (if not spoofed).

    Args:
        header_value: X-Forwarded-For header value

    Returns:
        List of IP addresses (leftmost = client, rightmost = last proxy)
    """
    if not header_value:
        return []

    ips = []
    for ip in header_value.split(","):
        ip = ip.strip()
        if ip:
            # Remove port if present (e.g., "192.168.1.1:12345")
            if ":" in ip and not ip.startswith("["):
                # IPv4 with port
                ip = ip.rsplit(":", 1)[0]
            elif ip.startswith("[") and "]:" in ip:
                # IPv6 with port: [::1]:8000
                ip = ip.rsplit("]:", 1)[0] + "]"
                ip = ip.strip("[]")
            ips.append(ip)

    return ips


def get_client_ip() -> str:
    """
    Get the real client IP address, handling proxies securely.

    Security approach (trusted proxy strategy):
    1. Get REMOTE_ADDR (immediate connection)
    2. If REMOTE_ADDR is a trusted proxy, look at X-Forwarded-For
    3. Walk X-Forwarded-For from right to left, finding the first non-trusted IP
    4. That's the real client IP

    This prevents IP spoofing because:
    - Untrusted clients can set X-Forwarded-For, but REMOTE_ADDR is their real IP
    - Trusted proxies append to X-Forwarded-For (can't be spoofed from outside)
    - We only trust the chain from the rightmost trusted proxy

    Returns:
        Client IP address string, or "unknown" if not determinable
    """
    # Handle test environments gracefully
    try:
        if not hasattr(frappe.local, "request") or not frappe.local.request:
            return "test_environment"

        request = frappe.local.request
        environ = getattr(request, "environ", {})
    except (AttributeError, RuntimeError):
        return "test_environment"

    # Get REMOTE_ADDR (immediate connection)
    remote_addr = environ.get("REMOTE_ADDR", "unknown")

    if remote_addr in ("unknown", ""):
        return "unknown"

    # Get trusted proxy networks
    trusted_networks = _get_trusted_proxy_networks()

    # If no trusted networks configured or REMOTE_ADDR is not trusted, return REMOTE_ADDR
    if not trusted_networks or not _is_trusted_proxy(remote_addr, trusted_networks):
        return remote_addr

    # REMOTE_ADDR is a trusted proxy - check X-Forwarded-For
    # Try multiple header names (different proxies use different conventions)
    xff_headers = ["HTTP_X_FORWARDED_FOR", "X-Forwarded-For", "X_FORWARDED_FOR"]
    xff_value = None

    for header in xff_headers:
        xff_value = environ.get(header)
        if xff_value:
            break

    # Also check Werkzeug's access_route if available
    if not xff_value and hasattr(request, "access_route") and request.access_route:
        # access_route is already parsed, use it directly
        forwarded_ips = list(request.access_route)
    else:
        forwarded_ips = _parse_x_forwarded_for(xff_value) if xff_value else []

    if not forwarded_ips:
        # No X-Forwarded-For, but REMOTE_ADDR is trusted proxy
        # This shouldn't normally happen - return the proxy IP
        return remote_addr

    # Walk X-Forwarded-For from right to left
    # Find the first IP that is NOT a trusted proxy
    for ip in reversed(forwarded_ips):
        if not _is_trusted_proxy(ip, trusted_networks):
            return ip

    # All IPs in chain are trusted proxies (unusual)
    # Return leftmost (original client per spec)
    return forwarded_ips[0] if forwarded_ips else remote_addr


def get_client_ip_with_info() -> dict:
    """
    Get client IP with additional debug information.

    Useful for troubleshooting proxy configurations.

    Returns:
        Dict with:
            - client_ip: The determined client IP
            - remote_addr: The REMOTE_ADDR value
            - x_forwarded_for: The X-Forwarded-For header value
            - is_proxied: Whether request came through a trusted proxy
            - trust_chain: List of IPs in the forwarding chain
    """
    try:
        if not hasattr(frappe.local, "request") or not frappe.local.request:
            return {
                "client_ip": "test_environment",
                "remote_addr": None,
                "x_forwarded_for": None,
                "is_proxied": False,
                "trust_chain": [],
            }

        request = frappe.local.request
        environ = getattr(request, "environ", {})
    except (AttributeError, RuntimeError):
        return {
            "client_ip": "test_environment",
            "remote_addr": None,
            "x_forwarded_for": None,
            "is_proxied": False,
            "trust_chain": [],
        }

    remote_addr = environ.get("REMOTE_ADDR", "unknown")
    xff_value = environ.get("HTTP_X_FORWARDED_FOR", "")
    trusted_networks = _get_trusted_proxy_networks()
    is_proxied = _is_trusted_proxy(remote_addr, trusted_networks) if remote_addr != "unknown" else False
    trust_chain = _parse_x_forwarded_for(xff_value) if xff_value else []

    return {
        "client_ip": get_client_ip(),
        "remote_addr": remote_addr,
        "x_forwarded_for": xff_value or None,
        "is_proxied": is_proxied,
        "trust_chain": trust_chain,
    }

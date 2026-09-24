"""Discover the server's LAN address without sending packets or using a public-IP service."""
import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit


def usable_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return not (address.is_loopback or address.is_unspecified or address.is_link_local
                or address.is_multicast or address.is_reserved)


def detect_lan_ip():
    override = os.environ.get("POSE_LAN_IP")
    if override:
        if not usable_ipv4(override):
            raise ValueError("POSE_LAN_IP must be a reachable, non-loopback IPv4 address")
        return override
    try:
        # UDP connect selects the default route's local address; no send() is performed.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
            if usable_ipv4(address):
                return address
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            if usable_ipv4(info[4][0]):
                return info[4][0]
    except OSError:
        pass
    return None


def configured_public_url():
    value = os.environ.get("POSE_PUBLIC_URL", "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("POSE_PUBLIC_URL must be an http(s) origin, e.g. https://pose.example.com")
    # Accessing port also checks for malformed or out-of-range port numbers.
    parsed.port
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def join_url(base_url, lan_ip, public_url=None):
    if public_url:
        return public_url
    parsed = urlsplit(base_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
    host = parsed.hostname or ""
    local = host == "localhost" or host.endswith(".localhost")
    try:
        address = ipaddress.ip_address(host)
        local = local or address.is_loopback or address.is_unspecified
    except ValueError:
        pass
    if local:
        if not lan_ip:
            return None  # Never advertise localhost as a shareable URL.
        authority = lan_ip + (f":{parsed.port}" if parsed.port is not None else "")
    else:
        # Preserve a LAN address or TLS hostname, plus the external (e.g. Vite) port.
        authority = parsed.netloc
    return urlunsplit((scheme, authority, "/", "", ""))

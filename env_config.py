from __future__ import annotations

import ipaddress
import math
import os


def env_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    aliases: tuple[str, ...] = (),
) -> int:
    source_name = name
    raw_value = os.environ.get(name)
    if raw_value is None:
        for alias in aliases:
            raw_value = os.environ.get(alias)
            if raw_value is not None:
                source_name = alias
                break
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(
            f"{source_name} must be an integer from {minimum} to {maximum}; "
            f"got {raw_value!r}."
        ) from error
    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{source_name} must be from {minimum} to {maximum}; got {value}."
        )
    return value


def env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as error:
        raise RuntimeError(
            f"{name} must be a number from {minimum} to {maximum}; got {raw_value!r}."
        ) from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be from {minimum} to {maximum}; got {value!r}.")
    return value


def env_bool(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be a boolean (1/0, true/false, yes/no, or on/off); "
        f"got {raw_value!r}."
    )


def env_ip_networks(
    name: str,
    default: str = "",
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw_value = os.environ.get(name, default)
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw_value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError as error:
            raise RuntimeError(f"{name} contains an invalid network: {candidate!r}.") from error
        minimum_prefix = 8 if network.version == 4 else 32
        if network.prefixlen < minimum_prefix or network.is_multicast or network.is_unspecified:
            raise RuntimeError(f"{name} contains an unsafe broad network: {candidate!r}.")
        networks.append(network)
    return tuple(networks)

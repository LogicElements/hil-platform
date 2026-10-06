"""In-process registry of simulated serial buses, used by the ``hilsim://`` URL handler."""

import threading
from collections.abc import Mapping, Sequence
from typing import Protocol

from serial import SerialException

LineSettings = tuple[object, ...]


class Endpoint(Protocol):
    def line_settings(self) -> LineSettings: ...

    def receive(self, data: bytes, settings: LineSettings) -> None: ...

    def bus_closed(self) -> None: ...


class SimBus:
    """Ports of one simulated wire: what one port writes, all the others receive."""

    def __init__(self, key: str, name: str, ports: Sequence[str]) -> None:
        self.key = key
        self.name = name
        self.ports = tuple(ports)
        self._lock = threading.Lock()
        self._attached: dict[str, Endpoint] = {}

    def attach(self, port: str, endpoint: Endpoint) -> None:
        with self._lock:
            if port in self._attached:
                raise SerialException(f"simulated port {self.key}/{port} is already open")
            self._attached[port] = endpoint

    def detach(self, endpoint: Endpoint) -> None:
        with self._lock:
            for port, attached in list(self._attached.items()):
                if attached is endpoint:
                    del self._attached[port]

    def deliver(self, sender: Endpoint, data: bytes) -> None:
        settings = sender.line_settings()
        with self._lock:
            receivers = [e for e in self._attached.values() if e is not sender]
        for receiver in receivers:
            receiver.receive(data, settings)

    def close(self) -> None:
        with self._lock:
            endpoints = list(self._attached.values())
            self._attached.clear()
        for endpoint in endpoints:
            endpoint.bus_closed()


_lock = threading.Lock()
_ports: dict[tuple[str, str], SimBus] = {}


def register(key: str, buses: Mapping[str, Sequence[str]]) -> None:
    """Create the buses of the device with registry key ``key``."""
    new: dict[tuple[str, str], SimBus] = {}
    for name, ports in buses.items():
        bus = SimBus(key, name, ports)
        for port in ports:
            new[(key, port)] = bus
    with _lock:
        taken = [f"{k}/{p}" for k, p in new if (k, p) in _ports]
        if taken:
            raise ValueError(f"simulated ports already registered: {', '.join(taken)}")
        _ports.update(new)


def unregister(key: str) -> None:
    with _lock:
        keys = [k for k in _ports if k[0] == key]
        buses = {id(_ports[k]): _ports[k] for k in keys}
        for k in keys:
            del _ports[k]
    for bus in buses.values():
        bus.close()


def attach(key: str, port: str, endpoint: Endpoint) -> SimBus:
    with _lock:
        bus = _ports.get((key, port))
    if bus is None:
        raise SerialException(f"no simulated serial port {key}/{port} (is the device open?)")
    bus.attach(port, endpoint)
    return bus

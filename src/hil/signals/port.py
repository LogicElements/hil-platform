"""Base of signals that talk through a serial port."""

import threading
from typing import ClassVar

from serial import Serial

from hil.config.models import SerialParams
from hil.recording import Recorder
from hil.resources import SerialLink, port_settings
from hil.signals.base import Signal


class PortSignal(Signal):
    """A terminal with a serial port, opened with the line parameters of the DUT.

    Open the port (configure or open) before the DUT is powered, so output right after
    power-on is captured; safe_state of serial signals runs at test teardown after the
    power is off.
    """

    read_timeout_s: ClassVar[float] = 0.01

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder)
        self.link = link
        self.params = SerialParams()
        self.alias = name
        self._port: Serial | None = None
        self._port_lock = threading.RLock()

    def configure(self, alias: str, params: SerialParams) -> None:
        """Use the DUT signal name ``alias`` for artifacts and the DUT's parameters; open."""
        with self._port_lock:
            changed = params != self.params
            self.alias = alias
            self.params = params
            if changed and self._port is not None:
                self._port.apply_settings(port_settings(params))
        if changed:
            self._event("configure", alias=alias, **params.model_dump())
        self.open()

    def open(self) -> None:
        """Open the port now (it is otherwise opened on first use)."""
        _ = self.port

    @property
    def is_open(self) -> bool:
        return self._port is not None

    @property
    def port(self) -> Serial:
        with self._port_lock:
            if self._port is None:
                port = self.link.open(self.params, timeout=self.read_timeout_s)
                self._port = port
                self._on_open(port)
            return self._port

    def _on_open(self, port: Serial) -> None:
        """Start background work on a freshly opened port."""

    def _on_close(self) -> None:
        """Stop background work before the port is closed."""

    def close(self) -> None:
        with self._port_lock:
            port, self._port = self._port, None
            if port is not None:
                try:
                    self._on_close()
                finally:
                    port.close()

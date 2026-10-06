"""Common base of signal objects."""

from typing import Any, ClassVar

from hil.recording import Recorder


class Signal:
    """A wired station terminal, typed by its kind."""

    kind: ClassVar[str] = ""

    def __init__(self, name: str, recorder: Recorder) -> None:
        self.name = name
        self.recorder = recorder

    def safe_state(self) -> None:
        """Bring the terminal into its safe state."""

    def close(self) -> None:
        """Release what the signal holds (ports, threads); called when the station closes."""

    def _event(self, action: str, **data: Any) -> None:
        self.recorder.event(self.name, action, **data)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"

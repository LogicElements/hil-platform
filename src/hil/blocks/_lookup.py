"""Shared name lookup of the blocks."""

from collections.abc import Mapping

from hil.errors import ConfigError, SignalUnavailable


def lookup[S](
    name: str,
    signals: Mapping[str, S],
    kind: str,
    profile_terminals: Mapping[str, str] | None,
) -> S:
    """Find the wired terminal ``name`` of ``kind``.

    With ``profile_terminals`` (terminal name -> kind) a name that the profile does not
    define, or that has another kind, is a configuration error (a typo in a test) and
    not a skip. A terminal of the right kind that is not wired is ``SignalUnavailable``.
    """
    if profile_terminals is not None:
        profile_kind = profile_terminals.get(name)
        if profile_kind is None:
            raise ConfigError(f"terminal {name!r} is not defined in the profile")
        if profile_kind != kind:
            raise ConfigError(f"terminal {name!r} is a {profile_kind} terminal, not a {kind}")
    try:
        return signals[name]
    except KeyError:
        raise SignalUnavailable(f"no {kind} terminal {name!r} on this station") from None

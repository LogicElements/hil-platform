# Analogová část balíčku `hil` – implementační plán (plán 4 ze 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Cíl:** analogové svorky `analog_out` a `analog_in`, blok `AnalogBlock` (přidělování dvou generátorů, výstupní a měřicí multiplexer, `follow`, `measure`), simulovaný ovladač `sim_ad3`, ovladač `analog_discovery_3` nad WaveForms SDK, zapojení analogu na stanovištích `sim` a `lab-a`, HW testy a dokumentace. Hardware zatím není k dispozici. Vrstva ctypes se testuje proti falešné knihovně dwf.

**Architektura:** Prostředky `AwgChannel` a `ScopeChannel` jsou tenké dataclassy nad zařízeními s protokoly `AwgDevice` a `ScopeDevice`. Průběh generátoru popisuje `Waveform`. Stav výstupů drží `AnalogRouter`: který generátor budí kterou svorku, přidělování a pořadí přepínání relé. Stanoviště ho vytvoří ze sekce `analog` před signály. Měřicí multiplexer jednoho kanálu scope drží `ScopeMux`. Signály `AnalogOut` a `AnalogIn` volají router a mux, `AnalogBlock` nad nimi nabízí operace podle jmen svorek. Ovladač AD3 používá `DwfLibrary` (`hil.drivers.dwf`), tenkou vrstvu ctypes s pythonovskými metodami.

**Tech stack:** Python ≥ 3.12, numpy, pydantic v2, pytest, ctypes, WaveForms SDK (systémová knihovna `libdwf.so` / `dwf.dll`, v testech nahrazená `tests/drivers/fake_dwf.py`).

**Spec:** [doc/specs/2026-10-05-hil-python-package-design.md](../specs/2026-10-05-hil-python-package-design.md), kap. 3.2 (sekce `analog`, sdílení kanálu scope), 4.2, 4.3, 4.4, 5.1, 5.2 (AnalogBlock, bezpečný stav analogu), 6.1, 9, 10. Navazuje na plány [1](2026-10-05-hil-jadro.md), [2](2026-10-05-hil-komunikace.md) a [3](2026-10-06-hil-ovladace.md), všechny jsou hotové na `main`.

## Global Constraints

- `requires-python = ">=3.12"`, CI na `ubuntu-latest` a `windows-latest`, Python 3.12, 3.13, 3.14.
- Zdrojový kód včetně komentářů, docstringů, zpráv výjimek a výstupu CLI je anglicky. Dokumentace v `doc/` je česky.
- Jediná nová runtime závislost je `numpy>=1.26`. WaveForms SDK je systémová knihovna, načítá se až v `open()` ovladače `analog_discovery_3`.
- mypy strict platí pro `hil.config.*`, `hil.blocks.*`, `hil.signals.*` a `hil.comm.*`. Pole numpy se typují `NDArray[np.float64]` z `numpy.typing`.
- Všechna časová razítka jsou z `hil.clock.now()` (= `time.perf_counter()`), v sekundách.
- Vytvoření zařízení nedělá žádné I/O, hardware se otevírá v `Device.open()`. `open`/`close`/`safe_state` hlásí selhání jako `DeviceError` (nebo podtřídu).
- Generátory AD3 mají rozsah ±5 V, scope ±25 V (rozsah 50 V špička–špička). Napětí mimo rozsah generátoru je `ValueError` dřív, než se cokoli přepne.
- Relé `select` v klidu (NC) vybírá generátor 1 (`analog.generators[0]`), sepnuté (NO) generátor 2. Relé `connect` sepnuté připojuje svorku k DUT.
- Pořadí přepnutí výstupu: nastavit a spustit generátor, potom `select` (jen při změně, předtím rozepnout `connect`), potom `connect`. Každý krok je samostatný zápis relé.
- Před každým commitem musí projít: `ruff format .`, `ruff check .`, `mypy`, `python -m pytest` a `python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml`. Nástroje se spouštějí z venv: `.venv/Scripts/python -m pytest`, `.venv/Scripts/ruff`, `.venv/Scripts/mypy` (systémový Python pytest nemá).
- Pracuje se na větvi `main`, bez vlastních větví, bez push. Commit zprávy česky ve stylu repozitáře, bez řádků `Co-Authored-By`.
- Když `ruff check` hlásí E501 u dlouhého řetězce v kódu z plánu, řetězec se rozdělí. Chování se nemění.

## Review Focus

1. **Bezpečný stav mezi testy uvolní generátory:** test obsadí oba generátory, teardown nastaví bezpečný stav a další test musí dostat oba generátory volné, i když teardown narazil na chybu relé. Test: úkol 5 `test_generators_free_after_safe_state`, úkol 3 `test_safe_state_frees_generator_even_if_relay_fails`.
2. **Zápis relé selže uprostřed přepínání výstupu** (timeout sběrnice): generátor nezůstane běžet bez svorky a přidělení se neztratí. Test: úkol 3 `test_failed_routing_stops_generator`.
3. **Napětí mimo ±5 V nebo arbitrární průběh delší než buffer:** `ValueError`, žádné relé se nepřepne a generátor zůstane volný. Testy: úkol 3 `test_out_of_range_voltage_switches_nothing`, úkol 7 `test_out_of_range_rejected`, `test_arbitrary_longer_than_buffer`.
4. **Měření po bezpečném stavu:** bezpečný stav rozepnul relé `connect`, další `measure()` na stejné svorce musí relé znovu sepnout a počkat `settle_s`, ne měřit odpojený vstup. Test: úkol 4 `test_reconnects_after_safe_state`.
5. **Dlouhý záznam ztratí vzorky nebo AD3 přestane odpovídat:** `DeviceError` nebo `DeviceTimeout` do `n / rate + 2 s`, nikdy nekonečné čekání. Totéž platí pro AD3 otevřené v programu WaveForms: srozumitelná `DeviceNotFound`. Testy: úkol 6 `test_scope_record_lost_samples`, `test_scope_single_timeout`, úkol 7 `test_device_in_use`.

---

## Struktura souborů

```
pyproject.toml                          # + numpy
src/hil/config/models.py                # + AnalogConfig, StationConfig.analog, validation of sharing
src/hil/resources.py                    # + Waveform, AwgDevice, ScopeDevice, AwgChannel, ScopeChannel
src/hil/drivers/sim/ad3.py              # driver sim_ad3
src/hil/drivers/sim/__init__.py         # registers sim_ad3
src/hil/drivers/dwf.py                  # DwfLibrary: thin ctypes layer over the WaveForms SDK
src/hil/drivers/analog_discovery.py     # driver analog_discovery_3
src/hil/drivers/__init__.py             # registers analog_discovery_3
src/hil/signals/analog.py               # AnalogRouter, AnalogOut, ScopeMux, AnalogIn, Measurement
src/hil/signals/__init__.py             # exports
src/hil/blocks/analog.py                # AnalogBlock
src/hil/blocks/__init__.py              # exports
src/hil/station.py                      # builds analog terminals, station.analog
src/hil/cli.py                          # hil info lists the analog block
src/hil/stations/sim.yaml               # analog terminals on sim_ad3 and rel2
stations/lab-a.yaml                     # ad3, analog section, AO.*, AI.*
examples/dut.yaml, examples/tests/test_door_alarm.py
tests/conftest.py                       # fixture no_analog_station
tests/config/test_models.py
tests/test_resources.py                 # new
tests/drivers/test_sim_ad3.py           # new
tests/drivers/fake_dwf.py               # new: fake WaveForms SDK library
tests/drivers/test_dwf.py               # new
tests/drivers/test_analog_discovery.py  # new
tests/signals/test_analog_out.py        # new
tests/signals/test_analog_in.py         # new
tests/test_station_analog.py            # new
tests/test_station.py, tests/test_dut.py, tests/test_cli.py, tests/test_pytest_plugin.py
tests/hw/test_station_hw.py             # AD3 loopback, analog multiplexer loopback
doc/software/konfigurace.md, testy.md, hw-testy.md, nasazeni.md
```

---

### Úkol 1: Konfigurace – sekce `analog` a sdílení kanálu scope

**Files:**
- Modify: `src/hil/config/models.py`
- Test: `tests/config/test_models.py`

**Interfaces:**
- Produces: `AnalogConfig(generators: list[Ref])` (přesně 2 prvky), `StationConfig.analog: AnalogConfig | None = None`. Validace v `StationConfig._check_references`:
  - svorka `analog_out` se `select` vyžaduje sekci `analog`,
  - kanál scope smí sdílet víc svorek `analog_in`, jen když má každá z nich `connect`,
  - generátor smí být použit jen jako `direct` jedné svorky,
  - generátory se nesmí opakovat a jejich zařízení musí existovat.

- [ ] **Step 1: Napsat padající testy**

Na konec `tests/config/test_models.py` přidat (funkce `station(**overrides)` už v souboru je):

```python
ANALOG_DEVICES = {
    "rel1": {"driver": "sim_relay", "channels": 8},
    "rel2": {"driver": "sim_relay", "channels": 16},
    "ad3": {"driver": "sim_ad3"},
}


def analog_station(terminals, analog=None):
    data = {"devices": ANALOG_DEVICES, "terminals": terminals}
    if analog is not None:
        data["analog"] = analog
    return station(**data)


def test_analog_section():
    cfg = analog_station(
        {
            "AO.0": {"kind": "analog_out", "direct": "ad3.awg1"},
            "AO.1": {"kind": "analog_out", "select": "rel2.0", "connect": "rel2.1"},
        },
        analog={"generators": ["ad3.awg1", "ad3.awg2"]},
    )
    assert cfg.analog is not None
    assert [str(g) for g in cfg.analog.generators] == ["ad3.awg1", "ad3.awg2"]


def test_station_without_analog_section():
    assert station().analog is None


def test_mux_output_needs_analog_section():
    with pytest.raises(ValidationError, match=r"'AO.1' uses the output multiplexer"):
        analog_station({"AO.1": {"kind": "analog_out", "select": "rel2.0", "connect": "rel2.1"}})


@pytest.mark.parametrize("generators", [["ad3.awg1"], ["ad3.awg1", "ad3.awg2", "ad3.awg1"]])
def test_analog_needs_two_generators(generators):
    with pytest.raises(ValidationError, match="generators"):
        analog_station({}, analog={"generators": generators})


def test_analog_generators_differ():
    with pytest.raises(ValidationError, match="must differ"):
        analog_station({}, analog={"generators": ["ad3.awg1", "ad3.awg1"]})


def test_analog_generator_unknown_device():
    with pytest.raises(ValidationError, match=r"generator nope.awg1 refers to unknown device"):
        analog_station({}, analog={"generators": ["nope.awg1", "ad3.awg2"]})


def test_generator_used_by_other_terminal():
    with pytest.raises(ValidationError, match=r"generator ad3.awg1 is also used by terminal 'X1.1'"):
        analog_station(
            {"X1.1": {"kind": "switch", "relay": "ad3.awg1"}},
            analog={"generators": ["ad3.awg1", "ad3.awg2"]},
        )


def test_two_direct_outputs_on_one_generator():
    with pytest.raises(ValidationError, match=r"ad3.awg1 is used by both 'AO.0' and 'AO.1'"):
        analog_station(
            {
                "AO.0": {"kind": "analog_out", "direct": "ad3.awg1"},
                "AO.1": {"kind": "analog_out", "direct": "ad3.awg1"},
            }
        )


def test_shared_scope_with_connect_relays():
    cfg = analog_station(
        {
            "AI.1": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.8"},
            "AI.2": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.9"},
        }
    )
    assert set(cfg.terminals) == {"AI.1", "AI.2"}


def test_shared_scope_needs_connect_relays():
    with pytest.raises(ValidationError, match=r"ad3.ch1 is shared by 'AI.1', 'AI.2'"):
        analog_station(
            {
                "AI.1": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.8"},
                "AI.2": {"kind": "analog_in", "scope": "ad3.ch1"},
            }
        )


def test_scope_used_by_other_kind():
    with pytest.raises(ValidationError, match=r"ad3.ch1 is used by both 'X1.1' and 'AI.1'"):
        analog_station(
            {
                "X1.1": {"kind": "switch", "relay": "ad3.ch1"},
                "AI.1": {"kind": "analog_in", "scope": "ad3.ch1"},
            }
        )


def test_connect_relay_used_twice():
    with pytest.raises(ValidationError, match=r"rel2.8 is used by both 'AI.1' and 'AI.2'"):
        analog_station(
            {
                "AI.1": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.8"},
                "AI.2": {"kind": "analog_in", "scope": "ad3.ch2", "connect": "rel2.8"},
            }
        )
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/config/test_models.py -q`
Expected: FAIL. Nové testy selžou (`analog` je neznámé pole a sdílení scope je zakázané). Ostatní testy v souboru projdou.

- [ ] **Step 3: Implementace**

V `src/hil/config/models.py`:

1. Do `__all__` přidat `"AnalogConfig"` (abecedně, před `"DebugParams"`).
2. Za třídu `DebugTerminal` (před `StationTerminal`) přidat:

```python
class AnalogConfig(_Strict):
    """Generators switched by the output multiplexers.

    ``generators[0]`` is selected by a released ``select`` relay (NC contact),
    ``generators[1]`` by an operated one (NO contact).
    """

    generators: list[Ref] = Field(min_length=2, max_length=2)
```

3. Do `StationConfig` za `devices` přidat pole `analog: AnalogConfig | None = None` a celý validátor `_check_references` nahradit:

```python
    @model_validator(mode="after")
    def _check_references(self) -> "StationConfig":
        used: dict[ResourceRef, str] = {}
        # scope channel -> (terminal, has a connect relay); a scope may be shared
        scopes: dict[ResourceRef, list[tuple[str, bool]]] = {}
        for name, terminal in self.terminals.items():
            refs = terminal_refs(terminal)
            devices = [ref.device for ref in refs]
            if isinstance(terminal, DebugTerminal):
                devices.append(terminal.probe)
            for device in devices:
                if device not in self.devices:
                    raise ValueError(f"terminal {name!r} refers to unknown device {device!r}")
            if isinstance(terminal, AnalogOutTerminal) and terminal.select is not None:
                if self.analog is None:
                    raise ValueError(
                        f"terminal {name!r} uses the output multiplexer; list its generators "
                        "in 'analog: {generators: [<generator 1>, <generator 2>]}'"
                    )
            if isinstance(terminal, AnalogInTerminal):
                scopes.setdefault(terminal.scope, []).append((name, terminal.connect is not None))
                refs = [ref for ref in refs if ref != terminal.scope]
            for ref in refs:
                if ref in used:
                    raise ValueError(f"resource {ref} is used by both {used[ref]!r} and {name!r}")
                used[ref] = name
        for scope, users in scopes.items():
            if scope in used:
                raise ValueError(
                    f"resource {scope} is used by both {used[scope]!r} and {users[0][0]!r}"
                )
            if len(users) > 1 and not all(has_connect for _, has_connect in users):
                names = ", ".join(repr(name) for name, _ in users)
                raise ValueError(
                    f"scope channel {scope} is shared by {names}; every terminal sharing "
                    "a scope channel needs a 'connect' relay"
                )
        if self.analog is not None:
            self._check_generators(self.analog.generators, used)
        return self

    def _check_generators(
        self, generators: list[ResourceRef], used: dict[ResourceRef, str]
    ) -> None:
        for ref in generators:
            if ref.device not in self.devices:
                raise ValueError(
                    f"analog generator {ref} refers to unknown device {ref.device!r}"
                )
        if generators[0] == generators[1]:
            raise ValueError(f"analog generators must differ, got {generators[0]} twice")
        for ref in generators:
            owner = used.get(ref)
            if owner is None:
                continue
            terminal = self.terminals[owner]
            if not (isinstance(terminal, AnalogOutTerminal) and terminal.direct == ref):
                raise ValueError(f"analog generator {ref} is also used by terminal {owner!r}")
```

- [ ] **Step 4: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest tests/config -q`
Expected: PASS (včetně dosavadních testů).

- [ ] **Step 5: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q`
```bash
git add src/hil/config/models.py tests/config/test_models.py
git commit -m "feat: sekce analog ve stanovišti a sdílení kanálu scope"
```

---

### Úkol 2: Prostředky `AwgChannel`, `ScopeChannel`, `Waveform` a ovladač `sim_ad3`

**Files:**
- Modify: `pyproject.toml` (závislost numpy)
- Modify: `src/hil/resources.py`
- Create: `src/hil/drivers/sim/ad3.py`
- Modify: `src/hil/drivers/sim/__init__.py`
- Test: `tests/test_resources.py` (nový), `tests/drivers/test_sim_ad3.py` (nový)

**Interfaces:**
- Produces (v `hil.resources`):
  - `Waveform` (frozen dataclass) s poli `kind: Literal["dc", "sine", "square", "arbitrary"]`, `offset`, `amplitude`, `frequency`, `duty`, `samples: tuple[float, ...]`, `rate`. Konstruktory `Waveform.dc(volts)`, `.sine(freq, amp, offset=0.0)`, `.square(freq, amp, offset=0.0, duty=0.5)`, `.arbitrary(samples, rate)`. Vlastnost `peak_v -> float` a metoda `describe() -> dict[str, float | int | str]`.
  - `AwgDevice` (protokol): `name`, `awg_apply(index, wave)`, `awg_start(index)`, `awg_stop(index)`.
  - `ScopeDevice` (protokol): `name`, `scope_acquire(index, rate, n) -> NDArray[np.float64]`.
  - `AwgChannel(device, index)`: `apply(wave)`, `sine(freq, amp, offset=0.0)`, `square(freq, amp, offset=0.0, duty=0.5)`, `dc(volts)`, `arbitrary(samples, rate)`, `start()`, `stop()`. `str()` vrací `"<zařízení>.awg<index+1>"`.
  - `ScopeChannel(device, index)`: `acquire(rate, n) -> NDArray[np.float64]`. `str()` vrací `"<zařízení>.ch<index+1>"`.
- Produces (ovladač `sim_ad3`, třída `hil.drivers.sim.ad3.SimAd3`):
  - kanály `awg1`, `awg2` (`AwgChannel` 0, 1) a `ch1`, `ch2` (`ScopeChannel` 0, 1),
  - stav `waves: list[Waveform | None]`, `running: list[bool]`, `history: list[tuple[float, int, str, Waveform | None]]` (čas, index generátoru, `"apply"`/`"start"`/`"stop"`, průběh), `acquisitions: list[tuple[float, int, float, int]]` (čas, index kanálu, rate, n), `fail_with: Exception | None`, `is_open`,
  - metoda `set_input(channel, dc=0.0, sine=None, noise=0.0)`, kde `sine` je `(freq, amp)`.

- [ ] **Step 1: numpy do závislostí**

V `pyproject.toml` do `dependencies` za `"pyserial>=3.5",` přidat `"numpy>=1.26",`. Potom:

Run: `.venv/Scripts/python -m pip install -e .[dev]`
Expected: nainstaluje numpy.

- [ ] **Step 2: Napsat padající testy**

`tests/test_resources.py`:

```python
import math

import numpy as np
import pytest

from hil.drivers.sim.ad3 import SimAd3, SimAd3Config
from hil.resources import AwgChannel, ScopeChannel, Waveform


def test_dc():
    wave = Waveform.dc(-2.5)
    assert wave.kind == "dc"
    assert wave.peak_v == 2.5
    assert wave.describe() == {"kind": "dc", "volts": -2.5}


def test_sine():
    wave = Waveform.sine(1000, 1.5, offset=-1.0)
    assert (wave.frequency, wave.amplitude, wave.offset) == (1000.0, 1.5, -1.0)
    assert wave.peak_v == 2.5
    assert wave.describe() == {"kind": "sine", "freq": 1000.0, "amp": 1.5, "offset": -1.0}


def test_square():
    wave = Waveform.square(50, 2.0, duty=0.25)
    assert wave.duty == 0.25
    assert wave.describe()["duty"] == 0.25


def test_arbitrary_from_numpy():
    wave = Waveform.arbitrary(np.array([0.0, 1.0, -3.0]), rate=1000)
    assert wave.samples == (0.0, 1.0, -3.0)
    assert wave.peak_v == 3.0
    assert wave.describe() == {"kind": "arbitrary", "samples": 3, "rate": 1000.0}


@pytest.mark.parametrize(
    "make",
    [
        lambda: Waveform.sine(0, 1.0),
        lambda: Waveform.sine(-5, 1.0),
        lambda: Waveform.sine(math.inf, 1.0),
        lambda: Waveform.sine(100, -1.0),
        lambda: Waveform.square(100, 1.0, duty=0.0),
        lambda: Waveform.square(100, 1.0, duty=1.0),
        lambda: Waveform.dc(math.nan),
        lambda: Waveform.arbitrary([], rate=1000),
        lambda: Waveform.arbitrary([0.0, math.nan], rate=1000),
        lambda: Waveform.arbitrary([0.0], rate=0),
    ],
)
def test_invalid_waveforms(make):
    with pytest.raises(ValueError):
        make()


@pytest.fixture
def ad3():
    device = SimAd3("ad3", SimAd3Config())
    device.open()
    return device


def test_channels_delegate_to_the_device(ad3):
    awg = ad3.resource("awg2")
    assert isinstance(awg, AwgChannel)
    assert str(awg) == "ad3.awg2"
    awg.sine(1000, 1.0)
    awg.start()
    assert ad3.waves[1] == Waveform.sine(1000, 1.0)
    assert ad3.running == [False, True]
    awg.stop()
    assert ad3.running == [False, False]
    scope = ad3.resource("ch1")
    assert isinstance(scope, ScopeChannel)
    assert str(scope) == "ad3.ch1"
    assert len(scope.acquire(1000, 10)) == 10


def test_channels_are_hashable_and_compare_by_device_and_index(ad3):
    assert ad3.resource("awg1") == ad3.resource("awg1")
    assert ad3.resource("awg1") != ad3.resource("awg2")
    assert len({ad3.resource("ch1"), ad3.resource("ch1")}) == 1
```

`tests/drivers/test_sim_ad3.py`:

```python
import math

import numpy as np
import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError
from hil.resources import AwgChannel, ScopeChannel, Waveform


def make(**options):
    device = create_device("ad3", DeviceConfig(driver="sim_ad3", **options))
    device.open()
    return device


def test_channels():
    ad3 = make()
    assert set(ad3.channel_names()) == {"awg1", "awg2", "ch1", "ch2"}
    assert isinstance(ad3.resource("awg1"), AwgChannel)
    assert isinstance(ad3.resource("ch2"), ScopeChannel)
    with pytest.raises(ConfigError, match="no channel 'awg3'"):
        ad3.resource("awg3")


def test_apply_start_stop_history():
    ad3 = make()
    wave = Waveform.dc(1.0)
    ad3.awg_apply(0, wave)
    ad3.awg_start(0)
    ad3.awg_stop(0)
    assert [(i, action) for _, i, action, _ in ad3.history] == [
        (0, "apply"),
        (0, "start"),
        (0, "stop"),
    ]
    assert ad3.history[0][3] == wave
    assert ad3.waves[0] is None
    assert ad3.running == [False, False]


def test_start_without_waveform():
    with pytest.raises(DeviceError, match="generator 2 has no waveform"):
        make().awg_start(1)


def test_generator_range():
    ad3 = make()
    with pytest.raises(ValueError, match=r"5.5 V exceeds the generator range"):
        ad3.awg_apply(0, Waveform.sine(100, 3.0, offset=2.5))
    assert ad3.waves == [None, None]


def test_closed_device():
    ad3 = make()
    ad3.close()
    with pytest.raises(DeviceError, match="not open"):
        ad3.awg_apply(0, Waveform.dc(0.0))
    with pytest.raises(DeviceError, match="not open"):
        ad3.scope_acquire(0, 1000, 10)


def test_fail_with():
    ad3 = make()
    ad3.fail_with = DeviceError("boom")
    with pytest.raises(DeviceError, match="boom"):
        ad3.scope_acquire(0, 1000, 10)


def test_scope_reads_configured_input():
    ad3 = make(inputs={"ch1": {"dc": 1.0, "sine": {"freq": 50, "amp": 0.5}}})
    data = ad3.scope_acquire(0, 100_000, 10_000)
    assert data.dtype == np.float64
    assert len(data) == 10_000
    assert float(np.mean(data)) == pytest.approx(1.0, abs=1e-9)
    assert float(np.std(data)) == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)
    assert ad3.acquisitions[-1][1:] == (0, 100_000, 10_000)
    assert float(np.max(np.abs(ad3.scope_acquire(1, 1000, 100)))) == 0.0


def test_noise_is_reproducible():
    a = make(inputs={"ch2": {"noise": 0.1}}, seed=3).scope_acquire(1, 1000, 100)
    b = make(inputs={"ch2": {"noise": 0.1}}, seed=3).scope_acquire(1, 1000, 100)
    assert np.array_equal(a, b)
    assert float(np.std(a)) > 0.05


def test_scope_clips_to_range():
    data = make(inputs={"ch1": {"dc": 40.0}}).scope_acquire(0, 1000, 10)
    assert float(np.max(data)) == 25.0


def test_set_input():
    ad3 = make()
    ad3.set_input("ch2", dc=-3.0, sine=(100, 1.0))
    data = ad3.scope_acquire(1, 10_000, 1000)
    assert float(np.mean(data)) == pytest.approx(-3.0, abs=1e-9)
    with pytest.raises(ValueError, match="no scope channel 'ch3'"):
        ad3.set_input("ch3", dc=1.0)


@pytest.mark.parametrize(("rate", "n"), [(0, 10), (1000, 0)])
def test_invalid_acquisition(rate, n):
    with pytest.raises(ValueError):
        make().scope_acquire(0, rate, n)


def test_safe_state_stops_both_generators():
    ad3 = make()
    for index in (0, 1):
        ad3.awg_apply(index, Waveform.dc(1.0))
        ad3.awg_start(index)
    ad3.safe_state()
    assert ad3.running == [False, False]
    assert ad3.waves == [None, None]
```

- [ ] **Step 3: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/test_resources.py tests/drivers/test_sim_ad3.py -q`
Expected: FAIL s `ImportError` (`Waveform`, `hil.drivers.sim.ad3`).

- [ ] **Step 4: Prostředky v `src/hil/resources.py`**

Importy na začátku souboru doplnit na:

```python
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
import serial
from numpy.typing import ArrayLike, NDArray

from hil.config.models import SerialParams
```

Na konec souboru přidat:

```python
WaveKind = Literal["dc", "sine", "square", "arbitrary"]


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value}")
    return value


def _periodic(freq: float, amp: float) -> tuple[float, float]:
    freq = _finite("frequency", freq)
    amp = _finite("amplitude", amp)
    if freq <= 0:
        raise ValueError(f"frequency must be positive, got {freq}")
    if amp < 0:
        raise ValueError(f"amplitude must not be negative, got {amp}")
    return freq, amp


@dataclass(frozen=True)
class Waveform:
    """Signal of one generator; voltages in volts, frequencies and rates in hertz.

    ``amplitude`` is the peak value (a sine of amplitude 1 V swings from -1 V to +1 V
    around ``offset``). An arbitrary waveform holds its samples in volts and plays
    them at ``rate`` samples per second, repeated.
    """

    kind: WaveKind
    offset: float = 0.0
    amplitude: float = 0.0
    frequency: float = 0.0
    duty: float = 0.5
    samples: tuple[float, ...] = ()
    rate: float = 0.0

    @classmethod
    def dc(cls, volts: float) -> "Waveform":
        return cls("dc", offset=_finite("voltage", volts))

    @classmethod
    def sine(cls, freq: float, amp: float, offset: float = 0.0) -> "Waveform":
        freq, amp = _periodic(freq, amp)
        return cls("sine", offset=_finite("offset", offset), amplitude=amp, frequency=freq)

    @classmethod
    def square(
        cls, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5
    ) -> "Waveform":
        freq, amp = _periodic(freq, amp)
        duty = _finite("duty", duty)
        if not 0 < duty < 1:
            raise ValueError(f"duty must be between 0 and 1, got {duty}")
        return cls(
            "square", offset=_finite("offset", offset), amplitude=amp, frequency=freq, duty=duty
        )

    @classmethod
    def arbitrary(cls, samples: ArrayLike, rate: float) -> "Waveform":
        values = tuple(float(v) for v in np.asarray(samples, dtype=np.float64).ravel())
        if not values:
            raise ValueError("an arbitrary waveform needs at least one sample")
        if not all(math.isfinite(v) for v in values):
            raise ValueError("samples of an arbitrary waveform must be finite numbers")
        rate = _finite("rate", rate)
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        return cls("arbitrary", samples=values, rate=rate)

    @property
    def peak_v(self) -> float:
        """Largest absolute voltage of the waveform."""
        if self.kind == "arbitrary":
            return max(abs(v) for v in self.samples)
        return abs(self.offset) + self.amplitude

    def describe(self) -> dict[str, float | int | str]:
        """Parameters for the event log (without the samples)."""
        if self.kind == "dc":
            return {"kind": "dc", "volts": self.offset}
        if self.kind == "arbitrary":
            return {"kind": "arbitrary", "samples": len(self.samples), "rate": self.rate}
        data: dict[str, float | int | str] = {
            "kind": self.kind,
            "freq": self.frequency,
            "amp": self.amplitude,
            "offset": self.offset,
        }
        if self.kind == "square":
            data["duty"] = self.duty
        return data


class AwgDevice(Protocol):
    """A device with numbered waveform generators."""

    name: str

    def awg_apply(self, index: int, wave: Waveform) -> None: ...

    def awg_start(self, index: int) -> None: ...

    def awg_stop(self, index: int) -> None: ...


class ScopeDevice(Protocol):
    """A device with numbered scope channels; samples are in volts."""

    name: str

    def scope_acquire(self, index: int, rate: float, n: int) -> NDArray[np.float64]: ...


@dataclass(frozen=True)
class AwgChannel:
    device: AwgDevice
    index: int

    def apply(self, wave: Waveform) -> None:
        """Set the waveform; a running generator changes its output at once."""
        self.device.awg_apply(self.index, wave)

    def sine(self, freq: float, amp: float, offset: float = 0.0) -> None:
        self.apply(Waveform.sine(freq, amp, offset))

    def square(self, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5) -> None:
        self.apply(Waveform.square(freq, amp, offset, duty))

    def dc(self, volts: float) -> None:
        self.apply(Waveform.dc(volts))

    def arbitrary(self, samples: Sequence[float] | NDArray[np.float64], rate: float) -> None:
        self.apply(Waveform.arbitrary(samples, rate))

    def start(self) -> None:
        self.device.awg_start(self.index)

    def stop(self) -> None:
        """Stop the generator; its output goes to 0 V."""
        self.device.awg_stop(self.index)

    def __str__(self) -> str:
        return f"{self.device.name}.awg{self.index + 1}"


@dataclass(frozen=True)
class ScopeChannel:
    device: ScopeDevice
    index: int

    def acquire(self, rate: float, n: int) -> NDArray[np.float64]:
        """``n`` samples taken at ``rate`` samples per second, in volts."""
        return self.device.scope_acquire(self.index, rate, n)

    def __str__(self) -> str:
        return f"{self.device.name}.ch{self.index + 1}"
```

- [ ] **Step 5: Ovladač `src/hil/drivers/sim/ad3.py`**

```python
"""Simulated Analog Discovery 3 (driver ``sim_ad3``)."""

import math
from collections.abc import Collection
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import AwgChannel, ScopeChannel, Waveform

_GENERATORS = {"awg1": 0, "awg2": 1}
_SCOPES = {"ch1": 0, "ch2": 1}


class SimSine(DriverConfig):
    freq: float = Field(gt=0)
    amp: float = Field(ge=0)


class SimScopeInput(DriverConfig):
    """Signal at a scope input: DC level, optional sine and Gaussian noise (sigma in V)."""

    dc: float = 0.0
    sine: SimSine | None = None
    noise: float = Field(default=0.0, ge=0)


class SimAd3Config(DriverConfig):
    inputs: dict[Literal["ch1", "ch2"], SimScopeInput] = Field(default_factory=dict)
    # output range of the generators (Analog Discovery 3: ±5 V)
    awg_limit_v: float = Field(default=5.0, gt=0)
    # input range of the scope (Analog Discovery 3: ±25 V); readings are clipped to it
    scope_limit_v: float = Field(default=25.0, gt=0)
    # seed of the noise generator, so that simulated readings are reproducible
    seed: int = 0


@register_driver("sim_ad3")
class SimAd3(Device):
    """Two generators and two scope channels held in memory.

    The scope does not see the generators: it reads the inputs from the configuration
    (or from ``set_input``), the DUT between them is not simulated.
    """

    Config = SimAd3Config
    config: SimAd3Config

    def __init__(self, name: str, config: SimAd3Config) -> None:
        super().__init__(name, config)
        self.waves: list[Waveform | None] = [None, None]
        self.running = [False, False]
        # (time, generator index, "apply" | "start" | "stop", waveform)
        self.history: list[tuple[float, int, str, Waveform | None]] = []
        # (time, scope index, rate, number of samples)
        self.acquisitions: list[tuple[float, int, float, int]] = []
        self.inputs = [
            config.inputs.get("ch1", SimScopeInput()),
            config.inputs.get("ch2", SimScopeInput()),
        ]
        self.fail_with: Exception | None = None
        self.is_open = False
        self._rng = np.random.default_rng(config.seed)

    def channel_names(self) -> Collection[str]:
        return frozenset(_GENERATORS) | frozenset(_SCOPES)

    def resource(self, channel: str) -> object:
        if channel in _GENERATORS:
            return AwgChannel(self, _GENERATORS[channel])
        if channel in _SCOPES:
            return ScopeChannel(self, _SCOPES[channel])
        self._no_channel(channel)

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def safe_state(self) -> None:
        for index in range(2):
            self.awg_stop(index)

    def _check(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")

    def awg_apply(self, index: int, wave: Waveform) -> None:
        with self.lock:
            self._check()
            limit = self.config.awg_limit_v
            if wave.peak_v > limit:
                raise ValueError(
                    f"device {self.name!r}: {wave.peak_v:g} V exceeds the generator "
                    f"range ±{limit:g} V"
                )
            self.waves[index] = wave
            self.history.append((clock.now(), index, "apply", wave))

    def awg_start(self, index: int) -> None:
        with self.lock:
            self._check()
            if self.waves[index] is None:
                raise DeviceError(f"device {self.name!r}: generator {index + 1} has no waveform")
            self.running[index] = True
            self.history.append((clock.now(), index, "start", self.waves[index]))

    def awg_stop(self, index: int) -> None:
        with self.lock:
            self._check()
            self.running[index] = False
            self.waves[index] = None
            self.history.append((clock.now(), index, "stop", None))

    def set_input(
        self,
        channel: str,
        dc: float = 0.0,
        sine: tuple[float, float] | None = None,
        noise: float = 0.0,
    ) -> None:
        """Change the signal at scope input ``channel`` (``ch1`` or ``ch2``)."""
        if channel not in _SCOPES:
            raise ValueError(f"device {self.name!r} has no scope channel {channel!r}")
        signal = SimScopeInput(
            dc=dc,
            sine=None if sine is None else SimSine(freq=sine[0], amp=sine[1]),
            noise=noise,
        )
        with self.lock:
            self.inputs[_SCOPES[channel]] = signal

    def scope_acquire(self, index: int, rate: float, n: int) -> NDArray[np.float64]:
        if not rate > 0 or n < 1:
            raise ValueError(f"invalid acquisition: rate {rate}, {n} samples")
        with self.lock:
            self._check()
            signal = self.inputs[index]
            t = np.arange(n, dtype=np.float64) / rate
            data = np.full(n, signal.dc, dtype=np.float64)
            if signal.sine is not None:
                data += signal.sine.amp * np.sin(2 * math.pi * signal.sine.freq * t)
            if signal.noise:
                data += self._rng.normal(0.0, signal.noise, n)
            limit = self.config.scope_limit_v
            self.acquisitions.append((clock.now(), index, rate, n))
            return np.clip(data, -limit, limit)
```

V `src/hil/drivers/sim/__init__.py`:

```python
"""Simulated drivers for running the platform without hardware."""

from hil.drivers.sim import ad3, di, probe, relay, serial_port

__all__ = ["ad3", "di", "probe", "relay", "serial_port"]
```

Poznámka: `resource()` končí voláním `self._no_channel(channel)`, které vrací `NoReturn`, takže mypy nehlásí chybějící `return`.

- [ ] **Step 6: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest tests/test_resources.py tests/drivers/test_sim_ad3.py -q`
Expected: PASS.

- [ ] **Step 7: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q`
```bash
git add pyproject.toml src/hil/resources.py src/hil/drivers/sim tests/test_resources.py tests/drivers/test_sim_ad3.py
git commit -m "feat: prostředky generátoru a scope, simulovaný ovladač sim_ad3"
```

---
### Úkol 3: Analogové výstupy – `AnalogRouter` a `AnalogOut`

**Files:**
- Create: `src/hil/signals/analog.py`
- Modify: `src/hil/signals/__init__.py`
- Test: `tests/signals/test_analog_out.py` (nový)

**Interfaces:**
- Consumes: `AwgChannel`, `Waveform`, `RelayChannel` (`hil.resources`), `SimAd3`, `SimRelay`.
- Produces (v `hil.signals.analog`, exportováno z `hil.signals`):
  - `AnalogRouter(generators: Sequence[AwgChannel], recorder: Recorder)`: `lock`, `add(out)`, `generator_of(name) -> AwgChannel | None`, `waveform_of(name) -> Waveform | None`, `drive(out, wave)`, `follow(out, other)`, `disconnect(out)`, `safe_state(out)`.
  - `AnalogOut(name, recorder, router, direct=None, select=None, connect=None)`: `kind = "analog_out"`, metody `sine(freq, amp, offset=0.0)`, `square(freq, amp, offset=0.0, duty=0.5)`, `dc(volts)`, `arbitrary(samples, rate)`, `follow(other)`, `disconnect()`, `safe_state()`, vlastnosti `generator -> AwgChannel | None` a `waveform -> Waveform | None`.
  - Události v `events.jsonl`: `waveform` (s `generator` a parametry průběhu), `follow` (s `other`), `disconnect`, `shared_generator` u svorky `direct` (s `generator` a `by`).

- [ ] **Step 1: Napsat padající testy**

`tests/signals/test_analog_out.py`:

```python
import json
from types import SimpleNamespace

import pytest

from hil.drivers.sim.ad3 import SimAd3, SimAd3Config
from hil.drivers.sim.relay import SimRelay, SimRelayConfig
from hil.errors import ConfigError, DeviceError, ResourceConflict
from hil.recording import Recorder
from hil.resources import Waveform
from hil.signals import AnalogOut, AnalogRouter


@pytest.fixture
def rig(tmp_path):
    rel = SimRelay("rel2", SimRelayConfig(channels=8))
    rel.open()
    ad3 = SimAd3("ad3", SimAd3Config())
    ad3.open()
    recorder = Recorder()
    recorder.start_test(tmp_path)
    router = AnalogRouter([ad3.resource("awg1"), ad3.resource("awg2")], recorder)
    out = {"AO.0": AnalogOut("AO.0", recorder, router, direct=ad3.resource("awg1"))}
    # AO.1: select rel2.0, connect rel2.1; AO.2: rel2.2, rel2.3; AO.3: rel2.4, rel2.5
    for i, name in enumerate(["AO.1", "AO.2", "AO.3"]):
        out[name] = AnalogOut(
            name,
            recorder,
            router,
            select=rel.resource(str(2 * i)),
            connect=rel.resource(str(2 * i + 1)),
        )
    yield SimpleNamespace(rel=rel, ad3=ad3, recorder=recorder, router=router, out=out, dir=tmp_path)
    recorder.stop_test()


def events(rig):
    lines = (rig.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    return [json.loads(line) for line in lines]


def frames(rig):
    return [states for _, states in rig.rel.history]


def test_mux_output_prefers_generator_without_direct_terminal(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    assert str(rig.out["AO.1"].generator) == "ad3.awg2"
    assert rig.out["AO.1"].waveform == Waveform.sine(1000, 1.0)
    assert rig.ad3.waves[1] == Waveform.sine(1000, 1.0)
    assert rig.ad3.running == [False, True]
    assert rig.rel.states[0:2] == [True, True]


def test_order_generator_then_select_then_connect(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    started = next(t for t, _, action, _ in rig.ad3.history if action == "start")
    assert frames(rig) == [{0: True}, {1: True}]
    assert started < rig.rel.history[0][0] < rig.rel.history[1][0]


def test_second_output_gets_generator_1_and_marks_direct_terminal(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.2"].dc(1.5)
    assert str(rig.out["AO.2"].generator) == "ad3.awg1"
    assert rig.rel.states[2:4] == [False, True]
    assert {2: True} not in frames(rig)
    shared = [e for e in events(rig) if e["action"] == "shared_generator"]
    assert len(shared) == 1
    assert (shared[0]["source"], shared[0]["generator"], shared[0]["by"]) == (
        "AO.0",
        "ad3.awg1",
        "AO.2",
    )


def test_no_free_generator(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.2"].dc(1.5)
    before = frames(rig)
    with pytest.raises(ResourceConflict, match=r"AO.3: both generators are in use"):
        rig.out["AO.3"].dc(1.0)
    assert frames(rig) == before


def test_direct_output_conflicts_with_mux_on_its_generator(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.2"].dc(1.5)
    with pytest.raises(ResourceConflict, match=r"AO.0: generator ad3.awg1 is in use by AO.2"):
        rig.out["AO.0"].dc(1.0)


def test_direct_output_keeps_its_generator(rig):
    rig.out["AO.0"].sine(10_000, 2.0)
    assert str(rig.out["AO.0"].generator) == "ad3.awg1"
    assert rig.rel.history == []
    rig.out["AO.1"].dc(1.0)
    assert str(rig.out["AO.1"].generator) == "ad3.awg2"
    with pytest.raises(ResourceConflict):
        rig.out["AO.2"].dc(1.0)


def test_waveform_change_keeps_generator_and_relays(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    before = frames(rig)
    rig.out["AO.1"].dc(2.0)
    assert rig.ad3.waves[1] == Waveform.dc(2.0)
    assert rig.ad3.running[1]
    assert frames(rig) == before


def test_follow_shares_generator(rig):
    ao1, ao2 = rig.out["AO.1"], rig.out["AO.2"]
    ao1.sine(1000, 1.0)
    ao2.follow(ao1)
    assert ao2.generator == ao1.generator
    assert rig.rel.states[2:4] == [True, True]
    ao2.dc(1.5)
    assert ao1.waveform == Waveform.dc(1.5)
    assert ("AO.2", "follow") in [(e["source"], e["action"]) for e in events(rig)]


def test_follow_needs_a_signal(rig):
    with pytest.raises(ResourceConflict, match="AO.2: AO.1 has no signal to follow"):
        rig.out["AO.2"].follow(rig.out["AO.1"])


def test_follow_itself(rig):
    rig.out["AO.1"].dc(1.0)
    with pytest.raises(ValueError, match="cannot follow itself"):
        rig.out["AO.1"].follow(rig.out["AO.1"])


def test_follow_moves_terminal_and_frees_old_generator(rig):
    ao1, ao2 = rig.out["AO.1"], rig.out["AO.2"]
    ao1.sine(1000, 1.0)  # generator 2
    ao2.dc(1.5)  # generator 1, select released
    rig.rel.history.clear()
    ao2.follow(ao1)
    assert frames(rig) == [{3: False}, {2: True}, {3: True}]
    assert rig.ad3.running == [False, True]
    assert ao2.generator == ao1.generator


def test_disconnect_stops_generator_when_last_terminal_leaves(rig):
    ao1, ao2, ao3 = rig.out["AO.1"], rig.out["AO.2"], rig.out["AO.3"]
    ao1.sine(1000, 1.0)
    ao2.follow(ao1)
    ao1.disconnect()
    assert rig.rel.states[1] is False
    assert rig.ad3.running[1]
    ao2.disconnect()
    assert rig.ad3.running == [False, False]
    assert ao1.generator is None
    assert ao2.waveform is None
    ao3.dc(1.0)
    assert str(ao3.generator) == "ad3.awg2"


def test_direct_output_follow_rules(rig):
    ao0, ao1 = rig.out["AO.0"], rig.out["AO.1"]
    ao1.sine(1000, 1.0)  # generator 2
    with pytest.raises(ResourceConflict, match="wired directly to ad3.awg1"):
        ao0.follow(ao1)
    ao1.disconnect()
    ao0.sine(10_000, 1.0)
    ao1.follow(ao0)
    assert str(ao1.generator) == "ad3.awg1"
    assert rig.rel.states[0:2] == [False, True]


def test_safe_state_releases_everything(rig):
    rig.out["AO.1"].dc(1.0)
    rig.out["AO.2"].follow(rig.out["AO.1"])
    rig.out["AO.3"].dc(2.0)
    for out in rig.out.values():
        out.safe_state()
    assert rig.rel.states[:6] == [False] * 6
    assert rig.ad3.running == [False, False]
    rig.out["AO.3"].dc(1.0)
    rig.out["AO.0"].dc(1.0)


def test_safe_state_frees_generator_even_if_relay_fails(rig):
    rig.out["AO.1"].dc(1.0)
    rig.rel.fail_with = DeviceError("bus timeout")
    with pytest.raises(DeviceError, match="bus timeout"):
        rig.out["AO.1"].safe_state()
    assert rig.out["AO.1"].generator is None
    assert rig.ad3.running == [False, False]


def test_failed_routing_stops_generator(rig):
    rig.rel.fail_with = DeviceError("bus timeout")
    with pytest.raises(DeviceError, match="bus timeout"):
        rig.out["AO.1"].sine(1000, 1.0)
    assert rig.out["AO.1"].generator is None
    assert rig.ad3.running == [False, False]
    rig.rel.fail_with = None
    rig.out["AO.1"].sine(1000, 1.0)
    assert str(rig.out["AO.1"].generator) == "ad3.awg2"


def test_out_of_range_voltage_switches_nothing(rig):
    with pytest.raises(ValueError, match="exceeds the generator range"):
        rig.out["AO.1"].sine(1000, 4.0, offset=2.0)
    assert rig.rel.history == []
    assert rig.ad3.running == [False, False]
    assert rig.out["AO.1"].generator is None


def test_square_and_arbitrary(rig):
    rig.out["AO.1"].square(100, 1.0, duty=0.2)
    assert rig.ad3.waves[1] == Waveform.square(100, 1.0, duty=0.2)
    rig.out["AO.1"].arbitrary([0.0, 1.0, 0.5], rate=3000)
    assert rig.ad3.waves[1] == Waveform.arbitrary([0.0, 1.0, 0.5], rate=3000)


def test_waveform_event(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.1"].disconnect()
    recorded = events(rig)
    waveform = next(e for e in recorded if e["action"] == "waveform")
    assert (waveform["source"], waveform["generator"], waveform["kind"], waveform["freq"]) == (
        "AO.1",
        "ad3.awg2",
        "sine",
        1000.0,
    )
    assert ("AO.1", "disconnect") in [(e["source"], e["action"]) for e in recorded]


def test_configuration_errors(rig):
    with pytest.raises(ConfigError, match="both wired to generator ad3.awg1"):
        AnalogOut("AO.4", rig.recorder, rig.router, direct=rig.ad3.resource("awg1"))
    with pytest.raises(ConfigError, match="no 'analog' generators"):
        AnalogOut(
            "AO.4",
            rig.recorder,
            AnalogRouter([], rig.recorder),
            select=rig.rel.resource("6"),
            connect=rig.rel.resource("7"),
        )
    with pytest.raises(ConfigError, match="either a direct generator"):
        AnalogOut("AO.4", rig.recorder, rig.router)
    with pytest.raises(ConfigError, match="needs 2 generators"):
        AnalogRouter([rig.ad3.resource("awg1")], rig.recorder)
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/signals/test_analog_out.py -q`
Expected: FAIL s `ImportError: cannot import name 'AnalogOut'`.

- [ ] **Step 3: Implementace `src/hil/signals/analog.py`**

```python
"""Analog terminals: generator outputs behind the output multiplexer, scope inputs."""

import logging
import threading
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from hil.errors import ConfigError, ResourceConflict
from hil.recording import Recorder
from hil.resources import AwgChannel, RelayChannel, Waveform
from hil.signals.base import Signal

log = logging.getLogger("hil.signals.analog")


class _Generator:
    """One generator and the output terminals connected to it."""

    def __init__(self, awg: AwgChannel, mux_position: int | None) -> None:
        self.awg = awg
        # position of the select relay that picks it (0 released, 1 operated);
        # None for a generator wired only to a direct terminal
        self.mux_position = mux_position
        # terminal wired to the generator permanently, without a relay
        self.direct: str | None = None
        self.users: set[str] = set()
        self.wave: Waveform | None = None


def _names(names: set[str]) -> str:
    return ", ".join(sorted(names))


class AnalogRouter:
    """Which generator drives which output terminal; switches the output multiplexer.

    A generator is free when no terminal is connected to it. Terminals connected to
    one generator share its waveform (``follow``). A mux terminal gets a free
    generator without a direct terminal first, so that the fast direct channel stays
    available. Operations of all output terminals are serialized by one lock.
    """

    def __init__(self, generators: Sequence[AwgChannel], recorder: Recorder) -> None:
        if len(generators) not in (0, 2):
            raise ConfigError(
                f"the output multiplexer needs 2 generators, got {len(generators)}"
            )
        self.recorder = recorder
        self.lock = threading.RLock()
        self._generators = [_Generator(awg, i) for i, awg in enumerate(generators)]

    def add(self, out: "AnalogOut") -> None:
        """Register an output terminal; called by ``AnalogOut``."""
        if out.direct is None:
            if not any(g.mux_position is not None for g in self._generators):
                raise ConfigError(
                    f"terminal {out.name!r} uses the output multiplexer, but the station "
                    "has no 'analog' generators"
                )
            return
        gen = self._find(out.direct)
        if gen is None:
            gen = _Generator(out.direct, None)
            self._generators.append(gen)
        if gen.direct is not None:
            raise ConfigError(
                f"terminals {gen.direct!r} and {out.name!r} are both wired to generator "
                f"{out.direct}"
            )
        gen.direct = out.name

    def _find(self, awg: AwgChannel) -> "_Generator | None":
        return next((g for g in self._generators if g.awg == awg), None)

    def _current(self, name: str) -> "_Generator | None":
        return next((g for g in self._generators if name in g.users), None)

    def generator_of(self, name: str) -> AwgChannel | None:
        with self.lock:
            gen = self._current(name)
            return None if gen is None else gen.awg

    def waveform_of(self, name: str) -> Waveform | None:
        with self.lock:
            gen = self._current(name)
            return None if gen is None else gen.wave

    # --- operations -----------------------------------------------------

    def drive(self, out: "AnalogOut", wave: Waveform) -> None:
        """Put ``wave`` on ``out``; allocate and connect a generator if it has none."""
        with self.lock:
            gen = self._current(out.name)
            if gen is not None:
                gen.awg.apply(wave)
                gen.wave = wave
                self._event(out.name, "waveform", gen, wave)
                return
            gen = self._allocate(out)
            gen.awg.apply(wave)
            gen.awg.start()
            gen.wave = wave
            try:
                self._route(out, gen)
            except BaseException:
                self._stop_unused(gen)
                raise
            gen.users.add(out.name)
            self._event(out.name, "waveform", gen, wave)
            self._note_direct(gen, out.name)

    def follow(self, out: "AnalogOut", other: "AnalogOut") -> None:
        """Connect ``out`` to the generator of ``other``; they share the waveform."""
        with self.lock:
            if other.name == out.name:
                raise ValueError(f"{out.name}: a terminal cannot follow itself")
            gen = self._current(other.name)
            if gen is None:
                raise ResourceConflict(f"{out.name}: {other.name} has no signal to follow")
            current = self._current(out.name)
            if current is gen:
                return
            if out.direct is not None:
                if gen.awg != out.direct:
                    raise ResourceConflict(
                        f"{out.name} is wired directly to {out.direct} and cannot follow "
                        f"{other.name} on {gen.awg}"
                    )
            elif gen.mux_position is None:
                raise ResourceConflict(
                    f"{out.name}: generator {gen.awg} of {other.name} is not on the "
                    "output multiplexer"
                )
            if current is not None:
                self._open_connect(out)
                self._leave(out, current)
            self._route(out, gen)
            gen.users.add(out.name)
            self._event(out.name, "follow", gen, other=other.name)
            self._note_direct(gen, out.name)

    def disconnect(self, out: "AnalogOut") -> None:
        """Disconnect ``out`` from the DUT; stop its generator if nothing else uses it."""
        with self.lock:
            self._open_connect(out)
            gen = self._current(out.name)
            if gen is not None:
                self._leave(out, gen)
            out.recorder.event(out.name, "disconnect")

    def safe_state(self, out: "AnalogOut") -> None:
        """Open both relays of ``out`` and release its generator, even if a relay fails."""
        with self.lock:
            try:
                self._open_connect(out)
                if out.select is not None and out.select.get():
                    out.select.set(False)
            finally:
                gen = self._current(out.name)
                if gen is not None:
                    self._leave(out, gen)

    # --- helpers --------------------------------------------------------

    def _allocate(self, out: "AnalogOut") -> _Generator:
        if out.direct is not None:
            gen = self._find(out.direct)
            if gen is None:
                raise ConfigError(f"terminal {out.name!r} is not registered")
            if gen.users:
                raise ResourceConflict(
                    f"{out.name}: generator {gen.awg} is in use by {_names(gen.users)}"
                )
            return gen
        free = [g for g in self._generators if g.mux_position is not None and not g.users]
        if not free:
            busy = "; ".join(
                f"{g.awg}: {_names(g.users)}"
                for g in self._generators
                if g.mux_position is not None
            )
            raise ResourceConflict(f"{out.name}: both generators are in use ({busy})")
        # keep the generator of the fast direct channel free as long as possible
        free.sort(key=lambda g: g.direct is not None)
        return free[0]

    def _route(self, out: "AnalogOut", gen: _Generator) -> None:
        """Select ``gen`` and connect ``out``; never connects the other generator."""
        if out.select is None or out.connect is None:
            return
        operated = gen.mux_position == 1
        if out.select.get() != operated:
            if out.connect.get():
                out.connect.set(False)
            out.select.set(operated)
        out.connect.set(True)

    def _open_connect(self, out: "AnalogOut") -> None:
        if out.connect is not None and out.connect.get():
            out.connect.set(False)

    def _leave(self, out: "AnalogOut", gen: _Generator) -> None:
        gen.users.discard(out.name)
        if not gen.users:
            gen.wave = None
            gen.awg.stop()

    def _stop_unused(self, gen: _Generator) -> None:
        """After a failed connection: do not leave an unused generator running."""
        if gen.users:
            return
        gen.wave = None
        try:
            gen.awg.stop()
        except Exception as exc:
            log.error("stopping generator %s failed: %s", gen.awg, exc)

    def _note_direct(self, gen: _Generator, user: str) -> None:
        if gen.direct is not None and gen.direct != user:
            self.recorder.event(
                gen.direct, "shared_generator", generator=str(gen.awg), by=user
            )

    def _event(
        self, name: str, action: str, gen: _Generator, wave: Waveform | None = None, **data: str
    ) -> None:
        details: dict[str, float | int | str] = {"generator": str(gen.awg), **data}
        if wave is not None:
            details.update(wave.describe())
        self.recorder.event(name, action, **details)


class AnalogOut(Signal):
    """Input of the DUT driven by a generator, directly or through the output multiplexer."""

    kind = "analog_out"

    def __init__(
        self,
        name: str,
        recorder: Recorder,
        router: AnalogRouter,
        direct: AwgChannel | None = None,
        select: RelayChannel | None = None,
        connect: RelayChannel | None = None,
    ) -> None:
        super().__init__(name, recorder)
        if (direct is None) == (select is None or connect is None):
            raise ConfigError(
                f"terminal {name!r} needs either a direct generator, or both select "
                "and connect relays"
            )
        self.router = router
        self.direct = direct
        self.select = select
        self.connect = connect
        router.add(self)

    @property
    def generator(self) -> AwgChannel | None:
        """Generator driving the terminal, None when disconnected."""
        return self.router.generator_of(self.name)

    @property
    def waveform(self) -> Waveform | None:
        return self.router.waveform_of(self.name)

    def sine(self, freq: float, amp: float, offset: float = 0.0) -> None:
        """Sine of peak amplitude ``amp`` volts around ``offset``."""
        self.router.drive(self, Waveform.sine(freq, amp, offset))

    def square(self, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5) -> None:
        self.router.drive(self, Waveform.square(freq, amp, offset, duty))

    def dc(self, volts: float) -> None:
        self.router.drive(self, Waveform.dc(volts))

    def arbitrary(self, samples: Sequence[float] | NDArray[np.float64], rate: float) -> None:
        """Repeat ``samples`` (volts) at ``rate`` samples per second."""
        self.router.drive(self, Waveform.arbitrary(samples, rate))

    def follow(self, other: "AnalogOut") -> None:
        """Connect to the generator of ``other``; a later change of either changes both."""
        self.router.follow(self, other)

    def disconnect(self) -> None:
        self.router.disconnect(self)

    def safe_state(self) -> None:
        self.router.safe_state(self)
```

Do `src/hil/signals/__init__.py` přidat import `from hil.signals.analog import AnalogOut, AnalogRouter` a obě jména do `__all__` (abecedně, na začátek).

Poznámka k typům: `AwgChannel` je frozen dataclass, porovnává se podle zařízení (identita) a indexu, takže `_find` najde generátor podle prostředku z jiného volání `resource()`.

- [ ] **Step 4: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest tests/signals/test_analog_out.py -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q`
```bash
git add src/hil/signals tests/signals/test_analog_out.py
git commit -m "feat: analogové výstupy s přidělováním generátorů a multiplexerem"
```

---

### Úkol 4: Analogové vstupy – `ScopeMux`, `AnalogIn`, `Measurement`

**Files:**
- Modify: `src/hil/signals/analog.py`
- Modify: `src/hil/signals/__init__.py`
- Test: `tests/signals/test_analog_in.py` (nový)

**Interfaces:**
- Consumes: `ScopeChannel`, `RelayChannel`, `precise_sleep` (`hil.signals.timing`), `clock.now`.
- Produces (v `hil.signals.analog`, exportováno z `hil.signals`):
  - `DEFAULT_RATE_HZ = 100_000.0`,
  - `Measurement(dc: float, rms_ac: float)` (frozen dataclass), `measurement_of(data) -> Measurement`,
  - `ScopeMux(scope)`: `members`, `active`, `add(inp)`, kontextový manažer `use(inp)`,
  - `AnalogIn(name, recorder, scope, mux, connect=None, settle_s=0.02)`: `kind = "analog_in"`, `measure(duration_s=0.1, rate=DEFAULT_RATE_HZ) -> Measurement`, `capture(duration_s, rate=DEFAULT_RATE_HZ) -> NDArray[np.float64]`, `safe_state()`,
  - záznam `measurements.jsonl`: `{"t", "terminal", "dc", "rms_ac", "duration_s", "rate"}`, události `connect`, `disconnect`, `capture`.

- [ ] **Step 1: Napsat padající testy**

`tests/signals/test_analog_in.py`:

```python
import json
import math
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from hil.drivers.sim.ad3 import SimAd3, SimAd3Config
from hil.drivers.sim.relay import SimRelay, SimRelayConfig
from hil.errors import ConfigError, ResourceConflict
from hil.recording import Recorder
from hil.resources import ScopeChannel
from hil.signals import AnalogIn, Measurement, ScopeMux, measurement_of


@pytest.fixture
def rig(tmp_path):
    rel = SimRelay("rel2", SimRelayConfig(channels=16))
    rel.open()
    ad3 = SimAd3(
        "ad3",
        SimAd3Config(
            inputs={"ch1": {"dc": 1.0, "sine": {"freq": 50, "amp": 0.5}}, "ch2": {"dc": -12.0}}
        ),
    )
    ad3.open()
    recorder = Recorder()
    recorder.start_test(tmp_path)
    ch1 = ad3.resource("ch1")
    mux1 = ScopeMux(ch1)
    ai1 = AnalogIn("AI.1", recorder, ch1, mux1, connect=rel.resource("8"), settle_s=0)
    ai2 = AnalogIn("AI.2", recorder, ch1, mux1, connect=rel.resource("9"), settle_s=0)
    ch2 = ad3.resource("ch2")
    ai3 = AnalogIn("AI.3", recorder, ch2, ScopeMux(ch2))
    yield SimpleNamespace(
        rel=rel, ad3=ad3, recorder=recorder, ai1=ai1, ai2=ai2, ai3=ai3, dir=tmp_path
    )
    recorder.stop_test()


def frames(rig):
    return [states for _, states in rig.rel.history]


def test_measurement_of():
    assert measurement_of(np.array([1.0, 3.0])) == Measurement(2.0, 1.0)
    with pytest.raises(ValueError):
        measurement_of(np.array([]))


def test_measure_dc_and_rms(rig):
    m = rig.ai1.measure()
    assert m.dc == pytest.approx(1.0, abs=1e-9)
    assert m.rms_ac == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)
    assert rig.ad3.acquisitions[-1][1:] == (0, 100_000.0, 10_000)


def test_measure_without_multiplexer(rig):
    assert rig.ai3.measure(0.02).dc == pytest.approx(-12.0)
    assert rig.rel.history == []


def test_measure_is_recorded(rig):
    rig.ai1.measure(0.02)
    lines = (rig.dir / "measurements.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    assert record["terminal"] == "AI.1"
    assert record["dc"] == pytest.approx(1.0, abs=1e-9)
    assert (record["duration_s"], record["rate"]) == (0.02, 100_000.0)


def test_capture(rig):
    data = rig.ai3.capture(0.01, rate=10_000)
    assert len(data) == 100
    events = (rig.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    capture = [json.loads(e) for e in events if '"capture"' in e]
    assert capture[0]["samples"] == 100


def test_break_before_make(rig):
    rig.ai1.measure(0.02)
    rig.ai2.measure(0.02)
    assert frames(rig) == [{8: True}, {8: False}, {9: True}]
    assert rig.rel.states[8:10] == [False, True]


def test_connected_terminal_is_not_switched_again(rig):
    rig.ai1.measure(0.02)
    rig.ai1.measure(0.02)
    assert frames(rig) == [{8: True}]


def test_settle_time(rig):
    ch2 = rig.ad3.resource("ch2")
    ai = AnalogIn("AI.4", rig.recorder, ch2, ScopeMux(ch2), connect=rig.rel.resource("10"), settle_s=0.05)
    ai.measure(0.001)
    connected_at = rig.rel.history[-1][0]
    acquired_at = rig.ad3.acquisitions[-1][0]
    assert acquired_at - connected_at >= 0.05


def test_reconnects_after_safe_state(rig):
    rig.ai1.measure(0.02)
    rig.ai1.safe_state()
    assert rig.rel.states[8] is False
    rig.ai1.measure(0.02)
    assert frames(rig) == [{8: True}, {8: False}, {8: True}]


def test_safe_state_without_connect_relay(rig):
    rig.ai3.safe_state()
    assert rig.rel.history == []


class SlowScope:
    name = "slow"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def scope_acquire(self, index, rate, n):
        self.entered.set()
        self.release.wait(5)
        return np.zeros(n)


def test_concurrent_measurement_conflicts(rig):
    slow = SlowScope()
    scope = ScopeChannel(slow, 0)
    mux = ScopeMux(scope)
    a = AnalogIn("AI.1", rig.recorder, scope, mux, connect=rig.rel.resource("12"), settle_s=0)
    b = AnalogIn("AI.2", rig.recorder, scope, mux, connect=rig.rel.resource("13"), settle_s=0)
    thread = threading.Thread(target=a.measure, args=(0.001,))
    thread.start()
    try:
        assert slow.entered.wait(5)
        with pytest.raises(ResourceConflict, match=r"AI.2: scope channel slow.ch1 is busy measuring AI.1"):
            b.measure(0.001)
        assert rig.rel.states[12:14] == [True, False]
    finally:
        slow.release.set()
        thread.join(5)
    b.measure(0.001)
    assert rig.rel.states[12:14] == [False, True]


def test_shared_scope_needs_connect_relays(rig):
    ch2 = rig.ad3.resource("ch2")
    mux = ScopeMux(ch2)
    AnalogIn("AI.3", rig.recorder, ch2, mux, connect=rig.rel.resource("10"))
    with pytest.raises(ConfigError, match="share scope channel ad3.ch2"):
        AnalogIn("AI.4", rig.recorder, ch2, mux)


@pytest.mark.parametrize(("duration", "rate"), [(0, 1000), (0.1, 0), (-1, 1000)])
def test_invalid_acquisition(rig, duration, rate):
    with pytest.raises(ValueError):
        rig.ai3.measure(duration, rate)
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/signals/test_analog_in.py -q`
Expected: FAIL s `ImportError: cannot import name 'AnalogIn'`.

- [ ] **Step 3: Implementace**

V `src/hil/signals/analog.py` doplnit importy:

```python
import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from hil import clock
from hil.errors import ConfigError, ResourceConflict
from hil.recording import Recorder
from hil.resources import AwgChannel, RelayChannel, ScopeChannel, Waveform
from hil.signals.base import Signal
from hil.signals.timing import precise_sleep
```

Na konec souboru přidat:

```python
# sampling rate of measure(): ten times the 10 kHz bandwidth of HW-ANA-07
DEFAULT_RATE_HZ = 100_000.0


@dataclass(frozen=True)
class Measurement:
    """DC value (mean) and RMS of the AC component of a measured signal, in volts."""

    dc: float
    rms_ac: float


def measurement_of(data: NDArray[np.float64]) -> Measurement:
    if len(data) == 0:
        raise ValueError("no samples to evaluate")
    dc = float(np.mean(data))
    return Measurement(dc, float(np.sqrt(np.mean((data - dc) ** 2))))


class ScopeMux:
    """Terminals sharing one scope channel; one of them is connected and measured at a time.

    Switching opens the ``connect`` relay of the other terminal first, then closes the
    relay of the measured one and waits ``settle_s``. The measured terminal stays
    connected until another terminal needs the channel.
    """

    def __init__(self, scope: ScopeChannel) -> None:
        self.scope = scope
        self.members: list[AnalogIn] = []
        self.active: str | None = None
        self._busy = threading.Lock()

    def add(self, inp: "AnalogIn") -> None:
        members = [*self.members, inp]
        if len(members) > 1 and any(m.connect is None for m in members):
            names = ", ".join(repr(m.name) for m in members)
            raise ConfigError(
                f"terminals {names} share scope channel {self.scope}; each needs a "
                "'connect' relay"
            )
        self.members.append(inp)

    @contextmanager
    def use(self, inp: "AnalogIn") -> Iterator[None]:
        """Connect ``inp`` to the scope channel for one acquisition."""
        if not self._busy.acquire(blocking=False):
            raise ResourceConflict(
                f"{inp.name}: scope channel {self.scope} is busy measuring {self.active}"
            )
        try:
            self.active = inp.name
            connect = inp.connect
            if connect is not None and not connect.get():
                for other in self.members:
                    if other is not inp and other.connect is not None and other.connect.get():
                        other.connect.set(False)
                        other._event("disconnect")
                connect.set(True)
                inp._event("connect")
                precise_sleep(inp.settle_s)
            yield
        finally:
            self.active = None
            self._busy.release()


class AnalogIn(Signal):
    """Output of the DUT measured by a scope channel, optionally through a multiplexer."""

    kind = "analog_in"

    def __init__(
        self,
        name: str,
        recorder: Recorder,
        scope: ScopeChannel,
        mux: ScopeMux,
        connect: RelayChannel | None = None,
        settle_s: float = 0.02,
    ) -> None:
        super().__init__(name, recorder)
        self.scope = scope
        self.mux = mux
        self.connect = connect
        self.settle_s = settle_s
        mux.add(self)

    def _acquire(self, duration_s: float, rate: float) -> NDArray[np.float64]:
        if not duration_s > 0 or not rate > 0:
            raise ValueError(
                f"{self.name}: duration and rate must be positive, got {duration_s} s "
                f"at {rate} Hz"
            )
        n = max(1, round(duration_s * rate))
        with self.mux.use(self):
            return self.scope.acquire(rate, n)

    def capture(self, duration_s: float, rate: float = DEFAULT_RATE_HZ) -> NDArray[np.float64]:
        """Samples (volts) of ``duration_s`` seconds at ``rate`` samples per second."""
        data = self._acquire(duration_s, rate)
        self._event("capture", samples=len(data), rate=rate)
        return data

    def measure(self, duration_s: float = 0.1, rate: float = DEFAULT_RATE_HZ) -> Measurement:
        """DC value and AC RMS over ``duration_s``; recorded in ``measurements.jsonl``."""
        result = measurement_of(self._acquire(duration_s, rate))
        self.recorder.write(
            "measurements.jsonl",
            {
                "t": round(self.recorder.relative(clock.now()), 6),
                "terminal": self.name,
                "dc": result.dc,
                "rms_ac": result.rms_ac,
                "duration_s": duration_s,
                "rate": rate,
            },
        )
        return result

    def safe_state(self) -> None:
        if self.connect is not None and self.connect.get():
            self.connect.set(False)
            self._event("disconnect")
```

Do `src/hil/signals/__init__.py` importovat a exportovat také `AnalogIn`, `DEFAULT_RATE_HZ`, `Measurement`, `ScopeMux` a `measurement_of`.

- [ ] **Step 4: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest tests/signals -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q`
```bash
git add src/hil/signals tests/signals/test_analog_in.py
git commit -m "feat: analogové vstupy s měřicím multiplexerem a záznamem měření"
```

---

### Úkol 5: Stanoviště – analogové svorky, `AnalogBlock`, stanoviště `sim`

**Files:**
- Create: `src/hil/blocks/analog.py`
- Modify: `src/hil/blocks/__init__.py`, `src/hil/station.py`, `src/hil/cli.py`, `src/hil/stations/sim.yaml`
- Modify: `examples/dut.yaml`, `examples/tests/test_door_alarm.py`
- Modify: `tests/conftest.py`, `tests/test_station.py`, `tests/test_dut.py`, `tests/test_cli.py`, `tests/test_pytest_plugin.py`, `tests/test_sim_station.py`
- Test: `tests/test_station_analog.py` (nový)

**Interfaces:**
- Consumes: `AnalogConfig`, `AnalogOutTerminal`, `AnalogInTerminal` (úkol 1), `AwgChannel`, `ScopeChannel` (úkol 2), `AnalogRouter`, `AnalogOut` (úkol 3), `ScopeMux`, `AnalogIn`, `Measurement`, `DEFAULT_RATE_HZ` (úkol 4).
- Produces:
  - `Station.analog: AnalogBlock` s atributy `outputs`, `inputs` a metodami `output(name)`, `input(name)`, `sine(name, freq, amp, offset=0.0)`, `square(name, freq, amp, offset=0.0, duty=0.5)`, `dc(name, volts)`, `arbitrary(name, samples, rate)`, `follow(name, other)`, `disconnect(name)`, `disconnect_all()`, `measure(name, duration_s=0.1, rate=DEFAULT_RATE_HZ)`, `capture(name, duration_s, rate=DEFAULT_RATE_HZ)`.
  - `hil.station._devices_of(terminal, analog: AnalogConfig | None) -> frozenset[str]`: svorka s multiplexerem závisí i na zařízeních generátorů.
  - Stanoviště `sim` zapojuje `AO.0` až `AO.4` a `AI.1` až `AI.4` (zařízení `rel2` typu `sim_relay` a `ad3` typu `sim_ad3`).
  - Fixture `no_analog_station` v `tests/conftest.py`: cesta ke kopii stanoviště `sim` bez analogových svorek.

- [ ] **Step 1: Napsat padající testy**

`tests/test_station_analog.py`:

```python
import pytest

from hil.config.models import AnalogConfig, AnalogOutTerminal
from hil.errors import ConfigError, DeviceError, ResourceConflict, SignalUnavailable
from hil.signals import AnalogIn, AnalogOut
from hil.station import Station, _devices_of

STATION = """
name: t
profile: standard-v1
devices:
  rel1: {driver: sim_relay, channels: 8}
  rel2: {driver: sim_relay, channels: 16}
  ad3: {driver: sim_ad3, inputs: {ch1: {dc: 2.0}}}
analog:
  generators: [ad3.awg1, ad3.awg2]
terminals:
  PWR: {kind: power, relays: [rel1.0, rel1.1]}
  AO.0: {kind: analog_out, direct: ad3.awg1}
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AO.2: {kind: analog_out, select: rel2.2, connect: rel2.3}
  AI.1: {kind: analog_in, scope: ad3.ch1, connect: rel2.8, settle_s: 0}
  AI.2: {kind: analog_in, scope: ad3.ch1, connect: rel2.9, settle_s: 0}
"""


def make(tmp_path, text=STATION) -> Station:
    path = tmp_path / "station.yaml"
    path.write_text(text, encoding="utf-8")
    return Station.from_files(path)


def test_analog_terminals_and_block(tmp_path):
    station = make(tmp_path)
    assert isinstance(station.terminals["AO.1"], AnalogOut)
    assert isinstance(station.terminals["AI.1"], AnalogIn)
    assert list(station.analog.outputs) == ["AO.0", "AO.1", "AO.2"]
    assert list(station.analog.inputs) == ["AI.1", "AI.2"]
    assert station.terminals["AI.1"].mux is station.terminals["AI.2"].mux


def test_block_operations(tmp_path):
    with make(tmp_path) as station:
        rel2, ad3 = station.devices["rel2"], station.devices["ad3"]
        station.analog.sine("AO.1", 1000, 1.0)
        assert rel2.states[0:2] == [True, True]
        station.analog.follow("AO.2", "AO.1")
        assert station.analog.output("AO.2").generator == station.analog.output("AO.1").generator
        assert station.analog.measure("AI.2", 0.01).dc == pytest.approx(2.0)
        assert rel2.states[8:10] == [False, True]
        assert len(station.analog.capture("AI.1", 0.001, rate=10_000)) == 10
        station.analog.disconnect_all()
        assert ad3.running == [False, False]
        assert rel2.states[1] is False
        assert rel2.states[3] is False


def test_block_lookup(tmp_path):
    station = make(tmp_path)
    with pytest.raises(SignalUnavailable, match="no analog_out terminal 'AO.3'"):
        station.analog.output("AO.3")
    with pytest.raises(ConfigError, match="'AI.1' is a analog_in terminal, not a analog_out"):
        station.analog.output("AI.1")


def test_safe_state(tmp_path):
    with make(tmp_path) as station:
        station.analog.sine("AO.1", 1000, 1.0)
        station.analog.dc("AO.0", 1.0)
        station.analog.measure("AI.1", 0.01)
        station.safe_state()
        assert station.devices["rel2"].states == [False] * 16
        assert station.devices["ad3"].running == [False, False]
        assert station.analog.output("AO.1").generator is None


def test_generators_free_after_safe_state(tmp_path):
    with make(tmp_path) as station:
        station.analog.dc("AO.1", 1.0)
        station.analog.dc("AO.2", 2.0)
        with pytest.raises(ResourceConflict):
            station.analog.dc("AO.0", 1.0)
        station.devices["rel2"].fail_with = DeviceError("bus timeout")
        with pytest.raises(DeviceError):
            station.safe_state()
        station.devices["rel2"].fail_with = None
        station.analog.dc("AO.1", 1.0)
        station.analog.dc("AO.2", 2.0)


def test_generator_must_be_awg(tmp_path):
    text = STATION.replace("generators: [ad3.awg1, ad3.awg2]", "generators: [rel1.5, ad3.awg2]")
    with pytest.raises(ConfigError, match=r"analog generator rel1.5 is not an AwgChannel"):
        make(tmp_path, text)


def test_direct_output_on_relay(tmp_path):
    with pytest.raises(ConfigError, match=r"terminal 'AO.0': rel1.5 is not a AwgChannel"):
        make(tmp_path, STATION.replace("direct: ad3.awg1", "direct: rel1.5"))


def test_mux_output_depends_on_generator_devices():
    terminal = AnalogOutTerminal.model_validate(
        {"kind": "analog_out", "select": "rel2.0", "connect": "rel2.1"}
    )
    analog = AnalogConfig.model_validate({"generators": ["ad3.awg1", "ad3.awg2"]})
    assert _devices_of(terminal, analog) == {"rel2", "ad3"}
    assert _devices_of(terminal, None) == {"rel2"}
```

Do `tests/test_sim_station.py` přidat:

```python
import math

import pytest


def test_builtin_sim_station_analog():
    with Station.from_files("sim") as station:
        station.analog.sine("AO.1", 1000, 1.0)
        m = station.analog.measure("AI.1", 0.02)
        assert m.dc == pytest.approx(1.0, abs=1e-6)
        assert m.rms_ac == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)
        assert station.analog.measure("AI.3", 0.02).dc == pytest.approx(12.0)
```

(importy `math` a `pytest` patří na začátek souboru).

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/test_station_analog.py tests/test_sim_station.py -q`
Expected: FAIL (`ImportError: cannot import name '_devices_of'` nebo `kind 'analog_out' is not supported`).

- [ ] **Step 3: `src/hil/blocks/analog.py`**

```python
"""Analog block: generator outputs and measured outputs of the DUT."""

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from hil.blocks._lookup import lookup
from hil.signals import DEFAULT_RATE_HZ, AnalogIn, AnalogOut, Measurement


class AnalogBlock:
    """All analog terminals of a station.

    Generator allocation, the output multiplexer and the measuring multiplexers live
    in the terminals (``AnalogRouter``, ``ScopeMux``); the block adds access by name.
    """

    def __init__(
        self,
        outputs: Mapping[str, AnalogOut],
        inputs: Mapping[str, AnalogIn],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.outputs = dict(outputs)
        self.inputs = dict(inputs)
        self._profile_terminals = profile_terminals

    def output(self, name: str) -> AnalogOut:
        return lookup(name, self.outputs, "analog_out", self._profile_terminals)

    def input(self, name: str) -> AnalogIn:
        return lookup(name, self.inputs, "analog_in", self._profile_terminals)

    def sine(self, name: str, freq: float, amp: float, offset: float = 0.0) -> None:
        self.output(name).sine(freq, amp, offset)

    def square(
        self, name: str, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5
    ) -> None:
        self.output(name).square(freq, amp, offset, duty)

    def dc(self, name: str, volts: float) -> None:
        self.output(name).dc(volts)

    def arbitrary(
        self, name: str, samples: Sequence[float] | NDArray[np.float64], rate: float
    ) -> None:
        self.output(name).arbitrary(samples, rate)

    def follow(self, name: str, other: str) -> None:
        self.output(name).follow(self.output(other))

    def disconnect(self, name: str) -> None:
        self.output(name).disconnect()

    def disconnect_all(self) -> None:
        for out in self.outputs.values():
            out.disconnect()

    def measure(
        self, name: str, duration_s: float = 0.1, rate: float = DEFAULT_RATE_HZ
    ) -> Measurement:
        return self.input(name).measure(duration_s, rate)

    def capture(
        self, name: str, duration_s: float, rate: float = DEFAULT_RATE_HZ
    ) -> NDArray[np.float64]:
        return self.input(name).capture(duration_s, rate)
```

V `src/hil/blocks/__init__.py` přidat `from hil.blocks.analog import AnalogBlock` a `"AnalogBlock"` do `__all__`.

- [ ] **Step 4: `src/hil/station.py`**

1. Importy rozšířit:

```python
from hil.blocks import AnalogBlock, CommBlock, DebugBlock, DigitalBlock, FaultMatrix, PowerBlock
from hil.config.models import (
    AnalogConfig,
    AnalogInTerminal,
    AnalogOutTerminal,
    DebugTerminal,
    ...  # dosavadní jména
)
from hil.resources import (
    AwgChannel,
    DebugProbe,
    DigitalInput,
    RelayChannel,
    ScopeChannel,
    SerialLink,
)
from hil.signals import (
    AnalogIn,
    AnalogOut,
    AnalogRouter,
    DebugSignal,
    ...  # dosavadní jména
    ScopeMux,
)
```

2. V `__init__` mezi smyčku `bind` a sestavení `self.terminals` vložit:

```python
        analog = self.config.analog
        generators = [] if analog is None else [self._generator(r) for r in analog.generators]
        self._router = AnalogRouter(generators, self.recorder)
        self._scope_muxes: dict[ScopeChannel, ScopeMux] = {}
```

   `self._terminal_devices` počítat s `_devices_of(terminal, self.config.analog)` a za `self.debug = ...` přidat:

```python
        self.analog = AnalogBlock(self._of(AnalogOut), self._of(AnalogIn), terminals)
```

3. Za metodu `_resource` přidat:

```python
    def _optional[T](self, terminal: str, ref: ResourceRef | None, expected: type[T]) -> T | None:
        return None if ref is None else self._resource(terminal, ref, expected)

    def _generator(self, ref: ResourceRef) -> AwgChannel:
        try:
            resource = self.devices[ref.device].resource(ref.channel)
        except ConfigError as exc:
            raise ConfigError(f"{self.source}: analog generator {ref}: {exc}") from exc
        if not isinstance(resource, AwgChannel):
            raise ConfigError(f"{self.source}: analog generator {ref} is not an AwgChannel")
        return resource
```

4. V `_build` před `case SerialTerminal(...)` přidat:

```python
            case AnalogOutTerminal() as out:
                return AnalogOut(
                    name,
                    rec,
                    self._router,
                    direct=self._optional(name, out.direct, AwgChannel),
                    select=self._optional(name, out.select, RelayChannel),
                    connect=self._optional(name, out.connect, RelayChannel),
                )
            case AnalogInTerminal() as inp:
                scope = self._resource(name, inp.scope, ScopeChannel)
                mux = self._scope_muxes.get(scope)
                if mux is None:
                    mux = self._scope_muxes[scope] = ScopeMux(scope)
                return AnalogIn(
                    name,
                    rec,
                    scope,
                    mux,
                    connect=self._optional(name, inp.connect, RelayChannel),
                    settle_s=inp.settle_s,
                )
```

5. Funkci `_devices_of` nahradit:

```python
def _devices_of(terminal: Any, analog: AnalogConfig | None) -> frozenset[str]:
    """Names of the devices a station terminal uses.

    A terminal behind the output multiplexer also needs the generators: its safe state
    stops the generator it uses.
    """
    devices = {ref.device for ref in terminal_refs(terminal)}
    if isinstance(terminal, DebugTerminal):
        devices.add(terminal.probe)
    if isinstance(terminal, AnalogOutTerminal) and terminal.select is not None and analog:
        devices.update(ref.device for ref in analog.generators)
    return frozenset(devices)
```

- [ ] **Step 5: `hil info` a stanoviště `sim`**

V `src/hil/cli.py` do slovníku `blocks` ve funkci `_info` za `"debug"` přidat:

```python
        "analog": [*station.analog.outputs, *station.analog.inputs],
```

`src/hil/stations/sim.yaml`: komentář v hlavičce změnit na „It wires every terminal of the standard-v1 profile.“ a doplnit odstavec: „Analog: AO.0 is wired directly to generator 1 of the simulated Analog Discovery 3, AO.1 to AO.4 go through the output multiplexer on rel2. AI.1, AI.2 share scope channel ch1, AI.3, AI.4 share ch2. The scope reads fixed signals (ch1: 1 V DC with a 50 Hz sine of 0.5 V, ch2: 12 V DC); the DUT between generators and scope is not simulated.“ Do `devices` přidat:

```yaml
  rel2: {driver: sim_relay, channels: 32}
  ad3: {driver: sim_ad3, inputs: {ch1: {dc: 1.0, sine: {freq: 50, amp: 0.5}}, ch2: {dc: 12.0}}}
```

Mezi `devices` a `terminals` přidat:

```yaml
analog:
  generators: [ad3.awg1, ad3.awg2]
```

Na konec `terminals` přidat:

```yaml
  AO.0: {kind: analog_out, direct: ad3.awg1}
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AO.2: {kind: analog_out, select: rel2.2, connect: rel2.3}
  AO.3: {kind: analog_out, select: rel2.4, connect: rel2.5}
  AO.4: {kind: analog_out, select: rel2.6, connect: rel2.7}
  AI.1: {kind: analog_in, scope: ad3.ch1, connect: rel2.8}
  AI.2: {kind: analog_in, scope: ad3.ch1, connect: rel2.9}
  AI.3: {kind: analog_in, scope: ad3.ch2, connect: rel2.10}
  AI.4: {kind: analog_in, scope: ad3.ch2, connect: rel2.11}
```

- [ ] **Step 6: Úprava testů, které počítaly s nezapojenou `AO.1` na `sim`**

Stanoviště `sim` teď zapojuje všechny svorky profilu. Testy přeskočení nezapojeného signálu proto použijí kopii `sim` bez analogu.

`tests/conftest.py` – přidat import `import yaml`, `from hil.config.loader import resolve_station_path` a fixture:

```python
@pytest.fixture
def no_analog_station(tmp_path):
    """The built-in station "sim" without analog terminals, for tests of unwired signals."""
    data = yaml.safe_load(resolve_station_path("sim").read_text(encoding="utf-8"))
    del data["analog"]
    data["terminals"] = {
        name: terminal
        for name, terminal in data["terminals"].items()
        if not name.startswith(("AO.", "AI."))
    }
    path = tmp_path / "sim-no-analog.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
```

`tests/test_dut.py` – `test_unwired_signal` přepsat:

```python
def test_unwired_signal(no_analog_station):
    with Station.from_files(no_analog_station) as station:
        dut = Dut(load_dut(EXAMPLE, station.profile), station)
        assert not dut.available("sensor_in3")
        with pytest.raises(SignalUnavailable, match=r"signal 'sensor_in3'.*'AO.1' is not wired"):
            dut.sensor_in3  # noqa: B018
```

`tests/test_pytest_plugin.py`:
- `run(pytester, test_source, *extra)` změnit na `run(pytester, test_source, *extra, station="sim")` a ve volání `runpytest` použít `"--hil-station", str(station)`.
- Testy `test_unwired_signal_skips`, `test_unwired_signal_in_fixture_skips`, `test_marker_skips_before_test_body` a `test_unwired_signal_in_module_scoped_fixture_skips` dostanou parametr `no_analog_station` a volají `run(..., station=no_analog_station)`.
- Přidat test:

```python
def test_measurement_is_recorded(pytester):
    result = run(
        pytester,
        """
        def test_measure(hil):
            hil.analog.measure("AI.1", 0.02)
        """,
    )
    result.assert_outcomes(passed=1)
    nodeid = "test_measurement_is_recorded.py::test_measure"
    out = pytester.path / "out" / artifact_dir_name(nodeid)
    lines = (out / "measurements.jsonl").read_text().splitlines()
    assert json.loads(lines[1])["terminal"] == "AI.1"
```

`tests/test_cli.py` – v `test_info` řádek s `AO\.1\s+analog_out\s+not wired` nahradit:

```python
    assert re.search(r"AO\.1\s+analog_out\s+wired", out)
    assert re.search(r"analog\s+AO\.0, AO\.1, AO\.2, AO\.3, AO\.4, AI\.1, AI\.2, AI\.3, AI\.4", out)
```

`tests/test_station.py` – `test_unsupported_kind` smazat (analogové druhy už jsou podporované, chybu typu prostředku pokrývá `test_direct_output_on_relay` v `tests/test_station_analog.py`). Pokud po smazání zůstane nepoužitý import, odstranit ho.

Pokud další test v repozitáři (`grep -rn "AO\.\|sensor_in3\|not wired" tests examples`) předpokládá nezapojenou analogovou svorku na `sim`, upravit ho stejně (stanoviště `no_analog_station`).

- [ ] **Step 7: Příklady**

`examples/dut.yaml`: za `sensor_in3: AO.1` přidat `sensor_out1: AI.1`.

`examples/tests/test_door_alarm.py`: test `test_analog_input` nahradit:

```python
@pytest.mark.hil_requires("sensor_in3")
def test_analog_input(dut):
    # Skipped on stations without terminal AO.1.
    dut.sensor_in3.sine(freq=1000, amp=1.0)


@pytest.mark.hil_requires("sensor_out1")
def test_analog_output_measurement(dut):
    dut.supply.on()
    m = dut.sensor_out1.measure(duration_s=0.1)
    # On the "sim" station AI.1 reads the fixed input of sim_ad3 (1 V DC, 50 Hz sine 0.5 V).
    assert -24.0 <= m.dc <= 24.0
    assert m.rms_ac >= 0.0
```

- [ ] **Step 8: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
Expected: PASS, v příkladech žádný přeskočený test.

- [ ] **Step 9: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy`
```bash
git add src/hil tests examples
git commit -m "feat: analogový blok stanoviště a analogové svorky na stanovišti sim"
```

---
### Úkol 6: Vrstva ctypes nad WaveForms SDK (`hil.drivers.dwf`)

**Files:**
- Create: `src/hil/drivers/dwf.py`
- Modify: `tests/drivers/conftest.py` (falešná knihovna `FakeDwf` a fixture `fake_dwf`)
- Test: `tests/drivers/test_dwf.py` (nový)

**Interfaces:**
- Consumes: `Waveform` (úkol 2), `clock.now`.
- Produces (v `hil.drivers.dwf`):
  - konstanty `FUNC_DC`, `FUNC_SINE`, `FUNC_SQUARE`, `FUNC_CUSTOM`, `PARAM_ON_CLOSE`, `ON_CLOSE_STOP`, `IDLE_OFFSET`, `ACQ_SINGLE`, `ACQ_RECORD`, `STATE_DONE`,
  - modulová proměnná `_load: Callable[[str], Any]` (výchozí `ctypes.CDLL`), kterou testy nahrazují,
  - `default_library() -> str`,
  - `NodeSettings(function, frequency, amplitude, offset, symmetry, data=None)` a `node_settings(wave) -> NodeSettings`,
  - `DwfDeviceInfo(index, serial, name, in_use)`,
  - `DwfLibrary(path=None)` s metodami `devices()`, `open(index) -> int`, `close(handle)`, `awg_apply(handle, channel, wave)`, `awg_start(handle, channel)`, `awg_stop(handle, channel)`, `awg_max_samples(handle, channel) -> int`, `scope_setup(handle, range_v)`, `scope_max_samples(handle) -> int`, `scope_acquire(handle, channel, rate, n, record, timeout_s) -> NDArray[np.float64]`.
  - Selhání funkce knihovny je `DeviceError` s textem z `FDwfGetLastErrorMsg`. Chybějící knihovna je `DeviceNotFound`. Nedokončený záznam je `DeviceTimeout`.
- Produces (testy): fixture `fake_dwf` v `tests/drivers/conftest.py` vrací instanci `FakeDwf` a nahradí jí `hil.drivers.dwf._load`. Seznam `fake_dwf.loaded` obsahuje jména načtených knihoven.

Funkce WaveForms SDK použité v plánu (podle `dwf.h` a příkladů SDK, ověří HW test v úkolu 8): `FDwfGetLastErrorMsg`, `FDwfEnum`, `FDwfEnumSN` (vrací `SN:<číslo>`), `FDwfEnumDeviceName`, `FDwfEnumDeviceIsOpened`, `FDwfParamSet` (`DwfParamOnClose` = 4, hodnota 1 = zastavit), `FDwfDeviceOpen`, `FDwfDeviceClose`, `FDwfAnalogOutNode{Enable,Function,Frequency,Amplitude,Offset,Symmetry,Data}Set`, `FDwfAnalogOutNodeDataInfo`, `FDwfAnalogOutIdleSet` (`DwfAnalogOutIdleOffset` = 1), `FDwfAnalogOutConfigure`, `FDwfAnalogInChannel{Enable,Range,Offset}Set`, `FDwfAnalogInBufferSizeInfo`, `FDwfAnalogInFrequencySet`, `FDwfAnalogInAcquisitionModeSet` (`acqmodeSingle` = 0, `acqmodeRecord` = 3), `FDwfAnalogInBufferSizeSet`, `FDwfAnalogInRecordLengthSet`, `FDwfAnalogInConfigure`, `FDwfAnalogInStatus` (`DwfStateDone` = 2), `FDwfAnalogInStatusRecord`, `FDwfAnalogInStatusData`. Funkce `funcDC` = 0, `funcSine` = 1, `funcSquare` = 2, `funcCustom` = 30. U `funcDC` je úroveň dána offsetem.

- [ ] **Step 1: Falešná knihovna v `tests/drivers/conftest.py`**

Na konec souboru přidat (importy `ctypes` a `from hil.drivers import dwf` patří na začátek):

```python
DWF_DONE, DWF_RUNNING = 2, 3


def _plain(arg):
    """Recorded form of a ctypes argument."""
    if hasattr(arg, "_obj"):
        return "ref"
    if isinstance(arg, ctypes.Array):
        return f"array[{len(arg)}]"
    return getattr(arg, "value", arg)


def _set(ref, value):
    ref._obj.value = value


class FakeDwf:
    """Stand-in for the WaveForms SDK library.

    Functions take ctypes arguments like the real library; outputs passed by
    reference are written through ``ref._obj``. Every call is recorded in ``calls``,
    a function named in ``fail`` returns 0 and sets the error message.
    """

    def __init__(self):
        # [serial as reported by FDwfEnumSN, device name, opened by another program]
        self.devices = [["SN:210415BABCDE", "Analog Discovery 3", False]]
        self.calls = []
        self.fail = {}
        self.error = ""
        self.loaded = []
        self.handles = set()
        self.params = {}
        self.out = {0: {}, 1: {}}
        self.running = {0: False, 1: False}
        self.scope_range = {}
        # signal at the scope inputs: sample index -> volts
        self.signal = {0: lambda i: 1.0, 1: lambda i: -2.0}
        self.awg_max = 32768
        self.buffer_max = 32768
        self.rate = 0.0
        self.mode = 0
        self.buffer_size = 0
        self.record_length = 0.0
        self.record_chunk = 4096
        self.polls_until_done = 1
        self.lost = 0
        self._polls = 0
        self._recorded = 0

    def names(self):
        return [name for name, _ in self.calls]

    def __getattr__(self, name):
        if not name.startswith("FDwf"):
            raise AttributeError(name)
        handler = getattr(type(self), "_" + name[4:], None)
        if handler is None:
            raise AttributeError(f"fake dwf has no function {name}")

        def call(*args):
            self.calls.append((name, tuple(_plain(a) for a in args)))
            if name in self.fail:
                self.error = self.fail[name]
                return 0
            handler(self, *args)
            return 1

        return call

    def _GetLastErrorMsg(self, buf):
        buf.value = self.error.encode()

    def _Enum(self, enum_filter, count):
        _set(count, len(self.devices))

    def _EnumSN(self, index, buf):
        buf.value = self.devices[index.value][0].encode()

    def _EnumDeviceName(self, index, buf):
        buf.value = self.devices[index.value][1].encode()

    def _EnumDeviceIsOpened(self, index, used):
        _set(used, int(self.devices[index.value][2]))

    def _ParamSet(self, param, value):
        self.params[param.value] = value.value

    def _DeviceOpen(self, index, handle):
        self.handles.add(index.value + 1)
        _set(handle, index.value + 1)

    def _DeviceClose(self, handle):
        self.handles.discard(handle.value)

    def _AnalogOutNodeEnableSet(self, handle, channel, node, enable):
        self.out[channel.value]["enabled"] = enable.value

    def _AnalogOutNodeFunctionSet(self, handle, channel, node, function):
        self.out[channel.value]["function"] = function.value

    def _AnalogOutNodeFrequencySet(self, handle, channel, node, hertz):
        self.out[channel.value]["frequency"] = hertz.value

    def _AnalogOutNodeAmplitudeSet(self, handle, channel, node, volts):
        self.out[channel.value]["amplitude"] = volts.value

    def _AnalogOutNodeOffsetSet(self, handle, channel, node, volts):
        self.out[channel.value]["offset"] = volts.value

    def _AnalogOutNodeSymmetrySet(self, handle, channel, node, percent):
        self.out[channel.value]["symmetry"] = percent.value

    def _AnalogOutNodeDataSet(self, handle, channel, node, data, count):
        self.out[channel.value]["data"] = list(data[: count.value])

    def _AnalogOutNodeDataInfo(self, handle, channel, node, low, high):
        _set(low, 2)
        _set(high, self.awg_max)

    def _AnalogOutIdleSet(self, handle, channel, idle):
        self.out[channel.value]["idle"] = idle.value

    def _AnalogOutConfigure(self, handle, channel, start):
        self.running[channel.value] = bool(start.value)

    def _AnalogInChannelEnableSet(self, handle, channel, enable):
        pass

    def _AnalogInChannelRangeSet(self, handle, channel, volts):
        self.scope_range[channel.value] = volts.value

    def _AnalogInChannelOffsetSet(self, handle, channel, volts):
        pass

    def _AnalogInBufferSizeInfo(self, handle, low, high):
        _set(low, 16)
        _set(high, self.buffer_max)

    def _AnalogInFrequencySet(self, handle, hertz):
        self.rate = hertz.value

    def _AnalogInAcquisitionModeSet(self, handle, mode):
        self.mode = mode.value

    def _AnalogInBufferSizeSet(self, handle, size):
        self.buffer_size = size.value

    def _AnalogInRecordLengthSet(self, handle, seconds):
        self.record_length = seconds.value

    def _AnalogInConfigure(self, handle, reconfigure, start):
        if start.value:
            self._polls = 0
            self._recorded = 0

    def _record_total(self):
        return round(self.record_length * self.rate)

    def _AnalogInStatus(self, handle, read_data, state):
        self._polls += 1
        if self.mode == 0:
            done = self._polls >= self.polls_until_done
        else:
            done = self._recorded >= self._record_total()
        _set(state, DWF_DONE if done else DWF_RUNNING)

    def _AnalogInStatusRecord(self, handle, available, lost, corrupt):
        _set(available, min(self.record_chunk, self._record_total() - self._recorded))
        _set(lost, self.lost)
        _set(corrupt, 0)

    def _AnalogInStatusData(self, handle, channel, buf, count):
        start = self._recorded if self.mode == 3 else 0
        for i in range(count.value):
            buf[i] = self.signal[channel.value](start + i)
        if self.mode == 3:
            self._recorded += count.value


@pytest.fixture
def fake_dwf(monkeypatch):
    fake = FakeDwf()

    def load(name):
        fake.loaded.append(name)
        return fake

    monkeypatch.setattr(dwf, "_load", load)
    return fake
```

- [ ] **Step 2: Napsat padající testy**

`tests/drivers/test_dwf.py`:

```python
import pytest

from hil.drivers import dwf
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import Waveform


@pytest.fixture
def lib(fake_dwf):
    return dwf.DwfLibrary()


def test_default_library(lib, fake_dwf):
    assert fake_dwf.loaded == [dwf.default_library()]
    assert dwf.default_library() in ("dwf.dll", "libdwf.so")


def test_missing_library(monkeypatch):
    def load(name):
        raise OSError("cannot open shared object file")

    monkeypatch.setattr(dwf, "_load", load)
    with pytest.raises(DeviceNotFound, match=r"'libdwf-x.so' cannot be loaded.*install WaveForms"):
        dwf.DwfLibrary("libdwf-x.so")


def test_devices(lib, fake_dwf):
    fake_dwf.devices.append(["SN:210415BXYZ", "Analog Discovery 3", True])
    assert lib.devices() == [
        dwf.DwfDeviceInfo(0, "210415BABCDE", "Analog Discovery 3", False),
        dwf.DwfDeviceInfo(1, "210415BXYZ", "Analog Discovery 3", True),
    ]


def test_failed_call_reports_last_error(lib, fake_dwf):
    fake_dwf.fail["FDwfDeviceOpen"] = "Device is busy"
    with pytest.raises(DeviceError, match="FDwfDeviceOpen failed: Device is busy"):
        lib.open(0)


def test_open_stops_generators_on_close(lib, fake_dwf):
    handle = lib.open(0)
    assert handle in fake_dwf.handles
    assert fake_dwf.params == {dwf.PARAM_ON_CLOSE: dwf.ON_CLOSE_STOP}
    names = fake_dwf.names()
    assert names.index("FDwfParamSet") < names.index("FDwfDeviceOpen")
    lib.close(handle)
    assert fake_dwf.handles == set()


@pytest.mark.parametrize(
    ("wave", "expected"),
    [
        (Waveform.dc(-1.5), dwf.NodeSettings(dwf.FUNC_DC, 0.0, 0.0, -1.5, 50.0)),
        (Waveform.sine(1000, 2.0, 0.5), dwf.NodeSettings(dwf.FUNC_SINE, 1000.0, 2.0, 0.5, 50.0)),
        (
            Waveform.square(50, 1.0, duty=0.25),
            dwf.NodeSettings(dwf.FUNC_SQUARE, 50.0, 1.0, 0.0, 25.0),
        ),
        (
            Waveform.arbitrary([0.0, 2.0, 1.0, 0.0], rate=4000),
            dwf.NodeSettings(dwf.FUNC_CUSTOM, 1000.0, 1.0, 1.0, 50.0, (-1.0, 1.0, 0.0, -1.0)),
        ),
        (
            Waveform.arbitrary([3.0, 3.0], rate=10),
            dwf.NodeSettings(dwf.FUNC_CUSTOM, 5.0, 0.0, 3.0, 50.0, (0.0, 0.0)),
        ),
    ],
)
def test_node_settings(wave, expected):
    assert dwf.node_settings(wave) == expected


def test_awg_apply_and_start(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 1, Waveform.sine(1000, 2.0, 0.5))
    assert fake_dwf.out[1] == {
        "enabled": 1,
        "function": dwf.FUNC_SINE,
        "frequency": 1000.0,
        "amplitude": 2.0,
        "offset": 0.5,
        "symmetry": 50.0,
        "idle": dwf.IDLE_OFFSET,
    }
    lib.awg_start(handle, 1)
    assert fake_dwf.running[1]


def test_awg_arbitrary_data(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 0, Waveform.arbitrary([0.0, 2.0], rate=100))
    assert fake_dwf.out[0]["data"] == [-1.0, 1.0]


def test_awg_stop_goes_to_zero_volts(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 0, Waveform.dc(3.0))
    lib.awg_start(handle, 0)
    lib.awg_stop(handle, 0)
    assert (fake_dwf.out[0]["function"], fake_dwf.out[0]["offset"]) == (dwf.FUNC_DC, 0.0)
    assert not fake_dwf.running[0]


def test_max_samples(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.awg_max = 4096
    fake_dwf.buffer_max = 16384
    assert lib.awg_max_samples(handle, 0) == 4096
    assert lib.scope_max_samples(handle) == 16384


def test_scope_setup(lib, fake_dwf):
    lib.scope_setup(lib.open(0), 50.0)
    assert fake_dwf.scope_range == {0: 50.0, 1: 50.0}


def test_scope_single(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.signal[1] = lambda i: i * 0.5
    data = lib.scope_acquire(handle, 1, 1000.0, 8, record=False, timeout_s=1.0)
    assert data.tolist() == [i * 0.5 for i in range(8)]
    assert (fake_dwf.mode, fake_dwf.buffer_size, fake_dwf.rate) == (dwf.ACQ_SINGLE, 8, 1000.0)


def test_scope_single_timeout(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.polls_until_done = 10**9
    with pytest.raises(DeviceTimeout, match="did not finish"):
        lib.scope_acquire(handle, 0, 1000.0, 8, record=False, timeout_s=0.05)


def test_scope_record(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.record_chunk = 3000
    fake_dwf.signal[0] = float
    data = lib.scope_acquire(handle, 0, 100_000.0, 10_000, record=True, timeout_s=1.0)
    assert data.tolist() == [float(i) for i in range(10_000)]
    assert fake_dwf.mode == dwf.ACQ_RECORD
    assert fake_dwf.record_length == pytest.approx(0.1)
    assert fake_dwf.calls[-1] == ("FDwfAnalogInConfigure", (handle, 0, 0))


def test_scope_record_lost_samples(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.lost = 5
    with pytest.raises(DeviceError, match="lost 5"):
        lib.scope_acquire(handle, 0, 100_000.0, 10_000, record=True, timeout_s=1.0)
    assert fake_dwf.calls[-1] == ("FDwfAnalogInConfigure", (handle, 0, 0))


def test_scope_record_timeout(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.record_chunk = 0
    with pytest.raises(DeviceTimeout, match="did not finish"):
        lib.scope_acquire(handle, 0, 1000.0, 100, record=True, timeout_s=0.05)
```

- [ ] **Step 3: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/drivers/test_dwf.py -q`
Expected: FAIL s `ImportError: cannot import name 'dwf'`.

- [ ] **Step 4: Implementace `src/hil/drivers/dwf.py`**

```python
"""Thin ctypes layer over the WaveForms SDK library (libdwf.so, dwf.dll).

Only the functions the ``analog_discovery_3`` driver needs, wrapped in Python
methods. The library is loaded when ``DwfLibrary`` is created, i.e. in ``open()``
of the driver, so that stations without an Analog Discovery do not need it.
"""

import ctypes
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hil import clock
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import Waveform

# constants of dwf.h
ENUM_ALL = 0
NODE_CARRIER = 0
FUNC_DC = 0
FUNC_SINE = 1
FUNC_SQUARE = 2
FUNC_CUSTOM = 30
PARAM_ON_CLOSE = 4
ON_CLOSE_STOP = 1
IDLE_OFFSET = 1
ACQ_SINGLE = 0
ACQ_RECORD = 3
STATE_DONE = 2

_FUNCTIONS = {"dc": FUNC_DC, "sine": FUNC_SINE, "square": FUNC_SQUARE, "arbitrary": FUNC_CUSTOM}
_POLL_S = 0.001

# loader of the shared library; the tests replace it with a fake library
_load: Callable[[str], Any] = ctypes.CDLL


def default_library() -> str:
    return "dwf.dll" if sys.platform == "win32" else "libdwf.so"


@dataclass(frozen=True)
class NodeSettings:
    """Settings of the carrier node of one generator."""

    function: int
    frequency: float
    amplitude: float
    offset: float
    # duty cycle in percent
    symmetry: float
    # samples of a custom function, normalized to -1..1
    data: tuple[float, ...] | None = None


def node_settings(wave: Waveform) -> NodeSettings:
    if wave.kind == "dc":
        return NodeSettings(FUNC_DC, 0.0, 0.0, wave.offset, 50.0)
    if wave.kind == "arbitrary":
        low, high = min(wave.samples), max(wave.samples)
        offset = (high + low) / 2
        amplitude = (high - low) / 2
        data = tuple(0.0 if amplitude == 0 else (v - offset) / amplitude for v in wave.samples)
        return NodeSettings(
            FUNC_CUSTOM, wave.rate / len(wave.samples), amplitude, offset, 50.0, data
        )
    return NodeSettings(
        _FUNCTIONS[wave.kind], wave.frequency, wave.amplitude, wave.offset, wave.duty * 100.0
    )


@dataclass(frozen=True)
class DwfDeviceInfo:
    index: int
    serial: str
    name: str
    in_use: bool


class DwfLibrary:
    """The WaveForms SDK library; handles are the integers returned by ``open``."""

    def __init__(self, path: str | None = None) -> None:
        name = path or default_library()
        try:
            self._dll = _load(name)
        except OSError as exc:
            raise DeviceNotFound(
                f"WaveForms SDK library {name!r} cannot be loaded ({exc}); install "
                "WaveForms with the Adept runtime"
            ) from exc

    def _call(self, function: str, *args: Any) -> None:
        if not getattr(self._dll, function)(*args):
            raise DeviceError(f"WaveForms {function} failed: {self.last_error()}")

    def last_error(self) -> str:
        buffer = ctypes.create_string_buffer(512)
        self._dll.FDwfGetLastErrorMsg(buffer)
        return buffer.value.decode(errors="replace").strip() or "unknown error"

    # --- devices --------------------------------------------------------

    def devices(self) -> list[DwfDeviceInfo]:
        count = ctypes.c_int()
        self._call("FDwfEnum", ctypes.c_int(ENUM_ALL), ctypes.byref(count))
        found = []
        for index in range(count.value):
            serial = ctypes.create_string_buffer(32)
            name = ctypes.create_string_buffer(32)
            used = ctypes.c_int()
            self._call("FDwfEnumSN", ctypes.c_int(index), serial)
            self._call("FDwfEnumDeviceName", ctypes.c_int(index), name)
            self._call("FDwfEnumDeviceIsOpened", ctypes.c_int(index), ctypes.byref(used))
            found.append(
                DwfDeviceInfo(
                    index,
                    serial.value.decode(errors="replace").removeprefix("SN:"),
                    name.value.decode(errors="replace"),
                    bool(used.value),
                )
            )
        return found

    def open(self, index: int) -> int:
        """Open device ``index``; closing it later stops its generators."""
        self._call("FDwfParamSet", ctypes.c_int(PARAM_ON_CLOSE), ctypes.c_int(ON_CLOSE_STOP))
        handle = ctypes.c_int()
        self._call("FDwfDeviceOpen", ctypes.c_int(index), ctypes.byref(handle))
        if handle.value == 0:
            raise DeviceError(f"WaveForms FDwfDeviceOpen failed: {self.last_error()}")
        return handle.value

    def close(self, handle: int) -> None:
        self._call("FDwfDeviceClose", ctypes.c_int(handle))

    # --- generators -----------------------------------------------------

    def awg_apply(self, handle: int, channel: int, wave: Waveform) -> None:
        settings = node_settings(wave)
        h, ch, node = ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_int(NODE_CARRIER)
        self._call("FDwfAnalogOutNodeEnableSet", h, ch, node, ctypes.c_int(1))
        self._call("FDwfAnalogOutNodeFunctionSet", h, ch, node, ctypes.c_ubyte(settings.function))
        if settings.data is not None:
            data = (ctypes.c_double * len(settings.data))(*settings.data)
            self._call("FDwfAnalogOutNodeDataSet", h, ch, node, data, ctypes.c_int(len(data)))
        self._call("FDwfAnalogOutNodeFrequencySet", h, ch, node, ctypes.c_double(settings.frequency))
        self._call("FDwfAnalogOutNodeAmplitudeSet", h, ch, node, ctypes.c_double(settings.amplitude))
        self._call("FDwfAnalogOutNodeOffsetSet", h, ch, node, ctypes.c_double(settings.offset))
        self._call("FDwfAnalogOutNodeSymmetrySet", h, ch, node, ctypes.c_double(settings.symmetry))
        # a stopped generator outputs its offset
        self._call("FDwfAnalogOutIdleSet", h, ch, ctypes.c_int(IDLE_OFFSET))

    def awg_start(self, handle: int, channel: int) -> None:
        self._call("FDwfAnalogOutConfigure", ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_int(1))

    def awg_stop(self, handle: int, channel: int) -> None:
        """Set 0 V DC and stop; the idle output is the offset, i.e. 0 V."""
        self.awg_apply(handle, channel, Waveform.dc(0.0))
        self._call("FDwfAnalogOutConfigure", ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_int(0))

    def awg_max_samples(self, handle: int, channel: int) -> int:
        low, high = ctypes.c_int(), ctypes.c_int()
        self._call(
            "FDwfAnalogOutNodeDataInfo",
            ctypes.c_int(handle),
            ctypes.c_int(channel),
            ctypes.c_int(NODE_CARRIER),
            ctypes.byref(low),
            ctypes.byref(high),
        )
        return high.value

    # --- scope ----------------------------------------------------------

    def scope_setup(self, handle: int, range_v: float) -> None:
        """Enable both scope channels with range ``range_v`` (peak to peak), offset 0."""
        h = ctypes.c_int(handle)
        for channel in (0, 1):
            ch = ctypes.c_int(channel)
            self._call("FDwfAnalogInChannelEnableSet", h, ch, ctypes.c_int(1))
            self._call("FDwfAnalogInChannelRangeSet", h, ch, ctypes.c_double(range_v))
            self._call("FDwfAnalogInChannelOffsetSet", h, ch, ctypes.c_double(0.0))
        self._call("FDwfAnalogInConfigure", h, ctypes.c_int(1), ctypes.c_int(0))

    def scope_max_samples(self, handle: int) -> int:
        low, high = ctypes.c_int(), ctypes.c_int()
        self._call(
            "FDwfAnalogInBufferSizeInfo", ctypes.c_int(handle), ctypes.byref(low), ctypes.byref(high)
        )
        return high.value

    def scope_acquire(
        self, handle: int, channel: int, rate: float, n: int, record: bool, timeout_s: float
    ) -> NDArray[np.float64]:
        """``n`` samples at ``rate``; ``record`` streams more samples than the buffer holds."""
        h, ch = ctypes.c_int(handle), ctypes.c_int(channel)
        self._call("FDwfAnalogInFrequencySet", h, ctypes.c_double(rate))
        deadline = clock.now() + timeout_s
        if record:
            return self._record(h, ch, rate, n, deadline, timeout_s)
        self._call("FDwfAnalogInAcquisitionModeSet", h, ctypes.c_int(ACQ_SINGLE))
        self._call("FDwfAnalogInBufferSizeSet", h, ctypes.c_int(n))
        self._call("FDwfAnalogInConfigure", h, ctypes.c_int(1), ctypes.c_int(1))
        state = ctypes.c_ubyte()
        while True:
            self._call("FDwfAnalogInStatus", h, ctypes.c_int(1), ctypes.byref(state))
            if state.value == STATE_DONE:
                break
            if clock.now() > deadline:
                raise DeviceTimeout(f"scope acquisition did not finish within {timeout_s} s")
            time.sleep(_POLL_S)
        buffer = (ctypes.c_double * n)()
        self._call("FDwfAnalogInStatusData", h, ch, buffer, ctypes.c_int(n))
        return np.ctypeslib.as_array(buffer).astype(np.float64)

    def _record(
        self,
        h: ctypes.c_int,
        ch: ctypes.c_int,
        rate: float,
        n: int,
        deadline: float,
        timeout_s: float,
    ) -> NDArray[np.float64]:
        self._call("FDwfAnalogInAcquisitionModeSet", h, ctypes.c_int(ACQ_RECORD))
        self._call("FDwfAnalogInRecordLengthSet", h, ctypes.c_double(n / rate))
        self._call("FDwfAnalogInConfigure", h, ctypes.c_int(0), ctypes.c_int(1))
        chunks: list[NDArray[np.float64]] = []
        got = 0
        state = ctypes.c_ubyte()
        available, lost, corrupt = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        try:
            while got < n:
                if clock.now() > deadline:
                    raise DeviceTimeout(f"scope record did not finish within {timeout_s} s")
                self._call("FDwfAnalogInStatus", h, ctypes.c_int(1), ctypes.byref(state))
                self._call(
                    "FDwfAnalogInStatusRecord",
                    h,
                    ctypes.byref(available),
                    ctypes.byref(lost),
                    ctypes.byref(corrupt),
                )
                if lost.value or corrupt.value:
                    raise DeviceError(
                        f"scope record lost {lost.value} and corrupted {corrupt.value} "
                        "samples; lower the sample rate"
                    )
                if available.value:
                    chunk = (ctypes.c_double * available.value)()
                    self._call("FDwfAnalogInStatusData", h, ch, chunk, available)
                    chunks.append(np.ctypeslib.as_array(chunk).astype(np.float64))
                    got += available.value
                elif state.value == STATE_DONE:
                    break
                else:
                    time.sleep(_POLL_S)
        finally:
            self._dll.FDwfAnalogInConfigure(h, ctypes.c_int(0), ctypes.c_int(0))
        data = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float64)
        if len(data) < n:
            raise DeviceError(f"scope record returned {len(data)} of {n} samples")
        return data[:n]
```

Poznámky:
- `test_scope_record_timeout` počítá s tím, že `record_chunk = 0` znamená stále 0 dostupných vzorků a stav „běží“. Smyčka pak skončí kontrolou `deadline` na začátku iterace.
- Dlouhé řádky (`FDwfAnalogOutNode...Set` s argumenty) zalomí `ruff format`.

- [ ] **Step 5: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest tests/drivers/test_dwf.py -q`
Expected: PASS.

- [ ] **Step 6: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q`
```bash
git add src/hil/drivers/dwf.py tests/drivers/conftest.py tests/drivers/test_dwf.py
git commit -m "feat: vrstva ctypes nad WaveForms SDK"
```

---

### Úkol 7: Ovladač `analog_discovery_3`

**Files:**
- Create: `src/hil/drivers/analog_discovery.py`
- Modify: `src/hil/drivers/__init__.py`
- Test: `tests/drivers/test_analog_discovery.py` (nový)

**Interfaces:**
- Consumes: `DwfLibrary`, `DwfDeviceInfo` (úkol 6), `AwgChannel`, `ScopeChannel`, `Waveform` (úkol 2), fixture `fake_dwf`.
- Produces: ovladač `analog_discovery_3` (třída `hil.drivers.analog_discovery.AnalogDiscovery3`):
  - volby `serial: str | None` (s prefixem `SN:` i bez něj, bez rozlišení velikosti písmen), `library: str | None`, `scope_warmup_s: float = 2.0`,
  - kanály `awg1`, `awg2`, `ch1`, `ch2`,
  - konstanty `AWG_LIMIT_V = 5.0` a `SCOPE_RANGE_V = 50.0`,
  - metody protokolů `AwgDevice` a `ScopeDevice`. `scope_acquire` použije režim record, když `n` přesáhne buffer scope, a timeout `n / rate + 2 s`.

- [ ] **Step 1: Napsat padající testy**

`tests/drivers/test_analog_discovery.py`:

```python
import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device, driver_names, dwf
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import AwgChannel, ScopeChannel, Waveform
from hil.station import Station


def make(**options):
    return create_device(
        "ad3", DeviceConfig(driver="analog_discovery_3", scope_warmup_s=0, **options)
    )


def opened(**options):
    device = make(**options)
    device.open()
    return device


def test_registered_and_no_io_on_create(fake_dwf):
    assert "analog_discovery_3" in driver_names()
    make()
    assert fake_dwf.calls == []
    assert fake_dwf.loaded == []


def test_channels(fake_dwf):
    ad3 = make()
    assert set(ad3.channel_names()) == {"awg1", "awg2", "ch1", "ch2"}
    assert isinstance(ad3.resource("awg2"), AwgChannel)
    assert isinstance(ad3.resource("ch1"), ScopeChannel)


@pytest.mark.parametrize("serial", ["210415BABCDE", "SN:210415BABCDE", "210415babcde"])
def test_open_by_serial(fake_dwf, serial):
    fake_dwf.devices.insert(0, ["SN:OTHER", "Analog Discovery 2", False])
    opened(serial=serial)
    assert ("FDwfDeviceOpen", (1, "ref")) in fake_dwf.calls
    assert fake_dwf.scope_range == {0: 50.0, 1: 50.0}


def test_single_device_without_serial(fake_dwf):
    opened()
    assert fake_dwf.handles == {1}


def test_serial_not_found(fake_dwf):
    with pytest.raises(
        DeviceNotFound, match=r"serial 'NOPE' not found \(connected: 210415BABCDE \(Analog Discovery 3\)\)"
    ):
        opened(serial="NOPE")


def test_two_devices_need_serial(fake_dwf):
    fake_dwf.devices.append(["SN:210415BXYZ", "Analog Discovery 3", False])
    with pytest.raises(DeviceNotFound, match=r"2 WaveForms devices connected.*set 'serial'"):
        opened()


def test_no_device(fake_dwf):
    fake_dwf.devices.clear()
    with pytest.raises(DeviceNotFound, match="connected: none"):
        opened()


def test_device_in_use(fake_dwf):
    fake_dwf.devices[0][2] = True
    with pytest.raises(DeviceNotFound, match="used by another program"):
        opened()


def test_missing_library(monkeypatch):
    def load(name):
        raise OSError("not found")

    monkeypatch.setattr(dwf, "_load", load)
    with pytest.raises(DeviceNotFound, match="install WaveForms"):
        opened()


def test_library_option(fake_dwf):
    opened(library="/opt/dwf/libdwf.so")
    assert fake_dwf.loaded == ["/opt/dwf/libdwf.so"]


def test_open_failure_closes_device(fake_dwf):
    fake_dwf.fail["FDwfAnalogInConfigure"] = "USB error"
    with pytest.raises(DeviceError, match="USB error"):
        opened()
    assert fake_dwf.handles == set()


def test_generator(fake_dwf):
    awg = opened().resource("awg2")
    awg.sine(1000, 1.0)
    awg.start()
    assert fake_dwf.out[1]["function"] == dwf.FUNC_SINE
    assert fake_dwf.running[1]


def test_out_of_range_rejected(fake_dwf):
    ad3 = opened()
    fake_dwf.calls.clear()
    with pytest.raises(ValueError, match="exceeds the generator range"):
        ad3.awg_apply(0, Waveform.dc(5.5))
    assert fake_dwf.calls == []


def test_arbitrary_longer_than_buffer(fake_dwf):
    ad3 = opened()
    fake_dwf.awg_max = 4
    with pytest.raises(ValueError, match="5 samples exceed the generator buffer of 4"):
        ad3.awg_apply(0, Waveform.arbitrary([0.0] * 5, rate=100))
    assert "FDwfAnalogOutNodeFunctionSet" not in fake_dwf.names()


def test_scope_single_or_record(fake_dwf):
    ad3 = opened()
    fake_dwf.buffer_max = 100
    assert len(ad3.scope_acquire(0, 1000.0, 100)) == 100
    assert fake_dwf.mode == dwf.ACQ_SINGLE
    assert len(ad3.scope_acquire(0, 1000.0, 101)) == 101
    assert fake_dwf.mode == dwf.ACQ_RECORD


@pytest.mark.parametrize(("rate", "n"), [(0, 10), (1000, 0)])
def test_invalid_acquisition(fake_dwf, rate, n):
    with pytest.raises(ValueError):
        opened().scope_acquire(0, rate, n)


def test_safe_state_stops_both_generators(fake_dwf):
    ad3 = opened()
    for index in (0, 1):
        ad3.awg_apply(index, Waveform.dc(1.0))
        ad3.awg_start(index)
    ad3.safe_state()
    assert fake_dwf.running == {0: False, 1: False}
    assert [fake_dwf.out[i]["offset"] for i in (0, 1)] == [0.0, 0.0]


def test_close(fake_dwf):
    ad3 = opened()
    ad3.close()
    assert fake_dwf.handles == set()
    with pytest.raises(DeviceError, match="not open"):
        ad3.awg_start(0)
    ad3.close()
    ad3.safe_state()


def test_station_does_not_load_the_library(fake_dwf, tmp_path):
    path = tmp_path / "station.yaml"
    path.write_text(
        """
name: t
profile: standard-v1
devices:
  rel2: {driver: sim_relay, channels: 16}
  ad3: {driver: analog_discovery_3, serial: "210415BABCDE"}
analog:
  generators: [ad3.awg1, ad3.awg2]
terminals:
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AI.1: {kind: analog_in, scope: ad3.ch1}
""",
        encoding="utf-8",
    )
    Station.from_files(path)
    assert fake_dwf.loaded == []
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `.venv/Scripts/python -m pytest tests/drivers/test_analog_discovery.py -q`
Expected: FAIL (`unknown driver 'analog_discovery_3'`).

- [ ] **Step 3: Implementace `src/hil/drivers/analog_discovery.py`**

```python
"""Digilent Analog Discovery 3 (driver ``analog_discovery_3``) over the WaveForms SDK."""

import time
from collections.abc import Collection

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from hil.drivers import dwf
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import AwgChannel, ScopeChannel, Waveform

_GENERATORS = {"awg1": 0, "awg2": 1}
_SCOPES = {"ch1": 0, "ch2": 1}

# output range of the generators
AWG_LIMIT_V = 5.0
# scope range, peak to peak (±25 V)
SCOPE_RANGE_V = 50.0
# added to the duration of an acquisition before it is reported as hung
_ACQUIRE_MARGIN_S = 2.0


class AnalogDiscovery3Config(DriverConfig):
    # serial number as shown by WaveForms (with or without "SN:"); without it the only
    # connected device is used
    serial: str | None = None
    # path or name of the WaveForms SDK library; default libdwf.so or dwf.dll
    library: str | None = None
    # wait after the scope is configured until its offset settles (Digilent: 2 s)
    scope_warmup_s: float = Field(default=2.0, ge=0)


@register_driver("analog_discovery_3")
class AnalogDiscovery3(Device):
    """Two generators (±5 V) and two scope channels (±25 V) on one device handle."""

    Config = AnalogDiscovery3Config
    config: AnalogDiscovery3Config

    def __init__(self, name: str, config: AnalogDiscovery3Config) -> None:
        super().__init__(name, config)
        self._lib: dwf.DwfLibrary | None = None
        self._handle: int | None = None

    def channel_names(self) -> Collection[str]:
        return frozenset(_GENERATORS) | frozenset(_SCOPES)

    def resource(self, channel: str) -> object:
        if channel in _GENERATORS:
            return AwgChannel(self, _GENERATORS[channel])
        if channel in _SCOPES:
            return ScopeChannel(self, _SCOPES[channel])
        self._no_channel(channel)

    # --- life cycle -----------------------------------------------------

    def open(self) -> None:
        lib = dwf.DwfLibrary(self.config.library)
        handle = lib.open(self._find(lib.devices()))
        try:
            lib.scope_setup(handle, SCOPE_RANGE_V)
        except BaseException:
            lib.close(handle)
            raise
        time.sleep(self.config.scope_warmup_s)
        with self.lock:
            self._lib, self._handle = lib, handle

    def _find(self, devices: list[dwf.DwfDeviceInfo]) -> int:
        wanted = self.config.serial
        key = None if wanted is None else wanted.removeprefix("SN:").upper()
        candidates = [d for d in devices if key is None or d.serial.upper() == key]
        connected = ", ".join(f"{d.serial} ({d.name})" for d in devices) or "none"
        if not candidates:
            what = "no WaveForms device" if wanted is None else f"serial {wanted!r} not"
            raise DeviceNotFound(
                f"device {self.name!r}: Analog Discovery with {what} found "
                f"(connected: {connected})"
            )
        if len(candidates) > 1:
            raise DeviceNotFound(
                f"device {self.name!r}: {len(candidates)} WaveForms devices connected "
                f"({connected}); set 'serial'"
            )
        device = candidates[0]
        if device.in_use:
            raise DeviceNotFound(
                f"device {self.name!r}: {device.serial} is used by another program "
                "(close WaveForms)"
            )
        return device.index

    def close(self) -> None:
        with self.lock:
            lib, handle = self._lib, self._handle
            self._lib = self._handle = None
        if lib is not None and handle is not None:
            lib.close(handle)

    def safe_state(self) -> None:
        with self.lock:
            if self._lib is None or self._handle is None:
                return
            for index in _GENERATORS.values():
                self._lib.awg_stop(self._handle, index)

    def _opened(self) -> tuple[dwf.DwfLibrary, int]:
        if self._lib is None or self._handle is None:
            raise DeviceError(f"device {self.name!r} is not open")
        return self._lib, self._handle

    # --- generators -----------------------------------------------------

    def awg_apply(self, index: int, wave: Waveform) -> None:
        if wave.peak_v > AWG_LIMIT_V:
            raise ValueError(
                f"device {self.name!r}: {wave.peak_v:g} V exceeds the generator range "
                f"±{AWG_LIMIT_V:g} V"
            )
        with self.lock:
            lib, handle = self._opened()
            if wave.kind == "arbitrary":
                limit = lib.awg_max_samples(handle, index)
                if len(wave.samples) > limit:
                    raise ValueError(
                        f"device {self.name!r}: {len(wave.samples)} samples exceed the "
                        f"generator buffer of {limit}"
                    )
            lib.awg_apply(handle, index, wave)

    def awg_start(self, index: int) -> None:
        with self.lock:
            lib, handle = self._opened()
            lib.awg_start(handle, index)

    def awg_stop(self, index: int) -> None:
        with self.lock:
            lib, handle = self._opened()
            lib.awg_stop(handle, index)

    # --- scope ----------------------------------------------------------

    def scope_acquire(self, index: int, rate: float, n: int) -> NDArray[np.float64]:
        if not rate > 0 or n < 1:
            raise ValueError(f"invalid acquisition: rate {rate}, {n} samples")
        with self.lock:
            lib, handle = self._opened()
            record = n > lib.scope_max_samples(handle)
            return lib.scope_acquire(
                handle, index, rate, n, record, timeout_s=n / rate + _ACQUIRE_MARGIN_S
            )
```

Zpráva při nenalezeném sériovém čísle je „Analog Discovery with serial 'NOPE' not found (connected: …)“, bez čísla „Analog Discovery with no WaveForms device found (connected: none)“. Obě odpovídají testům.

V `src/hil/drivers/__init__.py` přidat `analog_discovery` do importu `from hil.drivers import (...)` i do `__all__` (abecedně, na začátek). `dwf` se importuje nepřímo z `analog_discovery`. Do `__all__` přidat i `"dwf"` a do importu `dwf`, protože testy používají `from hil.drivers import dwf`.

- [ ] **Step 4: Spustit testy, musí projít**

Run: `.venv/Scripts/python -m pytest tests/drivers -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q`
```bash
git add src/hil/drivers tests/drivers/test_analog_discovery.py
git commit -m "feat: ovladač analog_discovery_3"
```

---

### Úkol 8: Stanoviště `lab-a`, HW testy analogu a dokumentace

**Files:**
- Modify: `stations/lab-a.yaml`
- Modify: `tests/hw/test_station_hw.py`
- Modify: `doc/software/konfigurace.md`, `doc/software/testy.md`, `doc/software/hw-testy.md`, `doc/software/nasazeni.md`

**Interfaces:**
- Consumes: celé analogové API (úkoly 1–7).
- Produces: `lab-a` se zapojeným analogem, HW testy `test_ad3_generator_loopback` a `test_analog_multiplexer_loopback`, uživatelská dokumentace.

- [ ] **Step 1: `stations/lab-a.yaml`**

Z hlavičky odstranit dva řádky o analogu („Analog terminals … are wired in plan 4 …; rel2 is reserved for their multiplexer.“). Do hlavičky doplnit: „rel2 is the analog multiplexer: AO.1 to AO.4 use select/connect pairs rel2.0 to rel2.7, AI.1 to AI.4 the connect relays rel2.8 to rel2.11.“

Do `devices` za `stlink` přidat:

```yaml
  # Digilent Analog Discovery 3: generators awg1, awg2 (±5 V), scope ch1, ch2 (±25 V)
  ad3: {driver: analog_discovery_3, serial: REPLACE}
```

Mezi `devices` a `terminals` přidat:

```yaml
analog:
  # select relay released (NC) = generator 1, operated (NO) = generator 2
  generators: [ad3.awg1, ad3.awg2]
```

Na konec `terminals` přidat:

```yaml
  # fast channel without relays (HW-ANA-03), permanently on generator 1
  AO.0: {kind: analog_out, direct: ad3.awg1}
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AO.2: {kind: analog_out, select: rel2.2, connect: rel2.3}
  AO.3: {kind: analog_out, select: rel2.4, connect: rel2.5}
  AO.4: {kind: analog_out, select: rel2.6, connect: rel2.7}
  # measuring multiplexer: two DUT outputs per scope channel
  AI.1: {kind: analog_in, scope: ad3.ch1, connect: rel2.8}
  AI.2: {kind: analog_in, scope: ad3.ch1, connect: rel2.9}
  AI.3: {kind: analog_in, scope: ad3.ch2, connect: rel2.10}
  AI.4: {kind: analog_in, scope: ad3.ch2, connect: rel2.11}
```

Run: `.venv/Scripts/python -m pytest tests/test_station_files.py -q && .venv/Scripts/hil check --station stations/lab-a.yaml`
Expected: PASS a `hil check` bez chyby (bez `--probe` se nic neotevírá).

- [ ] **Step 2: HW testy v `tests/hw/test_station_hw.py`**

Importy doplnit o `import math`, `from hil.drivers.analog_discovery import AnalogDiscovery3` a `from hil.signals import measurement_of`. Na konec souboru přidat:

```python
def analog_discovery(station):
    devices = [d for d in station.devices.values() if isinstance(d, AnalogDiscovery3)]
    if not devices:
        pytest.skip("the station has no Analog Discovery 3")
    return devices[0]


@pytest.mark.parametrize(("generator", "scope"), [("awg1", "ch1"), ("awg2", "ch2")])
def test_ad3_generator_loopback(hw_station, generator, scope):
    """W1 wired to 1+, W2 to 2+, 1- and 2- to ground; needs HIL_HW_AD3_LOOP=1."""
    require_flag("HIL_HW_AD3_LOOP")
    ad3 = analog_discovery(hw_station)
    awg, channel = ad3.resource(generator), ad3.resource(scope)
    try:
        awg.dc(2.0)
        awg.start()
        time.sleep(0.1)
        m = measurement_of(channel.acquire(100_000, 10_000))
        print(f"{generator} DC 2 V -> {scope}: dc {m.dc:.4f} V, rms_ac {m.rms_ac:.4f} V")
        assert m.dc == pytest.approx(2.0, abs=0.1)
        awg.sine(1000, 1.0)
        time.sleep(0.1)
        m = measurement_of(channel.acquire(100_000, 10_000))
        print(f"{generator} sine 1 kHz 1 V -> {scope}: dc {m.dc:.4f} V, rms_ac {m.rms_ac:.4f} V")
        assert m.dc == pytest.approx(0.0, abs=0.1)
        assert m.rms_ac == pytest.approx(1 / math.sqrt(2), rel=0.05)
        long = channel.acquire(100_000, 200_000)  # more than the buffer: record mode
        assert len(long) == 200_000
        assert measurement_of(long).rms_ac == pytest.approx(1 / math.sqrt(2), rel=0.05)
    finally:
        awg.stop()


def analog_pairs():
    """HIL_HW_ANALOG_LOOP=AO.1:AI.1,AO.2:AI.3 - outputs wired to inputs by jumpers."""
    pairs = [tuple(pair.split(":")) for pair in env("HIL_HW_ANALOG_LOOP").split(",")]
    if len(pairs) > 2:
        pytest.fail("HIL_HW_ANALOG_LOOP takes at most 2 pairs (the station has 2 generators)")
    return pairs


def test_analog_multiplexer_loopback(hw_station):
    """Both generators through the output multiplexer, then the "no signal" state."""
    pairs = analog_pairs()
    analog = hw_station.analog
    levels = [1.5, -2.0]
    try:
        for (out, _), level in zip(pairs, levels, strict=False):
            analog.dc(out, level)
        for (out, inp), level in zip(pairs, levels, strict=False):
            m = analog.measure(inp)
            generator = analog.output(out).generator
            print(f"{out} ({generator}) {level} V -> {inp}: {m.dc:.4f} V")
            assert m.dc == pytest.approx(level, abs=0.1)
        analog.disconnect_all()
        for out, inp in pairs:
            m = analog.measure(inp)
            print(f"{out} disconnected -> {inp}: {m.dc:.4f} V")
            assert abs(m.dc) < 0.2
    finally:
        analog.disconnect_all()
```

Run: `.venv/Scripts/python -m pytest tests/hw -q`
Expected: všechny HW testy přeskočené (bez `HIL_HW_STATION`).

- [ ] **Step 3: `doc/software/konfigurace.md`**

- Větu „Tato verze balíčku sestaví všechny druhy kromě `analog_out` a `analog_in`, ty přibudou s ovladačem Analog Discovery 3.“ nahradit: „Balíček sestaví všechny druhy svorek.“
- Bod „Odkaz na kanál má tvar `<zařízení>.<kanál>`, např. `rel1.6`. Každý kanál smí použít jen jedna svorka.“ doplnit o: „Výjimky: kanál scope smí sdílet více svorek `analog_in`, pokud má každá z nich relé `connect` (měřicí multiplexer). Generátor ze sekce `analog` smí být zároveň `direct` jedné svorky.“
- Za bod o `debug` přidat:
  - „`analog_out`: buď `direct: <zařízení>.awg1` (rychlý kanál bez relé, trvale zapojený na generátor), nebo `select` a `connect` (výstupní multiplexer). Relé `select` v klidu (NC) vybírá generátor 1, sepnuté (NO) generátor 2, relé `connect` připojuje vstup DUT. Svorky s multiplexerem vyžadují sekci `analog: {generators: [ad3.awg1, ad3.awg2]}` na úrovni stanoviště (generátor 1, generátor 2).“
  - „`analog_in`: `scope: <zařízení>.ch1`, volitelně `connect` (relé měřicího multiplexeru) a `settle_s` (doba ustálení po přepnutí multiplexeru, výchozí 0,02 s).“
- Do tabulky ovladačů přidat řádky:

  ```markdown
  | `sim_ad3` | `inputs: {ch1: {dc, sine: {freq, amp}, noise}, ch2: ...}`, `awg_limit_v` (5), `scope_limit_v` (25), `seed` (0) | `awg1`, `awg2`, `ch1`, `ch2` |
  | `analog_discovery_3` | `serial` (bez něj jediné připojené AD3), `library` (cesta ke knihovně WaveForms SDK), `scope_warmup_s` (2) | `awg1`, `awg2`, `ch1`, `ch2` |
  ```

- Za odstavec o `modbus_di` přidat odstavec: „`analog_discovery_3` načte knihovnu WaveForms SDK (`libdwf.so`, na Windows `dwf.dll`) až při otevření, stanoviště bez AD3 ji nepotřebuje. AD3 otevřené v programu WaveForms nejde současně použít. Generátory mají rozsah ±5 V, napětí mimo rozsah je chyba dřív, než se cokoli přepne. Scope má rozsah ±25 V. Po otevření ovladač čeká `scope_warmup_s`, než se ustálí offset scope. Záznam do velikosti bufferu scope se pořídí najednou, delší v režimu record. Po zavření zařízení generátory neběží. `sim_ad3` drží nastavení generátorů v paměti a scope čte vstupy z konfigurace, DUT mezi generátorem a scope se nesimuluje.“
- Větu „Stanoviště `sim` zapojuje všechny svorky druhů `power`, `switch`, `sense` a `fault_path` profilu `standard-v1`:“ změnit na „Stanoviště `sim` zapojuje všechny svorky profilu `standard-v1`:“ a do tabulky přidat řádky:

  ```markdown
  | `AO.0` | přímo `ad3.awg1` |
  | `AO.1` až `AO.4` | `select`/`connect`: `rel2.0`/`rel2.1`, `rel2.2`/`rel2.3`, `rel2.4`/`rel2.5`, `rel2.6`/`rel2.7` |
  | `AI.1`, `AI.2` | `ad3.ch1`, `connect` `rel2.8`, `rel2.9` |
  | `AI.3`, `AI.4` | `ad3.ch2`, `connect` `rel2.10`, `rel2.11` |
  ```

- Větu „Analogové svorky (`AO.*`, `AI.*`) `sim` nezapojuje, testy, které je použijí, se přeskočí.“ nahradit: „Scope zařízení `ad3` (`sim_ad3`) čte na `ch1` 1 V DC se sinem 50 Hz o amplitudě 0,5 V a na `ch2` 12 V DC. Test je může změnit přes `hil.devices["ad3"].set_input("ch1", dc=2.0)`.“
- Do výňatku stanoviště `sim` na začátku oddílu nic nepřidávat, jen pod něj doplnit větu: „Analogové svorky a sekce `analog` jsou v úplném souboru.“

- [ ] **Step 4: `doc/software/testy.md`**

- V odstavci o fixtures doplnit do výčtu bezpečného stavu „generátory zastaveny a odpojeny“: „(napájení vypnuto, poruchy obnoveny, generátory zastaveny a odpojeny, relé rozepnuta)“.
- Do tabulky signálů přidat řádky:

  ```markdown
  | `analog_out` | `sine(freq, amp, offset=0)`, `square(freq, amp, offset=0, duty=0.5)`, `dc(v)`, `arbitrary(vzorky, rate)`, `follow(jiný_signál)`, `disconnect()`, `generator`, `waveform` |
  | `analog_in` | `measure(duration_s=0.1) -> Measurement(dc, rms_ac)`, `capture(duration_s, rate=100000) -> numpy.ndarray`; měření do `measurements.jsonl` |
  ```

- Za odstavec o `inject` a `flood` přidat oddíl:

  ```markdown
  ### Analogové signály

  Stanoviště má dva generátory (sekce `analog`). Průběh na svorce s multiplexerem přidělí volný generátor. Přednost má generátor, na kterém není svorka `direct`, aby rychlý kanál zůstal volný. Pokud jsou oba generátory obsazené, vyhodí `ResourceConflict`. Generátor se nejdřív nastaví a spustí, potom se přepne relé `select` a nakonec sepne `connect`, takže vstup DUT nikdy nedostane ani na okamžik signál druhého generátoru. Změna průběhu na svorce, která už generátor má, změní jen generátor.

  `follow(jiný_signál)` připojí svorku na generátor jiné svorky. Generátor je pak sdílený a změna průběhu na kterékoli z nich platí pro obě. `disconnect()` rozepne `connect` (stav bez signálu). Když ke generátoru nezůstane připojena žádná svorka, generátor se zastaví. Svorka `direct` je na generátor zapojená trvale: když generátor používá multiplexer, signál je i na ní (v `events.jsonl` událost `shared_generator`).

  `amp` je amplituda (špička), napětí se uvádí ve voltech. Průběh mimo rozsah generátoru (AD3 ±5 V) vyhodí `ValueError` dřív, než se přepne jakékoli relé.

  `measure()` vzorkuje 100 kHz a vrací průměr (`dc`) a RMS po odečtení průměru (`rms_ac`). Svorky na jednom kanálu scope se přepínají měřicím multiplexerem: nejdřív se rozepne relé jiné svorky, potom sepne relé měřené svorky a počká se `settle_s`. Svorka zůstane připojená, dokud kanál nepotřebuje jiná svorka. Současné měření dvou svorek na jednom kanálu (z jiného vlákna) vyhodí `ResourceConflict`.

  Bez `dut.yaml` se analog ovládá přes blok `hil.analog`: `hil.analog.sine("AO.1", 1000, 1.0)`, `hil.analog.follow("AO.2", "AO.1")`, `hil.analog.measure("AI.1")`, `hil.analog.disconnect_all()`.
  ```

- V oddílu Záznamy doplnit větu: „Signály `analog_in` zapisují výsledky `measure()` do `measurements.jsonl` (čas, svorka, `dc`, `rms_ac`, délka a vzorkovací frekvence).“

- [ ] **Step 5: `doc/software/hw-testy.md`**

Do tabulky přidat řádky:

```markdown
| `test_ad3_generator_loopback` | `HIL_HW_AD3_LOOP=1`, propojky W1→1+ a W2→2+, 1− a 2− na zem, DUT odpojený od `AO.0` | DC 2 V a sinus 1 kHz z obou generátorů změřené scope téhož AD3, dlouhý záznam (200 000 vzorků) v režimu record |
| `test_analog_multiplexer_loopback` | `HIL_HW_ANALOG_LOOP=AO.1:AI.1,AO.2:AI.3` (nejvýš 2 páry) a propojky mezi svorkami | oba generátory přes výstupní multiplexer, měřicí multiplexer a stav bez signálu po odpojení |
```

Za tabulku přidat odstavec: „`test_ad3_generator_loopback` ověřuje vazbu na WaveForms SDK (funkce generátoru, úroveň DC, režim record). Tolerance jsou 0,1 V u DC a 5 % u RMS. `HIL_HW_AD3_LOOP` povolí test jen s hodnotou `1`. Svorka `AO.0` je na generátoru 1 trvale, proto musí být při testu odpojená od DUT.“

- [ ] **Step 6: `doc/software/nasazeni.md`**

- Bod 4 v oddílu Linux nahradit: „4. WaveForms a Adept runtime pro Analog Discovery 3 se instalují podle [návodu Digilentu](https://digilent.com/reference/test-and-measurement/guides/getting-started-with-raspberry-pi) (na Raspberry Pi 5 verze ARM64, na x86 balíčky `.deb` pro amd64). Adept runtime přidá pravidla udev pro přístup k AD3. Ovladač `analog_discovery_3` načte knihovnu `libdwf.so` při otevření stanoviště. Pokud je knihovna jinde než v cestě dynamického linkeru, uveďte ji ve stanovišti volbou `library`. Ověření: `hil check --station stations/lab-a.yaml --probe`.“
- Do oddílu Windows přidat bod: „WaveForms (s Adept runtime) nainstaluje `dwf.dll` do systémového adresáře, ovladač ji najde bez další konfigurace. Program WaveForms musí být během testů zavřený, AD3 jde otevřít jen jedním programem.“

- [ ] **Step 7: Kontroly a commit**

Run: `.venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy && .venv/Scripts/python -m pytest -q && .venv/Scripts/python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
```bash
git add stations/lab-a.yaml tests/hw doc
git commit -m "doc: analog na stanovišti lab-a, HW testy AD3 a dokumentace analogu"
```

---

## Po dokončení všech úkolů

- Celková kontrola větve (subagent-driven: závěrečný review celé změny).
- Aktualizovat paměť projektu: plán 4 hotový. Na HW zbývá ověřit funkce WaveForms SDK (úroveň `funcDC` z offsetu, idle offset, režim record), tolerance měření a přepínání multiplexeru.
- Všechny lokální commity sloučit do jednoho („feat: analogová část balíčku hil (Analog Discovery 3, AnalogBlock, multiplexery)“). Push až po potvrzení zadavatelem.

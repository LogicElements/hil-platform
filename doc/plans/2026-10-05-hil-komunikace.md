# Komunikace balíčku `hil` – implementační plán (plán 2 ze 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Cíl:** sériová konzole a log DUT, aktivní RS-485 (Modbus RTU master i slave, surové a vadné rámce, zahlcení) a pasivní monitor RS-485 s dekódováním, vše použitelné z testů přes `dut.<signál>` a spustitelné na simulovaném stanovišti `sim`.

**Architektura:** nad pyserialem vzniká prostředek `SerialLink`. Poskytuje ho ovladač `serial_ports` (skutečné porty, FT4232H) a ovladač `sim_serial`. Ten registruje vlastní URL handler `hilsim://`, takže simulované porty jsou plnohodnotné objekty pyserialu. Modbus RTU (CRC, sestavení a dekódování rámců, master, slave, dělení proudu bajtů na rámce) je vlastní implementace v `hil.comm`. Signály `serial`, `rs485` a `rs485_monitor` sdílejí základ `PortSignal`, který port otevírá s parametry z `dut.yaml`.

**Tech stack:** Python ≥ 3.12, pyserial 3.5, types-pyserial, pydantic v2, pytest.

**Spec:** [doc/specs/2026-10-05-hil-python-package-design.md](../specs/2026-10-05-hil-python-package-design.md). Navazuje na [plán 1](2026-10-05-hil-jadro.md), který je hotový na `main`.

**Odchylky od specifikace (k potvrzení zadavatelem, úkol 10 je zapíše do specifikace):**
- Modbus RTU master a slave jsou vlastní implementace v `hil.comm` místo pymodbus. Důvody: potřebujeme řízení na úrovni bajtů kvůli injektáži poruch, API pymodbus se mezi verzemi 3.x mění (`slave=` → `device_id=`) a vlastní kód je menší než obal nad cizí knihovnou se dvěma vlákny.
- `inject(kind, frame)` dostává rámec, který se má poškodit. Specifikace uvádí jen `inject(kind)`.
- Na Windows se latency timer FTDI nekontroluje (bez D2XX ho nelze přečíst), jen se zaloguje upozornění. Na Linuxu se nastaví přes sysfs.

**Navazující plány:** plán 3 (reálné Modbus ovladače relé a vstupů, OpenOCD, `lab-a.yaml`, HW testy, nasazení), plán 4 (analog).

## Global Constraints

- `requires-python = ">=3.12"`, CI na `ubuntu-latest` a `windows-latest`, Python 3.12, 3.13, 3.14.
- Zdrojový kód včetně komentářů, docstringů, zpráv výjimek a výstupu CLI je anglicky. Dokumentace v `doc/` je česky.
- Nové závislosti: jen `pyserial>=3.5` (runtime) a `types-pyserial` (dev). pymodbus ani numpy se nepřidávají.
- mypy strict platí pro `hil.config.*`, `hil.blocks.*`, `hil.signals.*` a nově `hil.comm.*`.
- Všechna časová razítka jsou z `hil.clock.now()` (= `time.perf_counter()`), v sekundách.
- Vytvoření zařízení nedělá žádné I/O, hardware se otevírá v `Device.open()`. `open`/`close`/`safe_state` hlásí selhání jako `DeviceError`.
- Porty signálů se čtou s krátkým timeoutem (`PortSignal.read_timeout_s = 0.01`). Všechna vlákna jsou `daemon` a zastavují se v `safe_state()` nebo `close()`.
- Modbus: adresa 0 je broadcast (bez odpovědi), CRC-16/MODBUS se přenáší nižším bajtem napřed, registry big-endian, bity LSB first.
- Před každým commitem musí projít: `ruff format .`, `ruff check .`, `mypy`, `python -m pytest` a `python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml`.
- Pracuje se na větvi `main`, bez vlastních větví, bez push. Commit zprávy česky ve stylu repozitáře.
- Když `ruff check` hlásí E501 u dlouhého řetězce v kódu z plánu, řetězec se rozdělí. Chování se nemění.

## Review Focus

1. **DUT na Modbus neodpovídá** (chybějící zařízení, jiná adresa, jiná rychlost): master vyhodí `DeviceTimeout` nejpozději po `timeout_s`, nikdy nezamrzne. Test: úkol 7 `test_silent_slave_times_out`, `test_other_address_times_out`.
2. **Požadavek a odpověď přijdou v jednom čtení bez měřitelné mezery** (921 600 Bd, latence USB): monitor je rozdělí na dva rámce. Test: úkol 3 `test_back_to_back_frames_in_one_chunk`.
3. **Smetí nebo neúplný rámec na sběrnici:** monitor ho nahlásí jako chybový rámec, další platné rámce dekóduje a běží dál. Testy: úkol 3 `test_garbage_then_valid_frame`, úkol 8 `test_monitor_survives_garbage`.
4. **Výstup konzole z předchozího testu nebo starší než očekávaný bod:** `expect()` ho po bezpečném stavu nenajde. Při timeoutu zpráva obsahuje konec přijatého výstupu. Testy: úkol 6 `test_safe_state_forgets_output`, `test_expect_timeout_shows_tail`.
5. **Překlep v parametrech sériového signálu v `dut.yaml`** (`buad: 9600`) **nebo parametry u signálu, který žádné nemá:** `ConfigError` už při načtení, ne až v testu. Testy: úkol 1 `test_dut_serial_param_typo`, `test_params_on_signal_without_parameters`.

---

## Struktura souborů

```
pyproject.toml                         # + pyserial, types-pyserial, mypy strict hil.comm
.github/workflows/package.yml          # actions/checkout@v5, actions/setup-python@v6
src/hil/config/models.py               # + SerialParams, signal_params
src/hil/config/loader.py               # load_dut validates signal parameters
src/hil/comm/__init__.py
src/hil/comm/modbus.py                 # CRC, request builders, decode, ModbusFrame
src/hil/comm/framing.py                # Frame, frame_length, split_frames, FrameSplitter
src/hil/comm/faults.py                 # corrupt_crc, truncate, extend, wrong_parity
src/hil/comm/master.py                 # ModbusMaster, ModbusExceptionResponse
src/hil/comm/slave.py                  # ModbusSlave, ModbusDataStore
src/hil/resources.py                   # + SerialProvider, SerialLink, port_settings
src/hil/drivers/sim/serial_bus.py      # registry of simulated buses
src/hil/drivers/sim/protocol_hilsim.py # pyserial URL handler hilsim://
src/hil/drivers/sim/serial_port.py     # driver sim_serial
src/hil/drivers/serial_ports.py        # driver serial_ports
src/hil/recording.py                   # + write_line
src/hil/signals/base.py                # + close()
src/hil/signals/port.py                # PortSignal
src/hil/signals/uart.py                # SerialSignal
src/hil/signals/rs485.py               # Rs485Signal, Rs485Monitor
src/hil/blocks/comm.py                 # CommBlock
src/hil/station.py                     # builds comm terminals, closes signals
src/hil/dut.py                         # configures and opens port signals
src/hil/cli.py                         # info lists the comm block
src/hil/stations/sim.yaml              # + device ser, terminals CON, LOG, COM1, MON1
examples/dut.yaml, examples/tests/test_comm_on_sim.py
doc/software/konfigurace.md, doc/software/testy.md, doc/specs/...design.md
```

---

### Úkol 1: Závislosti, parametry sériových signálů, CI

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/package.yml`, `src/hil/config/models.py`, `src/hil/config/loader.py`
- Test: `tests/config/test_models.py`, `tests/config/test_loader.py`

**Interfaces:**
- Consumes: `DutConfig`, `SignalSpec.params()`, `Profile`, `load_dut` (plán 1).
- Produces:
  - `SerialParams` (pydantic, frozen, `extra="forbid"`): `baud: int = 115200`, `parity: Literal["N","E","O"] = "N"`, `stopbits: Literal[1,2] = 1`, `bytesize: Literal[7,8] = 8`, `timeout_s: float = 1.0`, `echo: bool = False`, `frame_gap_s: float | None = None`; metody `char_time_s() -> float`, `gap_s() -> float`.
  - `PARAM_MODELS: dict[str, type[BaseModel]]` (klíče `serial`, `rs485`, `rs485_monitor`).
  - `signal_params(kind: str, params: dict[str, Any]) -> BaseModel | None` (vyhodí `ValueError`, pydantic `ValidationError` je jeho podtřída).
  - `load_dut` vyhodí `ConfigError` pro neplatné parametry signálu.

- [ ] **Step 1: Napsat padající testy**

Do `tests/config/test_models.py` přidat import `SerialParams, signal_params` z `hil.config.models` a na konec:
```python
def test_serial_params_defaults_and_gap():
    params = SerialParams()
    assert (params.baud, params.parity, params.stopbits, params.bytesize) == (115200, "N", 1, 8)
    assert SerialParams(baud=9600).gap_s() == pytest.approx(3.5 * 10 / 9600)
    assert SerialParams(baud=921600, parity="E").gap_s() == 0.0015
    assert SerialParams(frame_gap_s=0.01).gap_s() == 0.01
    assert SerialParams(baud=19200, parity="E").char_time_s() == pytest.approx(11 / 19200)


def test_signal_params():
    assert signal_params("power", {}) is None
    params = signal_params("rs485", {"baud": 19200, "parity": "E"})
    assert params == SerialParams(baud=19200, parity="E")
    with pytest.raises(ValueError, match="takes no parameters"):
        signal_params("switch", {"baud": 1})
    with pytest.raises(ValidationError):
        signal_params("serial", {"parity": "X"})
```

Na konec `tests/config/test_loader.py`:
```python
def test_dut_serial_params(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON, baud: 9600, parity: E}\n"
    dut = load_dut(write(tmp_path, "dut.yaml", text), profile)
    assert dut.signals["console"].params() == {"baud": 9600, "parity": "E"}


def test_dut_serial_param_typo(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON, buad: 9600}\n"
    with pytest.raises(ConfigError, match=r"signal 'console': buad: Extra inputs"):
        load_dut(write(tmp_path, "dut.yaml", text), profile)


def test_dut_invalid_parity(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON, parity: X}\n"
    with pytest.raises(ConfigError, match=r"signal 'console': parity"):
        load_dut(write(tmp_path, "dut.yaml", text), profile)


def test_params_on_signal_without_parameters(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT.replace("supply: PWR", "supply: {terminal: PWR, baud: 9600}")
    with pytest.raises(ConfigError, match=r"signal 'supply': terminal kind 'power' takes no parameters"):
        load_dut(write(tmp_path, "dut.yaml", text), profile)
```

- [ ] **Step 2: Ověřit, že testy padají**

Run: `python -m pytest tests/config -v`
Expected: FAIL, `ImportError: cannot import name 'SerialParams'`.

- [ ] **Step 3: Doplnit `src/hil/config/models.py`**

Na konec souboru přidat:
```python
class SerialParams(_Strict):
    """Line parameters of a ``serial``, ``rs485`` or ``rs485_monitor`` DUT signal."""

    baud: int = Field(default=115200, gt=0)
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    bytesize: Literal[7, 8] = 8
    # rs485: how long the Modbus master waits for a response
    timeout_s: float = Field(default=1.0, gt=0)
    # rs485: the transceiver echoes what the platform sends
    echo: bool = False
    # rs485_monitor: silence that ends a frame; default 3.5 characters, at least 1.5 ms
    frame_gap_s: float | None = Field(default=None, gt=0)

    def char_time_s(self) -> float:
        """Duration of one character on the line (start, data, parity and stop bits)."""
        bits = 1 + self.bytesize + (0 if self.parity == "N" else 1) + self.stopbits
        return bits / self.baud

    def gap_s(self) -> float:
        if self.frame_gap_s is not None:
            return self.frame_gap_s
        return max(3.5 * self.char_time_s(), 0.0015)


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "serial": SerialParams,
    "rs485": SerialParams,
    "rs485_monitor": SerialParams,
}


def signal_params(kind: str, params: dict[str, Any]) -> BaseModel | None:
    """Validated parameters of a DUT signal on a terminal of ``kind``.

    Raises ``ValueError`` (pydantic's ``ValidationError`` included) for invalid ones.
    """
    model = PARAM_MODELS.get(kind)
    if model is None:
        if params:
            raise ValueError(f"terminal kind {kind!r} takes no parameters, got {sorted(params)}")
        return None
    return model.model_validate(params)
```

- [ ] **Step 4: Doplnit validaci do `load_dut` v `src/hil/config/loader.py`**

Import rozšířit na `from hil.config.models import DutConfig, Profile, StationConfig, signal_params`. Ve smyčce `for name, spec in dut.signals.items():` za kontrolu existence svorky přidat:
```python
        kind = profile.terminals[spec.terminal]
        try:
            signal_params(kind, spec.params())
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConfigError(f"{path}: signal {name!r}: {details}") from exc
        except ValueError as exc:
            raise ConfigError(f"{path}: signal {name!r}: {exc}") from exc
```

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest tests/config -v`
Expected: všechny PASS.

- [ ] **Step 6: Závislosti a CI**

V `pyproject.toml`:
- do `dependencies` přidat `"pyserial>=3.5",`,
- `dev` změnit na `["ruff>=0.6", "mypy>=1.12", "types-PyYAML", "types-pyserial"]`,
- v `[[tool.mypy.overrides]]` změnit `module` na `["hil.config.*", "hil.blocks.*", "hil.signals.*", "hil.comm.*"]`.

V `.github/workflows/package.yml` změnit `actions/checkout@v4` na `actions/checkout@v5` a `actions/setup-python@v5` na `actions/setup-python@v6` (Node.js 20 se ruší).

Potom:
```
python -m pip install -e ".[dev]"
python -c "import serial; print(serial.__version__)"
```
Expected: `3.5`.

- [ ] **Step 7: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
git add pyproject.toml .github/workflows/package.yml src/hil/config tests/config
git commit -m "feat: parametry sériových signálů DUT a závislost pyserial"
```

---

### Úkol 2: Modbus RTU – CRC, sestavení a dekódování rámců

**Files:**
- Create: `src/hil/comm/__init__.py`, `src/hil/comm/modbus.py`
- Test: `tests/comm/test_modbus.py`

**Interfaces:**
- Produces (modul `hil.comm.modbus`):
  - konstanty funkcí `READ_COILS=1`, `READ_DISCRETE_INPUTS=2`, `READ_HOLDING_REGISTERS=3`, `READ_INPUT_REGISTERS=4`, `WRITE_SINGLE_COIL=5`, `WRITE_SINGLE_REGISTER=6`, `WRITE_MULTIPLE_COILS=15`, `WRITE_MULTIPLE_REGISTERS=16`, množiny `BIT_READS`, `REGISTER_READS`, limity `MAX_READ_BITS=2000`, `MAX_READ_REGISTERS=125`, `MAX_WRITE_BITS=1968`, `MAX_WRITE_REGISTERS=123`.
  - `crc16_step(crc, byte) -> int`, `crc16(data) -> int`, `with_crc(body) -> bytes`, `crc_ok(frame) -> bool`.
  - `request(address, function, payload=b"") -> bytes`, `read_request(address, function, start, count)`, `write_coil_request(address, coil, on)`, `write_register_request(address, register, value)`, `write_coils_request(address, start, values)`, `write_registers_request(address, start, values)` – vše vrací `bytes` s CRC, neplatné argumenty → `ValueError`.
  - `pack_bits(values) -> bytes`, `unpack_bits(data, count=None) -> list[bool]`.
  - `FrameKind = Literal["request", "response", "exception", "unknown"]`, `@dataclass(frozen=True) ModbusFrame(address, function, kind, fields: dict[str, object])` s `to_dict()`.
  - `decode(frame) -> ModbusFrame` (rámec se špatným CRC → `ValueError`).

- [ ] **Step 1: Napsat padající test `tests/comm/test_modbus.py`**

```python
import pytest

from hil.comm import modbus


def test_crc_known_values():
    assert modbus.crc16(b"123456789") == 0x4B37
    assert modbus.with_crc(bytes.fromhex("01 03 00 00 00 0A")) == bytes.fromhex(
        "01 03 00 00 00 0A C5 CD"
    )
    assert modbus.with_crc(bytes.fromhex("11 06 00 01 00 03")) == bytes.fromhex(
        "11 06 00 01 00 03 9A 9B"
    )


def test_crc_ok():
    frame = modbus.with_crc(b"\x01\x03\x00\x00\x00\x01")
    assert modbus.crc_ok(frame)
    assert not modbus.crc_ok(frame[:-1] + bytes([frame[-1] ^ 1]))
    assert not modbus.crc_ok(b"\x01\x03\x00")


def test_read_request():
    assert modbus.read_request(1, 3, 0, 10) == bytes.fromhex("01 03 00 00 00 0A C5 CD")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((248, 3, 0, 1), "address"),
        ((1, 3, 0, 0), "count"),
        ((1, 3, 0, 126), "count"),
        ((1, 1, 0, 2001), "count"),
        ((1, 6, 0, 1), "not a read function"),
    ],
)
def test_read_request_validation(args, message):
    with pytest.raises(ValueError, match=message):
        modbus.read_request(*args)


def test_write_builders():
    assert modbus.write_register_request(0x11, 1, 3) == bytes.fromhex("11 06 00 01 00 03 9A 9B")
    coil = modbus.write_coil_request(1, 2, True)
    assert coil[:6] == bytes.fromhex("01 05 00 02 FF 00")
    registers = modbus.write_registers_request(1, 16, [1, 2])
    assert registers[:-2] == bytes.fromhex("01 10 00 10 00 02 04 00 01 00 02")
    coils = modbus.write_coils_request(1, 0, [True, False, True])
    assert coils[:-2] == bytes.fromhex("01 0F 00 00 00 03 01 05")
    with pytest.raises(ValueError, match="value"):
        modbus.write_register_request(1, 0, 0x10000)


def test_bits_round_trip():
    values = [True, False, False, True, True, False, False, False, True]
    packed = modbus.pack_bits(values)
    assert packed == bytes([0b00011001, 0b00000001])
    assert modbus.unpack_bits(packed, len(values)) == values


def test_decode_read_request_and_responses():
    request = modbus.decode(modbus.read_request(1, 3, 5, 2))
    assert (request.kind, request.fields) == ("request", {"start": 5, "count": 2})
    registers = modbus.decode(modbus.with_crc(bytes([1, 3, 4, 0, 42, 1, 0])))
    assert (registers.kind, registers.fields) == ("response", {"values": [42, 256]})
    bits = modbus.decode(modbus.with_crc(bytes([1, 1, 1, 0b101])))
    assert bits.kind == "response"
    assert bits.fields["bits"][:3] == [True, False, True]


def test_decode_exception_and_writes():
    exception = modbus.decode(modbus.with_crc(bytes([1, 0x83, 2])))
    assert (exception.kind, exception.fields) == ("exception", {"code": 2})
    single = modbus.decode(modbus.write_register_request(1, 7, 99))
    assert single.fields == {"register": 7, "value": 99}
    coil = modbus.decode(modbus.write_coil_request(1, 3, True))
    assert coil.fields == {"coil": 3, "on": True}
    multiple = modbus.decode(modbus.write_registers_request(1, 16, [1, 2]))
    assert (multiple.kind, multiple.fields) == ("request", {"start": 16, "count": 2, "values": [1, 2]})
    answer = modbus.decode(modbus.with_crc(bytes.fromhex("01 10 00 10 00 02")))
    assert (answer.kind, answer.fields) == ("response", {"start": 16, "count": 2})


def test_decode_unknown_and_bad_crc():
    unknown = modbus.decode(modbus.with_crc(bytes([1, 0x2B, 0x0E, 1])))
    assert unknown.kind == "unknown"
    assert unknown.to_dict()["address"] == 1
    with pytest.raises(ValueError, match="bad CRC"):
        modbus.decode(b"\x01\x03\x00\x00\x00\x01\x00\x00")
```

- [ ] **Step 2: Ověřit, že test padá**

Run: `python -m pytest tests/comm/test_modbus.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hil.comm'`.

- [ ] **Step 3: Vytvořit `src/hil/comm/__init__.py`**

```python
"""Communication: Modbus RTU frames, master, slave and bus capture."""
```

- [ ] **Step 4: Vytvořit `src/hil/comm/modbus.py`**

```python
"""Modbus RTU frames: CRC, building of requests and decoding."""

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

READ_COILS = 1
READ_DISCRETE_INPUTS = 2
READ_HOLDING_REGISTERS = 3
READ_INPUT_REGISTERS = 4
WRITE_SINGLE_COIL = 5
WRITE_SINGLE_REGISTER = 6
WRITE_MULTIPLE_COILS = 15
WRITE_MULTIPLE_REGISTERS = 16

BIT_READS = frozenset({READ_COILS, READ_DISCRETE_INPUTS})
REGISTER_READS = frozenset({READ_HOLDING_REGISTERS, READ_INPUT_REGISTERS})

MAX_READ_BITS = 2000
MAX_READ_REGISTERS = 125
MAX_WRITE_BITS = 1968
MAX_WRITE_REGISTERS = 123

FrameKind = Literal["request", "response", "exception", "unknown"]


def crc16_step(crc: int, byte: int) -> int:
    """Feed one byte into a running CRC-16/MODBUS."""
    crc ^= byte
    for _ in range(8):
        crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS of ``data``."""
    crc = 0xFFFF
    for byte in data:
        crc = crc16_step(crc, byte)
    return crc


def with_crc(body: bytes) -> bytes:
    """``body`` followed by its CRC, low byte first."""
    return body + crc16(body).to_bytes(2, "little")


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")


def _check(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be in {low}..{high}, got {value}")


def request(address: int, function: int, payload: bytes = b"") -> bytes:
    """A request for ``address`` (0 = broadcast) with ``payload`` and CRC."""
    _check("address", address, 0, 247)
    _check("function", function, 1, 127)
    return with_crc(bytes((address, function)) + payload)


def read_request(address: int, function: int, start: int, count: int) -> bytes:
    if function not in BIT_READS | REGISTER_READS:
        raise ValueError(f"function {function} is not a read function")
    limit = MAX_READ_BITS if function in BIT_READS else MAX_READ_REGISTERS
    _check("start", start, 0, 0xFFFF)
    _check("count", count, 1, limit)
    return request(address, function, struct.pack(">HH", start, count))


def write_coil_request(address: int, coil: int, on: bool) -> bytes:
    _check("coil", coil, 0, 0xFFFF)
    return request(address, WRITE_SINGLE_COIL, struct.pack(">HH", coil, 0xFF00 if on else 0))


def write_register_request(address: int, register: int, value: int) -> bytes:
    _check("register", register, 0, 0xFFFF)
    _check("value", value, 0, 0xFFFF)
    return request(address, WRITE_SINGLE_REGISTER, struct.pack(">HH", register, value))


def write_coils_request(address: int, start: int, values: Sequence[bool]) -> bytes:
    _check("start", start, 0, 0xFFFF)
    _check("count", len(values), 1, MAX_WRITE_BITS)
    packed = pack_bits(values)
    header = struct.pack(">HHB", start, len(values), len(packed))
    return request(address, WRITE_MULTIPLE_COILS, header + packed)


def write_registers_request(address: int, start: int, values: Sequence[int]) -> bytes:
    _check("start", start, 0, 0xFFFF)
    _check("count", len(values), 1, MAX_WRITE_REGISTERS)
    for value in values:
        _check("value", value, 0, 0xFFFF)
    data = struct.pack(f">{len(values)}H", *values)
    header = struct.pack(">HHB", start, len(values), len(data))
    return request(address, WRITE_MULTIPLE_REGISTERS, header + data)


def pack_bits(values: Sequence[bool]) -> bytes:
    """Bits packed LSB first, as Modbus transfers coils and discrete inputs."""
    packed = bytearray((len(values) + 7) // 8)
    for index, value in enumerate(values):
        if value:
            packed[index // 8] |= 1 << (index % 8)
    return bytes(packed)


def unpack_bits(data: bytes, count: int | None = None) -> list[bool]:
    bits = [bool(data[i // 8] >> (i % 8) & 1) for i in range(len(data) * 8)]
    return bits if count is None else bits[:count]


@dataclass(frozen=True)
class ModbusFrame:
    """A decoded Modbus RTU frame."""

    address: int
    function: int
    kind: FrameKind
    fields: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "address": self.address,
            "function": self.function,
            "kind": self.kind,
            **self.fields,
        }


def decode(frame: bytes) -> ModbusFrame:
    """Decode a frame with a valid CRC.

    Requests and responses are told apart by their length. A single write (functions 5
    and 6) is answered by an identical echo, so both are reported as ``request``. A
    bit-read response with three data bytes has the length of a request and is
    reported as a request.
    """
    if not crc_ok(frame):
        raise ValueError(f"bad CRC in frame {frame.hex(' ')}")
    address, function = frame[0], frame[1]
    data = frame[2:-2]
    if function & 0x80:
        if len(data) == 1:
            return ModbusFrame(address, function, "exception", {"code": data[0]})
    elif function in BIT_READS | REGISTER_READS:
        if len(data) == 4:
            start, count = struct.unpack(">HH", data)
            return ModbusFrame(address, function, "request", {"start": start, "count": count})
        if data and data[0] == len(data) - 1:
            payload = data[1:]
            if function in BIT_READS:
                return ModbusFrame(address, function, "response", {"bits": unpack_bits(payload)})
            if len(payload) % 2 == 0:
                values = list(struct.unpack(f">{len(payload) // 2}H", payload))
                return ModbusFrame(address, function, "response", {"values": values})
    elif function in (WRITE_SINGLE_COIL, WRITE_SINGLE_REGISTER):
        if len(data) == 4:
            target, value = struct.unpack(">HH", data)
            if function == WRITE_SINGLE_COIL:
                fields: dict[str, object] = {"coil": target, "on": value == 0xFF00}
            else:
                fields = {"register": target, "value": value}
            return ModbusFrame(address, function, "request", fields)
    elif function in (WRITE_MULTIPLE_COILS, WRITE_MULTIPLE_REGISTERS):
        if len(data) == 4:
            start, count = struct.unpack(">HH", data)
            return ModbusFrame(address, function, "response", {"start": start, "count": count})
        if len(data) >= 5 and data[4] == len(data) - 5:
            start, count = struct.unpack(">HH", data[:4])
            payload = data[5:]
            if function == WRITE_MULTIPLE_COILS:
                bits = unpack_bits(payload, count)
                return ModbusFrame(
                    address, function, "request", {"start": start, "count": count, "bits": bits}
                )
            if len(payload) == 2 * count:
                values = list(struct.unpack(f">{count}H", payload))
                return ModbusFrame(
                    address, function, "request", {"start": start, "count": count, "values": values}
                )
    return ModbusFrame(address, function, "unknown", {"data": data.hex(" ")})
```

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest tests/comm/test_modbus.py -v`
Expected: všechny PASS. Pokud selže některý z referenčních vektorů CRC v `test_crc_known_values`, nesahat na test bez ověření: hodnota `0x4B37` je kontrolní hodnota CRC-16/MODBUS pro `"123456789"`, rámce `01 03 00 00 00 0A C5 CD` a `11 06 00 01 00 03 9A 9B` jsou příklady ze specifikace Modbus. Odchylku popsat v reportu.

- [ ] **Step 6: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/comm tests/comm
git commit -m "feat: kodek rámců Modbus RTU"
```

---

### Úkol 3: Dělení přijatých bajtů na rámce a vadné rámce

**Files:**
- Create: `src/hil/comm/framing.py`, `src/hil/comm/faults.py`
- Test: `tests/comm/test_framing.py`, `tests/comm/test_faults.py`

**Interfaces:**
- Consumes: `crc16_step`, `decode`, `ModbusFrame`, `crc_ok`, `read_request`, `with_crc` z úkolu 2.
- Produces:
  - `@dataclass(frozen=True) Frame(t: float, raw: bytes, decoded: ModbusFrame | None, error: str | None)` s `to_record(t: float) -> dict[str, object]` (klíče `t`, `raw` jako hex, `decoded`, `error`).
  - `MIN_FRAME = 4`, `MAX_FRAME = 256`, `NO_FRAME_ERROR` (text chyby).
  - `frame_length(data, start=0) -> int | None`, `split_frames(data, t) -> list[Frame]`.
  - `FrameSplitter(gap_s, max_burst=1024)` s `feed(data, t) -> list[Frame]`, `poll(t) -> list[Frame]`, `flush() -> list[Frame]`, atribut `gap_s`.
  - `FaultKind = Literal["bad_crc", "truncated", "extended", "bad_parity"]`, `FAULT_KINDS`, `corrupt_crc(frame)`, `truncate(frame, count=1)`, `extend(frame, extra=b"\x00")`, `wrong_parity(parity) -> str`.

- [ ] **Step 1: Napsat padající testy**

`tests/comm/test_framing.py`:
```python
from hil.comm import modbus
from hil.comm.framing import (
    NO_FRAME_ERROR,
    FrameSplitter,
    frame_length,
    split_frames,
)

REQUEST = modbus.read_request(1, 3, 0, 2)
RESPONSE = modbus.with_crc(bytes([1, 3, 4, 0, 1, 0, 2]))


def test_frame_length():
    assert frame_length(REQUEST) == len(REQUEST)
    assert frame_length(REQUEST + RESPONSE) == len(REQUEST)
    assert frame_length(REQUEST + RESPONSE, len(REQUEST)) == len(RESPONSE)
    assert frame_length(b"\x01\x02\x03") is None
    assert frame_length(REQUEST[:-1]) is None


def test_back_to_back_frames_in_one_chunk():
    frames = split_frames(REQUEST + RESPONSE, t=1.0)
    assert [f.raw for f in frames] == [REQUEST, RESPONSE]
    assert [f.decoded.kind for f in frames] == ["request", "response"]
    assert all(f.error is None and f.t == 1.0 for f in frames)


def test_garbage_then_valid_frame():
    splitter = FrameSplitter(gap_s=0.002)
    assert splitter.feed(b"\x01\x02\x03", t=0.0) == []
    frames = splitter.feed(REQUEST, t=0.010)
    assert len(frames) == 1
    assert frames[0].raw == b"\x01\x02\x03"
    assert frames[0].error == NO_FRAME_ERROR
    assert frames[0].decoded is None
    later = splitter.poll(t=0.020)
    assert [f.raw for f in later] == [REQUEST]
    assert later[0].t == 0.010


def test_chunks_within_gap_form_one_burst():
    splitter = FrameSplitter(gap_s=0.002)
    assert splitter.feed(REQUEST[:3], t=0.0) == []
    assert splitter.feed(REQUEST[3:], t=0.001) == []
    assert splitter.poll(t=0.0025) == []
    frames = splitter.poll(t=0.004)
    assert [f.raw for f in frames] == [REQUEST]
    assert frames[0].t == 0.0


def test_incomplete_frame_is_an_error_after_gap():
    splitter = FrameSplitter(gap_s=0.002)
    splitter.feed(REQUEST[:-1], t=0.0)
    frames = splitter.poll(t=0.01)
    assert frames[0].error == NO_FRAME_ERROR


def test_flush_and_max_burst():
    splitter = FrameSplitter(gap_s=1.0, max_burst=16)
    assert splitter.feed(REQUEST, t=0.0) == []
    frames = splitter.feed(RESPONSE + b"\xff" * 10, t=0.0)
    assert [f.raw for f in frames[:2]] == [REQUEST, RESPONSE]
    assert frames[2].error == NO_FRAME_ERROR
    assert splitter.flush() == []


def test_to_record():
    frame = split_frames(REQUEST, t=5.0)[0]
    record = frame.to_record(0.25)
    assert record["t"] == 0.25
    assert record["raw"] == REQUEST.hex(" ")
    assert record["decoded"]["kind"] == "request"
    assert record["error"] is None
```

`tests/comm/test_faults.py`:
```python
import pytest

from hil.comm import modbus
from hil.comm.faults import FAULT_KINDS, corrupt_crc, extend, truncate, wrong_parity
from hil.comm.framing import split_frames

FRAME = modbus.read_request(1, 3, 0, 1)


def test_corrupt_crc():
    bad = corrupt_crc(FRAME)
    assert len(bad) == len(FRAME)
    assert bad[:-2] == FRAME[:-2]
    assert not modbus.crc_ok(bad)


def test_truncate_and_extend():
    assert truncate(FRAME) == FRAME[:-1]
    assert truncate(FRAME, 3) == FRAME[:-3]
    longer = extend(FRAME)
    assert longer == FRAME + b"\x00"
    frames = split_frames(longer, t=0.0)
    assert frames[0].raw == FRAME
    assert frames[1].raw == b"\x00"
    assert frames[1].error is not None


@pytest.mark.parametrize("count", [0, len(FRAME)])
def test_truncate_rejects_bad_count(count):
    with pytest.raises(ValueError):
        truncate(FRAME, count)


def test_extend_needs_bytes():
    with pytest.raises(ValueError):
        extend(FRAME, b"")


def test_wrong_parity():
    assert wrong_parity("N") == "E"
    assert wrong_parity("E") == "O"
    assert wrong_parity("O") == "E"
    assert FAULT_KINDS == ("bad_crc", "truncated", "extended", "bad_parity")
```

- [ ] **Step 2: Ověřit, že testy padají**

Run: `python -m pytest tests/comm -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hil.comm.framing'`.

- [ ] **Step 3: Vytvořit `src/hil/comm/framing.py`**

```python
"""Splitting of received bytes into Modbus RTU frames."""

from dataclasses import dataclass

from hil.comm.modbus import ModbusFrame, crc16_step, decode

MIN_FRAME = 4
MAX_FRAME = 256
NO_FRAME_ERROR = "no valid Modbus RTU frame (bad CRC or incomplete frame)"


@dataclass(frozen=True)
class Frame:
    """Bytes seen on the bus: ``decoded`` for a valid frame, ``error`` otherwise."""

    t: float
    raw: bytes
    decoded: ModbusFrame | None
    error: str | None

    def to_record(self, t: float) -> dict[str, object]:
        """JSON record with ``t`` (e.g. relative to the start of the test) as time stamp."""
        return {
            "t": round(t, 6),
            "raw": self.raw.hex(" "),
            "decoded": None if self.decoded is None else self.decoded.to_dict(),
            "error": self.error,
        }


def frame_length(data: bytes, start: int = 0) -> int | None:
    """Length of the shortest frame with a valid CRC at ``data[start:]``, or None."""
    crc = 0xFFFF
    end = min(len(data), start + MAX_FRAME)
    for pos in range(start, end - 1):
        # crc covers data[start:pos]; the candidate frame is data[start:pos + 2]
        if pos - start >= MIN_FRAME - 2 and crc == data[pos] | (data[pos + 1] << 8):
            return pos - start + 2
        crc = crc16_step(crc, data[pos])
    return None


def split_frames(data: bytes, t: float) -> list[Frame]:
    """Split one burst into frames; bytes that form no valid frame end it as an error."""
    frames: list[Frame] = []
    pos = 0
    while pos < len(data):
        length = frame_length(data, pos)
        if length is None:
            frames.append(Frame(t, data[pos:], None, NO_FRAME_ERROR))
            break
        raw = data[pos : pos + length]
        frames.append(Frame(t, raw, decode(raw), None))
        pos += length
    return frames


class FrameSplitter:
    """Groups received chunks into bursts separated by silence and splits them into frames.

    Every frame of a burst carries the time stamp of the burst's first chunk. Frames
    that follow each other without a measurable gap are still separated by their CRC.
    """

    def __init__(self, gap_s: float, max_burst: int = 4 * MAX_FRAME) -> None:
        self.gap_s = gap_s
        self.max_burst = max_burst
        self._buffer = bytearray()
        self._first = 0.0
        self._last = 0.0

    def feed(self, data: bytes, t: float) -> list[Frame]:
        frames = self.poll(t)
        if data:
            if not self._buffer:
                self._first = t
            self._buffer.extend(data)
            self._last = t
            if len(self._buffer) >= self.max_burst:
                frames += self.flush()
        return frames

    def poll(self, t: float) -> list[Frame]:
        """Frames of a burst that has been followed by enough silence."""
        if self._buffer and t - self._last > self.gap_s:
            return self.flush()
        return []

    def flush(self) -> list[Frame]:
        if not self._buffer:
            return []
        data = bytes(self._buffer)
        self._buffer.clear()
        return split_frames(data, self._first)
```

- [ ] **Step 4: Vytvořit `src/hil/comm/faults.py`**

```python
"""Faulty frames for fault injection."""

from typing import Literal

FaultKind = Literal["bad_crc", "truncated", "extended", "bad_parity"]
FAULT_KINDS: tuple[FaultKind, ...] = ("bad_crc", "truncated", "extended", "bad_parity")


def corrupt_crc(frame: bytes) -> bytes:
    if len(frame) < 3:
        raise ValueError("frame is too short to have a CRC")
    return frame[:-2] + bytes((frame[-2] ^ 0xFF, frame[-1]))


def truncate(frame: bytes, count: int = 1) -> bytes:
    if not 0 < count < len(frame):
        raise ValueError(f"cannot remove {count} of {len(frame)} bytes")
    return frame[:-count]


def extend(frame: bytes, extra: bytes = b"\x00") -> bytes:
    if not extra:
        raise ValueError("extra bytes must not be empty")
    return frame + extra


def wrong_parity(parity: str) -> str:
    """A parity setting that makes the receiver see parity or framing errors."""
    return {"N": "E", "E": "O", "O": "E"}[parity]
```

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest tests/comm -v`
Expected: všechny PASS.

- [ ] **Step 6: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/comm/framing.py src/hil/comm/faults.py tests/comm/test_framing.py tests/comm/test_faults.py
git commit -m "feat: dělení proudu bajtů na rámce Modbus a vadné rámce"
```

---

### Úkol 4: Simulované sériové sběrnice (`sim_serial`) a prostředek `SerialLink`

**Files:**
- Create: `src/hil/drivers/sim/serial_bus.py`, `src/hil/drivers/sim/protocol_hilsim.py`, `src/hil/drivers/sim/serial_port.py`
- Modify: `src/hil/resources.py`, `src/hil/drivers/sim/__init__.py`
- Test: `tests/drivers/test_sim_serial.py`

**Interfaces:**
- Consumes: `SerialParams` (úkol 1), `Device`, `DriverConfig`, `register_driver`, `create_device`, `DeviceConfig`, `DeviceError`, `ConfigError`.
- Produces:
  - `hil.resources.SerialProvider` (Protocol: `name`, `open_port(channel: str, params: SerialParams, timeout: float | None) -> serial.SerialBase`), `@dataclass(frozen=True) SerialLink(provider, channel)` s `open(params, timeout=None) -> serial.SerialBase`, `str(link) == "ser.con"`, a `port_settings(params) -> dict[str, Any]` (klíče `baudrate`, `bytesize`, `parity`, `stopbits`).
  - ovladač `sim_serial` (`SimSerial`), volba `buses: dict[str, list[str]]`; kanály jsou jména portů; `resource(channel) -> SerialLink`; `open_port(...)`; `endpoint(channel, params=None, timeout=0.01) -> serial.SerialBase` pro testy, které hrají DUT; `is_open`.
  - simulovaný port (`hil.drivers.sim.protocol_hilsim.Serial`, URL `hilsim://<klíč>/<port>`): co jeden port zapíše, dostanou všechny ostatní porty sběrnice; atribut `line_errors` (počet přijatých zápisů s jiným nastavením linky); po zavření zařízení `read`/`write` vyhodí `serial.SerialException`.

- [ ] **Step 1: Napsat padající test `tests/drivers/test_sim_serial.py`**

```python
import time

import pytest
from serial import SerialException

from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError
from hil.resources import SerialLink

BUSES = {"con": ["con", "dut_con"], "bus": ["com1", "mon1", "dut"]}


@pytest.fixture
def ser():
    device = create_device("ser", DeviceConfig(driver="sim_serial", buses=BUSES))
    device.open()
    yield device
    device.close()


def test_pair_delivers_to_peer_only(ser):
    with ser.endpoint("con") as a, ser.endpoint("dut_con") as b:
        assert a.write(b"hello") == 5
        assert b.read(5) == b"hello"
        assert a.read(5) == b""


def test_bus_delivers_to_all_other_ports(ser):
    with ser.endpoint("com1") as com1, ser.endpoint("mon1") as mon1, ser.endpoint("dut") as dut:
        com1.write(b"\x01\x03")
        dut.write(b"\x01\x83")
        assert mon1.read(4) == b"\x01\x03\x01\x83"
        assert dut.read(2) == b"\x01\x03"
        assert com1.read(2) == b"\x01\x83"
        assert com1.in_waiting == 0


def test_read_timeout(ser):
    with ser.endpoint("con", timeout=0.05) as a:
        start = time.perf_counter()
        assert a.read(1) == b""
        assert time.perf_counter() - start >= 0.04


def test_line_settings_mismatch_counts_errors(ser):
    with ser.endpoint("con", SerialParams(baud=9600)) as slow, ser.endpoint("dut_con") as fast:
        slow.write(b"x")
        assert fast.read(1) == b"x"
        assert fast.line_errors == 1
        assert slow.line_errors == 0


def test_resource(ser):
    link = ser.resource("con")
    assert isinstance(link, SerialLink)
    assert str(link) == "ser.con"
    with pytest.raises(ConfigError, match="no channel 'nope'"):
        ser.resource("nope")


def test_port_already_open(ser):
    with ser.endpoint("con"), pytest.raises(DeviceError, match="already open"):
        ser.endpoint("con")


def test_open_port_requires_open_device():
    device = create_device("ser", DeviceConfig(driver="sim_serial", buses=BUSES))
    with pytest.raises(DeviceError, match="not open"):
        device.endpoint("con")


def test_closed_device_fails_port_io(ser):
    port = ser.endpoint("con")
    ser.close()
    with pytest.raises(SerialException):
        port.read(1)
    with pytest.raises(SerialException):
        port.write(b"x")


def test_two_devices_with_same_name_are_independent(ser):
    other = create_device("ser", DeviceConfig(driver="sim_serial", buses=BUSES))
    other.open()
    try:
        with ser.endpoint("con") as a, other.endpoint("dut_con") as b:
            a.write(b"x")
            assert b.read(1) == b""
    finally:
        other.close()


@pytest.mark.parametrize(
    ("buses", "message"),
    [
        ({"a": ["only"]}, "at least two ports"),
        ({"a": ["p", "q"], "b": ["q", "r"]}, "more than one bus"),
        ({"a": ["p.1", "q"]}, "invalid port name"),
        ({}, "at least 1"),
    ],
)
def test_config_validation(buses, message):
    with pytest.raises(ConfigError, match=message):
        create_device("ser", DeviceConfig(driver="sim_serial", buses=buses))
```

- [ ] **Step 2: Ověřit, že test padá**

Run: `python -m pytest tests/drivers/test_sim_serial.py -v`
Expected: FAIL, `ConfigError: device 'ser': unknown driver 'sim_serial'` (nebo `ImportError` u `SerialLink`).

- [ ] **Step 3: Doplnit `src/hil/resources.py`**

Importy rozšířit na:
```python
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import serial

from hil.config.models import SerialParams
```
Na konec souboru přidat:
```python
class SerialProvider(Protocol):
    """A device with named serial ports."""

    name: str

    def open_port(
        self, channel: str, params: SerialParams, timeout: float | None
    ) -> serial.SerialBase: ...


@dataclass(frozen=True)
class SerialLink:
    provider: SerialProvider
    channel: str

    def open(self, params: SerialParams, timeout: float | None = None) -> serial.SerialBase:
        """Open the port with the DUT's line parameters and the given read timeout."""
        return self.provider.open_port(self.channel, params, timeout)

    def __str__(self) -> str:
        return f"{self.provider.name}.{self.channel}"


def port_settings(params: SerialParams) -> dict[str, Any]:
    """pyserial keyword arguments for the line parameters."""
    return {
        "baudrate": params.baud,
        "bytesize": params.bytesize,
        "parity": params.parity,
        "stopbits": params.stopbits,
    }
```

- [ ] **Step 4: Vytvořit `src/hil/drivers/sim/serial_bus.py`**

```python
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
```

- [ ] **Step 5: Vytvořit `src/hil/drivers/sim/protocol_hilsim.py`**

```python
"""pyserial URL handler ``hilsim://<registry key>/<port>`` for simulated serial ports.

pyserial finds this module because the ``sim_serial`` driver adds ``hil.drivers.sim``
to ``serial.protocol_handler_packages``.
"""

import threading
import time
from collections.abc import Buffer
from typing import Any
from urllib.parse import urlsplit

from serial.serialutil import PortNotOpenError, SerialBase, SerialException, to_bytes

from hil.drivers.sim import serial_bus


def parse_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    key, port = parts.netloc, parts.path.lstrip("/")
    if parts.scheme != "hilsim" or not key or not port:
        raise SerialException(f"expected 'hilsim://<key>/<port>', got {url!r}")
    return key, port


class Serial(SerialBase):
    """A port of a simulated bus (see ``hil.drivers.sim.serial_bus``)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._cond = threading.Condition()
        self._rx = bytearray()
        self._bus: serial_bus.SimBus | None = None
        # received writes whose line settings differ from ours; a real UART would
        # report parity or framing errors
        self.line_errors = 0
        super().__init__(*args, **kwargs)

    def open(self) -> None:
        if self._port is None:
            raise SerialException("Port must be configured before it can be used.")
        if self.is_open:
            raise SerialException("Port is already open.")
        key, port = parse_url(self.portstr)
        self._bus = serial_bus.attach(key, port, self)
        self.is_open = True

    def close(self) -> None:
        if self.is_open:
            self.is_open = False
            bus, self._bus = self._bus, None
            if bus is not None:
                bus.detach(self)
            with self._cond:
                self._cond.notify_all()
        super().close()

    def _reconfigure_port(self, *args: Any) -> None:
        """Line settings are compared with the sender's on every delivery."""

    def from_url(self, url: str) -> None:
        parse_url(url)

    def line_settings(self) -> serial_bus.LineSettings:
        return (self._baudrate, self._bytesize, self._parity, self._stopbits)

    def receive(self, data: bytes, settings: serial_bus.LineSettings) -> None:
        with self._cond:
            if settings != self.line_settings():
                self.line_errors += 1
            self._rx.extend(data)
            self._cond.notify_all()

    def bus_closed(self) -> None:
        with self._cond:
            self._bus = None
            self._cond.notify_all()

    @property
    def in_waiting(self) -> int:
        with self._cond:
            return len(self._rx)

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise PortNotOpenError()
        deadline = None if self._timeout is None else time.monotonic() + self._timeout
        with self._cond:
            while len(self._rx) < size:
                if not self.is_open:
                    raise PortNotOpenError()
                if self._bus is None:
                    if self._rx:
                        break
                    raise SerialException("simulated serial device was closed")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._cond.wait(remaining)
            data = bytes(self._rx[:size])
            del self._rx[:size]
        return data

    def write(self, data: Buffer, /) -> int:
        if not self.is_open:
            raise PortNotOpenError()
        payload = to_bytes(data)
        bus = self._bus
        if bus is None:
            raise SerialException("simulated serial device was closed")
        bus.deliver(self, payload)
        return len(payload)

    def reset_input_buffer(self) -> None:
        with self._cond:
            self._rx.clear()

    def reset_output_buffer(self) -> None:
        """Nothing is buffered on output."""

    @property
    def out_waiting(self) -> int:
        return 0

    def cancel_read(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def _update_break_state(self) -> None:
        """Break is not simulated."""

    def _update_rts_state(self) -> None:
        """Modem lines are not simulated."""

    def _update_dtr_state(self) -> None:
        """Modem lines are not simulated."""

    @property
    def cts(self) -> bool:
        return False

    @property
    def dsr(self) -> bool:
        return False

    @property
    def ri(self) -> bool:
        return False

    @property
    def cd(self) -> bool:
        return False
```

Pokud `mypy` nahlásí u přepsaných metod nesoulad se stuby `types-pyserial` (`override`), přidat k dotčenému řádku cílené `# type: ignore[override]` a uvést to v reportu. Chování neměnit.

- [ ] **Step 6: Vytvořit `src/hil/drivers/sim/serial_port.py`**

```python
"""Simulated serial buses (driver ``sim_serial``)."""

from collections.abc import Collection

import serial
from pydantic import Field, field_validator

from hil.config.models import SerialParams
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.drivers.sim import serial_bus
from hil.errors import DeviceError
from hil.resources import SerialLink, port_settings

if "hil.drivers.sim" not in serial.protocol_handler_packages:
    serial.protocol_handler_packages.append("hil.drivers.sim")


class SimSerialConfig(DriverConfig):
    # bus name -> ports of the bus; what one port writes, all other ports receive
    buses: dict[str, list[str]] = Field(min_length=1)

    @field_validator("buses")
    @classmethod
    def _check_buses(cls, buses: dict[str, list[str]]) -> dict[str, list[str]]:
        seen: set[str] = set()
        for name, ports in buses.items():
            if len(ports) < 2:
                raise ValueError(f"bus {name!r} needs at least two ports")
            for port in ports:
                if not port or "/" in port or "." in port:
                    raise ValueError(f"invalid port name {port!r}")
                if port in seen:
                    raise ValueError(f"port {port!r} is on more than one bus")
                seen.add(port)
        return buses


@register_driver("sim_serial")
class SimSerial(Device):
    """Serial buses in memory; tests play the DUT through ``endpoint``."""

    Config = SimSerialConfig
    config: SimSerialConfig

    def __init__(self, name: str, config: SimSerialConfig) -> None:
        super().__init__(name, config)
        self._channels = frozenset(p for ports in config.buses.values() for p in ports)
        # unique per instance, so two stations with a device of the same name do not clash
        self._key = f"{name}-{id(self):x}"
        self.is_open = False

    def channel_names(self) -> Collection[str]:
        return self._channels

    def resource(self, channel: str) -> SerialLink:
        if channel not in self._channels:
            self._no_channel(channel)
        return SerialLink(self, channel)

    def open(self) -> None:
        try:
            serial_bus.register(self._key, self.config.buses)
        except ValueError as exc:
            raise DeviceError(f"device {self.name!r}: {exc}") from exc
        self.is_open = True

    def close(self) -> None:
        if self.is_open:
            serial_bus.unregister(self._key)
            self.is_open = False

    def open_port(
        self, channel: str, params: SerialParams, timeout: float | None
    ) -> serial.SerialBase:
        if channel not in self._channels:
            self._no_channel(channel)
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")
        url = f"hilsim://{self._key}/{channel}"
        try:
            return serial.serial_for_url(url, timeout=timeout, **port_settings(params))
        except serial.SerialException as exc:
            raise DeviceError(f"device {self.name!r}: {exc}") from exc

    def endpoint(
        self, channel: str, params: SerialParams | None = None, timeout: float | None = 0.01
    ) -> serial.SerialBase:
        """Open a port of a simulated bus from a test, e.g. to play the DUT."""
        return self.open_port(channel, params or SerialParams(), timeout)
```

- [ ] **Step 7: Zaregistrovat ovladač v `src/hil/drivers/sim/__init__.py`**

```python
"""Simulated drivers for running the platform without hardware."""

from hil.drivers.sim import di, relay, serial_port

__all__ = ["di", "relay", "serial_port"]
```

- [ ] **Step 8: Spustit testy**

Run: `python -m pytest tests/drivers/test_sim_serial.py -v`
Expected: všechny PASS.

- [ ] **Step 9: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/resources.py src/hil/drivers/sim tests/drivers/test_sim_serial.py
git commit -m "feat: simulované sériové sběrnice sim_serial"
```

---

### Úkol 5: Ovladač skutečných sériových portů `serial_ports`

**Files:**
- Create: `src/hil/drivers/serial_ports.py`
- Modify: `src/hil/drivers/__init__.py`
- Test: `tests/drivers/test_serial_ports.py`

**Interfaces:**
- Consumes: `SerialLink`, `port_settings`, `SerialParams`, `Device`, `DriverConfig`, `register_driver`, `DeviceError`, `DeviceNotFound`.
- Produces:
  - ovladač `serial_ports` (`SerialPorts`), volby `ports: dict[str, str | FtdiPort]` (cesta, pyserial URL nebo `{serial, interface}`), `low_latency: bool = True`; `resource(channel) -> SerialLink`; `open()` přeloží všechny porty na cesty (chybějící → `DeviceNotFound`); `open_port(...)`.
  - `FtdiPort(serial: str, interface: int 0..3)`.
  - `find_ftdi_port(serial_number, interface, ports, platform=sys.platform) -> str`.
  - `ensure_low_latency(device, sysfs_root=Path("/sys/bus/usb-serial/devices"), platform=sys.platform) -> None`.

- [ ] **Step 1: Napsat padající test `tests/drivers/test_serial_ports.py`**

```python
import logging
import os
import stat
from types import SimpleNamespace

import pytest

from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.drivers.serial_ports import ensure_low_latency, find_ftdi_port
from hil.errors import ConfigError, DeviceError, DeviceNotFound
from hil.resources import SerialLink


def make(**ports):
    return create_device("ft", DeviceConfig(driver="serial_ports", ports=ports))


def test_loop_url_port():
    device = make(A="loop://")
    device.open()
    link = device.resource("A")
    assert isinstance(link, SerialLink)
    with link.open(SerialParams(baud=921600), timeout=0.01) as port:
        port.write(b"abc")
        assert port.read(3) == b"abc"
        assert port.baudrate == 921600
    device.close()


def test_unknown_channel():
    with pytest.raises(ConfigError, match="no channel 'B'"):
        make(A="loop://").resource("B")


def test_open_port_requires_open_device():
    device = make(A="loop://")
    with pytest.raises(DeviceError, match="not open"):
        device.resource("A").open(SerialParams())


def test_missing_port_is_device_error():
    device = make(A="/nonexistent/ttyUSB9")
    device.open()
    with pytest.raises(DeviceError, match="cannot open port 'A'"):
        device.resource("A").open(SerialParams(), timeout=0.01)


def test_ftdi_port_config():
    device = create_device(
        "ft",
        DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 2}}),
    )
    assert device.channel_names() == {"C"}
    with pytest.raises(ConfigError, match="interface"):
        create_device(
            "ft",
            DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 4}}),
        )


PORTS = [
    SimpleNamespace(device="/dev/ttyUSB0", serial_number="FT4ABC", location="1-1:1.0"),
    SimpleNamespace(device="/dev/ttyUSB2", serial_number="FT4ABC", location="1-1:1.2"),
    SimpleNamespace(device="COM7", serial_number="FT4ABCC", location=None),
    SimpleNamespace(device="COM5", serial_number="FT4ABCA", location=None),
]


def test_find_ftdi_port_linux():
    assert find_ftdi_port("FT4ABC", 2, PORTS, platform="linux") == "/dev/ttyUSB2"


def test_find_ftdi_port_windows():
    assert find_ftdi_port("FT4ABC", 2, PORTS, platform="win32") == "COM7"
    assert find_ftdi_port("FT4ABC", 0, PORTS, platform="win32") == "COM5"


def test_find_ftdi_port_missing():
    with pytest.raises(DeviceNotFound, match="FT4ABC.*interface 3"):
        find_ftdi_port("FT4ABC", 3, PORTS, platform="linux")


def fake_tty(tmp_path, value):
    tty = tmp_path / "dev" / "ttyUSB0"
    tty.parent.mkdir()
    tty.write_text("")
    sysfs = tmp_path / "sys"
    (sysfs / "ttyUSB0").mkdir(parents=True)
    latency = sysfs / "ttyUSB0" / "latency_timer"
    latency.write_text(f"{value}\n")
    return tty, sysfs, latency


def test_low_latency_is_set(tmp_path):
    tty, sysfs, latency = fake_tty(tmp_path, 16)
    ensure_low_latency(str(tty), sysfs, platform="linux")
    assert latency.read_text().strip() == "1"


def test_low_latency_untouched_when_set(tmp_path):
    tty, sysfs, latency = fake_tty(tmp_path, 1)
    os.chmod(latency, stat.S_IREAD)
    ensure_low_latency(str(tty), sysfs, platform="linux")
    assert latency.read_text().strip() == "1"


def test_low_latency_warns_without_permission(tmp_path, caplog):
    tty, sysfs, latency = fake_tty(tmp_path, 16)
    os.chmod(latency, stat.S_IREAD)
    with caplog.at_level(logging.WARNING, logger="hil.drivers.serial_ports"):
        ensure_low_latency(str(tty), sysfs, platform="linux")
    assert "latency timer" in caplog.text


def test_low_latency_ignores_other_platforms_and_urls(tmp_path):
    tty, sysfs, latency = fake_tty(tmp_path, 16)
    ensure_low_latency(str(tty), sysfs, platform="win32")
    ensure_low_latency("loop://", sysfs, platform="linux")
    assert latency.read_text().strip() == "16"
```

- [ ] **Step 2: Ověřit, že test padá**

Run: `python -m pytest tests/drivers/test_serial_ports.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hil.drivers.serial_ports'`.

- [ ] **Step 3: Vytvořit `src/hil/drivers/serial_ports.py`**

```python
"""Serial ports of the station, e.g. FT4232H channels (driver ``serial_ports``)."""

import logging
import os
import sys
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import Any

import serial
from pydantic import Field
from serial.tools import list_ports

from hil.config.models import SerialParams
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import SerialLink, port_settings

log = logging.getLogger("hil.drivers.serial_ports")

SYSFS_USB_SERIAL = Path("/sys/bus/usb-serial/devices")


class FtdiPort(DriverConfig):
    """A channel of an FTDI chip found by the chip's serial number."""

    serial: str
    interface: int = Field(default=0, ge=0, le=3)


class SerialPortsConfig(DriverConfig):
    # channel name -> device path, pyserial URL or FTDI serial number and interface
    ports: dict[str, str | FtdiPort] = Field(min_length=1)
    # set the FTDI latency timer to 1 ms (Linux) for passive bus capture
    low_latency: bool = True


def find_ftdi_port(
    serial_number: str, interface: int, ports: Iterable[Any], platform: str = sys.platform
) -> str:
    """Device of channel ``interface`` (0 = A) of the FTDI chip ``serial_number``."""
    letter = "ABCD"[interface]
    for port in ports:
        number = port.serial_number or ""
        if platform == "win32":
            # the FTDI VCP driver reports each channel of a multi-port chip with a suffix
            if number == serial_number + letter:
                return str(port.device)
        elif number == serial_number and (port.location or "").endswith(f":1.{interface}"):
            return str(port.device)
    raise DeviceNotFound(
        f"no FTDI port with serial number {serial_number!r} and interface {interface}"
    )


def ensure_low_latency(
    device: str, sysfs_root: Path = SYSFS_USB_SERIAL, platform: str = sys.platform
) -> None:
    """Set the latency timer of an FTDI port to 1 ms (Linux); warn if it cannot be set."""
    if platform != "linux" or "://" in device:
        return
    tty = Path(os.path.realpath(device)).name
    path = sysfs_root / tty / "latency_timer"
    if not path.exists():
        return
    try:
        if int(path.read_text().strip()) <= 1:
            return
        path.write_text("1")
    except (OSError, ValueError) as exc:
        log.warning(
            "cannot set the latency timer of %s to 1 ms (%s); passive RS-485 capture may "
            "merge frames, set it with an udev rule",
            device,
            exc,
        )


@register_driver("serial_ports")
class SerialPorts(Device):
    Config = SerialPortsConfig
    config: SerialPortsConfig

    def __init__(self, name: str, config: SerialPortsConfig) -> None:
        super().__init__(name, config)
        self._devices: dict[str, str] | None = None

    def channel_names(self) -> Collection[str]:
        return set(self.config.ports)

    def resource(self, channel: str) -> SerialLink:
        if channel not in self.config.ports:
            self._no_channel(channel)
        return SerialLink(self, channel)

    def open(self) -> None:
        available: list[Any] | None = None
        devices: dict[str, str] = {}
        for channel, spec in self.config.ports.items():
            if isinstance(spec, str):
                devices[channel] = spec
                continue
            if available is None:
                available = list(list_ports.comports())
            devices[channel] = find_ftdi_port(spec.serial, spec.interface, available)
        if self.config.low_latency and sys.platform == "win32":
            log.info(
                "%s: the FTDI latency timer cannot be checked on Windows; set it to 1 ms "
                "in Device Manager",
                self.name,
            )
        self._devices = devices

    def close(self) -> None:
        self._devices = None

    def open_port(
        self, channel: str, params: SerialParams, timeout: float | None
    ) -> serial.SerialBase:
        if channel not in self.config.ports:
            self._no_channel(channel)
        if self._devices is None:
            raise DeviceError(f"device {self.name!r} is not open")
        device = self._devices[channel]
        try:
            port = serial.serial_for_url(device, timeout=timeout, **port_settings(params))
        except (serial.SerialException, ValueError, OSError) as exc:
            raise DeviceError(
                f"device {self.name!r}: cannot open port {channel!r} ({device}): {exc}"
            ) from exc
        if self.config.low_latency:
            ensure_low_latency(device)
        return port
```

- [ ] **Step 4: Zaregistrovat ovladač v `src/hil/drivers/__init__.py`**

```python
"""Device drivers. Importing this package registers all built-in drivers."""

from hil.drivers import serial_ports, sim
from hil.drivers.registry import create_device, driver_names, open_order, register_driver

__all__ = [
    "create_device",
    "driver_names",
    "open_order",
    "register_driver",
    "serial_ports",
    "sim",
]
```

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest tests/drivers/test_serial_ports.py -v`
Expected: všechny PASS. `test_low_latency_warns_without_permission` předpokládá, že testy neběží jako root (na Linuxu by root zápis provedl). Pokud tomu tak je, označit ho `pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file permissions")` a uvést v reportu.

- [ ] **Step 6: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/drivers/serial_ports.py src/hil/drivers/__init__.py tests/drivers/test_serial_ports.py
git commit -m "feat: ovladač sériových portů serial_ports"
```

---

### Úkol 6: Textové záznamy, základ `PortSignal` a signál `serial`

**Files:**
- Create: `src/hil/signals/port.py`, `src/hil/signals/uart.py`
- Modify: `src/hil/recording.py`, `src/hil/signals/base.py`, `src/hil/signals/__init__.py`
- Test: `tests/test_recording.py`, `tests/signals/test_uart.py`

**Interfaces:**
- Consumes: `SerialLink`, `port_settings`, `SerialParams`, `SimSerial.endpoint` (úkol 4), `Recorder`, `WaitTimeout`, `DeviceError`.
- Produces:
  - `Recorder.write_line(filename: str, text: str) -> None` (řádek `"<t:12.6f> <text>"`, první řádek souboru `# start_utc <ISO>`).
  - `Signal.close() -> None` (výchozí nic).
  - `PortSignal(name, recorder, link)`: `link`, `params: SerialParams`, `alias: str`, `read_timeout_s = 0.01`, `configure(alias, params)` (nastaví a otevře port), `open()`, `is_open`, `port -> serial.SerialBase` (otevře při prvním použití), `close()`, háčky `_on_open(port)`, `_on_close()`.
  - `SerialSignal(PortSignal)`, `kind = "serial"`: `write(data: bytes | str)`, `expect(pattern: str | bytes, timeout: float) -> re.Match[bytes]`, `read_until(terminator=b"\n", timeout=1.0) -> bytes`, `safe_state()` zahodí dosud přijatý výstup; přijaté řádky zapisuje do `serial-<alias>.log`; selhání portu → `DeviceError` při dalším volání.

- [ ] **Step 1: Napsat padající testy**

Do `tests/test_recording.py` přidat:
```python
def test_text_lines(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path)
    rec.write_line("serial-CON.log", "READY")
    rec.stop_test()
    lines = (tmp_path / "serial-CON.log").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# start_utc ")
    t, text = lines[1].split(maxsplit=1)
    assert float(t) >= 0
    assert text == "READY"
```

`tests/signals/test_uart.py`:
```python
import time

import pytest

from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.errors import DeviceError, WaitTimeout
from hil.recording import Recorder
from hil.signals import SerialSignal


@pytest.fixture
def ser():
    device = create_device("ser", DeviceConfig(driver="sim_serial", buses={"con": ["con", "dut_con"]}))
    device.open()
    yield device
    device.close()


@pytest.fixture
def recorder(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path)
    yield rec
    rec.stop_test()


@pytest.fixture
def console(ser, recorder):
    signal = SerialSignal("CON", recorder, ser.resource("con"))
    signal.configure("CON", SerialParams())
    yield signal
    signal.close()


@pytest.fixture
def dut_side(ser):
    with ser.endpoint("dut_con") as port:
        yield port


def test_expect(console, dut_side):
    dut_side.write(b"boot\r\nREADY 1.2\r\n")
    match = console.expect(r"READY (\S+)", timeout=1)
    assert match.group(1) == b"1.2"


def test_expect_consumes_output(console, dut_side):
    dut_side.write(b"tick\ntick\n")
    console.expect("tick", timeout=1)
    console.expect("tick", timeout=1)
    with pytest.raises(WaitTimeout):
        console.expect("tick", timeout=0.05)


def test_expect_timeout_shows_tail(console, dut_side):
    dut_side.write(b"booting...\n")
    start = time.perf_counter()
    with pytest.raises(WaitTimeout, match="READY") as info:
        console.expect("READY", timeout=0.1)
    assert 0.1 <= time.perf_counter() - start < 1.0
    assert "booting..." in str(info.value)


def test_write_reaches_dut(console, dut_side):
    console.write("help\n")
    assert dut_side.read(5) == b"help\n"


def test_read_until(console, dut_side):
    dut_side.write(b"a=1;b=2;")
    assert console.read_until(b";", timeout=1) == b"a=1;"
    assert console.read_until(b";", timeout=1) == b"b=2;"


def test_log_file(console, dut_side, tmp_path):
    dut_side.write(b"first\r\nsecond\r\n")
    console.expect("second", timeout=1)
    lines = (tmp_path / "serial-CON.log").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# start_utc")
    assert [line.split(maxsplit=1)[1] for line in lines[1:]] == ["first", "second"]


def test_configure_alias_and_settings(console, dut_side, tmp_path):
    console.configure("console", SerialParams(baud=9600))
    assert console.alias == "console"
    assert console.port.baudrate == 9600
    dut_side.write(b"x\n")
    console.expect("x", timeout=1)
    assert console.port.line_errors == 1
    assert (tmp_path / "serial-console.log").exists()


def test_safe_state_forgets_output(console, dut_side):
    dut_side.write(b"READY\n")
    time.sleep(0.05)
    console.safe_state()
    with pytest.raises(WaitTimeout):
        console.expect("READY", timeout=0.1)


def test_port_failure_is_reported(console, ser):
    ser.close()
    time.sleep(0.05)
    with pytest.raises(DeviceError, match="serial port failed"):
        console.expect("anything", timeout=0.5)


def test_close(console):
    assert console.is_open
    console.close()
    assert not console.is_open
```

- [ ] **Step 2: Ověřit, že testy padají**

Run: `python -m pytest tests/test_recording.py tests/signals/test_uart.py -v`
Expected: FAIL, `AttributeError: 'Recorder' object has no attribute 'write_line'` a `ImportError: cannot import name 'SerialSignal'`.

- [ ] **Step 3: Upravit `src/hil/recording.py`**

Metodu `write` nahradit těmito třemi metodami (zbytek třídy beze změny):
```python
    def write(self, filename: str, record: dict[str, Any]) -> None:
        """Append one JSON record to ``filename`` in the test directory."""
        self._append(filename, json.dumps(record, default=str), jsonl=True)

    def write_line(self, filename: str, text: str) -> None:
        """Append ``text`` with the time since the start of the test to a text file."""
        t = self.relative(clock.now())
        self._append(filename, f"{t:12.6f} {text}", jsonl=False)

    def _append(self, filename: str, line: str, jsonl: bool) -> None:
        """Append ``line``; the first line of a new file names the start of the test.

        The lock is taken with a timeout: a termination signal handler may call this
        while the interrupted main thread holds the lock, and waiting forever would
        hang the emergency switch-off. A record is dropped instead of deadlocking.
        """
        if not self._lock.acquire(timeout=_LOCK_TIMEOUT_S):
            log.warning("recorder busy, dropping %s record %s", filename, line)
            return
        try:
            if self._dir is None:
                log.debug("no test running, dropping %s record %s", filename, line)
                return
            file = self._files.get(filename)
            if file is None:
                file = (self._dir / filename).open("w", encoding="utf-8")
                if jsonl:
                    header = json.dumps({"start_utc": self._start_utc})
                else:
                    header = f"# start_utc {self._start_utc}"
                file.write(header + "\n")
                self._files[filename] = file
            file.write(line + "\n")
            file.flush()
        finally:
            self._lock.release()
```

- [ ] **Step 4: Doplnit `close()` do `src/hil/signals/base.py`**

Za metodu `safe_state` přidat:
```python
    def close(self) -> None:
        """Release what the signal holds (ports, threads); called when the station closes."""
```

- [ ] **Step 5: Vytvořit `src/hil/signals/port.py`**

```python
"""Base of signals that talk through a serial port."""

import threading
from typing import ClassVar

from serial import SerialBase

from hil.config.models import SerialParams
from hil.recording import Recorder
from hil.resources import SerialLink, port_settings
from hil.signals.base import Signal


class PortSignal(Signal):
    """A terminal with a serial port, opened with the line parameters of the DUT."""

    read_timeout_s: ClassVar[float] = 0.01

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder)
        self.link = link
        self.params = SerialParams()
        self.alias = name
        self._port: SerialBase | None = None
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
    def port(self) -> SerialBase:
        with self._port_lock:
            if self._port is None:
                port = self.link.open(self.params, timeout=self.read_timeout_s)
                self._port = port
                self._on_open(port)
            return self._port

    def _on_open(self, port: SerialBase) -> None:
        """Start background work on a freshly opened port."""

    def _on_close(self) -> None:
        """Stop background work before the port is closed."""

    def close(self) -> None:
        with self._port_lock:
            port, self._port = self._port, None
        if port is not None:
            self._on_close()
            port.close()
```

- [ ] **Step 6: Vytvořit `src/hil/signals/uart.py`**

```python
"""Serial console or log of the DUT (terminal kind ``serial``)."""

import logging
import re
import threading

from serial import SerialBase

from hil import clock
from hil.errors import DeviceError, WaitTimeout
from hil.recording import Recorder
from hil.resources import SerialLink
from hil.signals.port import PortSignal

log = logging.getLogger("hil.signals.uart")

_TAIL = 200


class SerialSignal(PortSignal):
    """Received bytes are logged line by line and kept for ``expect`` and ``read_until``."""

    kind = "serial"

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder, link)
        self._cond = threading.Condition()
        self._buffer = bytearray()
        self._pos = 0
        self._line = bytearray()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    def _on_open(self, port: SerialBase) -> None:
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._read_loop, args=(port,), name=f"hil-serial-{self.name}", daemon=True
        )
        self._thread.start()

    def _on_close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _read_loop(self, port: SerialBase) -> None:
        try:
            while not self._stop.is_set():
                data = port.read(max(1, port.in_waiting))
                if data:
                    self._received(data)
        except Exception as exc:
            if not self._stop.is_set():
                log.error("serial port %s failed: %s", self.alias, exc)
                self._error = exc
                self._event("port_failed", error=str(exc))
        finally:
            with self._cond:
                self._cond.notify_all()

    def _received(self, data: bytes) -> None:
        # log complete lines first, so a caller woken by ``expect`` finds them in the file
        self._line.extend(data)
        while (end := self._line.find(b"\n")) >= 0:
            line = bytes(self._line[:end]).rstrip(b"\r")
            del self._line[: end + 1]
            text = line.decode("utf-8", errors="replace")
            self.recorder.write_line(f"serial-{self.alias}.log", text)
        with self._cond:
            self._buffer.extend(data)
            self._cond.notify_all()

    def _check_reader(self) -> None:
        if self._error is not None:
            raise DeviceError(f"{self.alias}: serial port failed: {self._error}") from self._error

    def _tail(self) -> bytes:
        return bytes(self._buffer[self._pos :][-_TAIL:])

    def write(self, data: bytes | str) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        port = self.port
        self._check_reader()
        port.write(payload)
        self._event("write", data=payload.decode("utf-8", errors="replace"))

    def expect(self, pattern: str | bytes, timeout: float) -> re.Match[bytes]:
        """Wait for ``pattern`` (a regular expression) in output not consumed yet."""
        regex = re.compile(pattern.encode("utf-8") if isinstance(pattern, str) else pattern)
        _ = self.port
        deadline = clock.now() + timeout
        with self._cond:
            while True:
                match = regex.search(bytes(self._buffer), self._pos)
                if match is not None:
                    self._pos = match.end()
                    break
                self._check_reader()
                remaining = deadline - clock.now()
                if remaining <= 0:
                    raise WaitTimeout(
                        f"{self.alias}: {pattern!r} not received within {timeout} s; "
                        f"last output: {self._tail()!r}"
                    )
                self._cond.wait(remaining)
        self._event("expect", pattern=regex.pattern.decode("utf-8", errors="replace"))
        return match

    def read_until(self, terminator: bytes = b"\n", timeout: float = 1.0) -> bytes:
        """Consume output up to and including ``terminator``."""
        _ = self.port
        deadline = clock.now() + timeout
        with self._cond:
            while True:
                end = self._buffer.find(terminator, self._pos)
                if end >= 0:
                    stop = end + len(terminator)
                    data = bytes(self._buffer[self._pos : stop])
                    self._pos = stop
                    return data
                self._check_reader()
                remaining = deadline - clock.now()
                if remaining <= 0:
                    raise WaitTimeout(
                        f"{self.alias}: {terminator!r} not received within {timeout} s; "
                        f"last output: {self._tail()!r}"
                    )
                self._cond.wait(remaining)

    def safe_state(self) -> None:
        """Forget the output received so far, so the next test does not match it."""
        with self._cond:
            self._buffer.clear()
            self._pos = 0
```

- [ ] **Step 7: Upravit `src/hil/signals/__init__.py`**

```python
"""Signal objects: one per wired terminal, typed by the terminal kind."""

from hil.signals.base import Signal
from hil.signals.digital import SenseRecording, SenseSignal, SwitchSignal
from hil.signals.fault import FaultPath
from hil.signals.port import PortSignal
from hil.signals.power import PowerSignal
from hil.signals.uart import SerialSignal

__all__ = [
    "FaultPath",
    "PortSignal",
    "PowerSignal",
    "SenseRecording",
    "SenseSignal",
    "SerialSignal",
    "Signal",
    "SwitchSignal",
]
```

- [ ] **Step 8: Spustit testy**

Run: `python -m pytest tests/test_recording.py tests/signals/test_uart.py -v`
Expected: všechny PASS.

- [ ] **Step 9: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/recording.py src/hil/signals tests/test_recording.py tests/signals/test_uart.py
git commit -m "feat: signál sériové konzole s logem a expect"
```

---

### Úkol 7: Modbus RTU master a simulovaný slave

**Files:**
- Create: `src/hil/comm/master.py`, `src/hil/comm/slave.py`
- Test: `tests/comm/test_master_slave.py`

**Interfaces:**
- Consumes: `hil.comm.modbus` (úkol 2), `SimSerial.endpoint` (úkol 4), `DeviceError`, `DeviceTimeout`, `HilError`, `hil.clock.now`.
- Produces:
  - `ModbusExceptionResponse(HilError)` s atributy `address`, `function`, `code`; `EXCEPTION_NAMES`.
  - `response_length(function, received) -> int | None`.
  - `ModbusMaster(port, timeout_s=1.0, echo=False, on_exchange=None)` s `transact(frame) -> bytes | None` (None pro broadcast), `read_holding_registers(address, start, count) -> list[int]`, `read_input_registers(...) -> list[int]`, `read_coils(...) -> list[bool]`, `read_discrete_inputs(...) -> list[bool]`, `write_register(address, register, value)`, `write_registers(address, start, values)`, `write_coil(address, coil, on)`, `write_coils(address, start, values)`. `on_exchange(request: bytes, response: bytes | None)` se volá po každé výměně. Port musí mít krátký timeout čtení.
  - `@dataclass ModbusDataStore(coils, discrete_inputs, holding_registers, input_registers)` (slovníky adresa → hodnota; chybějící adresa = výjimka 2).
  - `request_length(received) -> int | None`.
  - `ModbusSlave(port, address, store=None)` s `start()`, `stop()`, context manager, `silent: bool`, `requests: list[bytes]`, `respond(frame) -> bytes`.

- [ ] **Step 1: Napsat padající test `tests/comm/test_master_slave.py`**

```python
import time

import pytest

from hil.comm import modbus
from hil.comm.master import ModbusExceptionResponse, ModbusMaster, response_length
from hil.comm.slave import ModbusDataStore, ModbusSlave, request_length
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceTimeout


@pytest.fixture
def bus():
    device = create_device("ser", DeviceConfig(driver="sim_serial", buses={"rs485": ["master", "dut"]}))
    device.open()
    yield device
    device.close()


@pytest.fixture
def store():
    return ModbusDataStore(
        coils={0: False, 1: True, 2: False},
        discrete_inputs={0: True},
        holding_registers={0: 42, 1: 7},
        input_registers={5: 1234},
    )


@pytest.fixture
def slave(bus, store):
    with bus.endpoint("dut") as port, ModbusSlave(port, address=1, store=store) as slave:
        yield slave


@pytest.fixture
def master(bus):
    with bus.endpoint("master") as port:
        yield ModbusMaster(port, timeout_s=0.3)


def test_reads(master, slave):
    assert master.read_holding_registers(1, 0, 2) == [42, 7]
    assert master.read_input_registers(1, 5, 1) == [1234]
    assert master.read_coils(1, 0, 3) == [False, True, False]
    assert master.read_discrete_inputs(1, 0, 1) == [True]
    assert slave.requests[0] == modbus.read_request(1, 3, 0, 2)


def test_writes(master, slave, store):
    master.write_register(1, 1, 99)
    master.write_registers(1, 0, [5, 6])
    master.write_coil(1, 2, True)
    master.write_coils(1, 0, [True, True])
    assert store.holding_registers == {0: 5, 1: 6}
    assert store.coils == {0: True, 1: True, 2: True}


def test_exception_response(master, slave):
    with pytest.raises(ModbusExceptionResponse, match="illegal data address") as info:
        master.read_holding_registers(1, 10, 1)
    assert info.value.code == 2


def test_unknown_function_is_illegal(master, slave):
    with pytest.raises(ModbusExceptionResponse) as info:
        master.transact(modbus.request(1, 0x2B, b"\x0e\x01"))
    assert info.value.code == 1


def test_silent_slave_times_out(master, slave):
    slave.silent = True
    start = time.perf_counter()
    with pytest.raises(DeviceTimeout, match="no complete response"):
        master.read_holding_registers(1, 0, 1)
    assert 0.3 <= time.perf_counter() - start < 0.8


def test_other_address_times_out(master, slave):
    with pytest.raises(DeviceTimeout):
        master.read_holding_registers(2, 0, 1)


def test_broadcast_write(master, slave, store):
    assert master.transact(modbus.write_register_request(0, 0, 5)) is None
    time.sleep(0.1)
    assert store.holding_registers[0] == 5


def test_on_exchange(bus, slave):
    exchanges = []
    with bus.endpoint("master") as port:
        master = ModbusMaster(port, timeout_s=0.3, on_exchange=lambda q, r: exchanges.append((q, r)))
        master.read_holding_registers(1, 0, 1)
    request, response = exchanges[0]
    assert request == modbus.read_request(1, 3, 0, 1)
    assert modbus.decode(response).fields == {"values": [42]}


class FakePort:
    """Port that answers with prepared bytes."""

    def __init__(self, reply):
        self.reply = bytearray(reply)
        self.written = bytearray()

    @property
    def in_waiting(self):
        return len(self.reply)

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written += data
        return len(data)

    def flush(self):
        pass

    def read(self, size=1):
        data = bytes(self.reply[:size])
        del self.reply[:size]
        return data


def test_echo_is_skipped():
    request = modbus.read_request(1, 3, 0, 1)
    response = modbus.with_crc(bytes([1, 3, 2, 0, 9]))
    master = ModbusMaster(FakePort(request + response), timeout_s=0.1, echo=True)
    assert master.read_holding_registers(1, 0, 1) == [9]


def test_bad_crc_response():
    response = bytearray(modbus.with_crc(bytes([1, 3, 2, 0, 9])))
    response[-1] ^= 0xFF
    with pytest.raises(DeviceError, match="bad CRC"):
        ModbusMaster(FakePort(response), timeout_s=0.1).read_holding_registers(1, 0, 1)


def test_response_from_other_device():
    response = modbus.with_crc(bytes([2, 3, 2, 0, 9]))
    with pytest.raises(DeviceError, match="from device 2"):
        ModbusMaster(FakePort(response), timeout_s=0.1).read_holding_registers(1, 0, 1)


def test_lengths():
    assert response_length(3, b"\x01") is None
    assert response_length(3, b"\x01\x03") is None
    assert response_length(3, b"\x01\x03\x04") == 9
    assert response_length(3, b"\x01\x83") == 5
    assert response_length(6, b"\x01\x06") == 8
    assert request_length(b"\x01\x03") == 8
    assert request_length(b"\x01\x10\x00\x00\x00\x02") is None
    assert request_length(b"\x01\x10\x00\x00\x00\x02\x04") == 13
    assert request_length(b"\x01\x2b") is None


def test_slave_rejects_bad_byte_count(store):
    slave = ModbusSlave(FakePort(b""), address=1, store=store)
    frame = modbus.request(1, 15, bytes.fromhex("00 00 00 03 02 05 00"))
    response = slave.respond(frame)
    assert response[1] == 0x8F
    assert response[2] == 3
```

- [ ] **Step 2: Ověřit, že test padá**

Run: `python -m pytest tests/comm/test_master_slave.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hil.comm.master'`.

- [ ] **Step 3: Vytvořit `src/hil/comm/master.py`**

```python
"""Modbus RTU master over a serial port."""

import struct
from collections.abc import Callable, Sequence

from serial import SerialBase

from hil import clock
from hil.comm import modbus
from hil.errors import DeviceError, DeviceTimeout, HilError

EXCEPTION_NAMES = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "server device failure",
    5: "acknowledge",
    6: "server device busy",
}

Exchange = Callable[[bytes, bytes | None], None]


class ModbusExceptionResponse(HilError):
    """The device answered with a Modbus exception."""

    def __init__(self, address: int, function: int, code: int) -> None:
        name = EXCEPTION_NAMES.get(code, "unknown exception")
        super().__init__(f"device {address}: function {function} failed with exception {code} ({name})")
        self.address = address
        self.function = function
        self.code = code


def response_length(function: int, received: bytes) -> int | None:
    """Length of the response to ``function`` known from its first bytes; None = need more."""
    if len(received) < 2:
        return None
    if received[1] & 0x80:
        return 5
    if function in modbus.BIT_READS | modbus.REGISTER_READS:
        return None if len(received) < 3 else 5 + received[2]
    return 8


class ModbusMaster:
    """Blocking Modbus RTU master.

    The port must have a short read timeout (tens of milliseconds); ``timeout_s`` bounds
    the wait for a whole response.
    """

    def __init__(
        self,
        port: SerialBase,
        timeout_s: float = 1.0,
        echo: bool = False,
        on_exchange: Exchange | None = None,
    ) -> None:
        self.port = port
        self.timeout_s = timeout_s
        self.echo = echo
        self.on_exchange = on_exchange

    def transact(self, frame: bytes) -> bytes | None:
        """Send ``frame`` and return the validated response (None for a broadcast)."""
        response: bytes | None = None
        try:
            self.port.reset_input_buffer()
            self.port.write(frame)
            self.port.flush()
            deadline = clock.now() + self.timeout_s
            if self.echo:
                echoed = self._read_exact(len(frame), deadline)
                if echoed != frame:
                    raise DeviceError(f"echo differs from the request: {echoed.hex(' ')}")
            if frame[0] == 0:
                return None
            response = self._read_response(frame, deadline)
            return response
        finally:
            if self.on_exchange is not None:
                self.on_exchange(frame, response)

    def _read_exact(self, count: int, deadline: float) -> bytes:
        received = bytearray()
        while len(received) < count:
            if clock.now() >= deadline:
                raise DeviceTimeout(f"echo of the request not received within {self.timeout_s} s")
            received += self.port.read(count - len(received))
        return bytes(received)

    def _read_response(self, frame: bytes, deadline: float) -> bytes:
        received = bytearray()
        while True:
            need = response_length(frame[1], bytes(received))
            if need is not None and len(received) >= need:
                break
            if clock.now() >= deadline:
                got = bytes(received).hex(" ") or "nothing"
                raise DeviceTimeout(
                    f"device {frame[0]}: no complete response within {self.timeout_s} s "
                    f"(received {got})"
                )
            missing = 1 if need is None else need - len(received)
            received += self.port.read(missing)
        response = bytes(received[:need])
        if not modbus.crc_ok(response):
            raise DeviceError(f"device {frame[0]}: response with bad CRC: {response.hex(' ')}")
        if response[0] != frame[0]:
            raise DeviceError(f"response from device {response[0]} to a request for device {frame[0]}")
        if response[1] == frame[1] | 0x80:
            raise ModbusExceptionResponse(frame[0], frame[1], response[2])
        if response[1] != frame[1]:
            raise DeviceError(
                f"device {frame[0]}: response to function {response[1]}, expected {frame[1]}"
            )
        return response

    def _read(self, frame: bytes) -> bytes:
        if frame[0] == 0:
            raise ValueError("a read request cannot be broadcast")
        response = self.transact(frame)
        if response is None:
            raise DeviceError(f"device {frame[0]}: no response")
        return response

    def _read_registers(self, address: int, function: int, start: int, count: int) -> list[int]:
        response = self._read(modbus.read_request(address, function, start, count))
        if response[2] != 2 * count:
            raise DeviceError(f"device {address}: expected {2 * count} data bytes, got {response[2]}")
        return list(struct.unpack(f">{count}H", response[3:-2]))

    def _read_bits(self, address: int, function: int, start: int, count: int) -> list[bool]:
        response = self._read(modbus.read_request(address, function, start, count))
        expected = (count + 7) // 8
        if response[2] != expected:
            raise DeviceError(f"device {address}: expected {expected} data bytes, got {response[2]}")
        return modbus.unpack_bits(response[3:-2], count)

    def read_holding_registers(self, address: int, start: int, count: int) -> list[int]:
        return self._read_registers(address, modbus.READ_HOLDING_REGISTERS, start, count)

    def read_input_registers(self, address: int, start: int, count: int) -> list[int]:
        return self._read_registers(address, modbus.READ_INPUT_REGISTERS, start, count)

    def read_coils(self, address: int, start: int, count: int) -> list[bool]:
        return self._read_bits(address, modbus.READ_COILS, start, count)

    def read_discrete_inputs(self, address: int, start: int, count: int) -> list[bool]:
        return self._read_bits(address, modbus.READ_DISCRETE_INPUTS, start, count)

    def write_register(self, address: int, register: int, value: int) -> None:
        self.transact(modbus.write_register_request(address, register, value))

    def write_registers(self, address: int, start: int, values: Sequence[int]) -> None:
        self.transact(modbus.write_registers_request(address, start, values))

    def write_coil(self, address: int, coil: int, on: bool) -> None:
        self.transact(modbus.write_coil_request(address, coil, on))

    def write_coils(self, address: int, start: int, values: Sequence[bool]) -> None:
        self.transact(modbus.write_coils_request(address, start, values))
```

- [ ] **Step 4: Vytvořit `src/hil/comm/slave.py`**

```python
"""Simulated Modbus RTU slave answering in a background thread."""

import logging
import struct
import threading
from dataclasses import dataclass, field
from types import TracebackType

from serial import SerialBase

from hil import clock
from hil.comm import modbus

log = logging.getLogger("hil.comm.slave")

ILLEGAL_FUNCTION = 1
ILLEGAL_DATA_ADDRESS = 2
ILLEGAL_DATA_VALUE = 3

# silence after which an incomplete or unknown request is processed or dropped
_RESYNC_S = 0.05


@dataclass
class ModbusDataStore:
    """Data of a simulated slave; an address missing from a table is an illegal address."""

    coils: dict[int, bool] = field(default_factory=dict)
    discrete_inputs: dict[int, bool] = field(default_factory=dict)
    holding_registers: dict[int, int] = field(default_factory=dict)
    input_registers: dict[int, int] = field(default_factory=dict)


class _ModbusFault(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def request_length(received: bytes) -> int | None:
    """Length of the request at the start of ``received``; None = need more or unknown."""
    if len(received) < 2:
        return None
    function = received[1]
    if function in (1, 2, 3, 4, 5, 6):
        return 8
    if function in (modbus.WRITE_MULTIPLE_COILS, modbus.WRITE_MULTIPLE_REGISTERS):
        return None if len(received) < 7 else 9 + received[6]
    return None


def _get[V](table: dict[int, V], address: int) -> V:
    if address not in table:
        raise _ModbusFault(ILLEGAL_DATA_ADDRESS)
    return table[address]


def _check_all[V](table: dict[int, V], start: int, count: int) -> None:
    if any(address not in table for address in range(start, start + count)):
        raise _ModbusFault(ILLEGAL_DATA_ADDRESS)


class ModbusSlave:
    """Answers Modbus RTU requests for ``address`` on ``port`` until stopped."""

    def __init__(self, port: SerialBase, address: int, store: ModbusDataStore | None = None) -> None:
        if not 1 <= address <= 247:
            raise ValueError(f"slave address must be in 1..247, got {address}")
        self.port = port
        self.address = address
        self.store = store if store is not None else ModbusDataStore()
        # True: requests are received but never answered (a missing device)
        self.silent = False
        self.requests: list[bytes] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"hil-modbus-slave-{self.address}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> "ModbusSlave":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def _run(self) -> None:
        received = bytearray()
        last = clock.now()
        while not self._stop.is_set():
            try:
                chunk = self.port.read(max(1, self.port.in_waiting))
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("Modbus slave %s: port failed: %s", self.address, exc)
                return
            now = clock.now()
            if chunk:
                received += chunk
                last = now
            elif received and now - last > _RESYNC_S:
                frame = bytes(received)
                received.clear()
                if modbus.crc_ok(frame):
                    self._handle(frame)
                continue
            while (length := request_length(bytes(received))) is not None and len(received) >= length:
                frame = bytes(received[:length])
                del received[:length]
                if not modbus.crc_ok(frame):
                    received.clear()
                    break
                self._handle(frame)

    def _handle(self, frame: bytes) -> None:
        self.requests.append(frame)
        if frame[0] not in (0, self.address) or self.silent:
            return
        response = self.respond(frame)
        if frame[0] != 0:
            self.port.write(response)

    def respond(self, frame: bytes) -> bytes:
        """The response of this slave to the request ``frame`` (CRC already checked)."""
        function = frame[1]
        try:
            body = self._execute(function, frame[2:-2])
        except _ModbusFault as fault:
            return modbus.with_crc(bytes((self.address, function | 0x80, fault.code)))
        return modbus.with_crc(bytes((self.address, function)) + body)

    def _execute(self, function: int, data: bytes) -> bytes:
        store = self.store
        if function in modbus.BIT_READS | modbus.REGISTER_READS:
            if len(data) != 4:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            start, count = struct.unpack(">HH", data)
            if function in modbus.BIT_READS:
                if not 1 <= count <= modbus.MAX_READ_BITS:
                    raise _ModbusFault(ILLEGAL_DATA_VALUE)
                table = store.coils if function == modbus.READ_COILS else store.discrete_inputs
                packed = modbus.pack_bits([_get(table, a) for a in range(start, start + count)])
                return bytes((len(packed),)) + packed
            if not 1 <= count <= modbus.MAX_READ_REGISTERS:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            registers = (
                store.holding_registers
                if function == modbus.READ_HOLDING_REGISTERS
                else store.input_registers
            )
            values = [_get(registers, a) for a in range(start, start + count)]
            return bytes((2 * count,)) + struct.pack(f">{count}H", *values)
        if function in (modbus.WRITE_SINGLE_COIL, modbus.WRITE_SINGLE_REGISTER):
            if len(data) != 4:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            target, value = struct.unpack(">HH", data)
            if function == modbus.WRITE_SINGLE_COIL:
                if value not in (0xFF00, 0):
                    raise _ModbusFault(ILLEGAL_DATA_VALUE)
                _get(store.coils, target)
                store.coils[target] = value == 0xFF00
            else:
                _get(store.holding_registers, target)
                store.holding_registers[target] = value
            return data
        if function == modbus.WRITE_MULTIPLE_COILS:
            if len(data) < 5:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            start, count, size = struct.unpack(">HHB", data[:5])
            if not 1 <= count <= modbus.MAX_WRITE_BITS or size != (count + 7) // 8 or len(data) != 5 + size:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            _check_all(store.coils, start, count)
            for offset, bit in enumerate(modbus.unpack_bits(data[5:], count)):
                store.coils[start + offset] = bit
            return data[:4]
        if function == modbus.WRITE_MULTIPLE_REGISTERS:
            if len(data) < 5:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            start, count, size = struct.unpack(">HHB", data[:5])
            if not 1 <= count <= modbus.MAX_WRITE_REGISTERS or size != 2 * count or len(data) != 5 + size:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            _check_all(store.holding_registers, start, count)
            for offset, value in enumerate(struct.unpack(f">{count}H", data[5:])):
                store.holding_registers[start + offset] = value
            return data[:4]
        raise _ModbusFault(ILLEGAL_FUNCTION)
```

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest tests/comm/test_master_slave.py -v`
Expected: všechny PASS.

- [ ] **Step 6: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/comm/master.py src/hil/comm/slave.py tests/comm/test_master_slave.py
git commit -m "feat: Modbus RTU master a simulovaný slave"
```

---

### Úkol 8: Signály `rs485` a `rs485_monitor`

**Files:**
- Create: `src/hil/signals/rs485.py`
- Modify: `src/hil/signals/__init__.py`
- Test: `tests/signals/test_rs485.py`

**Interfaces:**
- Consumes: `PortSignal` (úkol 6), `ModbusMaster`, `ModbusSlave`, `ModbusDataStore` (úkol 7), `FrameSplitter`, `Frame` (úkol 3), `FaultKind`, `corrupt_crc`, `truncate`, `extend`, `wrong_parity` (úkol 3), `ResourceConflict`, `OperationNotAllowed`, `WaitTimeout`, `DeviceError`.
- Produces:
  - `Rs485Signal(PortSignal)`, `kind = "rs485"`: `modbus -> ModbusMaster` (s `timeout_s` a `echo` z parametrů, výměny jdou do `events.jsonl` jako `modbus`), `slave(address, store=None)` (context manager vracející `ModbusSlave`, mezitím master a vysílání → `ResourceConflict`), `send_raw(data)`, `inject(kind, frame) -> bytes`, `flood(duration_s, chunk=64, seed=None) -> int` (odeslané bajty, rychlostí linky), `safe_state()` zastaví slave.
  - `Rs485Monitor(PortSignal)`, `kind = "rs485_monitor"`: `start()`, `stop() -> list[Frame]`, `running`, `frames: list[Frame]`, `wait_for_frame(predicate, timeout) -> Frame` (hledá od posledního vráceného rámce; před `start()` → `OperationNotAllowed`), rámce zapisuje do `rs485-<alias>.jsonl`, `safe_state()` zastaví a smaže rámce.

- [ ] **Step 1: Napsat padající test `tests/signals/test_rs485.py`**

```python
import json
import time

import pytest

from hil.comm import modbus
from hil.comm.master import ModbusMaster
from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.errors import DeviceTimeout, OperationNotAllowed, ResourceConflict
from hil.recording import Recorder
from hil.signals import Rs485Monitor, Rs485Signal

FRAME = modbus.read_request(1, 3, 0, 1)


def is_response(frame):
    return frame.decoded is not None and frame.decoded.kind == "response"


@pytest.fixture
def ser():
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"rs485": ["com1", "mon1", "dut"]})
    )
    device.open()
    yield device
    device.close()


@pytest.fixture
def recorder(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path)
    yield rec
    rec.stop_test()


@pytest.fixture
def rs485(ser, recorder):
    signal = Rs485Signal("COM1", recorder, ser.resource("com1"))
    signal.configure("modbus", SerialParams(timeout_s=0.3))
    yield signal
    signal.close()


@pytest.fixture
def monitor(ser, recorder):
    signal = Rs485Monitor("MON1", recorder, ser.resource("mon1"))
    signal.configure("bus", SerialParams())
    signal.start()
    yield signal
    signal.close()


@pytest.fixture
def dut(ser):
    with ser.endpoint("dut") as port:
        yield port


def test_master_and_monitor(rs485, monitor, dut):
    with ModbusSlave(dut, address=1, store=ModbusDataStore(holding_registers={0: 42})):
        assert rs485.modbus.read_holding_registers(1, 0, 1) == [42]
    request = monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    response = monitor.wait_for_frame(is_response, timeout=1)
    assert request.decoded.fields == {"start": 0, "count": 1}
    assert response.decoded.fields == {"values": [42]}
    assert response.t >= request.t


def test_platform_as_slave(rs485, dut):
    dut_master = ModbusMaster(dut, timeout_s=0.3)
    with rs485.slave(7, ModbusDataStore(holding_registers={3: 5})) as slave:
        assert dut_master.read_holding_registers(7, 3, 1) == [5]
        with pytest.raises(ResourceConflict):
            _ = rs485.modbus
        slave.silent = True
        with pytest.raises(DeviceTimeout):
            dut_master.read_holding_registers(7, 3, 1)
    with ModbusSlave(dut, address=1, store=ModbusDataStore(holding_registers={0: 1})):
        assert rs485.modbus.read_holding_registers(1, 0, 1) == [1]


def test_inject_bad_crc(rs485, monitor, dut):
    sent = rs485.inject("bad_crc", FRAME)
    assert dut.read(len(sent)) == sent
    frame = monitor.wait_for_frame(lambda f: f.error is not None, timeout=1)
    assert frame.raw == sent


@pytest.mark.parametrize(("kind", "length"), [("truncated", 7), ("extended", 9)])
def test_inject_length_faults(rs485, dut, kind, length):
    sent = rs485.inject(kind, FRAME)
    assert len(sent) == length
    assert dut.read(length) == sent


def test_inject_bad_parity(rs485, dut):
    sent = rs485.inject("bad_parity", FRAME)
    assert sent == FRAME
    assert dut.read(len(FRAME)) == FRAME
    assert dut.line_errors == 1
    assert rs485.port.parity == "N"


def test_monitor_survives_garbage(rs485, monitor):
    rs485.send_raw(b"\x01\x02\x03")
    time.sleep(0.05)
    rs485.send_raw(FRAME)
    error = monitor.wait_for_frame(lambda f: f.error is not None, timeout=1)
    valid = monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    assert error.raw == b"\x01\x02\x03"
    assert valid.raw == FRAME
    assert monitor.running


def test_flood_runs_at_line_rate(rs485, dut):
    sent = rs485.flood(0.05, seed=1)
    limit = 0.05 / SerialParams().char_time_s() + 2 * 64
    assert 0 < sent <= limit
    assert dut.in_waiting == sent


def test_monitor_records_frames(rs485, monitor, tmp_path):
    rs485.send_raw(FRAME)
    monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    lines = (tmp_path / "rs485-bus.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    assert record["raw"] == FRAME.hex(" ")
    assert record["decoded"]["kind"] == "request"


def test_monitor_safe_state(rs485, monitor):
    rs485.send_raw(FRAME)
    monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    monitor.safe_state()
    assert monitor.frames == []
    assert not monitor.running
    with pytest.raises(OperationNotAllowed, match="start"):
        monitor.wait_for_frame(lambda f: True, timeout=0.1)


def test_master_exchange_is_recorded(rs485, dut, tmp_path):
    with ModbusSlave(dut, address=1, store=ModbusDataStore(holding_registers={0: 3})):
        rs485.modbus.read_holding_registers(1, 0, 1)
    events = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()[1:]]
    exchange = next(e for e in events if e["action"] == "modbus")
    assert exchange["request"] == FRAME.hex(" ")
```

- [ ] **Step 2: Ověřit, že test padá**

Run: `python -m pytest tests/signals/test_rs485.py -v`
Expected: FAIL, `ImportError: cannot import name 'Rs485Monitor'`.

- [ ] **Step 3: Vytvořit `src/hil/signals/rs485.py`**

```python
"""RS-485 terminals: active port (``rs485``) and passive monitor (``rs485_monitor``)."""

import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from serial import SerialBase

from hil import clock
from hil.comm.faults import FaultKind, corrupt_crc, extend, truncate, wrong_parity
from hil.comm.framing import Frame, FrameSplitter
from hil.comm.master import ModbusMaster
from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.errors import DeviceError, OperationNotAllowed, ResourceConflict, WaitTimeout
from hil.recording import Recorder
from hil.resources import SerialLink
from hil.signals.port import PortSignal


class Rs485Signal(PortSignal):
    """Active RS-485 port of the platform: Modbus master or slave, raw and faulty frames."""

    kind = "rs485"

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder, link)
        self._slave: ModbusSlave | None = None

    def _check_no_slave(self, what: str) -> None:
        if self._slave is not None:
            raise ResourceConflict(
                f"{self.alias}: {what} is not possible while the platform acts as "
                f"Modbus slave {self._slave.address}"
            )

    @property
    def modbus(self) -> ModbusMaster:
        """Modbus RTU master on this port."""
        self._check_no_slave("the Modbus master")
        return ModbusMaster(
            self.port, self.params.timeout_s, echo=self.params.echo, on_exchange=self._exchange
        )

    def _exchange(self, request: bytes, response: bytes | None) -> None:
        self._event(
            "modbus",
            request=request.hex(" "),
            response=None if response is None else response.hex(" "),
        )

    @contextmanager
    def slave(self, address: int, store: ModbusDataStore | None = None) -> Iterator[ModbusSlave]:
        """Act as Modbus slave ``address`` while the ``with`` block runs."""
        self._check_no_slave("another slave")
        slave = ModbusSlave(self.port, address, store)
        slave.start()
        self._slave = slave
        self._event("slave_start", address=address)
        try:
            yield slave
        finally:
            self._stop_slave()

    def _stop_slave(self) -> None:
        slave, self._slave = self._slave, None
        if slave is not None:
            slave.stop()
            self._event("slave_stop", address=slave.address)

    def _send(self, data: bytes) -> None:
        port = self.port
        port.write(data)
        port.flush()

    def send_raw(self, data: bytes) -> None:
        self._check_no_slave("sending")
        payload = bytes(data)
        self._send(payload)
        self._event("send_raw", data=payload.hex(" "))

    def inject(self, kind: FaultKind, frame: bytes) -> bytes:
        """Send ``frame`` damaged by ``kind``; return the bytes sent."""
        self._check_no_slave("fault injection")
        if kind == "bad_crc":
            payload = corrupt_crc(frame)
        elif kind == "truncated":
            payload = truncate(frame)
        elif kind == "extended":
            payload = extend(frame)
        elif kind == "bad_parity":
            payload = bytes(frame)
        else:
            raise ValueError(f"unknown fault kind {kind!r}")
        if kind == "bad_parity":
            port = self.port
            original = port.parity
            port.parity = wrong_parity(original)
            try:
                self._send(payload)
            finally:
                port.parity = original
        else:
            self._send(payload)
        self._event("inject", kind=kind, data=payload.hex(" "))
        return payload

    def flood(self, duration_s: float, chunk: int = 64, seed: int | None = None) -> int:
        """Send random bytes at line rate for ``duration_s``; return the number of bytes."""
        self._check_no_slave("flooding")
        if duration_s <= 0 or chunk < 1:
            raise ValueError("duration and chunk size must be positive")
        rng = random.Random(seed)
        port = self.port
        char_s = self.params.char_time_s()
        start = clock.now()
        sent = 0
        while (now := clock.now()) - start < duration_s:
            ahead = start + sent * char_s - now
            if ahead > 0:
                time.sleep(ahead)
                continue
            port.write(rng.randbytes(chunk))
            sent += chunk
        port.flush()
        self._event("flood", duration_s=duration_s, bytes=sent)
        return sent

    def safe_state(self) -> None:
        self._stop_slave()

    def _on_close(self) -> None:
        self._stop_slave()


class Rs485Monitor(PortSignal):
    """Passive RS-485 capture with Modbus RTU decoding."""

    kind = "rs485_monitor"

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder, link)
        self.frames: list[Frame] = []
        self._cond = threading.Condition()
        self._cursor = 0
        self._started = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        if self._thread is not None:
            return
        port = self.port
        port.reset_input_buffer()
        splitter = FrameSplitter(self.params.gap_s())
        self._stop.clear()
        self._error = None
        self._started = True
        self._thread = threading.Thread(
            target=self._run, args=(port, splitter), name=f"hil-monitor-{self.name}", daemon=True
        )
        self._thread.start()
        self._event("monitor_start", gap_s=splitter.gap_s)

    def stop(self) -> list[Frame]:
        thread, self._thread = self._thread, None
        if thread is not None:
            self._stop.set()
            thread.join(timeout=1.0)
            self._event("monitor_stop", frames=len(self.frames))
        with self._cond:
            return list(self.frames)

    def _run(self, port: SerialBase, splitter: FrameSplitter) -> None:
        try:
            while not self._stop.is_set():
                data = port.read(max(1, port.in_waiting))
                now = clock.now()
                self._add(splitter.feed(data, now) if data else splitter.poll(now))
        except Exception as exc:
            if not self._stop.is_set():
                self._error = exc
                self._event("port_failed", error=str(exc))
        finally:
            self._add(splitter.flush())
            with self._cond:
                self._cond.notify_all()

    def _add(self, frames: list[Frame]) -> None:
        if not frames:
            return
        for frame in frames:
            record = frame.to_record(self.recorder.relative(frame.t))
            self.recorder.write(f"rs485-{self.alias}.jsonl", record)
        with self._cond:
            self.frames.extend(frames)
            self._cond.notify_all()

    def wait_for_frame(self, predicate: Callable[[Frame], bool], timeout: float) -> Frame:
        """Wait for a matching frame after the one returned by the previous call."""
        if not self._started:
            raise OperationNotAllowed(f"{self.alias}: start() the monitor first")
        deadline = clock.now() + timeout
        with self._cond:
            while True:
                while self._cursor < len(self.frames):
                    frame = self.frames[self._cursor]
                    self._cursor += 1
                    if predicate(frame):
                        return frame
                if self._error is not None:
                    raise DeviceError(f"{self.alias}: monitor port failed: {self._error}") from self._error
                remaining = deadline - clock.now()
                if remaining <= 0 or self._thread is None:
                    raise WaitTimeout(
                        f"{self.alias}: no matching frame within {timeout} s "
                        f"({len(self.frames)} frames captured)"
                    )
                self._cond.wait(remaining)

    def safe_state(self) -> None:
        self.stop()
        with self._cond:
            self.frames.clear()
            self._cursor = 0
        self._started = False

    def _on_close(self) -> None:
        self.stop()
```

- [ ] **Step 4: Upravit `src/hil/signals/__init__.py`**

Přidat `from hil.signals.rs485 import Rs485Monitor, Rs485Signal` a do `__all__` doplnit `"Rs485Monitor"` a `"Rs485Signal"` (seznam seřazený abecedně: `"FaultPath", "PortSignal", "PowerSignal", "Rs485Monitor", "Rs485Signal", "SenseRecording", "SenseSignal", "SerialSignal", "Signal", "SwitchSignal"`).

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest tests/signals/test_rs485.py -v`
Expected: všechny PASS.

- [ ] **Step 6: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
git add src/hil/signals tests/signals/test_rs485.py
git commit -m "feat: signály RS-485 master, slave, injektáž poruch a monitor"
```

---

### Úkol 9: Stanoviště, `Dut`, simulované stanoviště a CLI

**Files:**
- Create: `src/hil/blocks/comm.py`
- Modify: `src/hil/blocks/__init__.py`, `src/hil/station.py`, `src/hil/dut.py`, `src/hil/cli.py`, `src/hil/stations/sim.yaml`, `examples/dut.yaml`
- Test: `tests/test_station_comm.py`, `tests/test_cli.py`, `tests/test_pytest_plugin.py`

**Interfaces:**
- Consumes: vše z úkolů 1–8, `lookup` z `hil.blocks._lookup`.
- Produces:
  - `CommBlock(serials, rs485s, monitors, profile_terminals=None)` s atributy `serials`, `rs485s`, `monitors` a metodami `serial(name) -> SerialSignal`, `rs485(name) -> Rs485Signal`, `monitor(name) -> Rs485Monitor`.
  - `Station.comm: CommBlock`; stanoviště sestaví svorky `serial`, `rs485`, `rs485_monitor`; `Station.close()` zavře signály (porty) před zařízeními.
  - `Dut` při vytvoření nastaví (`configure`) a otevře porty všech zapojených komunikačních signálů s parametry z `dut.yaml`. Konzole tak zachytává výstup od začátku testu.
  - vestavěné stanoviště `sim` má zařízení `ser` (`sim_serial`) se sběrnicemi `con: [con, dut_con]`, `log: [log, dut_log]`, `rs485: [com1, mon1, dut_rs485]` a svorky `CON`, `LOG`, `COM1`, `MON1`. Testy hrají DUT přes `hil.devices["ser"].endpoint("dut_con")` apod.
  - `examples/dut.yaml` má 9 signálů (navíc `log`, `rs485`, `bus_monitor`).
  - `hil info` vypisuje blok `comm`.

- [ ] **Step 1: Napsat padající test `tests/test_station_comm.py`**

```python
from pathlib import Path

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.loader import load_dut
from hil.config.models import SerialParams
from hil.dut import Dut
from hil.errors import ConfigError
from hil.signals import Rs485Monitor, Rs485Signal, SerialSignal
from hil.station import Station

EXAMPLE = Path(__file__).parents[1] / "examples" / "dut.yaml"


@pytest.fixture
def station():
    with Station.from_files("sim") as station:
        yield station


@pytest.fixture
def dut(station):
    return Dut(load_dut(EXAMPLE, station.profile), station)


def test_comm_terminals(station):
    assert isinstance(station.comm.serial("CON"), SerialSignal)
    assert isinstance(station.comm.serial("LOG"), SerialSignal)
    assert isinstance(station.comm.rs485("COM1"), Rs485Signal)
    assert isinstance(station.comm.monitor("MON1"), Rs485Monitor)
    with pytest.raises(ConfigError, match="is a rs485 terminal, not a serial"):
        station.comm.serial("COM1")


def test_dut_configures_and_opens_ports(dut, station):
    assert station.terminals["CON"].is_open
    assert dut.console.alias == "console"
    assert dut.console.params == SerialParams(baud=115200)
    assert dut.rs485.params == SerialParams(baud=921600, parity="E")
    assert dut.bus_monitor.alias == "bus_monitor"


def test_console_round_trip(dut, station):
    with station.devices["ser"].endpoint("dut_con") as side:
        side.write(b"boot\r\nREADY\r\n")
        dut.console.expect("READY", timeout=1)
        dut.console.write("status\n")
        assert side.read(7) == b"status\n"


def test_modbus_end_to_end(dut, station):
    dut.bus_monitor.start()
    params = SerialParams(baud=921600, parity="E")
    with station.devices["ser"].endpoint("dut_rs485", params) as side, ModbusSlave(
        side, 1, ModbusDataStore(holding_registers={0: 3})
    ):
        assert dut.rs485.modbus.read_holding_registers(1, 0, 1) == [3]
    frame = dut.bus_monitor.wait_for_frame(
        lambda f: f.decoded is not None and f.decoded.kind == "response", timeout=1
    )
    assert frame.decoded.fields["values"] == [3]


def test_safe_state_stops_monitor(station):
    monitor = station.comm.monitor("MON1")
    monitor.start()
    station.safe_state()
    assert not monitor.running


def test_close_releases_ports():
    station = Station.from_files("sim")
    station.open()
    console = station.comm.serial("CON")
    console.open()
    station.close()
    assert not console.is_open
```

- [ ] **Step 2: Ověřit, že test padá**

Run: `python -m pytest tests/test_station_comm.py -v`
Expected: FAIL, `AttributeError: 'Station' object has no attribute 'comm'`.

- [ ] **Step 3: Vytvořit `src/hil/blocks/comm.py`**

```python
"""Communication block: serial consoles, RS-485 ports and monitors."""

from collections.abc import Mapping

from hil.blocks._lookup import lookup
from hil.signals import Rs485Monitor, Rs485Signal, SerialSignal


class CommBlock:
    """All communication terminals of a station."""

    def __init__(
        self,
        serials: Mapping[str, SerialSignal],
        rs485s: Mapping[str, Rs485Signal],
        monitors: Mapping[str, Rs485Monitor],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.serials = dict(serials)
        self.rs485s = dict(rs485s)
        self.monitors = dict(monitors)
        self._profile_terminals = profile_terminals

    def serial(self, name: str) -> SerialSignal:
        return lookup(name, self.serials, "serial", self._profile_terminals)

    def rs485(self, name: str) -> Rs485Signal:
        return lookup(name, self.rs485s, "rs485", self._profile_terminals)

    def monitor(self, name: str) -> Rs485Monitor:
        return lookup(name, self.monitors, "rs485_monitor", self._profile_terminals)
```

`src/hil/blocks/__init__.py`:
```python
"""HAL blocks: operations over terminals and rules spanning several terminals."""

from hil.blocks.comm import CommBlock
from hil.blocks.digital import DigitalBlock
from hil.blocks.faults import FaultMatrix
from hil.blocks.power import PowerBlock

__all__ = ["CommBlock", "DigitalBlock", "FaultMatrix", "PowerBlock"]
```

- [ ] **Step 4: Upravit `src/hil/station.py`**

1. Importy:
```python
from hil.blocks import CommBlock, DigitalBlock, FaultMatrix, PowerBlock
from hil.config.models import (
    FaultPathTerminal,
    PowerTerminal,
    Rs485MonitorTerminal,
    Rs485Terminal,
    SenseTerminal,
    SerialTerminal,
    SwitchTerminal,
)
from hil.resources import DigitalInput, RelayChannel, SerialLink
from hil.signals import (
    FaultPath,
    PowerSignal,
    Rs485Monitor,
    Rs485Signal,
    SenseSignal,
    SerialSignal,
    Signal,
    SwitchSignal,
)
```
2. V `__init__` za `self.faults = FaultMatrix(...)` přidat:
```python
        self.comm = CommBlock(
            self._of(SerialSignal), self._of(Rs485Signal), self._of(Rs485Monitor), terminals
        )
```
3. V `_build` před řádek `kind = getattr(terminal, "kind", "?")` přidat do `match` tři větve:
```python
            case SerialTerminal(port=port):
                return SerialSignal(name, rec, self._resource(name, port, SerialLink))
            case Rs485Terminal(port=port):
                return Rs485Signal(name, rec, self._resource(name, port, SerialLink))
            case Rs485MonitorTerminal(port=port):
                return Rs485Monitor(name, rec, self._resource(name, port, SerialLink))
```
4. V `close()` mezi blok s `self.safe_state()` a smyčku zavírání zařízení vložit:
```python
        for signal in self.terminals.values():
            try:
                signal.close()
            except Exception as exc:
                log.error("closing terminal %s failed: %s", signal.name, exc)
                errors.append(exc)
```

- [ ] **Step 5: Upravit `src/hil/dut.py`**

```python
"""DUT: logical signal names mapped to station terminals."""

from typing import Any

from hil.config.models import DutConfig, SerialParams, signal_params
from hil.errors import SignalUnavailable
from hil.signals import PortSignal, Signal
from hil.station import Station


class Dut:
    """Signals of the DUT, accessible as attributes (``dut.door_sensor``).

    Ports of wired communication signals are opened with the DUT's parameters when
    the object is created, so a console captures output from the start of the test.
    """

    def __init__(self, config: DutConfig, station: Station) -> None:
        self.config = config
        self.station = station
        self.name = config.dut
        for name, spec in config.signals.items():
            if isinstance(station.terminals.get(spec.terminal), PortSignal):
                self.signal(name)

    def signal(self, name: str) -> Signal:
        spec = self.config.signals.get(name)
        if spec is None:
            known = ", ".join(sorted(self.config.signals))
            raise AttributeError(f"DUT {self.name!r} has no signal {name!r} (known: {known})")
        try:
            signal = self.station.terminal(spec.terminal)
        except SignalUnavailable as exc:
            raise SignalUnavailable(f"signal {name!r}: {exc}") from exc
        if isinstance(signal, PortSignal):
            params = signal_params(signal.kind, spec.params())
            if isinstance(params, SerialParams):
                signal.configure(name, params)
        return signal
```
Metody `params`, `available`, `__getattr__` a `__repr__` zůstávají beze změny.

- [ ] **Step 6: Rozšířit `src/hil/stations/sim.yaml` a `examples/dut.yaml`**

V `src/hil/stations/sim.yaml` nahradit hlavičkový komentář:
```yaml
# Built-in simulated station: every device is simulated, no hardware is needed.
# It wires every power, switch, sense, fault_path, serial, rs485 and rs485_monitor
# terminal of the standard-v1 profile (analog and debug terminals are not wired).
# X1.1 is looped back to X2.1 (di1.0 mirrors rel1.2), so stimulus and response can be tested.
# Tests play the DUT side of the serial buses through hil.devices["ser"].endpoint(...):
# dut_con (console CON), dut_log (log LOG), dut_rs485 (RS-485 bus of COM1 and MON1).
```
Do `devices:` přidat řádek:
```yaml
  ser: {driver: sim_serial, buses: {con: [con, dut_con], log: [log, dut_log], rs485: [com1, mon1, dut_rs485]}}
```
Na konec `terminals:` přidat:
```yaml
  CON: {kind: serial, port: ser.con}
  LOG: {kind: serial, port: ser.log}
  COM1: {kind: rs485, port: ser.com1}
  MON1: {kind: rs485_monitor, port: ser.mon1}
```

`examples/dut.yaml` – na konec `signals:` přidat:
```yaml
  log: {terminal: LOG, baud: 115200}
  rs485: {terminal: COM1, baud: 921600, parity: E}
  bus_monitor: {terminal: MON1, baud: 921600, parity: E}
```

- [ ] **Step 7: Upravit CLI a jeho testy**

V `src/hil/cli.py` v `_info` do slovníku `blocks` přidat za `"faults"`:
```python
        "comm": [*station.comm.serials, *station.comm.rs485s, *station.comm.monitors],
```
V `tests/test_cli.py`:
- v `test_check_with_dut_and_probe` změnit `"DUT 'example': 6 signals OK"` na `"DUT 'example': 9 signals OK"` a `"all 2 devices opened"` na `"all 3 devices opened"`,
- na konec `test_info` přidat `assert re.search(r"comm\s+CON, LOG, COM1, MON1", out)` a `assert re.search(r"CON\s+serial\s+wired", out)`.

- [ ] **Step 8: Test záznamu konzole přes plugin**

Na konec `tests/test_pytest_plugin.py` přidat:
```python
CONSOLE_DUT = """
dut: demo
profile: standard-v1
signals:
  console: {terminal: CON, baud: 115200}
"""


def test_serial_log_artifact(pytester):
    pytester.makefile(".yaml", dut=CONSOLE_DUT)
    pytester.makepyfile(
        """
        def test_console(dut, hil):
            with hil.devices["ser"].endpoint("dut_con") as side:
                side.write(b"hello\\r\\n")
                dut.console.expect("hello", timeout=1)
        """
    )
    result = pytester.runpytest("--hil-station", "sim", "--hil-dut", "dut.yaml", "--hil-out", "out")
    result.assert_outcomes(passed=1)
    logs = list((pytester.path / "out").glob("*/serial-console.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8").splitlines()[1].endswith("hello")
```

- [ ] **Step 9: Spustit testy**

Run: `python -m pytest tests/test_station_comm.py tests/test_cli.py tests/test_pytest_plugin.py tests/test_dut.py -v`
Expected: všechny PASS.

- [ ] **Step 10: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
git add src/hil/blocks src/hil/station.py src/hil/dut.py src/hil/cli.py src/hil/stations/sim.yaml examples/dut.yaml tests/test_station_comm.py tests/test_cli.py tests/test_pytest_plugin.py
git commit -m "feat: komunikační svorky na stanovišti, v DUT a na simulovaném stanovišti"
```

---

### Úkol 10: Dokumentace, příklad testů a specifikace

**Files:**
- Create: `examples/tests/test_comm_on_sim.py`
- Modify: `doc/software/konfigurace.md`, `doc/software/testy.md`, `doc/specs/2026-10-05-hil-python-package-design.md`

**Interfaces:**
- Consumes: celé API z úkolů 1–9.
- Produces: spustitelný příklad, dokumentaci uživatele a specifikaci odpovídající implementaci.

- [ ] **Step 1: Vytvořit `examples/tests/test_comm_on_sim.py`**

```python
"""Communication examples on the built-in simulated station.

The DUT side is played through ``hil.devices["ser"]``; on a real station the DUT
answers itself and these lines are left out.

    python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
"""

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import SerialParams


def test_console_ready(dut, hil):
    with hil.devices["ser"].endpoint("dut_con") as side:
        side.write(b"boot\r\nREADY\r\n")
        dut.console.expect(r"READY", timeout=1)


def test_modbus_register(dut, hil):
    dut.bus_monitor.start()
    params = SerialParams(baud=921600, parity="E")
    with hil.devices["ser"].endpoint("dut_rs485", params) as side, ModbusSlave(
        side, address=1, store=ModbusDataStore(holding_registers={0: 7})
    ):
        assert dut.rs485.modbus.read_holding_registers(1, 0, 1) == [7]
    dut.bus_monitor.wait_for_frame(
        lambda f: f.decoded is not None and f.decoded.kind == "response", timeout=1
    )
```

Run: `python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -rs -v`
Expected: 5 passed, 1 skipped (AO.1).

- [ ] **Step 2: Doplnit `doc/software/konfigurace.md`**

Do tabulky ovladačů přidat řádky:
```markdown
| `sim_serial` | `buses: {sběrnice: [port, port, ...]}`, každá sběrnice alespoň 2 porty, port jen na jedné sběrnici | jména portů |
| `serial_ports` | `ports: {kanál: cesta \| URL \| {serial: FT4ABC, interface: 0–3}}`, `low_latency` (výchozí `true`) | klíče `ports` |
```
Za tabulku přidat odstavec:
```markdown
`sim_serial` simuluje vodiče: co jeden port sběrnice zapíše, dostanou všechny ostatní porty téže sběrnice (RS-485 master, monitor i DUT). Test hraje stranu DUT přes `hil.devices["ser"].endpoint("dut_con")`. `serial_ports` otevírá skutečné porty: cestou (`/dev/serial/by-id/...`, `COM7`), URL pyserialu (`loop://`) nebo sériovým číslem čipu FTDI a číslem kanálu (0 = A). Na Linuxu nastaví latency timer FTDI na 1 ms. Bez práv zápisu do sysfs jen varuje, nastavení pak patří do pravidla udev. Na Windows se latency timer nastavuje ve Správci zařízení.
```
Do seznamu svorek přidat:
```markdown
- `serial`, `rs485`, `rs485_monitor`: `port: <zařízení>.<kanál>` na zařízení `serial_ports` nebo `sim_serial`.
```
Do sekce o stanovišti `sim` doplnit, že zapojuje i `CON`, `LOG`, `COM1` a `MON1`. Strana DUT je dostupná jako porty `dut_con`, `dut_log` a `dut_rs485` zařízení `ser`.
Do sekce Zapojení DUT přidat tabulku parametrů:
```markdown
Parametry signálů `serial`, `rs485` a `rs485_monitor`:

| Parametr | Výchozí | Význam |
|---|---|---|
| `baud` | 115200 | rychlost |
| `parity` | `N` | `N`, `E` nebo `O` |
| `stopbits` | 1 | 1 nebo 2 |
| `bytesize` | 8 | 7 nebo 8 |
| `timeout_s` | 1.0 | `rs485`: jak dlouho master čeká na odpověď |
| `echo` | `false` | `rs485`: převodník vrací odeslané bajty |
| `frame_gap_s` | 3,5 znaku, alespoň 1,5 ms | `rs485_monitor`: ticho, které ukončuje rámec |

Neznámý parametr nebo parametr u signálu jiného druhu je chyba konfigurace.
```

- [ ] **Step 3: Doplnit `doc/software/testy.md`**

Do tabulky signálů přidat řádky:
```markdown
| `serial` | `write(data)`, `expect(regex, timeout) -> match`, `read_until(konec, timeout)`; log do `serial-<signál>.log` |
| `rs485` | `modbus.read_holding_registers(adresa, start, počet)` a další funkce 1–6, 15, 16; `with slave(adresa, store):`; `send_raw(bajty)`; `inject(druh, rámec)` (`bad_crc`, `truncated`, `extended`, `bad_parity`); `flood(s)` |
| `rs485_monitor` | `start()`, `stop()`, `frames`, `wait_for_frame(podmínka, timeout)`; záznam do `rs485-<signál>.jsonl` |
```
Za tabulku přidat:
```markdown
Porty komunikačních signálů se otevřou při vytvoření fixture `dut` s parametry z `dut.yaml`, takže konzole zachytí i výpis po zapnutí napájení. Po každém testu bezpečný stav zahodí nepřečtený výstup konzole, zastaví monitor (a smaže jeho rámce) a ukončí simulovaný slave. Master hlásí chybějící odpověď jako `DeviceTimeout` po `timeout_s`, výjimku zařízení jako `ModbusExceptionResponse` (atribut `code`).

Modbus RTU je vlastní implementace v `hil.comm`: `hil.comm.modbus` (CRC, sestavení a dekódování rámců), `ModbusMaster`, `ModbusSlave` s `ModbusDataStore`. Lze je použít i samostatně nad libovolným portem pyserialu.
```
Do sekce Záznamy doplnit soubory `serial-<signál>.log` (řádek = čas od začátku testu a text) a `rs485-<signál>.jsonl` (čas, bajty v hex, dekódovaný rámec nebo chyba).

- [ ] **Step 4: Zapsat odchylky do specifikace**

V `doc/specs/2026-10-05-hil-python-package-design.md`:
- v tabulce kap. 4.3 u `modbus_rtu_bus` nahradit „sdílený klient pymodbus“ textem „sdílený Modbus RTU master z `hil.comm`“,
- v kap. 5.1 v řádku `rs485` změnit `inject(kind)` na `inject(kind, frame)`,
- v kap. 9 v odstavci Závislosti odstranit `pymodbus` a `numpy` z výčtu a doplnit větu: „Modbus RTU (master, slave, kodek) je vlastní implementace v `hil.comm`. numpy přibude s analogovou částí.“,
- v tabulce kap. 4.3 u `serial_ports` doplnit „Na Windows se hodnota nekontroluje, jen se upozorní v logu“ místo „hodnotu jen ověří a při vyšší hodnotě varuje“.

- [ ] **Step 5: Kontroly a commit**

```
ruff format .
ruff check .
mypy
python -m pytest
python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
git add examples/tests/test_comm_on_sim.py doc/software doc/specs
git commit -m "doc: komunikace v dokumentaci, příklad testů a odchylky ve specifikaci"
```

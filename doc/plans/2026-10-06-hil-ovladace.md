# Ovladače balíčku `hil` – implementační plán (plán 3 ze 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Cíl:** skutečné ovladače stanoviště (sběrnice Modbus RTU, relé Waveshare a Quido, modul digitálních vstupů, OpenOCD) a celý ladicí řetězec (`debug`), bezpečné ukončení procesu, `hil safe` pro start PC, stanoviště `lab-a`, HW testy a dokumentace nasazení. Hardware zatím není k dispozici, vše se testuje proti simulaci.

**Architektura:** `modbus_rtu_bus` vlastní port (vlastní cestou, nebo odkazem `link` na port jiného zařízení) a `ModbusMaster` z `hil.comm`. Moduly relé a vstupů k němu přistupují přes `bus.call()`, které sběrnici zamkne s timeoutem. Testy ovladačů běží proti `hil.comm.slave.ModbusSlave` na portech `sim_serial`. Ladicí řetězec tvoří prostředek `DebugProbe` (vrací `ProbeResult`), ovladače `sim_probe` a `openocd`, signál `DebugSignal` a blok `DebugBlock`. Obsluha signálů procesu už nekomunikuje se zařízeními, jen vyhodí `TerminationRequested` (podtřída `KeyboardInterrupt`) a bezpečný stav nastaví úklid.

**Tech stack:** Python ≥ 3.12, pyserial 3.5, pydantic v2, pytest, OpenOCD (systémový program, v testech nahrazený skriptem).

**Spec:** [doc/specs/2026-10-05-hil-python-package-design.md](../specs/2026-10-05-hil-python-package-design.md) včetně rozhodnutí pro plán 3 (kap. 3.2, 4.2, 4.3, 4.4, 5.3, 8, 11). Navazuje na [plán 1](2026-10-05-hil-jadro.md) a [plán 2](2026-10-05-hil-komunikace.md), oba jsou hotové na `main`.

**Navazující plán:** plán 4 (analog: Analog Discovery 3, `analog_out`, `analog_in`, `AnalogBlock`, numpy).

## Global Constraints

- `requires-python = ">=3.12"`, CI na `ubuntu-latest` a `windows-latest`, Python 3.12, 3.13, 3.14.
- Zdrojový kód včetně komentářů, docstringů, zpráv výjimek a výstupu CLI je anglicky. Dokumentace v `doc/` je česky.
- Žádné nové runtime závislosti. OpenOCD je systémový program, v testech ho nahrazuje `tests/drivers/fake_openocd.py`.
- mypy strict platí pro `hil.config.*`, `hil.blocks.*`, `hil.signals.*` a `hil.comm.*`.
- Všechna časová razítka jsou z `hil.clock.now()` (= `time.perf_counter()`), v sekundách.
- Vytvoření zařízení nedělá žádné I/O, hardware se otevírá v `Device.open()`. `open`/`close`/`safe_state` hlásí selhání jako `DeviceError` (nebo podtřídu). Výjimka `ModbusExceptionResponse` se v ovladačích převádí na `DeviceError`.
- Modbus: adresa 0 je broadcast, CRC-16/MODBUS nižším bajtem napřed, registry big-endian, bity LSB first.
- Obsluha signálu procesu (SIGINT, SIGTERM, SIGHUP, SIGBREAK) nesmí komunikovat se zařízeními.
- Před každým commitem musí projít: `ruff format .`, `ruff check .`, `mypy`, `python -m pytest` a `python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml`.
- Pracuje se na větvi `main`, bez vlastních větví, bez push. Commit zprávy česky ve stylu repozitáře, bez řádků `Co-Authored-By`.
- Když `ruff check` hlásí E501 u dlouhého řetězce v kódu z plánu, řetězec se rozdělí. Chování se nemění.

## Review Focus

1. **Modul na sběrnici neodpovídá** (vypnutý, jiná adresa nebo rychlost): `open()` vyhodí `DeviceNotFound` se jménem zařízení, adresou a sběrnicí nejpozději po `timeout_s`, nikdy nezamrzne. Test: úkol 4 `test_missing_module_is_device_not_found`, úkol 5 `test_missing_input_module`.
2. **Sběrnici drží jiné vlákno** (záznam `sense`, zaseknutá transakce) **a ozve se `atexit` nebo další operace:** čekání skončí po `lock_timeout_s` chybou `DeviceTimeout`, ne deadlockem. Test: úkol 3 `test_busy_bus_times_out`.
3. **Signál ukončení přijde během `Station.close()` nebo podruhé:** nastavování bezpečného stavu doběhne a výjimka nevznikne. Testy: úkol 8 `test_signal_during_close_does_not_abort_safe_state`, `test_termination_signal_only_interrupts`.
4. **Při startu PC chybí jeden modul relé:** `hil safe` nastaví bezpečný stav na ostatních zařízeních a vrátí kód 3 s výpisem chyb. Testy: úkol 9 `test_best_effort_open_sets_safe_state_on_the_rest`, `test_safe_is_best_effort`.
5. **Chybějící obraz firmwaru, chybějící OpenOCD, chybějící `target` nebo selhání OpenOCD:** srozumitelná chyba (`FileNotFoundError`, `DeviceNotFound`, `OperationNotAllowed`, `DeviceError`) a výstup OpenOCD je v `openocd.log` i při chybě. Testy: úkol 6 `test_missing_image`, `test_target_needed`, `test_failure_is_device_error_with_log`, úkol 7 `test_missing_program`.

---

## Struktura souborů

```
pyproject.toml                          # + marker hw
src/hil/errors.py                       # + TerminationRequested
src/hil/comm/master.py                  # min_gap_s, check of write responses
src/hil/comm/modbus.py                  # decode(frame, previous)
src/hil/comm/framing.py                 # split_frames/FrameSplitter pass the previous frame
src/hil/config/models.py                # + DebugParams, PARAM_MODELS["debug"]
src/hil/resources.py                    # + ProbeResult, DebugProbe
src/hil/drivers/__init__.py             # registers the new drivers
src/hil/drivers/serial_ports.py         # resolve_port, list_comports_once, latency once, FT232 on Windows
src/hil/drivers/modbus_bus.py           # driver modbus_rtu_bus
src/hil/drivers/modbus_relay.py         # ModbusRelayModule (common part of relay modules)
src/hil/drivers/waveshare_relay.py      # driver waveshare_relay32
src/hil/drivers/quido.py                # driver quido_rs_2_32
src/hil/drivers/modbus_di.py            # driver modbus_di
src/hil/drivers/openocd.py              # driver openocd
src/hil/drivers/sim/probe.py            # driver sim_probe
src/hil/signals/debug.py                # DebugSignal
src/hil/signals/rs485.py                # cached master, bad_parity fixes
src/hil/signals/uart.py                 # reopen a failed port in safe_state
src/hil/signals/digital.py              # timeouts in SenseSignal.record
src/hil/blocks/debug.py                 # DebugBlock
src/hil/station.py                      # debug terminals, termination signals, best-effort open
src/hil/dut.py                          # configures debug signals
src/hil/cli.py                          # info lists debug, safe is best-effort
src/hil/stations/sim.yaml               # + sim_probe, SWD
stations/lab-a.yaml                     # first real station
deploy/udev/99-hil.rules, deploy/systemd/hil-safe.service
examples/dut.yaml, examples/tests/test_debug_on_sim.py
tests/drivers/conftest.py               # simulated RS-485 line with Modbus modules
tests/drivers/fake_openocd.py
tests/hw/conftest.py, tests/hw/test_station_hw.py
doc/software/konfigurace.md, testy.md, nasazeni.md, hw-testy.md, README.md
```

---

### Úkol 1: Modbus master – mezera mezi rámci, kontrola odpovědi na zápis, dekodér

**Files:**
- Modify: `src/hil/comm/master.py`, `src/hil/comm/modbus.py`, `src/hil/comm/framing.py`, `src/hil/signals/rs485.py`
- Test: `tests/comm/test_master_slave.py`, `tests/comm/test_modbus.py`, `tests/comm/test_framing.py`, `tests/signals/test_rs485.py`

**Interfaces:**
- Consumes: `ModbusMaster`, `decode`, `split_frames`, `FrameSplitter` (plán 2).
- Produces:
  - `ModbusMaster(port, timeout_s=1.0, echo=False, on_exchange=None, min_gap_s=0.0)`; atribut `min_gap_s: float`. Před každým odesláním počká, až od konce předchozí výměny uplyne `min_gap_s`.
  - `check_write_response(request: bytes, response: bytes) -> None` v `hil.comm.master` (vyhodí `DeviceError`).
  - `decode(frame: bytes, previous: ModbusFrame | None = None) -> ModbusFrame`.
  - `split_frames(data: bytes, t: float, previous: ModbusFrame | None = None) -> list[Frame]`.
  - `Rs485Signal.modbus` vrací stejný master, dokud se nezmění port nebo parametry. Master má `min_gap_s = params.gap_s()`.

- [ ] **Step 1: Napsat padající testy**

Na konec `tests/comm/test_master_slave.py`:
```python
def test_min_gap_between_requests(bus, slave):
    with bus.endpoint("master") as port:
        master = ModbusMaster(port, timeout_s=0.3, min_gap_s=0.05)
        master.read_holding_registers(1, 0, 1)
        start = time.perf_counter()
        master.read_holding_registers(1, 0, 1)
        assert time.perf_counter() - start >= 0.045


def test_min_gap_must_not_be_negative(bus):
    with bus.endpoint("master") as port, pytest.raises(ValueError, match="min_gap_s"):
        ModbusMaster(port, timeout_s=0.3, min_gap_s=-1)


def test_write_response_must_repeat_request(master, slave):
    slave.respond = lambda frame: modbus.with_crc(frame[:4] + b"\x00\x00")
    with pytest.raises(DeviceError, match="does not repeat the request"):
        master.write_register(1, 1, 99)


def test_multiple_write_response_must_match_start_and_count(master, slave):
    slave.respond = lambda frame: modbus.with_crc(frame[:2] + b"\x00\x00\x00\x01")
    with pytest.raises(DeviceError, match="does not match the start and count"):
        master.write_coils(1, 0, [True, False])
```

Na konec `tests/comm/test_modbus.py`:
```python
def test_decode_bit_read_response_with_three_bytes():
    request = modbus.read_request(1, modbus.READ_COILS, 0, 20)
    response = modbus.with_crc(bytes((1, 1, 3, 0x01, 0x02, 0x03)))
    # without the request the frame has the length of a request
    assert modbus.decode(response).kind == "request"
    decoded = modbus.decode(response, modbus.decode(request))
    assert decoded.kind == "response"
    bits = decoded.fields["bits"]
    assert isinstance(bits, list)
    assert bits[0] is True and bits[9] is True and bits[1] is False


def test_decode_previous_of_other_device_is_ignored():
    request = modbus.read_request(2, modbus.READ_COILS, 0, 20)
    response = modbus.with_crc(bytes((1, 1, 3, 0x01, 0x02, 0x03)))
    assert modbus.decode(response, modbus.decode(request)).kind == "request"
```

Na konec `tests/comm/test_framing.py` (pokud chybí `from hil.comm import modbus`, přidat ho mezi importy):
```python
def test_bit_read_response_with_three_bytes_after_request():
    request = modbus.read_request(1, modbus.READ_COILS, 0, 20)
    response = modbus.with_crc(bytes((1, 1, 3, 0x01, 0x02, 0x03)))
    splitter = FrameSplitter(gap_s=0.002)
    frames = splitter.feed(request, 0.0)
    frames += splitter.poll(0.01)
    frames += splitter.feed(response, 0.02)
    frames += splitter.poll(0.03)
    assert [f.decoded.kind for f in frames if f.decoded] == ["request", "response"]


def test_split_frames_passes_previous_frame():
    request = modbus.read_request(1, modbus.READ_COILS, 0, 20)
    response = modbus.with_crc(bytes((1, 1, 3, 0x01, 0x02, 0x03)))
    frames = split_frames(request + response, t=0.0)
    assert [f.decoded.kind for f in frames if f.decoded] == ["request", "response"]
```

Na konec `tests/signals/test_rs485.py`:
```python
def test_master_is_reused_and_keeps_gap(rs485):
    master = rs485.modbus
    assert rs485.modbus is master
    assert master.min_gap_s == rs485.params.gap_s()
    rs485.configure("modbus", SerialParams(baud=9600, timeout_s=0.3))
    assert rs485.modbus is not master
    assert rs485.modbus.min_gap_s == SerialParams(baud=9600).gap_s()
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/comm tests/signals/test_rs485.py -q`
Expected: FAIL (`unexpected keyword argument 'min_gap_s'`, `decode() takes 1 positional argument`, chybějící kontrola zápisu).

- [ ] **Step 3: Implementace v `src/hil/comm/master.py`**

Přidat importy `import math` a `import time`. Za funkci `response_length` přidat:
```python
def check_write_response(request: bytes, response: bytes) -> None:
    """A write response repeats the request (functions 5, 6) or its start and count (15, 16)."""
    function = request[1]
    if function in (modbus.WRITE_SINGLE_COIL, modbus.WRITE_SINGLE_REGISTER):
        if response != request:
            raise DeviceError(
                f"device {request[0]}: write response {response.hex(' ')} does not repeat "
                f"the request {request.hex(' ')}"
            )
    elif function in (modbus.WRITE_MULTIPLE_COILS, modbus.WRITE_MULTIPLE_REGISTERS):
        if response[2:6] != request[2:6]:
            raise DeviceError(
                f"device {request[0]}: write response {response.hex(' ')} does not match "
                f"the start and count of the request {request.hex(' ')}"
            )
```

Konstruktor `ModbusMaster` dostane parametr `min_gap_s` a docstring třídy větu o mezeře:
```python
class ModbusMaster:
    """Blocking Modbus RTU master.

    The port must have a short read timeout (tens of milliseconds); ``timeout_s`` bounds
    the wait for a whole response. ``min_gap_s`` is the silence kept on the bus between
    the end of one exchange and the next request (3.5 characters by the standard; some
    devices need more time before they listen again).
    """

    def __init__(
        self,
        port: Serial,
        timeout_s: float = 1.0,
        echo: bool = False,
        on_exchange: Exchange | None = None,
        min_gap_s: float = 0.0,
    ) -> None:
        if getattr(port, "timeout", 1) in (None, 0):
            raise ValueError("the port needs a finite non-zero read timeout")
        if min_gap_s < 0:
            raise ValueError("min_gap_s must not be negative")
        self.port = port
        self.timeout_s = timeout_s
        self.echo = echo
        self.on_exchange = on_exchange
        self.min_gap_s = min_gap_s
        self._received = b""
        self._last_traffic = -math.inf

    def _wait_quiet(self) -> None:
        """Keep the bus silent for ``min_gap_s`` after the previous exchange."""
        remaining = self._last_traffic + self.min_gap_s - clock.now()
        if remaining > 0:
            time.sleep(remaining)
```

`transact` nahradit:
```python
    def transact(self, frame: bytes) -> bytes | None:
        """Send ``frame`` and return the validated response (None for a broadcast)."""
        self._received = b""
        self._wait_quiet()
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
            self._received = b""
            response = self._read_response(frame, deadline)
            check_write_response(frame, response)
            return response
        except SerialException as exc:
            raise DeviceError(f"device {frame[0]}: serial port failed: {exc}") from exc
        finally:
            self._last_traffic = clock.now()
            if self.on_exchange is not None:
                try:
                    self.on_exchange(frame, self._received or None)
                except Exception:
                    log.exception("on_exchange callback failed")
```

- [ ] **Step 4: Implementace v `src/hil/comm/modbus.py`**

Před `decode` přidat:
```python
def _answers_bit_read(
    previous: ModbusFrame | None, address: int, function: int, data: bytes
) -> bool:
    """True when ``data`` is the response to the bit read ``previous``."""
    if previous is None or previous.kind != "request" or function not in BIT_READS:
        return False
    if (previous.address, previous.function) != (address, function):
        return False
    count = previous.fields.get("count")
    return isinstance(count, int) and (count + 7) // 8 == data[0] == len(data) - 1
```

Hlavičku a docstring `decode` nahradit a upravit první větev čtení:
```python
def decode(frame: bytes, previous: ModbusFrame | None = None) -> ModbusFrame:
    """Decode a frame with a valid CRC.

    Requests and responses are told apart by their length. A single write (functions 5
    and 6) is answered by an identical echo, so both are reported as ``request``. A
    bit-read response with three data bytes has the length of a request; it is reported
    as a response when ``previous`` (the frame seen before it) is the matching request,
    otherwise as a request.
    """
    if not crc_ok(frame):
        raise ValueError(f"bad CRC in frame {frame.hex(' ')}")
    address, function = frame[0], frame[1]
    data = frame[2:-2]
    if function & 0x80:
        if len(data) == 1:
            return ModbusFrame(address, function, "exception", {"code": data[0]})
    elif function in BIT_READS | REGISTER_READS:
        if len(data) == 4 and not _answers_bit_read(previous, address, function, data):
            start, count = struct.unpack(">HH", data)
            return ModbusFrame(address, function, "request", {"start": start, "count": count})
```
Zbytek funkce zůstává.

- [ ] **Step 5: Implementace v `src/hil/comm/framing.py`**

Import doplnit o `ModbusFrame` (už je importován). `split_frames` nahradit:
```python
def split_frames(data: bytes, t: float, previous: ModbusFrame | None = None) -> list[Frame]:
    """Split one burst into frames; bytes that form no valid frame become an error frame.

    After bytes that start no valid frame (a stray byte, a truncated frame), the error
    frame ends where the rest of the burst splits cleanly into valid frames to its end;
    when there is no such position, the rest of the burst is one error frame.
    ``previous`` is the last frame decoded before the burst (see ``decode``).
    """
    frames: list[Frame] = []
    pos = 0
    while pos < len(data):
        length = frame_length(data, pos)
        if length is None:
            resync = _resync(data, pos)
            frames.append(Frame(t, data[pos:resync], None, NO_FRAME_ERROR))
            pos = resync
            continue
        raw = data[pos : pos + length]
        decoded = decode(raw, previous)
        frames.append(Frame(t, raw, decoded, None))
        previous = decoded
        pos += length
    return frames
```

V `FrameSplitter.__init__` přidat `self._previous: ModbusFrame | None = None` a `flush` nahradit:
```python
    def flush(self) -> list[Frame]:
        if not self._buffer:
            return []
        data = bytes(self._buffer)
        self._buffer.clear()
        frames = split_frames(data, self._first, self._previous)
        for frame in frames:
            if frame.decoded is not None:
                self._previous = frame.decoded
        return frames
```

- [ ] **Step 6: Implementace v `src/hil/signals/rs485.py`**

V `Rs485Signal.__init__` přidat:
```python
        self._master: ModbusMaster | None = None
        self._master_key: tuple[Serial, SerialParams] | None = None
```
(import `from hil.config.models import SerialParams`). Vlastnost `modbus` nahradit:
```python
    @property
    def modbus(self) -> ModbusMaster:
        """Modbus RTU master on this port; the same object while port and parameters stay."""
        self._check_no_slave("the Modbus master")
        port = self.port
        key = (port, self.params)
        if self._master is None or self._master_key != key:
            self._master = ModbusMaster(
                port,
                self.params.timeout_s,
                echo=self.params.echo,
                on_exchange=self._exchange,
                min_gap_s=self.params.gap_s(),
            )
            self._master_key = key
        return self._master
```

- [ ] **Step 7: Spustit testy**

Run: `python -m pytest tests/comm tests/signals -q`
Expected: PASS.

- [ ] **Step 8: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q && python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
```bash
git add src/hil/comm src/hil/signals/rs485.py tests/comm tests/signals/test_rs485.py
git commit -m "feat: mezera mezi rámci a kontrola odpovědi na zápis v Modbus masteru"
```

---

### Úkol 2: `serial_ports` – sdílené hledání portu, latency timer jednou, jednokanálové FTDI na Windows

**Files:**
- Modify: `src/hil/drivers/serial_ports.py`
- Test: `tests/drivers/test_serial_ports.py`

**Interfaces:**
- Consumes: `FtdiPort`, `find_ftdi_port`, `ensure_low_latency` (plán 2).
- Produces (pro úkol 3 a 11):
  - `list_comports_once(owner: str) -> Callable[[], list[Any]]`: vrátí funkci, která seznam portů systému načte nejvýš jednou; chybu výpisu hlásí jako `DeviceError` zařízení `owner`.
  - `port_exists(path: str, comports: Callable[[], list[Any]]) -> bool`.
  - `resolve_port(owner: str, channel: str, spec: str | FtdiPort, comports: Callable[[], list[Any]]) -> str`: cesta nebo URL portu; `DeviceNotFound` se zprávou `device '<owner>': serial port '<channel>' not found: <spec>`.
  - `SerialPorts.device_path(channel: str) -> str`: cesta kanálu otevřeného zařízení.
  - `find_ftdi_port` na Windows najde i jednokanálový čip (sériové číslo bez písmene) pro `interface == 0`.

- [ ] **Step 1: Napsat padající testy**

Do importů `tests/drivers/test_serial_ports.py` doplnit `from hil.drivers.serial_ports import FtdiPort, ensure_low_latency, find_ftdi_port, resolve_port` (nahradí stávající import). Na konec:
```python
def test_find_ftdi_single_port_chip_windows():
    ports = [SimpleNamespace(device="COM3", serial_number="A10K", location=None)]
    assert find_ftdi_port("A10K", 0, ports, platform="win32") == "COM3"
    with pytest.raises(DeviceNotFound):
        find_ftdi_port("A10K", 1, ports, platform="win32")


def test_find_ftdi_prefers_channel_suffix_windows():
    ports = [
        SimpleNamespace(device="COM3", serial_number="FT4ABC", location=None),
        SimpleNamespace(device="COM5", serial_number="FT4ABCA", location=None),
    ]
    assert find_ftdi_port("FT4ABC", 0, ports, platform="win32") == "COM5"


def test_resolve_port(monkeypatch, tmp_path):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")

    def comports():
        return PORTS

    assert resolve_port("bus", "port", "loop://", comports) == "loop://"
    ftdi = FtdiPort(serial="FT4ABC", interface=2)
    assert resolve_port("bus", "port", ftdi, comports) == "/dev/ttyUSB2"
    with pytest.raises(DeviceNotFound, match="device 'bus': serial port 'port' not found"):
        resolve_port("bus", "port", str(tmp_path / "missing"), comports)


def test_low_latency_checked_once_per_port(monkeypatch):
    import hil.drivers.serial_ports

    calls = []
    monkeypatch.setattr(hil.drivers.serial_ports, "ensure_low_latency", calls.append)
    device = make(A="loop://")
    device.open()
    for _ in range(3):
        device.resource("A").open(SerialParams(), timeout=0.01).close()
    assert calls == ["loop://"]
    device.close()
    device.open()
    device.resource("A").open(SerialParams(), timeout=0.01).close()
    assert calls == ["loop://", "loop://"]
    assert device.device_path("A") == "loop://"
    device.close()
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/drivers/test_serial_ports.py -q`
Expected: FAIL (`cannot import name 'resolve_port'`).

- [ ] **Step 3: Implementace**

V `src/hil/drivers/serial_ports.py` nahradit `find_ftdi_port`:
```python
def find_ftdi_port(
    serial_number: str, interface: int, ports: Iterable[Any], platform: str = sys.platform
) -> str:
    """Device of channel ``interface`` (0 = A) of the FTDI chip ``serial_number``."""
    letter = "ABCD"[interface]
    candidates = list(ports)
    if platform == "win32":
        # the FTDI VCP driver reports each channel of a multi-port chip with a suffix,
        # a single-port chip (FT232R, FT232H) without one
        for port in candidates:
            if (port.serial_number or "") == serial_number + letter:
                return str(port.device)
        if interface == 0:
            for port in candidates:
                if (port.serial_number or "") == serial_number:
                    return str(port.device)
    else:
        for port in candidates:
            number = port.serial_number or ""
            if number == serial_number and (port.location or "").endswith(f":1.{interface}"):
                return str(port.device)
    raise DeviceNotFound(
        f"no FTDI port with serial number {serial_number!r} and interface {interface}"
    )
```

Za `ensure_low_latency` přidat:
```python
def list_comports_once(owner: str) -> Callable[[], list[Any]]:
    """A function listing the serial ports of the system at most once (slow on Windows)."""
    available: list[Any] | None = None

    def comports() -> list[Any]:
        nonlocal available
        if available is None:
            try:
                available = list(list_ports.comports())
            except OSError as exc:
                raise DeviceError(f"device {owner!r}: cannot list serial ports: {exc}") from exc
        return available

    return comports


def port_exists(path: str, comports: Callable[[], list[Any]]) -> bool:
    if sys.platform != "win32":
        return os.path.exists(path)
    name = path.removeprefix("\\\\.\\").upper()  # \\.\COM10 names the port COM10
    return any(str(port.device).upper() == name for port in comports())


def resolve_port(
    owner: str, channel: str, spec: "str | FtdiPort", comports: Callable[[], list[Any]]
) -> str:
    """Device path or URL of a port given by path, pyserial URL or FTDI serial number."""
    if isinstance(spec, FtdiPort):
        return find_ftdi_port(spec.serial, spec.interface, comports(), platform=sys.platform)
    if "://" not in spec and not port_exists(spec, comports):
        raise DeviceNotFound(f"device {owner!r}: serial port {channel!r} not found: {spec}")
    return spec
```
(`FtdiPort` je definován výš v modulu, uvozovky v anotaci nejsou nutné; ruff je případně odstraní.)

Třídu `SerialPorts` upravit: v `__init__` přidat `self._latency_checked: set[str] = set()`, metody `open`, `close`, `open_port` nahradit a statickou metodu `_port_exists` odstranit:
```python
    def open(self) -> None:
        """Resolve the device of every channel and check that it exists (ports stay closed)."""
        comports = list_comports_once(self.name)
        devices = {
            channel: resolve_port(self.name, channel, spec, comports)
            for channel, spec in self.config.ports.items()
        }
        if self.config.low_latency and sys.platform == "win32":
            log.info(
                "%s: the FTDI latency timer cannot be checked on Windows; set it to 1 ms "
                "in Device Manager",
                self.name,
            )
        self._devices = devices
        self._latency_checked = set()

    def close(self) -> None:
        self._devices = None

    def device_path(self, channel: str) -> str:
        """Device path or URL of ``channel`` (the device must be open)."""
        if channel not in self.config.ports:
            self._no_channel(channel)
        if self._devices is None:
            raise DeviceError(f"device {self.name!r} is not open")
        return self._devices[channel]

    def open_port(self, channel: str, params: SerialParams, timeout: float | None) -> serial.Serial:
        device = self.device_path(channel)
        try:
            port = serial.serial_for_url(device, timeout=timeout, **port_settings(params))
        except (serial.SerialException, ValueError, OSError) as exc:
            raise DeviceError(
                f"device {self.name!r}: cannot open port {channel!r} ({device}): {exc}"
            ) from exc
        if self.config.low_latency and device not in self._latency_checked:
            ensure_low_latency(device)
            self._latency_checked.add(device)
        return port
```

- [ ] **Step 4: Spustit testy**

Run: `python -m pytest tests/drivers/test_serial_ports.py -q`
Expected: PASS (včetně původního `test_missing_port_windows`, který ověřuje jediný výpis portů).

- [ ] **Step 5: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q`
```bash
git add src/hil/drivers/serial_ports.py tests/drivers/test_serial_ports.py
git commit -m "feat: sdílené hledání sériového portu a jednokanálové FTDI na Windows"
```

---
### Úkol 3: Ovladač `modbus_rtu_bus`

**Files:**
- Create: `src/hil/drivers/modbus_bus.py`, `tests/drivers/conftest.py`, `tests/drivers/test_modbus_bus.py`
- Modify: `src/hil/drivers/__init__.py`

**Interfaces:**
- Consumes: `ModbusMaster(..., min_gap_s)`, `ModbusExceptionResponse` (úkol 1), `resolve_port`, `list_comports_once`, `ensure_low_latency`, `FtdiPort` (úkol 2), `SerialLink`, `port_settings`, `SerialParams`, `Ref`.
- Produces (pro úkoly 4, 5, 8, 11):
  - driver `modbus_rtu_bus`, třída `ModbusRtuBus(Device)` s konfigurací `ModbusRtuBusConfig`: `port: str | FtdiPort | None`, `link: Ref | None` (právě jedno), `baud=9600`, `parity="N"`, `stopbits=1`, `timeout_s=0.2`, `min_gap_s: float | None`, `lock_timeout_s=2.0`, `low_latency=True`; metody konfigurace `params() -> SerialParams`, `gap_s() -> float`.
  - `ModbusRtuBus.is_open: bool`, `session() -> ContextManager[ModbusMaster]` (zámek s timeoutem, `DeviceTimeout` „busy“, `DeviceError` „not open“).
  - `ModbusRtuBus.call[T](owner: str, action: Callable[[ModbusMaster], T]) -> T`: provede `action` v `session()`, `ModbusExceptionResponse` převede na `DeviceError` se jménem `owner`.
  - `find_bus(owner: str, name: str, devices: Mapping[str, Device]) -> ModbusRtuBus` (`ConfigError`, když zařízení není `modbus_rtu_bus`).
  - Fixtures v `tests/drivers/conftest.py`: `line` (sim_serial `ser`, sběrnice `relay` s porty `bus`, `m1`, `m2`, `m3`), `make_bus(**options)`, `bus` (otevřená sběrnice `relay_bus`), `module(address, store, port="m1") -> ModbusSlave`; rychlost 115200 Bd.

- [ ] **Step 1: Napsat fixtures a padající testy**

`tests/drivers/conftest.py`:
```python
from contextlib import ExitStack

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device

BAUD = 115200


@pytest.fixture
def line():
    """Simulated RS-485 line: the bus driver on port 'bus', modules on 'm1' to 'm3'."""
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"relay": ["bus", "m1", "m2", "m3"]})
    )
    device.open()
    yield device
    device.close()


@pytest.fixture
def make_bus(line):
    def make(**options):
        options.setdefault("timeout_s", 0.2)
        bus = create_device(
            "relay_bus",
            DeviceConfig(driver="modbus_rtu_bus", link="ser.bus", baud=BAUD, **options),
        )
        bus.bind({"ser": line})
        return bus

    return make


@pytest.fixture
def bus(make_bus):
    device = make_bus()
    device.open()
    yield device
    device.close()


@pytest.fixture
def module(line):
    """Start a simulated Modbus module: ``module(address, store, port="m1")``."""
    with ExitStack() as stack:

        def start(address: int, store: ModbusDataStore, port: str = "m1") -> ModbusSlave:
            side = stack.enter_context(line.endpoint(port, SerialParams(baud=BAUD)))
            return stack.enter_context(ModbusSlave(side, address, store))

        yield start
```

`tests/drivers/test_modbus_bus.py`:
```python
import threading
import time

import pytest

from hil.comm.slave import ModbusDataStore
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.drivers.modbus_bus import ModbusRtuBus, find_bus
from hil.errors import ConfigError, DeviceError, DeviceNotFound, DeviceTimeout


def bus_device(**options):
    return create_device("b", DeviceConfig(driver="modbus_rtu_bus", **options))


def test_config_needs_exactly_one_port():
    with pytest.raises(ConfigError, match="exactly one of 'port' and 'link'"):
        bus_device()
    with pytest.raises(ConfigError, match="exactly one of 'port' and 'link'"):
        bus_device(port="loop://", link="ser.bus")


def test_default_gap():
    assert bus_device(port="loop://").config.gap_s() == pytest.approx(3.5 * 10 / 9600)
    assert bus_device(port="loop://", baud=115200).config.gap_s() == 0.002
    assert bus_device(port="loop://", min_gap_s=0.01).config.gap_s() == 0.01


def test_dependencies_and_link_type(line):
    assert bus_device(link="ser.bus").dependencies() == ["ser"]
    assert bus_device(port="loop://").dependencies() == []
    relay = create_device("rel", DeviceConfig(driver="sim_relay"))
    with pytest.raises(ConfigError, match=r"link rel\.0 is not a serial port"):
        bus_device(link="rel.0").bind({"rel": relay})


def test_exchange_over_link(bus, module):
    module(1, ModbusDataStore(holding_registers={0: 5}))
    with bus.session() as master:
        assert master.read_holding_registers(1, 0, 1) == [5]
        assert master.min_gap_s == 0.002


def test_call_turns_modbus_exception_into_device_error(bus, module):
    module(1, ModbusDataStore())
    with pytest.raises(DeviceError, match="device 'rel1': .*illegal data address"):
        bus.call("rel1", lambda master: master.read_coils(1, 0, 1))


def test_session_requires_open(make_bus):
    bus = make_bus()
    with pytest.raises(DeviceError, match="not open"), bus.session():
        pass


def test_busy_bus_times_out(make_bus):
    bus = make_bus(lock_timeout_s=0.1)
    bus.open()
    holding = threading.Event()
    release = threading.Event()

    def hold():
        with bus.session():
            holding.set()
            release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holding.wait(1)
        start = time.perf_counter()
        with pytest.raises(DeviceTimeout, match="busy"), bus.session():
            pass
        assert time.perf_counter() - start < 1.0
    finally:
        release.set()
        thread.join()
        bus.close()


def test_own_port():
    bus = bus_device(port="loop://")
    bus.open()
    assert bus.is_open
    bus.close()
    assert not bus.is_open


def test_missing_own_port(monkeypatch, tmp_path):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")
    bus = bus_device(port=str(tmp_path / "ttyUSB7"))
    with pytest.raises(DeviceNotFound, match="serial port 'port' not found"):
        bus.open()


def test_find_bus():
    bus = bus_device(port="loop://")
    assert isinstance(find_bus("rel1", "b", {"b": bus}), ModbusRtuBus)
    other = create_device("x", DeviceConfig(driver="sim_relay"))
    with pytest.raises(ConfigError, match="device 'rel1': 'x' is not a modbus_rtu_bus"):
        find_bus("rel1", "x", {"x": other})
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/drivers/test_modbus_bus.py -q`
Expected: FAIL (`No module named 'hil.drivers.modbus_bus'`).

- [ ] **Step 3: Implementace `src/hil/drivers/modbus_bus.py`**

```python
"""Shared Modbus RTU bus of relay and input modules (driver ``modbus_rtu_bus``)."""

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Literal

import serial
from pydantic import Field, model_validator

from hil.comm.master import ModbusExceptionResponse, ModbusMaster
from hil.config.models import SerialParams
from hil.config.refs import Ref
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.drivers.serial_ports import (
    FtdiPort,
    ensure_low_latency,
    list_comports_once,
    resolve_port,
)
from hil.errors import ConfigError, DeviceError, DeviceTimeout
from hil.resources import SerialLink, port_settings

log = logging.getLogger("hil.drivers.modbus_bus")

# read timeout of the port; the master bounds the wait for a whole response
_READ_TIMEOUT_S = 0.01
# Quido answers 2 ms after a request at the earliest
_MIN_TURNAROUND_S = 0.002


class ModbusRtuBusConfig(DriverConfig):
    # own port (path, pyserial URL or FTDI chip) or a serial port of another device
    port: str | FtdiPort | None = None
    link: Ref | None = None
    baud: int = Field(default=9600, gt=0)
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    # how long the master waits for a response
    timeout_s: float = Field(default=0.2, gt=0)
    # silence between frames; default 3.5 characters, at least 2 ms
    min_gap_s: float | None = Field(default=None, ge=0)
    # how long an operation waits while another one uses the bus
    lock_timeout_s: float = Field(default=2.0, gt=0)
    # set the FTDI latency timer of an own port to 1 ms (Linux)
    low_latency: bool = True

    @model_validator(mode="after")
    def _one_port(self) -> "ModbusRtuBusConfig":
        if (self.port is None) == (self.link is None):
            raise ValueError("give exactly one of 'port' and 'link'")
        return self

    def params(self) -> SerialParams:
        return SerialParams(baud=self.baud, parity=self.parity, stopbits=self.stopbits)

    def gap_s(self) -> float:
        if self.min_gap_s is not None:
            return self.min_gap_s
        return max(3.5 * self.params().char_time_s(), _MIN_TURNAROUND_S)


@register_driver("modbus_rtu_bus")
class ModbusRtuBus(Device):
    """One RS-485 line with Modbus RTU modules; operations of all modules are serialized."""

    Config = ModbusRtuBusConfig
    config: ModbusRtuBusConfig

    def __init__(self, name: str, config: ModbusRtuBusConfig) -> None:
        super().__init__(name, config)
        self._link: SerialLink | None = None
        self._port: serial.Serial | None = None
        self._master: ModbusMaster | None = None

    def dependencies(self) -> list[str]:
        return [] if self.config.link is None else [self.config.link.device]

    def bind(self, devices: Mapping[str, Device]) -> None:
        ref = self.config.link
        if ref is None:
            return
        resource = devices[ref.device].resource(ref.channel)
        if not isinstance(resource, SerialLink):
            raise ConfigError(f"device {self.name!r}: link {ref} is not a serial port")
        self._link = resource

    @property
    def is_open(self) -> bool:
        return self._master is not None

    def open(self) -> None:
        port = self._open_port(self.config.params())
        self._port = port
        self._master = ModbusMaster(port, self.config.timeout_s, min_gap_s=self.config.gap_s())

    def _open_port(self, params: SerialParams) -> serial.Serial:
        if self.config.link is not None:
            if self._link is None:
                raise DeviceError(f"device {self.name!r}: link {self.config.link} is not bound")
            return self._link.open(params, timeout=_READ_TIMEOUT_S)
        spec = self.config.port
        if spec is None:
            raise ConfigError(f"device {self.name!r}: no port")
        device = resolve_port(self.name, "port", spec, list_comports_once(self.name))
        try:
            port = serial.serial_for_url(device, timeout=_READ_TIMEOUT_S, **port_settings(params))
        except (serial.SerialException, ValueError, OSError) as exc:
            raise DeviceError(f"device {self.name!r}: cannot open port {device}: {exc}") from exc
        if self.config.low_latency:
            ensure_low_latency(device)
        return port

    def close(self) -> None:
        # a stuck operation must not block closing for longer than the lock timeout
        acquired = self.lock.acquire(timeout=self.config.lock_timeout_s)
        try:
            port, self._port, self._master = self._port, None, None
        finally:
            if acquired:
                self.lock.release()
        if port is not None:
            try:
                port.close()
            except Exception as exc:
                log.warning("closing the port of %s failed: %s", self.name, exc)

    @contextmanager
    def session(self) -> Iterator[ModbusMaster]:
        """Exclusive use of the master for one or more exchanges."""
        if not self.lock.acquire(timeout=self.config.lock_timeout_s):
            raise DeviceTimeout(
                f"bus {self.name!r} is busy for more than {self.config.lock_timeout_s} s"
            )
        try:
            if self._master is None:
                raise DeviceError(f"device {self.name!r} is not open")
            yield self._master
        finally:
            self.lock.release()

    def call[T](self, owner: str, action: Callable[[ModbusMaster], T]) -> T:
        """Run ``action`` with the master; a Modbus exception becomes a ``DeviceError``."""
        try:
            with self.session() as master:
                return action(master)
        except ModbusExceptionResponse as exc:
            raise DeviceError(f"device {owner!r}: {exc}") from exc


def find_bus(owner: str, name: str, devices: Mapping[str, Device]) -> ModbusRtuBus:
    """The ``modbus_rtu_bus`` device ``name`` that the module ``owner`` is attached to."""
    bus = devices[name]
    if not isinstance(bus, ModbusRtuBus):
        raise ConfigError(f"device {owner!r}: {name!r} is not a modbus_rtu_bus")
    return bus
```

V `src/hil/drivers/__init__.py` importovat nový modul (pořadí importů nevadí, `modbus_bus` si `serial_ports` importuje sám):
```python
from hil.drivers import modbus_bus, serial_ports, sim
```
a doplnit `"modbus_bus"` do `__all__`.

- [ ] **Step 4: Spustit testy**

Run: `python -m pytest tests/drivers -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q`
```bash
git add src/hil/drivers tests/drivers
git commit -m "feat: ovladač sběrnice modbus_rtu_bus"
```

---

### Úkol 4: Moduly relé `waveshare_relay32` a `quido_rs_2_32`

**Files:**
- Create: `src/hil/drivers/modbus_relay.py`, `src/hil/drivers/waveshare_relay.py`, `src/hil/drivers/quido.py`, `tests/drivers/test_modbus_relay.py`
- Modify: `src/hil/drivers/__init__.py`

**Interfaces:**
- Consumes: `ModbusRtuBus.call`, `find_bus` (úkol 3), `RelayChannel`, `DigitalInput`, fixtures `bus`, `module` (úkol 3).
- Produces (pro úkoly 5, 11):
  - `ModbusRelayConfig`: `bus: str`, `address: int` (1–247), `channels=32` (1–256), `coil_base=0`, `write: Literal["multiple", "single"] = "multiple"`.
  - `ModbusRelayModule(Device)`: atributy `states: list[bool]` (povelový stav), `initial_states: list[bool] | None` (coily přečtené při `open`), `is_open`; metody `set_many(Mapping[int, bool])` (jedním rámcem FC15 přes rozsah od nejnižšího po nejvyšší měněné relé, nebo FC05 po jednom), `get(index)`, `read_back() -> list[bool]` (přečte coily z modulu), `safe_state()` (vše vypnout jedním rámcem). Kanály `"0"` až `"channels-1"`.
  - drivery `waveshare_relay32` (`WaveshareRelay32`) a `quido_rs_2_32` (`QuidoRs232`, navíc `input_base=0`, kanály `in0`, `in1` jako `DigitalInput`, metoda `read(index) -> bool`).
  - `open()` modulu, který neodpovídá: `DeviceNotFound("device '<jméno>': no answer from address <a> on bus '<sběrnice>': ...")`.

- [ ] **Step 1: Napsat padající testy**

`tests/drivers/test_modbus_relay.py`:
```python
import pytest

from hil.comm import modbus
from hil.comm.slave import ModbusDataStore
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError, DeviceNotFound
from hil.resources import DigitalInput, RelayChannel


def coils(count=32, base=0, on=()):
    return {base + i: i in on for i in range(count)}


@pytest.fixture
def make_module(bus):
    def make(driver="waveshare_relay32", name="rel1", **options):
        options.setdefault("address", 1)
        device = create_device(name, DeviceConfig(driver=driver, bus="relay_bus", **options))
        device.bind({"relay_bus": bus})
        return device

    return make


def test_open_reads_initial_state(make_module, module):
    module(1, ModbusDataStore(coils=coils(on={3})))
    rel = make_module()
    rel.open()
    assert rel.initial_states[3] is True
    assert rel.states == rel.initial_states
    assert rel.get(3) is True


def test_set_many_is_one_frame(make_module, module):
    store = ModbusDataStore(coils=coils())
    slave = module(1, store)
    rel = make_module()
    rel.open()
    rel.set_many({2: True, 5: True})
    assert slave.requests[-1] == modbus.write_coils_request(1, 2, [True, False, False, True])
    assert [store.coils[i] for i in range(7)] == [False, False, True, False, False, True, False]
    assert rel.get(5) is True


def test_relay_channel(make_module, module):
    store = ModbusDataStore(coils=coils())
    module(1, store)
    rel = make_module()
    rel.open()
    channel = rel.resource("7")
    assert isinstance(channel, RelayChannel)
    channel.set(True)
    assert store.coils[7] is True
    assert channel.get() is True
    assert rel.read_back()[7] is True


def test_coil_base_and_single_writes(make_module, module):
    slave = module(1, ModbusDataStore(coils=coils(base=100)))
    rel = make_module(coil_base=100, write="single")
    rel.open()
    rel.set_many({1: True, 0: True})
    assert slave.requests[-2:] == [
        modbus.write_coil_request(1, 100, True),
        modbus.write_coil_request(1, 101, True),
    ]


def test_safe_state_switches_all_off_in_one_frame(make_module, module):
    store = ModbusDataStore(coils=coils(on=set(range(32))))
    slave = module(1, store)
    rel = make_module()
    rel.open()
    rel.safe_state()
    assert slave.requests[-1] == modbus.write_coils_request(1, 0, [False] * 32)
    assert not any(store.coils.values())


def test_missing_module_is_device_not_found(make_module):
    rel = make_module(address=9)
    with pytest.raises(DeviceNotFound, match="no answer from address 9 on bus 'relay_bus'"):
        rel.open()


def test_wrong_coil_map_is_device_error(make_module, module):
    module(1, ModbusDataStore(coils=coils(count=8)))
    with pytest.raises(DeviceError, match="illegal data address"):
        make_module().open()


def test_requires_open_and_valid_index(make_module):
    rel = make_module()
    with pytest.raises(DeviceError, match="not open"):
        rel.set_many({0: True})
    with pytest.raises(DeviceError, match="has no relay 32"):
        rel.set_many({32: True})


def test_bus_must_be_modbus_bus():
    rel = create_device("rel1", DeviceConfig(driver="waveshare_relay32", bus="x", address=1))
    assert rel.dependencies() == ["x"]
    other = create_device("x", DeviceConfig(driver="sim_relay"))
    with pytest.raises(ConfigError, match="'x' is not a modbus_rtu_bus"):
        rel.bind({"x": other})


def test_waveshare_and_quido_on_one_bus(make_module, module):
    waveshare = ModbusDataStore(coils=coils())
    quido = ModbusDataStore(coils=coils(), discrete_inputs={0: True, 1: False})
    module(1, waveshare, port="m1")
    module(2, quido, port="m2")
    rel1 = make_module()
    rel2 = make_module("quido_rs_2_32", name="rel2", address=2)
    rel1.open()
    rel2.open()
    rel1.set_many({0: True})
    rel2.set_many({31: True})
    assert waveshare.coils[0] is True and quido.coils[31] is True
    assert {"0", "31", "in0", "in1"} <= set(rel2.channel_names())
    in0 = rel2.resource("in0")
    assert isinstance(in0, DigitalInput)
    assert in0.read() is True
    assert rel2.resource("in1").read() is False


def test_quido_input_base(make_module, module):
    module(2, ModbusDataStore(coils=coils(), discrete_inputs={10: False, 11: True}))
    rel2 = make_module("quido_rs_2_32", name="rel2", address=2, input_base=10)
    rel2.open()
    assert rel2.read(1) is True
    with pytest.raises(DeviceError, match="has no input 2"):
        rel2.read(2)
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/drivers/test_modbus_relay.py -q`
Expected: FAIL (`unknown driver 'waveshare_relay32'`).

- [ ] **Step 3: Implementace**

`src/hil/drivers/modbus_relay.py`:
```python
"""Relay modules on a Modbus RTU bus: common part of the Waveshare and Quido drivers."""

from collections.abc import Collection, Mapping
from typing import Literal

from pydantic import Field

from hil.comm.master import ModbusMaster
from hil.drivers.base import Device, DriverConfig
from hil.drivers.modbus_bus import ModbusRtuBus, find_bus
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import RelayChannel


class ModbusRelayConfig(DriverConfig):
    bus: str
    address: int = Field(ge=1, le=247)
    channels: int = Field(default=32, ge=1, le=256)
    # Modbus address of the coil of relay 0; relay i is coil coil_base + i
    coil_base: int = Field(default=0, ge=0, le=0xFFFF)
    # multiple: one frame per operation (function 15); single: a frame per relay (function 5)
    write: Literal["multiple", "single"] = "multiple"


class ModbusRelayModule(Device):
    """Relays mapped to consecutive coils of one module; the commanded state is kept here.

    One frame of function 15 writes the range from the lowest to the highest changed
    relay; relays in between are written with their commanded state.
    """

    Config = ModbusRelayConfig
    config: ModbusRelayConfig

    def __init__(self, name: str, config: ModbusRelayConfig) -> None:
        super().__init__(name, config)
        self.states = [False] * config.channels
        # coils read when the device was opened (the relay state after power-up)
        self.initial_states: list[bool] | None = None
        self.is_open = False
        self._bus: ModbusRtuBus | None = None
        self._relays = frozenset(str(i) for i in range(config.channels))

    def dependencies(self) -> list[str]:
        return [self.config.bus]

    def bind(self, devices: Mapping[str, Device]) -> None:
        self._bus = find_bus(self.name, self.config.bus, devices)

    def channel_names(self) -> Collection[str]:
        return self._relays

    def resource(self, channel: str) -> object:
        if channel not in self._relays:
            self._no_channel(channel)
        return RelayChannel(self, int(channel))

    def _bus_or_fail(self) -> ModbusRtuBus:
        if self._bus is None:
            raise DeviceError(f"device {self.name!r} is not bound to bus {self.config.bus!r}")
        return self._bus

    def _read_coils(self, master: ModbusMaster) -> list[bool]:
        return master.read_coils(self.config.address, self.config.coil_base, self.config.channels)

    def open(self) -> None:
        bus = self._bus_or_fail()
        try:
            states = bus.call(self.name, self._read_coils)
        except DeviceTimeout as exc:
            raise DeviceNotFound(
                f"device {self.name!r}: no answer from address {self.config.address} "
                f"on bus {self.config.bus!r}: {exc}"
            ) from exc
        with self.lock:
            self.initial_states = list(states)
            self.states = list(states)
            self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def safe_state(self) -> None:
        if self.is_open:
            self.set_many(dict.fromkeys(range(self.config.channels), False))

    def set_many(self, states: Mapping[int, bool]) -> None:
        for index in states:
            if not 0 <= index < self.config.channels:
                raise DeviceError(f"device {self.name!r} has no relay {index}")
        if not states:
            return
        with self.lock:
            if not self.is_open:
                raise DeviceError(f"device {self.name!r} is not open")
            new = list(self.states)
            for index, on in states.items():
                new[index] = on
            address, base = self.config.address, self.config.coil_base
            if self.config.write == "multiple":
                low, high = min(states), max(states)
                values = new[low : high + 1]
                self._bus_or_fail().call(
                    self.name, lambda m: m.write_coils(address, base + low, values)
                )
            else:

                def write_each(master: ModbusMaster) -> None:
                    for index, on in sorted(states.items()):
                        master.write_coil(address, base + index, on)

                self._bus_or_fail().call(self.name, write_each)
            self.states = new

    def get(self, index: int) -> bool:
        with self.lock:
            return self.states[index]

    def read_back(self) -> list[bool]:
        """Coil states as reported by the module (for hardware checks of the coil map)."""
        return self._bus_or_fail().call(self.name, self._read_coils)
```

`src/hil/drivers/waveshare_relay.py`:
```python
"""Waveshare Modbus RTU Relay 32-ch (driver ``waveshare_relay32``).

Relay i is coil i, written with function 15 and read with function 1, as the vendor
documents it. The map is not verified on hardware yet; ``coil_base`` and ``write`` in
the station file adapt it without a code change.
"""

from hil.drivers.modbus_relay import ModbusRelayModule
from hil.drivers.registry import register_driver


@register_driver("waveshare_relay32")
class WaveshareRelay32(ModbusRelayModule):
    """32 relays, each with one NO and one NC contact."""
```

`src/hil/drivers/quido.py`:
```python
"""Papouch Quido RS 2/32 (driver ``quido_rs_2_32``).

The module must be switched from its default Spinel protocol to Modbus RTU. Relays are
coils 0 to 31 and the two inputs discrete inputs 0 and 1 by default; the map is not
verified on hardware yet (``coil_base``, ``input_base``).
"""

from collections.abc import Collection

from pydantic import Field

from hil.drivers.modbus_relay import ModbusRelayConfig, ModbusRelayModule
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import DigitalInput

INPUTS = ("in0", "in1")


class QuidoConfig(ModbusRelayConfig):
    # Modbus address of the discrete input of input in0
    input_base: int = Field(default=0, ge=0, le=0xFFFF)


@register_driver("quido_rs_2_32")
class QuidoRs232(ModbusRelayModule):
    """32 changeover relays and 2 isolated inputs."""

    Config = QuidoConfig
    config: QuidoConfig

    def channel_names(self) -> Collection[str]:
        return self._relays | frozenset(INPUTS)

    def resource(self, channel: str) -> object:
        if channel in INPUTS:
            return DigitalInput(self, INPUTS.index(channel))
        return super().resource(channel)

    def read(self, index: int) -> bool:
        if not 0 <= index < len(INPUTS):
            raise DeviceError(f"device {self.name!r} has no input {index}")
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")
        address, start = self.config.address, self.config.input_base + index
        bits = self._bus_or_fail().call(
            self.name, lambda m: m.read_discrete_inputs(address, start, 1)
        )
        return bits[0]
```

V `src/hil/drivers/__init__.py`:
```python
from hil.drivers import modbus_bus, quido, serial_ports, sim, waveshare_relay
```
a doplnit `"quido"`, `"waveshare_relay"` do `__all__` (abecedně).

- [ ] **Step 4: Spustit testy**

Run: `python -m pytest tests/drivers -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q`
```bash
git add src/hil/drivers tests/drivers
git commit -m "feat: ovladače modulů relé Waveshare 32-ch a Papouch Quido RS 2/32"
```

---

### Úkol 5: Modul vstupů `modbus_di` a stanoviště nad Modbus moduly

**Files:**
- Create: `src/hil/drivers/modbus_di.py`, `tests/drivers/test_modbus_di.py`, `tests/test_station_modbus.py`
- Modify: `src/hil/drivers/__init__.py`

**Interfaces:**
- Consumes: `find_bus`, `ModbusRtuBus.call` (úkol 3), `WaveshareRelay32` (úkol 4), `SimSerial` (plán 2), fixtures `bus`, `module`.
- Produces:
  - driver `modbus_di` (`ModbusDi`), konfigurace `bus`, `address`, `count` (1–256), `source: Literal["discrete_inputs", "input_registers"] = "discrete_inputs"`, `start=0`, `invert=False`; metody `read_all() -> list[bool]` (jeden požadavek), `read(index) -> bool`; kanály `"0"` až `"count-1"` jako `DigitalInput`.
  - testovací driver `test_modbus_line` v `tests/test_station_modbus.py` (sim_serial, který na portech `m1` a `m2` spustí simulované moduly).

- [ ] **Step 1: Napsat padající testy**

`tests/drivers/test_modbus_di.py`:
```python
import pytest

from hil.comm import modbus
from hil.comm.slave import ModbusDataStore
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import DigitalInput


@pytest.fixture
def make_di(bus):
    def make(**options):
        options.setdefault("address", 5)
        options.setdefault("count", 8)
        device = create_device("di1", DeviceConfig(driver="modbus_di", bus="relay_bus", **options))
        device.bind({"relay_bus": bus})
        return device

    return make


def test_discrete_inputs_in_one_request(make_di, module):
    slave = module(5, ModbusDataStore(discrete_inputs={i: i in (1, 6) for i in range(8)}))
    di = make_di()
    di.open()
    count = len(slave.requests)
    assert di.read_all() == [False, True, False, False, False, False, True, False]
    assert slave.requests[count:] == [modbus.read_request(5, 2, 0, 8)]
    channel = di.resource("6")
    assert isinstance(channel, DigitalInput)
    assert channel.read() is True


def test_invert_and_start(make_di, module):
    module(5, ModbusDataStore(discrete_inputs={10 + i: i == 0 for i in range(4)}))
    di = make_di(count=4, start=10, invert=True)
    di.open()
    assert di.read_all() == [False, True, True, True]


def test_input_registers_hold_16_inputs_each(make_di, module):
    slave = module(5, ModbusDataStore(input_registers={0: 0b1000_0000_0000_0001, 1: 0b1}))
    di = make_di(count=20, source="input_registers")
    di.open()
    inputs = di.read_all()
    assert [i for i, on in enumerate(inputs) if on] == [0, 15, 16]
    assert slave.requests[-1] == modbus.read_request(5, 4, 0, 2)


def test_missing_input_module(make_di):
    with pytest.raises(DeviceNotFound, match="no answer from address 5 on bus 'relay_bus'"):
        make_di().open()


def test_read_requires_open(make_di):
    with pytest.raises(DeviceError, match="not open"):
        make_di().read(0)
```

`tests/test_station_modbus.py`:
```python
"""A station on Modbus modules, with the modules simulated on the RS-485 line."""

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import SerialParams
from hil.drivers import register_driver
from hil.drivers.sim.serial_port import SimSerial
from hil.station import Station

BAUD = 115200


@register_driver("test_modbus_line")
class _ModbusLine(SimSerial):
    """sim_serial whose port m1 answers as relay module 1 and port m2 as input module 5."""

    def open(self):
        super().open()
        self.stores = {
            1: ModbusDataStore(coils={i: False for i in range(32)}),
            5: ModbusDataStore(discrete_inputs={i: False for i in range(8)}),
        }
        self._sides = [self.endpoint(p, SerialParams(baud=BAUD)) for p in ("m1", "m2")]
        self.slaves = [
            ModbusSlave(side, address, self.stores[address])
            for side, address in zip(self._sides, (1, 5), strict=True)
        ]
        for slave in self.slaves:
            slave.start()

    def close(self):
        for slave in getattr(self, "slaves", []):
            slave.stop()
        for side in getattr(self, "_sides", []):
            side.close()
        super().close()


STATION = f"""
name: modbus
profile: standard-v1
devices:
  line: {{driver: test_modbus_line, buses: {{relay: [bus, m1, m2]}}}}
  relay_bus: {{driver: modbus_rtu_bus, link: line.bus, baud: {BAUD}}}
  rel1: {{driver: waveshare_relay32, bus: relay_bus, address: 1}}
  di1: {{driver: modbus_di, bus: relay_bus, address: 5, count: 8}}
terminals:
  PWR: {{kind: power, relays: [rel1.0, rel1.1]}}
  X1.1: {{kind: switch, relay: rel1.2}}
  X2.1: {{kind: sense, input: di1.0}}
"""


@pytest.fixture
def station(tmp_path):
    path = tmp_path / "station.yaml"
    path.write_text(STATION, encoding="utf-8")
    with Station.from_files(path) as station:
        yield station


def test_power_and_sense_over_modbus(station):
    coils = station.devices["line"].stores[1].coils
    inputs = station.devices["line"].stores[5].discrete_inputs
    station.power.on("PWR")
    assert coils[0] and coils[1]
    station.digital.set("X1.1", True)
    assert coils[2]
    inputs[0] = True
    assert station.digital.read("X2.1") is True
    station.safe_state()
    assert not any(coils.values())


def test_open_order_puts_the_bus_first(station):
    order = station._order
    assert order.index("line") < order.index("relay_bus") < order.index("rel1")
    assert order.index("relay_bus") < order.index("di1")
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/drivers/test_modbus_di.py tests/test_station_modbus.py -q`
Expected: FAIL (`unknown driver 'modbus_di'`).

- [ ] **Step 3: Implementace `src/hil/drivers/modbus_di.py`**

```python
"""Generic Modbus RTU digital input module (driver ``modbus_di``)."""

from collections.abc import Collection, Mapping
from typing import Literal

from pydantic import Field

from hil.comm.master import ModbusMaster
from hil.drivers.base import Device, DriverConfig
from hil.drivers.modbus_bus import ModbusRtuBus, find_bus
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import DigitalInput


class ModbusDiConfig(DriverConfig):
    bus: str
    address: int = Field(ge=1, le=247)
    count: int = Field(ge=1, le=256)
    # discrete_inputs: function 2, one input per bit; input_registers: function 4,
    # 16 inputs per register starting with its lowest bit
    source: Literal["discrete_inputs", "input_registers"] = "discrete_inputs"
    # Modbus address of the first discrete input or register
    start: int = Field(default=0, ge=0, le=0xFFFF)
    # True: an input reads True when the module reports 0
    invert: bool = False


@register_driver("modbus_di")
class ModbusDi(Device):
    """Inputs of one module; all of them are read with one request."""

    Config = ModbusDiConfig
    config: ModbusDiConfig

    def __init__(self, name: str, config: ModbusDiConfig) -> None:
        super().__init__(name, config)
        self.is_open = False
        self._bus: ModbusRtuBus | None = None
        self._channels = frozenset(str(i) for i in range(config.count))

    def dependencies(self) -> list[str]:
        return [self.config.bus]

    def bind(self, devices: Mapping[str, Device]) -> None:
        self._bus = find_bus(self.name, self.config.bus, devices)

    def channel_names(self) -> Collection[str]:
        return self._channels

    def resource(self, channel: str) -> DigitalInput:
        if channel not in self._channels:
            self._no_channel(channel)
        return DigitalInput(self, int(channel))

    def _read(self, master: ModbusMaster) -> list[bool]:
        cfg = self.config
        if cfg.source == "discrete_inputs":
            bits = master.read_discrete_inputs(cfg.address, cfg.start, cfg.count)
        else:
            registers = master.read_input_registers(cfg.address, cfg.start, (cfg.count + 15) // 16)
            bits = [bool(registers[i // 16] >> (i % 16) & 1) for i in range(cfg.count)]
        return [bit != cfg.invert for bit in bits]

    def _call(self) -> list[bool]:
        if self._bus is None:
            raise DeviceError(f"device {self.name!r} is not bound to bus {self.config.bus!r}")
        return self._bus.call(self.name, self._read)

    def open(self) -> None:
        try:
            self._call()
        except DeviceTimeout as exc:
            raise DeviceNotFound(
                f"device {self.name!r}: no answer from address {self.config.address} "
                f"on bus {self.config.bus!r}: {exc}"
            ) from exc
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def read_all(self) -> list[bool]:
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")
        return self._call()

    def read(self, index: int) -> bool:
        return self.read_all()[index]
```

V `src/hil/drivers/__init__.py` doplnit import a `__all__` o `modbus_di`.

- [ ] **Step 4: Spustit testy**

Run: `python -m pytest tests/drivers tests/test_station_modbus.py -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q`
```bash
git add src/hil/drivers tests/drivers tests/test_station_modbus.py
git commit -m "feat: ovladač modulu digitálních vstupů modbus_di"
```

---

### Úkol 6: Ladicí řetězec – `DebugProbe`, `sim_probe`, `DebugSignal`, `DebugBlock`

**Files:**
- Create: `src/hil/drivers/sim/probe.py`, `src/hil/signals/debug.py`, `src/hil/blocks/debug.py`, `examples/tests/test_debug_on_sim.py`, `tests/drivers/test_sim_probe.py`, `tests/signals/test_debug.py`
- Modify: `src/hil/resources.py`, `src/hil/config/models.py`, `src/hil/drivers/sim/__init__.py`, `src/hil/signals/__init__.py`, `src/hil/blocks/__init__.py`, `src/hil/station.py`, `src/hil/dut.py`, `src/hil/cli.py`, `src/hil/stations/sim.yaml`, `examples/dut.yaml`
- Test: `tests/config/test_models.py`, `tests/config/test_loader.py`, `tests/test_station.py`, `tests/test_dut.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Signal`, `Recorder.write_line`, `lookup`, `DebugTerminal` (plán 1), `signal_params`, `PARAM_MODELS`.
- Produces (pro úkoly 7, 11):
  - `hil.config.models`: `DEFAULT_DEBUG_TIMEOUT_S = 120.0`, `DebugParams` (`target: str` povinný, `timeout_s=120.0`), `PARAM_MODELS["debug"] = DebugParams`.
  - `hil.resources`: `ProbeResult(action: str, output: str, returncode: int | None, duration_s: float, interrupted: bool = False, timed_out: bool = False)` s vlastností `ok`; protokol `DebugProbe` (`runtime_checkable`): `name`, `flash(image: Path, target: str, timeout_s: float, abort_after_s: float | None = None) -> ProbeResult`, `reset(target: str, timeout_s: float) -> ProbeResult`, `halt(target: str, timeout_s: float) -> ProbeResult`. Probe chyby nástroje nevyhazuje, vrací je v `ProbeResult`; vyhazuje jen `DeviceError` (není otevřený), `DeviceNotFound` (program chybí).
  - driver `sim_probe` (`SimProbe`): konfigurace `flash_s=0.05`; atributy `calls: list[tuple[float, str, str, str | None]]` (čas, akce, target, obraz), `returncode: int = 0`, `fail_with: Exception | None`, `is_open`.
  - `DebugSignal(name, recorder, probe)`: `configure(alias, params: DebugParams)`, `params`, `alias`, `flash(image, target=None) -> ProbeResult`, `flash_interrupted(image, after_s, target=None) -> ProbeResult`, `reset(target=None)`, `halt(target=None)`. Výstup zapisuje do `openocd.log`, chybu převádí na `DeviceError` / `DeviceTimeout`.
  - `DebugBlock(signals, profile_terminals=None)`: `__getitem__(name) -> DebugSignal`, `flash(name, image, target)`, `reset(name, target)`; `Station.debug`.
  - Vestavěné stanoviště `sim` má zařízení `probe` (`sim_probe`) a svorku `SWD`; `examples/dut.yaml` má signál `firmware`.

- [ ] **Step 1: Napsat padající testy**

Na konec `tests/config/test_models.py` (do importu z `hil.config.models` přidat `DebugParams`):
```python
def test_debug_params():
    params = signal_params("debug", {"target": "target/stm32g4x.cfg"})
    assert params == DebugParams(target="target/stm32g4x.cfg", timeout_s=120.0)
    with pytest.raises(ValidationError):
        signal_params("debug", {})
    with pytest.raises(ValidationError):
        signal_params("debug", {"target": "t.cfg", "speed": 4000})
```

Na konec `tests/config/test_loader.py`:
```python
def test_dut_debug_signal_needs_target(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  firmware: {terminal: SWD}\n"
    with pytest.raises(ConfigError, match=r"signal 'firmware': target: Field required"):
        load_dut(write(tmp_path, "dut.yaml", text), profile)
```

`tests/drivers/test_sim_probe.py`:
```python
from pathlib import Path

import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError
from hil.resources import DebugProbe


@pytest.fixture
def probe():
    device = create_device("probe", DeviceConfig(driver="sim_probe", flash_s=0.05))
    device.open()
    yield device
    device.close()


def test_is_debug_probe(probe):
    assert isinstance(probe, DebugProbe)


def test_flash_records_call(probe):
    result = probe.flash(Path("fw.bin"), "t.cfg", timeout_s=1)
    assert result.ok and result.action == "flash"
    assert result.duration_s >= 0.04
    assert probe.calls[-1][1:] == ("flash", "t.cfg", "fw.bin")


def test_abort_and_timeout(probe):
    aborted = probe.flash(Path("fw.bin"), "t.cfg", timeout_s=1, abort_after_s=0.01)
    assert aborted.interrupted and not aborted.timed_out and aborted.returncode is None
    timed_out = probe.flash(Path("fw.bin"), "t.cfg", timeout_s=0.01)
    assert timed_out.timed_out and not timed_out.interrupted


def test_failure_and_closed(probe):
    probe.returncode = 3
    assert probe.reset("t.cfg", timeout_s=1).returncode == 3
    probe.fail_with = DeviceError("probe unplugged")
    with pytest.raises(DeviceError, match="unplugged"):
        probe.halt("t.cfg", timeout_s=1)
    probe.close()
    probe.fail_with = None
    with pytest.raises(DeviceError, match="not open"):
        probe.reset("t.cfg", timeout_s=1)
```

`tests/signals/test_debug.py`:
```python
import json

import pytest

from hil.config.models import DebugParams, DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceTimeout, OperationNotAllowed
from hil.recording import Recorder
from hil.signals import DebugSignal

TARGET = "target/stm32g4x.cfg"


@pytest.fixture
def probe():
    device = create_device("probe", DeviceConfig(driver="sim_probe", flash_s=0.05))
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
def swd(probe, recorder):
    signal = DebugSignal("SWD", recorder, probe)
    signal.configure("firmware", DebugParams(target=TARGET))
    return signal


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "fw.bin"
    path.write_bytes(b"\x01\x02")
    return path


def test_flash(swd, probe, image, tmp_path):
    result = swd.flash(image)
    assert result.ok and not result.interrupted
    assert probe.calls[-1][1:] == ("flash", TARGET, str(image))
    log = (tmp_path / "openocd.log").read_text(encoding="utf-8")
    assert "--- firmware: flash" in log
    assert "sim_probe flash" in log
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])
    assert (event["source"], event["action"], event["returncode"]) == ("SWD", "flash", 0)


def test_flash_interrupted(swd, image):
    result = swd.flash_interrupted(image, after_s=0.01)
    assert result.interrupted and result.returncode is None


def test_flash_interrupted_after_finish(swd, image):
    result = swd.flash_interrupted(image, after_s=1.0)
    assert result.ok and not result.interrupted


def test_reset_and_halt(swd, probe):
    swd.reset()
    swd.halt()
    assert [call[1] for call in probe.calls] == ["reset", "halt"]


def test_failure_is_device_error_with_log(swd, probe, image, tmp_path):
    probe.returncode = 1
    with pytest.raises(DeviceError, match="flash failed with exit code 1"):
        swd.flash(image)
    assert "sim_probe flash" in (tmp_path / "openocd.log").read_text(encoding="utf-8")


def test_timeout(probe, recorder, image):
    signal = DebugSignal("SWD", recorder, probe)
    signal.configure("firmware", DebugParams(target=TARGET, timeout_s=0.01))
    with pytest.raises(DeviceTimeout, match="did not finish"):
        signal.flash(image)


def test_missing_image(swd, tmp_path):
    with pytest.raises(FileNotFoundError, match="firmware image"):
        swd.flash(tmp_path / "missing.bin")


def test_target_needed(probe, recorder, image):
    signal = DebugSignal("SWD", recorder, probe)
    with pytest.raises(OperationNotAllowed, match="no debug target"):
        signal.flash(image)
    assert signal.flash(image, target="t.cfg").ok


def test_invalid_interrupt_time(swd, image):
    with pytest.raises(ValueError, match="after_s"):
        swd.flash_interrupted(image, after_s=0)
```

Na konec `tests/test_station.py`:
```python
def test_debug_terminal_needs_a_probe(tmp_path):
    with pytest.raises(ConfigError, match="device 'rel1' is not a debug probe"):
        make(tmp_path, STATION + "  SWD: {kind: debug, probe: rel1}\n")


def test_debug_block(tmp_path):
    text = STATION.replace("terminals:\n", "  probe: {driver: sim_probe}\nterminals:\n")
    with make(tmp_path, text + "  SWD: {kind: debug, probe: probe}\n") as station:
        assert station.debug.reset("SWD", "t.cfg").ok
        assert station.devices["probe"].calls[-1][1] == "reset"
        with pytest.raises(ConfigError, match="'PWR' is a power terminal, not a debug"):
            station.debug["PWR"]
```

Na konec `tests/test_dut.py` (do importů přidat `from hil.config.models import DebugParams`):
```python
def test_debug_signal_gets_target(tmp_path):
    path = tmp_path / "dut.yaml"
    path.write_text(
        "dut: d\nprofile: standard-v1\nsignals:\n"
        "  firmware: {terminal: SWD, target: target/stm32g4x.cfg, timeout_s: 30}\n",
        encoding="utf-8",
    )
    with Station.from_files("sim") as station:
        device = Dut(load_dut(path, station.profile), station)
        assert device.firmware.params == DebugParams(target="target/stm32g4x.cfg", timeout_s=30)
        assert device.firmware.alias == "firmware"
```

V `tests/test_cli.py` upravit očekávání v `test_check_with_dut_and_probe` a `test_info`:
```python
    assert "DUT 'example': 10 signals OK" in out
    assert "all 4 devices opened" in out
```
```python
    assert re.search(r"SWD\s+debug\s+wired", out)
    assert re.search(r"debug\s+SWD", out)
```

`examples/tests/test_debug_on_sim.py`:
```python
"""Debug probe examples on the built-in simulated station.

On a real station the image is the build output of the DUT firmware and the probe is
OpenOCD with an ST-Link.

    python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
"""


def test_flash_and_reset(dut, hil, tmp_path):
    image = tmp_path / "firmware.bin"
    image.write_bytes(bytes(1024))
    assert dut.firmware.flash(image).ok
    dut.firmware.reset()
    actions = [call[1] for call in hil.devices["probe"].calls]
    assert actions[-2:] == ["flash", "reset"]


def test_interrupted_update(dut, tmp_path):
    image = tmp_path / "firmware.bin"
    image.write_bytes(bytes(1024))
    assert dut.firmware.flash_interrupted(image, after_s=0.01).interrupted
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests -q -x`
Expected: FAIL (`cannot import name 'DebugParams'`).

- [ ] **Step 3: Parametry signálu a prostředek**

V `src/hil/config/models.py` přidat `"DebugParams"` do `__all__`, za `SerialParams` přidat:
```python
DEFAULT_DEBUG_TIMEOUT_S = 120.0


class DebugParams(_Strict):
    """Parameters of a ``debug`` DUT signal."""

    # OpenOCD target configuration, e.g. target/stm32g4x.cfg
    target: str = Field(min_length=1)
    # longest duration of one probe operation (flashing a large image takes tens of seconds)
    timeout_s: float = Field(default=DEFAULT_DEBUG_TIMEOUT_S, gt=0)
```
a `PARAM_MODELS` rozšířit o `"debug": DebugParams`.

Na konec `src/hil/resources.py` (importy `from pathlib import Path` a `from typing import Any, Protocol, runtime_checkable`):
```python
@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one operation of a debug probe (e.g. one OpenOCD run)."""

    action: str
    output: str
    # exit code of the tool; None when it was stopped (interrupted or timed out)
    returncode: int | None
    duration_s: float
    interrupted: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@runtime_checkable
class DebugProbe(Protocol):
    """A device that flashes and controls the microcontroller of the DUT.

    Failures of the tool are returned in ``ProbeResult``, so that its output can be
    saved; only a missing tool or a closed device raise.
    """

    name: str

    def flash(
        self, image: Path, target: str, timeout_s: float, abort_after_s: float | None = None
    ) -> ProbeResult: ...

    def reset(self, target: str, timeout_s: float) -> ProbeResult: ...

    def halt(self, target: str, timeout_s: float) -> ProbeResult: ...
```

- [ ] **Step 4: Ovladač `sim_probe`**

`src/hil/drivers/sim/probe.py`:
```python
"""Simulated debug probe (driver ``sim_probe``)."""

import time
from pathlib import Path

from pydantic import Field

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import ProbeResult


class SimProbeConfig(DriverConfig):
    # how long a simulated flashing takes
    flash_s: float = Field(default=0.05, ge=0)


@register_driver("sim_probe")
class SimProbe(Device):
    """Records flash, reset and halt; ``returncode`` and ``fail_with`` simulate failures."""

    Config = SimProbeConfig
    config: SimProbeConfig

    def __init__(self, name: str, config: SimProbeConfig) -> None:
        super().__init__(name, config)
        # (time, action, target, image)
        self.calls: list[tuple[float, str, str, str | None]] = []
        self.returncode = 0
        self.fail_with: Exception | None = None
        self.is_open = False

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def _run(
        self,
        action: str,
        target: str,
        image: str | None,
        duration_s: float,
        timeout_s: float,
        abort_after_s: float | None,
    ) -> ProbeResult:
        with self.lock:
            if self.fail_with is not None:
                raise self.fail_with
            if not self.is_open:
                raise DeviceError(f"device {self.name!r} is not open")
            start = clock.now()
            limit = timeout_s if abort_after_s is None else min(timeout_s, abort_after_s)
            stopped = duration_s > limit
            time.sleep(min(duration_s, limit))
            self.calls.append((start, action, target, image))
            interrupted = stopped and abort_after_s is not None and abort_after_s <= timeout_s
            output = f"sim_probe {action} target={target}"
            if image is not None:
                output += f" image={image}"
            return ProbeResult(
                action,
                output + "\n",
                None if stopped else self.returncode,
                clock.now() - start,
                interrupted=interrupted,
                timed_out=stopped and not interrupted,
            )

    def flash(
        self, image: Path, target: str, timeout_s: float, abort_after_s: float | None = None
    ) -> ProbeResult:
        return self._run("flash", target, str(image), self.config.flash_s, timeout_s, abort_after_s)

    def reset(self, target: str, timeout_s: float) -> ProbeResult:
        return self._run("reset", target, None, 0.0, timeout_s, None)

    def halt(self, target: str, timeout_s: float) -> ProbeResult:
        return self._run("halt", target, None, 0.0, timeout_s, None)
```

V `src/hil/drivers/sim/__init__.py` přidat `probe` do importu a `__all__`.

- [ ] **Step 5: Signál a blok**

`src/hil/signals/debug.py`:
```python
"""Debug terminal: flashing and control of the DUT's microcontroller (kind ``debug``)."""

from pathlib import Path

from hil.config.models import DEFAULT_DEBUG_TIMEOUT_S, DebugParams
from hil.errors import DeviceError, DeviceTimeout, OperationNotAllowed
from hil.recording import Recorder
from hil.resources import DebugProbe, ProbeResult
from hil.signals.base import Signal

LOG_FILE = "openocd.log"


class DebugSignal(Signal):
    """Debug probe of a terminal; the target comes from the DUT signal or from the call."""

    kind = "debug"

    def __init__(self, name: str, recorder: Recorder, probe: DebugProbe) -> None:
        super().__init__(name, recorder)
        self.probe = probe
        self.alias = name
        self.params: DebugParams | None = None

    def configure(self, alias: str, params: DebugParams) -> None:
        """Use the DUT signal name ``alias`` in the log and the DUT's target."""
        self.alias = alias
        self.params = params

    def flash(self, image: str | Path, target: str | None = None) -> ProbeResult:
        """Program ``image`` into the DUT, verify it and let the DUT run."""
        path = _image(image)
        target, timeout_s = self._settings(target)
        return self._finish(self.probe.flash(path, target, timeout_s), image=str(path))

    def flash_interrupted(
        self, image: str | Path, after_s: float, target: str | None = None
    ) -> ProbeResult:
        """Start flashing ``image`` and stop the probe after ``after_s`` seconds.

        ``interrupted`` of the result is False when flashing finished earlier.
        """
        if after_s <= 0:
            raise ValueError("after_s must be positive")
        path = _image(image)
        target, timeout_s = self._settings(target)
        result = self.probe.flash(path, target, timeout_s, abort_after_s=after_s)
        return self._finish(result, image=str(path), after_s=after_s)

    def reset(self, target: str | None = None) -> ProbeResult:
        """Reset the DUT and let it run."""
        target, timeout_s = self._settings(target)
        return self._finish(self.probe.reset(target, timeout_s))

    def halt(self, target: str | None = None) -> ProbeResult:
        """Stop the DUT's core."""
        target, timeout_s = self._settings(target)
        return self._finish(self.probe.halt(target, timeout_s))

    def _settings(self, target: str | None) -> tuple[str, float]:
        timeout_s = DEFAULT_DEBUG_TIMEOUT_S if self.params is None else self.params.timeout_s
        if target is not None:
            return target, timeout_s
        if self.params is None:
            raise OperationNotAllowed(
                f"{self.alias}: no debug target; set 'target' of the DUT signal or pass target="
            )
        return self.params.target, timeout_s

    def _finish(self, result: ProbeResult, **data: object) -> ProbeResult:
        self.recorder.write_line(LOG_FILE, f"--- {self.alias}: {result.action}")
        for line in result.output.splitlines():
            self.recorder.write_line(LOG_FILE, line)
        self._event(
            result.action,
            returncode=result.returncode,
            duration_s=round(result.duration_s, 3),
            interrupted=result.interrupted,
            **data,
        )
        if result.timed_out:
            raise DeviceTimeout(
                f"{self.alias}: {result.action} did not finish in time; output in {LOG_FILE}"
            )
        if not result.interrupted and result.returncode != 0:
            last = result.output.strip().splitlines()[-1:] or ["no output"]
            raise DeviceError(
                f"{self.alias}: {result.action} failed with exit code {result.returncode}: "
                f"{last[0]} (output in {LOG_FILE})"
            )
        return result

    def safe_state(self) -> None:
        """Nothing to do: every probe operation ends before its call returns."""


def _image(image: str | Path) -> Path:
    path = Path(image)
    if not path.is_file():
        raise FileNotFoundError(f"firmware image {path} not found")
    return path
```

V `src/hil/signals/__init__.py` přidat `from hil.signals.debug import DebugSignal` a `"DebugSignal"` do `__all__`.

`src/hil/blocks/debug.py`:
```python
"""Debug block: debug probes of the station."""

from collections.abc import Mapping
from pathlib import Path

from hil.blocks._lookup import lookup
from hil.resources import ProbeResult
from hil.signals import DebugSignal


class DebugBlock:
    """All debug terminals of a station; without a DUT file the target is passed explicitly."""

    def __init__(
        self,
        signals: Mapping[str, DebugSignal],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.signals = dict(signals)
        self._profile_terminals = profile_terminals

    def __getitem__(self, name: str) -> DebugSignal:
        return lookup(name, self.signals, "debug", self._profile_terminals)

    def flash(self, name: str, image: str | Path, target: str) -> ProbeResult:
        return self[name].flash(image, target)

    def reset(self, name: str, target: str) -> ProbeResult:
        return self[name].reset(target)
```

V `src/hil/blocks/__init__.py` přidat `DebugBlock` do importů a `__all__`.

- [ ] **Step 6: Stanoviště, DUT a CLI**

V `src/hil/station.py`:
- importy: `DebugBlock` z `hil.blocks`, `DebugTerminal` z `hil.config.models`, `DebugProbe` z `hil.resources`, `DebugSignal` z `hil.signals`;
- v `_build` před koncovým `kind = ...` přidat větev:
```python
            case DebugTerminal(probe=probe):
                device = self.devices[probe]
                if not isinstance(device, DebugProbe):
                    raise ConfigError(
                        f"{self.source}: terminal {name!r}: device {probe!r} is not a debug probe"
                    )
                return DebugSignal(name, rec, device)
```
- v `__init__` za `self.comm = ...` přidat `self.debug = DebugBlock(self._of(DebugSignal), terminals)`.

V `src/hil/dut.py` (importy `DebugParams` z `hil.config.models`, `DebugSignal` z `hil.signals`) rozšířit `signal`:
```python
        if isinstance(signal, PortSignal):
            params = signal_params(signal.kind, spec.params())
            if not isinstance(params, SerialParams):
                raise TypeError(f"no line parameters for {signal.kind} signal {name!r}")
            signal.configure(name, params)
        elif isinstance(signal, DebugSignal):
            debug = signal_params(signal.kind, spec.params())
            if not isinstance(debug, DebugParams):
                raise TypeError(f"no debug parameters for signal {name!r}")
            signal.configure(name, debug)
        return signal
```

V `src/hil/cli.py` (`_info`) doplnit do `blocks` položku `"debug": list(station.debug.signals)`.

`src/hil/stations/sim.yaml`: v hlavičkovém komentáři nahradit „(analog and debug terminals are not wired)“ textem „(analog terminals are not wired)“ a doplnit řádek „SWD is wired to the simulated probe ``probe``.“. Do `devices` přidat `  probe: {driver: sim_probe}`, do `terminals` přidat `  SWD: {kind: debug, probe: probe}`.

`examples/dut.yaml`: přidat signál
```yaml
  firmware: {terminal: SWD, target: target/stm32g4x.cfg}
```

- [ ] **Step 7: Spustit testy**

Run: `python -m pytest -q && python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
Expected: PASS. Pokud jiný existující test počítá svorky nebo zařízení stanoviště `sim`, upravit jeho očekávání o `probe` a `SWD`.

- [ ] **Step 8: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy`
```bash
git add src tests examples
git commit -m "feat: ladicí svorka debug se simulovanou sondou"
```

---

### Úkol 7: Ovladač `openocd`

**Files:**
- Create: `src/hil/drivers/openocd.py`, `tests/drivers/fake_openocd.py`, `tests/drivers/test_openocd.py`
- Modify: `src/hil/drivers/__init__.py`

**Interfaces:**
- Consumes: `ProbeResult`, `DebugProbe` (úkol 6).
- Produces (pro úkol 11):
  - driver `openocd` (`OpenOcd`), konfigurace `command: list[str] = ["openocd"]` (program a úvodní argumenty), `interface="interface/stlink.cfg"`, `adapter_serial: str | None`, `speed_khz: int | None`, `search: list[str]` (adresáře `-s`).
  - `OpenOcd.open()` najde program (`shutil.which`), jinak `DeviceNotFound("device '<jméno>': OpenOCD program '<program>' not found; ...")`.
  - `OpenOcd.arguments(target: str, commands: Sequence[str]) -> list[str]`: příkazová řádka jednoho běhu.
  - `flash` spustí `program {<cesta>} verify reset exit`, `reset` příkazy `init`, `reset run`, `shutdown`, `halt` příkazy `init`, `halt`, `shutdown`. Každá operace je jeden proces OpenOCD s timeoutem; `abort_after_s` proces ukončí dřív (přerušené flashování).

- [ ] **Step 1: Napsat falešný OpenOCD a padající testy**

`tests/drivers/fake_openocd.py`:
```python
"""Stand-in for the openocd program in driver tests.

Prints its arguments. When a -c command contains "fail" it ends with exit code 1; when
one contains "slow" it sleeps for 10 seconds first.
"""

import sys
import time

args = sys.argv[1:]
commands = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "-c"]
joined = " ".join(commands)
print("Open On-Chip Debugger (fake)", flush=True)
print("args: " + " | ".join(args), flush=True)
if "slow" in joined:
    time.sleep(10)
if "fail" in joined:
    print("Error: simulated failure", file=sys.stderr, flush=True)
    sys.exit(1)
print("** Programming Finished **" if "program" in joined else "done", flush=True)
```

`tests/drivers/test_openocd.py`:
```python
import sys
from pathlib import Path

import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import DebugProbe

FAKE = Path(__file__).with_name("fake_openocd.py")


def make(**options):
    options.setdefault("command", [sys.executable, str(FAKE)])
    return create_device("stlink", DeviceConfig(driver="openocd", **options))


@pytest.fixture
def ocd():
    device = make(adapter_serial="066DFF", speed_khz=4000)
    device.open()
    yield device
    device.close()


def test_is_debug_probe():
    assert isinstance(make(), DebugProbe)


def test_arguments(ocd):
    args = ocd.arguments("target/stm32g4x.cfg", ["init", "halt"])
    assert args[1:] == [
        str(FAKE),
        "-f",
        "interface/stlink.cfg",
        "-c",
        "adapter serial 066DFF",
        "-c",
        "adapter speed 4000",
        "-f",
        "target/stm32g4x.cfg",
        "-c",
        "init",
        "-c",
        "halt",
    ]


def test_search_directories():
    device = make(search=["/opt/ocd/scripts"])
    device.open()
    assert device.arguments("t.cfg", [])[2:4] == ["-s", "/opt/ocd/scripts"]


def test_flash(ocd, tmp_path):
    image = tmp_path / "my fw.bin"
    image.write_bytes(b"\0")
    result = ocd.flash(image, "target/stm32g4x.cfg", timeout_s=10)
    assert result.ok and result.action == "flash"
    assert f"program {{{image.resolve().as_posix()}}} verify reset exit" in result.output
    assert "Programming Finished" in result.output


def test_reset_and_halt(ocd):
    reset = ocd.reset("t.cfg", timeout_s=10)
    assert reset.ok and "init | -c | reset run | -c | shutdown" in reset.output
    assert ocd.halt("t.cfg", timeout_s=10).ok


def test_failure_is_returned_with_output():
    device = make(adapter_serial="fail")
    device.open()
    result = device.reset("t.cfg", timeout_s=10)
    assert result.returncode == 1
    assert "simulated failure" in result.output


def test_timeout_and_abort(tmp_path):
    device = make(adapter_serial="slow")
    device.open()
    timed_out = device.reset("t.cfg", timeout_s=0.5)
    assert timed_out.timed_out and timed_out.returncode is None
    assert timed_out.duration_s < 5
    image = tmp_path / "fw.bin"
    image.write_bytes(b"\0")
    aborted = device.flash(image, "t.cfg", timeout_s=10, abort_after_s=0.3)
    assert aborted.interrupted and not aborted.timed_out


def test_missing_program():
    with pytest.raises(DeviceNotFound, match="OpenOCD program 'no-such-openocd' not found"):
        make(command=["no-such-openocd"]).open()


def test_requires_open():
    with pytest.raises(DeviceError, match="not open"):
        make().reset("t.cfg", timeout_s=1)
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/drivers/test_openocd.py -q`
Expected: FAIL (`unknown driver 'openocd'`).

- [ ] **Step 3: Implementace `src/hil/drivers/openocd.py`**

```python
"""OpenOCD as the debug probe of the DUT (driver ``openocd``)."""

import logging
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import ProbeResult

log = logging.getLogger("hil.drivers.openocd")


class OpenOcdConfig(DriverConfig):
    # program and leading arguments; OpenOCD from PATH by default
    command: list[str] = Field(default_factory=lambda: ["openocd"], min_length=1)
    # adapter configuration (ST-Link V2 and V3)
    interface: str = "interface/stlink.cfg"
    # serial number of the adapter when more of them are connected
    adapter_serial: str | None = None
    # SWD clock; the target configuration's default when not given
    speed_khz: int | None = Field(default=None, gt=0)
    # extra directories with configuration scripts (-s)
    search: list[str] = Field(default_factory=list)


@register_driver("openocd")
class OpenOcd(Device):
    """Runs one OpenOCD process per operation and returns its output."""

    Config = OpenOcdConfig
    config: OpenOcdConfig

    def __init__(self, name: str, config: OpenOcdConfig) -> None:
        super().__init__(name, config)
        self._program: str | None = None

    @property
    def is_open(self) -> bool:
        return self._program is not None

    def open(self) -> None:
        program = self.config.command[0]
        found = shutil.which(program)
        if found is None:
            raise DeviceNotFound(
                f"device {self.name!r}: OpenOCD program {program!r} not found; "
                "install OpenOCD or set 'command'"
            )
        self._program = found

    def close(self) -> None:
        self._program = None

    def arguments(self, target: str, commands: Sequence[str]) -> list[str]:
        """Command line of one run: adapter, target and ``commands`` (each with -c)."""
        if self._program is None:
            raise DeviceError(f"device {self.name!r} is not open")
        cfg = self.config
        args = [self._program, *cfg.command[1:]]
        for directory in cfg.search:
            args += ["-s", directory]
        args += ["-f", cfg.interface]
        if cfg.adapter_serial is not None:
            args += ["-c", f"adapter serial {cfg.adapter_serial}"]
        if cfg.speed_khz is not None:
            args += ["-c", f"adapter speed {cfg.speed_khz}"]
        args += ["-f", target]
        for command in commands:
            args += ["-c", command]
        return args

    def flash(
        self, image: Path, target: str, timeout_s: float, abort_after_s: float | None = None
    ) -> ProbeResult:
        # braces keep a path with spaces one Tcl word; OpenOCD wants forward slashes
        program = f"program {{{image.resolve().as_posix()}}} verify reset exit"
        return self._run("flash", self.arguments(target, [program]), timeout_s, abort_after_s)

    def reset(self, target: str, timeout_s: float) -> ProbeResult:
        args = self.arguments(target, ["init", "reset run", "shutdown"])
        return self._run("reset", args, timeout_s, None)

    def halt(self, target: str, timeout_s: float) -> ProbeResult:
        args = self.arguments(target, ["init", "halt", "shutdown"])
        return self._run("halt", args, timeout_s, None)

    def _run(
        self, action: str, args: list[str], timeout_s: float, abort_after_s: float | None
    ) -> ProbeResult:
        limit = timeout_s if abort_after_s is None else min(timeout_s, abort_after_s)
        with self.lock:
            log.debug("%s: running %s", self.name, args)
            start = clock.now()
            try:
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise DeviceNotFound(f"device {self.name!r}: cannot start OpenOCD: {exc}") from exc
            try:
                output, _ = process.communicate(timeout=limit)
                stopped = False
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
                stopped = True
            duration = clock.now() - start
        interrupted = stopped and abort_after_s is not None and abort_after_s <= timeout_s
        return ProbeResult(
            action,
            output,
            None if stopped else process.returncode,
            duration,
            interrupted=interrupted,
            timed_out=stopped and not interrupted,
        )
```

V `src/hil/drivers/__init__.py` doplnit import a `__all__` o `openocd`.

- [ ] **Step 4: Spustit testy**

Run: `python -m pytest tests/drivers/test_openocd.py -q`
Expected: PASS.

- [ ] **Step 5: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q`
```bash
git add src/hil/drivers tests/drivers
git commit -m "feat: ovladač openocd"
```

---

### Úkol 8: Signály procesu bez I/O v obsluze

**Files:**
- Modify: `src/hil/errors.py`, `src/hil/station.py`, `src/hil/recording.py` (jen docstring)
- Test: `tests/test_station.py`, `tests/test_pytest_plugin.py`

**Interfaces:**
- Consumes: `Station.install_emergency_handlers`, `Station.close`, `Station._at_exit` (plán 1).
- Produces:
  - `hil.errors.TerminationRequested(KeyboardInterrupt)` s atributem `signame: str`.
  - Obsluha SIGINT a SIGTERM a SIGHUP (Linux), SIGINT a SIGBREAK (Windows) nekomunikuje se zařízeními a vyhodí `TerminationRequested`. Další signál během ukončování nebo během `Station.close()` jen zaloguje. Ignorovaný signál (`SIG_IGN`) zůstává ignorovaný. Obsluhy se obnoví až na konci `close()`.

- [ ] **Step 1: Napsat padající testy**

V `tests/test_station.py` přidat importy `import sys` a `from hil.errors import TerminationRequested` (do stávajícího importu z `hil.errors`). Testy `test_emergency_handler_switches_power_off` a `test_emergency_handler_does_not_deadlock_on_busy_recorder` nahradit:
```python
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


def test_termination_signal_only_interrupts(station):
    previous = signal.getsignal(signal.SIGINT)
    station.install_emergency_handlers()
    station.power.on("PWR")
    handler = signal.getsignal(signal.SIGINT)
    with pytest.raises(TerminationRequested) as info:
        handler(signal.SIGINT, None)
    assert isinstance(info.value, KeyboardInterrupt)
    assert info.value.signame == "SIGINT"
    # no device I/O in the handler: the interrupted thread may be inside a bus frame
    assert station.devices["rel1"].states[0]
    assert handler(signal.SIGINT, None) is None  # a repeated signal is only logged
    station.close()
    assert not station.devices["rel1"].states[0]
    assert signal.getsignal(signal.SIGINT) is previous


@posix_only
def test_sigterm_interrupts(station):
    station.install_emergency_handlers()
    with pytest.raises(TerminationRequested, match="SIGTERM"):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)


@posix_only
def test_ignored_signal_stays_ignored(station):
    previous = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        station.install_emergency_handlers()
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
    finally:
        station.close()
        signal.signal(signal.SIGHUP, previous)


@register_driver("test_signal_in_safe_state")
class _SignalInSafeState(Device):
    """Delivers SIGINT to the station's handler while the safe state is being set."""

    armed = False

    def safe_state(self):
        if self.armed:
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)


def test_signal_during_close_does_not_abort_safe_state(tmp_path):
    text = STATION.replace("terminals:\n", "  sig: {driver: test_signal_in_safe_state}\nterminals:\n")
    station = make(tmp_path, text)
    station.open()
    station.install_emergency_handlers()
    station.devices["sig"].armed = True
    station.power.on("PWR")
    station.close()
    assert not station.devices["rel1"].states[0]


def test_at_exit_switches_power_off_despite_busy_recorder(station):
    station.power.on("PWR")
    station.recorder._lock.acquire()
    try:
        start = time.perf_counter()
        station._at_exit()
        elapsed = time.perf_counter() - start
    finally:
        station.recorder._lock.release()
    assert elapsed < 2.0
    assert not station.devices["rel1"].states[0]
```

Na konec `tests/test_pytest_plugin.py` (importy `import sys`):
```python
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_ends_session_with_safe_state(pytester):
    pytester.makefile(".yaml", dut=DUT)
    pytester.makepyfile(
        """
        import os
        import signal

        def test_1_terminated(dut):
            dut.supply.on()
            os.kill(os.getpid(), signal.SIGTERM)

        def test_2_not_run(dut):
            pass
        """
    )
    result = pytester.runpytest_subprocess(
        "--hil-station", "sim", "--hil-dut", "dut.yaml", "--hil-out", "out", "-v"
    )
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert "test_2_not_run PASSED" not in result.stdout.str()
    events = next((pytester.path / "out").glob("*test_1_terminated*/events.jsonl"))
    actions = [json.loads(line).get("action") for line in events.read_text().splitlines()]
    assert "safe_state" in actions
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/test_station.py tests/test_pytest_plugin.py -q`
Expected: FAIL (`cannot import name 'TerminationRequested'`).

- [ ] **Step 3: Implementace**

Na konec `src/hil/errors.py`:
```python
class TerminationRequested(KeyboardInterrupt):
    """A termination signal arrived; raised in the main thread so that cleanup runs.

    A subclass of ``KeyboardInterrupt``: pytest ends the session and tears the fixtures
    down as after Ctrl+C, while a ``SystemExit`` raised in a test would only fail that
    test and the session would go on.
    """

    def __init__(self, signame: str) -> None:
        super().__init__(signame)
        self.signame = signame
```

V `src/hil/station.py`:
- import `TerminationRequested` z `hil.errors`;
- v `__init__` za `self._atexit_registered = False` přidat `self._terminating = False` a `self._closing = False`;
- `close` nahradit:
```python
    def close(self) -> None:
        """Safe state, release signals and devices; signal handlers are restored last."""
        self._closing = True
        try:
            errors: list[Exception] = []
            if self._opened:
                try:
                    self.safe_state()
                except DeviceError as exc:
                    errors.append(exc)
            for signal in self.terminals.values():
                try:
                    signal.close()
                except Exception as exc:
                    log.error("closing terminal %s failed: %s", signal.name, exc)
                    errors.append(exc)
            for name in reversed(self._opened):
                try:
                    self.devices[name].close()
                except Exception as exc:
                    log.error("closing device %s failed: %s", name, exc)
                    errors.append(exc)
            self._opened.clear()
            if errors:
                raise DeviceError(f"closing station {self.name!r} failed: {errors[0]}")
        finally:
            self._remove_emergency_handlers()
            self._closing = False
            self._terminating = False
```
- `install_emergency_handlers` a `_make_handler` nahradit:
```python
    def install_emergency_handlers(self) -> None:
        """Interrupt the main thread on termination signals; power off at interpreter exit.

        The handlers do no device I/O: the main thread may be inside a bus transaction
        and a frame sent from the handler would corrupt it. They raise
        ``TerminationRequested`` and the cleanup (``close``, pytest teardown) sets the
        full safe state.
        """
        if not self._atexit_registered:
            atexit.register(self._at_exit)
            self._atexit_registered = True
        if threading.current_thread() is not threading.main_thread():
            return
        if sys.platform == "win32":
            names: tuple[str, ...] = ("SIGINT", "SIGBREAK")
        else:
            names = ("SIGINT", "SIGTERM", "SIGHUP")
        for signame in names:
            signum = getattr(os_signal, signame)
            if signum in self._previous_handlers:
                continue
            previous = os_signal.getsignal(signum)
            if previous == os_signal.SIG_IGN:
                continue  # e.g. SIGHUP under nohup: the run is meant to survive it
            self._previous_handlers[signum] = previous
            os_signal.signal(signum, self._make_handler(signame, previous))

    def _make_handler(
        self, signame: str, previous: _Handler
    ) -> Callable[[int, FrameType | None], None]:
        def handler(signum: int, frame: FrameType | None) -> None:
            if self._terminating or self._closing:
                log.warning("%s ignored: the station is being put into the safe state", signame)
                return
            self._terminating = True
            log.warning("%s received: stopping, the station goes to the safe state", signame)
            if callable(previous) and previous is not os_signal.default_int_handler:
                previous(signum, frame)
            raise TerminationRequested(signame)

        return handler
```
`_remove_emergency_handlers`, `_at_exit` a `emergency_off` zůstávají.

V `src/hil/recording.py` v docstringu `_append` nahradit „a termination signal handler may call this while the interrupted main thread holds the lock“ textem „the atexit handler may call this while another thread holds the lock“.

- [ ] **Step 4: Spustit testy**

Run: `python -m pytest tests/test_station.py tests/test_pytest_plugin.py -q`
Expected: PASS (testy s `posix_only` se na Windows přeskočí).

- [ ] **Step 5: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q && python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
```bash
git add src/hil tests
git commit -m "feat: signály procesu jen přeruší hlavní vlákno, bezpečný stav nastaví úklid"
```

---

### Úkol 9: Best-effort otevření stanoviště a `hil safe`

**Files:**
- Modify: `src/hil/station.py`, `src/hil/cli.py`
- Test: `tests/test_station.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Station.open`, `Station.safe_state`, `terminal_refs`, `DebugTerminal`, `Device.dependencies()`.
- Produces:
  - `Station.open(best_effort: bool = False) -> list[Exception]`: bez `best_effort` beze změny chování (vrátí `[]`); s ním přeskočí zařízení, které se nepodařilo otevřít, i zařízení na něm závislá, nastaví bezpečný stav na zbytku a chyby vrátí.
  - `Station.safe_state()` přeskakuje svorky, jejichž zařízení nejsou otevřená.
  - `hil safe` je best-effort: při chybách vypíše `device error: ...` pro každou chybu a vrátí 3.

- [ ] **Step 1: Napsat padající testy**

Na konec `tests/test_station.py` (import `from hil.drivers.sim.relay import SimRelay`):
```python
@register_driver("test_missing_relay")
class _MissingRelay(SimRelay):
    def open(self):
        raise DeviceNotFound("relay module not connected")


BEST_EFFORT = (
    STATION.replace(
        "terminals:\n",
        "  bad: {driver: test_missing_relay, channels: 4}\n"
        "  di2: {driver: sim_di, inputs: 1, mirror: {0: bad.0}}\n"
        "terminals:\n",
    )
    + "  X1.2: {kind: switch, relay: bad.1}\n"
    + "  X2.2: {kind: sense, input: di2.0}\n"
)


def test_best_effort_open_sets_safe_state_on_the_rest(tmp_path):
    station = make(tmp_path, BEST_EFFORT)
    station.devices["rel1"].states[0] = True  # power left on, e.g. by a crashed run
    errors = station.open(best_effort=True)
    assert [str(e) for e in errors] == [
        "relay module not connected",
        "device 'di2' not opened: it depends on bad",
    ]
    assert station.devices["rel1"].is_open
    assert not station.devices["rel1"].states[0]
    assert not station.devices["di2"].is_open
    station.close()


def test_open_without_best_effort_fails_fast(tmp_path):
    station = make(tmp_path, BEST_EFFORT)
    with pytest.raises(DeviceNotFound, match="relay module not connected"):
        station.open()
    assert station._opened == []
```

Na konec `tests/test_cli.py` (importy `from hil.drivers import register_driver`, `from hil.drivers.base import Device`, `from hil.errors import DeviceNotFound`):
```python
@register_driver("test_cli_missing")
class _Missing(Device):
    def open(self):
        raise DeviceNotFound("module not connected")


def test_safe_is_best_effort(tmp_path, capsys):
    path = tmp_path / "s.yaml"
    path.write_text(
        "name: cli-best-effort\nprofile: standard-v1\ndevices:\n"
        "  rel1: {driver: sim_relay}\n  gone: {driver: test_cli_missing}\n"
        "terminals:\n  PWR: {kind: power, relays: [rel1.0, rel1.1]}\n",
        encoding="utf-8",
    )
    assert main(["safe", "--station", str(path)]) == 3
    err = capsys.readouterr().err
    assert err.count("device error: module not connected") == 1
    assert "safe state set only on the devices that opened" in err
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/test_station.py tests/test_cli.py -q`
Expected: FAIL (`open() got an unexpected keyword argument 'best_effort'`).

- [ ] **Step 3: Implementace `src/hil/station.py`**

Import `terminal_refs` a `DebugTerminal` z `hil.config.models` (DebugTerminal už je importován z úkolu 6). V `__init__` za vytvoření `self.terminals` přidat:
```python
        self._terminal_devices: dict[str, frozenset[str]] = {
            name: _devices_of(terminal) for name, terminal in self.config.terminals.items()
        }
```
a na konec modulu:
```python
def _devices_of(terminal: Any) -> frozenset[str]:
    """Names of the devices a station terminal uses."""
    devices = {ref.device for ref in terminal_refs(terminal)}
    if isinstance(terminal, DebugTerminal):
        devices.add(terminal.probe)
    return frozenset(devices)
```

`open` nahradit a přidat `_open_best_effort`:
```python
    def open(self, best_effort: bool = False) -> list[Exception]:
        """Open all devices and set the safe state.

        With ``best_effort`` a device that fails to open, and every device that depends
        on it, is skipped; the safe state is set on the rest and the errors are returned
        instead of raised. ``hil safe`` uses it at boot, so that one missing module does
        not leave the other outputs of the station switched on.
        """
        if best_effort:
            return self._open_best_effort()
        try:
            for name in self._order:
                self.devices[name].open()
                self._opened.append(name)
            self.safe_state()
        except BaseException:
            try:
                self.close()
            except Exception as cleanup_error:
                log.error("cleanup after failed open of station %s: %s", self.name, cleanup_error)
            raise
        return []

    def _open_best_effort(self) -> list[Exception]:
        errors: list[Exception] = []
        failed: set[str] = set()
        for name in self._order:
            device = self.devices[name]
            missing = failed.intersection(device.dependencies())
            if missing:
                failed.add(name)
                errors.append(
                    DeviceError(
                        f"device {name!r} not opened: it depends on {', '.join(sorted(missing))}"
                    )
                )
                continue
            try:
                device.open()
            except Exception as exc:
                log.error("opening device %s failed: %s", name, exc)
                failed.add(name)
                errors.append(exc)
                continue
            self._opened.append(name)
        try:
            self.safe_state()
        except DeviceError as exc:
            errors.append(exc)
        return errors
```

`safe_state` nahradit:
```python
    def safe_state(self) -> None:
        """Power off first, then every terminal and every open device.

        Terminals on a device that is not open (after ``open(best_effort=True)``) are
        skipped.
        """
        opened = set(self._opened)
        ready = [
            signal
            for name, signal in self.terminals.items()
            if self._terminal_devices[name] <= opened
        ]
        errors: list[Exception] = []
        for signal in ready:
            if isinstance(signal, PowerSignal):
                try:
                    signal.off()
                except Exception as exc:
                    log.error("switching off %s failed: %s", signal.name, exc)
                    errors.append(exc)
        for signal in ready:
            if isinstance(signal, PowerSignal):
                continue
            try:
                signal.safe_state()
            except Exception as exc:
                errors.append(exc)
        for name in self._opened:
            try:
                self.devices[name].safe_state()
            except Exception as exc:
                errors.append(exc)
        if errors:
            details = "; ".join(str(e) for e in errors)
            raise DeviceError(f"station {self.name!r}: safe state failed: {details}")
        self.recorder.event("station", "safe_state")
```

- [ ] **Step 4: Implementace `src/hil/cli.py`**

Import `DeviceError` z `hil.errors`. `_safe` nahradit:
```python
def _safe(station: Station) -> int:
    with StationLock(station.name):
        errors = station.open(best_effort=True)
        try:
            station.close()  # sets the safe state once more and releases the devices
        except DeviceError as exc:
            errors.append(exc)
    if errors:
        seen: set[str] = set()
        for error in errors:
            if str(error) not in seen:
                seen.add(str(error))
                print(f"device error: {error}", file=sys.stderr)
        print(
            f"station {station.name!r}: safe state set only on the devices that opened",
            file=sys.stderr,
        )
        return EXIT_DEVICE
    print(f"station {station.name!r}: safe state set")
    return EXIT_OK
```

- [ ] **Step 5: Spustit testy**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
```bash
git add src/hil/station.py src/hil/cli.py tests/test_station.py tests/test_cli.py
git commit -m "feat: hil safe nastaví bezpečný stav i při chybějícím zařízení"
```

---

### Úkol 10: Odolnost signálů – znovuotevření portu, timeouty záznamu, chybná parita

**Files:**
- Modify: `src/hil/signals/uart.py`, `src/hil/signals/digital.py`, `src/hil/signals/rs485.py`
- Test: `tests/signals/test_uart.py`, `tests/signals/test_digital.py`, `tests/signals/test_rs485.py`

**Interfaces:**
- Consumes: `SerialSignal`, `SenseSignal.record`, `Rs485Signal.inject` (plán 1 a 2).
- Produces:
  - `SerialSignal.safe_state()` zavře port, jehož čtecí vlákno skončilo chybou; další použití ho otevře znovu.
  - `SenseSignal.record()` vyhodí `DeviceTimeout`, když první čtení vstupu trvá déle než `_START_TIMEOUT_S` (5 s); čtecí vlákno čeká nejvýš `_STOP_TIMEOUT_S` (5 s).
  - `Rs485Signal.inject("bad_parity", ...)` počítá čekání s dobou znaku při chybné paritě, chybu nastavení parity hlásí jako `DeviceError`, při chybě obnovení parity zavře port.

- [ ] **Step 1: Napsat padající testy**

Na konec `tests/signals/test_uart.py`:
```python
def test_safe_state_reopens_failed_port(console, ser):
    ser.close()
    time.sleep(0.05)
    with pytest.raises(DeviceError, match="serial port failed"):
        console.expect("anything", timeout=0.2)
    ser.open()
    console.safe_state()
    assert not console.is_open
    with ser.endpoint("dut_con") as side:
        console.open()
        side.write(b"back\n")
        console.expect("back", timeout=1)
```

Na konec `tests/signals/test_digital.py` (importy `import threading`, `from hil.errors import DeviceTimeout`, `from hil.resources import DigitalInput`):
```python
class _StuckBank:
    name = "stuck"

    def __init__(self):
        self.release = threading.Event()

    def read(self, index):
        self.release.wait(5)
        return False


def test_record_times_out_on_stuck_input(monkeypatch):
    import hil.signals.digital

    monkeypatch.setattr(hil.signals.digital, "_START_TIMEOUT_S", 0.1)
    bank = _StuckBank()
    sense = SenseSignal("X2.1", Recorder(), DigitalInput(bank, 0))
    try:
        with pytest.raises(DeviceTimeout, match="first reading"), sense.record():
            pass
    finally:
        bank.release.set()
```

V `tests/signals/test_rs485.py` upravit očekávání v `test_bad_parity_waits_for_transmission` (rs485 má paritu N, chybná parita E přidá ke znaku bit):
```python
    char_s = SerialParams(timeout_s=0.3, parity="E").char_time_s()
    assert sleeps == [pytest.approx(len(FRAME) * char_s + 0.002)]
```
a na konec přidat:
```python
def test_bad_parity_switch_failure_is_device_error(rs485, monkeypatch):
    port = rs485.port

    def refuse(self, value):
        raise ValueError("parity not supported")

    monkeypatch.setattr(type(port), "parity", property(lambda self: "N", refuse))
    with pytest.raises(DeviceError, match="cannot switch parity to E"):
        rs485.inject("bad_parity", FRAME)
```

- [ ] **Step 2: Spustit testy, musí selhat**

Run: `python -m pytest tests/signals -q`
Expected: FAIL (port zůstává otevřený, `record` nečeká s timeoutem, jiná doba čekání, `ValueError` místo `DeviceError`).

- [ ] **Step 3: `src/hil/signals/uart.py`**

Na konec `SerialSignal.safe_state` přidat:
```python
        if self._error is not None:
            # the reader stopped on a port failure; reopen the port on next use
            log.info("serial port %s failed earlier, closing it", self.alias)
            try:
                self.close()
            except Exception as exc:
                log.warning("serial port %s: closing failed: %s", self.alias, exc)
```

- [ ] **Step 4: `src/hil/signals/digital.py`**

Přidat `import logging`, `from hil.errors import DeviceTimeout, WaitTimeout`, pod importy:
```python
log = logging.getLogger("hil.signals.digital")

# longest wait for the first reading of a recorded input and for the recording to stop
_START_TIMEOUT_S = 5.0
_STOP_TIMEOUT_S = 5.0
```
V `record` nahradit část od `thread.start()` do konce:
```python
        thread.start()
        if not started.wait(_START_TIMEOUT_S):
            stop.set()
            raise DeviceTimeout(
                f"{self.name}: first reading of the input took longer than {_START_TIMEOUT_S} s"
            )
        try:
            yield recording
        finally:
            stop.set()
            thread.join(_STOP_TIMEOUT_S)
            if thread.is_alive():
                log.warning("%s: recording did not stop within %s s", self.name, _STOP_TIMEOUT_S)
            self._event(
                "recorded",
                changes=len(recording.changes),
                mean_period_s=round(recording.mean_period_s, 6),
            )
        if errors:
            raise errors[0]
```

- [ ] **Step 5: `src/hil/signals/rs485.py`**

Přidat `import logging` a `log = logging.getLogger("hil.signals.rs485")`. V `inject` nahradit větev `if kind == "bad_parity": ... else: self._send(payload)` voláním:
```python
        if kind == "bad_parity":
            self._send_with_parity(payload)
        else:
            self._send(payload)
```
a do třídy přidat:
```python
    def _send_with_parity(self, payload: bytes) -> None:
        """Send ``payload`` with the wrong parity, then restore the port's parity."""
        port = self.port
        original = port.parity
        parity = wrong_parity(original)
        try:
            port.parity = parity
        except (SerialException, ValueError) as exc:
            raise DeviceError(f"{self.alias}: cannot switch parity to {parity}: {exc}") from exc
        try:
            self._send(payload)
            # flush() on Windows returns before the chip FIFO is empty; restoring the parity
            # earlier would send the tail with the right parity. The wrong parity can add
            # a bit to every character, so its character time counts.
            char_s = self.params.model_copy(update={"parity": parity}).char_time_s()
            time.sleep(len(payload) * char_s + 0.002)
        finally:
            try:
                port.parity = original
            except (SerialException, ValueError) as exc:
                log.error("%s: cannot restore parity %s (%s), closing the port", self.alias, original, exc)
                self.close()
```

- [ ] **Step 6: Spustit testy**

Run: `python -m pytest tests/signals -q`
Expected: PASS.

- [ ] **Step 7: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q && python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
```bash
git add src/hil/signals tests/signals
git commit -m "fix: znovuotevření portu konzole, timeouty záznamu vstupu a chybná parita"
```

---

### Úkol 11: Stanoviště `lab-a` a HW testy

**Files:**
- Create: `stations/lab-a.yaml`, `tests/test_station_files.py`, `tests/hw/__init__.py`, `tests/hw/conftest.py`, `tests/hw/test_station_hw.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: drivery `modbus_rtu_bus`, `waveshare_relay32`, `modbus_di`, `serial_ports`, `openocd` (úkoly 2–7), `ModbusRelayModule.initial_states`, `read_back()`, `set_many()` (úkol 4), `SerialPorts.device_path()` (úkol 2), `Station.debug` (úkol 6), `StationLock`.
- Produces: soubor stanoviště `stations/lab-a.yaml` (validovaný v CI bez hardwaru), marker `hw`, fixture `hw_station` a HW testy spouštěné proměnnou prostředí `HIL_HW_STATION`.

- [ ] **Step 1: Napsat padající test souborů stanovišť**

`tests/test_station_files.py`:
```python
"""Station files in stations/ must stay valid; building a station does no I/O."""

from pathlib import Path

import pytest

from hil.cli import main
from hil.station import Station

STATIONS = sorted((Path(__file__).parents[1] / "stations").glob("*.yaml"))


def test_station_files_exist():
    assert STATIONS


@pytest.mark.parametrize("path", STATIONS, ids=lambda p: p.stem)
def test_station_file_is_valid(path, capsys):
    station = Station.from_files(path)
    assert station.name == path.stem
    assert "PWR" in station.terminals
    assert main(["check", "--station", str(path)]) == 0
    assert "configuration OK" in capsys.readouterr().out
```

- [ ] **Step 2: Spustit test, musí selhat**

Run: `python -m pytest tests/test_station_files.py -q`
Expected: FAIL (`assert []`).

- [ ] **Step 3: `stations/lab-a.yaml`**

```yaml
# Station lab-a: the selected hardware set (doc/vyber/doporuceni.md).
# Serial numbers and device paths marked REPLACE are placeholders until the station is
# built; put in the values of the real devices and check them with
#   hil check --station stations/lab-a.yaml --probe
# Analog terminals (AO.*, AI.*) are wired in plan 4 together with the Analog Discovery 3;
# rel2 is reserved for their multiplexer.
name: lab-a
labels: [hil, lab-a]
profile: standard-v1
devices:
  # isolated USB to RS-485 converter, the fifth serial port next to the FT4232H
  relay_bus:
    driver: modbus_rtu_bus
    port: /dev/serial/by-id/usb-FTDI_USB-RS485-REPLACE-if00-port0
    baud: 9600
  rel1: {driver: waveshare_relay32, bus: relay_bus, address: 1}
  rel2: {driver: waveshare_relay32, bus: relay_bus, address: 2}
  di1: {driver: modbus_di, bus: relay_bus, address: 5, count: 8}
  # Waveshare USB to 4-Ch Serial Converter: A TTL, B TTL or RS-485, C and D isolated RS-485
  ft:
    driver: serial_ports
    ports:
      A: {serial: FT4232-REPLACE, interface: 0}
      B: {serial: FT4232-REPLACE, interface: 1}
      C: {serial: FT4232-REPLACE, interface: 2}
      D: {serial: FT4232-REPLACE, interface: 3}
  stlink: {driver: openocd, interface: interface/stlink.cfg}
terminals:
  PWR: {kind: power, relays: [rel1.0, rel1.1]}
  X1.1: {kind: switch, relay: rel1.2}
  X1.2: {kind: switch, relay: rel1.3}
  X1.3: {kind: switch, relay: rel1.4}
  X1.4: {kind: switch, relay: rel1.5}
  F1: {kind: fault_path, series: rel1.6, short: rel1.7}
  F2: {kind: fault_path, series: rel1.8, short: rel1.9}
  F3: {kind: fault_path, series: rel1.10, short: rel1.11}
  F4: {kind: fault_path, series: rel1.12, short: rel1.13}
  X2.1: {kind: sense, input: di1.0}
  X2.2: {kind: sense, input: di1.1}
  X2.3: {kind: sense, input: di1.2}
  X2.4: {kind: sense, input: di1.3}
  X2.5: {kind: sense, input: di1.4}
  X2.6: {kind: sense, input: di1.5}
  X2.7: {kind: sense, input: di1.6}
  X2.8: {kind: sense, input: di1.7}
  CON: {kind: serial, port: ft.A}
  LOG: {kind: serial, port: ft.B}
  COM1: {kind: rs485, port: ft.C}
  MON1: {kind: rs485_monitor, port: ft.D}
  SWD: {kind: debug, probe: stlink}
```

- [ ] **Step 4: Spustit test**

Run: `python -m pytest tests/test_station_files.py -q`
Expected: PASS.

- [ ] **Step 5: Marker a HW testy**

V `pyproject.toml` do `[tool.pytest.ini_options]` přidat:
```toml
markers = ["hw: needs a real HIL station (set HIL_HW_STATION, see doc/software/hw-testy.md)"]
```

`tests/hw/__init__.py`: prázdný soubor.

`tests/hw/conftest.py`:
```python
"""Hardware checks of a real station; skipped unless HIL_HW_STATION names a station file.

    HIL_HW_STATION=stations/lab-a.yaml python -m pytest tests/hw -v

The wiring the checks need is described in doc/software/hw-testy.md.
"""

import os

import pytest

from hil.locking import StationLock
from hil.station import Station


@pytest.fixture(scope="session")
def hw_station():
    path = os.environ.get("HIL_HW_STATION", "")
    if not path:
        pytest.skip("set HIL_HW_STATION to run this hardware check")
    station = Station.from_files(path)
    with StationLock(station.name), station:
        yield station
```

`tests/hw/test_station_hw.py`:
```python
"""Checks from "Co ověřit při stavbě" (doc/vyber/doporuceni.md) on a real station."""

import os
import sys
import time
from pathlib import Path

import pytest

from hil.comm import modbus
from hil.config.models import SerialParams
from hil.drivers.modbus_relay import ModbusRelayModule
from hil.drivers.serial_ports import SYSFS_USB_SERIAL, SerialPorts

pytestmark = pytest.mark.hw


def env(name):
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"set {name} to run this hardware check")
    return value


def relay_modules(station):
    modules = [d for d in station.devices.values() if isinstance(d, ModbusRelayModule)]
    if not modules:
        pytest.skip("the station has no Modbus relay modules")
    return modules


def test_relays_are_off_after_power_up(hw_station):
    """Run right after the relay modules were powered on (doporuceni.md, point 4)."""
    for module in relay_modules(hw_station):
        on = [i for i, state in enumerate(module.initial_states or []) if state]
        assert not on, f"{module.name}: relays {on} were on when the station opened"


def test_relay_coil_map(hw_station):
    """Every relay is switched alone and read back; needs HIL_HW_NO_DUT=1 (no DUT wired)."""
    env("HIL_HW_NO_DUT")
    for module in relay_modules(hw_station):
        channels = module.config.channels
        for index in range(channels):
            module.set_many({index: True})
            assert module.read_back() == [i == index for i in range(channels)], index
            module.set_many({index: False})


def loopback_pairs():
    pairs = env("HIL_HW_LOOPBACK")  # e.g. "X1.1:X2.1,X1.2:X2.2"
    return [tuple(pair.split(":")) for pair in pairs.split(",")]


def test_loopback_latency_and_polling_period(hw_station):
    """Switch to sense through a loopback cable: latency and polling period (D-03)."""
    for switch_name, sense_name in loopback_pairs():
        switch = hw_station.digital.switch(switch_name)
        sense = hw_station.digital.sense(sense_name)
        for state in (True, False):
            switch.set(state)
            seen = sense.wait_for(state, timeout=0.5)
            latency = seen - switch.last_change
            print(f"{switch_name} -> {sense_name} {state}: {latency * 1000:.1f} ms")
            assert latency < 0.05
        with sense.record() as recording:
            time.sleep(0.5)
        print(f"{sense_name}: mean polling period {recording.mean_period_s * 1000:.2f} ms")


def test_outage_accuracy(hw_station):
    """PWR outage measured on a sense input wired to the DUT supply (target below 10 ms)."""
    sense = hw_station.digital.sense(env("HIL_HW_SUPPLY_SENSE"))
    power = hw_station.power["PWR"]
    power.on()
    sense.wait_for(True, timeout=2)
    with sense.record(period_s=0.0005) as recording:
        power.outage(0.1)
        time.sleep(0.2)
    power.off()
    off = next(t for t, state in recording.changes if not state)
    on = next(t for t, state in recording.changes if state and t > off)
    print(f"outage 100 ms measured as {(on - off) * 1000:.1f} ms")
    assert abs((on - off) - 0.1) < 0.010


@pytest.mark.skipif(sys.platform != "linux", reason="the latency timer is read from sysfs")
def test_ftdi_latency_timer(hw_station):
    ports = [d for d in hw_station.devices.values() if isinstance(d, SerialPorts)]
    if not ports:
        pytest.skip("the station has no serial_ports device")
    for device in ports:
        for channel in device.config.ports:
            device.resource(channel).open(SerialParams(), timeout=0.01).close()
            tty = Path(os.path.realpath(device.device_path(channel))).name
            timer = SYSFS_USB_SERIAL / tty / "latency_timer"
            if timer.exists():
                assert int(timer.read_text()) == 1, f"{device.name}.{channel}"


def test_rs485_monitor_sees_active_port(hw_station):
    """COM1 and MON1 on the same pair (HIL_HW_RS485_LOOP=1), 921 600 Bd, parity E."""
    env("HIL_HW_RS485_LOOP")
    params = SerialParams(baud=921600, parity="E")
    port = hw_station.comm.rs485("COM1")
    monitor = hw_station.comm.monitor("MON1")
    port.configure("COM1", params)
    monitor.configure("MON1", params)
    monitor.start()
    frame = modbus.read_request(1, 3, 0, 1)
    port.send_raw(frame)
    seen = monitor.wait_for_frame(lambda f: f.raw == frame, timeout=1)
    assert seen.decoded is not None


def test_flash_with_openocd(hw_station):
    """Flash HIL_HW_IMAGE with OpenOCD target HIL_HW_TARGET through SWD."""
    target = env("HIL_HW_TARGET")
    image = env("HIL_HW_IMAGE")
    swd = hw_station.debug["SWD"]
    assert swd.flash(image, target).ok
    assert swd.reset(target).ok
```

- [ ] **Step 6: Spustit testy**

Run: `python -m pytest -q`
Expected: PASS, testy v `tests/hw` hlášené jako skipped (bez `HIL_HW_STATION`).

Run: `python -m pytest tests/hw -q -rs`
Expected: všechny skipped s důvodem `set HIL_HW_STATION to run this hardware check`.

- [ ] **Step 7: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy`
```bash
git add stations tests pyproject.toml
git commit -m "feat: stanoviště lab-a a HW testy"
```

---

### Úkol 12: Nasazení a dokumentace

**Files:**
- Create: `deploy/udev/99-hil.rules`, `deploy/systemd/hil-safe.service`, `doc/software/nasazeni.md`, `doc/software/hw-testy.md`
- Modify: `doc/software/konfigurace.md`, `doc/software/testy.md`, `README.md`

**Interfaces:**
- Consumes: všechny předchozí úkoly.
- Produces: soubory nasazení a uživatelská dokumentace v češtině.

- [ ] **Step 1: `deploy/udev/99-hil.rules`**

```
# HIL station (Linux): serial ports for the dialout group and FTDI latency timer 1 ms.
# Install: sudo cp 99-hil.rules /etc/udev/rules.d/ && sudo udevadm control --reload
#          && sudo udevadm trigger
# ST-Link rules come with the openocd package (60-openocd.rules), Analog Discovery rules
# with the Adept runtime.
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", GROUP="dialout", MODE="0660"
ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"
```

- [ ] **Step 2: `deploy/systemd/hil-safe.service`**

```
# HIL station: safe state after boot (NF-03). Edit the paths, then
#   sudo cp hil-safe.service /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable hil-safe.service
[Unit]
Description=HIL station safe state after boot
# wait until udev has created the serial devices
Wants=systemd-udev-settle.service
After=systemd-udev-settle.service

[Service]
Type=oneshot
User=hil
ExecStart=/opt/hil/venv/bin/hil safe --station /opt/hil/hil-platform/stations/lab-a.yaml

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: `doc/software/nasazeni.md`**

~~~markdown
# Nasazení stanoviště

## Linux (Debian, Raspberry Pi OS)

### Instalace balíčku

1. Uživatel stanoviště a skupiny pro sériové porty a ladicí sondu:
   `sudo useradd -m -G dialout,plugdev hil`
2. Repozitář a virtuální prostředí:
   ```
   sudo mkdir -p /opt/hil && sudo chown hil: /opt/hil
   git clone git@github.com:LogicElements/hil-platform.git /opt/hil/hil-platform
   python3 -m venv /opt/hil/venv
   /opt/hil/venv/bin/pip install -e /opt/hil/hil-platform
   ```
3. OpenOCD z distribuce: `sudo apt install openocd`. Balíček přidá pravidla udev pro ST-Link. Ovladač `openocd` používá syntaxi `adapter serial` a `adapter speed`, potřebuje tedy OpenOCD 0.11 nebo novější.
4. WaveForms a Adept runtime pro Analog Discovery 3 se instalují podle [návodu Digilentu](../vyber/doporuceni.md) (ARM64 na Raspberry Pi 5). Ovladač přibude v plánu 4.

### Pravidla udev

Soubor [deploy/udev/99-hil.rules](../../deploy/udev/99-hil.rules) zpřístupní porty FTDI skupině `dialout` a nastaví latency timer FTDI na 1 ms (pasivní záchyt RS-485 jinak slévá rámce). Bez pravidla se balíček pokusí latency timer nastavit sám a při chybějících právech jen varuje.

### Bezpečný stav po startu

Služba [deploy/systemd/hil-safe.service](../../deploy/systemd/hil-safe.service) spustí po startu PC `hil safe` (NF-03). V souboru upravte cestu k prostředí a ke stanovišti. `hil safe` pracuje best-effort: zařízení, které se nepodaří otevřít, přeskočí (i zařízení na něm závislá), na ostatních nastaví bezpečný stav, chyby vypíše a skončí kódem 3. Výsledek ukáže `systemctl status hil-safe`.

### Ukončení běžících testů

SIGINT (Ctrl+C), SIGTERM (`systemctl stop`, zrušení jobu v GitHub Actions) a SIGHUP (zavřený terminál) běh testů přeruší a úklid nastaví úplný bezpečný stav. Obsluha signálu sama na sběrnici nesahá, rozpracovaná transakce doběhne nebo skončí timeoutem. Další signál během nastavování bezpečného stavu se jen zaloguje. Pod `nohup` zůstává SIGHUP ignorovaný. Při `atexit` (konec interpretu bez úklidu) se vypne aspoň napájení DUT.

## Windows (vývoj)

- Ovladač FTDI VCP je součástí Windows Update. Latency timer nastavte ve Správci zařízení: port, Vlastnosti, Port Settings, Advanced, Latency Timer 1 ms. Balíček ho na Windows neověřuje, jen to připomene v logu.
- Port lze zadat jako `COM7` nebo sériovým číslem čipu FTDI (`{serial: FT4ABC, interface: 2}`). Jednokanálový čip (FT232R, FT232H) má jen `interface: 0`.
- OpenOCD (např. sestavení xPack) přidejte do `PATH`, nebo ve stanovišti uveďte `command: [C:/tools/openocd/bin/openocd.exe]`.
- Ukončení: Ctrl+C a Ctrl+Break přeruší běh stejně jako na Linuxu.
~~~

- [ ] **Step 4: `doc/software/hw-testy.md`**

~~~markdown
# HW testy stanoviště

Testy v `tests/hw/` ověřují skutečné stanoviště, body „Co ověřit při stavbě“ z [doporuceni.md](../vyber/doporuceni.md). Mají marker `hw` a bez proměnné `HIL_HW_STATION` se přeskočí, takže v CI neběží.

```
HIL_HW_STATION=stations/lab-a.yaml python -m pytest tests/hw -v -s
```

Volba `-s` ukáže naměřené hodnoty (zpoždění, perioda čtení, délka výpadku). Stanoviště se otevře jednou pro všechny testy a na konci přejde do bezpečného stavu.

| Test | Potřebuje | Ověřuje |
|---|---|---|
| `test_relays_are_off_after_power_up` | spustit hned po zapnutí modulů relé | výchozí stav relé po zapnutí (doporuceni.md, bod 4) |
| `test_relay_coil_map` | `HIL_HW_NO_DUT=1`, odpojený DUT | mapu coilů: každé relé se sepne samo a přečte zpět |
| `test_loopback_latency_and_polling_period` | `HIL_HW_LOOPBACK=X1.1:X2.1,...` a propojky mezi svorkami | zpoždění `switch` → `sense` pod 50 ms, průměrnou periodu čtení vstupu |
| `test_outage_accuracy` | `HIL_HW_SUPPLY_SENSE=X2.8` a vstup zapojený na napájení DUT | délku `outage(0.1)`, odchylka pod 10 ms |
| `test_ftdi_latency_timer` | Linux | latency timer všech portů `serial_ports` je 1 ms |
| `test_rs485_monitor_sees_active_port` | `HIL_HW_RS485_LOOP=1`, `COM1` a `MON1` na jednom páru | záchyt rámce při 921 600 Bd s paritou E |
| `test_flash_with_openocd` | `HIL_HW_TARGET`, `HIL_HW_IMAGE`, připojený DUT | flashování a reset přes ST-Link |

`test_relay_coil_map` spíná postupně všechna relé včetně napájení a poruchových cest, proto běží jen s `HIL_HW_NO_DUT=1`.

Pokud mapa coilů nesouhlasí, upravte ve stanovišti `coil_base`, případně `write: single` (zápis po jednom relé funkcí 5), a test spusťte znovu. U modulu Quido se stejně upravuje `input_base`.
~~~

- [ ] **Step 5: `doc/software/konfigurace.md`**

- Odstavec za výčtem druhů svorek nahradit: „Tato verze balíčku sestaví všechny druhy kromě `analog_out` a `analog_in`, ty přibudou s ovladačem Analog Discovery 3.“
- Za odrážku `serial`, `rs485`, `rs485_monitor` přidat odrážku: „`debug`: `probe: <zařízení>`, ladicí sonda (`openocd` nebo `sim_probe`). Cíl OpenOCD uvádí `dut.yaml`.“
- Tabulku ovladačů doplnit řádky:

| Ovladač | Volby | Kanály |
|---|---|---|
| `sim_probe` | `flash_s` (doba simulovaného flashování, výchozí 0,05 s) | žádné, svorka `debug` odkazuje na zařízení |
| `modbus_rtu_bus` | `port` (cesta, URL nebo `{serial, interface}`) nebo `link: <zařízení>.<kanál>`, `baud` (9600), `parity` (`N`), `stopbits` (1), `timeout_s` (0,2), `min_gap_s` (3,5 znaku, alespoň 2 ms), `lock_timeout_s` (2), `low_latency` (`true`) | žádné |
| `waveshare_relay32` | `bus`, `address` (1–247), `channels` (32), `coil_base` (0), `write` (`multiple` nebo `single`) | `0` až `channels-1` |
| `quido_rs_2_32` | jako `waveshare_relay32` a `input_base` (0) | `0` až `31`, vstupy `in0`, `in1` |
| `modbus_di` | `bus`, `address`, `count` (1–256), `source` (`discrete_inputs` nebo `input_registers`), `start` (0), `invert` (`false`) | `0` až `count-1` |
| `openocd` | `command` (`[openocd]`), `interface` (`interface/stlink.cfg`), `adapter_serial`, `speed_khz`, `search` | žádné |

- Za tabulku přidat odstavce:
  „Moduly relé a vstupů sdílejí sběrnici `modbus_rtu_bus`, operace na ní jdou postupně. Operace, která na sběrnici čeká déle než `lock_timeout_s`, skončí chybou `DeviceTimeout`. Modul, který při otevření neodpovídá, způsobí `DeviceNotFound` s adresou a jménem sběrnice. Moduly relé drží povelový stav: `set_many` zapíše jedním rámcem (funkce 15) rozsah od nejnižšího po nejvyšší měněné relé. Coily přečtené při otevření jsou v `initial_states` (stav po zapnutí modulu).“
  „Mapy registrů Waveshare a Quido nejsou ověřené na hardwaru. Pokud nesouhlasí, upravují se volbami `coil_base`, `write` a `input_base`, ne kódem (viz [HW testy](hw-testy.md)). Quido je třeba přepnout z protokolu Spinel na Modbus RTU.“
  „`modbus_di` čte všechny vstupy jedním požadavkem: z discrete inputs (funkce 2), nebo z input registrů (funkce 4) po 16 vstupech na registr od nejnižšího bitu.“
- Tabulku zapojení stanoviště `sim` doplnit řádkem `| SWD | zařízení probe (sim_probe) |` a větu o nezapojených svorkách změnit na „Analogové svorky (`AO.*`, `AI.*`) `sim` nezapojuje, testy, které je použijí, se přeskočí.“
- Za tabulku parametrů sériových signálů přidat:
  „Parametry signálu `debug`: `target` (povinný, konfigurace cíle OpenOCD, např. `target/stm32g4x.cfg`) a `timeout_s` (výchozí 120 s, nejdelší doba jedné operace sondy).“
- V oddílu Kontrola konfigurace odstranit komentář „stations/lab-a.yaml je příklad cesty, soubor přibude v dalším plánu“ a přidat odstavec: „Stanoviště `stations/lab-a.yaml` popisuje zvolenou sestavu. Sériová čísla a cesty označené `REPLACE` se doplní při stavbě, potom je ověří `hil check --station stations/lab-a.yaml --probe`.“

- [ ] **Step 6: `doc/software/testy.md`**

- Do tabulky signálů přidat řádek:
  `| debug | flash(obraz) -> ProbeResult, flash_interrupted(obraz, after_s), reset(), halt(); výstup sondy do openocd.log |`
- Za odstavec o Modbus RTU přidat odstavec:
  „Signál `debug` předá operaci sondě s cílem z `dut.yaml` (bez `dut.yaml` přes `hil.debug.flash("SWD", obraz, target)`). Výsledek `ProbeResult` nese výstup, návratový kód, dobu a příznaky `interrupted` a `timed_out`. Selhání nástroje je `DeviceError`, překročení `timeout_s` je `DeviceTimeout`, chybějící obraz `FileNotFoundError`. Výstup sondy je v `openocd.log` i při chybě. `flash_interrupted(obraz, after_s)` ukončí sondu po `after_s` sekundách a simuluje přerušenou aktualizaci firmwaru. Pokud flashování skončí dřív, má výsledek `interrupted` rovno `False`.“
- V oddílu Záznamy doplnit větu: „Signál `debug` zapisuje výstup sondy do `openocd.log` (řádek `--- <signál>: <operace>` a za ním výstup).“
- Za oddíl Záznamy přidat oddíl:
  ~~~markdown
  ## Přerušení běhu

  Ctrl+C, `systemctl stop` (SIGTERM) a zavření terminálu (SIGHUP) běh testů přeruší jako Ctrl+C: pytest ukončí session, úklid fixtures nastaví bezpečný stav a návratový kód je 2. Obsluha signálu nekomunikuje se zařízeními, aby nepoškodila rozpracovaný rámec na sběrnici relé.
  ~~~
- V tabulce příkazové řádky změnit řádek `hil safe` na: `| hil safe --station S | bezpečný stav stanoviště; zařízení, které nejde otevřít, přeskočí a skončí kódem 3 |`.

- [ ] **Step 7: `README.md`**

Do seznamu Dokumentace za „Psaní a spouštění testů“ přidat:
```markdown
- [Nasazení stanoviště](doc/software/nasazeni.md)
- [HW testy stanoviště](doc/software/hw-testy.md)
```

- [ ] **Step 8: Kontroly a commit**

Run: `ruff format . && ruff check . && mypy && python -m pytest -q && python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml -q`
```bash
git add deploy doc README.md
git commit -m "doc: nasazení stanoviště, HW testy a nové ovladače"
```

---

## Po dokončení všech úkolů

- Celková kontrola větve (subagent-driven: závěrečný review celé změny).
- Aktualizovat paměť projektu (plán 3 hotový, co zbývá ověřit na HW).
- Všechny lokální commity sloučit do jednoho („feat: ovladače balíčku hil (Modbus moduly, OpenOCD, bezpečné ukončení, lab-a)“) a push až po potvrzení zadavatelem.

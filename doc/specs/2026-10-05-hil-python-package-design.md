# Návrh Python balíčku `hil`

Stav: návrh ke schválení · Datum: 2026-10-05

Balíček obsahuje ovladače zařízení HIL stanoviště, definici platformy (HAL bloky a konfiguraci stanoviště) a popis zapojení vůči DUT. Vychází ze [specifikace](../hil-specifikace.md), [zvolené sestavy](../vyber/doporuceni.md) a [návrhu software](../vyber/software-a-ci.md). Kde se tento dokument od návrhu software liší (např. formát konfigurace), platí tento dokument.

## 1. Cíl a rozsah

**Cíl:** test v pytestu ovládá DUT jen přes logická jména signálů (`dut.door_sensor`), ne přes konkrétní relé nebo port. Stejné testy běží na stanovištích s různou výbavou. Chybějící výbava znamená přeskočení testu, ne chybu.

**Úspěch:**
- celé API je spustitelné na simulovaném stanovišti bez hardwaru,
- výměna zařízení (např. relé Waveshare za Papouch Quido) znamená změnu konfigurace stanoviště, ne změnu testů ani popisu zapojení DUT,
- jeden popis zapojení DUT funguje na každém stanovišti se stejným profilem konektoru.

**Platformy:** Python 3.12 a vyšší. Linux (Debian, Raspberry Pi OS) je cíl pro provoz stanoviště. Windows je podporovaný pro vývoj balíčku a ověřování ovladačů na skutečných zařízeních.

**V rozsahu v1:**
- ovladače: Modbus RTU sběrnice, Waveshare Modbus RTU Relay 32-ch, Papouch Quido RS 2/32, obecný Modbus modul digitálních vstupů, Digilent Analog Discovery 3, sériové porty (FT4232H, USB–RS-485), OpenOCD (ST-Link),
- simulované ovladače pro všechna uvedená zařízení,
- konfigurace: profil konektoru, stanoviště, zapojení DUT, validace,
- HAL bloky a signály DUT,
- komunikace: Modbus RTU master, simulace slave, pasivní monitor s dekodérem, injektor chybných rámců, zahlcení sběrnice,
- pytest plugin, záznamy ke každému testu, CLI `hil`.

**Mimo rozsah v1:** Modbus TCP, asyncio API, simulace chování DUT, ovladače jako externí pluginy (entry points), GUI, provoz stanoviště jako služba na Windows, Advantech USB-4761.

## 2. Architektura

Vrstvy, každá závisí jen na vrstvě pod sebou:

```
ovladače zařízení   WaveshareRelay32, QuidoRelay, ModbusDI, AnalogDiscovery3, SerialPorts, OpenOCD (+ sim)
      ↓ poskytují
prostředky          RelayChannel, DigitalInput, SerialLink, AwgChannel, ScopeChannel, DebugProbe
      ↓ skládají se do
HAL bloky           PowerBlock, DigitalBlock, FaultMatrix, CommBlock, DebugBlock, AnalogBlock
      ↓ vystavují
svorky stanoviště   PWR, X1.1, AO.1, COM1, ...       (stations/*.yaml, podle profilu)
      ↓ mapuje
signály DUT         door_sensor → X1.1              (dut.yaml v repozitáři DUT)
      ↓
pytest plugin       fixture hil, dut; automatický skip; záznamy do out/<test>/
```

Bloky neznají výrobce, pracují jen s prostředky. Balíček leží v tomto repozitáři. Popis zapojení konkrétního DUT a testy leží v repozitáři DUT.

## 3. Konfigurace

Tři druhy souborů YAML, validované modely pydantic v2. Chyba validace uvádí soubor a cestu k poli.

### 3.1 Profil konektoru

Profil je seznam všech svorek, které stanoviště daného typu může mít, a jejich druhů. Profily se distribuují s balíčkem (`src/hil/profiles/`), aby je repozitář DUT měl k dispozici po instalaci.

```yaml
# profiles/standard-v1.yaml
profile: standard-v1
terminals:
  PWR: power
  X1.1: switch
  X1.2: switch
  X2.1: sense
  F1: fault_path
  AO.0: analog_out
  AO.1: analog_out
  AI.1: analog_in
  CON: serial
  LOG: serial
  COM1: rs485
  MON1: rs485_monitor
  SWD: debug
```

### 3.2 Stanoviště

Stanoviště uvádí profil, zařízení a zapojení podmnožiny svorek profilu na prostředky. Bloky se neuvádějí, vznikají z druhů zapojených svorek.

```yaml
# stations/lab-a.yaml
name: lab-a
labels: [hil, lab-a]
profile: standard-v1
devices:
  relay_bus: {driver: modbus_rtu_bus, port: /dev/serial/by-id/usb-...-if00, baud: 115200}
  rel1:   {driver: waveshare_relay32, bus: relay_bus, address: 1}
  rel2:   {driver: quido_rs_2_32,     bus: relay_bus, address: 2}
  di1:    {driver: modbus_di,         bus: relay_bus, address: 5, count: 8}
  ad3:    {driver: analog_discovery_3, serial: "210415B..."}
  ft:     {driver: serial_ports, ports: {A: {serial: "FT4ABC", interface: 0}, C: COM7, D: /dev/ttyUSB3}}
  stlink: {driver: openocd, interface: interface/stlink.cfg}
terminals:
  PWR:  {kind: power,      relays: [rel1.0, rel1.1]}
  X1.1: {kind: switch,     relay: rel1.2}
  X2.1: {kind: sense,      input: di1.0}
  F1:   {kind: fault_path, series: rel1.6, short: rel1.7}
  AO.0: {kind: analog_out, direct: ad3.awg1}
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AI.1: {kind: analog_in,  scope: ad3.ch1, connect: rel1.20}
  CON:  {kind: serial,     port: ft.A}
  COM1: {kind: rs485,      port: ft.C}
  MON1: {kind: rs485_monitor, port: ft.D}
  SWD:  {kind: debug,      probe: stlink}
```

Pravidla:
- Odkaz na prostředek má tvar `<zařízení>.<kanál>`. Názvy kanálů určuje ovladač: relé `0` až `31`, vstupy `modbus_di` `0` až `count-1`, vstupy Quido `in0` a `in1`, AD3 `awg1`, `awg2`, `ch1`, `ch2`, porty `serial_ports` podle klíčů v `ports`. Validace: zařízení existuje, ovladač kanál poskytuje, kanál je v rozsahu, žádný prostředek není použit dvakrát.
- Svorka musí být v profilu a mít v něm uvedený druh. `kind` ve stanovišti se musí s profilem shodovat.
- Sériový port lze zadat cestou (`/dev/serial/by-id/...`, `COM7`), pyserial URL (`loop://`) nebo sériovým číslem FTDI a číslem rozhraní (`{serial, interface}`). Poslední způsob funguje na Linuxu i Windows a nezávisí na pořadí připojení.
- `analog_out` má buď `direct` (rychlý kanál bez relé), nebo `select` + `connect`. Relé `select` v klidu (NC) vybírá generátor 1, sepnuté (NO) generátor 2. Relé `connect` připojuje vstup DUT, rozepnuté znamená bez signálu.
- `fault_path` má relé `series` v cestě vodiče a volitelně `short` pro zkrat na zem. Zkrat svorky označené `carries_power: true` je povolen jen s `allow_short: true` (zdroje HDR nemají proudové omezení).
- Volitelné časy: `settle_s` u `analog_in` (doba ustálení multiplexeru, výchozí 0,02 s).

### 3.3 Zapojení DUT

Leží v repozitáři DUT. Mapuje logická jména signálů na svorky profilu a nese parametry patřící k DUT.

```yaml
# dut.yaml
dut: meter-x
profile: standard-v1
signals:
  firmware:      {terminal: SWD, target: target/stm32g4x.cfg}
  supply:        PWR
  door_sensor:   X1.1
  alarm_out:     X2.1
  link_ab_rs485: F1
  sensor_in3:    AO.1
  console:       {terminal: CON, baud: 115200}
  modbus:        {terminal: COM1, baud: 921600, parity: E}
```

Pravidla:
- Profil DUT se musí shodovat s profilem stanoviště.
- Svorka mimo profil je chyba konfigurace. Svorka v profilu, kterou stanoviště nezapojuje, znamená nedostupný signál a testy, které ho použijí, se přeskočí.
- Parametry signálu patří do `dut.yaml`: u sériových svorek baud, parita a stop bity, u `debug` cíl OpenOCD (`target`).

### 3.4 Výběr souborů

Pořadí: volby pytestu `--hil-station`, `--hil-dut`, potom proměnné prostředí `HIL_STATION`, `HIL_DUT`. Hodnota stanoviště je cesta k souboru, nebo jméno vestavěného stanoviště (`sim`). Profily se hledají v balíčku, další adresář lze přidat volbou `--hil-profiles`.

## 4. Ovladače a prostředky

### 4.1 Základ ovladače

```python
@register_driver("waveshare_relay32")
class WaveshareRelay32(Device):
    Config = WaveshareRelay32Config      # bus, address, coil_base, ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    def safe_state(self) -> None: ...    # all coils off
    def channel(self, name: str) -> RelayChannel: ...
```

- Registr je interní slovník `jméno → třída`.
- Zařízení se otevírají v pořadí závislostí (sběrnice před moduly) a zavírají v opačném pořadí, vždy přes `safe_state()`.
- Každé zařízení má vlastní zámek, protože k němu přistupují vlákna záznamu i test.

### 4.2 Prostředky

| Prostředek | Rozhraní | Poskytuje |
|---|---|---|
| `RelayChannel` | `set(bool)`, `get()`; zařízení navíc `set_many({kanál: bool})` jedním rámcem | Waveshare 32-ch, Quido RS 2/32, sim |
| `DigitalInput` | `read() -> bool`; zařízení `read_all()` | `modbus_di`, Quido vstupy, sim |
| `SerialLink` | `open(params, timeout) -> serial.Serial`, `params` je `SerialParams` (parametry linky z `dut.yaml`) | `serial_ports`, sim |
| `AwgChannel` | `sine`, `square`, `dc`, `arbitrary`, `start()`, `stop()` | Analog Discovery 3, sim |
| `ScopeChannel` | `acquire(rate, n) -> numpy.ndarray` | Analog Discovery 3, sim |
| `DebugProbe` | `flash(image, target)`, `reset()`, `halt()` | OpenOCD, sim |

### 4.3 Ovladače v1

| Ovladač | Popis |
|---|---|
| `modbus_rtu_bus` | sdílený Modbus RTU master z `hil.comm`, zámek, nastavitelná minimální mezera mezi rámci (Quido odpovídá nejdřív za 2 ms) |
| `waveshare_relay32` | 32 coilů. Adresa prvního coilu a funkční kódy jsou v konfiguraci s výchozí hodnotou, protože mapa registrů není ověřena na hardwaru |
| `quido_rs_2_32` | 32 coilů a 2 vstupy, modul musí být přepnutý z protokolu Spinel do Modbus RTU. Mapa coilů neověřena, řeší se stejně jako u Waveshare |
| `modbus_di` | obecné čtení vstupů: druh (discrete inputs nebo input registry), adresa prvního vstupu, počet, inverze |
| `analog_discovery_3` | vazba `ctypes` na `libdwf.so` (Linux) nebo `dwf.dll` (Windows), knihovna se načte až v `open()`. Jeden handle pro 2 kanály AWG a 2 kanály scope |
| `serial_ports` | pyserial. Na Linuxu nastaví u FTDI latency timer na 1 ms přes sysfs. Na Windows se hodnota nekontroluje, jen se upozorní v logu (nastavuje se ve Správci zařízení) |
| `openocd` | spouští `openocd` / `openocd.exe` (PATH nebo cesta v konfiguraci) s timeoutem, výstup ukládá do záznamů |

### 4.4 Simulované ovladače

`sim_relay`, `sim_di`, `sim_serial`, `sim_ad3`, `sim_probe` poskytují stejné prostředky a drží stav v paměti. Každou změnu zaznamenají s časovým razítkem, aby na ni mohly testy balíčku dělat aserce.

- `sim_di` může zrcadlit sim relé (`mirror: {0: rel1.2}`), takže lze vytvořit smyčku stimul a odezva.
- `sim_serial` vytváří propojené virtuální páry portů (např. aktivní RS-485 a monitor, konzole a strana DUT ovladatelná z testu).
- `sim_ad3` vrací průběh odpovídající nastavení v konfiguraci (konstanta nebo sinus se šumem).
- Vestavěné stanoviště `sim` (`src/hil/stations/sim.yaml`, distribuuje se s balíčkem) zapojuje všechny svorky profilu `standard-v1` na sim ovladače. Repozitář DUT tak může spustit své testy naprázdno volbou `--hil-station sim`.

## 5. HAL bloky a signály DUT

### 5.1 Signály

Test pracuje se signály DUT. Druh objektu určuje druh svorky.

```python
def test_alarm_on_door_open(dut):
    dut.supply.on()
    dut.console.expect(r"READY", timeout=10)
    dut.door_sensor.set(True)
    t = dut.alarm_out.wait_for(True, timeout=0.5)
    assert t - dut.door_sensor.last_change < 0.050
```

| Druh svorky | Objekt | Metody |
|---|---|---|
| `power` | `PowerSignal` | `on()`, `off()`, `outage(duration_s)`, `cycle(n, on_s, off_s)` |
| `switch` | `SwitchSignal` | `set(bool)`, `pulse(duration_s)`, `last_change` |
| `sense` | `SenseSignal` | `read()`, `wait_for(state, timeout) -> čas změny`, `record()` (změny s razítky, polling ve vlákně) |
| `fault_path` | `FaultPath` | `open()`, `short_to_gnd()`, `restore()` |
| `analog_out` | `AnalogOut` | `sine(freq, amp, offset)`, `square(...)`, `dc(v)`, `arbitrary(samples, rate)`, `follow(other)`, `disconnect()` |
| `analog_in` | `AnalogIn` | `measure(duration_s=0.1) -> Measurement(dc, rms_ac)`, `capture(duration_s, rate) -> ndarray` |
| `serial` | `SerialSignal` | `write()`, `read_until()`, `expect(regex, timeout)`, záznam na pozadí s razítky |
| `rs485` | `Rs485Signal` | `modbus` (master), `slave(address, store=None)`, `send_raw(bytes)`, `inject(kind, frame)`, `flood(duration_s)` |
| `rs485_monitor` | `Rs485Monitor` | `start()`, `stop()`, `frames`, `wait_for_frame(predicate, timeout)` |
| `debug` | `DebugSignal` | `flash(image)`, `flash_interrupted(after_s)`, `reset()` |

Vstupy `sense` se čtou pollingem ve vlákně. Nejkratší perioda je dána ovladačem a rychlostí sběrnice (čtení přes Modbus trvá jednotky ms), skutečná perioda se zaznamená do `events.jsonl` a ověří HW testem (cíl řádu ms, D-03).

Časy (`last_change`, návratová hodnota `wait_for`, razítka rámců) jsou v sekundách z jednotných hodin `hil.clock.now()`, což je `time.perf_counter()`. Hodiny jsou monotónní a mají vysoké rozlišení i na Windows, kde má `time.monotonic()` před Pythonem 3.13 rozlišení asi 16 ms.

`inject(kind, frame)` podporuje: špatný CRC, zkrácený rámec, prodloužený rámec, chybnou paritu. `frames` vrací `Frame(t, raw, decoded | error)`, kde dekodér Modbus RTU rozpozná požadavky a odpovědi standardních funkcí a rámce oddělí podle mezery 3,5 znaku.

### 5.2 Bloky

Bloky `hil.power`, `hil.digital`, `hil.faults`, `hil.comm`, `hil.debug`, `hil.analog` nabízejí stejné operace nad jmény svorek (pro diagnostiku stanoviště a práci bez `dut.yaml`) a drží pravidla přes více svorek:

- **AnalogBlock:** spravuje 2 generátory. `sine()` na svorce s multiplexerem přidělí volný generátor a nastaví `select` a `connect`. Pokud jsou oba generátory obsazené, vyhodí `ResourceConflict`. `follow()` připojí další svorku na generátor jiné svorky. Měřicí multiplexer přepíná nejdřív rozepnutím, potom sepnutím, a čeká `settle_s`. Dvě svorky na jednom měřicím kanálu současně vyhodí `ResourceConflict`.
- **FaultMatrix:** `restore_all()`, pravidlo `allow_short` (kap. 3.2).
- **PowerBlock:** `emergency_off()` rozepne napájecí relé bez čekání na zámky ostatních operací. `outage()` přepíná oba póly jedním rámcem a dobu odměřuje `time.perf_counter()`. Skutečná přesnost závisí na relé a latenci Modbusu a ověří se HW testem (cíl odchylka pod 10 ms).
- Změny více relé jednoho zařízení v jedné operaci jdou jedním rámcem (`set_many`).

### 5.3 Bezpečný stav

Napájení DUT vypnuto, všechny poruchy obnoveny, generátory zastaveny a odpojeny, stimuly vypnuty, ostatní relé rozepnuta. Nastavuje se při otevření stanoviště, po každém testu, při chybě, při ukončení procesu (`atexit`, SIGINT a SIGTERM na Linuxu, SIGINT a SIGBREAK na Windows) a příkazem `hil safe`.

## 6. pytest plugin

Registruje se přes entry point `pytest11` a aktivuje se instalací balíčku.

- **Volby:** `--hil-station`, `--hil-dut`, `--hil-out` (výchozí `out/`), `--hil-profiles`.
- **Fixture `hil`** (scope `session`): načte a zvaliduje konfiguraci, zamkne stanoviště, otevře zařízení, nastaví bezpečný stav. Na konci session zavře zařízení a uvolní zámek.
- **Fixture `dut`** (scope `function`): signály DUT. Po testu, i neúspěšném, nastaví bezpečný stav a uloží záznamy.
- **Automatický skip:** přístup k nedostupnému signálu vyhodí `SignalUnavailable` a plugin test přeskočí s důvodem (např. „svorka AO.1 není na stanovišti lab-b zapojena“). Marker `@pytest.mark.hil_requires("sensor_in3", "modbus")` přeskočí test ještě před jeho spuštěním.
- **Zámek stanoviště:** balíček `filelock`, soubor `hil-<stanoviště>.lock` v adresáři pro zámky platformy (Linux `/run/lock`, jinak dočasný adresář). Doplňuje `concurrency` v GitHub Actions o ochranu proti souběhu ručního běhu a CI.

### 6.1 Záznamy

Ke každému testu v `out/<id testu>/`:

| Soubor | Obsah |
|---|---|
| `serial-<signál>.log` | řádky sériového logu s razítkem |
| `rs485-<signál>.jsonl` | rámce s razítkem, dekódováním nebo chybou |
| `events.jsonl` | změny relé, vstupů, napájení, generátorů, poruch |
| `measurements.jsonl` | výsledky `measure()` |
| `openocd.log` | výstup OpenOCD |

Razítka jsou relativní ke startu testu, první řádek souboru nese čas startu (UTC). JUnit XML vytváří pytest volbou `--junitxml`.

## 7. Chyby a logování

- Hierarchie: `HilError` → `ConfigError`, `DeviceError` (`DeviceNotFound`, `DeviceTimeout`), `SignalUnavailable`, `ResourceConflict`.
- `ConfigError` při startu ukončí session se zprávou obsahující soubor a cestu k poli.
- `DeviceError` během testu: test selže a stanoviště přejde do bezpečného stavu. Pokud bezpečný stav nastavit nejde, plugin ukončí session (`pytest.exit`).
- Logování standardním modulem `logging`, loggery `hil.*`.

## 8. CLI

| Příkaz | Účel |
|---|---|
| `hil check --station S [--dut D] [--probe]` | validace konfigurace; s `--probe` otevře zařízení a ověří jejich dostupnost |
| `hil safe --station S` | nastaví bezpečný stav, na Linuxu ho volá služba systemd při startu PC (NF-03) |
| `hil info --station S` | vypíše zařízení, svorky a bloky |

## 9. Struktura repozitáře

```
pyproject.toml              # hatchling, requires-python >=3.12, entry points: hil, pytest11
src/hil/
  config/                   # pydantic models: profile, station, dut; loader, reference parser
  drivers/
    base.py registry.py     # Device, register_driver, dependency ordering
    modbus_bus.py waveshare_relay.py quido.py modbus_di.py
    analog_discovery.py dwf.py
    serial_ports.py openocd.py
    sim/
  resources.py
  blocks/                   # power, digital, faults, comm, debug, analog
  signals/                  # signal classes, Dut; rs485.py: monitor, injection, flooding
  comm/                     # Modbus RTU codec and CRC, master, slave;
                            # faults.py, framing.py: helpers of injection and monitor
  recording.py
  station.py                # Station: devices -> blocks -> terminals, safe state
  pytest_plugin.py  cli.py  errors.py
  profiles/standard-v1.yaml
  stations/sim.yaml         # built-in station "sim"
stations/lab-a.yaml         # real stations, versioned here
examples/dut.yaml  examples/tests/
tests/                      # unit and integration tests on the sim station
tests/hw/                   # hardware checks, marker hw
doc/software/               # user documentation
```

**Závislosti:** `pydantic>=2`, `pyyaml`, `pyserial`, `filelock`, `pytest`. WaveForms SDK (s Adept runtime) a OpenOCD jsou systémové programy, potřebné jen pro příslušný ovladač. Modbus RTU (master, slave, kodek) je vlastní implementace v `hil.comm`. numpy přibude s analogovou částí.

## 10. Testování balíčku

- **Unit testy:** parser konfigurace a odkazů, validační pravidla (duplicitní prostředek, svorka mimo profil, nesoulad druhu, `allow_short`), Modbus codec a CRC proti známým rámcům, přidělování generátorů a multiplexer, pořadí otevírání zařízení.
- **Integrační testy na stanovišti `sim`:** celé API přes sim ovladače, plugin přes `pytester` (skip nedostupného signálu, bezpečný stav po selhání testu, obsah `out/`).
- **Ovladače relé a DI:** proti simulovanému slave `hil.comm.slave.ModbusSlave` na portu ovladače `sim_serial`. Ověří se odesílané rámce, ne skutečný modul.
- **HW testy** (`tests/hw/`, marker `hw`, spouští se ručně na stanovišti nebo na vývojovém PC s připojeným zařízením): mapa coilů relé, výchozí stav relé po zapnutí, přesnost `outage()`, AD3 generování a měření, latency timer FTDI. Odpovídají bodům „Co ověřit při stavbě“ v [doporuceni.md](../vyber/doporuceni.md).
- **CI balíčku:** GitHub Actions, matice `ubuntu-latest` a `windows-latest`, Python 3.12 až 3.14. Kroky: ruff, mypy (strict pro `hil.config`, `hil.blocks`, `hil.signals`, `hil.comm`), pytest bez HW testů.

## 11. Nasazení

Popíše se v `doc/software/`:
- **Linux (Debian, Raspberry Pi OS):** pravidla udev (skupina `dialout`, přístup k AD3), služba systemd volající `hil safe` při startu, instalace WaveForms a Adept runtime (ARM64 podle návodu Digilentu), OpenOCD z distribuce.
- **Windows (vývoj):** ovladač FTDI VCP a nastavení latency timeru, instalace WaveForms, OpenOCD v PATH.

## 12. Pokrytí požadavků

| Požadavek | Pokrytí |
|---|---|
| HW-DIG-01 až 04 | `switch`, `sense` (kap. 5.1) |
| HW-PWR-01 až 03 | `power`, `PowerBlock.emergency_off()`, bezpečný stav |
| HW-FLT-01, 02, 04 | `fault_path`, `FaultMatrix`; počet cest dán konfigurací |
| HW-COM-01 až 06 | `rs485`, `rs485_monitor`, `serial`, `comm/` |
| HW-DBG-01 až 03 | `debug`, `flash_interrupted()`, outage napájení |
| HW-ANA-01 až 03, 05 až 07 | `analog_out`, `analog_in`, `AnalogBlock` |
| SW-01 | pytest plugin |
| SW-02 | vrstvy prostředků a bloků (kap. 2) |
| SW-03 | záznamy (kap. 6.1), JUnit XML z pytestu |
| SW-04 | zámek stanoviště, `concurrency` v GitHub Actions |
| SW-05, NF-05, NF-06 | profil, stanoviště a `dut.yaml` v gitu; skip nedostupných signálů |
| NF-03 | `hil safe` ve službě systemd |

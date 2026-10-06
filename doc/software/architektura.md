# Architektura balíčku `hil`

Balíček obsahuje ovladače zařízení HIL stanoviště, definici platformy (HAL bloky a konfiguraci stanoviště) a popis zapojení vůči DUT. Požadavky jsou ve [specifikaci](../hil-specifikace.md), zvolená sestava v [doporuceni.md](../vyber/doporuceni.md). Dokument [software-a-ci.md](../vyber/software-a-ci.md) je podklad z výběru platformy. Kde se od tohoto dokumentu liší (např. pymodbus místo vlastní implementace Modbus RTU, návrhové metody bloků jako `generate` nebo `press_button`), platí tento dokument a kód.

Uživatelská dokumentace: [konfigurace](konfigurace.md), [psaní a spouštění testů](testy.md), [nasazení](nasazeni.md), [HW testy](hw-testy.md).

## 1. Cíl a rozsah

**Cíl:** test v pytestu ovládá DUT jen přes logická jména signálů (`dut.door_sensor`), ne přes konkrétní relé nebo port. Stejné testy běží na stanovištích s různou výbavou. Chybějící výbava znamená přeskočení testu, ne chybu.

**Kritéria:**
- celé API je spustitelné na simulovaném stanovišti bez hardwaru,
- výměna zařízení (např. relé Waveshare za Papouch Quido) znamená změnu konfigurace stanoviště, ne změnu testů ani popisu zapojení DUT,
- jeden popis zapojení DUT funguje na každém stanovišti se stejným profilem konektoru.

**Platformy:** Python 3.12 a vyšší. Linux (Debian, Raspberry Pi OS) je cíl pro provoz stanoviště. Windows je podporovaný pro vývoj balíčku a ověřování ovladačů na skutečných zařízeních.

**Co balíček umí:**
- ovladače: Modbus RTU sběrnice, Waveshare Modbus RTU Relay 32-ch, Papouch Quido RS 2/32, obecný Modbus modul digitálních vstupů, Digilent Analog Discovery 3, sériové porty (FT4232H, USB–RS-485), OpenOCD (ST-Link),
- simulované ovladače pro všechna uvedená zařízení a vestavěné stanoviště `sim`,
- konfigurace: profil konektoru, stanoviště, zapojení DUT, validace,
- HAL bloky a signály DUT,
- komunikace: Modbus RTU master, simulace slave, pasivní monitor s dekodérem, injektor chybných rámců, zahlcení sběrnice,
- pytest plugin, záznamy ke každému testu, CLI `hil`.

**Mimo rozsah:** Modbus TCP, asyncio API, simulace chování DUT, ovladače jako externí pluginy (entry points), GUI, provoz stanoviště jako služba na Windows, Advantech USB-4761.

Balíček byl vyvinut bez hardwaru. Ovladače jsou ověřené proti simulaci a falešným knihovnám, co zbývá ověřit na stanovišti, uvádí [hw-testy.md](hw-testy.md#předpoklady-neověřené-na-hardwaru).

## 2. Vrstvy

Každá vrstva závisí jen na vrstvě pod sebou:

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

Bloky neznají výrobce, pracují jen s prostředky. Balíček, profily, stanoviště a ovladače leží v tomto repozitáři. Popis zapojení konkrétního DUT (`dut.yaml`) a jeho testy leží v repozitáři DUT.

`Station` (`station.py`) vytvoří zařízení, otevře je, z druhů zapojených svorek sestaví signály a bloky a drží bezpečný stav. `Dut` (`dut.py`) mapuje jména signálů z `dut.yaml` na signály stanoviště.

## 3. Konfigurace

Tři druhy souborů YAML: profil konektoru, stanoviště a zapojení DUT. Validují je modely pydantic v2. Formát, pravidla svorek, volby ovladačů a parametry signálů popisuje [konfigurace.md](konfigurace.md). Zásady:

- **Profil** je seznam všech svorek, které stanoviště daného typu může mít, a jejich druhů. Profily se distribuují s balíčkem (`src/hil/profiles/`), aby je repozitář DUT měl k dispozici po instalaci.
- **Stanoviště** uvádí profil, zařízení a zapojení podmnožiny svorek profilu na prostředky (`<zařízení>.<kanál>`). Bloky se neuvádějí, vznikají z druhů zapojených svorek. Validuje se existence zařízení a kanálu, shoda druhu s profilem a to, že žádný prostředek není použit dvakrát (výjimky: měřicí multiplexer, generátor v sekci `analog` a zároveň `direct`).
- **Zapojení DUT** mapuje logická jména signálů na svorky profilu a nese parametry patřící k DUT (parametry sériové linky, cíl OpenOCD). Profil DUT se musí shodovat s profilem stanoviště. Svorka v profilu, kterou stanoviště nezapojuje, znamená nedostupný signál a přeskočení testů, ne chybu.
- **Konvence kontaktů relé** (`power` a `switch` NO, `series` u `fault_path` NC, `short` NO na zem, `select` v klidu NC vybírá generátor 1) je popsaná v [konfigurace.md](konfigurace.md#stanoviště).
- **Výběr souborů:** volby pytestu `--hil-station`, `--hil-dut`, potom proměnné `HIL_STATION`, `HIL_DUT`. Hodnota stanoviště je cesta nebo jméno vestavěného stanoviště (`sim`). Chybějící stanoviště (bez volby i proměnné, nebo `HIL_STATION=""`) je chyba, ne přeskočení.

**Chybný vstup je `ConfigError`, ne traceback.** Prázdný soubor, kanál zapsaný nekanonicky (`05`), odkaz zapsaný jako číslo, překlep v parametru signálu (`buad`), parametry u signálu bez parametrů, neznámý ovladač nebo cyklus v závislostech zařízení: vždy `ConfigError` se souborem a cestou k poli, nikdy výjimka pydantic nebo YAML.

## 4. Ovladače a prostředky

### 4.1 Základ ovladače

```python
@register_driver("waveshare_relay32")
class WaveshareRelay32(Device):
    class Config(DriverConfig):          # pydantic, extra="forbid", frozen
        bus: str
        address: int
    def dependencies(self) -> list[str]: ...        # e.g. [self.config.bus]
    def bind(self, devices: Mapping[str, Device]) -> None: ...   # resolve the bus object
    def channel_names(self) -> Collection[str]: ...
    def resource(self, channel: str) -> object: ...  # RelayChannel, DigitalInput, ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    def safe_state(self) -> None: ...    # all coils off
```

- Registr (`drivers/registry.py`) je interní slovník `jméno → třída`. Volby zařízení ze stanoviště validuje vnořený `Config`, chyba je `ConfigError`.
- Konstruktor nedělá I/O, hardware se otevírá až v `open()`. `open`, `close` a `safe_state` hlásí selhání jako `DeviceError` nebo podtřídu.
- `open_order()` seřadí zařízení podle `dependencies()` (`graphlib.TopologicalSorter`, sběrnice před moduly). Neznámá závislost nebo cyklus je `ConfigError`. Zavírá se v opačném pořadí, vždy přes `safe_state()`.
- Každé zařízení má vlastní `RLock` (`device.lock`), protože k němu přistupují vlákna záznamu i test.

### 4.2 Prostředky

| Prostředek | Rozhraní | Poskytuje |
|---|---|---|
| `RelayChannel` | `set(bool)`, `get()`; banka relé (`RelayBank`) má `set_many({index: bool})` jedním rámcem, funkce `set_relays()` seskupí změny více kanálů po bankách | Waveshare 32-ch, Quido RS 2/32, sim |
| `DigitalInput` | `read() -> bool`; `modbus_di` navíc `read_all()` | `modbus_di`, Quido vstupy, sim |
| `SerialLink` | `open(params, timeout) -> serial.Serial`, `params` je `SerialParams` (parametry linky z `dut.yaml`) | `serial_ports`, sim |
| `AwgChannel` | `sine`, `square`, `dc`, `arbitrary`, `apply(Waveform)`, `start()`, `stop()` | Analog Discovery 3, sim |
| `ScopeChannel` | `acquire(rate, n) -> numpy.ndarray` | Analog Discovery 3, sim |
| `DebugProbe` | `flash(image, target, timeout_s, abort_after_s)`, `reset(target, timeout_s)`, `halt(target, timeout_s)`, vrací `ProbeResult` (výstup, návratový kód, doba, přerušeno, timeout); signál výstup uloží a chybu převede na `DeviceError` | OpenOCD, sim |

### 4.3 Ovladače

Volby a kanály ovladačů jsou v [konfigurace.md](konfigurace.md#stanoviště). Návrhová rozhodnutí:

| Ovladač | Popis |
|---|---|
| `modbus_rtu_bus` | sdílený Modbus RTU master z `hil.comm`. Sběrnici drží jedno vlákno, ostatní čekají nejvýš `lock_timeout_s`, pak `DeviceTimeout` (ne deadlock). Minimální mezera mezi rámci `min_gap_s` (výchozí větší z 3,5 znaku a 2 ms, Quido odpovídá nejdřív za 2 ms). Odpověď na zápis (FC5, 6, 15, 16) se kontroluje proti požadavku |
| `waveshare_relay32` | 32 coilů. Adresa prvního coilu a způsob zápisu jsou volby s výchozí hodnotou (coily 0 až 31, zápis FC05/FC15, čtení FC01), protože mapa registrů není ověřena na hardwaru. Modul, který při `open()` neodpovídá, je `DeviceNotFound` se jménem zařízení, adresou a sběrnicí |
| `quido_rs_2_32` | 32 coilů a 2 vstupy (výchozí coily 0 až 31, vstupy jako discrete inputs 0 a 1), modul musí být přepnutý z protokolu Spinel do Modbus RTU. Mapa není ověřena na hardwaru, upravuje se volbami jako u Waveshare |
| `modbus_di` | obecné čtení vstupů: zdroj (discrete inputs, nebo input registry po 16 vstupech od nejnižšího bitu), adresa prvního vstupu, počet, inverze. Všechny vstupy se čtou jedním požadavkem |
| `analog_discovery_3` | vazba `ctypes` (`drivers/dwf.py`) na `libdwf.so` (Linux) nebo `dwf.dll` (Windows), knihovna se načte až v `open()`. Jeden handle pro 2 kanály AWG a 2 kanály scope, scope ±25 V. Viz kap. 4.4 |
| `serial_ports` | pyserial. Na Linuxu nastaví u FTDI latency timer na 1 ms přes sysfs. Na Windows se hodnota nekontroluje, jen se upozorní v logu |
| `openocd` | spouští `openocd` / `openocd.exe` (PATH nebo cesta v konfiguraci) s timeoutem, výstup ukládá do záznamů. Používá `adapter serial` a `adapter speed`, potřebuje OpenOCD 0.12 nebo novější (viz [nasazeni.md](nasazeni.md)). Chybějící program je `DeviceNotFound` |

### 4.4 Analog Discovery 3

- `DwfParamOnClose = 2` (shutdown), ne stop. Stop by po zavření nechal na výstupu klidovou úroveň s DC offsetem. Po zavření zařízení generátory neběží a výstupy jsou vypnuté.
- AutoConfigure je vypnuté. Nastavení generátoru se aplikuje najednou voláním `FDwfAnalogOutConfigure`, takže změna běžícího průběhu nedorazí do DUT po parametrech (např. nová amplituda kolem starého offsetu) a zastavený generátor nedává mezilehlé offsety.
- Bezpečný stav je zastavený generátor s 0 V.
- Záznam do velikosti bufferu scope se pořídí v režimu single. Delší záznam běží v režimu record s neomezenou délkou a končí po sebrání `n` vzorků. Čekání je omezeno na `n / rate + 2 s`, pak `DeviceTimeout`. Ztracené nebo poškozené vzorky a neúplný záznam jsou `DeviceError`.
- Zařízení otevřené jiným programem (WaveForms) je `DeviceNotFound`.

### 4.5 Simulace

`sim_relay`, `sim_di`, `sim_serial`, `sim_ad3`, `sim_probe` poskytují stejné prostředky a drží stav v paměti. Každou změnu zaznamenají s časovým razítkem, aby na ni mohly testy balíčku dělat aserce.

- `sim_di` může zrcadlit sim relé (`mirror: {0: rel1.2}`), takže lze vytvořit smyčku stimul a odezva.
- `sim_serial` vytváří propojené virtuální sběrnice portů. Registruje vlastní URL handler pyserialu `hilsim://<klíč>/<port>`, takže simulované porty jsou plnohodnotné objekty pyserialu. `SerialSignal`, `ModbusMaster` i `ModbusSlave` běží nad stejným rozhraním jako na skutečném portu.
- `sim_ad3` drží nastavení generátorů v paměti a jako vstup scope vrací průběh z konfigurace, který lze z testu změnit metodou `set_input()`. DUT mezi generátorem a scope se nesimuluje.
- `sim_probe` zaznamenává volání `flash`, `reset` a `halt` a umí nasimulovat selhání.
- Vestavěné stanoviště `sim` (`src/hil/stations/sim.yaml`) zapojuje všechny svorky profilu `standard-v1` na sim ovladače. Repozitář DUT tak může spustit své testy naprázdno volbou `--hil-station sim`.

## 5. Signály a bloky

### 5.1 Signály

Test pracuje se signály DUT. Druh objektu určuje druh svorky (`PowerSignal`, `SwitchSignal`, `SenseSignal`, `FaultPath`, `AnalogOut`, `AnalogIn`, `SerialSignal`, `Rs485Signal`, `Rs485Monitor`, `DebugSignal`). Metody signálů a jejich chyby popisuje [testy.md](testy.md#signály).

```python
def test_alarm_on_door_open(dut):
    dut.supply.on()
    dut.console.expect(r"READY", timeout=10)
    dut.door_sensor.set(True)
    t = dut.alarm_out.wait_for(True, timeout=0.5)
    assert t - dut.door_sensor.last_change < 0.050
```

- Vstupy `sense` se čtou pollingem ve vlákně. Nejkratší perioda je dána ovladačem a rychlostí sběrnice (čtení přes Modbus trvá jednotky ms). Skutečná perioda se zaznamená do `events.jsonl`, na stanovišti ji měří HW test (cíl řádu ms, D-03).
- Časy (`last_change`, návratová hodnota `wait_for`, razítka rámců) jsou v sekundách z jednotných hodin `hil.clock.now()`, což je `time.perf_counter()`. Hodiny jsou monotónní a mají vysoké rozlišení i na Windows, kde má `time.monotonic()` před Pythonem 3.13 rozlišení asi 16 ms.
- Porty komunikačních signálů se otevírají s timeoutem čtení 0,01 s (`PortSignal.read_timeout_s`), aby čtecí vlákna rychle reagovala na zastavení.
- `inject(kind, frame)` podporuje špatný CRC, zkrácený rámec, prodloužený rámec a chybnou paritu. Monitor dekóduje požadavky a odpovědi standardních funkcí Modbus RTU a rámce dělí podle mezery `frame_gap_s` (výchozí 3,5 znaku, alespoň 1,5 ms) a podle CRC.

### 5.2 Bloky

Bloky `hil.power`, `hil.digital`, `hil.faults`, `hil.comm`, `hil.debug`, `hil.analog` nabízejí stejné operace nad jmény svorek (pro diagnostiku stanoviště a práci bez `dut.yaml`) a drží pravidla přes více svorek:

- **PowerBlock:** `emergency_off()` rozepne napájecí relé bez čekání na zámky ostatních operací. `outage()` přepíná všechny póly jedním rámcem a dobu odměřuje `hil.clock`. Skutečná přesnost závisí na relé a latenci Modbusu, cíl je odchylka pod 10 ms a na stanovišti ji měří HW test.
- **FaultMatrix:** `restore_all()`, pravidlo `allow_short` u svorek s napájením (zdroje HDR nemají proudové omezení).
- Změny více relé jednoho zařízení v jedné operaci jdou jedním rámcem (`set_many`).
- **AnalogBlock** přidává přístup podle jména k pravidlům, která drží `AnalogRouter` (výstupy) a `ScopeMux` (měřicí kanály) v `signals/analog.py`.

### 5.3 Pravidla analogu

Stanoviště má 2 generátory ze sekce `analog`. Generátor je volný, když k němu není připojena žádná svorka.

- Průběh na svorce s multiplexerem, která ještě generátor nemá, přidělí volný generátor. Přednost má generátor bez svorky `direct`, aby rychlý kanál zůstal volný. Pokud volný generátor není, vyhodí `ResourceConflict`. Svorka `direct` má generátor pevně daný. Pokud ho používají svorky přes multiplexer, vyhodí `ResourceConflict`.
- Pořadí přepnutí: nastavit a spustit generátor, potom `select` (jen při změně, předtím se rozepne `connect`), potom `connect`. Každý krok je jeden rámec, takže DUT nedostane ani na okamžik signál druhého generátoru.
- `follow(other)` připojí svorku na generátor svorky `other`. Generátor je pak sdílený a změna průběhu na kterékoli z připojených svorek platí pro všechny. Samostatný signál vyžaduje nejdřív `disconnect()`.
- `disconnect()` rozepne `connect`. Když ke generátoru nezůstane připojena žádná svorka, generátor se zastaví a uvolní.
- Svorka `direct` je na generátor zapojená trvale. Když generátor používá multiplexer, signál je i na ní. Zaznamená se to do `events.jsonl` (`shared_generator`).
- `measure(duration_s=0.1)` vzorkuje 100 kHz (desetinásobek šířky pásma 10 kHz z HW-ANA-07) a vrací `Measurement(dc, rms_ac)`: průměr a RMS po odečtení průměru.
- Měřicí multiplexer přepíná nejdřív rozepnutím `connect` jiné svorky na stejném kanálu, potom sepnutím vlastní, a čeká `settle_s`. Po měření zůstane svorka připojená, dokud kanál nepotřebuje jiná svorka. Dvě měření na jednom kanálu současně vyhodí `ResourceConflict`.

Invarianty:
- Napětí mimo rozsah generátoru nebo arbitrární průběh delší než buffer je `ValueError` dřív, než se přepne relé. Generátor zůstane volný.
- Selže-li zápis relé uprostřed přepínání výstupu, generátor nezůstane běžet bez svorky a přidělení se neztratí.
- **Bezpečný stav analogu:** generátory zastaveny s 0 V a uvolněny, relé `connect` a `select` rozepnuta. Generátory se uvolní, i když zápis relé selže.
- Po bezpečném stavu (relé `connect` rozepnuto) další `measure()` na téže svorce relé znovu sepne a počká `settle_s`.

## 6. Bezpečný stav a ukončení

Bezpečný stav: napájení DUT vypnuto, všechny poruchy obnoveny, generátory zastaveny a odpojeny, stimuly vypnuty, ostatní relé rozepnuta. Kdy se nastavuje (otevření stanoviště, po každém testu, při chybě, při ukončení procesu, `hil safe`) a jak se chová `hil safe`, popisují [testy.md](testy.md) a [nasazeni.md](nasazeni.md).

Ukončení procesu:
- Signály SIGINT, SIGTERM a SIGHUP na Linuxu, SIGINT a SIGBREAK na Windows. Obsluha signálu nekomunikuje se zařízeními, jen vyhodí výjimku `TerminationRequested`. Kdyby obsluha sahala na sběrnici, mohla by vložit vlastní rámec doprostřed rozeslaného rámce.
- `TerminationRequested` je podtřída `KeyboardInterrupt`, ne `HilError`. Pytest bere `SystemExit` v testu jako selhání testu a pokračoval by dalším testem, `KeyboardInterrupt` ukončí session a spustí úklid fixtures.
- Rozpracovaná transakce na sběrnici se přeruší a sběrnice zůstane potichu až do konce jejího timeoutu, aby se pozdní odpověď modulu nesrazila s vypnutím napájení. Zásobník se odvine a úklid (`Station.close()`, teardown pytestu) nastaví úplný bezpečný stav.
- Další signál během ukončování nebo během `Station.close()` se jen zaloguje, aby nepřerušil nastavování bezpečného stavu. Signál, který je ignorovaný (SIGHUP pod `nohup`), zůstane ignorovaný.
- `atexit` je záloha pro případ, že úklid neproběhl. Volá jen `emergency_off()` (vypnutí napájení DUT bez čekání na zámky ostatních operací), protože jiná vlákna mohou v tu chvíli držet zámky zařízení. Zámek sběrnice čeká s timeoutem.

## 7. pytest plugin a souběh

Plugin se registruje přes entry point `pytest11` a aktivuje se instalací balíčku. Volby (`--hil-station`, `--hil-dut`, `--hil-out`, `--hil-profiles`, `--hil-lock-timeout`), fixtures, přeskakování a záznamy popisuje [testy.md](testy.md).

- **Fixture `hil`** (scope `session`): načte a zvaliduje konfiguraci, zamkne stanoviště, otevře zařízení, nastaví bezpečný stav. Na konci session zavře zařízení a uvolní zámek.
- **Fixture `dut`** (scope `function`): signály DUT. Po testu, i neúspěšném, nastaví bezpečný stav a uloží záznamy.
- **Automatický skip:** přístup k nedostupnému signálu vyhodí `SignalUnavailable` a plugin test přeskočí s důvodem. Marker `hil_requires` přeskočí test ještě před spuštěním.
- **Zámek stanoviště** (`locking.py`): `filelock`, soubor `hil-<stanoviště>.lock` v `/run/lock` na Linuxu (sdílený pro celý stroj), jinak v dočasném adresáři. Doplňuje `concurrency` v GitHub Actions o ochranu proti souběhu ručního běhu a CI. Obsazené stanoviště je `StationLocked`.
- **Ukončení session:** chyba konfigurace je `pytest.exit` s kódem 4 (`USAGE_ERROR`), selhání stanoviště (zámek, otevření, bezpečný stav) kódem 3.

## 8. Chyby a logování

| Výjimka | Význam |
|---|---|
| `HilError` | základ chyb balíčku |
| `ConfigError` | neplatný profil, stanoviště nebo `dut.yaml`; zpráva uvádí soubor a cestu k poli |
| `DeviceError` | selhání zařízení; podtřídy `DeviceNotFound` (zařízení chybí nebo ho drží jiný program) a `DeviceTimeout` (zařízení neodpovědělo) |
| `SignalUnavailable` | svorka není na stanovišti zapojena, test se přeskočí |
| `ResourceConflict` | dvě operace potřebují tentýž prostředek současně |
| `OperationNotAllowed` | operace není v aktuálním stavu nebo konfigurací povolena |
| `WaitTimeout` | očekávaný stav DUT nenastal včas; i podtřída `TimeoutError` |
| `ModbusExceptionResponse` (`hil.comm.master`) | zařízení Modbus odpovědělo výjimkou (atribut `code`) |
| `StationLocked` (`hil.locking`) | stanoviště používá jiný proces |
| `TerminationRequested` | podtřída `KeyboardInterrupt`, viz kap. 6 |

- `ConfigError` při startu ukončí session.
- `DeviceError` během testu: test selže a stanoviště přejde do bezpečného stavu. Pokud bezpečný stav nastavit nejde, plugin ukončí session.
- `ModbusExceptionResponse` převádějí ovladače na `DeviceError`. Master signálu `rs485` ji předává testu beze změny.
- Logování standardním modulem `logging`, loggery `hil.*`.

## 9. CLI

Příkazy `hil check`, `hil safe` a `hil info` přijímají `--station` a `--profiles <adresář>` (opakovatelné). Použití je v [testy.md](testy.md#příkazová-řádka).

- `hil check [--dut D] [--probe]` validuje konfiguraci, s `--probe` otevře zařízení.
- `hil safe` nastaví bezpečný stav, na Linuxu ho volá služba systemd při startu PC (NF-03). Pracuje best-effort: otevře zařízení, která jdou, nastaví na nich bezpečný stav a chyby ostatních vypíše.
- `hil info` vypíše zařízení, svorky a bloky.
- Návratové kódy všech příkazů: 0 v pořádku, 2 chyba konfigurace, 3 chyba zařízení nebo stanoviště používané jiným procesem.

## 10. Rozhodnutí

- **Vlastní Modbus RTU místo pymodbus.** Injektáž poruch a monitor potřebují řízení na úrovni bajtů. API pymodbus se mezi verzemi 3.x mění (`slave=` na `device_id=`). Vlastní kodek, master a slave jsou menší než obal nad cizí knihovnou s vlastními vlákny. Konvence: adresa 0 je broadcast, CRC nižším bajtem napřed, registry big-endian, bity LSB first.
- **`perf_counter` jako hodiny** (kap. 5.1), **`TerminationRequested` jako `KeyboardInterrupt`** a **obsluha signálu bez přístupu ke sběrnici** (kap. 6), **pořadí přepnutí multiplexeru** (kap. 5.3), **`DwfParamOnClose` shutdown** (kap. 4.4).
- **Simulace jako ovladače.** Sim ovladače poskytují stejné prostředky jako skutečné, takže celý zbytek balíčku se testuje bez hardwaru.

## 11. Konvence kódu

- Kód, komentáře, zprávy výjimek a výstup CLI anglicky, dokumentace česky.
- Všechna časová razítka z `hil.clock.now()`.
- Zařízení se vytvoří bez I/O.
- Vlákna jsou `daemon` a zastavují se v `safe_state()` nebo `close()`.
- Obsluha signálu procesu nesmí komunikovat se zařízeními.
- Kontrola před commitem: `ruff format`, `ruff check`, `mypy` (strict pro `hil.config`, `hil.blocks`, `hil.signals`, `hil.comm`), `pytest` a příklady `pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml`.

## 12. Rozšiřování

**Nový ovladač:**
1. Třída odvozená z `Device` s `@register_driver("jméno")` a vnořeným `Config` (podtřída `DriverConfig`).
2. Konstruktor bez I/O, hardware jen v `open()`. Selhání `open`, `close` a `safe_state` jako `DeviceError` nebo podtřída. `ModbusExceptionResponse` převést na `DeviceError`.
3. Závislosti přes `dependencies()` a `bind()`, kanály přes `channel_names()` a `resource(kanál)`.
4. Modul přidat do `hil/drivers/__init__.py` (import i `__all__`), jinak se ovladač nezaregistruje.
5. Ke každému ovladači patří sim varianta nebo falešná knihovna pro testy (`FakeDwf`, `tests/drivers/fake_openocd.py`, `ModbusSlave` na portu `sim_serial`).

**Nový druh svorky:**
1. Druh v modelech konfigurace (`config/models.py`). Druh, který modely znají a stanoviště ho neumí sestavit, odmítne `Station` chybou „kind ... is not supported“.
2. Signálová třída v `signals/`, sestavení v `Station._build`, operace v bloku v `blocks/`.
3. Zapojení ve stanovišti `sim`, v profilu `standard-v1` a výpis v `hil info`.

## 13. Struktura repozitáře

```
pyproject.toml              # hatchling, requires-python >=3.12, entry points: hil, pytest11
src/hil/
  config/                   # pydantic models: profile, station, dut; loader, reference parser
  drivers/
    base.py registry.py     # Device, DriverConfig, register_driver, open_order
    modbus_bus.py modbus_relay.py waveshare_relay.py quido.py modbus_di.py
    analog_discovery.py dwf.py   # driver; thin ctypes layer over libdwf
    serial_ports.py openocd.py
    sim/                    # relay, di, serial_port, serial_bus, protocol_hilsim, ad3, probe
  resources.py
  blocks/                   # power, digital, faults, comm, debug, analog; _lookup
  signals/                  # signal classes; port (serial base), uart, rs485, timing (precise_sleep)
  comm/                     # Modbus RTU codec and CRC, master, slave;
                            # faults.py, framing.py: helpers of injection and monitor
  clock.py                  # hil.clock.now()
  locking.py                # station lock, StationLocked
  dut.py                    # Dut: signal names from dut.yaml
  recording.py
  station.py                # Station: devices -> blocks -> terminals, safe state
  pytest_plugin.py  cli.py  errors.py
  profiles/standard-v1.yaml
  stations/sim.yaml         # built-in station "sim"
stations/lab-a.yaml         # real stations, versioned here
examples/dut.yaml  examples/tests/
deploy/udev/ deploy/systemd/   # FTDI udev rule, hil-safe service
tests/                      # unit and integration tests on the sim station:
                            # blocks/ comm/ config/ drivers/ signals/
tests/hw/                   # hardware checks, marker hw
doc/software/               # architecture and user documentation
.github/workflows/package.yml
```

**Závislosti:** `pydantic>=2.6`, `pyyaml>=6.0`, `filelock>=3.12`, `pytest>=8.1`, `pyserial>=3.5`, `numpy>=1.26`. Vývojové nástroje (`ruff`, `mypy`, `types-PyYAML`, `types-pyserial`) jsou v extras `dev`. WaveForms SDK (s Adept runtime) a OpenOCD jsou systémové programy, potřebné jen pro příslušný ovladač. Modbus RTU (master, slave, kodek) je vlastní implementace v `hil.comm`.

## 14. Testování balíčku

- **Unit testy:** parser konfigurace a odkazů, validační pravidla (duplicitní prostředek, svorka mimo profil, nesoulad druhu, `allow_short`), Modbus kodek a CRC proti známým rámcům, přidělování generátorů a multiplexer, pořadí otevírání zařízení.
- **Integrační testy na stanovišti `sim`:** celé API přes sim ovladače, plugin přes `pytester` (skip nedostupného signálu, bezpečný stav po selhání testu, obsah `out/`).
- **Ovladače relé a DI:** proti simulovanému slave `hil.comm.slave.ModbusSlave` na portu `sim_serial`. Ověřují se odesílané rámce, ne skutečný modul. AD3 se testuje proti `FakeDwf`, OpenOCD proti `tests/drivers/fake_openocd.py`.
- **HW testy** (`tests/hw/`, marker `hw`): body „Co ověřit při stavbě“ z [doporuceni.md](../vyber/doporuceni.md). Spouštějí se ručně na stanovišti, bez `HIL_HW_STATION` se přeskočí. Seznam a zapojení jsou v [hw-testy.md](hw-testy.md).
- **CI** (`.github/workflows/package.yml`): GitHub Actions, matice `ubuntu-latest` a `windows-latest`, Python 3.12 až 3.14. Kroky: `ruff format --check`, `ruff check`, `mypy`, `pytest` (HW testy se přeskočí) a příklady `examples/tests` na stanovišti `sim`.

## 15. Nasazení

Instalace na Linuxu a Windows, pravidla udev a služba `hil-safe` jsou v [nasazeni.md](nasazeni.md). Pravidlo `deploy/udev/99-hil.rules` řeší jen porty FTDI (skupina `dialout`, latency timer 1 ms). Pravidla pro ST-Link dodá balíček openocd, pro AD3 Adept runtime.

## 16. Pokrytí požadavků

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
| SW-03 | záznamy (`out/<test>/`, viz [testy.md](testy.md#záznamy)), JUnit XML z pytestu |
| SW-04 | zámek stanoviště, `concurrency` v GitHub Actions |
| SW-05, NF-05, NF-06 | profil, stanoviště a `dut.yaml` v gitu; skip nedostupných signálů |
| NF-03 | `hil safe` ve službě systemd |

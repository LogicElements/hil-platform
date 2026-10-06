# Psaní a spouštění testů

## Instalace

```
python -m pip install -e .            # z tohoto repozitáře
python -m pip install "hil-platform @ git+ssh://git@github.com/LogicElements/hil-platform.git"   # z repozitáře DUT
```

Plugin pro pytest se aktivuje instalací balíčku.

## Spuštění

```
python -m pytest tests --hil-station sim --hil-dut dut.yaml
```

| Volba | Proměnná | Význam |
|---|---|---|
| `--hil-station` | `HIL_STATION` | soubor stanoviště nebo jméno vestavěného stanoviště (`sim`) |
| `--hil-dut` | `HIL_DUT` | soubor se zapojením DUT |
| `--hil-out` | | adresář záznamů, výchozí `out` |
| `--hil-profiles` | | další adresář s profily (lze opakovat) |
| `--hil-lock-timeout` | | jak dlouho čekat na zámek stanoviště (s), výchozí 0 |

Bez stanoviště testy, které používají `hil` nebo `dut`, skončí chybou.

Návratové kódy pytestu: 4 při chybě konfigurace stanoviště nebo DUT (neplatný soubor, neznámý ovladač), 3 při selhání stanoviště (zámek drží jiný proces, zařízení nejde otevřít, nelze dosáhnout bezpečného stavu).

## Fixtures

- `dut`: signály DUT podle `dut.yaml`. Marker `hil_requires` funguje jen u testů, které používají `dut`.
- `hil`: celé stanoviště (`hil.power`, `hil.digital`, `hil.faults`, `hil.devices`) pro diagnostiku nebo testy bez `dut.yaml`.

Každý test, který používá `hil` nebo `dut` (i nepřímo přes jinou fixture), dostane po skončení, i neúspěšném, bezpečný stav stanoviště (napájení vypnuto, poruchy obnoveny, generátory zastaveny a odpojeny, relé rozepnuta) a vlastní adresář záznamů. Pokud bezpečný stav nejde nastavit, běh se ukončí s kódem 3.

```python
import pytest


def test_alarm_follows_door_sensor(dut):
    dut.supply.on()
    dut.door_sensor.set(True)
    t = dut.alarm_out.wait_for(True, timeout=0.5)
    assert t - dut.door_sensor.last_change < 0.050


@pytest.mark.hil_requires("sensor_in3")
def test_analog_input(dut):
    ...
```

## Signály

| Druh | Metody |
|---|---|
| `power` | `on()`, `off()`, `outage(s) -> naměřená doba` (jen při zapnutém napájení, jinak `OperationNotAllowed`), `cycle(n, on_s, off_s)`, `is_on` |
| `switch` | `set(bool)`, `pulse(s)`, `state`, `last_change` |
| `sense` | `read()`, `wait_for(stav, timeout, poll_s=0.001) -> čas`, `with record() as r:` (změny v `r.changes`, průměrná perioda čtení v `r.mean_period_s`) |
| `fault_path` | `open()`, `short_to_gnd()`, `restore()`, `state` |
| `serial` | `write(data)`, `expect(regex, timeout) -> match`, `read_until(konec, timeout)`; log do `serial-<signál>.log` |
| `rs485` | `modbus.read_holding_registers(adresa, start, počet)` a další funkce 1–6, 15, 16; `with slave(adresa, store):`; `send_raw(bajty)`; `inject(druh, rámec)` (`bad_crc`, `truncated`, `extended`, `bad_parity`); `flood(s, chunk=64, seed=None) -> počet bajtů` |
| `rs485_monitor` | `start()`, `stop() -> rámce`, `frames`, `wait_for_frame(podmínka, timeout)`; záznam do `rs485-<signál>.jsonl` |
| `debug` | `flash(obraz) -> ProbeResult`, `flash_interrupted(obraz, after_s)`, `reset()`, `halt()`; výstup sondy do `openocd.log` |
| `analog_out` | `sine(freq, amp, offset=0)`, `square(freq, amp, offset=0, duty=0.5)`, `dc(v)`, `arbitrary(vzorky, rate)`, `follow(jiný_signál)`, `disconnect()`, `generator`, `waveform` |
| `analog_in` | `measure(duration_s=0.1) -> Measurement(dc, rms_ac)`, `capture(duration_s, rate=100000) -> numpy.ndarray`; měření do `measurements.jsonl` |

Časy jsou v sekundách z `hil.clock.now()`.

Chyby a limity signálů:

- `sense.record()` vyhodí `DeviceTimeout`, když první čtení vstupu trvá déle než 5 s. Zastavení záznamu čeká nejvýš 5 s.
- `fault_path.short_to_gnd()` na svorce bez relé `short` vyhodí `SignalUnavailable`, na svorce s napájením bez `allow_short` `OperationNotAllowed`.
- `rs485_monitor.wait_for_frame()` bez předchozího `start()` vyhodí `OperationNotAllowed`.
- `inject("bad_parity", rámec)` přepne paritu portu, odešle rámec a paritu obnoví. Když paritu nejde přepnout, je to `DeviceError`. Když ji nejde obnovit, port se zavře.
- Port konzole, jehož čtecí vlákno skončilo chybou, se po bezpečném stavu zavře a při dalším použití otevře znovu.

Porty komunikačních signálů se otevřou při vytvoření fixture `dut` s parametry z `dut.yaml`, takže konzole zachytí i výpis po zapnutí napájení. Konzole drží výstup od vzniku fixture. Po každém testu bezpečný stav zapíše nedokončený řádek do logu a zahodí nepřečtený výstup konzole, zastaví monitor (a smaže jeho rámce) a ukončí simulovaný slave. Master hlásí chybějící odpověď jako `DeviceTimeout` po `timeout_s`, výjimku zařízení jako `ModbusExceptionResponse` (atribut `code`). Chyby portu (např. odpojený převodník) hlásí signály i master jako `DeviceError`. Protože se porty otevírají už při vytvoření fixture `dut`, nefunkční port konzole nebo logu způsobí chybu (error) každého testu, který používá `dut`. Master získaný z `dut.rs485.modbus` před blokem `with dut.rs485.slave(...)` kontrolu konfliktu obejde (kontroluje se jen při získání mastera), proto si master přes blok slave nedržte a po jeho skončení si ho získejte znovu.

Modbus RTU je vlastní implementace v `hil.comm`: `hil.comm.modbus` (CRC, sestavení a dekódování rámců), `ModbusMaster`, `ModbusSlave` s `ModbusDataStore`. Lze je použít i samostatně nad libovolným portem pyserialu, port ale musí mít nastavený timeout čtení (jinak ho master i slave odmítnou). S parametrem `echo` signálu `rs485` (nebo `ModbusSlave(..., echo=True)`) slave po každé odpovědi přečte a zahodí její ozvěnu; při startu zahodí bajty přijaté dříve. Simulovaný slave je bezpečný na sdílené sběrnici: přeslechnutý provoz přeskočí, odpovídá jen na požadavky pro svou adresu (neznámá funkce vrací výjimku 1, vnitřní chyba výjimku 4, broadcast provede bez odpovědi).

Signál `debug` předá operaci sondě s cílem z `dut.yaml` (bez `dut.yaml` přes `hil.debug.flash("SWD", obraz, target)`). Výsledek `ProbeResult` nese výstup, návratový kód, dobu a příznaky `interrupted` a `timed_out`. Selhání nástroje je `DeviceError`, překročení `timeout_s` je `DeviceTimeout`, chybějící obraz `FileNotFoundError`. Chybějící `target` (v `dut.yaml` ani v argumentu) je `OperationNotAllowed`, chybějící program OpenOCD je `DeviceNotFound`. Výstup sondy je v `openocd.log` i při chybě. `flash_interrupted(obraz, after_s)` ukončí sondu po `after_s` sekundách a simuluje přerušenou aktualizaci firmwaru. Pokud flashování skončí dřív, má výsledek `interrupted` rovno `False`.

`inject` a `flood` sestavují rámce z `hil.comm.faults`; `extend` přidává ve výchozím stavu bajt `0xFF` (rámec prodloužený o `0x00` by mohl mít stále platné CRC). Bajty, které netvoří platný rámec (např. zbloudilý bajt nebo zkrácený rámec), monitor zaznamená jako chybový rámec a v dávce pokračuje od místa, odkud se zbytek dávky rozdělí na platné rámce. Monitor rozpozná i rámce, jejichž CRC končí bajtem `0x00`: rámce dělí podle CRC a všechny rámce jedné dávky nesou časové razítko prvního kusu dávky.

### Analogové signály

Stanoviště má dva generátory (sekce `analog`). Průběh na svorce s multiplexerem přidělí volný generátor. Přednost má generátor, na kterém není svorka `direct`, aby rychlý kanál zůstal volný. Pokud jsou oba generátory obsazené, vyhodí `ResourceConflict`. Generátor se nejdřív nastaví a spustí, potom se přepne relé `select` a nakonec sepne `connect`, takže vstup DUT nikdy nedostane ani na okamžik signál druhého generátoru. Změna průběhu na svorce, která už generátor má, změní jen generátor.

`follow(jiný_signál)` připojí svorku na generátor jiné svorky. Generátor je pak sdílený a změna průběhu na kterékoli z nich platí pro obě. `disconnect()` na svorce s multiplexerem rozepne `connect` (stav bez signálu). Když ke generátoru nezůstane připojena žádná svorka, generátor se zastaví. Svorka `direct` (`AO.0`) je na generátor 1 zapojená trvale a relé nemá: když generátor 1 používá svorka s multiplexerem, signál je i na `AO.0` (v `events.jsonl` událost `shared_generator`). `disconnect()` na `AO.0` jen zastaví generátor, pokud ho nepoužívá žádná jiná svorka; signál, který na generátor 1 dává svorka s multiplexerem, na `AO.0` zůstane. Dokud generátor 1 používá svorka s multiplexerem, `dc()`, `sine()` a další průběhy na `AO.0` vyhodí `ResourceConflict`. Naopak když generátor 1 drží `AO.0`, má multiplexer k dispozici jen generátor 2 a další svorka s multiplexerem dostane `ResourceConflict`, pokud je i ten obsazený.

`amp` je amplituda (špička), napětí se uvádí ve voltech. Průběh mimo rozsah generátoru (AD3 ±5 V) vyhodí `ValueError` dřív, než se přepne jakékoli relé.

`measure()` vzorkuje 100 kHz a vrací průměr (`dc`) a RMS po odečtení průměru (`rms_ac`). Svorky na jednom kanálu scope se přepínají měřicím multiplexerem: nejdřív se rozepne relé jiné svorky, potom sepne relé měřené svorky a počká se `settle_s`. Svorka zůstane připojená, dokud kanál nepotřebuje jiná svorka. Kanál scope měří vždy jen jednu svorku najednou: `measure()`, které začne, zatímco na stejném kanálu scope ještě běží jiné měření (typicky z jiného vlákna), vyhodí `ResourceConflict` a nečeká. Platí to pro libovolnou svorku na tomto kanálu včetně té právě měřené a i pro kanál bez multiplexeru.

Bez `dut.yaml` se analog ovládá přes blok `hil.analog`: `hil.analog.sine("AO.1", 1000, 1.0)`, `hil.analog.follow("AO.2", "AO.1")`, `hil.analog.measure("AI.1")`, `hil.analog.disconnect_all()`.

## Přeskakování

Pokud test použije signál, jehož svorka na stanovišti není zapojená, test se přeskočí s důvodem. Platí to i pro použití ve fixture. Marker `hil_requires` přeskočí test ještě před spuštěním. Překlep ve jméně signálu je chyba testu.

## Záznamy

Každý test s fixture `hil` nebo `dut` má adresář `out/<id testu>/` (znaky nevhodné pro jména souborů se nahradí; je-li jméno upraveno nebo zkráceno, připojí se `-` a 8 znaků hashe id testu, aby se adresáře různých testů nepřekrývaly). Soubor `events.jsonl` obsahuje všechny změny signálů s časem od začátku testu. První řádek každého souboru nese čas začátku testu (UTC). Komunikační signály přidávají `serial-<signál>.log` (řádek = čas od začátku testu a text) a `rs485-<signál>.jsonl` (čas, bajty v hex, dekódovaný rámec nebo chyba). Signál `debug` zapisuje výstup sondy do `openocd.log` (řádek `--- <signál>: <operace>` a za ním výstup). Signály `analog_in` zapisují výsledky `measure()` do `measurements.jsonl` (čas, svorka, `dc`, `rms_ac`, délka a vzorkovací frekvence).

## Přerušení běhu

Ctrl+C a na Linuxu i `systemctl stop` (SIGTERM) a zavření terminálu (SIGHUP) běh testů přeruší jako Ctrl+C, na Windows totéž platí pro Ctrl+C a Ctrl+Break. Pytest ukončí session a úklid fixtures nastaví bezpečný stav. Návratový kód je 2, když se bezpečný stav podaří nastavit; když se nepodaří, session skončí kódem 3. Obsluha signálu nekomunikuje se zařízeními, aby nepoškodila rozpracovaný rámec na sběrnici relé.

## Příkazová řádka

| Příkaz | Účel |
|---|---|
| `hil check --station S [--dut D] [--probe]` | kontrola konfigurace, s `--probe` i otevření zařízení |
| `hil safe --station S` | bezpečný stav stanoviště; zařízení, které nejde otevřít, přeskočí a skončí kódem 3 |
| `hil info --station S` | výpis zařízení, svorek a bloků |

Všechny tři příkazy přijímají `--profiles <adresář>` (další adresář s profily, lze opakovat). Návratové kódy: 0 v pořádku, 2 chyba konfigurace, 3 chyba zařízení nebo je stanoviště používáno jiným procesem.

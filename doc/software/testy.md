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

Každý test, který používá `hil` nebo `dut` (i nepřímo přes jinou fixture), dostane po skončení, i neúspěšném, bezpečný stav stanoviště (napájení vypnuto, poruchy obnoveny, relé rozepnuta) a vlastní adresář záznamů. Pokud bezpečný stav nejde nastavit, běh se ukončí s kódem 3.

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
| `power` | `on()`, `off()`, `outage(s) -> naměřená doba`, `cycle(n, on_s, off_s)`, `is_on` |
| `switch` | `set(bool)`, `pulse(s)`, `state`, `last_change` |
| `sense` | `read()`, `wait_for(stav, timeout) -> čas`, `with record() as r:` (změny v `r.changes`) |
| `fault_path` | `open()`, `short_to_gnd()`, `restore()`, `state` |
| `serial` | `write(data)`, `expect(regex, timeout) -> match`, `read_until(konec, timeout)`; log do `serial-<signál>.log` |
| `rs485` | `modbus.read_holding_registers(adresa, start, počet)` a další funkce 1–6, 15, 16; `with slave(adresa, store):`; `send_raw(bajty)`; `inject(druh, rámec)` (`bad_crc`, `truncated`, `extended`, `bad_parity`); `flood(s)` |
| `rs485_monitor` | `start()`, `stop()`, `frames`, `wait_for_frame(podmínka, timeout)`; záznam do `rs485-<signál>.jsonl` |

Časy jsou v sekundách z `hil.clock.now()`.

Porty komunikačních signálů se otevřou při vytvoření fixture `dut` s parametry z `dut.yaml`, takže konzole zachytí i výpis po zapnutí napájení. Konzole drží výstup od vzniku fixture. Po každém testu bezpečný stav zapíše nedokončený řádek do logu a zahodí nepřečtený výstup konzole, zastaví monitor (a smaže jeho rámce) a ukončí simulovaný slave. Master hlásí chybějící odpověď jako `DeviceTimeout` po `timeout_s`, výjimku zařízení jako `ModbusExceptionResponse` (atribut `code`). Chyby portu (např. odpojený převodník) hlásí signály i master jako `DeviceError`. Protože se porty otevírají už při vytvoření fixture `dut`, nefunkční port konzole nebo logu způsobí chybu (error) každého testu, který používá `dut`. Master získaný z `dut.rs485.modbus` před blokem `with dut.rs485.slave(...)` kontrolu konfliktu obejde (kontroluje se jen při získání mastera), proto si master přes blok slave nedržte a po jeho skončení si ho získejte znovu.

Modbus RTU je vlastní implementace v `hil.comm`: `hil.comm.modbus` (CRC, sestavení a dekódování rámců), `ModbusMaster`, `ModbusSlave` s `ModbusDataStore`. Lze je použít i samostatně nad libovolným portem pyserialu, port ale musí mít nastavený timeout čtení (jinak ho master i slave odmítnou). S parametrem `echo` signálu `rs485` (nebo `ModbusSlave(..., echo=True)`) slave po každé odpovědi přečte a zahodí její ozvěnu; při startu zahodí bajty přijaté dříve. Simulovaný slave je bezpečný na sdílené sběrnici: přeslechnutý provoz přeskočí, odpovídá jen na požadavky pro svou adresu (neznámá funkce vrací výjimku 1, vnitřní chyba výjimku 4, broadcast provede bez odpovědi).

`inject` a `flood` sestavují rámce z `hil.comm.faults`; `extend` přidává ve výchozím stavu bajt `0xFF` (rámec prodloužený o `0x00` by mohl mít stále platné CRC). Bajty, které netvoří platný rámec (např. zbloudilý bajt nebo zkrácený rámec), monitor zaznamená jako chybový rámec a v dávce pokračuje od místa, odkud se zbytek dávky rozdělí na platné rámce. Monitor rozpozná i rámce, jejichž CRC končí bajtem `0x00`: rámce dělí podle CRC a všechny rámce jedné dávky nesou časové razítko prvního kusu dávky.

## Přeskakování

Pokud test použije signál, jehož svorka na stanovišti není zapojená, test se přeskočí s důvodem. Platí to i pro použití ve fixture. Marker `hil_requires` přeskočí test ještě před spuštěním. Překlep ve jméně signálu je chyba testu.

## Záznamy

Každý test s fixture `hil` nebo `dut` má adresář `out/<id testu>/` (znaky nevhodné pro jména souborů se nahradí; je-li jméno upraveno nebo zkráceno, připojí se `-` a 8 znaků hashe id testu, aby se adresáře různých testů nepřekrývaly). Soubor `events.jsonl` obsahuje všechny změny signálů s časem od začátku testu. První řádek každého souboru nese čas začátku testu (UTC). Komunikační signály přidávají `serial-<signál>.log` (řádek = čas od začátku testu a text) a `rs485-<signál>.jsonl` (čas, bajty v hex, dekódovaný rámec nebo chyba).

## Příkazová řádka

| Příkaz | Účel |
|---|---|
| `hil check --station S [--dut D] [--probe]` | kontrola konfigurace, s `--probe` i otevření zařízení |
| `hil safe --station S` | bezpečný stav stanoviště |
| `hil info --station S` | výpis zařízení, svorek a bloků |

Návratové kódy: 0 v pořádku, 2 chyba konfigurace, 3 chyba zařízení nebo je stanoviště používáno jiným procesem.

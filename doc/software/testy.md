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

Časy jsou v sekundách z `hil.clock.now()`.

## Přeskakování

Pokud test použije signál, jehož svorka na stanovišti není zapojená, test se přeskočí s důvodem. Platí to i pro použití ve fixture. Marker `hil_requires` přeskočí test ještě před spuštěním. Překlep ve jméně signálu je chyba testu.

## Záznamy

Každý test s fixture `hil` nebo `dut` má adresář `out/<id testu>/` (znaky nevhodné pro jména souborů se nahradí; je-li jméno upraveno nebo zkráceno, připojí se `-` a 8 znaků hashe id testu, aby se adresáře různých testů nepřekrývaly). Soubor `events.jsonl` obsahuje všechny změny signálů s časem od začátku testu. První řádek každého souboru nese čas začátku testu (UTC).

## Příkazová řádka

| Příkaz | Účel |
|---|---|
| `hil check --station S [--dut D] [--probe]` | kontrola konfigurace, s `--probe` i otevření zařízení |
| `hil safe --station S` | bezpečný stav stanoviště |
| `hil info --station S` | výpis zařízení, svorek a bloků |

Návratové kódy: 0 v pořádku, 2 chyba konfigurace, 3 chyba zařízení nebo je stanoviště používáno jiným procesem.

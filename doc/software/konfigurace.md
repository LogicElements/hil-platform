# Konfigurace stanoviště a DUT

Balíček `hil` čte tři druhy souborů YAML. Návrh je ve [specifikaci](../specs/2026-10-05-hil-python-package-design.md).

| Soubor | Kde leží | Obsah |
|---|---|---|
| profil konektoru | v balíčku (`src/hil/profiles/`), případně vlastní adresář | všechny svorky, které stanoviště daného typu může mít, a jejich druhy |
| stanoviště | `stations/` v tomto repozitáři, vestavěné `sim` v balíčku | zařízení a zapojení svorek na jejich kanály |
| zapojení DUT | repozitář DUT | logická jména signálů DUT a svorky, na které vedou |

## Profil

```yaml
profile: standard-v1
terminals:
  PWR: power
  X1.1: switch
  X2.1: sense
  F1: fault_path
```

Druhy svorek: `power`, `switch`, `sense`, `fault_path`, `analog_out`, `analog_in`, `serial`, `rs485`, `rs485_monitor`, `debug`. Tato verze balíčku sestaví `power`, `switch`, `sense`, `fault_path`, `serial`, `rs485` a `rs485_monitor`, ostatní přibudou v dalších verzích.

## Stanoviště

Výňatek ze stanoviště `sim` (úplný soubor je `src/hil/stations/sim.yaml`):

```yaml
name: sim
labels: [sim]
profile: standard-v1
devices:
  rel1: {driver: sim_relay, channels: 32}
  di1: {driver: sim_di, inputs: 8, mirror: {0: rel1.2}}
terminals:
  PWR: {kind: power, relays: [rel1.0, rel1.1]}
  X1.1: {kind: switch, relay: rel1.2}
  X2.1: {kind: sense, input: di1.0}
  F1: {kind: fault_path, series: rel1.6, short: rel1.7}
```

- Odkaz na kanál má tvar `<zařízení>.<kanál>`, např. `rel1.6`. Každý kanál smí použít jen jedna svorka.
- Svorka musí být v profilu a mít stejný druh.
- `power`: relé ve všech pólech napájení, spínají NO kontaktem.
- `switch`: relé, které spíná binární vstup nebo tlačítko DUT (NO kontakt).
- `sense`: digitální vstup, který čte výstup DUT (suchý kontakt, LED).
- `fault_path`: relé `series` zapojené NC kontaktem v cestě vodiče (sepnutí vodič přeruší) a volitelně relé `short`, které vodič spojí se zemí. U vodiče s napájením (`carries_power: true`) je zkrat povolen jen s `allow_short: true`.
- `serial`, `rs485`, `rs485_monitor`: `port: <zařízení>.<kanál>` na zařízení `serial_ports` nebo `sim_serial`.

Ovladače v této verzi:

| Ovladač | Volby | Kanály |
|---|---|---|
| `sim_relay` | `channels` (1–256, výchozí 32) | `0` až `channels-1` |
| `sim_di` | `inputs` (1–256, výchozí 8), `mirror: {vstup: relé}` | `0` až `inputs-1` |
| `sim_serial` | `buses: {sběrnice: [port, port, ...]}`, každá sběrnice alespoň 2 porty, port jen na jedné sběrnici | jména portů |
| `serial_ports` | `ports: {kanál: cesta \| URL \| {serial: FT4ABC, interface: 0–3}}`, `low_latency` (výchozí `true`) | klíče `ports` |

`mirror` propojí vstup se simulovaným relé, takže na stanovišti `sim` vede `X1.1` na `X2.1`.

`sim_serial` simuluje vodiče: co jeden port sběrnice zapíše, dostanou všechny ostatní porty téže sběrnice (RS-485 master, monitor i DUT). Test hraje stranu DUT přes `hil.devices["ser"].endpoint("dut_con")`. `serial_ports` otevírá skutečné porty: cestou (`/dev/serial/by-id/...`, `COM7`), URL pyserialu (`loop://`) nebo sériovým číslem čipu FTDI a číslem kanálu (0 = A). Na Linuxu nastaví latency timer FTDI na 1 ms. Bez práv zápisu do sysfs jen varuje, nastavení pak patří do pravidla udev. Na Windows se latency timer nastavuje ve Správci zařízení.

Stanoviště `sim` zapojuje všechny svorky druhů `power`, `switch`, `sense` a `fault_path` profilu `standard-v1`:

| Svorky | Kanály |
|---|---|
| `PWR` | `rel1.0`, `rel1.1` |
| `X1.1` až `X1.4` | `rel1.2` až `rel1.5` |
| `X2.1` až `X2.8` | `di1.0` až `di1.7` |
| `F1` až `F4` | `series`/`short`: `rel1.6`/`rel1.7`, `rel1.8`/`rel1.9`, `rel1.10`/`rel1.11`, `rel1.12`/`rel1.13` |

`X1.1` je zpětnou smyčkou propojena s `X2.1`. Stanoviště `sim` zapojuje i `CON`, `LOG`, `COM1` a `MON1` (zařízení `ser` typu `sim_serial`). Strana DUT je dostupná jako porty `dut_con`, `dut_log` a `dut_rs485` zařízení `ser`. Analogové a ladicí svorky (`AO.*`, `AI.*`, `SWD`) `sim` nezapojuje, testy, které je použijí, se přeskočí.

## Zapojení DUT

```yaml
dut: example
profile: standard-v1
signals:
  supply: PWR
  door_sensor: X1.1
  alarm_out: X2.1
  console: {terminal: CON, baud: 115200}
```

- Jméno signálu musí být identifikátor Pythonu (test k němu přistupuje jako `dut.door_sensor`), nesmí začínat znakem `_` a nesmí být `name`, `config`, `station`, `signal`, `params` ani `available`.
- Další pole u signálu (např. `baud`) jsou parametry signálu, test je přečte přes `dut.params("console")`.
- Dva signály DUT nesmí používat tutéž svorku druhu `serial`, `rs485` nebo `rs485_monitor` (jeden port nelze otevřít dvakrát), jinak je to chyba konfigurace.
- Svorka mimo profil je chyba. Svorka v profilu, kterou stanoviště nezapojuje, způsobí přeskočení testů, které signál použijí.

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

Všechny tři druhy přijímají celou tabulku, ale `echo` a `timeout_s` mají vliv jen u `rs485` a `frame_gap_s` jen u `rs485_monitor`; ostatní druhy je ignorují. Neznámý parametr je chyba konfigurace, stejně jako jakýkoli parametr u signálu druhu bez parametrů (např. `switch` nebo `sense`).

## Kontrola konfigurace

```
# stations/lab-a.yaml je příklad cesty, soubor přibude v dalším plánu
hil check --station stations/lab-a.yaml --dut ../meter-x/dut.yaml
hil info --station sim
```

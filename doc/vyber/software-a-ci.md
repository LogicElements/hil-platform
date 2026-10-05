# Software a integrace do CI

Jak sestavu z [doporuceni.md](doporuceni.md) ovládat z testů a CI. Požadavky: [hil-specifikace.md](../hil-specifikace.md) (SW-01 až SW-05, NF-02, NF-03, NF-05).

**Upozornění:** verze a licence knihoven jsem nevyhledával, ověřte je před použitím. Konstrukce GitHub Actions (self-hosted runner, štítky, `concurrency`) vychází z obecných znalostí.

## 1. Ovladače a Python API

| Zařízení | Přístup z Pythonu | Poznámka |
|---|---|---|
| Digilent Analog Discovery 3 | WaveForms SDK s podporou Pythonu | Windows, macOS, Linux včetně Raspberry Pi (ARM64, viz [návod Digilentu](https://digilent.com/reference/test-and-measurement/guides/getting-started-with-raspberry-pi)) |
| Převodníky FT4232H a USB–RS-485 | pyserial, případně pyftdi | latenci čtení lze nastavit (pro pasivní záchyt nízkou) |
| Relé moduly Waveshare (Modbus RTU) | pymodbus | adresy 1–255, rychlost až 256 000 baud |
| RS-485 simulace master a slave, injektor chybných rámců | pymodbus a vlastní kód nad sériovým portem | |
| ST-Link V2/V3 | OpenOCD nebo STM32CubeProgrammer, volání jako subprocess | |
| Modul s digitálními vstupy (např. Advantech USB-4761) | ovladače výrobce | Python obálka neověřena |

## 2. Rozhraní HAL

Test nesmí používat konkrétní přístroj, jen blok. Každý blok je třída s pevným rozhraním, implementace se vybírá z konfigurace.

| Blok | Metody (návrh) | Realizace v sestavě | Pokrývá |
|---|---|---|---|
| `PowerBlock` | `on()`, `off()`, `outage(duration_s)`, `emergency_off()` | relé v cestě pevného napájení ±24 V | HW-PWR-01 až 03 |
| `DigitalBlock` | `set_input(ch, state)`, `read_output(ch)`, `press_button(ch)`, `read_led(ch)` | relé moduly pro vstupy, vstupní modul pro výstupy | HW-DIG-01 až 04 |
| `FaultMatrix` | `open(path)`, `short_to_gnd(path)`, `restore(path)`, `restore_all()` | relé v cestách mezi komponentami | HW-FLT-01, 02, 04 |
| `CommBlock` | `serial(name)` (UART), `rs485_master(name)`, `rs485_monitor(name)`, `inject(name, frame)` | FT4232H a pymodbus | HW-COM-01 až 06 |
| `DebugBlock` | `flash(image)`, `reset()`, `console()` | ST-Link přes OpenOCD, konzole přes UART | HW-DBG-01 až 03 |
| `AnalogBlock` | `generate(ch, wave, freq, amp)`, `disconnect(ch)`, `measure(ch) -> (dc, rms)` | Analog Discovery 3 a relé multiplexer | HW-ANA-01 až 03, 05 až 07 |

Pravidla:

- Blok, který instance nemá, se v konfiguraci neuvede a test, který ho potřebuje, se přeskočí (`pytest.skip` s důvodem). Tím vznikne univerzální platforma s různou konfigurací (NF-05).
- Implementace přístroje je jedna třída na výrobce. Výměna přístroje znamená nový soubor a změnu konfigurace, ne změnu testů.
- Každý blok při inicializaci a ukončení přejde do bezpečného stavu: relé rozepnuta, napájení DUT vypnuto.

## 3. Konfigurace stanoviště (SW-05, NF-05)

Soubory ve složce `stations/` jsou verzované v gitu. Příklad kompletního stanoviště a zjednodušené instance:

```yaml
# stations/lab-a.yaml
name: lab-a
labels: [hil, lab-a]
blocks:
  relays:   {driver: waveshare_modbus_relay, port: "/dev/ttyUSB0", baud: 115200, modules: {1: relay32, 2: relay32, 3: relay32, 4: relay32}}
  power:    {relay_module: 1, channels: [0, 1]}            # oba póly
  digital:  {relay_module: 1, inputs: [2, 3, 4, 5], outputs_module: advantech_usb4761}
  faults:   {relay_module: 1, paths: {rs485_a: 6, rs485_b: 7, sig1: 8, sig2: 9}}
  comm:
    ports: {console: "/dev/ttyUSB1", rs485_master: "/dev/ttyUSB2", rs485_monitor: "/dev/ttyUSB3", uart_log: "/dev/ttyUSB4"}
  debug:    {driver: openocd, config: "interface/stlink.cfg"}
  analog:   {driver: analog_discovery_3, mux_modules: [2, 3, 4], max_simultaneous: 2, fast_channels_direct: [0]}
```

```yaml
# stations/lab-b.yaml (jen funkční a poruchové testy, bez analogu)
name: lab-b
labels: [hil, lab-b]
blocks:
  relays:   {driver: waveshare_modbus_relay, port: "COM5", baud: 115200, modules: {1: relay32}}
  power:    {relay_module: 1, channels: [0, 1]}
  digital:  {relay_module: 1, inputs: [2, 3, 4, 5], outputs_module: advantech_usb4761}
  faults:   {relay_module: 1, paths: {rs485_a: 6, rs485_b: 7}}
  comm:
    ports: {console: "COM6", rs485_master: "COM7", rs485_monitor: "COM8"}
  debug:    {driver: openocd, config: "interface/stlink.cfg"}
```

Loader (`hil/config.py`) načte soubor podle proměnné `HIL_STATION`, zkontroluje schéma a vytvoří jen bloky, které jsou v konfiguraci. Test použije fixture `hil.power` a pokud blok chybí, test se přeskočí.

## 4. Integrace s GitHub Actions (SW-04, NF-02)

**Runner:** self-hosted runner nainstalovaný jako služba (systemd na Linuxu, Windows Service na Windows) na řídicím PC. Každé stanoviště má vlastní runner se štítky `hil` a názvem stanoviště (`lab-a`).

**Zámek zdrojů:** workflow používá `concurrency`, takže na jednom stanovišti běží vždy jen jeden test.

```yaml
# .github/workflows/hil.yml
name: hil
on: [push, workflow_dispatch]
jobs:
  hil-lab-a:
    runs-on: [self-hosted, hil, lab-a]
    concurrency: {group: hil-lab-a, cancel-in-progress: false}
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: pytest tests --junitxml=out/junit.xml
        env: {HIL_STATION: stations/lab-a.yaml}
      - uses: actions/upload-artifact@v4
        if: always()
        with: {name: hil-lab-a-logs, path: out/}
```

**Výstup a záznamy (SW-03):** JUnit XML plus složka `out/` s UART logem, záznamem RS-485 (surové rámce s časovými razítky) a časovými řadami. Fixtury po každém testu uloží záznamy do `out/<test>/`.

**Automatický start po výpadku (NF-03):** runner jako služba s automatickým startem, PC v BIOSu nastaveno na start po obnovení napájení, při startu služba zavolá `restore_all()` a `off()` na napájení (bezpečný stav). Softwarový handler (`atexit`, signály) volá `emergency_off()` při ukončení testu. Hardwarový watchdog se nedělá.

## 5. Pokrytí požadavků

| Požadavek | Pokrytí |
|---|---|
| SW-01 (pytest, git) | pytest nad HAL, vše v gitu |
| SW-02 (abstrakční vrstva) | rozhraní HAL v kap. 2 |
| SW-03 (JUnit XML, záznamy) | kap. 4 |
| SW-04 (runner, zámek) | kap. 4 |
| SW-05 (konfigurace v gitu) | `stations/*.yaml` |
| NF-02 | GitHub Actions s self-hosted runnerem |
| NF-03 | služba s automatickým startem a výchozí bezpečný stav |
| NF-05 | konfigurace bloků na instanci, přeskočení testů při chybějícím bloku |
| NF-06 (škálování) | stejný repozitář a formát, štítek runneru na stanoviště |

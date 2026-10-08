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
| `test_outage_accuracy` | `HIL_HW_SUPPLY_SENSE=X2.8` a vstup zapojený na napájení DUT | délku `outage(0.1)`, odchylka pod 10 ms plus perioda čtení vstupu (vstup se čte po sběrnici relé) |
| `test_ftdi_latency_timer` | Linux | latency timer všech portů FTDI v zařízeních `serial_ports` je 1 ms, ostatní porty přeskočí |
| `test_rs485_monitor_sees_active_port` | `HIL_HW_RS485_LOOP=1`, `COM1` a `MON1` na jednom páru | záchyt rámce při 921 600 Bd s paritou E |
| `test_flash_with_openocd` | `HIL_HW_TARGET`, `HIL_HW_IMAGE`, připojený DUT | flashování a reset přes ST-Link |
| `test_ad3_generator_loopback` | `HIL_HW_AD3_LOOP=1`, propojky W1→1+ a W2→2+, 1− a 2− na zem, DUT odpojený od `AO.0` | DC 2 V a sinus 1 kHz z obou generátorů změřené scope téhož AD3, dlouhý záznam (200 000 vzorků) v režimu record |
| `test_analog_multiplexer_loopback` | `HIL_HW_ANALOG_LOOP=AO.1:AI.1,AO.2:AI.3` (nejvýš 2 páry) a propojky mezi svorkami, DUT odpojený (aspoň od `AO.0` a od použitých svorek) | oba generátory přes výstupní multiplexer, měřicí multiplexer a stav bez signálu po odpojení |
| `test_analog_waveforms_loopback` | `HIL_HW_ANALOG_LOOP` (první pár), propojka, DUT odpojený | obdélník a libovolný průběh přes blok `analog` (DC 0,1 V, RMS 5 %), záznam 2 s (200 000 vzorků) |
| `test_ad3_dio_loopback` | `HIL_HW_DIO_LOOP` (např. `X3.1:X2.1`), propojka mezi svorkami | zpoždění logic_out → sense (limit 50 ms) a periodu čtení vstupu |
| `test_ad3_dio_during_scope_acquisition` | `HIL_HW_DIO_LOOP` (první pár), propojka | zpoždění logic_out → sense (limit 50 ms) během 2 s záznamu scope téhož AD3 |

`test_relay_coil_map` spíná postupně všechna relé včetně napájení a poruchových cest, proto běží jen s `HIL_HW_NO_DUT=1`. Proměnné `HIL_HW_NO_DUT` a `HIL_HW_RS485_LOOP` povolí svůj test jen s hodnotou `1`, jiná hodnota test přeskočí.

`test_ad3_generator_loopback` ověřuje vazbu na WaveForms SDK (funkce generátoru, úroveň DC, režim record). Tolerance jsou 0,1 V u DC a 5 % u RMS. `HIL_HW_AD3_LOOP` povolí test jen s hodnotou `1`. Svorka `AO.0` je na generátoru 1 trvale, proto musí být při testu odpojená od DUT.

`test_analog_multiplexer_loopback` nastaví na svorky postupně 1,5 V a 2,5 V. Při dvou párech dostane druhá svorka generátor 1, který je trvale zapojený i na `AO.0` (bez relé), takže napětí je během testu i na `AO.0`. Proto musí být DUT odpojený, aspoň od `AO.0` a od svorek z `HIL_HW_ANALOG_LOOP`.

`test_ad3_dio_loopback` nastaví výstup na 0 a 1 a čeká na změnu vstupu, takže nezávisí na `dio_invert`. Propojka spojuje výstupní a vstupní linku napřímo (bez pull-upu stačí, výstup budí obě úrovně). Na konci testu je výstup uvolněný. Měřené zpoždění začíná návratem zápisu přes USB (`last_change`), samotná doba zápisu v něm není.

Pokud mapa coilů nesouhlasí, upravte ve stanovišti `coil_base`, případně `write: single` (zápis po jednom relé funkcí 5), a test spusťte znovu. U modulu Quido se stejně upravuje `input_base`.

## Předpoklady neověřené na hardwaru

Balíček byl vyvinut bez hardwaru. Ovladače jsou ověřené jen proti simulaci a falešným knihovnám (`ModbusSlave` na `sim_serial`, `FakeDwf`, `tests/drivers/fake_openocd.py`). Mapy registrů Waveshare a Quido, stav relé po zapnutí, přesnost `outage()` a latency timer ověřují testy v tabulce výše. U modulu Quido RS 2/32 je ověřená mapa coilů (`coil_base: 0`) a vstupů (`input_base: 0`), vypnutá relé po zapnutí a zpoždění smyčky relé → vstup asi 35 ms při 115 200 Bd. Flashování a reset přes OpenOCD a ST-Link V3 jsou ověřené na STM32H7A3 s OpenOCD od ST na Windows i s OpenOCD 0.12 z distribuce na Linuxu (viz [oživení](oziveni.md#výsledky)). Testy AD3 a Quido prošly na Windows i na Raspberry Pi 4 s 64bitovým systémem. U Analog Discovery 3 jsou smyčkami bez relé ověřené: úroveň `funcDC` z offsetu, změna průběhu za běhu (režim 3), 0 V po zastavení (režim 0), frekvence scope, režim record bez omezení délky, ustálení offsetu, tolerance měření, obdélník a libovolný průběh, přepínání výstupu DIO s čtením vstupu, čtení DIO během měření scope a vysoká impedance DIO po zavření zařízení (`FDwfDeviceClose`). Po ukončení procesu bez zavření zařízení ale AD3 linky DIO dál budí až do dalšího otevření (viz [nasazení](nasazeni.md)). Navíc se předpokládá:

- změna průběhu v režimu 3 je bez skoku (ověřena jen výsledná úroveň),
- přepínání výstupního a měřicího multiplexeru funguje se skutečnými relé,
- generátory se po ukončení procesu bez zavření zařízení chovají stejně jako DIO (běží dál až do dalšího otevření), ověřené je to jen u DIO,
- `FDwfDigitalIOOutputSet`, potom `FDwfDigitalIOOutputEnableSet` a jeden `FDwfDigitalIOConfigure` přepne výstup bez zákmitu (ověřeno jen přepnutí),
- `FDwfDigitalIOReset` a povolení výstupů 0 udělá ze všech linek vstupy,
- `FDwfDigitalIOInputStatus` vrací úroveň na pinu i u buzeného výstupu (smyčka čte jinou linku).

Multiplexer s relé ověří `test_analog_multiplexer_loopback` na stanovišti s relé. Pokud předpoklad neplatí, opravuje se ovladač `analog_discovery_3` (`drivers/dwf.py`).

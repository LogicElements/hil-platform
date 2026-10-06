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
| `test_ftdi_latency_timer` | Linux | latency timer všech portů `serial_ports` je 1 ms |
| `test_rs485_monitor_sees_active_port` | `HIL_HW_RS485_LOOP=1`, `COM1` a `MON1` na jednom páru | záchyt rámce při 921 600 Bd s paritou E |
| `test_flash_with_openocd` | `HIL_HW_TARGET`, `HIL_HW_IMAGE`, připojený DUT | flashování a reset přes ST-Link |

`test_relay_coil_map` spíná postupně všechna relé včetně napájení a poruchových cest, proto běží jen s `HIL_HW_NO_DUT=1`. Proměnné `HIL_HW_NO_DUT` a `HIL_HW_RS485_LOOP` povolí svůj test jen s hodnotou `1`, jiná hodnota test přeskočí.

Pokud mapa coilů nesouhlasí, upravte ve stanovišti `coil_base`, případně `write: single` (zápis po jednom relé funkcí 5), a test spusťte znovu. U modulu Quido se stejně upravuje `input_base`.

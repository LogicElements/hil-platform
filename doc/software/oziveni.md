# Oživení stanoviště

Stanoviště se oživuje po jednotlivých zařízeních. Každé zařízení se nejdřív vyzkouší samo na vývojovém PC (Windows je podporovaný). Teprve když projde, přijde na řadu další. Co nesedí, se opraví v konfiguraci (např. `coil_base`), jen výjimečně v ovladači. Výsledek každého kroku se zapíše do tabulky [Výsledky](#výsledky) a z oddílu „Předpoklady neověřené na hardwaru“ v [HW testech](hw-testy.md) se škrtne příslušná položka.

## Nastavení sběrnice Modbus RTU

Všechna zařízení na sběrnici relé (moduly relé a vstupů) mají jedno společné nastavení linky:

| Parametr | Hodnota |
|---|---|
| protokol | Modbus RTU |
| rychlost | 19 200 Bd |
| znak | 8 datových bitů, sudá parita, 1 stop bit (8E1) |

Každé zařízení má vlastní adresu:

| Zařízení | Adresa |
|---|---|
| Papouch Quido RS 2/32 | 49 |

Zařízení si nastaví uživatel sám podle dokumentace výrobce, balíček je nekonfiguruje. Stanoviště uvádí totéž nastavení u `modbus_rtu_bus` (`baud: 19200`, `parity: E`). Do budoucna se sběrnice může zrychlit na 115 200 Bd. Pak se rychlost změní u všech zařízení najednou i ve stanovištích.

## Pořadí

| # | Zařízení | Co se ověří | Stav |
|---|---|---|---|
| 1 | Papouch Quido RS 2/32 | Modbus RTU, mapa coilů a vstupů, stav po zapnutí, zpoždění smyčky relé → vstup | hotovo kromě kroku 5 |
| 2 | Waveshare Modbus RTU Relay 32-ch | mapa coilů, stav po zapnutí, sdílená sběrnice s Quido | čeká |
| 3 | modul digitálních vstupů (`modbus_di`) | čtení vstupů, perioda čtení | čeká |
| 4 | napájení přes zdroj HDR | `outage()`, odchylka pod 10 ms | čeká |
| 5 | FT4232H | latency timer, monitor RS-485 na 921 600 Bd | čeká |
| 6 | Analog Discovery 3 | funkce WaveForms SDK, smyčka generátor → scope | čeká |
| 7 | ST-Link a OpenOCD | flashování a reset DUT | čeká |
| 8 | analogový multiplexer | oba generátory přes relé, měřicí multiplexer | čeká |
| 9 | celé stanoviště na Linuxu | udev, služba `hil safe`, `hil check --probe` | čeká |

## 1. Papouch Quido RS 2/32

Připojení: převodník FTDI na portu `COM4` vývojového PC. Modul je nastavený podle [společného nastavení sběrnice](#nastavení-sběrnice-modbus-rtu), adresa 49. Příkazy níže jsou pro PowerShell.

### Co víme z dokumentace výrobce

Zdroj: [Quido – MODBUS](https://cdn.papouch.com/data/user-content/spolecne/quido/Quido%20Modbus%20CZ.pdf) (verze 10. 2. 2023), [produktová stránka](https://papouch.com/quido-rs-2-32-2-vstupy-32-vystupu-a-teplomer-p4662/?vid=1846).

- Z výroby komunikuje protokolem Spinel, do Modbus RTU se přepíná podle dokumentace výrobce.
- Funkce: 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0F, 0x10, 0x11 (identifikace).
- Výstupy jsou coily od 0 (výstup 1 = coil 0), vstupy jsou discrete inputs od 0 (IN1 = 0). Odpovídá výchozím volbám ovladače `quido_rs_2_32` (`coil_base: 0`, `input_base: 0`).
- Holding registry 13, 14 a 15 obsahují počet vstupů, výstupů a teploměrů. Od registru 1000 jsou kopie stavů vstupů, od 1200 kopie stavů výstupů.
- Adresa 0 je broadcast (bez odpovědi), adresa 248 (0xF8) je univerzální a modul na ni odpoví. Hodí se, jen když je na lince jediný modul.
- Registr 4 „Rozlišení konce paketu“: ticho mezi bajty, které modul bere jako konec rámce, výchozí 10 znaků (4 až 100). Při 19 200 Bd modul na dotaz odpoví nejdřív asi 6 ms po jeho konci.
- Vstupy jsou izolované, 7 až 28 V (existuje i varianta 4,5 až 9 V). Aktivní vstup znamená připojené napětí. Napájení modulu je 8 až 30 V.

### Potřebné vybavení

- Quido RS 2/32 nastavený podle společného nastavení sběrnice, napájení 8 až 30 V DC.
- Převodník FTDI podle rozhraní modulu (RS-232 nebo RS-485), port `COM4`.
- Pro kroky 4 a 5 zdroj napětí pro vstupy (např. napájení modulu, je-li v rozsahu vstupů) a vodiče.
- Nainstalovaný balíček `hil` ve venv (`python -m pip install -e .[dev]`).

### Krok 1: První komunikace

Ověří, že modul odpovídá na Modbus, a přečte jeho typ a stav. Spouští se z kořene repozitáře:

```
.venv/Scripts/python -c "import serial; from hil.comm.master import ModbusMaster; p = serial.Serial('COM4', 19200, parity='E', timeout=0.05); m = ModbusMaster(p, timeout_s=0.5); print('registry 1 až 4:', m.read_holding_registers(49, 1, 4)); print('coily:', m.read_coils(49, 0, 32)); print('vstupy:', m.read_discrete_inputs(49, 0, 2))"
```

Očekávané: registry 1 až 4 `[49, 7, 1, 10]` (adresa, kód rychlosti, kód parity, rozlišení konce paketu, hodnoty naměřené při společném nastavení sběrnice), 32 coilů a 2 vstupy. Registry 13 až 15 (počty vstupů, výstupů a teploměrů) tento modul vrací nulové, i když je dokumentace výrobce uvádí. Počty se proto ověří čtením na hranicích: coil 31 a vstup 1 se přečtou, coil 32 a vstup 2 skončí chybou. Pokud modul neodpovídá:
- ověřit nastavení modulu (protokol, rychlost, parita) podle dokumentace výrobce,
- zkusit univerzální adresu 248 místo 49 (zjistí, jestli modul nemá jinou adresu),
- u RS-485 prohodit vodiče A a B a ověřit, že převodník přepíná směr sám.

### Krok 2: Stanoviště pro zkušební stůl

Vytvořit `stations/bench-quido.yaml`:

```yaml
# Bench station: one Papouch Quido RS 2/32 on COM4 (bring-up, doc/software/oziveni.md).
name: bench-quido
labels: [bench]
profile: standard-v1
devices:
  relay_bus: {driver: modbus_rtu_bus, port: COM4, baud: 19200, parity: E}
  quido: {driver: quido_rs_2_32, bus: relay_bus, address: 49}
terminals:
  X1.1: {kind: switch, relay: quido.0}
  X1.2: {kind: switch, relay: quido.1}
  X1.3: {kind: switch, relay: quido.2}
  X1.4: {kind: switch, relay: quido.3}
  X2.1: {kind: sense, input: quido.in0}
  X2.2: {kind: sense, input: quido.in1}
```

Ověření:

```
.venv/Scripts/hil check --station stations/bench-quido.yaml --probe
.venv/Scripts/hil info --station stations/bench-quido.yaml
```

### Krok 3: Stav relé po zapnutí

Hned po zapnutí modulu (před jakýmkoli zápisem):

```
$env:HIL_HW_STATION = "stations/bench-quido.yaml"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_relays_are_off_after_power_up
```

Test čte coily při otevření stanoviště. Coil říká povelový stav modulu, proto se stav relé ověří i pohledem na LED a měřením na kontaktech.

### Krok 4: Mapa coilů

Nic nesmí být připojené na kontakty relé.

```
$env:HIL_HW_NO_DUT = "1"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_relay_coil_map
```

Test sepne postupně každé relé samotné a přečte coily zpět. Čtení ověří jen odpověď modulu. Že sepne správné fyzické relé (výstup 1 až 32), se ověří pohledem na LED nebo ohmmetrem na kontaktech aspoň u relé 1, 2, 16 a 32. Když mapa nesedí, upraví se `coil_base` nebo `write: single`.

### Krok 5: Vstupy a smyčka relé → vstup

Zapojení: kladný pól zdroje na COM relé 1, NO relé 1 na vstup IN1+, IN1− na záporný pól. Stejně relé 2 na IN2.

```
$env:HIL_HW_LOOPBACK = "X1.1:X2.1,X1.2:X2.2"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_loopback_latency_and_polling_period
```

Test měří zpoždění od sepnutí relé po změnu vstupu (limit 50 ms) a průměrnou periodu čtení vstupu. Při 19 200 Bd a výchozím rozlišení konce paketu (10 znaků, asi 6 ms) by se zpoždění mělo do limitu vejít, ověří se to měřením (zápis relé, čekání modulu, odpověď a čtení vstupu jsou několik rámců za sebou). Pokud limit nesplní, další pokus je zrychlit celou sběrnici (např. na 115 200 Bd, viz [nastavení sběrnice](#nastavení-sběrnice-modbus-rtu)) nebo zkrátit rozlišení konce paketu Quido.

### Krok 6: Zápis výsledků

- Výsledky do tabulky níže, naměřené hodnoty z výstupu `-s`.
- Úpravy konfigurace do `stations/bench-quido.yaml`, později do `stations/lab-a.yaml`.
- V [HW testech](hw-testy.md) škrtnout ověřené předpoklady.

## Výsledky

| Zařízení | Datum | Výsledek | Poznámka |
|---|---|---|---|
| Quido RS 2/32, krok 1 | 6. 10. 2026 | prošlo | odpovídá na adrese 49, 32 coilů (0 až 31), 2 vstupy (0 a 1). Registry 13 až 15 vrací 0 (proti dokumentaci). Registry 1 až 4: `[49, 7, 1, 10]`, registr 10 = 260, 11 = 22473 (význam neověřen). Čtení mimo rozsah vrací výjimku 2 s kódem funkce 0x84 místo 0x81 nebo 0x82; ovladač to hlásí jako chybu, na funkci to nemá vliv. |
| Quido RS 2/32, krok 2 | 6. 10. 2026 | prošlo | `hil check --probe` otevře obě zařízení, `hil info` ukazuje X1.1 až X1.4 a X2.1, X2.2 zapojené. |
| Quido RS 2/32, krok 3 | 6. 10. 2026 | prošlo | po vypnutí a zapnutí modulu jsou všechny coily vypnuté, žádná LED relé nesvítí. |
| Quido RS 2/32, krok 4 | 6. 10. 2026 | prošlo | `test_relay_coil_map` prošel (3,6 s). Po sepnutí coilů 0, 1, 15 a 31 svítí LED výstupů 1, 2, 16 a 32, mapa odpovídá `coil_base: 0`. Zápis více coilů funkcí 0x0F funguje. |
| Quido RS 2/32, krok 5 | 6. 10. 2026 | odloženo | smyčka relé → vstup zatím nezapojená; mapa vstupů, varianta napětí vstupů a zpoždění proti limitu 50 ms zůstávají neověřené. |

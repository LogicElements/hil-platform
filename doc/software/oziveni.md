# Oživení stanoviště

Stanoviště se oživuje po jednotlivých zařízeních. Každé zařízení se nejdřív vyzkouší samo na vývojovém PC (Windows je podporovaný). Teprve když projde, přijde na řadu další. Co nesedí, se opraví v konfiguraci (např. `coil_base`), jen výjimečně v ovladači. Výsledek každého kroku se zapíše do tabulky [Výsledky](#výsledky) a z oddílu „Předpoklady neověřené na hardwaru“ v [HW testech](hw-testy.md) se škrtne příslušná položka.

## Nastavení sběrnice Modbus RTU

Všechna zařízení na sběrnici relé (moduly relé a vstupů) mají jedno společné nastavení linky:

| Parametr | Hodnota |
|---|---|
| protokol | Modbus RTU |
| rychlost | 115 200 Bd |
| znak | 8 datových bitů, sudá parita, 1 stop bit (8E1) |

Každé zařízení má vlastní adresu:

| Zařízení | Adresa |
|---|---|
| Papouch Quido RS 2/32 | 49 |

Zařízení si nastaví uživatel sám podle dokumentace výrobce, balíček je nekonfiguruje. Stanoviště uvádí totéž nastavení u `modbus_rtu_bus` (`baud: 115200`, `parity: E`). Změna rychlosti se dělá u všech zařízení najednou i ve stanovištích. Původně byla sběrnice na 19 200 Bd, 7. 10. 2026 se zrychlila na 115 200 Bd, protože jedna transakce trvala asi 17 ms a smyčka relé → vstup se nevešla spolehlivě do limitu 50 ms. Na Windows musí mít převodník FTDI latency timer 1 ms (viz [nasazení](nasazeni.md)), s výchozími 16 ms trvá každá transakce o 16 ms déle.

## Pořadí

| # | Zařízení | Co se ověří | Stav |
|---|---|---|---|
| 1 | Papouch Quido RS 2/32 | Modbus RTU, mapa coilů a vstupů, stav po zapnutí, zpoždění smyčky relé → vstup | hotovo |
| 2 | Waveshare Modbus RTU Relay 32-ch | mapa coilů, stav po zapnutí, sdílená sběrnice s Quido | odloženo, není k dispozici |
| 3 | modul digitálních vstupů (`modbus_di`) | nahrazeno linkami DIO Analog Discovery 3 (bod 6), Modbus modul je budoucí alternativa pro jiné úrovně než 3,3 V | odloženo |
| 4 | napájení přes zdroj HDR | `outage()`, odchylka pod 10 ms | čeká |
| 5 | FT4232H | latency timer, monitor RS-485 na 921 600 Bd | čeká |
| 6 | Analog Discovery 3 | funkce WaveForms SDK, smyčka generátor → scope, DIO: smyčka logic_out → sense (`test_ad3_dio_loopback`) | hotovo |
| 7 | ST-Link a OpenOCD | flashování a reset DUT | hotovo |
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
- Registr 4 „Rozlišení konce paketu“: ticho mezi bajty, které modul bere jako konec rámce, výchozí 10 znaků (4 až 100). Při 115 200 Bd modul na dotaz odpoví asi 1 ms po jeho konci (při 19 200 Bd asi 6 ms).
- Vstupy jsou izolované, 7 až 28 V (existuje i varianta 4,5 až 9 V, tento kus má 7 až 28 V). Aktivní vstup znamená připojené napětí. Napájení modulu je 8 až 30 V.

### Potřebné vybavení

- Quido RS 2/32 nastavený podle společného nastavení sběrnice, napájení 8 až 30 V DC.
- Převodník FTDI podle rozhraní modulu (RS-232 nebo RS-485), port `COM4`.
- Pro kroky 4 a 5 zdroj napětí pro vstupy (např. napájení modulu, je-li v rozsahu vstupů) a vodiče.
- Nainstalovaný balíček `hil` ve venv (`python -m pip install -e .[dev]`).

### Krok 1: První komunikace

Ověří, že modul odpovídá na Modbus, a přečte jeho typ a stav. Spouští se z kořene repozitáře:

```
.venv/Scripts/python -c "import serial; from hil.comm.master import ModbusMaster; p = serial.Serial('COM4', 115200, parity='E', timeout=0.05); m = ModbusMaster(p, timeout_s=0.5); print('registry 1 až 4:', m.read_holding_registers(49, 1, 4)); print('coily:', m.read_coils(49, 0, 32)); print('vstupy:', m.read_discrete_inputs(49, 0, 2))"
```

Očekávané: registry 1 až 4 `[49, 10, 1, 10]` (adresa, kód rychlosti, kód parity, rozlišení konce paketu, hodnoty naměřené při společném nastavení sběrnice), 32 coilů a 2 vstupy. Registry 13 až 15 (počty vstupů, výstupů a teploměrů) tento modul vrací nulové, i když je dokumentace výrobce uvádí. Počty se proto ověří čtením na hranicích: coil 31 a vstup 1 se přečtou, coil 32 a vstup 2 skončí chybou. Pokud modul neodpovídá:
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
  relay_bus: {driver: modbus_rtu_bus, port: COM4, baud: 115200, parity: E}
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

Test měří zpoždění od sepnutí relé po změnu vstupu (limit 50 ms) a průměrnou periodu čtení vstupu. Při 115 200 Bd trvá zápis relé asi 3,5 ms a čtení vstupu asi 5,5 ms. Většinu zpoždění (asi 30 ms) tvoří samotný modul (sepnutí relé a vyhodnocení vstupu), sběrnice ho už nezkrátí.

### Krok 6: Zápis výsledků

- Výsledky do tabulky níže, naměřené hodnoty z výstupu `-s`.
- Úpravy konfigurace do `stations/bench-quido.yaml`, později do `stations/lab-a.yaml`.
- V [HW testech](hw-testy.md) škrtnout ověřené předpoklady.

## 6. Analog Discovery 3

Připojení: AD3 přes USB vývojového PC, sériové číslo `210415BB5F29`. Musí být nainstalovaný WaveForms (s runtime Adept, knihovna `dwf.dll`) a aplikace WaveForms musí být zavřená, jinak je zařízení obsazené. AD3 se oživuje samo, bez relé: oba generátory jsou na přímých svorkách a DIO i analogové kanály jsou propojené smyčkami.

### Potřebné vybavení

- Analog Discovery 3 s kabelem svorek (flywires) a propojkami.
- Nainstalovaný balíček `hil` ve venv.

### Zapojení smyček

| Smyčka | Propojka | Svorky stanoviště |
|---|---|---|
| generátor 1 → scope 1 | W1 → 1+, 1− → GND | `AO.0` → `AI.1` |
| generátor 2 → scope 2 | W2 → 2+, 2− → GND | `AO.1` → `AI.3` |
| DIO výstupy → vstupy | DIO 8 → DIO 0, 9 → 1, 10 → 2, 11 → 3, 12 → 4, 13 → 5 | `X3.1` → `X2.1` až `X3.6` → `X2.6` |

Propojka DIO spojuje výstup a vstup napřímo, výstup budí obě úrovně, pull-up není potřeba.

### Krok 1: První komunikace

```
.venv/Scripts/python -c "from hil.drivers.dwf import DwfLibrary; print(DwfLibrary().devices())"
```

Očekávané: jedno zařízení `Analog Discovery 3` se sériovým číslem a `in_use=False`. Když je seznam prázdný, chybí runtime Adept nebo kabel; když je `in_use=True`, běží aplikace WaveForms.

### Krok 2: Stanoviště pro zkušební stůl

`stations/bench-ad3.yaml` obsahuje AD3 se sériovým číslem, DIO 8 až 13 jako výstupy `X3.1` až `X3.6`, DIO 0 až 5 jako vstupy `X2.1` až `X2.6` (bez `dio_invert`, vstup čte úroveň výstupu), přímé svorky `AO.0` (generátor 1) a `AO.1` (generátor 2) a vstupy `AI.1` (scope 1) a `AI.3` (scope 2) bez relé.

```
.venv/Scripts/hil check --station stations/bench-ad3.yaml --probe
.venv/Scripts/hil info --station stations/bench-ad3.yaml
```

### Krok 3: Smyčka generátor → scope

Zapojené smyčky W1 → 1+ a W2 → 2+.

```
$env:HIL_HW_STATION = "stations/bench-ad3.yaml"
$env:HIL_HW_AD3_LOOP = "1"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_ad3_generator_loopback
```

Test pustí z obou generátorů DC 2 V a sinus 1 kHz s amplitudou 1 V a změří je scope (tolerance 0,1 V u DC, 5 % u RMS), nakonec dlouhý záznam 200 000 vzorků v režimu record. Ověří předpoklady o `funcDC`, změně průběhu za běhu, frekvenci scope a režimu record.

### Krok 4: Analogové svorky přes blok `analog`

Stejné zapojení, test jde přes svorky stanoviště místo ovladače:

```
$env:HIL_HW_ANALOG_LOOP = "AO.0:AI.1,AO.1:AI.3"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_analog_multiplexer_loopback
```

Na přímých svorkách nepřepíná žádné relé. Test ověří úrovně 1,5 V a 2,5 V na obou svorkách a že po `disconnect_all()` (zastavení generátorů) je na vstupech pod 0,2 V, tj. režim 0 nechá na výstupu 0 V. Multiplexer s relé se ověří až v bodě 8.

Průběhy obdélník a libovolný a dlouhý záznam přes blok `analog` (použije první pár z `HIL_HW_ANALOG_LOOP`):

```
.venv/Scripts/python -m pytest tests/hw -v -s -k test_analog_waveforms_loopback
```

Test pustí obdélník 500 Hz (1 V, offset 0,5 V, střída 30 %) a libovolný průběh 1 kHz (impuls 0 V / 2 V, střída 25 %), porovná střední hodnotu a RMS s výpočtem a nakonec zaznamená 2 s (200 000 vzorků).

### Krok 5: Smyčka DIO

Zapojené propojky DIO 8 až 13 → DIO 0 až 5.

```
$env:HIL_HW_DIO_LOOP = "X3.1:X2.1,X3.2:X2.2,X3.3:X2.3,X3.4:X2.4,X3.5:X2.5,X3.6:X2.6"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_ad3_dio_loopback
```

Test u každé dvojice nastaví výstup na 0 a 1, měří zpoždění změny vstupu (limit 50 ms) a průměrnou periodu čtení vstupu, nakonec výstup uvolní. Ověří přepínání výstupu, čtení úrovně a mapu linek. Že vstup bez `dio_invert` čte úroveň výstupu (1 → `True`), ukáže výpis `-s` nebo krátký pokus:

```
.venv/Scripts/python -c "from hil.station import Station; s = Station.from_files('stations/bench-ad3.yaml'); s.__enter__(); o = s.digital.logic_out('X3.1'); i = s.digital.sense('X2.1'); o.set(True); print(i.read()); o.set(False); print(i.read()); s.__exit__(None, None, None)"
```

Očekávané: `True`, potom `False`.

Čtení DIO během dlouhého měření scope (první pár z `HIL_HW_DIO_LOOP`):

```
.venv/Scripts/python -m pytest tests/hw -v -s -k test_ad3_dio_during_scope_acquisition
```

Test spustí záznam scope na 2 s a během něj pětkrát přepne výstup. Zpoždění smyčky musí zůstat pod 50 ms, čtení DIO tedy nečeká na konec měření.

### Krok 6: Linky DIO po zavření zařízení

Ověří, že zavřené AD3 nebudí výstupy (DUT nedostane napětí, když stanoviště skončí nebo spadne). Softwarem to ověřit nejde, protože každé otevření AD3 linky resetuje. Měří se multimetrem na DIO 8 proti GND, mezi DIO 8 a GND je odpor asi 10 kΩ (vysoká impedance pak ukáže 0 V, ne plovoucí napětí). Propojka DIO 8 → DIO 0 může zůstat.

a) Zavření zařízení bez uvolnění výstupu (`FDwfDeviceClose`):

```
.venv/Scripts/python -c "from hil.station import Station; s = Station.from_files('stations/bench-ad3.yaml'); s.__enter__(); s.digital.logic_out('X3.1').set(True); input('DIO 8 = 3,3 V? Enter zavre AD3'); s.devices['ad3'].close(); input('DIO 8 = 0 V? Enter skonci')"
```

b) Proces ukončený bez zavření (pád, zabití):

```
.venv/Scripts/python -c "import os; from hil.station import Station; s = Station.from_files('stations/bench-ad3.yaml'); s.__enter__(); s.digital.logic_out('X3.1').set(True); input('DIO 8 = 3,3 V? Enter ukonci proces'); os._exit(1)"
```

Očekávané v obou případech: při zapnutém výstupu 3,3 V, po zavření nebo ukončení 0 V. Případ a) na AD3 platí, případ b) ne: výstup zůstane buzený až do dalšího otevření (viz [Výsledky](#výsledky) a [nasazení](nasazeni.md)).

### Krok 7: Zápis výsledků

- Výsledky do tabulky níže, naměřené hodnoty z výstupu `-s`.
- V [HW testech](hw-testy.md) škrtnout ověřené předpoklady o AD3.
- Konfiguraci AD3 (sériové číslo) převzít do `stations/lab-a.yaml`.

## 7. ST-Link a OpenOCD

Připojení: deska NUCLEO-H7A3ZI-Q (STM32H7A3, Cortex-M7, 2 MB flash) s vestavěným ST-Link V3 (firmware V3J16M7) přes USB vývojového PC. Typ desky a čipu ukáže `STM32_Programmer_CLI -l stlink` a `STM32_Programmer_CLI -c port=SWD mode=HOTPLUG` (STM32CubeCLT).

OpenOCD není v `PATH`, použije se verze od ST přibalená k STM32CubeIDE 1.12 (OpenOCD 0.12.0 ST fork) i s jejími skripty (`st_scripts`). Stanoviště `stations/bench-stlink.yaml` proto uvádí plnou cestu v `command` a skripty v `search`. Pro tento cíl potřebuje dvě odchylky od výchozích voleb ovladače:

- `interface: interface/stlink-dap.cfg`: s výchozím `interface/stlink.cfg` (HLA) skončí `target/stm32h7x.cfg` ze `st_scripts` zacyklením v `hla newtap`.
- `-c "reset_config srst_only srst_nogate"` v `command`: bez hardwarového resetu (NRST) skončí `reset init` chybou „timed out while waiting for target halted“, takže selže `program`. Volba funguje i před konfigurací rozhraní, proto stačí úvodní argumenty.

Ověření:

```
.venv/Scripts/hil check --station stations/bench-stlink.yaml --probe
$env:HIL_HW_STATION = "stations/bench-stlink.yaml"
$env:HIL_HW_TARGET = "target/stm32h7x.cfg"
$env:HIL_HW_IMAGE = "examples/AmplifFilter-App.hex"
.venv/Scripts/python -m pytest tests/hw -v -s -k test_flash_with_openocd
```

`HIL_HW_IMAGE` je libovolný image pro cílový čip (.hex nebo .elf). Image se do repozitáře nedávají (`.gitignore`), `examples/AmplifFilter-App.hex` je jen lokální soubor na vývojovém PC. Test přepíše firmware v čipu. Před prvním flashováním se vyplatí uložit obsah flash: `STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -r 0x08000000 0x200000 zaloha.bin`.

## Výsledky

| Zařízení | Datum | Výsledek | Poznámka |
|---|---|---|---|
| Quido RS 2/32, krok 1 | 6. 10. 2026 | prošlo | odpovídá na adrese 49, 32 coilů (0 až 31), 2 vstupy (0 a 1). Registry 13 až 15 vrací 0 (proti dokumentaci). Registry 1 až 4: `[49, 7, 1, 10]`, registr 10 = 260, 11 = 22473 (význam neověřen). Čtení mimo rozsah vrací výjimku 2 s kódem funkce 0x84 místo 0x81 nebo 0x82; ovladač to hlásí jako chybu, na funkci to nemá vliv. |
| Quido RS 2/32, krok 2 | 6. 10. 2026 | prošlo | `hil check --probe` otevře obě zařízení, `hil info` ukazuje X1.1 až X1.4 a X2.1, X2.2 zapojené. |
| Quido RS 2/32, krok 3 | 6. 10. 2026 | prošlo | po vypnutí a zapnutí modulu jsou všechny coily vypnuté, žádná LED relé nesvítí. |
| Quido RS 2/32, krok 4 | 6. 10. 2026 | prošlo | `test_relay_coil_map` prošel (3,6 s). Po sepnutí coilů 0, 1, 15 a 31 svítí LED výstupů 1, 2, 16 a 32, mapa odpovídá `coil_base: 0`. Zápis více coilů funkcí 0x0F funguje. |
| Quido RS 2/32, krok 5 | 7. 10. 2026 | prošlo | smyčka relé 12 → IN1 a relé 13 → IN2 (dočasné svorky na coily 11 a 12). Mapa vstupů sedí (IN1 = vstup 0, IN2 = vstup 1, `input_base: 0`). Při 19 200 Bd a latency timeru FTDI 16 ms: čtení 30 ms, zpoždění až 64 ms (neprošlo). S latency timerem 1 ms: čtení 16,9 ms, zpoždění 32 až 51 ms (na hraně). Po zrychlení sběrnice na 115 200 Bd (registr 2 = 10): čtení 5,5 ms, zápis 3,5 ms, zpoždění 29 až 42 ms (medián 35 ms, 80 měření), test prošel třikrát. Při rozepnutí relé je zpoždění někdy jen 5 ms, při sepnutí vždy přes 29 ms. Vstupy jsou ve variantě 7 až 28 V (údaj uživatele). |
| ST-Link a OpenOCD | 6. 10. 2026 | prošlo | NUCLEO-H7A3ZI-Q, OpenOCD od ST z CubeIDE 1.12. Reset přes `hil` 1,9 s, `test_flash_with_openocd` s lokálním `examples/AmplifFilter-App.hex` 5,0 s (program, verify, reset). Nutné `interface/stlink-dap.cfg` a `reset_config srst_only srst_nogate`, bez nich selže připojení nebo `reset init`. Neověřeno s OpenOCD z distribuce (Linux, upstream skripty). |
| Analog Discovery 3, krok 1 | 7. 10. 2026 | prošlo | `DwfLibrary().devices()` najde `Analog Discovery 3`, SN `210415BB5F29`, WaveForms s runtime Adept nainstalovaný. |
| Analog Discovery 3, krok 2 | 7. 10. 2026 | prošlo | `hil check --probe` otevře AD3, `hil info` ukazuje X2.1 až X2.6, X3.1 až X3.6, AO.0, AO.1, AI.1 a AI.3 zapojené. |
| Analog Discovery 3, krok 3 | 7. 10. 2026 | prošlo | `test_ad3_generator_loopback`: generátor 1 → scope 1 DC 2,0026 V, sinus 1 kHz/1 V RMS 0,7077 V (DC −0,004 V); generátor 2 → scope 2 DC 1,9779 V, RMS 0,7076 V (DC −0,029 V). Kanál 2 má stálý posun asi −25 mV, v toleranci. Záznam 200 000 vzorků v režimu record prošel. |
| Analog Discovery 3, krok 4 | 7. 10. 2026 | prošlo | `AO.0` 1,5 V → `AI.1` 1,5054 V, `AO.1` 2,5 V → `AI.3` 2,4804 V; po `disconnect_all()` −0,005 V a −0,025 V. |
| Analog Discovery 3, krok 5 | 7. 10. 2026 | prošlo | všech 6 dvojic DIO: zpoždění 0,25 až 0,60 ms (limit 50 ms), mapa linek sedí, vstup bez `dio_invert` čte úroveň výstupu. Průměrná perioda `record()` 15 ms místo požadované 1 ms: zrnitost `threading.Event.wait` na Windows, ne omezení AD3. |
| Analog Discovery 3, krok 4 (průběhy) | 7. 10. 2026 | prošlo | `test_analog_waveforms_loopback`: obdélník DC 0,0972 V (výpočet 0,1), RMS 0,9132 V (0,9165); libovolný průběh DC 0,4964 V (0,5), RMS 0,8593 V (0,8660); záznam 2 s = 200 000 vzorků. |
| Analog Discovery 3, krok 5 (souběh se scope) | 7. 10. 2026 | prošlo | `test_ad3_dio_during_scope_acquisition`: během 2 s záznamu scope nejvyšší zpoždění smyčky DIO 1,36 ms. Po opravě `record()` (`time.sleep` místo `Event.wait`) je perioda čtení vstupu 1,75 ms místo 15 ms. |
| Analog Discovery 3, krok 6 a) | 7. 10. 2026 | prošlo | DIO 8 se zapnutým výstupem 3,3 V, po `close()` bez uvolnění výstupu (`FDwfDeviceClose`) 0 V přes 10 kΩ na GND. |
| Analog Discovery 3, krok 6 b) | 7. 10. 2026 | neprošlo (omezení) | po ukončení procesu bez zavření (`os._exit`) zůstalo na DIO 8 asi 3 V. AD3 drží poslední stav DIO až do dalšího otevření, které linky resetuje. Stejně se po SIGKILL chovají relé, úklid zajistí `hil safe` nebo další běh. |

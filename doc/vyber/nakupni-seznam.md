# Nákupní seznam HIL stanoviště

Podklad: [doporuceni.md](doporuceni.md), [hil-specifikace.md](../hil-specifikace.md). Datum: 2026-10-05.

**Upozornění:** ceny jsou orientační z webu (USD, bez DPH a dopravy) a podle rozhodnutí zadavatele se v českých e-shopech neověřovaly. U položek bez ceny je uvedeno „neověřeno“. Počty relé vycházejí z odhadu, protože počet spínaných cest mezi komponentami DUT (PR-01) není přesně určen.

## 1. Seznam

| # | Položka | Počet | Cena za kus (USD) | Odkaz | Poznámka |
|---|---|---|---|---|---|
| 1 | Fanless mini PC, Intel N100/N150 nebo srovnatelný Celeron | 1 | 250–300 | [MITXPC MES-N100DC](https://mitxpc.com/products/mes-n100dc) (příklad) | pasivní chlazení pro 24/7, alespoň 5 USB, auto start po obnovení napájení, eMMC/SSD, alespoň 1 Ethernet, Windows a Linux |
| 2 | Digilent Analog Discovery 3 | 1 | cca 390 (535 CAD) | [Digilent](https://digilent.com/shop/analog-discovery-3/) | AWG ±5 V a měření ±25 V, WaveForms SDK pro Python |
| 3 | BNC adaptér pro Analog Discovery 3 | 1 (volitelně) | neověřeno | [Digilent](https://digilent.com/reference/test-and-measurement/analog-discovery-3/specifications) | zvýší šířku pásma AWG z 9 na 12 MHz (HW-ANA-03, 10 MHz) |
| 4 | Mean Well HDR-30-24 (24 V, 1,5 A, DIN lišta) | 3 | 15–37 | [DigiKey](https://www.digikey.com/en/products/detail/mean-well-usa-inc/HDR-30-24/7703799) | 2× pro ±24 V DUT v sérii (společný střed), 1× pro napájení relé modulů |
| 5 | Waveshare Modbus RTU Relay 32-ch | 4 (odhad) | neověřeno | [Waveshare](https://www.waveshare.com/modbus-rtu-relay-32ch.htm) | multiplexer, spínání napájení a stimulace, viz kap. 2. Alternativa: [Papouch Quido RS 2/32](https://papouch.com/quido-rs-2-32-2-vstupy-32-vystupu-a-teplomer-p4662/?vid=1846), 5 280 Kč bez DPH, 32 přepínacích relé + 2 izolované vstupy, do 230,4 kBd, nutné přepnout z Spinelu na Modbus RTU, varistor 0,64 nF na výstupu |
| 6 | Modul s digitálními vstupy pro čtení 8 výstupů DUT (suché kontakty) a LED | 1 | neověřeno | [Advantech USB-4761](https://www.advantech.com/en-us/products/1-2MLKNO/USB-4761/mod_c1e301ab-cdc8-45c0-b610-6aea44b544ae) | alternativa k ověření: [Waveshare Modbus RTU Relay (D)](https://www.waveshare.com/modbus-rtu-relay-d.htm) s digitálním vstupem, zda umí číst suché kontakty, jsem neověřil |
| 7 | Modul s FT4232H (4× UART) pro RS-485 a UART | 1 | 26,99 | [Waveshare Industrial USB To 4-Ch Serial Converter](https://www.waveshare.com/usb-to-4ch-serial-converter.htm) | FT4232HL, port A TTL, B TTL/RS-485, C izolovaný RS-485/422, D izolovaný RS-232/485, automatické řízení směru. RS-485 do 921 600 baud, což zadavatel potvrdil jako dostatečné. Využití portů: C aktivní RS-485, D pasivní záchyt, A konzole, B UART log (TTL) |
| 8 | USB převodník na RS-485, izolovaný | 1 | neověřeno | [innomaker](https://www.amazon.com/Industrial-Converter-Adapter-Protection-Support/dp/B0B2QSW67D) (příklad) | pátý port pro sběrnici relé modulů (zadavatel) |
| 9 | ST-Link V2 nebo V3 | 1 | cca 10–40 (V2) | [přehled](https://microcontrollerslab.com/best-jtag-swd-debuggers-embedded-firmware-developers-buying-guide/) | JTAG/SWD a flashování, V3 cena neověřena |
| 10 | Napájený USB hub | 1 (podle PC) | neověřeno | | pokud PC nemá dost USB portů |
| 11 | Pojistky (jedna v každé větvi napájení), DIN lišta, svorky, kabeláž | podle zapojení | neověřeno | | zdroje HDR nemají omezení proudu stejně jako laboratorní zdroje |

**Poznámka k RS-485:** poruchy sběrnice RS-485 A/B se zatím řeší relé z modulů Waveshare (zadavatel). Pokud měření ukáže problém při 921 600 baud, lze později přidat photoMOS Panasonic AQY221N3V na malé desce.

## 2. Odhad počtu relé

| Účel | Relé |
|---|---|
| Multiplexer generovaných signálů (47 vstupů DUT × 2 relé, jeden rychlý vstup napřímo) | 94 |
| Multiplexer měřených výstupů ±24 V (4 vstupy na 2 kanály Analog Discovery 3) | 4 |
| Spínání napájení DUT (oba póly) | 2 |
| Stimulace binárních vstupů DUT (do 4) | 4 |
| Poruchová matice mezi komponentami (napájení, RS-485 A/B, digitální signály, odhad) | 10 až 20 |
| **Celkem** | **cca 115 až 125** |

To odpovídá čtyřem 32kanálovým modulům (128 relé). Při méně využitých vstupech DUT stačí méně, např. 3 moduly pro 96 relé. Moduly se nastaví na různé adresy (1–255) a řetězí se na jedné sběrnici RS-485 na samostatném USB převodníku (položka 8).

## 3. Součet známých cen

| Položka | USD |
|---|---|
| PC (1) | 250–300 |
| Analog Discovery 3 (2) | cca 390 |
| 3× HDR-30-24 (4) | 45–111 |
| FT4232H modul Waveshare (7) | 26,99 |
| ST-Link (9) | 10–40 |
| **Součet cen, které jsou známé** | **cca 720 až 870** |

Do rozpočtu 2 000 USD zbývá cca 1 130 až 1 280 USD na položky 3, 5, 6, 8, 10, 11 (relé moduly jsou největší položka). Zda se vše vejde, jsem neověřoval, protože ceny a dostupnost podle zadavatele ověřovat netřeba.

## 4. Co zbývá udělat vlastní prací

1. Zapojení relé multiplexeru, měřicího multiplexeru a poruchové matice (svorky a kabeláž, žádné desky).
2. Sériové zapojení dvou zdrojů HDR-30-24 se společným středem a pojistky.
3. Nastavení adres a rychlosti modulů Waveshare (ve výchozím stavu 9 600 baud, až 256 000 baud).
4. Přípravek nebo konektory pro připojení DUT (PR-05 jsem vypustil, zapojení určíte vy).
5. Software: HAL a konfigurace stanice podle [software-a-ci.md](software-a-ci.md), GitHub Actions runner.
6. Ověření měřením při stavbě: šířka pásma relé pro rychlé kanály, RS-485 při 921 600 baud, přesnost výpadku napájení, výchozí stav relé po startu a počet modulů na sběrnici.

## 5. Doporučené pořadí nákupu

1. Nejdřív PC, Analog Discovery 3, ST-Link a jeden 32kanálový relé modul. Ověřit, že WaveForms SDK a pytest fungují na PC a že relé modul jde ovládat z Pythonu.
2. Potom zdroje HDR a zbývající relé moduly po upřesnění počtu spínaných cest (PR-01).
3. Nakonec FT4232H, převodníky RS-485 a vstupní modul podle potřeb prvních testů.

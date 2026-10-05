# Zvolená sestava HIL stanoviště

Výsledek výběru platformy pro [specifikaci](../hil-specifikace.md). Co koupit je v [nakupni-seznam.md](nakupni-seznam.md), jak sestavu používat z testů a CI je v [software-a-ci.md](software-a-ci.md).

**Upozornění:** sestava vychází z údajů z webu, nic nebylo měřeno na hardwaru. Ceny jsou orientační (USD) a v českých e-shopech se neověřovaly. Rozpočet je 2 000 USD na stanoviště.

## Sestava

| Subsystém | Volba | Poznámka |
|---|---|---|
| Řídicí PC | fanless x86 mini PC s Intel N100/N150 nebo srovnatelným Celeronem (cca 250–300 USD) | Rozhoduje krabice: pasivní chlazení pro 24/7, alespoň 5 USB portů, automatický start po obnovení napájení v BIOSu, eMMC nebo SSD (ne SD karta), alespoň 1 Ethernet, Windows a Linux. Alternativa: Raspberry Pi 5 v pasivní skříni s NVMe, ale Analog Discovery 3 s ním Digilent netestoval a má jen 4 USB porty, použít jen po ověření |
| Generování a měření analogu | Digilent Analog Discovery 3 (cca 390 USD) | 2 kanály AWG ±5 V (9 MHz, s BNC adaptérem 12 MHz), 2 kanály měření ±25 V, Python (WaveForms SDK) |
| Napájení DUT | 2× Mean Well HDR-30-24 (24 V/1,5 A, DIN lišta) v sérii, společný střed = ±24 V | Pevné napětí, bez řízení. Výstupy jsou izolované (500 V). Spínání relé z modulů Waveshare, spínat oba póly, pojistka v každé větvi |
| Relé (spínání napájení, stimul vstupů, poruchy, multiplexer) | Waveshare Modbus RTU Relay moduly (32-ch, nebistabilní), řetězené na jedné sběrnici RS-485 | Relé 1NO + 1NC, 10 A/30 V DC, adresa 1–255, rychlost až 256 000 baud. **Nepoužít bistabilní verzi.** Do budoucna možná Modbus TCP po Ethernetu |
| Sběrnice relé | USB převodník na RS-485 (izolovaný) | pátý port vedle čtyř portů FT4232H |
| Komunikace | modul s FT4232H (4 porty). Kandidát: [Waveshare Industrial USB To 4-Ch Serial Converter](https://www.waveshare.com/usb-to-4ch-serial-converter.htm) (FT4232HL, 26,99 USD) | aktivní RS-485/Modbus RTU, pasivní záchyt, UART log, konzole. Waveshare modul: port A jen TTL, port B TTL/RS-485, porty C a D izolované RS-485/422 (D také RS-232), automatické řízení směru, RS-485 a RS-232 do 921 600 baud (zadavatel potvrdil, že RS-485 tuto rychlost nepřekročí), TTL až 12 Mbaud |
| Čtení výstupů DUT a LED | modul s digitálními vstupy (např. Advantech USB-4761) | 8 suchých kontaktů a snímání LED |
| Ladění | ST-Link V2 nebo V3 | JTAG/SWD a flashování přes OpenOCD nebo STM32CubeProgrammer |

## Zapojení

```
řídicí PC (fanless) ── GitHub Actions runner, pytest, HAL
  │ USB
  ├─ Analog Discovery 3 ── generátor 1, 2 ──► relé multiplexer ──► vstupy DUT
  │                         měření (2 kanály) ◄── relé multiplexer ◄── výstupy DUT (±24 V)
  ├─ FT4232H ── RS-485 aktivní, RS-485 pasivní záchyt, UART log, konzole
  ├─ USB–RS-485 ── sběrnice relé modulů Waveshare (adresy 1–255)
  ├─ vstupní modul ── 8 výstupů DUT (suché kontakty), LED
  └─ ST-Link ── JTAG/SWD DUT

Napájení DUT: 2× HDR-30-24 v sérii (±24 V) ── relé (oba póly) ── pojistky ── DUT
Poruchová matice: relé v cestách mezi komponentami DUT (napájení, RS-485 A/B, digitální signály)
```

### Relé multiplexer

- Každý vstup DUT má dvě relé: první vybere zdroj (generátor 1 nebo 2), druhé připojí vstup k DUT. Rozepnuto znamená bez signálu.
- Pro 48 vstupů je to 96 relé, tedy asi 3 moduly 32-ch. Při méně využitých vstupech stačí méně.
- Jeden rychlý kanál (1 MHz) zapojit napřímo bez relé, protože šířka pásma relé není dokumentována.
- Měření výstupů DUT (±24 V): 4 vstupy na 2 kanály Analog Discovery 3, několik relé z týchž modulů.

## Rozpočet

Součet známých cen (PC, Analog Discovery 3, 3× HDR-30-24, modul FT4232H, ST-Link) je asi 720 až 870 USD. Zbývá asi 1 130 až 1 280 USD na relé moduly, vstupní modul, převodník RS-485, USB hub a pojistky. Zda se vše vejde, nebylo ověřeno.

## Co ověřit při stavbě

1. Šířka pásma relé pro rychlé kanály (1 MHz).
2. Vliv relé na RS-485 při 921 600 baud a ztráty rámců při pasivním záchytu. Pokud relé signál zkreslí, přidat polovodičový spínač (photoMOS, např. Panasonic AQY221N3V) na malé desce.
3. Skutečná přesnost výpadku napájení přes relé (požadavek 10 ms, zpoždění řízení je akceptováno).
4. Výchozí stav relé Waveshare při startu a po výpadku napájení a počet modulů na jedné sběrnici RS-485.

## Rozhodnutí zadavatele

- Generované analogové signály jsou ±5 V, měření výstupů DUT zůstává ±24 V.
- Požadavek na 100 MHz generování a hardwarový watchdog se nepožadují.
- Napájení je pevné ±24 V, výpadky vyvolává relé. Přesnost 10 ms je akceptována jako hraniční.
- Zdroj Mean Well HDR vyhovuje chlazení a má izolovaný výstup (500 V), 10 MHz s Analog Discovery 3 je akceptováno.
- RS-485 poruchy se zatím řeší relé, photoMOS se nepoužije.
- Ladicí sonda je ST-Link V2 nebo V3. J-Link EDU Mini nelze použít (jen nekomerční licence).

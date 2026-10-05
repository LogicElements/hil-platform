# Specifikace HIL platformy pro closed-loop testy

Stav: schváleno zadavatelem · Datum: 2026-10-03

Tento dokument specifikuje, co mají automatické closed-loop (HIL) testy pokrýt a jaké požadavky z toho plynou na testovací platformu. Na jejím základě byla vybrána sestava, viz [vyber/doporuceni.md](vyber/doporuceni.md).

## 1. Účel a rozsah

**Cíl:** definovat požadavky na HIL platformu, která v CI automaticky testuje firmware embedded elektroniky, včetně chování při poruchách.

**V rozsahu:**
- funkční testy firmwaru testovaného systému (DUT),
- testy poruchových stavů (vkládání poruch do napájení, signálů a komunikace),
- generování analogových vstupních signálů a vyhodnocení digitálních výstupů,
- monitorování a aktivní řízení komunikace RS-485 a UART,
- ladicí rozhraní (flashování, konzole).

**Mimo rozsah:**
- cloudové služby a mobilní aplikace,
- hotová komerční HIL řešení (z rozpočtových důvodů),
- hardwarová synchronizace a mikrosekundové časování mezi kanály,
- přesná analogová měření DUT (měří se jen DC a RMS do 10 kHz, viz A-06).

## 2. Testovaný objekt a kontext nasazení

**DUT:** embedded vícekanálová měřicí elektronika, systém ze 2 až 3 komponent, které jsou funkční pouze jako celek. Poruchy se simulují rozpojováním signálů mezi komponentami a zásahy do vstupů.

**Priority testů:** (1) funkční chování firmwaru, (2) poruchové stavy, (3) analogová část.

**Nasazení:**
- první etapa: jedno sdílené stanoviště integrované do CI (GitHub Actions),
- nepřetržitý provoz, pasivní chlazení, nízký rozpočet,
- do budoucna více instancí (farma), viz požadavek NF-05.

**Způsob řízení testů:** sekvenční stimul a odezva řízené z PC. Testy se píší v Pythonu (pytest) a verzují v gitu spolu s kódem. Časování stačí softwarové, v řádu milisekund.

## 3. Katalog testovaných scénářů

Priorita: **V** = vysoká, **S** = střední, **N** = nízká. Scénáře skupiny F popisují chování celého systému a odkazují se na elementární scénáře skupin D, C, A a P.

### 3.1 F – funkční (priorita V)

| ID | Scénář | Používá | Priorita |
|---|---|---|---|
| F-01 | Zapnutí DUT a jeho start do provozního stavu | D-01, C-02 | V |
| F-02 | Reakce systému na změny a kombinace binárních vstupů | D-01, D-02 | V |
| F-03 | Komunikace mezi komponentami a s řídicí stanicí | C-01, C-03 | V |
| F-04 | Parametrizace a čtení stavu přes sériovou konzoli | C-02 | S |
| F-05 | Regresní běh po každém flashování nové verze firmwaru | F-01 až F-04 | V |

### 3.2 D – digitální (priorita V)

| ID | Scénář | Priorita |
|---|---|---|
| D-01 | Stimulace až 4 binárních vstupů DUT (5–24 V) | V |
| D-02 | Sledování méně než 8 binárních výstupů DUT (suché kontakty) | V |
| D-03 | Měření doby mezi stimulem a změnou výstupu s přesností řádu ms | S |

### 3.3 C – komunikační (priorita V)

| ID | Scénář | Priorita |
|---|---|---|
| C-01 | Pasivní monitorování RS-485 (typicky Modbus RTU) a dekódování rámců | V |
| C-02 | Záznam UART systémového logu s časovými razítky | V |
| C-03 | Aktivní komunikace platformy jako Modbus RTU master | V |
| C-04 | Simulace Modbus RTU slave nebo chybějícího zařízení na sběrnici | S |
| C-05 | Vyhledávání vzorů a chyb v záznamech a jejich vyhodnocení | S |

Rychlosti: RS-485 od 19 200 do 921 600 baud (zadavatel), UART od 19 200 baud do 1 Mbaud.

### 3.4 P – poruchové (priorita V)

| ID | Scénář | Priorita |
|---|---|---|
| P-01 | Úplný výpadek napájení DUT, krátký (od 100 ms) i delší (sekundy) | V |
| P-02 | Přerušení vodiče (napájení, RS-485, digitální signál) mezi komponentami a na vstupech | V |
| P-03 | Zkrat na zem vodiče (napájení, signál) mezi komponentami a na vstupech | V |
| P-04 | Ztráta komunikace (odpojení sběrnice, mlčící zařízení) | V |
| P-05 | Chybné rámce a zahlcení sběrnice RS-485 a UART | V |
| P-06 | Reset nebo restart zařízení v nečekanou chvíli | V |
| P-07 | Přerušené flashování firmwaru | S |
| P-08 | Sekvence zapnutí a vypnutí napájení (opakovaná, s proměnnými prodlevami) | S |

### 3.5 A – analogové (priorita S)

| ID | Scénář | Priorita |
|---|---|---|
| A-01 | Generování pomalých signálů, 32 kanálů, 10 kHz, ±5 V | S |
| A-02 | Generování rychlých signálů, 16 kanálů, 1 MHz, ±5 V | S |
| A-03 | Generování rychlého signálu (10 MHz) na jednom kanálu, ±5 V | N |
| A-04 | Chybějící signál na vstupním kanálu (odpojení) | S |
| A-05 | Směrování generovaných signálů na zvolené kanály (multiplexování) | S |
| A-06 | Měření až 4 analogových výstupů DUT (±24 V, šířka pásma 10 kHz): DC hodnota a AC složka jako RMS, kanály multiplexované | S |

Poznámka: amplituda generovaných signálů je ±5 V (zúženo zadavatelem). Měření výstupů DUT (A-06) zůstává v rozsahu ±24 V. Kanály lze multiplexovat. Současně je potřeba generovat nejvýše na 2 signálech. K ověření rychlého chování stačí jeden kanál. Pro A-03 je požadavkem 10 MHz. 100 MHz zadavatel nepožaduje (nelze realizovat v rámci rozpočtu).

## 4. Požadavky na platformu

Závaznost: **MUSÍ** (nutné), **MĚL BY** (žádoucí, rozhodne se při výběru podle ceny). Sloupec „Z“ odkazuje na zdrojové scénáře.

### 4.1 Digitální stimul a vyhodnocení (HW-DIG)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| HW-DIG-01 | Platforma MUSÍ poskytovat alespoň 4 spínané výstupy (relé nebo SSR) pro stimulaci binárních vstupů DUT v rozsahu 5–24 V. | MUSÍ | D-01, F-02 |
| HW-DIG-02 | Platforma MUSÍ číst stav alespoň 8 binárních výstupů DUT (suché kontakty) a vyhodnocovat otevřeno a sepnuto. | MUSÍ | D-02, F-02 |
| HW-DIG-03 | Platforma MUSÍ pořizovat softwarová časová razítka změn s přesností ms. | MUSÍ | D-03 |
| HW-DIG-04 | Platforma MUSÍ umožnit ovládání tlačítek DUT a snímání LED (alespoň logický stav svítí a nesvítí). | MUSÍ | F-01, F-02 |

### 4.2 Napájení DUT (HW-PWR)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| HW-PWR-01 | Platforma MUSÍ napájet DUT pevným symetrickým stejnosměrným napětím ±24 V s proudem alespoň 1 A na výstup (dva výstupy se společným středem) a umět napájení zapnout a vypnout z Pythonu spínáním v cestě napájení (relé nebo polovodičový spínač). Řízení napětí zdroje není požadováno. | MUSÍ | F-01, P-01, P-08 |
| HW-PWR-02 | Platforma MUSÍ simulovat výpadek napájení s dobou trvání od 100 ms výše s opakovatelností lepší než 10 ms. | MUSÍ | P-01, P-08 |
| HW-PWR-03 | Platforma MUSÍ obsahovat nouzové odpojení napájení DUT řízené z řídicí vrstvy. | MUSÍ | všechny |

### 4.3 Vkládání poruch do propojení (HW-FLT)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| HW-FLT-01 | Platforma MUSÍ umožnit rozpojení vodičů mezi komponentami DUT: napájení, RS-485 (A i B zvlášť) a digitální signály. | MUSÍ | P-02, P-04 |
| HW-FLT-02 | Platforma MUSÍ umožnit zkrat na zem pro stejné vodiče. | MUSÍ | P-03 |
| HW-FLT-03 | Spínací prvky v cestě sběrnice MUSÍ zachovat integritu signálu při rychlostech do 921 600 baud (nízká kapacita, bez zkreslení). | MUSÍ | P-02, P-04 |
| HW-FLT-04 | Počet a zatížitelnost spínaných cest MUSÍ být konfigurovatelné (viz předpoklad PR-01). | MUSÍ | P-02, P-03 |

### 4.4 Komunikace (HW-COM)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| HW-COM-01 | Platforma MUSÍ pasivně monitorovat RS-485 bez ovlivnění sběrnice a bez ztráty rámců při rychlostech 19 200 až 921 600 baud. | MUSÍ | C-01 |
| HW-COM-02 | Platforma MUSÍ dekódovat rámce Modbus RTU a poskytnout je testu v Pythonu. | MUSÍ | C-01, C-05 |
| HW-COM-03 | Platforma MUSÍ zaznamenávat UART systémový log s časovými razítky při rychlostech 19 200 až 1 Mbaud. | MUSÍ | C-02, F-01 |
| HW-COM-04 | Platforma MUSÍ aktivně vysílat na RS-485 a UART (Modbus RTU master, vlastní rámce) včetně spolehlivého přepínání směru. | MUSÍ | C-03, F-03 |
| HW-COM-05 | Platforma MUSÍ umět injektovat chybné rámce (špatný CRC, zkrácený, prodloužený, chybná parita) a generovat zahlcení sběrnice. | MUSÍ | P-05 |
| HW-COM-06 | Platforma MĚL BY simulovat Modbus RTU slave nebo chybějící zařízení na sběrnici. | MĚL BY | C-04 |

### 4.5 Ladicí rozhraní (HW-DBG)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| HW-DBG-01 | Platforma MUSÍ umožnit flashování firmwaru DUT přes JTAG/SWD z CI bez zásahu člověka. | MUSÍ | F-05 |
| HW-DBG-02 | Platforma MUSÍ poskytnout sériovou konzoli DUT z Pythonu. | MUSÍ | F-04, C-02 |
| HW-DBG-03 | Platforma MUSÍ umět přerušit flashování (odpojením napájení nebo ladicího rozhraní) a reset DUT v definovanou chvíli. | MUSÍ | P-06, P-07 |

### 4.6 Analogové generování (HW-ANA)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| HW-ANA-01 | Platforma MUSÍ generovat napěťové signály v rozsahu ±5 V na 32 pomalých kanálech s šířkou pásma alespoň 10 kHz. | MUSÍ | A-01 |
| HW-ANA-02 | Platforma MUSÍ generovat napěťové signály v rozsahu ±5 V na 16 rychlých kanálech s šířkou pásma alespoň 1 MHz. | MUSÍ | A-02 |
| HW-ANA-03 | Platforma MUSÍ generovat signál s šířkou pásma alespoň 10 MHz na jednom kanálu. | MUSÍ | A-03 |
| HW-ANA-04 | *Vypuštěno zadavatelem (2026-10-05): 100 MHz generování se nepožaduje, nelze realizovat v rámci rozpočtu.* | – | – |
| HW-ANA-05 | Platforma MUSÍ současně generovat až 2 nezávislé signály a směrovat je multiplexerem na libovolný ze zvolených kanálů. | MUSÍ | A-05 |
| HW-ANA-06 | Platforma MUSÍ umět odpojit signál od zvoleného vstupního kanálu DUT (stav „bez signálu“). | MUSÍ | A-04 |
| HW-ANA-07 | Platforma MUSÍ měřit až 4 analogové výstupy DUT v rozsahu ±24 V s šířkou pásma alespoň 10 kHz a poskytnout testu DC hodnotu a AC složku jako RMS. Kanály lze multiplexovat na menší počet měřicích vstupů. Přesnost viz PR-02. | MUSÍ | A-06 |

### 4.7 Software a integrace (SW)

| ID | Požadavek | Závaznost | Z |
|---|---|---|---|
| SW-01 | Testy MUSÍ být psané v Pythonu (pytest) a verzované v gitu. | MUSÍ | F-05 |
| SW-02 | Platforma MUSÍ poskytovat abstrakční vrstvu (HAL) nad přístroji, aby testy nezávisely na výrobci hardwaru. | MUSÍ | NF-05 |
| SW-03 | Platforma MUSÍ vytvářet výstup ve formátu JUnit XML a archivovat záznamy (UART log, RS-485 záznam, časové řady) ke každému běhu. | MUSÍ | F-05, C-05 |
| SW-04 | Platforma MUSÍ běžet jako self-hosted runner pro GitHub Actions a zamykat zdroje stanoviště tak, aby běžel vždy jen jeden test. | MUSÍ | NF-02 |
| SW-05 | Konfigurace stanoviště a DUT MUSÍ být soubory verzovanými v gitu. | MUSÍ | NF-05 |

## 5. Nefunkční požadavky

| ID | Požadavek | Závaznost |
|---|---|---|
| NF-01 | Nepřetržitý provoz 24/7, řídicí PC a všechny komponenty pasivně chlazené (bez ventilátorů). | MUSÍ |
| NF-02 | Integrace do CI na GitHubu (GitHub Actions, self-hosted runner). | MUSÍ |
| NF-03 | Automatická obnova po výpadku sítě nebo napájení bez zásahu člověka (automatický start služeb). | MUSÍ |
| NF-04 | Nízký rozpočet: preferovat běžně dostupné moduly a skládání z nich, bez závislosti na jednom výrobci. Konkrétní limit viz PR-03. | MUSÍ |
| NF-05 | Platforma je univerzální a modulární: skládá se ze stavebních bloků (digitální, napájení, poruchová matice, komunikace, analogové generování), které lze použít pro jiné DUT. Každá instance může mít odlišný počet a typ bloků, konfigurace tedy nemusí být shodná na všech instancích. Software a testy musí s různou konfigurací pracovat (zjištění dostupných bloků z konfigurace). | MUSÍ |
| NF-06 | Škálování na více stanovišť: každé stanoviště má vlastní runner a štítek (label), stejný software a konfigurační formát. | MĚL BY |

## 6. Matice sledovatelnosti

| Scénář | Požadavky |
|---|---|
| F-01 | HW-DIG-04, HW-PWR-01, HW-COM-03 |
| F-02 | HW-DIG-01, HW-DIG-02, HW-DIG-04 |
| F-03 | HW-COM-01, HW-COM-04 |
| F-04 | HW-DBG-02 |
| F-05 | HW-DBG-01, SW-01, SW-03 |
| D-01 | HW-DIG-01 |
| D-02 | HW-DIG-02 |
| D-03 | HW-DIG-03 |
| C-01 | HW-COM-01, HW-COM-02 |
| C-02 | HW-COM-03, HW-DBG-02 |
| C-03 | HW-COM-04 |
| C-04 | HW-COM-06 |
| C-05 | HW-COM-02, SW-03 |
| P-01 | HW-PWR-01, HW-PWR-02 |
| P-02 | HW-FLT-01, HW-FLT-03, HW-FLT-04 |
| P-03 | HW-FLT-02, HW-FLT-04 |
| P-04 | HW-FLT-01, HW-FLT-03 |
| P-05 | HW-COM-05 |
| P-06 | HW-DBG-03 |
| P-07 | HW-DBG-03 |
| P-08 | HW-PWR-01, HW-PWR-02 |
| A-01 | HW-ANA-01 |
| A-02 | HW-ANA-02 |
| A-03 | HW-ANA-03 |
| A-04 | HW-ANA-06 |
| A-05 | HW-ANA-05 |
| A-06 | HW-ANA-07 |

## 7. Předpoklady a otevřené body

| ID | Bod | Výchozí předpoklad | Kdo potvrdí |
|---|---|---|---|
| PR-01 | Počet spínaných cest mezi komponentami DUT a jejich proudy | Jednotky až desítky cest, pevné napájení ±24 V a proud do 1 A (zadavatel); signály a sběrnice v mA. | Tým DUT |
| PR-02 | Přesné rozsahy, rozlišení a přesnost analogových signálů (generování i měření DC a RMS) | Generování ±5 V (rozhodnuto zadavatelem), měření ±24 V. Rozlišení a přesnost nejsou specifikovány. | Tým DUT |
| PR-03 | Limit rozpočtu na jedno stanoviště | **2 000 USD** (zadavatel). Součet známých cen sestavy viz [nákupní seznam](vyber/nakupni-seznam.md). | Vedení |

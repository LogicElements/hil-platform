# Nasazení stanoviště

## Linux (Debian, Raspberry Pi OS)

### Instalace balíčku

1. Uživatel stanoviště a skupiny pro sériové porty a ladicí sondu:
   `sudo useradd -m -G dialout,plugdev hil`
2. Repozitář a virtuální prostředí:
   ```
   sudo mkdir -p /opt/hil && sudo chown hil: /opt/hil
   git clone https://github.com/LogicElements/hil-platform.git /opt/hil/hil-platform
   python3 -m venv /opt/hil/venv
   /opt/hil/venv/bin/pip install -e /opt/hil/hil-platform
   ```
   Repozitář je veřejný, ke klonování přes HTTPS stanice nepotřebuje klíč pro GitHub.
3. OpenOCD z distribuce: `sudo apt install openocd`. Balíček přidá pravidla udev pro ST-Link. Ovladač `openocd` používá syntaxi `adapter serial` a `adapter speed`, potřebuje tedy OpenOCD 0.12 nebo novější (`adapter serial` je od verze 0.12.0, starší verze měly `hla_serial`). Debian bookworm i trixie obsahují verzi 0.12. S ní funguje výchozí `interface/stlink.cfg` (ověřeno s ST-Link V3 a STM32H7A3).
4. WaveForms a Adept runtime pro Analog Discovery 3 se instalují podle [návodu Digilentu](https://digilent.com/reference/test-and-measurement/guides/getting-started-with-raspberry-pi) (na Raspberry Pi verze ARM64 pro 64bitový systém, na x86 balíčky `.deb` pro amd64). Balíčky se stahují ručně ze stránek Digilentu a instalují `sudo apt install ./digilent.adept.runtime_…_arm64.deb ./digilent.waveforms_…_arm64.deb`. Na Raspberry Pi OS Lite (bez desktopu) skončí instalace WaveForms chybou skriptu `postinst`, protože chybí adresáře menu. Pomůže `sudo mkdir -p /usr/share/desktop-directories /etc/xdg/menus/applications-merged` a `sudo dpkg --configure -a`. Adept runtime přidá pravidla udev pro přístup k AD3. Ovladač `analog_discovery_3` načte knihovnu `libdwf.so` při otevření stanoviště. Pokud je knihovna jinde než v cestě dynamického linkeru, uveďte ji ve stanovišti volbou `library`. Ověření: `hil check --station stations/lab-a.yaml --probe`.

### Pravidla udev

Soubor [deploy/udev/99-hil.rules](../../deploy/udev/99-hil.rules) zpřístupní porty FTDI skupině `dialout` a nastaví latency timer FTDI na 1 ms (pasivní záchyt RS-485 jinak slévá rámce). Bez pravidla se balíček pokusí latency timer nastavit sám a při chybějících právech jen varuje.

### Bezpečný stav po startu

Služba [deploy/systemd/hil-safe.service](../../deploy/systemd/hil-safe.service) spustí po startu PC `hil safe` (NF-03). V souboru upravte cestu k prostředí a ke stanovišti. `hil safe` pracuje best-effort: zařízení, které se nepodaří otevřít, přeskočí (i zařízení na něm závislá), na ostatních nastaví bezpečný stav, chyby vypíše a skončí kódem 3. Výsledek ukáže `systemctl status hil-safe`.

### Ukončení běžících testů

SIGINT (Ctrl+C), SIGTERM (`systemctl stop`, zrušení jobu v GitHub Actions) a SIGHUP (zavřený terminál) běh testů přeruší a úklid nastaví úplný bezpečný stav. Obsluha signálu sama na sběrnici nesahá. Rozpracovaná transakce se přeruší a sběrnice zůstane potichu až do konce jejího timeoutu, aby se pozdní odpověď modulu nesrazila s vypnutím napájení. Každý další signál od prvního až do zavření stanoviště se jen zaloguje, proces pak jde zastavit jen signálem SIGKILL, který systemd i CI pošlou po vypršení svého timeoutu. Pod `nohup` zůstává SIGHUP ignorovaný. Při `atexit` (konec interpretu bez úklidu) se vypne aspoň napájení DUT. Po SIGKILL nebo pádu interpretu neproběhne nic: relé a Analog Discovery 3 (výstupy DIO ověřené na HW) drží poslední stav až do dalšího otevření stanoviště. Proto má job v CI po testech krok `hil safe --station …` s `if: always()`, aby se stanoviště uklidilo i po zabitém procesu.

## Windows (vývoj)

- Ovladač FTDI VCP je součástí Windows Update. Latency timer nastavte ve Správci zařízení: port, Vlastnosti, Port Settings, Advanced, Latency Timer 1 ms. Balíček ho na Windows neověřuje, jen to připomene v logu. Platí to i pro převodník sběrnice relé, s výchozími 16 ms trvá každá transakce Modbus o 16 ms déle.
- Port lze zadat jako `COM7` nebo sériovým číslem čipu FTDI (`{serial: FT4ABC, interface: 2}`). Jednokanálový čip (FT232R, FT232H) má jen `interface: 0`.
- OpenOCD (např. sestavení xPack) přidejte do `PATH`, nebo ve stanovišti uveďte `command: [C:/tools/openocd/bin/openocd.exe]`.
- WaveForms (s Adept runtime) nainstaluje `dwf.dll` do systémového adresáře, ovladač ji najde bez další konfigurace. Program WaveForms musí být během testů zavřený, AD3 jde otevřít jen jedním programem.
- Ukončení: Ctrl+C a Ctrl+Break přeruší běh stejně jako na Linuxu.

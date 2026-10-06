# hil-platform

[![package](https://github.com/LogicElements/hil-platform/actions/workflows/package.yml/badge.svg)](https://github.com/LogicElements/hil-platform/actions/workflows/package.yml)
[![license](https://img.shields.io/github/license/LogicElements/hil-platform)](LICENSE)

Platforma pro jednoduché closed-loop (HIL) testy firmwaru. Python balíček `hil` obsahuje ovladače zařízení stanoviště, HAL bloky, konfiguraci stanoviště a zapojení DUT a plugin pro pytest.

## Instalace

Python 3.12 nebo novější, Linux nebo Windows.

```
python -m pip install -e .
```

## Použití

```
python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
hil info --station sim
```

## Dokumentace

- [Specifikace HIL platformy](doc/hil-specifikace.md)
- [Doporučení výběru platformy](doc/vyber/doporuceni.md)
- [Nákupní seznam](doc/vyber/nakupni-seznam.md)
- [Architektura balíčku hil](doc/software/architektura.md)
- [Konfigurace stanoviště a DUT](doc/software/konfigurace.md)
- [Psaní a spouštění testů](doc/software/testy.md)
- [Nasazení stanoviště](doc/software/nasazeni.md)
- [HW testy stanoviště](doc/software/hw-testy.md)

## Licence

[MIT](LICENSE)

# Acalor Thermostat

Home-Assistant Custom Integration für Heiz- und Kühlanlagen mit **getrennten
Solltemperaturen** für Heizen und Kühlen. Fork des Home-Assistant
*Generic Thermostat* (Git-Basis `7ab2d69`).

## Ziel

Ein Thermostat mit drei eigenständigen Bereichen:

- **HEAT** – Heizbetrieb mit eigener Heiz-Solltemperatur
- **COOL** – Kühlbetrieb mit eigener Kühl-Solltemperatur
- **HEAT_COOL** – Automatik: entscheidet nur, welcher Modus aktiv ist (Dispatcher)

Kernmerkmale laut Lastenheft:

- Getrennte, unabhängig gespeicherte Heiz- und Kühl-Solltemperatur
- **Dynamic Dead Zone (DDZ)** – symmetrischer Mindestabstand zwischen den Sollwerten
- Gegenseitige Verriegelung von Heiz- und Kühlschalter
- Schnittstelle für **externe Anforderungen** (`heat_enable`, `cool_enable`,
  `heat_offset`, `cool_offset`) ohne Eingriff in die Regelungslogik
- Persistenz über Neustart, konfigurierbare Temperaturauflösung, Mindest-/
  Höchstlaufzeiten, Startverzögerung

> Die vollständige Spezifikation liegt unter
> [`docs/Lastenheft Acalor-Thermostat.pdf`](docs/Lastenheft%20Acalor-Thermostat.pdf).

## Installation (HACS)

1. In HACS → *Custom repositories* dieses Repository als Integration hinzufügen.
2. „Acalor Thermostat" herunterladen.
3. Home Assistant neu starten.
4. Unter *Einstellungen → Geräte & Dienste → Helfer* hinzufügen.

## Entwicklungsstand

In aktiver Entwicklung. Umsetzung in Phasen gemäß Lastenheft (Abschnitt 10).

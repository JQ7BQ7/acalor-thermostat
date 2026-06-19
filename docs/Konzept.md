# Technisches Umsetzungskonzept – Acalor Thermostat

Grundlage: Lastenheft v0.7. Bezug ist der aktuelle Code in
`custom_components/acalor_thermostat/` (Generic-Thermostat-Fork, Basis `7ab2d69`).

Dieses Dokument beschreibt **wie** wir das Lastenheft umsetzen, bevor Code entsteht.
Offene Entscheidungen sind am Ende (Abschnitt 8) gesammelt.

---

## 1. Datenmodell

### Heute (Ist)
- Ein einziger Sollwert `self._target_temp`.
- Ein Schalter `heater_entity_id`. `ac_mode` (bool) dreht die Logik zwischen Heizen/Kühlen.
- HVAC-Modi: `HEAT`, `COOL`, `OFF`.

### Ziel (Soll)
Zwei **getrennte, unabhängig gespeicherte** Sollwerte:

| Intern | Bedeutung | Climate-Attribut je Modus |
|---|---|---|
| `self._target_temp_heat` | Heiz-Solltemperatur | `target_temperature` (HEAT), `target_temperature_low` (HEAT_COOL) |
| `self._target_temp_cool` | Kühl-Solltemperatur | `target_temperature` (COOL), `target_temperature_high` (HEAT_COOL) |

**Abbildung auf Home-Assistant-Standardmechanismen** (Lastenheft 5.4 „Bevorzugte Umsetzung"):

- `supported_features` enthält **beide** Flags: `TARGET_TEMPERATURE` **und**
  `TARGET_TEMPERATURE_RANGE`.
- Das Frontend zeigt dann automatisch:
  - in **HEAT**/**COOL** → ein Sollwert-Regler (`target_temperature`)
  - in **HEAT_COOL** → ein Bereich mit zwei Griffen (`…_low`/`…_high`), Anzeige z.B. „22,0 °C – 25,0 °C"
- Property-Logik:
  - `target_temperature` → liefert Heiz-Sollwert in HEAT, Kühl-Sollwert in COOL, `None` in HEAT_COOL
  - `target_temperature_low` → immer Heiz-Sollwert
  - `target_temperature_high` → immer Kühl-Sollwert

### HVAC-Modi
`[OFF, HEAT, COOL, HEAT_COOL]` (Lastenheft 5.1).

### Entfällt
- `ac_mode` (CONF_AC_MODE) – durch zwei echte Schalter obsolet.
- **Presets** (away/eco/comfort/…) – im Lastenheft **nicht gefordert**. Mit zwei Sollwerten
  würden Presets das Modell deutlich verkomplizieren. **Empfehlung: für v1 entfernen**
  (siehe Entscheidung 8.1).

---

## 2. Konfigurationsparameter

### 2.1 Pflichtparameter (Lastenheft 7.1)

| Konstante | Bedeutung | Status |
|---|---|---|
| `CONF_SENSOR` | Temperaturfühler | vorhanden |
| `CONF_HEATER` | Heizschalter | vorhanden |
| `CONF_COOLER` | Kühlschalter | **neu** |
| `CONF_DDZ` | Dynamic Dead Zone (Mindestabstand) | **neu** |
| `CONF_HEAT_ON_TOLERANCE` | Heizung-EIN-Toleranz | **neu** (ersetzt `cold_tolerance`) |
| `CONF_HEAT_OFF_TOLERANCE` | Heizung-AUS-Toleranz | **neu** (ersetzt `hot_tolerance`) |
| `CONF_COOL_ON_TOLERANCE` | Kühlung-EIN-Toleranz | **neu** |
| `CONF_COOL_OFF_TOLERANCE` | Kühlung-AUS-Toleranz | **neu** |

**Toleranz-Semantik** (Hysterese um den jeweiligen Sollwert):

- Heizen EIN, wenn `Ist < Heiz-Soll − Heiz-EIN-Toleranz`
- Heizen AUS, wenn `Ist > Heiz-Soll + Heiz-AUS-Toleranz`
- Kühlen EIN, wenn `Ist > Kühl-Soll + Kühl-EIN-Toleranz`
- Kühlen AUS, wenn `Ist < Kühl-Soll − Kühl-AUS-Toleranz`

### 2.2 Erweiterbare Parameter (Lastenheft 7.2)

| Konstante | Bedeutung | Status |
|---|---|---|
| `CONF_MAX_DUR` | Höchstlaufzeit | vorhanden |
| `CONF_MIN_DUR_HEAT` | Mindestlaufzeit Heizen | **neu** (split aus `min_cycle_duration`) |
| `CONF_MIN_DUR_COOL` | Mindestlaufzeit Kühlen | **neu** |
| `CONF_START_DELAY` | Startverzögerung (Default **15 s**) | **neu** |
| externe Schnittstellen | siehe Abschnitt 4 | Phase 7 |
| Sperrzeiten | später | später |

### 2.3 Temperaturauflösung (Lastenheft 7.3)
- `CONF_RESOLUTION` ∈ {`0.1`, `0.5`}, Default `0.1`.
- Gilt für **alle** Werte (Sollwerte, DDZ, alle Toleranzen) – treibt `precision`,
  `target_temperature_step` und die `step`-Werte der Eingabefelder im Config-Flow.
- Ersetzt die heutigen `CONF_PRECISION` / `CONF_TEMP_STEP`.

---

## 3. Reglerkern `_evaluate()`

Statt der heutigen `_async_control_heating()`-Logik (auf *einen* Schalter zugeschnitten)
ein klar getrennter Aufbau:

```
_async_control()              # Einstieg (Sensor-Event, Timer, Moduswechsel, keep-alive)
  └─ _evaluate() -> Decision   # REINE Entscheidung: heating | cooling | idle
  └─ _apply(decision)          # schaltet Ausgänge unter Beachtung der Sperren
```

### 3.1 `_evaluate()` – die Entscheidung
Eingänge: Ist-Temperatur, Heiz-/Kühl-Sollwert (**inkl. externer Offsets**),
externe Freigaben, aktueller Modus, aktueller Ausgangszustand.

Ablauf nach Modus (Lastenheft 2 + 2.4):

- **OFF** → `idle` (beide Ausgänge AUS)
- **HEAT** → nur Heizlogik; Kühlausgang bleibt AUS
- **COOL** → nur Kühllogik; Heizausgang bleibt AUS
- **HEAT_COOL** (Dispatcher, Modus bleibt konstant):
  - `Ist < Heiz-Soll` → Heizlogik
  - `Ist > Kühl-Soll` → Kühllogik
  - sonst → `idle`

Heiz-/Kühllogik = Hysterese aus den 4 Toleranzen (Abschnitt 2.1), unter Beachtung der
externen Freigaben (`heat_enable`/`cool_enable`).

### 3.2 `_apply()` – das Schalten
Reihenfolge exakt nach Lastenheft 8.2:

1. **Neubewertung** (Ergebnis von `_evaluate()`)
2. **Mindestlaufzeit** prüfen (getrennt Heizen/Kühlen, Lastenheft 8.3 – laufender Betrieb
   darf bis Ablauf weiterlaufen)
3. **weitere Sperren** prüfen – v.a. die **gegenseitige Verriegelung** (4.1): bevor ein
   Ausgang EIN geht, ist sicherzustellen, dass der andere AUS ist
4. **Startverzögerung** (8.4): vor dem Einschalten konfigurierbare Verzögerung; nach Ablauf
   **erneute** Bewertung – nur wenn die Anforderung noch besteht, wird geschaltet
5. **Schaltentscheidung** → Ausgänge schalten

### 3.3 Gegenseitige Verriegelung (4.1)
Beim Wechsel z.B. von Heizen → Kühlen: **immer erst** den Heizausgang AUS, **dann** (ggf.
nach Startverzögerung) den Kühlausgang EIN. Ein Zustand „beide EIN" darf nie entstehen.

---

## 4. Externe Schnittstelle (Lastenheft 6) – Architektur-Seam

Der Regler kennt **keine konkreten Quellen** (Fenster, PV, …), nur generische Anforderungen.
Wir bauen die **Einhängepunkte jetzt** ein, die konkrete Anbindung an HA-Entitäten ist
laut Lastenheft 9.2 noch offen → eigentliche Quelle in **Phase 7**.

Interner Zustand mit sicheren Defaults:

| Attribut | Default | Wirkung in `_evaluate()` |
|---|---|---|
| `_ext_heat_enable` | `True` | `False` → Heizausgang zwangs-AUS |
| `_ext_cool_enable` | `True` | `False` → Kühlausgang zwangs-AUS |
| `_ext_heat_offset` | `0.0` | wird auf Heiz-Sollwert addiert (vor Bewertung) |
| `_ext_cool_offset` | `0.0` | wird auf Kühl-Sollwert addiert (vor Bewertung) |

So fließen externe Einflüsse an **genau einer** definierten Stelle ein, ohne die
Regelungslogik zu verändern (erfüllt 6.1). Die Defaults sorgen dafür, dass das System
ohne jede externe Quelle voll funktioniert.

---

## 5. DDZ-Logik (Lastenheft 3.2 / 3.3)

**Invariante:** `Kühl-Soll ≥ Heiz-Soll + DDZ` – darf **nie** verletzt werden
(nicht durch UI, Service, Automation, Neustart).

Zentrale Normalisierung `_enforce_ddz(changed)` wird bei **jeder** Sollwert-Änderung
durchlaufen (eine Quelle der Wahrheit):

- **Heiz-Soll erhöht** und Kühl-Soll < Heiz-Soll + DDZ → Kühl-Soll auf `Heiz-Soll + DDZ` nachziehen
- **Kühl-Soll gesenkt** und Heiz-Soll > Kühl-Soll − DDZ → Heiz-Soll auf `Kühl-Soll − DDZ` nachziehen
- Gilt **in beide Richtungen** (3.3)
- Greift auch beim **Restore nach Neustart** und bei **Config-Änderung** (z.B. DDZ vergrößert)

**Symmetrische DDZ / Mittenverschiebung** (3.2.1, 5.5 – *optional*):
`Mitte = (Heiz + Kühl) / 2`. Verschieben der Mitte um Δ → `Heiz += Δ`, `Kühl += Δ`,
DDZ-Breite unverändert. Optionale Komfortfunktion (siehe Entscheidung 8.3).

Alle Sollwerte werden zusätzlich auf `min_temp`/`max_temp` und die gewählte Auflösung
gerundet/geclampt.

---

## 6. Persistenz & Neustart (Lastenheft 3.4)

| Wert | Mechanismus |
|---|---|
| HVAC-Modus | `RestoreEntity` (alter `state`) |
| Heiz-Sollwert | `RestoreEntity` → `attributes[target_temp_low]` |
| Kühl-Sollwert | `RestoreEntity` → `attributes[target_temp_high]` |
| DDZ, 4 Toleranzen | **Config-Entry** (persistiert HA automatisch) |

**Nicht** gespeichert (3.4.1): `heating`/`cooling`/`idle`. Diese werden nach dem Neustart
aus den aktuellen Sensordaten **neu ermittelt** (volle Neubewertung über `_evaluate()`).
Nach dem Restore läuft `_enforce_ddz()`, um eine konsistente Ausgangslage zu garantieren.

---

## 7. Migration der bestehenden Instanz

Deine in HA laufende Instanz hat ein Config-Entry (minor_version 3) im *alten* Format.
Damit es beim Update nicht bricht: `async_migrate_entry` bumpt die Version und füllt die
neuen Felder:

- `cold_tolerance` → `heat_on_tolerance`, `hot_tolerance` → `heat_off_tolerance`
- `cool_on_tolerance` / `cool_off_tolerance` → Default (= Heizwerte oder `0.3`)
- `min_cycle_duration` → `min_dur_heat` **und** `min_dur_cool`
- `cooler` → leer (muss vom Nutzer gesetzt werden) · `ddz` → Default · `resolution` → `0.1`

**Fallback:** Da es deine Dev-Instanz ist, ist alternativ „Helfer löschen & neu anlegen"
jederzeit problemlos möglich, falls die Migration zu aufwendig wird.

---

## 8. Entscheidungen (bestätigt am 2026-06-20)

**8.1 Presets entfernen?** → **JA**, für v1 raus (nicht im Lastenheft, passt schlecht
zu Doppel-Sollwert). Später wieder einbaubar.

**8.2 Migration vs. Neuanlage?** → **Neuanlage** während der Entwicklung (kein
Migrations-Code). Der Helfer wird einmal neu angelegt; eine saubere Migration bauen wir
**einmalig am Ende**, bevor das Format stabil/produktiv ist.

**8.3 Mittenverschiebung (5.5) jetzt oder später?** → **Später** (Phase 8). Erst
getrennte Sollwerte + DDZ stabil.

**8.4 Externe Schnittstelle – Anbindungsart (Lastenheft 9.2, offen)** → Seam wird jetzt
gebaut (Abschnitt 4), konkrete Quelle in Phase 7. **Jetzt keine Festlegung nötig.**

> Folge aus 8.2: Bei jeder config-ändernden Phase muss der Helfer in HA **gelöscht und
> neu angelegt** werden. Die Config-Schema deckt deshalb schon jetzt den vollen
> Pflicht-Parametersatz ab (auch Felder, deren Logik erst in späteren Phasen aktiv wird).

---

## 9. Umsetzungsreihenfolge (an Lastenheft 10 angelehnt)

1. **Phase 3** – Datenmodell + Config: zweiter Schalter, getrennte Sollwerte, 4 Toleranzen,
   Auflösung, `_evaluate()/_apply()`-Grundgerüst (zunächst HEAT + COOL).
2. **Phase 5** – DDZ inkl. Auto-Nachziehen + Restore-Konsistenz.
3. **Phase 6** – HEAT_COOL-Dispatcher.
4. **Phase 7** – externe Schnittstelle an Quelle anbinden.
5. **Phase 8** – Startverzögerung-Feinschliff, Mittenverschiebung, erweiterte Statusanzeige (5.3).

Jede Phase = ein lauffähiger, in HA testbarer Zwischenstand mit eigenem Commit.

# Dashboard-Beispiele (Lovelace)

Fertige Karten für den Acalor Thermostat. **Vor dem Einfügen** überall die
Beispiel-Entität `climate.acalor_thermostat` durch deine echte Entitäts-ID
ersetzen (zu finden unter *Entwicklerwerkzeuge → Zustände*).

> Tipp: YAML-Karten fügst du über *Karte hinzufügen → ganz unten „Manuell"* ein,
> **nicht** über die Markdown-Karte (die rendert den Code nur als Text).

---

## 1. Thermostat-Karte (großer Regler)

Zeigt den Doppel-Regler. `name: " "` blendet den Titel aus. In einer
**Abschnitte**-View die Karte größer ziehen, damit die Ist-Temperatur außerhalb
des Kreises erscheint.

```yaml
type: thermostat
entity: climate.acalor_thermostat
name: " "
```

---

## 2. Statuskarte (Status + effektiver Wert + Schaltpunkte)

Zeigt modus-abhängig den Status, den tatsächlich angefahrenen Wert (inkl. Offset)
und die realen Ein-/Ausschaltpunkte (Hysterese). Dezimalzahlen werden mit Komma
dargestellt.

```yaml
type: markdown
content: |
  {% set e = 'climate.acalor_thermostat' %}
  {% set action = state_attr(e, 'hvac_action') %}
  **Status:** {{ state_attr(e, 'status_reason') }}

  {% if action == 'cooling' %}❄️ **Kühlt effektiv auf:** {{ state_attr(e, 'cool_setpoint_effective') | string | replace('.', ',') }} °C — ein > {{ state_attr(e, 'cool_on_at') | string | replace('.', ',') }} / aus < {{ state_attr(e, 'cool_off_at') | string | replace('.', ',') }} °C
  {% elif action == 'heating' %}🔥 **Heizt effektiv auf:** {{ state_attr(e, 'heat_setpoint_effective') | string | replace('.', ',') }} °C — ein < {{ state_attr(e, 'heat_on_at') | string | replace('.', ',') }} / aus > {{ state_attr(e, 'heat_off_at') | string | replace('.', ',') }} °C
  {% endif %}
```

Beispiel-Ausgabe beim Kühlen:

> **Status:** Kühlen (Offset −1,0 °C)
> ❄️ **Kühlt effektiv auf:** 24,5 °C — ein > 24,8 / aus < 24,2 °C

---

## 3. Komfort-Buttons: DDZ-Mitte verschieben

Verschiebt **beide** Sollwerte gemeinsam (die Mitte der Dead Zone), der Abstand
bleibt gleich. Die Schrittweite legst du über `delta` fest.

```yaml
type: horizontal-stack
cards:
  - type: button
    name: Wärmer
    icon: mdi:chevron-up
    tap_action:
      action: perform-action
      perform_action: acalor_thermostat.shift_center
      target: { entity_id: climate.acalor_thermostat }
      data: { delta: 0.5 }
  - type: button
    name: Kälter
    icon: mdi:chevron-down
    tap_action:
      action: perform-action
      perform_action: acalor_thermostat.shift_center
      target: { entity_id: climate.acalor_thermostat }
      data: { delta: -0.5 }
```

---

## 4. Temperaturverlauf (optional)

```yaml
type: history-graph
title: Temperatur Wohnzimmer
hours_to_show: 24
entities:
  - entity: sensor.DEIN_TEMPERATURSENSOR
```

---

## Verfügbare Attribute

Über `state_attr('climate.acalor_thermostat', '<attribut>')` abrufbar:

| Attribut | Bedeutung |
|---|---|
| `status_reason` | Lesbarer Status, z. B. „Heizen", „Kühlen (Offset +1,0 °C)", „Abschaltverzögerung läuft", „Heizen extern gesperrt", „Leerlauf", „Aus" |
| `heat_setpoint_effective` / `cool_setpoint_effective` | Sollwert **inkl.** externem Offset (tatsächlich angefahrener Zielwert) |
| `heat_on_at` / `heat_off_at` | Heizen schaltet EIN unterhalb / AUS oberhalb dieser Temperatur (Hysterese) |
| `cool_on_at` / `cool_off_at` | Kühlen schaltet EIN oberhalb / AUS unterhalb dieser Temperatur (Hysterese) |
| `heat_offset` / `cool_offset` | aktueller externer Offset in °C |
| `heat_enabled` / `cool_enabled` | externe Freigabe aktiv (true/false) |
| `dead_zone` | konfigurierte DDZ-Breite |
| `center` | aktuelle DDZ-Mitte |

Standard-Climate-Attribute zusätzlich: `current_temperature`, `temperature`
bzw. `target_temp_low` / `target_temp_high`, `hvac_action`, `hvac_mode`.

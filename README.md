# EV Smart Charge

Home Assistant-integration, der finder den billigste sammenhængende ladeperiode for en elbil,
så bilen er ladet til mål-SOC inden et valgt klokkeslæt. Den virker med enhver bil, der har en
batterisensor i %, og enhver elpris-sensor med en prisliste i attributterne
(fx Strømligning, Nord Pool eller Energi Data Service).

Integrationen er lavet til at levere sensorerne til panelet "Smart ladeplan" i
[`th-tesla-dashboard-card`](https://github.com/MRDonnii/ha-smart-home-cards/tree/main/src/cards/th-tesla-dashboard-card),
men den kan bruges alene.

## Installation

1. HACS → ⋮ → **Custom repositories** → `https://github.com/MRDonnii/ha-ev-smart-charge`, type **Integration**.
2. Installer **EV Smart Charge** og genstart Home Assistant.
3. **Indstillinger → Enheder & tjenester → Tilføj integration → EV Smart Charge**.
4. Vælg:
   - **Navn**, fx bilens navn. Det bliver præfiks på entiteterne.
   - **Batteriniveau (%)**, fx bilens `sensor.<bil>_battery`.
   - **Elpris-sensorer**: pris for i dag og, hvis den ligger i en separat entity, pris for i morgen.
   - **Brugbar batterikapacitet** i kWh (Model 3 RWD ≈ 57,5, Long Range ≈ 75).

Én bil pr. opsætning. Har man to biler, tilføjer man integrationen to gange.

## Entiteter

Entity-id'erne følger Home Assistants sprog, da integrationen blev tilføjet. På engelsk
(med navnet "Gokart") ser de sådan ud:

| Entity | Betydning |
|---|---|
| `number.gokart_target_soc` | Mål-SOC i %. |
| `time.gokart_ready_by` | Klokkeslæt bilen skal være klar (næste forekomst). |
| `number.gokart_charging_power` | Ladeeffekt i kW (standard 11). |
| `number.gokart_charging_efficiency` | Virkningsgrad væg → batteri (standard 0,90). |
| `number.gokart_price_factor` | Ganges på elprisen, fx rabat hos en ladeoperatør (standard 1). |
| `sensor.gokart_best_charge_start` / `sensor.gokart_expected_charge_end` | Tidsstempler for planen. |
| `sensor.gokart_best_charge_start_text` / `sensor.gokart_expected_charge_end_text` | Samme som `HH:MM`. |
| `sensor.gokart_expected_charge_price` | Pris for opladningen i elprisens valuta. |
| `sensor.gokart_missing_from_the_wall` / `sensor.gokart_missing_in_battery` | kWh, der mangler for at nå målet. |
| `sensor.gokart_charging_time` | Ladetid i minutter. |
| `sensor.gokart_ready_by_timestamp` | Næste deadline som tidsstempel. |
| `binary_sensor.gokart_plug_in_now` | Tændt de 15 minutter før planlagt start. |

## Beregning

- Manglende energi = kapacitet × (mål-SOC − SOC) / virkningsgrad.
- Ladetid = manglende energi / ladeeffekt, rundet op til hele kvarterer.
- Priserne deles op i kvarterer. Blandt alle sammenhængende vinduer, der slutter inden
  "klar senest", vælges det billigste. Er to vinduer næsten lige billige (under 0,08 i
  samlet forskel), vælges det seneste, så batteriet står fuldt så kort tid som muligt.
- Planen genberegnes hvert minut og når batteri eller priser ændrer sig.

## Brug i th-tesla-dashboard-card

```yaml
entities:
  best_charge_start: sensor.gokart_best_charge_start_text
  best_charge_end: sensor.gokart_expected_charge_end_text
  best_charge_price: sensor.gokart_expected_charge_price
  missing_wall_kwh: sensor.gokart_missing_from_the_wall
  charge_minutes_needed: sensor.gokart_charging_time
controls:
  target_soc: number.gokart_target_soc
  deadline: time.gokart_ready_by
```

Integrationen styrer ikke laderen. Den beregner kun planen; start/stop kan laves med en
automation, der fx reagerer på `sensor.gokart_best_charge_start`.

## Licens

MIT

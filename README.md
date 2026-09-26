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

| Entity | Betydning |
|---|---|
| `number.<navn>_mal_soc` | Mål-SOC i %. |
| `time.<navn>_klar_senest` | Klokkeslæt bilen skal være klar (næste forekomst). |
| `number.<navn>_ladeeffekt` | Ladeeffekt i kW (standard 11). |
| `number.<navn>_ladevirkningsgrad` | Virkningsgrad væg → batteri (standard 0,90). |
| `number.<navn>_prisfaktor` | Ganges på elprisen, fx til en rabat hos en ladeoperatør (standard 1). |
| `sensor.<navn>_bedste_ladestart` / `_forventet_ladeslut` | Tidsstempler for planen. |
| `sensor.<navn>_bedste_ladestart_tekst` / `_forventet_ladeslut_tekst` | Samme som `HH:MM`. |
| `sensor.<navn>_forventet_ladepris` | Pris for opladningen i elprisens valuta. |
| `sensor.<navn>_mangler_fra_vaeggen` / `_mangler_i_batteriet` | kWh, der mangler for at nå målet. |
| `sensor.<navn>_ladetid` | Ladetid i minutter. |
| `binary_sensor.<navn>_saet_stikket_i_nu` | Tændt de 15 minutter før planlagt start. |

De præcise entity-id'er afhænger af navn og sprog; se dem under integrationens enhed.

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
  best_charge_start: sensor.<navn>_bedste_ladestart_tekst
  best_charge_end: sensor.<navn>_forventet_ladeslut_tekst
  best_charge_price: sensor.<navn>_forventet_ladepris
  missing_wall_kwh: sensor.<navn>_mangler_fra_vaeggen
  charge_minutes_needed: sensor.<navn>_ladetid
controls:
  target_soc: number.<navn>_mal_soc
  deadline: time.<navn>_klar_senest
```

Integrationen styrer ikke laderen. Den beregner kun planen; start/stop kan laves med en
automation, der fx reagerer på `sensor.<navn>_bedste_ladestart`.

## Licens

MIT

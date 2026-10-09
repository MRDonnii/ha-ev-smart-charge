# EV Smart Charge

Home Assistant-integration, der planlægger opladningen af en elbil efter elprisen og (valgfrit)
selv starter og stopper laderen. Den virker med enhver bil, der har en batterisensor i %, og
enhver elpris-sensor med en prisliste i attributterne (fx Strømligning, Nord Pool eller Energi
Data Service).

Integrationen er lavet til at levere sensorerne til panelet "Smart ladeplan" i
[`th-tesla-dashboard-card`](https://github.com/MRDonnii/ha-smart-home-cards/tree/main/src/cards/th-tesla-dashboard-card),
men den kan bruges alene.

## Installation

1. HACS → ⋮ → **Custom repositories** → `https://github.com/MRDonnii/ha-ev-smart-charge`, type **Integration**.
2. Installer **EV Smart Charge** og genstart Home Assistant.
3. **Indstillinger → Enheder & tjenester → Tilføj integration → EV Smart Charge**.
4. Vælg:
   - **Bil**: bilens enhed, fx fra Tesla-integrationen. Batterisensor, stik-sensor og navn udfyldes
     selv. Uden en enhed vælges **Batteriniveau (%)** og evt. **Bilens tilslutnings-sensor** i hånden.
   - **Navn** (valgfrit), ellers bilens navn. Det bliver præfiks på entiteterne.
   - **Elpris-sensorer**: pris for i dag og, hvis den ligger i en separat entity, pris for i morgen.
   - **Bilmodel**: *Automatisk* finder Tesla-modellen ud fra bilens enhed og rækkevidden pr. %
     (fx Model 3 RWD). Alle Tesla-modeller kan også vælges direkte; modellen giver batterikapacitet og
     forbrug. *Anden bil*: angiv kapaciteten.
   - **Brugbar batterikapacitet** (valgfri) overskriver modellens kapacitet.
   - **Styring af laderen** (valgfri, kan også sættes senere under **Konfigurer**):
     - *Zaptec*: vælg laderens "Charger mode"-sensor fra Zaptec-integrationen. Ladekontakten og
       godkend-knappen findes selv. Kræver "Authorisation required" i Zaptec Portal, hvis laderen
       ikke må starte af sig selv.
     - *Kontakt*: en kontakt, der starter (tændt) og stopper (slukket) opladningen, fx fra OCPP,
       Monta eller Easee.

Én bil pr. opsætning. Har man flere biler, tilføjer man integrationen én gang pr. bil. Bilerne kan
dele samme lader: hver bil styrer kun laderen, når dens egen stik-sensor siger, at den er tilsluttet.

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
| `select.gokart_charge_mode` | Ladeplan, se nedenfor. |
| `sensor.gokart_charge_status` | Lader, venter på billig strøm, mål nået, ikke tilsluttet, ... |
| `sensor.gokart_next_charge_start` / `sensor.gokart_next_charge_end` | Næste ladeperiode. Attributten `blocks` har hele planen. |
| `sensor.gokart_planned_charge_cost` / `sensor.gokart_planned_charge_energy` | Pris og kWh for hele planen. |
| `sensor.gokart_plan_target_soc` | Den SOC planen lader til (mål-SOC eller turens). |
| `binary_sensor.gokart_charge_now` | Tændt, når planen vil lade lige nu. Kan bruges i egne automationer. |
| `time.gokart_fixed_charging_start` / `..._end` | Vindue for "Fast tidspunkt". |
| `number.gokart_price_cap` / `number.gokart_minimum_soc` | Prisloft og minimum for "Prisloft". |

## Ladeplaner

Vælges med `select.<bil>_charge_mode`:

| Plan | Hvad sker der |
|---|---|
| Billigst inden afgang (`smart`) | De billigste kvarterer inden "klar senest" vælges, også spredt. Ved samme pris foretrækkes kvarterer, der hænger sammen med allerede valgte. |
| Fast tidspunkt (`fixed`) | Lader fra `time.<bil>_fixed_charging_start` til `..._end`, til målet er nået. |
| Lad nu (`now`) | Lader med det samme. Bilens egen grænse bestemmer, hvornår den stopper. Skifter tilbage til forrige plan, når kablet tages ud. |
| Prisloft (`price_cap`) | Lader kun i kvarterer med kendt pris under `number.<bil>_price_cap`, men altid op til `number.<bil>_minimum_soc`. |
| Pause (`off`) | Lader ikke. |
| Manuel (`manual`) | Laderen styres ikke. Sensorerne viser planen for "Billigst inden afgang". |

Starter man selv opladningen fra laderens app eller bilen, skifter planen til **Lad nu**. Stopper
bilen eller appen opladningen, forsøger integrationen ikke at starte igen, før planen ændrer sig
eller kablet har været taget ud. Svarer laderen ikke efter tre forsøg med tre minutters mellemrum,
opgives det (status *Laderen svarer ikke*).

## Midlertidig plan (tur)

Sæt `datetime.<bil>_temporary_departure` og eventuelt `text.<bil>_trip_destination`
(adresse, `lat,lon` eller `zone.arbejde`). Afstanden hentes fra OpenStreetMap
([Nominatim](https://nominatim.org/) + [OSRM](https://project-osrm.org/)), kun når destinationen
ændres. Kan ruten ikke hentes, bruges luftlinje × 1,3.

Turens SOC = reserve + afstand × (2 ved tur/retur) × forbrug × (1 + sikkerhedsmargin) / kapacitet.
Planen lader til det højeste af mål-SOC og turens SOC inden afgang, i alle planer undtagen Pause,
Lad nu og Manuel. Indstillinger: `number.<bil>_consumption` (Wh/km, standard 180),
`number.<bil>_trip_safety_margin` (15 %), `number.<bil>_arrival_reserve` (10 %) og
`switch.<bil>_round_trip`. Planen ryddes selv, når afgangen er passeret, eller med
`button.<bil>_clear_temporary_plan`.

## Beregning

- Manglende energi = kapacitet × (mål-SOC − SOC) / virkningsgrad.
- Ladetid = manglende energi / ladeeffekt, rundet op til hele kvarterer.
- Sensorerne `best_charge_*` (fra 0.1) viser stadig det billigste *sammenhængende* vindue.
  Ladeplanen bruger enkelte kvarterer.
- Priserne deles op i kvarterer. Mangler der priser frem til afgang (fx morgendagens før kl. 13),
  skønnes de ud fra samme klokkeslæt dagen før. Planen genberegnes, når de rigtige priser kommer.
- Blandt alle sammenhængende vinduer, der slutter inden
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

Uden laderstyring beregner integrationen kun planen; start/stop kan så laves med en automation,
der reagerer på `binary_sensor.gokart_charge_now`.

## Licens

MIT

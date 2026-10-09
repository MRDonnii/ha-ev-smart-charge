# Changelog

## 0.2.0

- Ladeplaner pr. bil (`select.<bil>_charge_mode`): Billigst inden afgang (billigste kvarterer, også
  ikke-sammenhængende), Fast tidspunkt, Lad nu (nulstilles, når kablet tages ud), Prisloft med
  minimum-SOC, Pause og Manuel.
- Valgfri styring af laderen: Zaptec (via Zaptec-integrationen) eller en vilkårlig ladekontakt (OCPP,
  Monta, Easee m.fl.). Start/stop sendes kun, når laderen ikke allerede står rigtigt, med genforsøg og
  opgivelse efter tre forsøg. Starter man selv fra appen, skifter planen til Lad nu.
- Bilens egen stik-sensor kan angives, så laderen ikke styres, når en anden bil står i den.
- Midlertidig plan: afgangstidspunkt og destination (adresse, `lat,lon` eller `zone.*`). Afstanden
  hentes fra OpenStreetMap (Nominatim + OSRM), og planen lader op til det, turen kræver, plus
  sikkerhedsmargin og reserve. Planen ryddes selv, når afgangen er passeret.
- Ukendte priser (fx morgendagens før kl. 13) skønnes ud fra samme klokkeslæt dagen før, så planen
  altid kan nå målet inden afgang.
- Nye sensorer: ladestatus, næste ladestart/-slut, planlagt pris og energi, planens mål-SOC, turens
  afstand, energi og krævede SOC, samt `binary_sensor.<bil>_charge_now` til egne automationer.

## 0.1.0

- Første version: billigste ladevindue før deadline ud fra batteri-SOC og en vilkårlig elpris-sensor.

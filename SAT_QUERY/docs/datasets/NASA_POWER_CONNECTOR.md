# NASA POWER Daily Connector

SatQuery's `nasa_power` connector acquires daily point records from NASA's
Prediction Of Worldwide Energy Resources (POWER) temporal API. The adapter
uses the provider's daily point endpoint and requests UTC time stamps. NASA
documents daily solar and meteorological series from 1981 to near real time;
parameter availability is community-specific and source spatial resolution
varies by parameter ([Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/),
[parameter dictionary](https://power.larc.nasa.gov/parameters/)).

Enable it through the connector manifest:

```json
{
  "implementation": "nasa_power",
  "configuration": {
    "community": "AG"
  }
}
```

The adapter supports an explicit geographic point, UTC day-boundary start and
end values, and these declared variable mappings:

| SatQuery variable | NASA POWER parameter |
| --- | --- |
| `air_temperature` | `T2M` |
| `precipitation_amount` | `PRECTOTCORR` |
| `relative_humidity` | `RH2M` |
| `wind_speed` | `WS10M` |
| `surface_air_pressure` | `PS` |

The provider-reported unit and long name are retained in the canonical
measurement's source metadata. No unit conversion, interpolation, uncertainty
estimate, or confidence value is added. The provider-declared fill value is
retained and represented as a missing measurement, not as a valid observation.
Each result is a daily product with a one-day UTC temporal extent. It is not a
station observation. Unsupported parameters, missing provider metadata, and
invalid responses fail explicitly.

The `community` configuration defaults to `AG` and may be set to a supported
POWER community (`AG`, `RE`, or `SB`). The request may override it with the
`power_community` EarthQuery filter. NASA POWER may restrict repetitive requests
for the same relative location; use SatQuery's normal observation cache and
avoid unnecessary reacquisition. `maximum_days` bounds one request and defaults
to 18,263 days. The connector does not declare a single spatial resolution
because NASA's parameters have different source resolutions.

Example structured query:

```json
{
  "point": [-112.074, 33.4484],
  "temporal_start": "2020-01-01T00:00:00Z",
  "temporal_end": "2020-01-03T00:00:00Z",
  "requested_dataset_ids": ["nasa-power-daily-point"],
  "requested_variables": ["air_temperature", "precipitation_amount"]
}
```

NASA's daily endpoint treats the requested date bounds as daily records; the
connector requires both timestamps at UTC day boundaries and preserves the
provider's returned dates. A request ending on January 3 includes January 3.

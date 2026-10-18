# AI safety configuration

## Water pH

The environmental agent uses configurable project thresholds, in pH units:

| Setting | Default |
| --- | ---: |
| `PH_LOW` | 6.5 |
| `PH_HIGH` | 8.5 |
| `PH_CRITICAL_LOW` | 3.0 |
| `PH_CRITICAL_HIGH` | 11.0 |

Values outside `PH_LOW`–`PH_HIGH` trigger at least `MEDIUM` risk and
`INSPECTION_REQUIRED`. Readings below `PH_CRITICAL_LOW` or above
`PH_CRITICAL_HIGH` trigger `HIGH` risk and `SAFE_MODE`. Missing, invalid, or
out-of-scale readings are treated as unconfirmed water quality and trigger
inspection; they are not treated as safe.

These are application defaults for the simulated project, not universal
ecological safety limits. Set the four variables in the AI service environment
after calibrating the pH sensor and determining suitable thresholds for the
specific water body and intended use.

## Solar voltage

The serial bridge expects each sensor line as
`TL,TR,BL,BR,ServoX,ServoY,pH,SolarV` and stores the readings under
`sensors.ph` and `sensors.solarVoltage`. The bridge rejects voltage values
outside its accepted input range of 0–5 V. This parsing range is not a
recommended operating range for a solar panel. Missing or invalid voltage
readings trigger at least inspection; the actual reading is supplied to the
electrical model when available.

The repository does not contain the floating-panel Arduino sketch or a
configured panel operating-voltage threshold. Calibrate and set an
application-specific limit before relying on deterministic voltage alarms.

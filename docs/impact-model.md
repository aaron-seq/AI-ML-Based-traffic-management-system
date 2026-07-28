# The impact model

`GET /api/v1/impact/{id}` reports how much delay, fuel, CO₂ and money adaptive
control is saving. This document explains exactly how those numbers are
produced, so they can be audited rather than taken on trust.

> **Every figure here is a model estimate, not a measurement.** The system does
> not have a control group; it compares its own behaviour against a simulated
> fixed-time plan. Treat the output as an engineering estimate and re-base the
> factors on local data before using it in a business case.

## What is being compared

| | Baseline | Adaptive |
|---|---|---|
| Cycle length | `TRAFFIC_BASELINE_FIXED_CYCLE_SECONDS` (default 120 s) | Derived from measured demand |
| Green split | Even between the two phases | Proportional to queued passenger-car units |

The baseline represents what an un-upgraded junction typically runs: a fixed
plan, the same green whether the approach is full or empty.

## Step 1 — delay per vehicle

Both plans are evaluated with the uniform-delay term of Webster's formula:

```
        C · (1 − g/C)²
d = ─────────────────────
     2 · (1 − x · g/C)
```

| Symbol | Meaning |
|---|---|
| `d` | Average delay per vehicle, seconds |
| `C` | Cycle length, seconds |
| `g` | Effective green for the approach, seconds |
| `x` | Degree of saturation, `arrival rate ÷ capacity`, capped at 0.95 |

Capacity is `saturation_flow × g/C`, with saturation flow taken as **0.53
vehicles per second of green per lane** — the usual planning figure of roughly
1900 passenger cars per hour of green.

Webster assumes vehicles arrive at a constant rate. Real arrivals are bunched,
so this understates absolute delay. It is nonetheless the standard first-order
estimate and, crucially, it applies *the same assumption to both plans* — which
is what makes the comparison meaningful even where the absolute values are
approximate.

`x` is capped at 0.95 because the formula diverges as saturation approaches 1.
An oversaturated approach cannot be described by uniform-delay theory at all;
the cap keeps the output finite and conservative rather than pretending
otherwise.

## Step 2 — total delay saved

```
delay_saved = (d_baseline − d_adaptive) × vehicles_in_window
```

`vehicles_in_window` is observed throughput where the controller has recorded
completed cycles, falling back to the current standing queue on a freshly
started system.

The result can be **negative**. Under very light traffic a long adaptive cycle
can perform slightly worse than a short fixed one; the API reports that honestly
rather than clamping to zero. (The Prometheus counters do clamp, because
counters cannot decrease.)

## Step 3 — fuel, emissions and time

```
idling_hours   = delay_saved / 3600
fuel_litres    = idling_hours × TRAFFIC_IDLE_FUEL_LITRES_PER_HOUR      (0.9)
co2_kg         = fuel_litres  × TRAFFIC_CO2_KG_PER_LITRE_PETROL        (2.31)
person_hours   = idling_hours × TRAFFIC_AVERAGE_VEHICLE_OCCUPANCY      (1.4)
economic_value = person_hours × TRAFFIC_VALUE_OF_TIME_PER_HOUR         (8.0)
```

### Where the defaults come from, and why you should change them

| Factor | Default | Why it will be wrong for you |
|---|---|---|
| Idle fuel consumption | 0.9 L/h | Ranges from ~0.6 L/h for a small petrol car to ~4 L/h for a heavy truck. Depends entirely on your fleet mix. |
| CO₂ per litre | 2.31 kg | Correct for petrol. Diesel is ~2.68; a fleet with significant EV share is far lower. |
| Vehicle occupancy | 1.4 | Typical urban commuting. A bus corridor is an order of magnitude higher. |
| Value of time | 8.0 /hour | Varies enormously by country, and by trip purpose within a country. Use your transport authority's published figure. |

Set each with the corresponding `TRAFFIC_*` variable. The values in use are
returned in the `assumptions` object on every response, so an audit can always
see what produced a given number.

## Step 4 — annual projection

`GET /api/v1/impact/{id}/cumulative` extrapolates observed savings to a year:

```
annual = observed × (8760 / observed_hours)
```

This is naive linear extrapolation. It assumes the observation window is
representative of the whole year, which a single rush hour emphatically is not.
The response labels its own confidence:

| Observed | Confidence |
|---|---|
| < 168 hours (one week) | `low` |
| ≥ 168 hours | `moderate` |

Never `high` — a year-long claim from a shorter observation is always an
extrapolation.

## What the model does not capture

Being explicit about this matters more than the numbers themselves:

- **Bunched arrivals.** Real platoons produce higher delay than uniform arrivals.
- **Turning movements.** Left and right turns are not modelled separately.
- **Oversaturation.** Where demand exceeds capacity, queues spill back and delay
  grows superlinearly. Webster does not describe this regime.
- **Network effects.** Delay moved to the next junction is not subtracted. The
  green-wave feature addresses this operationally, but the impact model is
  per-intersection.
- **Induced demand.** A faster route attracts more traffic over time, eroding
  some of the saving.
- **Emissions beyond idling.** Acceleration after a stop produces significantly
  more emissions than idling alone, so the CO₂ figure is likely conservative.
- **Pedestrian and cyclist delay.** Not currently valued.

## Validating against reality

If you want defensible numbers rather than an estimate:

1. **Run a controlled comparison.** Alternate weekly between `adaptive_mode:
   true` and `false` via `PATCH /api/v1/intersections/{id}/plan`, and compare
   measured travel times over the same period.
2. **Measure travel time directly** with Bluetooth or ANPR re-identification
   between two points, rather than inferring it.
3. **Re-base the factors** on local fleet composition and your authority's
   published value of time.
4. **Observe for at least a month** so weekday, weekend and seasonal variation
   are all represented.

The model is a good way to decide whether a full study is worth funding. It is
not a substitute for one.

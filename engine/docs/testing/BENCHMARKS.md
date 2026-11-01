# Benchmarks and scientific validation assets

SatQuery contains software-level benchmark and certification interfaces, but
does not ship a broad scientific benchmark dataset. A registry entry or a
passing deterministic replay is not proof that a method is scientifically
valid.

## What exists

- Versioned scientific method and benchmark-suite contracts.
- Method applicability/preflight and evidence-sufficiency checks.
- A benchmark runner that evaluates supplied reference inputs against exact
  expected outputs and records a reproducibility report.
- Earth Object extraction benchmark plumbing for supplied canonical
  observations.
- A certification lifecycle with recorded transitions and benchmark links.

The runner verifies declared software behavior for the supplied cases. It
does not independently establish that reference labels are correct, that the
benchmark is representative, or that accuracy generalizes to other places,
times, sensors, or conditions.

## Current assets

Scientific knowledge records cite methods and published evaluations, but no
reference dataset/benchmark corpus is bundled for the cited methods. In
particular, the project does not package labels for DSWE, SPI, burn severity,
NLCD production, glacier mass balance, vegetation condition, or urban growth.
The implementation status is recorded per catalog method; those entries are
not executable certified methods. There is also no public leaderboard or
performance claim.

## Adding a benchmark responsibly

Before adding data, record its source and version, license/redistribution
terms, reference-label provenance, geographic/temporal/sensor scope, sampling
design, known uncertainty, expected outputs, tolerance policy, and reproducible
preprocessing. Keep test fixtures small and license-compatible. Separate
software regression fixtures from scientific validation datasets, and do not
promote a method's certification state based solely on metadata or unit tests.

When a dataset license, validation protocol, domain review, or reference
interpretation is unknown, leave the benchmark as identified but
unmaterialized and the method unvalidated.

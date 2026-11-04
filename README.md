# SatQuery — Earth Intelligence Platform

This repository contains two cooperating applications:

- **SatQuery Engine** (`engine/`) is the scientific and execution service. Its API owns
  investigations, evidence, data connectors, reasoning execution, and the Engine Agent API.
- **Earth Intelligence Platform** (`APP/`) is the user-facing workspace. It provides chat UX,
  sessions, image intake, streaming presentation, and Cesium visualization. It delegates turns
  to the Engine and does not reproduce Engine science or execution.

The Platform workspace is desktop-first and supports viewport widths of 1024 pixels or more.

The Engine can run on its own. For live Platform chat, the Engine must be reachable and have a
compatible reasoning model registered. The checked-in default configuration supplies no provider
credentials and enables no model; an opt-in OpenAI Chat Completions Agent adapter is available
when configured. Other Agent providers need their own Engine adapter.

## Quick Start

Use the repository's [authoritative integrated startup guide](INSTALL.md) for clean-clone setup,
local Engine + Platform + frontend startup, endpoint checks, troubleshooting, and the optional
Docker Compose path. It distinguishes a running, connected workspace from live Agent chat, which
requires an Engine reasoning adapter registered for the Agent API.

For a cloud-only setup, open the [Google Colab deployment notebook](SatQuery-Colab.ipynb).
It inspects the runtime, installs Python packages from the checked-in lockfiles, configures
optional hosted Agent credentials through Colab Secrets, starts the three services, and runs
live-provider smoke checks. See [Colab limitations and capabilities](COLAB.md).

## Local development

See [INSTALL.md](INSTALL.md) for Windows, Linux, macOS, and Colab prerequisites and setup.
[DEVELOPMENT.md](DEVELOPMENT.md) covers tests, contracts, builds, and source layout. The
[boot sequence](BOOTSTRAP.md) explains process startup, SQLite, event delivery, SSE, Cesium, and
the Engine boundary.

## CI

- [Earth Intelligence Platform workflow](.github/workflows/platform-ci.yml): Platform backend,
  frontend, contract, and architecture checks.
- [Platform regressions workflow](.github/workflows/platform-tests.yml): deterministic Engine
  tests, including optional geospatial and raster extras.

The local PowerShell/POSIX setup commands in `INSTALL.md` use pip and compatible version ranges;
the Colab notebook uses the checked-in Python `uv.lock` files for a frozen environment. The
frontend is locked by `APP/frontend/package-lock.json` and is installed with `npm ci`.

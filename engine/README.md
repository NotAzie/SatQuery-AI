# SatQuery

SatQuery is an Earth Intelligence platform for evidence-linked observation and
investigation. The canonical Python project is [`satquery-ai/`](satquery-ai/);
this workspace root is not a second Python package.

Start with the [project README](satquery-ai/README.md), the
[current implementation status](docs/IMPLEMENTATION_STATUS.md), or the
[documentation index](docs/README.md).

Run the local service from the canonical package directory:

```powershell
cd satquery-ai
.\.venv\Scripts\python.exe -m satquery doctor
.\.venv\Scripts\python.exe -m satquery serve
```

Model warmup is optional and applies to the legacy image-analysis models; the
Earth observation platform does not require those model weights to start.

The CLI, API, and browser workspace share the running platform runtime. By
default, platform state is in process memory; configure a local SQLite storage
path to retain it across restarts. The example connector manifest is
`configs/connectors.example.json` and must be explicitly enabled. See the
[setup guide](docs/development/SETUP.md) before using live data. The legacy
`satquery ask` image workflow remains available alongside the platform-first
investigation commands.

Python applications can use the public synchronous
[`SatQueryClient`](docs/api/API_REFERENCE.md#python-client) after installing the
package; it uses the same local platform API as the CLI and browser workspace.

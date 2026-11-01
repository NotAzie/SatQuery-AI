# Google Colab

Colab is suitable for a temporary development/demo session, not a persistent or production
deployment. The notebook runs the Engine, Platform API, and Vite frontend in the Colab VM; use the
Colab port proxy to open the UI.

## 1. Check the runtime

Select a CPU or GPU runtime. Python 3.12 is required by the Platform backend; the Engine supports
Python 3.10+ but use the notebook's Python 3.12 runtime for both. The Platform does not need a GPU.

```python
import sys
print(sys.version)
assert sys.version_info >= (3, 12), "Select a Colab runtime with Python 3.12 or newer."
```

The repository needs Node 22 for Vite. Check before installing:

```bash
!node --version
!npm --version
```

If `node` is missing or is not version 22, install Node 22 from the NodeSource 22.x apt
repository. These apt packages are only needed for Node installation; the Python application
itself has no required apt packages.

```bash
!sudo apt-get update
!sudo apt-get install -y ca-certificates curl gnupg
!curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
!sudo apt-get install -y nodejs
!node --version
!npm --version
```

## 2. Clone and install

```bash
%cd /content
!git clone https://github.com/NotAzie/SatQuery-AI.git
```

For a private repository, authenticate using Colab's supported GitHub credential flow; never paste
a token into a committed notebook or a shared output.

Install Engine test/runtime dependencies and Platform backend dependencies into separate
environments:

```bash
%cd /content/SatQuery-AI/engine/satquery-ai
!python -m venv .venv
!.venv/bin/python -m pip install --upgrade pip
!.venv/bin/python -m pip install -e ".[dev,geospatial,raster]"

%cd /content/SatQuery-AI/APP
!python -m venv .venv
!.venv/bin/python -m pip install --upgrade pip
!.venv/bin/python -m pip install -e "backend[dev]"
!npm --prefix frontend ci
```

The `raster` extra is optional for normal service startup; it is installed above to match the
Engine regression CI environment. Do not install the optional `vision` extra unless using the
legacy Engine-local image models. It pulls large Torch/Transformers packages and model weights are
downloaded separately at runtime.

## 3. Configure and start all services in one notebook cell

Set the Engine model ID only if a compatible model adapter has actually been registered in the
Engine. The repository's default configuration does not provide a model adapter or credentials.

Run this cell after installation. It launches Engine on port 9000, Platform API on port 8000, and
Vite on port 5173, then waits for their HTTP endpoints:

```python
import os
import subprocess
import time
import urllib.request
from pathlib import Path

root = Path("/content/SatQuery-AI")
engine_dir = root / "engine" / "satquery-ai"
app_dir = root / "APP"

engine_env = os.environ.copy()
engine_env.update({"SATQUERY_HOST": "0.0.0.0", "SATQUERY_PORT": "9000"})
platform_env = os.environ.copy()
platform_env.update({
    "EARTH_ENGINE__KIND": "http",
    "EARTH_ENGINE__BASE_URL": "http://127.0.0.1:9000",
    "EARTH_SERVER__HOST": "0.0.0.0",
})
frontend_env = os.environ.copy()
frontend_env["VITE_API_PROXY_TARGET"] = "http://127.0.0.1:8000"

engine_log = open("/tmp/satquery-engine.log", "w")
platform_log = open("/tmp/earth-platform-api.log", "w")
frontend_log = open("/tmp/earth-platform-frontend.log", "w")

engine = subprocess.Popen(
    [str(engine_dir / ".venv/bin/python"), "-m", "satquery", "serve",
     "--host", "0.0.0.0", "--port", "9000"],
    cwd=engine_dir, env=engine_env, stdout=engine_log, stderr=subprocess.STDOUT,
)
platform_api = subprocess.Popen(
    [str(app_dir / ".venv/bin/python"), "-m", "uvicorn",
     "earth_platform.main:create_app", "--factory", "--app-dir", "backend/src",
     "--host", "0.0.0.0", "--port", "8000"],
    cwd=app_dir, env=platform_env, stdout=platform_log, stderr=subprocess.STDOUT,
)
frontend = subprocess.Popen(
    ["npm", "run", "dev", "--", "--host", "0.0.0.0"],
    cwd=app_dir / "frontend", env=frontend_env,
    stdout=frontend_log, stderr=subprocess.STDOUT,
)

def wait_for(url, process, label, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited; inspect its /tmp log.")
        try:
            with urllib.request.urlopen(url, timeout=2):
                print(f"{label}: ready at {url}")
                return
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"{label} did not become ready; inspect its /tmp log.")

wait_for("http://127.0.0.1:9000/api/v1/health", engine, "SatQuery Engine")
wait_for("http://127.0.0.1:8000/healthz", platform_api, "Platform API")
wait_for("http://127.0.0.1:5173", frontend, "Frontend")

from google.colab import output
output.serve_kernel_port_as_window(5173)
```

The Engine starts before the Platform API; the frontend starts after both. To inspect startup
errors, read `/tmp/satquery-engine.log`, `/tmp/earth-platform-api.log`, and
`/tmp/earth-platform-frontend.log`. The Python `Popen` handles remain in the notebook kernel; stop
the processes before restarting in the same runtime.

## Environment variables

The startup cell sets the minimum internal addresses. Additional values are optional:

| Variable | Use |
|---|---|
| `EARTH_AGENT__MODEL_ID` | Exact model ID registered in Engine; required for chat turns |
| `SATQUERY_*` | Engine configuration, such as provider/model settings and optional storage |
| Provider API key(s) | Only if the Engine model adapter uses an external provider |
| `VITE_CESIUM_ION_TOKEN` | Optional Cesium default imagery; visible to browser users |

Set secrets through Colab's secret manager or the current runtime environment. Do not put provider
keys in notebook cells that will be shared.

## What works and limitations

- The Platform UI/API and Engine can run in a single Colab VM; Engine is reached over loopback.
- Uploaded files, SQLite databases, and model caches live on ephemeral VM storage unless explicitly
  copied to mounted Drive. Disconnecting or resetting the runtime loses local data.
- Cesium requires browser WebGL. Default imagery requires a Cesium ion token; external imagery may
  also be restricted by network/CORS policy.
- Local file picker upload is available through the browser. Screen/display capture and clipboard
  access depend on Colab's embedded browser permissions and may not be granted.
- There is no desktop session for OS-level capture, no stable public inbound address, no production
  authentication/TLS, and no guarantee of long-running background processes.
- GPU runtime is not required by the Platform. The optional Engine `vision` models are not installed
  here; installing them requires a compatible PyTorch build and separate model downloads.
- External Earth connectors, provider APIs, and registered Engine reasoning models remain subject
  to their own credentials, quotas, network access, and configuration.
- Colab is not Docker support: this setup runs processes directly in the notebook VM.

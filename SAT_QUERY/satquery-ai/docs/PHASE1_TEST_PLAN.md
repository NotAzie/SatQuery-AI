# Phase 1 Test Plan

## Purpose

This document defines the verification package for SatQuery AI Phase 1. Phase 1 is an optimization and reliability phase. It verifies that the current architecture is faster to operate after warmup, truthful about readiness, strict about request validation, deterministic in tests, and clear about its canonical source path.

The acceptance suite is [tests/test_phase1_acceptance.py](../tests/test_phase1_acceptance.py).
Saved run artifacts are kept separately under [test_runs/phase1](../test_runs/phase1).

## Scope

### In scope

- Practical model warmup for CLIP, BLIP captioning, and BLIP VQA.
- Health and capability truthfulness before and after warmup.
- Minimum and maximum image-count validation.
- Canonical package import path.
- Quality as the default profile.
- Explicit opt-in fast profile.
- Post-warmup caption, scene classification, and grounding smoke queries.
- Persistent-engine model reuse.
- Practical post-warmup latency checks.
- Actionable failure messages and test diagnostics.

### Out of scope

- New vision capabilities.
- UI redesign or browser visual testing.
- GeoChat or RS-VLM expansion.
- Satellite fetcher behavior beyond locating an existing sample image.
- Accuracy benchmarking against a labelled remote-sensing dataset.
- Detector-level object counting, registration for change detection, or model retraining.
- Replacing the quality default with a weaker model.

## Test design

The file contains two layers:

1. **Deterministic contract checks** run in the normal suite. These use the existing pixel-derived backend doubles and do not download models. They verify package location, profile semantics, image cardinality, and no-backend readiness truthfulness.
2. **Real-model acceptance checks** are explicitly opt-in. They use the actual configured Hugging Face models and an existing image under `data/fetched_images/`. They verify warmup, loaded-model reuse, real captioning, scene classification, grounding, region output, and latency.

This split keeps normal CI deterministic while still providing a practical gate for a demo machine.

## Test cases

| Test | What it proves | Default run |
|---|---|---:|
| `test_canonical_package_path_is_explicit_and_importable` | `satquery` resolves to `satquery-ai/satquery`; duplicate outer modules are quarantined. | Runs |
| `test_quality_profile_is_the_default_and_fast_is_explicit` | Quality remains the default; fast mode requires `SATQUERY_PROFILE=fast`. | Runs |
| `test_tool_image_cardinality_rejects_missing_and_extra_images` | Single-image tools reject extras and change detection rejects too few/too many images. | Runs |
| `test_health_and_capabilities_are_honest_before_models_are_loaded` | Missing dependencies produce degraded health and unavailable model-backed capabilities. | Runs |
| `test_warmup_health_capabilities_and_model_reuse` | Warmup loads CLIP/captioner/VQA, readiness becomes true, capabilities become available, and repeated access returns the same loaded objects. | Opt-in |
| `test_post_warmup_caption_scene_and_grounding_smoke` | Real `describe`, scene classification, and `where are the buildings` queries complete without crashes; grounding returns regions. | Opt-in |
| `test_acceptance_configuration_is_self_describing` | Canonical package and CLI files exist, making failures actionable. | Runs |

## Environment assumptions

- Windows PowerShell is the primary supported operator shell for this workspace.
- The canonical package directory is `C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai`.
- The virtual environment is `C:\Users\mazin\HACKATHON\SAT_QUERY\.venv`.
- Run commands with the project interpreter, not a global `pytest` executable.
- Torch, Transformers, Pillow, NumPy, FastAPI, and the development dependencies must be installed for the full project suite.
- Real acceptance requires the practical model checkpoints to be available locally or downloadable from Hugging Face.
- Real acceptance requires at least one `.jpg` or `.png` under `satquery-ai/data/fetched_images/`.
- Real acceptance uses the configured profile and model settings. It does not silently switch to a smaller model.

## Exact commands

### 0. Run and save a Phase 1 report in one command

From `satquery-ai`:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe scripts\run_phase1.py
```

This runs deterministic Phase 1 acceptance checks and creates a new UTC
timestamped folder under `test_runs/phase1/`. The folder contains:

- `REPORT.md` — readable command results, counts, profile, environment notes, and verdict
- `summary.json` — machine-readable run metadata
- `deterministic.txt` — complete pytest output

To include the real-model acceptance command in the same saved run:

```powershell
..\.venv\Scripts\python.exe scripts\run_phase1.py --real --timeout 45
```

To explicitly record the latency-first profile for a demo run:

```powershell
..\.venv\Scripts\python.exe scripts\run_phase1.py --real --profile fast --timeout 45
```

The runner returns exit code `0` only when every selected command passes. It
returns `1` when deterministic or enabled real acceptance fails. It never
changes source modules, quality defaults, or product behavior.

### 1. Install development dependencies

From the canonical package directory:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 2. Run the complete deterministic suite

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m pytest -q
```

Expected result after the current Phase 1 changes: all project tests pass. The suite includes the acceptance contract checks and should not download models.

### 3. Run only deterministic Phase 1 checks

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -q
```

Expected result: deterministic tests pass and the two real-model tests are skipped unless explicitly enabled.

The equivalent saved run is the `scripts\\run_phase1.py` command above. Prefer
that command when a report needs to be retained for review.

### 4. Run real-model acceptance

Use the quality profile by default:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
$env:SATQUERY_RUN_REAL_ACCEPTANCE = "1"
..\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -m real_acceptance -q -s
Remove-Item Env:SATQUERY_RUN_REAL_ACCEPTANCE
```

The first run may download and load the configured CLIP, captioner, and VQA checkpoints. Later runs should reuse the local Hugging Face cache, but every test process still constructs its own in-memory registry.

### 5. Run warmup manually

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m satquery warmup
```

Expected shape of the final output:

```json
{
  "loaded": ["clip", "captioner", "vqa"],
  "errors": {},
  "ready": true,
  "device": "cpu",
  "elapsed_s": 0.0
}
```

The elapsed value is machine-dependent. `ready: true`, all three model names in `loaded`, and an empty `errors` object are the important fields.

### 6. Run a real post-warmup smoke process

For a meaningful latency measurement, warmup and queries must happen in the same Python process so the registry can reuse loaded model objects. The acceptance test does this automatically. A manual CLI invocation starts a new process and therefore includes model startup again.

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
$env:SATQUERY_RUN_REAL_ACCEPTANCE = "1"
$env:SATQUERY_ACCEPTANCE_QUERY_TIMEOUT = "30"
..\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -m real_acceptance -q -s
Remove-Item Env:SATQUERY_RUN_REAL_ACCEPTANCE
Remove-Item Env:SATQUERY_ACCEPTANCE_QUERY_TIMEOUT
```

## Expected results

### Deterministic checks

- Full suite passes with zero failures.
- Phase 1 contract tests pass without network access or model downloads.
- No test should depend on whether Hugging Face weights happen to be cached.
- Extra images produce `QueryError` messages containing the configured maximum.
- Quality profile resolves to CLIP-Large, four grounding scales, and a 320-window maximum.
- Fast profile resolves only when explicitly requested and uses its documented smaller-window settings.

### Real checks

- Before warmup, a fresh engine reports `ready: false`.
- Warmup loads `clip`, `captioner`, and `vqa` with no errors.
- After warmup, health reports `ready: true` and CLIP-shaped capabilities are available.
- Repeated registry access returns the same model objects rather than reloading them.
- Captioning returns a non-empty answer.
- Scene classification returns a non-empty answer and completes without a tool failure.
- Grounding returns a non-empty answer and at least one region for the selected sample image. A real image with no visible buildings may legitimately require changing the sample or query; the test is intended for the repository's existing fetched samples.
- The practical latency smoke uses the explicit `SATQUERY_PROFILE=fast` configuration. This is intentional: the quality default retains the broad 320-window sweep, which is not a practical CPU latency gate. The quality-default contract is still asserted separately, and the fast profile must be explicitly selected rather than silently replacing it.
- Each fast-profile query stays under `SATQUERY_ACCEPTANCE_QUERY_TIMEOUT` after warmup. The default is 30 seconds and should be adjusted to the target demo machine, not weakened to hide a regression.

## Failure interpretation

### Reading a saved result

Open the newest directory under `test_runs/phase1/` and inspect `REPORT.md`
first. The report lists the exact command, exit code, duration, pass/fail/
skipped counts, selected profile, whether real acceptance was enabled, and raw
output file locations. Use `summary.json` for automation or comparison between
runs. The raw `.txt` files contain model-loading messages and pytest tracebacks
that may not fit in the summary.

The final verdict is `PASS` only when every command selected by the runner exits
zero. A deterministic-only `PASS` does not prove real model behavior; it proves
the Phase 1 contracts are stable. A `--real` run with `PASS` proves the actual
configured models completed the opt-in checks on that machine.

### `ModuleNotFoundError`, import path, or canonical path failure

The command is running from the wrong directory or with the wrong interpreter. Confirm:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -c "import satquery; print(satquery.__file__)"
```

The printed path must be under `satquery-ai\\satquery`.

### Warmup has errors

The configured model did not load. Read the model-specific error and remediation. Common causes are missing Torch/Transformers, incomplete Hugging Face cache, network access, insufficient RAM/VRAM, or a bad model identifier. Do not interpret `doctor` dependency presence as successful model readiness.

### Health is ready before warmup

This is a readiness regression. A fresh engine should not claim warmed readiness merely because Python packages import.

### Capabilities are available before warmup

This is a capability honesty regression. Model-backed capabilities should become available only when the required backend is actually ready according to the current readiness contract.

### Image cardinality failure is absent

A tool is silently ignoring input images. Check `Tool.validate()` and confirm both `min_images` and `max_images` are enforced before model execution.

### Real smoke test is skipped

The test was not enabled, or no fetched sample image was found. Skips are intentional and are not evidence that real inference passed. Set `SATQUERY_RUN_REAL_ACCEPTANCE=1` and ensure `data/fetched_images/` contains a valid image.

### Real smoke test exceeds the timeout

This is a practical performance failure on the target machine. Record the profile, model, device, warmup time, query latency, and trace tool latency. Do not change the quality default or merely raise the timeout without recording the result. If the failing run used quality, repeat the documented fast-profile smoke before deciding whether Phase 1 is blocked.

### Grounding returns no regions

First confirm the query routed to grounding and inspect the selected image. Semantic grounding is not instance detection, and a sample may not contain a visually separable building region. A crash is a hard failure; an empty result is an image/model quality finding that needs investigation.

## Known limitations

- Real acceptance is machine-dependent: CPU/GPU, RAM, disk cache, Transformers version, and network all affect latency.
- The quality profile intentionally retains the stronger default model and broader grounding sweep. The fast profile is an explicit demo tradeoff, not the quality baseline.
- The acceptance suite verifies successful execution and practical latency, not remote-sensing accuracy metrics.
- Grounding returns semantic regions rather than verified object instances.
- The sample image set is not a labelled benchmark.
- Caption and scene queries may perform nested analysis and therefore take longer than a single backend forward pass.
- The current tests do not certify arbitrary GeoChat/RS-VLM checkpoints.

## Phase 2 sign-off checklist

Do not start Phase 2 until the owner can check each applicable item:

- [ ] `..\.venv\Scripts\python.exe -m pytest -q` passes with zero failures.
- [ ] Canonical import path points to `satquery-ai\\satquery`.
- [ ] Duplicate outer modules are quarantined and no operator documentation points to them.
- [ ] Warmup loads the required models on the actual demo machine with `errors: {}` and `ready: true`.
- [ ] Health is false/degraded before warmup and true/ready after warmup.
- [ ] Capabilities change truthfully with backend readiness.
- [ ] Caption smoke query completes without a crash.
- [ ] Scene classification smoke query completes without a crash.
- [ ] Grounding smoke query returns regions on the selected curated image.
- [ ] Model reuse is demonstrated in one persistent engine process.
- [ ] Measured post-warmup latency is recorded for the actual demo hardware.
- [ ] Any skipped real acceptance test has an explicit owner decision and reason.
- [ ] No Phase 2 feature work has been mixed into the Phase 1 verification result.

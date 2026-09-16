# Phase 1 Test Run

- Timestamp (UTC): `20260916T082304Z`
- Profile: `fast`
- Real acceptance enabled: `True`
- Python: `C:\Users\mazin\HACKATHON\SAT_QUERY\.venv\Scripts\python.exe`
- Final verdict: **FAIL**

## Commands

### 1. `C:\Users\mazin\HACKATHON\SAT_QUERY\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -s -rA`

- Exit code: `1`
- Duration: `130.083s`
- Passed: `6`
- Failed: `1`
- Skipped: `0`
- Raw output: `satquery-ai\test_runs\phase1\20260916T082304Z\deterministic.txt`

### 2. `C:\Users\mazin\HACKATHON\SAT_QUERY\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -s -rA -m real_acceptance`

- Exit code: `0`
- Duration: `90.857s`
- Passed: `2`
- Failed: `0`
- Skipped: `0`
- Raw output: `satquery-ai\test_runs\phase1\20260916T082304Z\real_acceptance.txt`

## Environment notes

- Working directory: C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
- Python version: 3.12.10
- Configured SATQUERY_PROFILE: fast
- Real acceptance uses existing fetched images under data/fetched_images when available.
- The runner does not alter source modules or change model defaults.

## Interpretation

- `PASS` means every selected command exited with code 0.
- A skipped real acceptance command means real-model verification was not enabled or prerequisites were unavailable; it is not evidence that real inference passed.
- Inspect the per-command `.txt` files for model loading errors, trace failures, and latency details.

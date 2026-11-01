# Phase 1 Test Run

- Timestamp (UTC): `20260916T082252Z`
- Profile: `quality (default)`
- Real acceptance enabled: `False`
- Python: `C:\Users\mazin\HACKATHON\SAT_QUERY\.venv\Scripts\python.exe`
- Final verdict: **PASS**

## Commands

### 1. `C:\Users\mazin\HACKATHON\SAT_QUERY\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -s -rA`

- Exit code: `0`
- Duration: `3.366s`
- Passed: `5`
- Failed: `0`
- Skipped: `2`
- Raw output: `satquery-ai\test_runs\phase1\20260916T082252Z\deterministic.txt`

## Environment notes

- Working directory: C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
- Python version: 3.12.10
- Configured SATQUERY_PROFILE: quality (default)
- Real acceptance uses existing fetched images under data/fetched_images when available.
- The runner does not alter source modules or change model defaults.

## Interpretation

- `PASS` means every selected command exited with code 0.
- A skipped real acceptance command means real-model verification was not enabled or prerequisites were unavailable; it is not evidence that real inference passed.
- Inspect the per-command `.txt` files for model loading errors, trace failures, and latency details.

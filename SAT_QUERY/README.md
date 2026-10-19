# SatQuery AI

The canonical project is [`satquery-ai`](satquery-ai/). This outer README is only a pointer so the workspace root does not look like a second Python project.

Read the setup, usage, Phase 1/Phase 2 notes, limitations, and current project notes in [satquery-ai/README.md](satquery-ai/README.md).

Project documentation is organized under [docs/](docs/), with foundation, architecture, API, dataset, development, research, and testing sections.

Run commands from the canonical package directory:

```powershell
cd satquery-ai
..\.venv\Scripts\python.exe -m satquery doctor
..\.venv\Scripts\python.exe -m satquery warmup
..\.venv\Scripts\python.exe -m satquery serve
```

The primary CLI commands talk to that running platform API so mission and
investigation history remains shared with the browser and API. Set
`SATQUERY_API_URL` when the server is not at `http://127.0.0.1:8000`. Start
with `satquery capabilities`, then use `satquery investigate "..."
--query-file earth-query.json` for a scoped observation task. The legacy
`satquery ask` image workflow remains available as one perception capability.

# Configuration

Layers, later overriding earlier (maps deep-merge; lists and scalars replace):

1. `config/base.yaml`
2. `config/providers/*.yaml`: every known LLM endpoint, `enabled: false`
3. `config/environments/<EARTH_ENV>.yaml`: `development` (default), `production`, `test`
4. `config/profiles/<name>.yaml` for each name in `EARTH_PROFILES` (comma-separated)
5. `.env`, then real environment variables: `EARTH_<SECTION>__<KEY>`, e.g. `EARTH_LLM__DEFAULT_MODEL`

| Concern | Where |
|---|---|
| Development vs production | `environments/` |
| API providers | `providers/*.yaml` + `profiles/hosted-apis.yaml` |
| Local models | `providers/ollama.yaml` + `profiles/local-models.yaml` |
| SatQuery Engine | `engine.kind: http`, `engine.base_url`; `engine.api_key_env` is not usable until the Engine/deployment authentication scheme is defined |
| Engine Agent model | `agent.model_id`: an id already registered with SatQuery Engine |
| Event streaming | `streaming.heartbeat_interval_s`, `streaming.replay_window_events` (bounded replay page size; history is not truncated) |
| Vision uploads | `vision.max_image_bytes`, `vision.max_images_per_message`, `vision.max_message_bytes`, `vision.max_concurrent_ingests`, `vision.store_path` |
| Secrets | environment only; sections name the variable (`api_key_env: OPENAI_API_KEY`) |

Examples:

```bash
EARTH_PROFILES=local-models EARTH_LLM__DEFAULT_MODEL=<pulled-model> make backend
EARTH_ENV=production EARTH_PROFILES=hosted-apis OPENAI_API_KEY=... make backend
EARTH_ENGINE__KIND=http EARTH_ENGINE__BASE_URL=https://engine.example EARTH_AGENT__MODEL_ID=<engine-model-id> make backend
```

Default model names are intentionally unset in the repo: model catalogues change faster than this
code. Choose one explicitly per deployment.
The Platform's Agent runtime does not use `llm.default_model` or call provider SDKs directly;
`agent.model_id` must name a model registered inside SatQuery Engine.
Unknown keys are rejected at startup (`extra="forbid"`), so typos fail fast.

# Module overview

Each folder has a `README.md` with purpose, what belongs, what must never belong, dependencies and
public interface. This page is the map.

## Backend: `backend/src/earth_platform`

| Module | Responsibility | State |
|---|---|---|
| `shared` | ids, errors, `Registry`, geo + message value types | implemented |
| `settings` | typed, layered configuration | implemented |
| `engine` | the only seam to SatQuery Engine | Agent API and tool descriptors, typed dataset/image-capability and Earth modality discovery, HTTP adapter, explicit unconfigured client |
| `llm` | provider-neutral model access | interfaces |
| `vision` | image ingest, store, multimodal preparation | interfaces |
| `earth` | `EarthController`, camera, command dispatcher, layer/overlay/timeline/investigation interfaces | Earth workspace presentation plus validated Engine Earth Object overlays |
| `sessions` | sessions, conversations, tasks, event log | SQLite implementation + repository Protocols |
| `agent` | Platform session/event bridge and event contracts; Engine owns the model/tool loop | Engine Agent bridge implemented; generic Platform agent/tool interfaces remain extension contracts |
| `plugins` | plugin contracts | no concrete backend loader; runtime loading is not active |
| `streaming` | event bus, client frames, encoders | SQLite-backed single-process bus + bounded subscriber queues, paged replay, and SSE encoder |
| `api` | HTTP routing, DI, error mapping | health, session lifecycle, chat, intelligence and Engine discovery, monitoring, and SSE routes implemented |
| root | `main`, `lifecycle`, `container`, `logging` | implemented |

## Frontend: `frontend/src`

| Folder | Responsibility | State |
|---|---|---|
| `app` | bootstrap, providers, router, `AppShell` | implemented |
| `earth` | all Cesium code behind `EarthController` | globe, camera, capture, workspace tools, overlays, timeline, selection/drawings, and split view |
| `features` | chat, Earth tools/data discovery, vision, monitoring, sessions | session sidebar, streamed Engine Agent chat, Engine data catalogue, image attachments, and monitoring |
| `components` | feature-agnostic UI primitives | structure |
| `hooks` | cross-cutting hooks | `useEarthController` |
| `services` | `api` client, `stream` contract | client + contract |
| `state` | Zustand stores | earth, session |
| `plugins` | frontend registries and `PanelHost` | no manifest feed or dynamic module loader |
| `shared` | generated types, registry, constants | implemented |
| `styles` | Tailwind tokens | implemented |

## Top level

`config/` layered YAML · `contracts/` generated schema · `plugins/` plugin packages ·
`scripts/` tooling · `tests/e2e/` cross-stack tests · `docs/`.

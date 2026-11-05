# Earth View

A real-time intelligence console for planet Earth: a photorealistic 3D globe with
live aircraft, military tracks, vessels, satellites, rocket launches,
earthquakes, wildfires, CCTV, radio, traffic, bikeshare, submarine cables and
more — plus hands-free voice control. Runs entirely in the browser.

## SatQuery integration

The supplied package metadata identifies the authored project as God's Eye View
by Bilawal Sidhu and declares MIT; the supplied source directory did not include
a standalone license text. This integration preserves that metadata and does not
relicense the vendored source.

In SatQuery, this authored frontend is the primary Earth experience and is composed
into `APP/frontend`'s same-page Vite build. SatQuery React attaches its typed Earth
controllers to the viewer exposed by this runtime; it does not create a second
Cesium viewer or run this directory as another frontend service. The standalone
commands below remain useful for upstream development, but are not the integrated
SatQuery startup workflow. SatQuery's root `INSTALL.md` documents the coordinated
Engine, Platform API, and frontend startup.

## Requirements

- **Node.js 24.14+** (24.x or 26.x; see `engines` in `package.json`) and npm.
- A WebGL-capable browser with a microphone if you want voice control.

Node 22 and older are outside the supported range. If you use a version manager,
select a supported release before installing.

## Quick start

```sh
npm install
npm run dev
```

The dev server listens on `http://localhost:4173` by default. Override it with
`HOST` and `PORT` environment variables.

The app is usable with **no API keys at all**: it starts on keyless Esri World
Imagery, with OSM available in the map tray and as the automatic provider
fallback.

For the integrated SatQuery app, local keys belong in the repository-root `.env`
(beside `INSTALL.md`), not this directory. The notch's optional Provider Settings
panel saves to that same file. It does not open on normal startup. To add keys,
either:

- open the in-app **Provider Settings** panel (the POWER UP chip, bottom-right),
  paste keys, and let it write the repository-root `.env`; or
- copy the repository-root `.env.example` to `.env` and fill in the values you have.

When running this folder's standalone upstream server, use
`APP/earth-view/.env.example` and `APP/earth-view/.env` instead. That separate
path does not apply to the integrated SatQuery startup in [INSTALL.md](../../INSTALL.md).

`GOOGLE_MAPS_API_KEY` and `CESIUM_ION_TOKEN` are intentionally exposed to the
browser (they are used client-side), so restrict them by HTTP referrer in the
provider console. Every other key stays server-side and is never bundled.

## Drawing on the globe

Use **DISPLAY ▸ Draw** to add an area, line, or pin to the world. Select a shape,
then click its vertices; double-click or press Enter to finish, and press Esc to
cancel. A label and color are optional. Drawn marks use the same annotation
engine as other world annotations, persist with the board, and can be removed
with Clear. Areas and routes are draped onto the surface; the final marks do not
preserve per-vertex altitude.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the Vite dev server with local provider middleware |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run doctor` | Inspect dependencies, dotenv and configured credentials |
| `npm test` | Run the unit test suite (`scripts/run-unit-tests.mjs`) |
| `npm run format` | Format the project with Prettier |
| `npm run format:check` | Check formatting without writing |
| `npm run build:panel` | Build the MCP Apps panel into `dist/panel` |
| `npm run check:boundaries` | Enforce import directions and package boundaries |
| `npm run mcp` | Start the MCP tool server over stdio |
| `npm run dev:secure` | Start the dev server through the secure launch script |
| `npm run opensky:import` | Fetch OpenSky credentials through the import client |
| `npm run qa:transit` | Run the transit QA harness |
| `npm run qa:map-source-tray` | Run the map-source tray QA harness |
| `npm run test:track` | Run the track-regression harness |
| `npm run layer-token:check` | Verify layer state tokens |

## Configuration

The root `.env.example` documents the shared local settings and common provider
keys. The full standalone God's Eye variable reference remains in this
directory's `.env.example`. The most common provider variables:

| Variable | Scope | Enables |
| --- | --- | --- |
| `GOOGLE_MAPS_API_KEY` | client | Google Photorealistic 3D Tiles and GEV place search |
| `GOOGLE_MAPS_SERVER_API_KEY` | server | Server-side Places and Street View calls (falls back to the client key) |
| `CESIUM_ION_TOKEN` | client | Cesium ion imagery, world terrain and ion-hosted Google 3D |
| `OPENAI_API_KEY` | server | OpenAI Realtime voice control and HUD summaries |
| `AISSTREAM_API_KEY` | server | Live AIS vessel positions |
| `FIRMS_MAP_KEY` | server | NASA FIRMS wildfire detections |
| `TOMTOM_API_KEY` | server | TomTom traffic tiles |
| `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` | server | Authenticated OpenSky flight data |
| `LL2_API_TOKEN` | server | Launch Library 2 launch data |

Additional optional tuning exists for rate limits, Overpass upstreams, AIS row
caps and OpenAI Realtime models — see the comments in `.env.example`.

## Source layout

```
index.html            Application shell; feature markup is injected at build time
style.css             Stylesheet entry that imports the UI style layers
src/
  main.js             Browser entry point
  app/                Application bootstrap, scene/data/controls wiring
  layers/             Data layers (flights, vessels, satellites, fires, CCTV, …)
  sources/            Provider clients and source adapters
  data/               Bundled datasets, cards, models and context stores
  ui/                 Panels, controls, templates and CSS (src/ui/styles)
  voice/              Realtime voice session, commands and actions
  maps/               Map imagery, terrain and 3D-tiles providers
  scenes/             Scene director and playback
  overlays/           Shared world-overlay renderer
  view/               Camera and viewer helpers
server/
  providers/          Server-side provider proxies used by Vite middleware
  standalone/         Standalone Vite config and key setup
  mcp/                MCP server
build/                Vite config builder, HTML assembly, panel/embed plugins
scripts/              Setup doctor, tests, formatting and QA harnesses
public/               Static assets served as-is
config/               CCTV source registry
tools/                Geospatial CLI utilities (imagery, Street View, panoramas)
pinokio/              Pinokio launcher scripts
```

`build/` is **source code**, not generated output; production output goes to
`dist/`.

## Tests and checks

```sh
npm test
npm run check:boundaries
npm run format:check
```

The unit tests use Node's built-in test runner. Browser-level QA harnesses under
`scripts/qa-*.mjs` use Puppeteer and require the dev server.

## License

MIT (declared in `package.json`).

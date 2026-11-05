import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const app = path.join(root, "APP");
const engine = path.join(root, "engine", "satquery-ai");
const configuredKeys = new Set(Object.keys(process.env));
const envFile = path.join(root, ".env");
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const match = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/.exec(line);
    if (match) configuredKeys.add(match[1]);
  }
}
const engineEnv = { ...process.env };
const hasPlatformStorageConfig = [...configuredKeys].some(
  (key) =>
    key === "SATQUERY_PLATFORM_CONFIG" || key.startsWith("SATQUERY_PLATFORM__STORAGE__"),
);
if (!hasPlatformStorageConfig) {
  engineEnv.SATQUERY_PLATFORM__STORAGE__AGENT_SESSIONS_PATH = path.join(
    engine,
    ".satquery",
    "agent-sessions.sqlite",
  );
}
const platformPython =
  process.env.SATQUERY_PLATFORM_PYTHON ||
  path.join(
    app,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
const viteCli = path.join(
  app,
  "frontend",
  "node_modules",
  "vite",
  "bin",
  "vite.js",
);

for (const [label, target] of [
  ["Platform Python environment", platformPython],
  ["Frontend dependencies", viteCli],
]) {
  if (!existsSync(target)) {
    console.error(
      `${label} not found. Follow INSTALL.md, or set SATQUERY_PLATFORM_PYTHON to the Platform interpreter.`,
    );
    process.exit(1);
  }
}

const python =
  process.env.SATQUERY_ENGINE_PYTHON ||
  (process.platform === "win32" ? "python" : "python3");
const services = [
  {
    name: "SatQuery Engine",
    command: python,
    args: ["-m", "satquery", "serve", "--host", "127.0.0.1", "--port", "9000"],
    cwd: engine,
    env: engineEnv,
  },
  {
    name: "Atlas Platform",
    command: platformPython,
    args: [
      "-m",
      "uvicorn",
      "earth_platform.main:create_app",
      "--factory",
      "--app-dir",
      path.join("backend", "src"),
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    cwd: app,
  },
  {
    name: "God's Eye / Atlas frontend",
    command: process.execPath,
    args: [viteCli, "--host", "127.0.0.1"],
    cwd: path.join(app, "frontend"),
  },
];

const children = [];
let stopping = false;

function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode === null && !child.killed) child.kill("SIGTERM");
  }
  const deadline = setTimeout(() => process.exit(exitCode), 5000);
  deadline.unref();
  Promise.all(
    children.map(
      (child) =>
        new Promise((resolve) => {
          if (child.exitCode !== null) resolve();
          else child.once("close", resolve);
        }),
    ),
  ).then(() => {
    clearTimeout(deadline);
    process.exit(exitCode);
  });
}

process.once("SIGINT", () => stop(0));
process.once("SIGTERM", () => stop(0));

function start(service) {
  const child = spawn(service.command, service.args, {
    cwd: service.cwd,
    env: service.env ?? process.env,
    stdio: "inherit",
    windowsHide: true,
  });
  children.push(child);
  let startupError = null;
  child.once("error", (error) => {
    console.error(`${service.name} failed to start: ${error.message}`);
    startupError = error;
    stop(1);
  });
  child.once("exit", (code, signal) => {
    if (stopping) return;
    console.error(
      `${service.name} exited unexpectedly (${signal || `code ${code}`}); stopping the other services.`,
    );
    stop(code && code > 0 ? code : 1);
  });
  console.log(`Starting ${service.name}...`);
  return { name: service.name, child, getStartupError: () => startupError };
}

async function waitUntilReady(service, url) {
  const deadline = Date.now() + 60_000;
  while (!stopping && Date.now() < deadline) {
    if (service.getStartupError()) throw service.getStartupError();
    if (service.child.exitCode !== null) {
      throw new Error(`${service.name} exited before becoming ready.`);
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (response.ok) {
        console.log(`${service.name} is ready.`);
        return;
      }
    } catch {
      // Connection refusal is expected while a service is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!stopping) {
    throw new Error(`${service.name} did not become ready in 60 seconds.`);
  }
}

async function main() {
  const engineService = start(services[0]);
  await waitUntilReady(engineService, "http://127.0.0.1:9000/api/v1/health");
  if (stopping) return;

  const platformService = start(services[1]);
  await waitUntilReady(platformService, "http://127.0.0.1:8000/healthz");
  if (stopping) return;
  start(services[2]);
  console.log("Atlas is available at http://127.0.0.1:5173/ (Ctrl+C stops all services).");
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : "Development startup failed.");
  stop(1);
});

// Capture README screenshots from the REAL running application (no mock-ups).
//
// Prerequisites: backend on :8000 and the frontend (dev or preview) on BASE_URL.
//   node scripts/capture-screenshots.mjs [outDir]
// Env: BASE_URL (default http://127.0.0.1:5173), PW_CHANNEL (e.g. msedge/chrome; default bundled chromium),
//      ONLY=overview,plant (optional subset)
//
// The script drives the simulation through the public API: it resets to a fresh run, runs normal
// operation, starts Scenario C (synthetic sensor manipulation) at 5x, waits for the detection, and
// captures each page.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const OUT = resolve(process.argv[2] ?? "../docs/screenshots");
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;
mkdirSync(OUT, { recursive: true });

const api = async (method, path, body) => {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-Analyst": "screenshot-bot" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${await r.text()}`);
  return r.json();
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const v = await fn();
    if (v) return v;
    await sleep(500);
  }
  throw new Error(`timeout waiting for ${label}`);
}

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1.5, colorScheme: "dark" });
const shot = async (name, path, { wait = 1500, full = false, before } = {}) => {
  if (ONLY && !ONLY.has(name)) return;
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  if (before) await before();
  await sleep(wait);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  console.log("captured", name);
};

// 1. fresh run, normal operation at 5x
const { run_id: runId } = await api("POST", "/api/simulation/reset", { seed: 1337 });
await api("POST", "/api/simulation/start");
await api("POST", "/api/simulation/speed", { speed: 5 });
await waitFor(async () => (await api("GET", "/api/simulation/state")).sim_time_s > 150, 90_000, "warm-up");
await shot("overview-normal", "/", { wait: 2500 });

// 2. synthetic sensor manipulation (Scenario C)
await api("POST", "/api/scenarios/sensor-manipulation/start", { params: {} });
const inc = await waitFor(async () => {
  const r = await api("GET", `/api/incidents?run_id=${runId}&limit=5`);
  return r.items.find((i) => i.classification === "suspected_manipulation");
}, 120_000, "incident");
await waitFor(async () => (await api("GET", "/api/simulation/state")).scenario?.elapsed_s > 150, 120_000, "scenario progress");
await api("POST", "/api/simulation/speed", { speed: 1 });

await shot("overview-incident", "/", { wait: 2500 });
await shot("digital-twin", "/plant", { wait: 2500 });
await shot("telemetry", "/telemetry", { wait: 2500, full: true });
await shot("scenario-lab", "/scenarios", { wait: 2000 });
await shot("detection", "/detection", { wait: 2500, full: true });
await shot("incident", `/incidents/${inc.id}`, { wait: 2500, full: true });
await shot("report", `/reports?incident=${inc.id}`, { wait: 2500 });
const state = await api("GET", "/api/simulation/state");
await shot("replay", `/replay?run=${state.run_id}`, {
  wait: 2000,
  full: true,
  before: async () => {
    await page.getByRole("button", { name: `${inc.id} −30 s` }).first().click();
    await page.getByRole("button", { name: "Forward 10 seconds" }).click();
    await page.getByRole("button", { name: "Forward 10 seconds" }).click();
    await page.getByRole("button", { name: "Forward 10 seconds" }).click();
    await page.getByRole("button", { name: "Forward 10 seconds" }).click();
    await page.getByRole("button", { name: "Forward 10 seconds" }).click();
    await page.getByRole("button", { name: "Forward 10 seconds" }).click();
  },
});
await shot("architecture", "/about", { wait: 800 });

await api("POST", "/api/scenarios/stop");
await browser.close();
console.log(`screenshots written to ${OUT}`);

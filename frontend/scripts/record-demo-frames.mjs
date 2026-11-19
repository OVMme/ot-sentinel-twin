// Record frames of the REAL running twin during Scenario C (synthetic sensor manipulation) for the README GIF.
//   node scripts/record-demo-frames.mjs <framesDir>     then: python scripts/make_demo_gif.py <framesDir> <out.gif>
// Env: BASE_URL (default http://127.0.0.1:5173), PW_CHANNEL (optional installed browser channel).
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const OUT = process.argv[2] ?? "frames";
mkdirSync(OUT, { recursive: true });
const post = (p, b) =>
  fetch(BASE + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b ?? {}) });
const get = async (p) => (await fetch(BASE + p)).json();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await post("/api/simulation/reset", { seed: 1337 });
await post("/api/simulation/start");
await post("/api/simulation/speed", { speed: 10 });
while ((await get("/api/simulation/state")).sim_time_s < 120) await sleep(500);
await post("/api/simulation/speed", { speed: 5 });

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
const page = await browser.newPage({ viewport: { width: 1500, height: 900 }, deviceScaleFactor: 1 });
await page.goto(`${BASE}/plant`, { waitUntil: "networkidle" });
await sleep(1500);
const diagram = page.getByTestId("plant-diagram");

let i = 0;
const frame = async () => {
  await diagram.screenshot({ path: `${OUT}/frame-${String(i++).padStart(3, "0")}.png` });
};
for (let k = 0; k < 6; k++) { await frame(); await sleep(400); } // normal operation
await post("/api/scenarios/sensor-manipulation/start", { params: {} });
for (let k = 0; k < 64; k++) { await frame(); await sleep(400); } // onset, detection, controller response
await post("/api/scenarios/stop");
await post("/api/simulation/speed", { speed: 1 });
await browser.close();
console.log(`${i} frames in ${OUT}`);

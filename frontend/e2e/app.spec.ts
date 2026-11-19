import { expect, test, type APIRequestContext } from "@playwright/test";

// Critical user journeys against the real simulator. All data is synthetic.

async function ensureRunning(request: APIRequestContext) {
  await request.post("/api/scenarios/stop");
  const state = await (await request.get("/api/simulation/state")).json();
  if (state.status !== "running") await request.post("/api/simulation/start");
  await request.post("/api/simulation/speed", { data: { speed: 10 } });
}

test.beforeEach(async ({ request }) => {
  await ensureRunning(request);
});

test("overview streams live telemetry", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Plant overview" })).toBeVisible();
  const clock = page.getByTitle("Simulated time since run start");
  const t1 = await clock.textContent();
  await expect.poll(async () => clock.textContent(), { timeout: 10_000 }).not.toBe(t1);
  await expect(page.getByTestId("plant-diagram")).toBeVisible();
  await expect(page.getByText("SIMULATED DATA").first()).toBeVisible();
});

test("scenario lab: stuck valve is detected, investigated and reported", async ({ page, request }) => {
  await page.goto("/scenarios");
  await expect(page.getByRole("heading", { name: "Simulation & Scenario Lab" })).toBeVisible();
  // Let the detector warm up (60 s simulated) before injecting the fault.
  await expect
    .poll(async () => (await (await request.get("/api/simulation/state")).json()).detection.warmup_complete, { timeout: 30_000 })
    .toBe(true);
  await page.getByRole("list", { name: "Scenarios" }).getByRole("button", { name: /Stuck Inlet Valve/ }).click();
  await page.getByRole("button", { name: /Start scenario|Replace active scenario/ }).click();
  await expect(page.getByText(/Active scenario: Stuck Inlet Valve/)).toBeVisible();
  await expect(page.getByText(/detected after/)).toBeVisible({ timeout: 60_000 });

  await page.getByRole("link", { name: /Incidents/ }).first().click();
  const row = page.getByRole("link", { name: /Command \/ Actuator Mismatch on XV-101/ }).first();
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.click();
  await expect(page.getByText("Equipment fault").first()).toBeVisible();
  await page.getByLabel("Add investigation note").fill("E2E: valve stem inspection requested");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("E2E: valve stem inspection requested").first()).toBeVisible();

  await page.getByRole("link", { name: "Report", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Executive summary/ })).toBeVisible();
  await request.post("/api/scenarios/stop");
});

test("replay plays recorded data without touching the live plant", async ({ page }) => {
  await page.goto("/replay");
  await expect(page.getByText("REPLAY MODE · RECORDED DATA · NO LIVE EFFECTS")).toBeVisible();
  await page.getByRole("button", { name: "Jump to start" }).click();
  const pos = page.locator("#replay-scrub");
  const before = Number(await pos.inputValue());
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(async () => Number(await pos.inputValue()), { timeout: 10_000 }).toBeGreaterThan(before);
  await page.getByRole("button", { name: "Pause" }).click();
});

test("every navigation item leads to a working page", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  const expected: [RegExp, string][] = [
    [/Digital Twin/, "Industrial digital twin"],
    [/Live Telemetry/, "Live telemetry"],
    [/Detection Analytics/, "Detection analytics"],
    [/Incidents/, "Incident investigation"],
    [/Scenario Lab/, "Simulation & Scenario Lab"],
    [/Replay/, "Time-travel replay"],
    [/Reports/, "Security reports"],
    [/Settings/, "Simulation configuration"],
    [/Architecture/, "Architecture & methodology"],
    [/Overview/, "Plant overview"],
  ];
  for (const [link, heading] of expected) {
    await nav.getByRole("link", { name: link }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
});

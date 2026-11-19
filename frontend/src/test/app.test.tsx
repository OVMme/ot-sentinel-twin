import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { PlantDiagram } from "../components/PlantDiagram";
import { LiveProvider } from "../hooks/useLive";
import { viewFromSample } from "../lib/plant";
import { alert, defaultRoutes, FakeWebSocket, incident, installFetch, makeSample, simState, type Route } from "./fixtures";

function renderAt(path: string, route: Route = defaultRoutes()) {
  const calls = installFetch(route);
  const utils = render(
    <MemoryRouter initialEntries={[path]}>
      <LiveProvider>
        <App />
      </LiveProvider>
    </MemoryRouter>,
  );
  return { ...utils, calls };
}

async function connect(extra: Record<string, unknown> = {}) {
  await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
  const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  act(() => {
    ws.open();
    ws.emit({
      type: "hello",
      data: { state: simState, recent: [makeSample(1), makeSample(2), makeSample(3)], active_alerts: [], recent_alerts: [], ...extra },
    });
  });
  // flush the throttled snapshot
  await act(async () => {
    await new Promise((r) => setTimeout(r, 300));
  });
  return ws;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

describe("navigation", () => {
  const pages: [string, string][] = [
    ["/", "Plant overview"],
    ["/plant", "Industrial digital twin"],
    ["/telemetry", "Live telemetry"],
    ["/detection", "Detection analytics"],
    ["/incidents", "Incident investigation"],
    ["/scenarios", "Simulation & Scenario Lab"],
    ["/replay", "Time-travel replay"],
    ["/reports", "Security reports"],
    ["/settings", "Simulation configuration"],
    ["/about", "Architecture & methodology"],
  ];
  it.each(pages)("route %s renders its page", async (path, heading) => {
    renderAt(path);
    await connect();
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("sidebar links navigate between pages", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await connect();
    await user.click(screen.getByRole("link", { name: /Scenario Lab/ }));
    expect(await screen.findByRole("heading", { name: "Simulation & Scenario Lab" })).toBeInTheDocument();
  });

  it("unknown routes show a not-found state", async () => {
    renderAt("/nope");
    await connect();
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});

describe("live data", () => {
  it("overview shows values from the telemetry stream and the simulated-data label", async () => {
    renderAt("/");
    await connect();
    expect(await screen.findByText("60.0")).toBeInTheDocument(); // LT-101 3.0 m of 5 m
    expect(screen.getAllByText("SIMULATED DATA").length).toBeGreaterThan(0);
  });

  it("shows a disconnected banner when the WebSocket drops", async () => {
    renderAt("/");
    const ws = await connect();
    act(() => ws.close());
    expect(await screen.findByText(/Live connection to the simulator lost/)).toBeInTheDocument();
  });

  it("active alerts appear in the top bar", async () => {
    renderAt("/");
    await connect({ active_alerts: [alert] });
    expect(await screen.findByText("1 ACTIVE ALERT")).toBeInTheDocument();
  });
});

describe("plant diagram", () => {
  it("renders reported levels, setpoint and physical truth from a sample", () => {
    const view = viewFromSample(makeSample(5, { "sensor.primary_level": 2.0 }), 5);
    render(<PlantDiagram view={view} variant="twin" />);
    expect(screen.getByTestId("marker-LT-101")).toHaveTextContent("40.0%");
    expect(screen.getByTestId("truth-line")).toHaveTextContent("TRUE 68.0%");
    expect(screen.getByTestId("setpoint-line")).toHaveTextContent("SP 60%");
    expect(screen.getByTestId("valve-XV-101")).toHaveTextContent("CMD 45.0%");
  });

  it("HMI view hides the simulator truth", () => {
    render(<PlantDiagram view={viewFromSample(makeSample(5), 5)} variant="hmi" />);
    expect(screen.queryByTestId("truth-line")).not.toBeInTheDocument();
  });

  it("marks assets with active alerts", () => {
    const view = viewFromSample(makeSample(5), 5);
    render(<PlantDiagram view={view} anchors={{ "XV-101": { rules: ["PHYS-004"], severity: "high" } }} />);
    expect(screen.getByLabelText("Active alert PHYS-004")).toBeInTheDocument();
  });
});

describe("scenario lab", () => {
  it("starts the selected scenario with its parameters", async () => {
    const user = userEvent.setup();
    const { calls } = renderAt("/scenarios");
    await connect();
    const list = await screen.findByRole("list", { name: "Scenarios" });
    const cards = within(list).getAllByRole("button");
    await user.click(cards[1]); // B
    expect(within(list).getByRole("button", { pressed: true })).toHaveTextContent("Stuck Inlet Valve");
    await user.click(cards[2]); // C
    await user.click(screen.getByRole("button", { name: /Start scenario/ }));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.url === "/api/scenarios/sensor-manipulation/start");
      expect(post?.body).toEqual({ params: { offset_m: -1.4 } });
    });
  });

  it("reset asks for confirmation before posting", async () => {
    const user = userEvent.setup();
    const { calls } = renderAt("/scenarios");
    await connect();
    await user.click(await screen.findByRole("button", { name: "Reset" }));
    expect(calls.some((c) => c.url === "/api/simulation/reset")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm reset" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/simulation/reset")).toBe(true));
  });
});

describe("incidents", () => {
  it("shows an empty state when there are no incidents", async () => {
    renderAt("/incidents");
    await connect();
    expect(await screen.findByText("No incidents")).toBeInTheDocument();
  });

  it("shows an error state with retry when the API fails", async () => {
    renderAt("/incidents", defaultRoutes((_m, url) => (url.startsWith("/api/incidents") ? new TypeError("boom") : undefined)));
    await connect();
    expect(await screen.findByText("Could not load data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("incident detail shows evidence and supports analyst actions", async () => {
    const user = userEvent.setup();
    const { calls } = renderAt(
      "/incidents/INC-0001",
      defaultRoutes((m, url) => (m === "POST" && url.includes("/notes") ? { id: 1 } : m === "POST" ? { ok: true } : undefined)),
    );
    await connect();
    expect(await screen.findByRole("heading", { name: incident.title })).toBeInTheDocument();
    expect(screen.getByText("Suspected manipulation")).toBeInTheDocument();
    expect(screen.getByText("Calibration error")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Add investigation note"), "Checked sight glass");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.url === "/api/incidents/INC-0001/notes")?.body).toEqual({ text: "Checked sight glass" }),
    );
    await user.click(screen.getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/incidents/INC-0001/acknowledge")).toBe(true));
  });
});

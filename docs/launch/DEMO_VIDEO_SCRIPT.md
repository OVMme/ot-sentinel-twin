# Demo video script (45–60 s)

Setup: `docker compose up --build`, browser at 1600×1000, fresh run, simulation at 1x for 30 s, then 5x.
All on-screen data is synthetic — keep the "SIMULATED DATA" badge visible.

| Time | Screen | Action | Voice-over |
|---|---|---|---|
| 0–7 s | Overview | slow pan over KPIs and the animated twin | "This is OT Sentinel Twin — a synthetic water-storage process with a detection engine that checks physics, not just packets." |
| 7–14 s | Digital Twin (twin view) | hover over the tank: truth line and both level transmitters agree | "Liquid is the simulator's truth; the markers are what the instruments report. Right now they agree." |
| 14–20 s | Scenario Lab | 5x → select **C Sensor Value Manipulation** → Start | "Let's inject a synthetic false-data attack: the controller's level transmitter starts lying." |
| 20–30 s | Digital Twin | LT-101 drops, magenta truth rises, XV-101 opens to 100 %, red PHYS-002 badge on the tank | "The reported level falls, so the controller opens the inlet — while the real tank fills. Each value looks plausible on its own." |
| 30–38 s | Scenario Lab → Incidents | expected-vs-actual shows PHYS-002 / PHYS-001 detected in seconds; open the incident | "Mass balance and the redundant transmitter catch it within seconds: the reported volume change can't be explained by measured flows." |
| 38–47 s | Incident detail | scroll classification basis, alternatives, evidence charts | "The incident is classified as *suspected* manipulation — with the evidence and the non-malicious explanations an analyst must still rule out." |
| 47–56 s | Replay | jump to incident −30 s, press Play at 10x, before/after table | "Everything is recorded. Replay is deterministic: no re-simulation, no live effects." |
| 56–60 s | Detection Analytics | evaluation matrix and robustness sweep | "Measured results and their limits are in the repo. Open source, 100 % synthetic." |

Recording tips: hide the OS cursor during pans, use 1x for the twin close-up and 5x–10x for waiting periods, end on the
repository URL.

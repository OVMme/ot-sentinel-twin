"""Alert correlation and evidence-based incident classification.

Alerts that overlap in time (or follow each other within ``merge_window_s``) are grouped into
one incident. Each incident receives exactly one of four classifications, derived from a
documented decision procedure over the alerts and the reported telemetry only:

* ``data_quality``           - only telemetry freshness/integrity findings.
* ``equipment_fault``        - a component does not behave as its model predicts (valve, pump,
                               or a single sensor that is inconsistent with physics).
* ``physical_anomaly``       - the process itself deviates from the model while instruments agree
                               with each other (unmeasured flow, restriction, leak ...).
* ``suspected_manipulation`` - a single sensor is isolated as inconsistent by redundancy *and*
                               mass balance, the deviation appeared abruptly, and the controller
                               acted on the false value while the reported value stayed near
                               setpoint (a deception pattern). Always reported as *suspected*.

The classifier never sees scenario labels. It states its reasoning in ``classification_basis``
and always lists non-malicious explanations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.simulation.engine import TelemetrySample, _iso

from .base import Alert, ProcessModel
from .engine import AlertChange

Classification = Literal["data_quality", "equipment_fault", "physical_anomaly", "suspected_manipulation"]
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ABRUPT_RATE_M_S = 0.005  # sensor deviation growing faster than 5 mm/s is not plausible ageing drift
LEVEL_SENSORS = ("LT-101", "LT-102")

ALTERNATIVES: dict[str, list[str]] = {
    "data_quality": [
        "Transmitter power or communication loss",
        "Gateway / historian buffering or collector restart",
        "Clock synchronisation problem between field device and collector",
    ],
    "equipment_fault:valve": [
        "Loss of actuator air supply or positioner failure",
        "Mechanical binding of the valve stem",
        "Position feedback (ZT) miscalibration",
    ],
    "equipment_fault:pump": [
        "Impeller wear or damage, coupling slip",
        "Suction blockage or air entrainment",
        "Pressure transmitter PT-101 or flow meter FT-102 fault",
    ],
    "equipment_fault:sensor": [
        "Transmitter drift / ageing or calibration error",
        "Wiring, grounding or loop-power fault",
        "Range/span configuration change on the transmitter",
        "Deliberate falsification cannot be excluded from telemetry alone",
    ],
    "physical_anomaly": [
        "Partially closed manual valve or blockage downstream of PT-101",
        "Unmeasured leak, drain or overflow path",
        "Flow meter error masquerading as a process change",
        "Plant change not reflected in the twin's model",
    ],
    "suspected_manipulation": [
        "Abrupt calibration or configuration error on the primary transmitter",
        "Transmitter forced / simulated value left active after maintenance",
        "Engineering change not reflected in the model",
    ],
}

RECOMMENDED: dict[str, list[str]] = {
    "data_quality": [
        "Verify communication path and device status of the affected transmitter",
        "Compare with local indication in the field before relying on the value",
        "Check collector / gateway logs for buffering or restarts",
    ],
    "equipment_fault": [
        "Dispatch maintenance to verify the affected component locally",
        "Compare with independent instruments and local gauges",
        "Review recent maintenance and calibration records for the asset",
    ],
    "physical_anomaly": [
        "Walk down the affected line for leaks, closed manual valves or blockages",
        "Cross-check flow meters against tank level trends",
        "Confirm that no unrecorded plant change has been made",
    ],
    "suspected_manipulation": [
        "Treat the isolated transmitter as untrusted; operate on the redundant instrument",
        "Verify the true level locally (sight glass / manual dip) before any action",
        "Preserve controller, engineering-workstation and network logs for the incident window",
        "Review recent configuration changes and remote sessions to the controller and transmitter",
        "Escalate according to the site OT incident response plan",
    ],
}


@dataclass
class Incident:
    id: str
    title: str
    classification: Classification
    confidence: Literal["low", "medium", "high"]
    severity: str
    first_seen_t: float
    first_seen: str
    last_seen_t: float
    last_seen: str
    detection_state: Literal["active", "inactive"] = "active"
    status: str = "open"  # analyst workflow status, managed by the API
    acknowledged: bool = False
    alert_ids: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    summary: str = ""
    expected_behavior: str = ""
    observed_behavior: str = ""
    classification_basis: list[str] = field(default_factory=list)
    confidence_rationale: str = ""
    alternatives: list[str] = field(default_factory=list)
    recommended_steps: list[str] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class IncidentChange:
    change: Literal["created", "updated"]
    incident: Incident


class IncidentCorrelator:
    def __init__(
        self, model: ProcessModel, merge_window_s: float = 120.0, id_prefix: str = "INC", id_start: int = 0
    ) -> None:
        self.model = model
        self.merge_window_s = merge_window_s
        self.incidents: dict[str, Incident] = {}
        self._alerts: dict[str, Alert] = {}
        self._prefix = id_prefix
        self._counter = id_start
        self._current: Incident | None = None

    def reset(self) -> None:
        self.incidents.clear()
        self._alerts.clear()
        self._current = None

    def _new_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:04d}"

    # ------------------------------------------------------------------ main entry
    def process(self, changes: list[AlertChange], sample: TelemetrySample) -> list[IncidentChange]:
        out: dict[str, IncidentChange] = {}
        t = sample.sim_time_s
        ts = _iso(sample.timestamp)
        cur = self._current
        if cur is not None and cur.detection_state == "active":
            any_active = any(self._alerts[a].status == "active" for a in cur.alert_ids)
            if not any_active and t - cur.last_seen_t > self.merge_window_s:
                cur.detection_state = "inactive"
                cur.timeline.append(
                    {
                        "t": t,
                        "ts": ts,
                        "type": "detection_inactive",
                        "text": "All detections cleared; incident closed for new alerts.",
                    }
                )
                out[cur.id] = IncidentChange("updated", cur)
                self._current = None

        for ch in changes:
            a = ch.alert
            self._alerts[a.id] = a
            if ch.change == "raised":
                inc = self._current
                created = False
                if inc is None:
                    inc = Incident(
                        id=self._new_id(),
                        title="",
                        classification="physical_anomaly",
                        confidence="low",
                        severity=a.severity,
                        first_seen_t=a.first_seen_t,
                        first_seen=a.first_seen,
                        last_seen_t=t,
                        last_seen=ts,
                    )
                    self.incidents[inc.id] = inc
                    self._current = inc
                    created = True
                a.incident_id = inc.id
                inc.alert_ids.append(a.id)
                if a.rule_id not in inc.rule_ids:
                    inc.rule_ids.append(a.rule_id)
                if a.asset_id not in inc.assets:
                    inc.assets.append(a.asset_id)
                if a.first_seen_t < inc.first_seen_t:
                    inc.first_seen_t, inc.first_seen = a.first_seen_t, a.first_seen
                if SEVERITY_ORDER[a.severity] > SEVERITY_ORDER.get(inc.severity, 0):
                    inc.severity = a.severity
                inc.timeline.append(
                    {
                        "t": a.raised_t,
                        "ts": a.raised_at,
                        "type": "detection_raised",
                        "alert_id": a.id,
                        "rule_id": a.rule_id,
                        "text": f"{a.rule_id} {a.title} raised on {a.instance_key}: {a.explanation}",
                    }
                )
                inc.last_seen_t, inc.last_seen = t, ts
                out[inc.id] = IncidentChange("created" if created else "updated", inc)
            elif ch.change == "cleared" and a.incident_id in self.incidents:
                inc = self.incidents[a.incident_id]
                inc.timeline.append(
                    {
                        "t": a.cleared_t,
                        "ts": a.cleared_at,
                        "type": "detection_cleared",
                        "alert_id": a.id,
                        "rule_id": a.rule_id,
                        "text": f"{a.rule_id} on {a.instance_key} returned to normal.",
                    }
                )
                inc.last_seen_t, inc.last_seen = t, ts
                out.setdefault(inc.id, IncidentChange("updated", inc))

        # Re-evaluate classification of the current incident with fresh telemetry context.
        inc = self._current
        if inc is not None:
            if any(self._alerts[a].status == "active" for a in inc.alert_ids):
                inc.last_seen_t, inc.last_seen = t, ts
            before = (inc.classification, inc.confidence)
            self._classify(inc, sample)
            if before != (inc.classification, inc.confidence) or inc.id in out:
                if before != (inc.classification, inc.confidence) and inc.timeline:
                    verb = (
                        "revised" if any(e["type"] == "classification" for e in inc.timeline) else "assigned"
                    )
                    inc.timeline.append(
                        {
                            "t": t,
                            "ts": ts,
                            "type": "classification",
                            "text": f"Classification {verb}: "
                            f"{inc.classification.replace('_', ' ')} "
                            f"(confidence {inc.confidence}). " + " ".join(inc.classification_basis[-2:]),
                        }
                    )
                out.setdefault(inc.id, IncidentChange("updated", inc))
        return list(out.values())

    # ------------------------------------------------------------------ classification
    def _classify(self, inc: Incident, sample: TelemetrySample) -> None:
        alerts = [self._alerts[a] for a in inc.alert_ids]
        rules = {a.rule_id for a in alerts}
        pairs = {(a.rule_id, a.instance_key) for a in alerts}
        h = self.model.tank_height_m
        basis: list[str] = []
        ev = inc.evidence

        # sensor isolation evidence
        suspects = {
            s
            for s in LEVEL_SENSORS
            if ("PHYS-001", s) in pairs or ("PHYS-003", s) in pairs or ("PHYS-006", s) in pairs
        }
        rate = max((a.metrics.get("max_abs_deviation_rate_m_s", 0.0) for a in alerts), default=0.0)
        ev["max_deviation_rate_m_s"] = max(ev.get("max_deviation_rate_m_s", 0.0), rate)

        # Control-impact test on the controller's process variable (PV). Two deception patterns:
        #  (a) "false error": the PV shows a control error that the redundant transmitter does not
        #      confirm, and the measured flows show the controller actively filling/draining on it;
        #  (b) "masking": the PV sits at setpoint while the redundant transmitter has departed.
        pv_tag = self.model.controller_pv_tag
        vals = [
            sample.value(n)
            for n in (
                "sensor.primary_level",
                "sensor.secondary_level",
                "controller.setpoint_percent",
                "flow.inlet_lps",
                "flow.outlet_lps",
            )
        ]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            lt1, lt2, sp, qin, qout = (float(v) for v in vals)  # type: ignore[arg-type]
            pv_pct, other_pct = lt1 / h * 100.0, lt2 / h * 100.0
            if pv_tag == "LT-102":
                pv_pct, other_pct = other_pct, pv_pct
            e_pv, e_red = sp - pv_pct, sp - other_pct
            net = qin - qout
            false_error = (
                abs(e_pv) >= 5.0
                and (e_pv * e_red <= 0 or abs(e_red) <= 0.5 * abs(e_pv))
                and net * (1 if e_pv > 0 else -1) >= 3.0
            )
            masking = abs(e_pv) <= 3.0 and abs(e_red) >= 8.0
            if (false_error or masking) and not ev.get("control_impact_observed"):
                ev["control_impact_observed"] = True
                ev["control_impact_snapshot"] = {
                    "t": sample.sim_time_s,
                    "ts": _iso(sample.timestamp),
                    "pattern": "false-error" if false_error else "masking",
                    "pv_tag": pv_tag,
                    "pv_pct": round(pv_pct, 2),
                    "redundant_pct": round(other_pct, 2),
                    "setpoint_pct": round(sp, 2),
                    "net_inflow_lps": round(net, 2),
                }

        cls: Classification
        conf: Literal["low", "medium", "high"]
        alt_key: str
        if rules <= {"DATA-001"}:
            cls, conf, alt_key = "data_quality", "high", "data_quality"
            basis.append(
                "Only telemetry freshness/integrity rules fired; no physical inconsistency evaluated."
            )
        elif "PHYS-004" in rules or "PHYS-005" in rules:
            cls, alt_key = (
                "equipment_fault",
                ("equipment_fault:valve" if "PHYS-004" in rules else "equipment_fault:pump"),
            )
            conf = "high" if len(rules) == 1 or max(a.peak_score for a in alerts) >= 2 else "medium"
            comp = [a.instance_key for a in alerts if a.rule_id in ("PHYS-004", "PHYS-005")]
            basis.append(f"Component behaviour contradicts its model: {', '.join(sorted(set(comp)))}.")
        elif len(suspects) == 1 or ("PHYS-002" in rules and len(suspects) == 1):
            sensor = next(iter(suspects))
            ev["isolated_sensor"] = sensor
            basis.append(
                f"{sensor} is isolated: it disagrees with physics (mass balance / rate / flatline) while the "
                f"redundant transmitter remains consistent with measured flows."
            )
            abrupt = ev["max_deviation_rate_m_s"] >= ABRUPT_RATE_M_S or ("PHYS-003", sensor) in pairs
            if ("PHYS-006", sensor) in pairs:
                cls, conf, alt_key = "equipment_fault", "high", "equipment_fault:sensor"
                basis.append(f"{sensor} value is frozen while the process is changing.")
            elif abrupt and sensor == pv_tag and ev.get("control_impact_observed"):
                cls, conf, alt_key = "suspected_manipulation", "medium", "suspected_manipulation"
                snap = ev.get("control_impact_snapshot", {})
                rate_mm = ev["max_deviation_rate_m_s"] * 1000
                how = f"up to {rate_mm:.1f} mm/s" if rate_mm > 0 else "rate beyond physical limits, PHYS-003"
                basis.append(
                    f"Deviation appeared abruptly ({how}; plausible transmitter drift is below "
                    f"{ABRUPT_RATE_M_S * 1000:.0f} mm/s)."
                )
                if snap.get("pattern") == "masking":
                    basis.append(
                        f"{sensor} is the controller's process variable and stayed near setpoint "
                        f"({snap.get('pv_pct')} % vs SP {snap.get('setpoint_pct')} %) while the redundant "
                        f"transmitter showed {snap.get('redundant_pct')} %: the false value hid a real process change."
                    )
                else:
                    basis.append(
                        f"{sensor} is the controller's process variable: it showed {snap.get('pv_pct')} % against a "
                        f"setpoint of {snap.get('setpoint_pct')} %, an error the redundant transmitter "
                        f"({snap.get('redundant_pct')} %) does not confirm, and measured flows show the controller "
                        f"acting on it (net {snap.get('net_inflow_lps'):+} L/s): the false value is driving the "
                        f"physical process."
                    )
            else:
                cls, alt_key = "equipment_fault", "equipment_fault:sensor"
                conf = "high" if len(rules) >= 2 else "medium"
                basis.append(
                    "Deviation onset was abrupt (step/offset)."
                    if abrupt
                    else "Deviation grew slowly, consistent with transmitter drift."
                )
        elif "PHYS-002" in rules:
            cls, conf, alt_key = "equipment_fault", "low", "equipment_fault:sensor"
            basis.append(
                "Redundant level transmitters disagree but neither can yet be isolated by mass balance."
            )
        elif "PHYS-006" in rules:
            frozen = sorted({a.instance_key for a in alerts if a.rule_id == "PHYS-006"})
            cls, conf, alt_key = "equipment_fault", "high", "equipment_fault:sensor"
            basis.append(
                f"{', '.join(frozen)} frozen while independent signals show the process changing; "
                "other inconsistencies are explained by the frozen value."
            )
        elif "PHYS-007" in rules or suspects == set(LEVEL_SENSORS):
            cls, alt_key = "physical_anomaly", "physical_anomaly"
            conf = "medium"
            if "PHYS-007" in rules:
                basis.append("Measured outlet flow contradicts the hydraulic model at the measured pressure.")
            if suspects == set(LEVEL_SENSORS):
                basis.append("Both level transmitters agree with each other but not with measured flows.")
        else:
            cls, conf, alt_key = "physical_anomaly", "low", "physical_anomaly"
            basis.append("Physical inconsistency without a single attributable component.")

        inc.classification, inc.confidence = cls, conf
        inc.classification_basis = basis
        inc.alternatives = ALTERNATIVES[alt_key]
        inc.recommended_steps = RECOMMENDED[cls]
        inc.confidence_rationale = {
            "high": "Several independent checks agree, or a single check exceeds its threshold by a wide margin.",
            "medium": "The pattern is supported by more than one signal, but alternative explanations remain plausible.",
            "low": "Evidence is limited to a single check; the cause cannot be attributed yet.",
        }[conf]
        primary = min(alerts, key=lambda a: (-SEVERITY_ORDER[a.severity], a.first_seen_t))
        inc.title = _title(cls, primary, ev.get("isolated_sensor"))
        inc.summary = (primary.peak_explanation or primary.explanation) + (
            f" {len(alerts) - 1} further detection(s) are correlated with this incident."
            if len(alerts) > 1
            else ""
        )
        inc.expected_behavior = _fmt_pair(primary, expected=True)
        inc.observed_behavior = _fmt_pair(primary, expected=False)


def _title(cls: str, primary: Alert, sensor: str | None) -> str:
    if cls == "suspected_manipulation":
        return f"{sensor} reports values inconsistent with physics - suspected manipulation"
    if cls == "data_quality":
        return f"Telemetry from {primary.instance_key} is not fresh"
    if cls == "equipment_fault" and sensor:
        return f"{sensor} measurement inconsistent with process physics"
    return f"{primary.title} on {primary.instance_key}"


def _fmt_pair(a: Alert, expected: bool) -> str:
    """Human-readable expected/observed value at the alert's strongest evidence (peak)."""
    v = a.peak_expected if expected else a.peak_observed
    if v is None:
        v = a.expected_value if expected else a.observed_value
    if v is None:
        return "n/a"
    label = a.expected_label if expected else a.observed_label
    return f"{label}: {v:.3f} {a.units} ({a.rule_id})"

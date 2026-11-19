// Types mirroring the backend API. All data is synthetic.

export type Quality = "good" | "uncertain" | "bad";
export type Severity = "low" | "medium" | "high" | "critical";
export type Classification = "data_quality" | "equipment_fault" | "physical_anomaly" | "suspected_manipulation";

export interface SignalReading {
  v: number | boolean | string | null;
  u: string;
  t_src: number;
  q: Quality;
  valid: boolean;
  tag: string;
}

export interface Truth {
  level_m: number;
  level_pct: number;
  volume_m3: number;
  qin_lps: number;
  qout_lps: number;
  overflow_lps: number;
  inlet_pos_pct: number;
  outlet_pos_pct: number;
  pump_speed: number;
  line_pressure_bar: number;
  pump_power_kw: number;
  dry_running: boolean;
  interlock_high: boolean;
  interlock_low: boolean;
  faults: string[];
}

export interface Derived {
  predicted_level_m?: number | null;
  mass_residual_m3?: Record<string, number | null>;
  disagreement_m?: number | null;
  level_rate_m_s?: Record<string, number | null>;
  valve_expected_pct?: Record<string, number>;
  pump_dp_deficit_bar?: number | null;
  outlet_flow_expected_lps?: number | null;
  scores?: Record<string, number>;
  anomaly_score?: number;
  active_alerts?: number;
}

export interface Sample {
  run_id: string;
  seq: number;
  t: number;
  ts: string;
  signals: Record<string, SignalReading>;
  truth: Truth;
  derived: Derived;
  validity: Record<string, boolean>;
  scenario_id: string | null;
}

export interface EvidenceEntry {
  phase: string;
  t: number;
  ts: string;
  statistic: number | null;
  threshold: number;
  observed: number | null;
  expected: number | null;
  values: Record<string, unknown>;
}

export interface Alert {
  id: string;
  rule_id: string;
  title: string;
  category: "physics" | "data_quality";
  severity: Severity;
  asset_id: string;
  instance_key: string;
  signal: string;
  units: string;
  threshold: number | null;
  observed_value: number | null;
  expected_value: number | null;
  statistic?: number | null;
  peak_score: number | null;
  peak_observed?: number | null;
  peak_expected?: number | null;
  peak_explanation?: string;
  expected_label?: string;
  observed_label?: string;
  first_seen: string;
  raised_at: string;
  last_seen: string;
  cleared_at: string | null;
  first_seen_t: number;
  raised_t: number;
  last_seen_t: number;
  cleared_t: number | null;
  status: "active" | "cleared";
  explanation: string;
  evidence: EvidenceEntry[];
  metrics: Record<string, number>;
  incident_id: string | null;
  run_id?: string;
}

export interface TimelineEntry {
  t: number | null;
  ts: string | null;
  type: string;
  text: string;
  alert_id?: string;
  rule_id?: string;
}

export interface Note {
  id: number;
  incident_id: string;
  author: string;
  text: string;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  ts: string;
  actor: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
}

export interface ScenarioEventRow {
  id?: number;
  run_id?: string;
  scenario_id: string;
  kind: string;
  sim_time_s?: number;
  t?: number;
  ts: string;
  description: string;
  ground_truth: Record<string, unknown>;
}

export interface Incident {
  id: string;
  run_id?: string;
  title: string;
  classification: Classification;
  confidence: "low" | "medium" | "high";
  severity: Severity;
  detection_state: "active" | "inactive";
  status: string;
  acknowledged: boolean;
  first_seen_t: number;
  first_seen: string;
  last_seen_t: number;
  last_seen: string;
  rule_ids: string[];
  assets: string[];
  summary: string;
  expected_behavior: string;
  observed_behavior: string;
  classification_basis: string[];
  confidence_rationale: string;
  alternatives: string[];
  recommended_steps: string[];
  timeline?: TimelineEntry[];
  evidence?: Record<string, unknown>;
  alert_ids?: string[];
}

export interface WindowRow {
  seq: number;
  t: number;
  ts: string;
  lt101: number | null;
  lt102: number | null;
  ft101: number | null;
  ft102: number | null;
  pt101: number | null;
  zt101: number | null;
  zt102: number | null;
  inlet_cmd: number | null;
  outlet_cmd: number | null;
  pump_cmd: boolean | null;
  pump_running: boolean | null;
  pump_kw: number | null;
  setpoint: number | null;
  true_level: number | null;
  predicted_level: number | null;
  residual_lt101: number | null;
  residual_lt102: number | null;
  disagreement: number | null;
  anomaly_score: number | null;
}

export interface IncidentDetail extends Incident {
  notes: Note[];
  detections: Alert[];
  scenario_events: ScenarioEventRow[];
  audit: AuditEvent[];
  telemetry: WindowRow[];
}

export interface ScenarioState {
  scenario_id: string;
  code: string;
  title: string;
  params: Record<string, number | string>;
  phase: "armed" | "active";
  started_t: number;
  onset_t: number;
  elapsed_s: number;
  ground_truth: GroundTruth;
  next_actions: { offset_s: number; description: string; done: boolean }[];
}

export interface GroundTruth {
  scenario_id: string;
  code: string;
  category: string;
  params: Record<string, number | string>;
  expected_rules: string[];
  allowed_rules: string[];
  expected_classification: string | null;
  expected_latency_s: number | null;
}

export interface SimState {
  run_id: string;
  status: "running" | "paused" | "error";
  speed: number;
  max_speed: number;
  sim_time_s: number;
  seq: number;
  epoch: string;
  sim_timestamp: string;
  mode: "auto" | "manual";
  setpoint_pct: number;
  manual_commands: { inlet_valve_pct: number; outlet_valve_pct: number; pump_on: boolean };
  interlocks: { high: boolean; low: boolean };
  controller_health: string;
  scenario: ScenarioState | null;
  detection: {
    status: string;
    samples_processed: number;
    active_alerts: number;
    rules_enabled: number;
    rules_total: number;
    anomaly_score: number;
    warmup_complete: boolean;
  };
  health: { loop_lag_ms: number; ws_clients: number; pending_samples: number };
  read_only: boolean;
  demo_mode: boolean;
  config: { seed: number; sample_interval_s: number; tank_area_m2: number; tank_height_m: number };
}

export interface ScenarioParam {
  name: string;
  label: string;
  kind: "number" | "select";
  default: number | string;
  minimum: number | null;
  maximum: number | null;
  unit: string;
  options: string[];
}

export interface ScenarioDef {
  id: string;
  code: string;
  title: string;
  category: string;
  summary: string;
  initial_conditions: string;
  trigger: string;
  changes: string[];
  expected_behavior: string;
  required_evidence: string[];
  reset_behavior: string;
  onset_delay_s: number;
  expected_latency_s: number | null;
  params: ScenarioParam[];
  timeline: { offset_s: number; description: string }[];
  ground_truth_defaults: GroundTruth;
}

export interface RuleConfig {
  enabled: boolean;
  severity: Severity;
  threshold: number;
  debounce_s: number;
  clear_s: number;
  clear_ratio: number;
  window_s: number;
  units: string;
}

export interface RuleInstance {
  key: string;
  state: "idle" | "pending" | "active";
  statistic: number | null;
  threshold: number | null;
  score: number | null;
  evaluable: boolean;
  alert_id: string | null;
}

export interface RuleStatus {
  rule_id: string;
  title: string;
  category: string;
  description: string;
  methodology: string;
  config: RuleConfig;
  instances: RuleInstance[];
}

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface RunInfo {
  id: string;
  started_at: string;
  ended_at: string | null;
  epoch: string;
  status: string;
  mode: string;
  seed: number;
  sample_interval_s: number;
  sample_count: number;
  first_seq: number;
  sim_duration_s: number;
  truncated: boolean;
  incident_count: number;
  detection_count: number;
  scenarios: string[];
}

export type ReplayColumns = {
  seq: number[];
  sim_time_s: number[];
  ts: string[];
  mode: (string | null)[];
  scenario_id: (string | null)[];
} & Record<
  | "lt101"
  | "lt102"
  | "ft101"
  | "ft102"
  | "pt101"
  | "zt101"
  | "zt102"
  | "inlet_cmd"
  | "outlet_cmd"
  | "pump_kw"
  | "setpoint"
  | "true_level"
  | "predicted_level"
  | "residual_lt101"
  | "residual_lt102"
  | "disagreement"
  | "anomaly_score",
  (number | null)[]
> &
  Record<"pump_cmd" | "pump_running", (boolean | null)[]>;

export interface ReplayData {
  run: RunInfo;
  from_seq: number;
  count: number;
  next_from_seq: number | null;
  columns: ReplayColumns;
  detections: Alert[];
  incidents: Incident[];
  scenario_events: ScenarioEventRow[];
}

export interface CoverageRow {
  scenario: string;
  code: string;
  expected_rules: string[];
  allowed_rules: string[];
  runs: number;
  detected: number;
  false_positives: number;
  rules_fired: string[];
  classification_expected: string | null;
  classification_ok: number;
  classifications: string[];
  anomalous: boolean;
  latency_mean_s: number | null;
  latency_max_s: number | null;
  result: "PASS" | "FAIL";
}

export interface EvaluationSummary {
  runs: number;
  anomalous_runs: number;
  true_positives: number;
  false_negatives: number;
  attributed_alerts: number;
  false_positive_alerts: number;
  precision: number;
  recall: number;
  f1: number;
  latency_mean_s: number | null;
  latency_max_s: number | null;
  normal_operation_hours: number;
  normal_operation_false_positives: number;
  false_positives_per_hour_normal: number | null;
  classification_accuracy: number | null;
  coverage_matrix: CoverageRow[];
}

export interface RobustnessRow {
  severity: number;
  precision: number;
  recall: number;
  f1: number;
  latency_mean_s: number | null;
  false_positive_alerts: number;
  normal_operation_false_positives: number;
  classification_accuracy: number | null;
  false_positive_rules: string[];
  missed: string[];
}

export interface EvaluationResult {
  generated_at: string;
  data_notice: string;
  seeds: number[];
  definitions: Record<string, string | number>;
  summary: EvaluationSummary;
  robustness?: { description: string; sweep: RobustnessRow[] };
  wall_time_s: number;
}

export interface EvaluationResponse {
  status: { running: boolean; started_at: string | null; error: string | null; finished_at?: string };
  result: EvaluationResult | null;
}

export interface Report {
  report_id: string;
  generated_at: string;
  data_notice: string;
  executive_summary: string;
  simulation: Record<string, unknown>;
  incident: Pick<
    Incident,
    | "id"
    | "title"
    | "classification"
    | "confidence"
    | "severity"
    | "status"
    | "acknowledged"
    | "detection_state"
    | "first_seen"
    | "last_seen"
  >;
  classification_label: string;
  affected_assets: { id: string; name: string; kind: string }[];
  timeline: { ts: string | null; t: number | null; source: string; type: string; text: string }[];
  triggered_rules: Array<{
    id: string;
    rule_id: string;
    title: string;
    instance_key: string;
    asset_id: string;
    severity: Severity;
    status: string;
    raised_at: string;
    cleared_at: string | null;
    observed_value: number | null;
    expected_value: number | null;
    threshold: number | null;
    units: string;
    peak_score: number | null;
    explanation: string;
  }>;
  discrepancies: Array<{ rule_id: string; instance: string; at: string; observed: number | null; expected: number | null }>;
  expected_behavior: string;
  observed_behavior: string;
  supporting_telemetry: {
    window_s: [number, number];
    signals: {
      signal: string;
      label: string;
      unit: string;
      before: { min: number; max: number; mean: number } | null;
      during: { min: number; max: number; mean: number } | null;
    }[];
  };
  methodology: { rule_id: string; title: string; description: string; methodology: string; config: RuleConfig }[];
  classification_basis: string[];
  confidence_rationale: string;
  alternative_explanations: string[];
  evidence_limitations: string[];
  recommended_investigation_steps: string[];
  analyst_notes: Note[];
  conclusions: string;
  simulator_ground_truth: { notice: string; events: { ts: string; t: number; kind: string; scenario_id: string; description: string }[] };
}

export interface Asset {
  id: string;
  name: string;
  kind: string;
  description: string;
  tags: string[];
  signals: string[];
}

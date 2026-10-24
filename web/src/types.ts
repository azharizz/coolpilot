export type RunRequest = {
  workload: "camera_health";
  camera: CameraSettings;
  name: string;
  strategy: "agent" | "random" | "baseline";
  budget: number;
  repetitions: number;
  hourly_price: number | null;
  seed: number;
};
export type Gate = {
  passed: boolean;
  checks: {
    metric: string;
    actual: number;
    operator: string;
    limit: number;
    passed: boolean;
  }[];
};
export type CameraExperiment = {
  id: number;
  sequence: number;
  run_id: string;
  kind: string;
  status: string;
  workload?: "camera_health";
  config: CameraConfig;
  rationale: string;
  gate: Gate | null;
  metrics?: CameraMetrics;
  error: string | null;
  split?: string;
  repetitions?: number;
  dataset?: CameraDataset;
  trace?: {streams: CameraStream[]};
};
export type RunSummary = {
  id: string;
  created: string;
  status: string;
  request: RunRequest;
  summary: string | null;
  error: string | null;
  recommendation: number | null;
};
export type History = {
  items: RunSummary[];
  total: number;
  page: number;
  page_size: number;
  running_id: string | null;
};
export type CameraRunData = RunSummary & {
  experiments: CameraExperiment[];
  events: {
    id: number;
    created: string;
    kind: string;
    payload: Record<string, unknown>;
  }[];
};
export type System = {
  readonly?: boolean;
  runtime: {
    architecture: string;
    system: string;
    cpu_count: number;
    opencv_version: string;
    distribution: string;
    hardware_note: string;
    build_sha256: string;
  };
  agent: { model: string; configured: boolean };
  cool: { available: boolean; detail: string };
  camera_datasets: CameraDataset[];
};

export type DetectorTuning = Partial<Record<"glare_rise" | "dark_ratio" | "blur_ratio" | "obstruction_ratio" | "obstruction_s" | "hysteresis" | "persistence_s" | "recovery_s", number | null>>;
export type CameraConfig = {
  width: number; sample_every: number; threads: number; queue_size: number;
  mode: "local" | "scheduled" | "hybrid"; review_interval_s: number;
  detector?: DetectorTuning | null;
};
export type CameraSettings = {
  dataset: string; dataset_sha256: string; baseline: CameraConfig;
  goals: {
    faults: Record<string, { min_recall: number; max_detection_s: number; max_recovery_s: number; min_events: number }>;
    max_false_alarms_per_hour: number; min_normal_seconds: number; max_age_s: number;
    max_unknown_fraction: number; max_api_failure_fraction: number; max_cost_per_camera_hour?: number | null;
  };
  thresholds?: Record<string, number>;
  scenarios?: {clip: string; interruptions: {start_s: number; end_s: number}[]; processing_delay_ms?: number; processing_delay_interval?: {start_s: number; end_s: number} | null}[];
  concurrent_streams: number; allow_image_requests: boolean; max_image_requests: number;
  api_timeout_s: number; cool_hourly_price: number | null;
};
export type CameraDataset = {
  id: string; error?: string; sha256: string; development_only: boolean;
  clips: {id: string; session: string; camera: string; split: string; duration_s: number; sha256: string}[];
};
export type CameraMetrics = {
  cpu_seconds_per_camera_second: number; wall_seconds: number; camera_seconds: number;
  peak_rss_mb: number; max_age_s: number; p95_ms: number | null; cost_per_camera_hour: number | null;
  image_requests: number; image_cost: number | null; streams_tested: number;
  evaluations: {clip: string; repetition: number; stream: number; unknown_fraction: number; dropped: number;
    false_alarms?: {type: string; start_s: number}[];
    by_fault: Record<string, {events: number; missed: number; recall: number; detection_s: number | null; recovery_s: number | null; bad_recovery: number}>}[];
  repetition_evidence: {repetition: number; normal_seconds: number; false_alarms_per_hour: number | null; event_counts: Record<string, number>}[];
};
export type CameraStream = {
  clip: string; repetition: number; stream: number; session: string; camera: string;
  transitions?: {time_s: number; pipeline_status?: string; quality_status?: string; visual_observations?: string[]; unknown: boolean; delivery: string; queue_age_s: number}[];
  observations?: {pts_s: number; analysis_s: number; arrival_age_s: number; local_conditions: string[];
    regions: {box: number[]; mean: number; detail: number; clipped: number; suspected_obstruction?: boolean}[]}[];
  episodes: {type: string; start_s: number; end_s: number | null}[];
  truth: {type: string; start_s: number; end_s: number; provenance: string; severity?: string}[];
  reviews: {frame: number; status: string; latency_s?: number; cost?: number | null; error?: string; probabilities?: Record<string, number>}[];
};

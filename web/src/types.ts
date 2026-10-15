export type Configuration = {
  width: number;
  features: number;
  frame_stride: number;
  threads: number;
  workers: number;
  pyramid_levels: number;
};
export type Goals = {
  min_success: number;
  max_corner_error_px: number;
  max_p95_ms: number;
};
export type RunRequest = {
  workload?: "tracking" | "camera_health";
  camera?: CameraSettings;
  name: string;
  strategy: "agent" | "random" | "baseline";
  budget: number;
  repetitions: number;
  frames: number;
  goals: Goals;
  baseline: Configuration;
  hourly_price: number | null;
  seed: number;
};
export type Metrics = {
  throughput_fps: number;
  p95_ms: number;
  p50_ms: number;
  success_rate: number;
  corner_error_px: number;
  mean_iou: number;
  lost_frames: number;
  scored_frames_per_stream: number;
  processed_frames_per_stream: number;
  prediction_interval_ms: number;
  cpu_capacity_pct: number;
  worker_peak_rss_sum_mb: number;
  cost_per_video_hour: number | null;
  stages_ms: Record<string, number>;
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
export type Polygon = number[][];
export type Experiment = {
  id: number;
  sequence: number;
  run_id: string;
  kind: string;
  status: string;
  config: Configuration;
  rationale: string;
  gate: Gate | null;
  metrics?: Metrics;
  error: string | null;
  split?: "tuning" | "validation";
  frames?: number;
  repetitions?: number;
  rounds?: { throughput_fps: number; p95_ms: number; wall_seconds: number }[];
  trace?: {
    polygons: (Polygon | null)[];
    truth: Polygon[];
    errors_px: number[];
    ious: number[];
  };
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
export type Run = RunSummary & {
  experiments: Experiment[];
  frontier: number[];
  events: {
    id: number;
    created: string;
    kind: string;
    payload: Record<string, unknown>;
  }[];
};
export type Dataset = {
  name: string;
  source: string;
  citation: string;
  fps: number;
  frame_count: number;
  width: number;
  height: number;
  sha256: string;
  annotation: string;
  splits: Record<string, { start: number; max_frames: number }>;
};
export type System = {
  runtime: {
    architecture: string;
    system: string;
    cpu_count: number;
    opencv_version: string;
    distribution: string;
    hardware_note: string;
    build_sha256: string;
  };
  dataset: Dataset | null;
  dataset_state: { status: string; error: string | null };
  agent: { model: string; configured: boolean };
  cool: { available: boolean; detail: string };
  camera_datasets: CameraDataset[];
};
export type Active = {
  id: number;
  created: string;
  experiment_id: number;
  previous_id: number | null;
  experiment: Experiment;
} | null;

export type CameraConfig = {
  width: number; sample_every: number; threads: number; queue_size: number;
  mode: "local" | "scheduled" | "hybrid"; review_interval_s: number;
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
    by_fault: Record<string, {events: number; missed: number; recall: number; detection_s: number | null; recovery_s: number | null; bad_recovery: number}>}[];
  repetition_evidence: {repetition: number; normal_seconds: number; false_alarms_per_hour: number | null; event_counts: Record<string, number>}[];
};
export type CameraStream = {
  clip: string; repetition: number; stream: number; session: string; camera: string;
  transitions?: {time_s: number; conditions: string[]; unknown: boolean; delivery: string; queue_age_s: number}[];
  observations?: {pts_s: number; analysis_s: number; arrival_age_s: number; local_conditions: string[];
    regions: {box: number[]; mean: number; detail: number; clipped: number; suspected_obstruction?: boolean}[]}[];
  episodes: {type: string; start_s: number; end_s: number | null}[];
  truth: {type: string; start_s: number; end_s: number; provenance: string; severity?: string}[];
  reviews: {frame: number; status: string; latency_s?: number; cost?: number | null; error?: string; probabilities?: Record<string, number>}[];
};
export type CameraExperiment = Omit<Experiment, "config" | "metrics" | "trace" | "split"> & {
  workload?: "camera_health"; config: CameraConfig; metrics?: CameraMetrics; split?: string;
  dataset?: CameraDataset; trace?: {streams: CameraStream[]};
};
export type CameraRunData = Omit<Run, "experiments"> & {experiments: CameraExperiment[]};

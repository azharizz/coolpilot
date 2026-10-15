import { useEffect, useRef, useState } from "react";
import { useResource } from "./api";

type CameraId = "left" | "centre" | "right";
type Mode = "local" | "scheduled" | "hybrid";
type Sources = {
  sources: { id: CameraId; label: string; video_url: string }[];
  faults: string[]; decision_configured: boolean; distribution: string; opencv_version: string;
};
type Episode = { type: string; start_s: number; end_s: number | null };
type Injection = { kind: string; start_s: number; end_s: number; delay_ms?: number; max_delay_ms?: number; analysis_width_multiplier?: number };
type Review = {
  status: string; pts_s?: number; requested_s?: number; received_s?: number;
  attempted?: boolean; probabilities?: Record<string, number>; cost?: number | null;
  error?: string; latency_s?: number; late?: boolean;
};
type Frame = {
  type: "frame"; camera: CameraId; time_s: number; pipeline_status: string; quality_status: string;
  delivery_conditions: string[]; visual_conditions: string[];
  image: string | null; evidence_age_s: number | null;
  evidence: { frame?: number; pts_s?: number; analysis_ms?: number; decode_ms?: number;
    compute_ms?: number; injected_delay_ms?: number; analysis_width?: number;
    black_fraction?: number; regions?: { mean: number; detail: number; clipped: number }[] };
  processed: number; delivered: number; dropped: number; interrupted: number; rejected: number; queue_depth: number; processed_fps: number;
  analysis_p95_ms: number | null; injection_p95_ms: number | null;
  injection: { kind: string; current: string; strength: number }; episodes: Episode[];
  review_pending: Review | null; review_slot: Review | null; review_result: Review | null;
  review_attempts: number; review_cost: number; review_cost_complete: boolean;
};
type Ready = {
  type: "ready"; sources: { camera: CameraId; frames: number; source_fps: number; replay_seconds: number }[];
  environment: { distribution: string; opencv_version: string };
  configuration: { review_interval_s: number; mode: Mode };
  thresholds: { feed_timeout_s: number; backlog_s: number };
  faults: Record<CameraId, string>;
  seed: number; schedule: Record<CameraId, Injection[]>;
};
type Profile = {
  camera: CameraId; label: string; fault: string; frames: number; error?: string;
  trace?: { processed: number; skipped: number; dropped: number; interrupted_frames: number; rejected_frames: number;
    unfinished_frames: number; expected_frames: number; unknown_fraction: number;
    max_age_s: number; episodes: Episode[]; reviews: Review[]; review_required: number };
};
type Complete = Omit<Ready, "type"> & {
  type: "complete"; cancelled: boolean; profiles: Profile[];
  measurement: { wall_seconds: number; cpu_seconds: number; clock: string };
};
type Message = Frame | Ready | Complete | { type: "error"; error: string } |
  { type: "camera_error"; camera: CameraId; error: string };
const ids: CameraId[] = ["left", "centre", "right"];
const number = (value: number | null | undefined, digits = 2) => value == null ? "—" : value.toFixed(digits);

type Metric = { label: string; unit: string; value: (frame: Frame) => number | null | undefined };
const metricGroups: { label: string; metrics: Metric[] }[] = [
  { label: "Delivery", metrics: [
    { label: "Evidence age", unit: "s", value: f => f.evidence_age_s },
    { label: "Processed pace", unit: "fps", value: f => f.processed_fps },
    { label: "Processed", unit: "frames", value: f => f.processed },
    { label: "Delivered", unit: "frames", value: f => f.delivered },
    { label: "Dropped", unit: "frames", value: f => f.dropped },
    { label: "Queued", unit: "frames", value: f => f.queue_depth },
    { label: "Interrupted", unit: "frames", value: f => f.interrupted },
    { label: "Rejected", unit: "frames", value: f => f.rejected },
  ] },
  { label: "Processing", metrics: [
    { label: "Worker time (includes waits)", unit: "ms", value: f => f.evidence.analysis_ms },
    { label: "Worker p95", unit: "ms", value: f => f.analysis_p95_ms },
    { label: "Analyzer compute", unit: "ms", value: f => f.evidence.compute_ms },
    { label: "Injected wait", unit: "ms", value: f => f.evidence.injected_delay_ms },
    { label: "Decode", unit: "ms", value: f => f.evidence.decode_ms },
    { label: "Synthetic edit p95", unit: "ms", value: f => f.injection_p95_ms },
    { label: "Analysis width", unit: "px", value: f => f.evidence.analysis_width },
  ] },
  { label: "Image", metrics: [
    { label: "Detail variance", unit: "variance", value: f => f.evidence.regions?.length ? f.evidence.regions.reduce((sum, r) => sum + r.detail, 0) / f.evidence.regions.length : null },
    { label: "Brightness", unit: "0–255", value: f => f.evidence.regions?.length ? f.evidence.regions.reduce((sum, r) => sum + r.mean, 0) / f.evidence.regions.length : null },
    { label: "Clipped pixels", unit: "%", value: f => f.evidence.regions?.length ? f.evidence.regions.reduce((sum, r) => sum + r.clipped, 0) / f.evidence.regions.length * 100 : null },
    { label: "Black pixels", unit: "%", value: f => f.evidence.black_fraction == null ? null : f.evidence.black_fraction * 100 },
  ] },
];

export function CameraCompare() {
  const source = useResource<Sources>("/api/camera-comparison", 60000);
  const [faults, setFaults] = useState<Record<CameraId, string>>({ left: "random", centre: "random", right: "random" });
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 2147483648));
  const [mode, setMode] = useState<Mode>("local");
  const [consent, setConsent] = useState(false);
  const [interval, setIntervalSeconds] = useState(5);
  const [limit, setLimit] = useState(4);
  const [timeout, setTimeoutSeconds] = useState(5);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("Choose scenarios, then start a local replay. No images leave this service in local mode.");
  const [error, setError] = useState("");
  const [cameraErrors, setCameraErrors] = useState<Partial<Record<CameraId, string>>>({});
  const [ready, setReady] = useState<Ready>();
  const [result, setResult] = useState<Complete>();
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tick, setTick] = useState(Date.now());
  const [metrics, setMetrics] = useState([0, 0, 0]);
  const [regionMetric, setRegionMetric] = useState<"mean" | "detail" | "clipped">("mean");
  const [, redraw] = useState(0);
  const history = useRef<Record<CameraId, Frame[]>>({ left: [], centre: [], right: [] });
  const received = useRef<Partial<Record<CameraId, number>>>({});
  const controller = useRef<AbortController | null>(null);
  const liveTime = Math.max(0, ...ids.map(id => history.current[id].at(-1)?.time_s ?? 0));
  const horizon = ready ? Math.max(...ready.sources.map(s => s.replay_seconds)) : liveTime;
  const shownTime = busy ? liveTime : cursor;

  useEffect(() => {
    const timer = window.setInterval(() => setTick(Date.now()), 250);
    return () => { window.clearInterval(timer); controller.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const elapsed = (now - previous) / 1000;
      previous = now;
      setCursor(t => Math.min(liveTime, t + elapsed));
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, liveTime]);
  useEffect(() => { if (cursor >= liveTime) setPlaying(false); }, [cursor, liveTime]);

  async function start() {
    const abort = new AbortController();
    controller.current = abort;
    history.current = { left: [], centre: [], right: [] }; received.current = {};
    setReady(undefined); setResult(undefined); setCameraErrors({}); setError("");
    setCursor(0); setPlaying(false); setBusy(true); setPhase("Opening source metadata; frames decode incrementally during replay…");
    let completed = false;
    try {
      const response = await fetch("/api/camera-comparison/analyze", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: abort.signal,
        body: JSON.stringify({ faults, seed, mode, review_interval_s: interval, review_limit: limit,
          api_timeout_s: timeout, allow_image_requests: mode !== "local" && consent }),
      });
      if (!response.ok) {
        const problem = await response.json();
        throw new Error(typeof problem.detail === "string" ? problem.detail : "Invalid input. Check review limits and image consent.");
      }
      if (!response.body) throw new Error("Streaming response is unavailable in this browser.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      function accept(line: string) {
        const message = JSON.parse(line) as Message;
        if (message.type === "error") throw new Error(message.error);
        if (message.type === "ready") {
          setReady(message); setPhase("Live paced replay — previews and measurements come from the same analyzed frames.");
        } else if (message.type === "frame") {
          history.current[message.camera].push(message);
          received.current[message.camera] = Date.now();
          setCursor(message.time_s); redraw(n => n + 1);
        } else if (message.type === "camera_error") {
          setCameraErrors(errors => ({ ...errors, [message.camera]: message.error }));
        } else if (message.type === "complete") {
          completed = true; setResult(message);
          setPhase(message.cancelled ? "Replay stopped. Retained evidence is historical." : "Replay complete. Scrub or play the recorded preview samples below.");
        }
      }
      try {
        while (true) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
          lines.filter(line => line.trim()).forEach(accept);
          if (done) { if (buffer.trim()) accept(buffer); break; }
        }
      } finally { reader.releaseLock(); }
      if (!completed) throw new Error("The replay stream ended without a final report. Retained frames are partial evidence.");
    } catch (reason) {
      abort.abort();
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setPhase("Stopped. Retained samples are partial; the server releases the run after outstanding work exits (up to the review timeout).");
      } else {
        setError(reason instanceof Error ? reason.message : "Replay failed.");
        setPhase("Replay interrupted. Retained samples are historical, not live measurements.");
      }
    } finally {
      setBusy(false); controller.current = null;
      setCursor(Math.max(0, ...ids.map(id => history.current[id].at(-1)?.time_s ?? 0)));
    }
  }

  const distribution = ready?.environment.distribution ?? source.data?.distribution;
  const plots = metricGroups.map((group, index) => {
    const metric = group.metrics[metrics[index]];
    const series = ids.map(id => history.current[id].filter(f => f.time_s <= shownTime).map(f => {
      const value = metric.value(f);
      return { time: f.time_s, value: value != null && Number.isFinite(value) ? value : null };
    }));
    const reference = index === 0 && metrics[index] === 0 && ready
      ? Math.min(ready.thresholds.backlog_s, ready.thresholds.feed_timeout_s) : null;
    const max = metric.unit === "%" ? 100 : metric.unit === "0–255" ? 255 :
      Math.max(reference ?? 0, ...(index === 0 && metrics[index] === 1 ? ready?.sources.map(s => s.source_fps) ?? [] : []),
               ...series.flatMap(points => points.map(p => p.value ?? 0)), 1);
    return { metric, series, max, reference };
  });
  const regionMax = regionMetric === "mean" ? 255 : regionMetric === "clipped" ? 1 :
    Math.max(1, ...ids.flatMap(id => {
      const frame = history.current[id].reduce<Frame | undefined>((last, f) => f.time_s <= shownTime ? f : last, undefined);
      return frame?.evidence.regions?.map(r => r.detail) ?? [];
    }));
  return <section className="camera-workbench camera-comparison">
    <div className="section-heading"><h1>Three-camera replay monitor</h1>
      <p>Three forward views · one brief random fault per camera. Pipeline ≠ image quality. Unvalidated heuristics—not a driving-safety assessment.</p></div>
    {source.loading && !source.data && <p role="status">Loading camera sources…</p>}
    {source.error && <p className="notice" role="alert">{source.error}</p>}
    <p className="camera-runtime-note"><strong>Runtime: {distribution ?? "checking"} · OpenCV {ready?.environment.opencv_version ?? source.data?.opencv_version ?? "—"}</strong><br />
      {distribution === "COOL" ? "Detected COOL runtime; speedup not established." : "Local OpenCV · COOL unavailable on this host."}</p>
    <fieldset disabled={busy} className="camera-replay-settings"><legend>Next replay</legend>
      <div className="camera-comparison-controls">
        <label>Random seed <input id="camera-replay-seed" type="number" min="0" max="2147483647" step="1" value={seed} onChange={e => setSeed(e.target.valueAsNumber)} /></label>
        <button type="button" onClick={() => setSeed(Math.floor(Math.random() * 2147483648))}>New seed</button>
        <label>Review mode <select value={mode} onChange={e => { setMode(e.target.value as Mode); setConsent(false); }}>
          <option value="local">Local only · no uploads</option>
          <option value="scheduled" disabled={!source.data?.decision_configured}>Scheduled Decisions review</option>
          <option value="hybrid" disabled={!source.data?.decision_configured}>Decisions on local suspicion</option>
        </select></label>
        {mode !== "local" && <>
          <label>Review slot interval <select value={interval} onChange={e => setIntervalSeconds(Number(e.target.value))}>{[1, 2, 5].map(n => <option key={n} value={n}>{n} seconds</option>)}</select></label>
          <label>Max requests / camera <input type="number" min="1" max="10" value={limit} onChange={e => setLimit(Number(e.target.value))} /></label>
          <label>Request deadline (seconds) <input type="number" min="1" max="20" value={timeout} onChange={e => setTimeoutSeconds(Number(e.target.value))} /></label>
          <label className="camera-decision-consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> I authorize up to {limit * 3} image reviews for this run through OpenRouter to OpenAI, each with at most one HTTP 404 retry. Paid uploads, data collection allowed, not zero-retention. One outstanding review per camera; missed slots stay visible. Scores never clear local alarms.</label>
        </>}
      </div>
      {!source.data?.decision_configured && <p>Decisions is not configured on the server. Local replay remains available.</p>}
    </fieldset>
    <div className="camera-comparison-controls">
      <button type="button" onClick={start} disabled={busy || !source.data || !Number.isInteger(seed) || seed < 0 || seed > 2147483647 || (mode !== "local" && (!consent || limit < 1 || limit > 10 || timeout < 1 || timeout > 20))}>{busy ? "Replay running…" : mode === "local" ? "Start local three-camera replay" : "Start replay and paid review"}</button>
      {busy && <button type="button" onClick={() => controller.current?.abort()}>Stop replay</button>}
      {!busy && liveTime > 0 && <button type="button" onClick={() => { if (cursor >= liveTime) setCursor(0); setPlaying(!playing); }}>{playing ? "Pause recorded preview" : "Play recorded preview"}</button>}
      <label>Shared replay time {shownTime.toFixed(2)} / {horizon.toFixed(2)} s
        <input aria-label="Shared replay time" type="range" min="0" max={liveTime || 1} step="0.05" disabled={busy || !liveTime} value={shownTime} onChange={e => { setPlaying(false); setCursor(Number(e.target.value)); }} /></label>
    </div>
    <p role="status">{phase}</p>
    {error && <p className="notice" role="alert">{error}</p>}
    <details className="camera-run-notes"><summary>Replay notes{ready && ` · seed ${ready.seed}`}</summary>
      <p>Previews use analyzed pixels at up to 10 Hz. Timelines show sampled reports, not every frame; gaps are unknown and future time is blank. Scrub after replay to inspect history.</p>
      <p>Seeds repeat injection schedules, not host timing. Worker waits are synthetic, not COOL performance. Resolution stress doubles initial analysis width, not source resolution. Injection labels never control health.</p>
      <p>Image flags are suspicions: sky and scene changes can trigger glare or obstruction. No flag does not establish usable imagery. Stale evidence is unknown; last flags remain in diagnostics.</p>
    </details>
    <div className="camera-chart-controls">
      {metricGroups.map((group, i) => <label key={group.label}>{group.label} chart
        <select value={metrics[i]} onChange={e => setMetrics(values => values.map((value, j) => j === i ? Number(e.target.value) : value))}>
          {group.metrics.map((metric, j) => <option key={metric.label} value={j}>{metric.label}</option>)}
        </select>
      </label>)}
      <label>Region map<select value={regionMetric} onChange={e => setRegionMetric(e.target.value as typeof regionMetric)}>
        <option value="mean">Brightness</option><option value="detail">Detail variance</option><option value="clipped">Clipped pixels</option>
      </select></label>
    </div>
    <p className="camera-frame-caption">Shared scales · sampled report time · gaps = missing data · hover for values. Dashed line = age limit or source fps. Region shading = magnitude, not safety.</p>
    <div className="camera-comparison-grid">
      {source.data?.sources.map(camera => {
        const samples = history.current[camera.id];
        const snapshot = busy ? samples.at(-1) : samples.reduce<Frame | undefined>((last, frame) => frame.time_s <= cursor ? frame : last, undefined);
        const sinceReceipt = busy ? Math.max(0, (tick - (received.current[camera.id] ?? tick)) / 1000) : 0;
        const age = snapshot?.evidence_age_s == null ? null : snapshot.evidence_age_s + sinceReceipt;
        const stale = busy && (sinceReceipt > 1 || age == null || age >= Math.min(ready?.thresholds.backlog_s ?? 0.5, ready?.thresholds.feed_timeout_s ?? 1));
        const status = cameraErrors[camera.id] ? "unavailable" : stale ? "unknown" : snapshot?.pipeline_status ?? "unknown";
        const quality = cameraErrors[camera.id] || stale ? "unknown" : snapshot?.quality_status ?? "unknown";
        const profile = result?.profiles.find(p => p.camera === camera.id);
        const regions = snapshot?.evidence.regions ?? [];
        const review = snapshot?.review_result;
        const reviewAge = review?.pts_s == null || !snapshot ? null : snapshot.time_s - review.pts_s + sinceReceipt;
        const runMode = ready?.configuration.mode ?? "local";
        const episodes = snapshot?.episodes ?? [];
        const finalReviews = profile?.trace?.reviews ?? [];
        return <article className="camera-comparison-card" key={camera.id}>
          <h2>{camera.label} <small className="camera-frame-caption">{busy ? "Live" : snapshot ? "Recorded" : "Ready"}</small></h2>
          <label>Next replay fault <select disabled={busy} value={faults[camera.id]} onChange={e => setFaults(f => ({ ...f, [camera.id]: e.target.value }))}>
            {source.data?.faults.map(fault => <option key={fault} value={fault}>{fault === "reference" ? "Original · no injected fault" : fault === "random" ? "Randomized fault mix" : fault}</option>)}
          </select></label>
          {snapshot?.image ? <img className="camera-replay-image" src={snapshot.image} alt={`${camera.label} analyzed frame at ${number(snapshot.evidence.pts_s)} seconds; ${snapshot.injection.kind}`} /> :
            <div className="camera-replay-empty">{ready ? "No analyzed frame at this time" : "Start replay to decode this source incrementally"}</div>}
          <div className="camera-health-pair">
            <section className={`camera-health-channel camera-state-${status}`} aria-label={`${camera.label} pipeline status`}>
              <h3>Pipeline</h3><strong>{status === "healthy" ? "On time" : status.replaceAll("_", " ")}</strong>
              <small>{snapshot?.delivery_conditions.join(", ") || "Delivery & processing"}</small>
            </section>
            <section className={`camera-health-channel camera-state-${quality}`} aria-label={`${camera.label} image status`}>
              <h3>Image</h3><strong>{quality === "suspected" ? "Check image" : quality === "no_issue_detected" ? "No flag detected" : "Unknown"}</strong>
              <small>{quality === "suspected" ? snapshot?.visual_conditions.join(", ") : quality === "unknown" ? "No fresh assessment" : "Unvalidated visual checks"}</small>
            </section>
          </div>
          <div className="camera-status-history" aria-label={`${camera.label} sampled status history`}>
            {(["pipeline_status", "quality_status"] as const).map(channel => <div className="camera-history-row" key={channel}>
              <span>{channel === "pipeline_status" ? "Pipeline" : "Image"}</span>
              <div className="camera-history-track" role="img" aria-label={`${channel === "pipeline_status" ? "Pipeline" : "Image"} history through ${number(shownTime, 1)} seconds; details in diagnostics`}>
                <div className="camera-history-elapsed" style={{ width: `${horizon ? shownTime / horizon * 100 : 0}%` }} />
                {samples.filter(sample => sample.time_s <= shownTime).map((sample, i) => {
                  const end = Math.min(samples[i + 1]?.time_s ?? shownTime, shownTime, sample.time_s + 1);
                  return <span key={sample.time_s} className={`camera-history-segment camera-state-${sample[channel]}`}
                    title={`${number(sample.time_s, 1)}–${number(end, 1)} s: ${sample[channel].replaceAll("_", " ")}`}
                    style={{ left: `${horizon ? sample.time_s / horizon * 100 : 0}%`, width: `${horizon ? Math.max(0, end - sample.time_s) / horizon * 100 : 0}%` }} />;
                })}
              </div>
            </div>)}
            <p className="camera-frame-caption">Green: on time / no flag · red: alarm / image flag · striped: unknown</p>
          </div>
          <p className="camera-frame-caption">{snapshot ? `Frame ${number(snapshot.evidence.pts_s, 2)} s · injection: ${snapshot.injection.kind}` : "Waiting for frames"}</p>
          {cameraErrors[camera.id] && <p role="alert" className="notice">{cameraErrors[camera.id]}</p>}
          <div className="camera-metric-plots">
            {plots.map(({ metric, series, max, reference }, chart) => {
              const points = series[ids.indexOf(camera.id)];
              const guide = chart === 0 && metrics[chart] === 1 ? ready?.sources.find(s => s.camera === camera.id)?.source_fps : reference;
              let path = "", previous: number | null = null;
              for (const point of points) {
                if (point.value == null) { previous = null; continue; }
                const x = 4 + point.time / (horizon || 1) * 292;
                const y = 76 - point.value / max * 68;
                path += `${previous == null || point.time - previous > 1 ? "M" : "L"}${x},${y} `;
                previous = point.time;
              }
              const latest = points.at(-1)?.value;
              return <figure className="camera-metric-plot" key={chart}>
                <figcaption><span>{metric.label}</span><strong>{number(latest)} <small>{metric.unit}</small></strong></figcaption>
                <svg tabIndex={0} viewBox="0 0 300 96" role="img" aria-label={`${camera.label} ${metric.label}; latest sampled ${number(latest)} ${metric.unit}; scale 0 to ${number(max)}; ${stale ? "stale" : busy ? "live" : "recorded"}`}>
                  <title>{metric.label}: 0–{number(max)} {metric.unit}. Report time 0–{number(horizon, 1)} s.{guide != null && ` Dashed reference: ${number(guide)} ${metric.unit}.`}</title>
                  <path className="camera-plot-axis" d="M4 8 V76 H296" />
                  {guide != null && <path className="camera-plot-limit" d={`M4 ${76 - guide / max * 68} H296`} />}
                  <path className="camera-plot-line" d={path} />
                  {points.map((point, i) => point.value == null ? null : <circle key={i} cx={4 + point.time / (horizon || 1) * 292} cy={76 - point.value / max * 68} r="2">
                    <title>{number(point.time, 2)} s: {number(point.value)} {metric.unit}</title>
                  </circle>)}
                  <text x="8" y="14">{number(max, 1)} {metric.unit}</text><text x="4" y="92">0 s</text><text x="296" y="92" textAnchor="end">{number(horizon, 1)} s</text>
                  {!points.some(p => p.value != null) && <text x="150" y="46" textAnchor="middle">No samples</text>}
                </svg>
              </figure>;
            })}
            {stale && <p className="camera-frame-caption">Updates stale · charts retain past samples</p>}
          </div>
          <div className="camera-region-map" aria-label={`${camera.label} regional ${regionMetric}`}>
            {Array.from({ length: 16 }, (_, i) => {
              const value = regions[i]?.[regionMetric];
              const label = `Tile ${Math.floor(i / 4) + 1},${i % 4 + 1}: ${value == null ? "unknown" : number(regionMetric === "clipped" ? value * 100 : value, 1)}${regionMetric === "clipped" ? "%" : ""}`;
              return <div key={i} tabIndex={0} aria-label={label} title={label} style={{ backgroundColor: value == null ? undefined : `color-mix(in srgb, var(--blue) ${Math.max(0, Math.min(100, value / regionMax * 100))}%, var(--surface))` }}><span>{i + 1}</span></div>;
            })}
          </div>
          <p className="camera-frame-caption">Region {regionMetric === "mean" ? "brightness" : regionMetric} · light 0 → dark {number(regionMetric === "clipped" ? 100 : regionMax, 1)}{regionMetric === "clipped" ? "%" : ""} · displayed frame</p>
          <details className="camera-diagnostics"><summary>Diagnostics & event log</summary>
          <p>Report {number(snapshot?.time_s, 3)} s · frame {snapshot?.evidence.frame ?? "—"} · injection at report: {snapshot?.injection.current ?? "none"} · displayed strength: {number(snapshot ? snapshot.injection.strength * 100 : null, 0)}%. Last visual flags: {snapshot?.visual_conditions.join(", ") || "none"}.</p>
          </details>
          {runMode !== "local" && <details><summary>Decisions · {snapshot?.review_pending ? "pending" : review?.status ?? "waiting"} · advisory</summary>
            <p>{snapshot?.review_pending ? `Pending at report time: frame PTS ${number(snapshot.review_pending.pts_s, 3)} s` : "No request pending at report time."}<br />Latest slot: {snapshot?.review_slot?.status ?? "waiting"} · attempts {snapshot?.review_attempts ?? 0}<br />Reported charges at report time: ${number(snapshot?.review_cost, 6)} {snapshot?.review_cost_complete ? "" : "(incomplete / pending)"}</p>
            {review && <><p>Latest returned review: {review.status} · frame PTS {number(review.pts_s, 3)} s · age {number(reviewAge)} s{reviewAge != null && reviewAge > (ready?.configuration.review_interval_s ?? 5) ? " · older than review interval" : ""}<br />Latency {number(review.latency_s)} s{review.error && ` · ${review.error}`}</p>
              {review.status === "ok" && <div className="camera-review-bars">{Object.entries(review.probabilities ?? {}).map(([kind, score]) => <label key={kind}>{kind} <meter min="0" max="1" value={score} /> {number(score * 100, 1)}%</label>)}</div>}</>}
            <p>Single-frame review cannot establish freeze or feed interruption. Scores are not calibrated safety probabilities.</p>
          </details>}
          <details><summary>Injection & detection timeline</summary>
          <p>Scheduled injections are not proof of detection. Open episodes have not cleared.</p>
          <div className="table-scroll"><table><thead><tr><th>Signal</th><th>Onset s</th><th>End / cleared s</th></tr></thead><tbody>
            {ready?.schedule[camera.id].map((event, i) => <tr key={`injection-${i}`}><td>Injection: {event.kind}{event.delay_ms != null && ` (${event.delay_ms} ms wait)`}{event.max_delay_ms != null && ` (0–${event.max_delay_ms} ms)`}{event.analysis_width_multiplier != null && ` (${event.analysis_width_multiplier}× width)`}</td><td>{number(event.start_s, 3)}</td><td>{number(event.end_s, 3)}</td></tr>)}
            {episodes.map((e, i) => <tr key={i}><td>{["interruption", "backlog"].includes(e.type) ? "Delivery alarm" : "Visual suspicion"}: {e.type}</td><td>{number(e.start_s, 3)}</td><td>{e.end_s == null ? "not cleared" : number(e.end_s, 3)}</td></tr>)}
            {!episodes.length && <tr><td colSpan={3}>No alarm or suspicion episodes by this report time.</td></tr>}
          </tbody></table></div>
          {profile && <section className="camera-final-report"><h3>Final camera report{profile.error ? " · failed" : ""}</h3>
            <p>{profile.error ?? `Processed ${profile.trace?.processed}/${profile.frames}; dropped ${profile.trace?.dropped}; interrupted ${profile.trace?.interrupted_frames}; rejected ${profile.trace?.rejected_frames}; unfinished ${profile.trace?.unfinished_frames}. Unknown ${number((profile.trace?.unknown_fraction ?? 1) * 100)}%; max age ${number(profile.trace?.max_age_s, 3)} s.`}</p>
            {runMode !== "local" && <>
              <p>Completed attempts: {finalReviews.filter(r => r.attempted).length} · covered slots: {finalReviews.filter(r => r.status === "ok").length}/{profile.trace?.review_required ?? 0}. Late/unavailable results do not count as covered.</p>
              <div className="table-scroll"><table><thead><tr><th>Reviewed PTS s</th><th>Outcome</th><th>Reported $</th></tr></thead><tbody>{finalReviews.map((r, i) => <tr key={i}><td>{number(r.pts_s, 3)}</td><td>{r.status}{r.late ? " · late" : ""}{r.error && <><br />{r.error}</>}</td><td>{r.attempted ? number(r.cost, 6) : "not attempted"}</td></tr>)}</tbody></table></div>
            </>}
          </section>}
          </details>
        </article>;
      })}
    </div>
    {result && <section><h2>Final measured evidence</h2>
      <p>Wall {number(result.measurement.wall_seconds)} s · CPU {number(result.measurement.cpu_seconds)} s · sampled previews, full traces in export.</p>
      <button type="button" onClick={() => { const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "three-camera-replay.json"; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }}>Download measured evidence JSON</button>
      <details><summary>Full runtime identity, configuration and traces</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>
    </section>}
  </section>;
}

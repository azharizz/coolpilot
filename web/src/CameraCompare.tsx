import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useResource } from "./api";
import { Icon, PageHead } from "./ui";

type CameraId = "left" | "centre" | "right";
type Mode = "local" | "scheduled" | "hybrid";
type Sources = {
  sources: { id: CameraId; label: string; video_url: string }[];
  faults: string[]; decision_configured: boolean; distribution: string; opencv_version: string;
};
type Verification = { status: "pending" | "done"; mode: string; requested_s: number; received_s?: number; tiles: number[];
  verdict?: "confirm" | "dismiss" | "escalate"; reason?: string; tool_calls?: string[] | null; summary?: { objects: string[] | null; engine: string | null } };
type Episode = { type: string; observation: string; start_s: number; end_s: number | null; verification?: Verification | null; dismissed?: boolean };
type Injection = { kind: string; start_s: number; end_s: number; delay_ms?: number; max_delay_ms?: number; analysis_width_multiplier?: number };
type Review = {
  status: string; pts_s?: number; requested_s?: number; received_s?: number;
  attempted?: boolean; probabilities?: Record<string, number>; cost?: number | null;
  error?: string; latency_s?: number; late?: boolean;
  expires_s?: number | null; valid_on_arrival?: boolean;
};
type Frame = {
  type: "frame"; camera: CameraId; time_s: number; pipeline_status: string; quality_status: string;
  delivery_conditions: string[]; visual_conditions: string[]; visual_observations: string[];
  image: string | null; evidence_age_s: number | null;
  evidence: { frame?: number; pts_s?: number; analysis_ms?: number; decode_ms?: number;
    compute_ms?: number; injected_delay_ms?: number; analysis_width?: number;
    black_fraction?: number; regions?: { mean: number; detail: number; clipped: number }[] };
  processed: number; delivered: number; dropped: number; interrupted: number; rejected: number; queue_depth: number; processed_fps: number;
  analysis_p95_ms: number | null; injection_p95_ms: number | null;
  injection: { kind: string; current: string; strength: number }; episodes: Episode[];
  review_pending: Review | null; review_slot: Review | null; review_result: Review | null; review_current: Review | null;
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
const number = (value: number | null | undefined, digits = 2) => value == null ? "n/a" : value.toFixed(digits);

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
  const [phase, setPhase] = useState("Ready. In local mode no image leaves this machine.");
  const [error, setError] = useState("");
  const [cameraErrors, setCameraErrors] = useState<Partial<Record<CameraId, string>>>({});
  const [ready, setReady] = useState<Ready>();
  const [result, setResult] = useState<Complete>();
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tick, setTick] = useState(Date.now());
  const [metrics, setMetrics] = useState([0, 0, 0]);
  const [regionMetric, setRegionMetric] = useState<"off" | "mean" | "detail" | "clipped">("detail");
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
    setCursor(0); setPlaying(false); setBusy(true); setPhase("Opening sources…");
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
          setReady(message); setPhase("Live. Previews and charts come from the same analyzed frames.");
        } else if (message.type === "frame") {
          if (!Array.isArray(message.visual_observations) ||
              !message.visual_observations.every(value => typeof value === "string") ||
              !Object.hasOwn(message, "review_current")) {
            throw new Error("Incompatible replay response. Restart the backend with the current code, then reload this page.");
          }
          history.current[message.camera].push(message);
          received.current[message.camera] = Date.now();
          setCursor(message.time_s); redraw(n => n + 1);
        } else if (message.type === "camera_error") {
          setCameraErrors(errors => ({ ...errors, [message.camera]: message.error }));
        } else if (message.type === "complete") {
          completed = true; setResult(message);
          setPhase(message.cancelled ? "Replay stopped. Retained evidence is historical." : "Replay complete. Scrub the timeline to inspect any moment.");
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
        setPhase("Stopped. Retained samples are partial.");
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
  const canStart = !busy && source.data && Number.isInteger(seed) && seed >= 0 && seed <= 2147483647 &&
    (mode === "local" || (consent && limit >= 1 && limit <= 10 && timeout >= 1 && timeout <= 20));
  const progress = horizon ? Math.min(100, shownTime / horizon * 100) : 0;
  return <section className="monitor">
    <PageHead title="Live replay" lead="Three forward views, one brief random fault each. Pipeline and image health are judged separately.">
      <span className={`sys-chip${distribution === "COOL" ? " is-cool" : ""}`}>
        <span className="sys-dot" aria-hidden="true" />
        {distribution ?? "Checking"} <b className="mono">{ready?.environment.opencv_version ?? source.data?.opencv_version ?? "n/a"}</b>
        {distribution === "COOL" ? " · speedup unverified" : " · COOL not on this host"}
      </span>
    </PageHead>
    {source.loading && !source.data && <div className="skeleton-rows" role="status" aria-label="Loading camera sources"><i /></div>}
    {source.error && <p className="notice" role="alert">{source.error}</p>}

    <div className={`deck panel${busy ? " is-live" : ""}`}>
      <div className="deck-primary">
        {busy
          ? <button type="button" className="btn btn-lg btn-danger" onClick={() => controller.current?.abort()}><Icon name="stop" /> Stop replay</button>
          : <button type="button" className="btn btn-lg btn-primary" onClick={start} disabled={!canStart}><Icon name="play" /> {mode === "local" ? "Start replay" : "Start replay and paid review"}</button>}
        <p className="deck-phase" role="status"><span className={`live-dot${busy ? "" : " is-idle"}`} aria-hidden="true" />{phase}</p>
      </div>
      <fieldset disabled={busy} className="deck-settings">
        <legend className="sr-only">Next replay</legend>
        <label className="field">Seed
          <span className="input-group">
            <input id="camera-replay-seed" type="number" min="0" max="2147483647" step="1" value={seed} onChange={e => setSeed(e.target.valueAsNumber)} />
            <button type="button" className="btn btn-icon" aria-label="New random seed" onClick={() => setSeed(Math.floor(Math.random() * 2147483648))}><Icon name="dice" /></button>
          </span>
        </label>
        <label className="field">Review
          <select value={mode} onChange={e => { setMode(e.target.value as Mode); setConsent(false); }}>
            <option value="local">Local only · no uploads</option>
            <option value="scheduled" disabled={!source.data?.decision_configured}>Scheduled Decisions review</option>
            <option value="hybrid" disabled={!source.data?.decision_configured}>Decisions on local suspicion</option>
          </select>
        </label>
        {mode !== "local" && <>
          <label className="field">Interval<select value={interval} onChange={e => setIntervalSeconds(Number(e.target.value))}>{[1, 2, 5].map(n => <option key={n} value={n}>{n} s</option>)}</select></label>
          <label className="field">Max / camera<input type="number" min="1" max="10" value={limit} onChange={e => setLimit(Number(e.target.value))} /></label>
          <label className="field">Deadline (s)<input type="number" min="1" max="20" value={timeout} onChange={e => setTimeoutSeconds(Number(e.target.value))} /></label>
          <label className="check deck-consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
            <span>Send up to {limit * 3} images for paid review through OpenRouter to OpenAI, with at most one HTTP 404 retry each. The provider may collect data; not zero retention. Scores never clear local alarms.</span></label>
        </>}
        {source.data && !source.data.decision_configured && <p className="hint">Decisions is not configured on the server. Local replay is available.</p>}
      </fieldset>
    </div>
    {error && <p className="notice" role="alert">{error}</p>}

    <div className="lens-bar">
      {metricGroups.map((group, i) => <label className="field" key={group.label}>{group.label}
        <select value={metrics[i]} onChange={e => setMetrics(values => values.map((value, j) => j === i ? Number(e.target.value) : value))}>
          {group.metrics.map((metric, j) => <option key={metric.label} value={j}>{metric.label}</option>)}
        </select>
      </label>)}
      <label className="field">Region overlay<select value={regionMetric} onChange={e => setRegionMetric(e.target.value as typeof regionMetric)}>
        <option value="detail">Detail variance</option><option value="mean">Brightness</option><option value="clipped">Clipped pixels</option><option value="off">Off</option>
      </select></label>
    </div>

    <div className="monitor-grid">
      {source.data?.sources.map((camera, ci) => {
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
        const reviewTime = busy ? (snapshot?.time_s ?? 0) + sinceReceipt : cursor;
        const reviewAge = review?.pts_s == null ? null : reviewTime - review.pts_s;
        const advice = snapshot?.review_current;
        const adviceValid = advice?.status === "ok" && advice.expires_s != null &&
          reviewTime < advice.expires_s && !cameraErrors[camera.id];
        const adviceStatus = advice?.status === "ok" && !adviceValid ? "expired" : advice?.status ?? "waiting";
        const runMode = ready?.configuration.mode ?? "local";
        const episodes = snapshot?.episodes ?? [];
        const finalReviews = profile?.trace?.reviews ?? [];
        const alarm = status === "degraded" || status === "unavailable" || quality === "suspected";
        const injecting = snapshot && snapshot.injection.current && !["none", "reference"].includes(snapshot.injection.current) ? snapshot.injection.current.replaceAll("_", " ") : null;
        return <article className={`cam${alarm ? " is-alarm" : ""}`} key={camera.id} style={{ "--i": ci } as CSSProperties}>
          <header className="cam-head">
            <h2><span className="hud-tag">{camera.id === "centre" ? "C" : camera.id[0].toUpperCase()}</span>{camera.label}</h2>
            <span className={`chip ${busy ? "chip-running" : snapshot ? "chip-completed" : "chip-idle"}`}>{busy ? "Live" : snapshot ? "Recorded" : "Ready"}</span>
          </header>
          <div className={`hud cam-frame${busy && !stale ? " is-live" : ""}`}>
            {snapshot?.image
              ? <img src={snapshot.image} alt={`${camera.label} analyzed frame at ${number(snapshot.evidence.pts_s)} seconds; ${snapshot.injection.kind}`} />
              : <div className="no-signal"><Icon name="target" size={28} /><span>{ready ? "No analyzed frame at this time" : "Awaiting replay"}</span></div>}
            {regionMetric !== "off" && regions.length > 0 && <div className="region-overlay" aria-hidden="true">
              {regions.map((r, i) => <i key={i} style={{ left: `${(i % 4) * 25}%`, top: `${Math.floor(i / 4) * 25}%`, width: "25%", height: "25%", "--v": Math.max(0, Math.min(1, r[regionMetric] / regionMax)) } as CSSProperties} />)}
            </div>}
            <div className="hud-status">
              <span className={`hud-pill tone-${status === "healthy" ? "ok" : status === "unknown" ? "unknown" : "alarm"}`}>Pipeline · {status === "healthy" ? "on time" : status.replaceAll("_", " ")}</span>
              <span className={`hud-pill tone-${quality === "no_issue_detected" ? "ok" : quality === "suspected" ? "alarm" : "unknown"}`}>Image · {quality === "suspected" ? "check" : quality === "no_issue_detected" ? "no flag" : "unknown"}</span>
            </div>
            <span className="hud-time mono">{snapshot ? `${number(snapshot.evidence.pts_s, 2)} s · f${snapshot.evidence.frame ?? "n/a"}` : "n/a"}</span>
            {injecting && <span className="hud-inject">Injected · {injecting}</span>}
          </div>

          <div className="cam-readout">
            <div className={`channel tone-${status === "healthy" ? "ok" : status === "unknown" ? "unknown" : "alarm"}`} aria-label={`${camera.label} pipeline status`}>
              <small>Pipeline</small><strong>{status === "healthy" ? "On time" : status.replaceAll("_", " ")}</strong>
              <span>{snapshot?.delivery_conditions.join(", ") || "Delivery and processing"}</span>
            </div>
            <div className={`channel tone-${quality === "no_issue_detected" ? "ok" : quality === "suspected" ? "alarm" : "unknown"}`} aria-label={`${camera.label} image status`}>
              <small>Image</small><strong>{quality === "suspected" ? "Check image" : quality === "no_issue_detected" ? "No flag" : "Unknown"}</strong>
              <span>{quality === "suspected" ? snapshot?.visual_observations.join(", ") : quality === "unknown" ? "No fresh assessment" : "Unvalidated visual checks"}</span>
            </div>
          </div>

          <label className="field field-compact">Next fault <select disabled={busy} value={faults[camera.id]} onChange={e => setFaults(f => ({ ...f, [camera.id]: e.target.value }))}>
            {source.data?.faults.map(fault => <option key={fault} value={fault}>{fault === "reference" ? "None (original)" : fault === "random" ? "Random mix" : fault.replaceAll("_", " ")}</option>)}
          </select></label>

          <div className="cam-tracks" aria-label={`${camera.label} sampled status history`}>
            {(["pipeline_status", "quality_status"] as const).map(channel => <div className="track" key={channel}>
              <span>{channel === "pipeline_status" ? "Pipeline" : "Image"}</span>
              <div className="track-lane" role="img" aria-label={`${channel === "pipeline_status" ? "Pipeline" : "Image"} history through ${number(shownTime, 1)} seconds`}>
                {samples.filter(sample => sample.time_s <= shownTime).map((sample, i) => {
                  const end = Math.min(samples[i + 1]?.time_s ?? shownTime, shownTime, sample.time_s + 1);
                  const value = sample[channel];
                  const tone = value === "healthy" || value === "no_issue_detected" ? "ok" : value === "unknown" ? "unknown" : "alarm";
                  return <i key={sample.time_s} className={`seg tone-${tone}`}
                    title={`${number(sample.time_s, 1)}–${number(end, 1)} s: ${value.replaceAll("_", " ")}`}
                    style={{ left: `${horizon ? sample.time_s / horizon * 100 : 0}%`, width: `${horizon ? Math.max(0, end - sample.time_s) / horizon * 100 : 0}%` }} />;
                })}
                {shownTime > 0 && <i className="playhead" style={{ left: `${progress}%` }} />}
              </div>
            </div>)}
          </div>

          {cameraErrors[camera.id] && <p role="alert" className="notice">{cameraErrors[camera.id]}</p>}
          <div className="plots">
            {plots.map(({ metric, series, max, reference }, chart) => {
              const points = series[ids.indexOf(camera.id)];
              const guide = chart === 0 && metrics[chart] === 1 ? ready?.sources.find(s => s.camera === camera.id)?.source_fps : reference;
              const x = (t: number) => 4 + t / (horizon || 1) * 292;
              const y = (v: number) => 76 - v / max * 64;
              let path = "", area = "", previous: number | null = null, last = 0;
              for (const point of points) {
                if (point.value == null) { if (previous != null) area += `L${last},76 Z `; previous = null; continue; }
                const px = x(point.time), py = y(point.value);
                if (previous == null || point.time - previous > 1) {
                  if (previous != null) area += `L${last},76 Z `;
                  path += `M${px},${py} `; area += `M${px},76 L${px},${py} `;
                } else { path += `L${px},${py} `; area += `L${px},${py} `; }
                previous = point.time; last = px;
              }
              if (previous != null) area += `L${last},76 Z`;
              const latest = points.at(-1)?.value;
              const gid = `g-${camera.id}-${chart}`;
              return <figure className="plot" key={chart}>
                <figcaption><span>{metric.label}</span><strong className="mono">{number(latest)} <small>{metric.unit}</small></strong></figcaption>
                <svg tabIndex={0} viewBox="0 0 300 92" role="img" aria-label={`${camera.label} ${metric.label}; latest sampled ${number(latest)} ${metric.unit}; scale 0 to ${number(max)}; ${stale ? "stale" : busy ? "live" : "recorded"}`}>
                  <title>{metric.label}: 0–{number(max)} {metric.unit}. Report time 0–{number(horizon, 1)} s.{guide != null && ` Dashed reference: ${number(guide)} ${metric.unit}.`}</title>
                  <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1"><stop offset="0" style={{ stopColor: "var(--blue)" }} stopOpacity="0.35" /><stop offset="1" style={{ stopColor: "var(--blue)" }} stopOpacity="0" /></linearGradient></defs>
                  <path className="plot-grid" d="M4 12 H296 M4 44 H296 M4 76 H296" />
                  {guide != null && <path className="plot-limit" d={`M4 ${y(guide)} H296`} />}
                  <path d={area} fill={`url(#${gid})`} />
                  <path className="plot-line" d={path} />
                  {points.map((point, i) => point.value == null ? null : <circle key={i} cx={x(point.time)} cy={y(point.value)} r="2">
                    <title>{number(point.time, 2)} s: {number(point.value)} {metric.unit}</title>
                  </circle>)}
                  {latest != null && <circle className="plot-head" cx={x(points.at(-1)!.time)} cy={y(latest)} r="3" />}
                  <text x="6" y="9">{number(max, 1)}</text><text x="4" y="90">0 s</text><text x="296" y="90" textAnchor="end">{number(horizon, 1)} s</text>
                  {!points.some(p => p.value != null) && <text className="plot-empty" x="150" y="48" textAnchor="middle">No samples</text>}
                </svg>
              </figure>;
            })}
            {stale && <p className="hint">Updates stale · charts keep past samples</p>}
          </div>

          <details className="disclosure"><summary>Diagnostics</summary>
            <p className="small">Report {number(snapshot?.time_s, 3)} s · frame {snapshot?.evidence.frame ?? "n/a"} · injection at report: {snapshot?.injection.current ?? "none"} ({number(snapshot ? snapshot.injection.strength * 100 : null, 0)}%). Observations: {snapshot?.visual_observations.join(", ") || "none"}. Suspected causes, not diagnoses: {snapshot?.visual_conditions.join(", ") || "none"}.</p>
          </details>
          {runMode !== "local" && <details className="disclosure"><summary>Decisions · {adviceStatus}{snapshot?.review_pending ? " · pending" : ""}</summary>
            <p className="small">{snapshot?.review_pending ? `Pending: frame PTS ${number(snapshot.review_pending.pts_s, 3)} s` : "No request pending."} Latest slot: {snapshot?.review_slot?.status ?? "waiting"} · attempts {snapshot?.review_attempts ?? 0} · charges ${number(snapshot?.review_cost, 6)}{snapshot?.review_cost_complete ? "" : " (incomplete)"}</p>
            {review && <><p className="small">Response: {review.status} · valid on arrival: {review.valid_on_arrival ? "yes" : "no"} · PTS {number(review.pts_s, 3)} s · source age {number(reviewAge)} s · expires {number(advice?.expires_s, 3)} s · latency {number(review.latency_s)} s{review.error && ` · ${review.error}`}</p>
              {adviceValid && <div className="meters">{Object.entries(advice?.probabilities ?? {}).map(([kind, score]) => <label key={kind}><span>{kind}</span><meter min="0" max="1" value={score} /><b className="mono">{number(score * 100, 1)}%</b></label>)}</div>}</>}
            <p className="hint">Advisory only. Advice expires with source age, cannot detect freeze or interruption, and scores are not calibrated probabilities.</p>
          </details>}
          <VerifyLog camera={camera.id} episodes={episodes} />
          <details className="disclosure"><summary>Injections and detections</summary>
            <div className="table-scroll"><table className="compact"><thead><tr><th>Signal</th><th>Onset s</th><th>End s</th></tr></thead><tbody>
              {ready?.schedule[camera.id].map((event, i) => <tr key={`injection-${i}`}><td><span className="fault-tag">{event.kind}</span>{event.delay_ms != null && ` ${event.delay_ms} ms`}{event.max_delay_ms != null && ` 0–${event.max_delay_ms} ms`}{event.analysis_width_multiplier != null && ` ${event.analysis_width_multiplier}× width`}</td><td className="mono">{number(event.start_s, 3)}</td><td className="mono">{number(event.end_s, 3)}</td></tr>)}
              {episodes.map((e, i) => <tr key={i}><td>{["interruption", "backlog"].includes(e.type) ? "Delivery alarm" : "Visual"}: {e.observation}{e.observation !== e.type && ` (possible ${e.type})`}</td><td className="mono">{number(e.start_s, 3)}</td><td className="mono">{e.end_s == null ? "open" : number(e.end_s, 3)}</td></tr>)}
              {!episodes.length && <tr><td colSpan={3} className="muted">No episodes yet.</td></tr>}
            </tbody></table></div>
            {profile && <div className="final-report"><h3>Final report{profile.error ? " · failed" : ""}</h3>
              {profile.error ? <p className="small">{profile.error}</p> : <dl className="mini-stats">
                <div><dt>Processed</dt><dd className="mono">{profile.trace?.processed}/{profile.frames}</dd></div>
                <div><dt>Dropped</dt><dd className="mono">{profile.trace?.dropped}</dd></div>
                <div><dt>Interrupted</dt><dd className="mono">{profile.trace?.interrupted_frames}</dd></div>
                <div><dt>Rejected</dt><dd className="mono">{profile.trace?.rejected_frames}</dd></div>
                <div><dt>Unfinished</dt><dd className="mono">{profile.trace?.unfinished_frames}</dd></div>
                <div><dt>Unknown</dt><dd className="mono">{number((profile.trace?.unknown_fraction ?? 1) * 100)}%</dd></div>
                <div><dt>Max age</dt><dd className="mono">{number(profile.trace?.max_age_s, 3)} s</dd></div>
              </dl>}
              {runMode !== "local" && <>
                <p className="small">Attempts {finalReviews.filter(r => r.attempted).length} · covered slots {finalReviews.filter(r => r.valid_on_arrival).length}/{profile.trace?.review_required ?? 0}. Late or expired results do not count.</p>
                <div className="table-scroll"><table className="compact"><thead><tr><th>PTS s</th><th>Outcome</th><th>$</th></tr></thead><tbody>{finalReviews.map((r, i) => <tr key={i}><td className="mono">{number(r.pts_s, 3)}</td><td>{r.status}{r.attempted && !r.valid_on_arrival ? " · not valid on arrival" : ""}{r.late ? " · late" : ""}{r.error && <><br />{r.error}</>}</td><td className="mono">{r.attempted ? number(r.cost, 6) : "n/a"}</td></tr>)}</tbody></table></div>
              </>}
            </div>}
          </details>
        </article>;
      })}
    </div>

    {(busy || liveTime > 0) && <div className="transport" role="group" aria-label="Replay timeline">
      <button type="button" className="btn btn-icon" disabled={busy} aria-label={playing ? "Pause recorded preview" : "Play recorded preview"}
        onClick={() => { if (cursor >= liveTime) setCursor(0); setPlaying(!playing); }}><Icon name={playing ? "pause" : "play"} /></button>
      <div className="scrub">
        <div className="scrub-marks" aria-hidden="true">
          {ready && ids.map((id, row) => ready.schedule[id].map((event, i) => <i key={`${id}-${i}`} className={`mark-${id}`}
            style={{ left: `${horizon ? event.start_s / horizon * 100 : 0}%`, width: `${horizon ? Math.max(0.4, (event.end_s - event.start_s) / horizon * 100) : 0}%`, top: `${row * 5}px` }} title={`${id}: ${event.kind}`} />))}
        </div>
        <input aria-label="Shared replay time" type="range" min="0" max={liveTime || 1} step="0.05" disabled={busy || !liveTime} value={shownTime}
          style={{ "--p": `${liveTime ? shownTime / Math.max(liveTime, 0.001) * 100 : 0}%` } as CSSProperties}
          onChange={e => { setPlaying(false); setCursor(Number(e.target.value)); }} />
      </div>
      <span className="mono transport-time">{shownTime.toFixed(2)} <small>/ {horizon.toFixed(2)} s</small></span>
    </div>}

    <details className="panel disclosure"><summary>Reading this monitor{ready && ` · seed ${ready.seed}`}</summary>
      <ul className="notes">
        <li>Previews use analyzed pixels at up to 10 Hz. Charts plot sampled reports; gaps are unknown.</li>
        <li>Seeds repeat injection schedules, not host timing. Synthetic waits are not COOL performance.</li>
        <li>Image flags are suspicions. Sky and scene changes can trigger glare or obstruction, and no flag does not prove usable imagery.</li>
        <li>Region overlay shows magnitude on the displayed frame, not safety.</li>
      </ul>
    </details>

    {result && <section className="panel result">
      <div className="evidence-head"><h2>Measured evidence</h2>
        <button type="button" className="btn btn-sm" onClick={() => { const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "three-camera-replay.json"; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }}><Icon name="download" size={16} /> Download JSON</button>
      </div>
      <dl className="stat-strip">
        <div><dt>Wall time</dt><dd className="mono">{number(result.measurement.wall_seconds)} s</dd></div>
        <div><dt>CPU time</dt><dd className="mono">{number(result.measurement.cpu_seconds)} s</dd></div>
        <div><dt>Seed</dt><dd className="mono">{result.seed}</dd></div>
        <div><dt>Status</dt><dd>{result.cancelled ? "Stopped early" : "Complete"}</dd></div>
      </dl>
      <details className="disclosure"><summary>Runtime identity, configuration and traces</summary><pre className="code">{JSON.stringify(result, null, 2)}</pre></details>
    </section>}
    <LiveCamera />
  </section>;
}

type LiveStatus = { type: "live"; elapsed_s: number; frames: number; reconnects: number; pipeline_status: string; quality_status: string; visual_observations: string[] };
type LiveResult = { type: "result"; frames: number; seconds: number; fps: number; reconnects: number; episodes: Episode[]; note: string };

// Operator-configured cameras only (COOLPILOT_LIVE_SOURCES). Hidden when the server lists none.
function LiveCamera() {
  const live = useResource<{ sources: string[] }>("/api/live", 60000);
  const [name, setName] = useState("");
  const [seconds, setSeconds] = useState(20);
  const [status, setStatus] = useState<LiveStatus>();
  const [result, setResult] = useState<LiveResult>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sources = live.data?.sources ?? [];
  if (!sources.length) return null;
  const chosen = name || sources[0];
  async function start() {
    setBusy(true); setError(""); setStatus(undefined); setResult(undefined);
    try {
      const response = await fetch("/api/live/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: chosen, seconds }) });
      if (!response.ok || !response.body) throw new Error((await response.json()).detail ?? "Live analysis refused.");
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
        for (const line of lines.filter(Boolean)) {
          const message = JSON.parse(line);
          if (message.type === "error") throw new Error(message.error);
          if (message.type === "live") setStatus(message);
          if (message.type === "result") setResult(message);
        }
        if (done) break;
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Live analysis failed.");
    } finally { setBusy(false); }
  }
  return <section className="panel">
    <h2>Live camera</h2>
    <p className="muted">Monitor only: a live feed has no labels, so recall and false alarms are not measured here.</p>
    <fieldset disabled={busy} className="deck-settings">
      <label className="field">Source
        <select value={chosen} onChange={e => setName(e.target.value)}>{sources.map(s => <option key={s}>{s}</option>)}</select>
      </label>
      <label className="field">Seconds
        <input type="number" min="1" max="120" value={seconds} onChange={e => setSeconds(e.target.valueAsNumber)} />
      </label>
      <button type="button" className="btn btn-primary" onClick={start} disabled={!(seconds > 0 && seconds <= 120)}><Icon name="play" /> Analyze live feed</button>
    </fieldset>
    {error && <p className="notice" role="alert">{error}</p>}
    {status && <p role="status" className="mono">{status.elapsed_s}s · {status.frames} frames · pipeline {status.pipeline_status} · image {status.quality_status}{status.visual_observations.length ? `: ${status.visual_observations.join(", ")}` : ""}{status.reconnects ? ` · ${status.reconnects} reconnects` : ""}</p>}
    {result && <p role="status">{result.frames} frames in {result.seconds}s ({result.fps} fps), {result.episodes.length} suspicion episodes. {result.note}</p>}
  </section>;
}


// Second stage: each obstruction suspicion is investigated (OpenCV tools, optionally the agent) before it alarms.
function VerifyLog({ camera, episodes }: { camera: string; episodes: Episode[] }) {
  const [human, setHuman] = useState<Record<string, "confirm" | "dismiss">>({});
  const checked = episodes.filter(e => e.verification);
  if (!checked.length) return null;
  return <div className="verify-log" aria-live="polite">
    <h3>Second-stage check</h3>
    <ol>{checked.map(e => {
      const v = e.verification!, key = `${camera}-${v.requested_s}`;
      const verdict = v.status === "pending" ? "verifying" : v.verdict;
      return <li key={key} className={`is-${verdict}`}>
        <p><b>Obstruction suspected</b> at {number(v.requested_s, 2)} s, tiles {v.tiles.join(", ")} · <span className="chip">{v.mode}</span>
          {" "}<b className="verify-verdict">{verdict}</b>{v.received_s != null && <span className="mono"> after {number(v.received_s - v.requested_s, 2)} s</span>}</p>
        {v.reason && <p className="small">{v.reason}</p>}
        {v.tool_calls && <p className="hint">Tools: {v.tool_calls.join(" → ")}{v.summary?.engine && ` · DNN engine: ${v.summary.engine}`}{v.summary?.objects && ` · road users: ${v.summary.objects.length ? v.summary.objects.join(", ") : "none"}`}</p>}
        {v.verdict === "escalate" && (human[key]
          ? <p className="small">Operator decision: <b>{human[key]}</b> (recorded in this browser session only).</p>
          : <p className="verify-actions">Operator review needed:
              <button type="button" className="btn" onClick={() => setHuman(h => ({ ...h, [key]: "confirm" }))}>Confirm alarm</button>
              <button type="button" className="btn" onClick={() => setHuman(h => ({ ...h, [key]: "dismiss" }))}>Dismiss</button></p>)}
      </li>;
    })}</ol>
  </div>;
}

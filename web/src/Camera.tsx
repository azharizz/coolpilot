import { useRef, useState, type FormEvent } from "react";
import { request, refresh, useResource } from "./api";
import type { CameraConfig, CameraExperiment, CameraRunData, CameraSettings, CameraStream, RunRequest, System } from "./types";
import { Notice, Status, number } from "./ui";

const baseline: CameraConfig = { width: 640, sample_every: 1, threads: 1, queue_size: 2, mode: "local", review_interval_s: 2 };
const proposedGoals: CameraSettings["goals"] = {
  faults: Object.fromEntries(["blur", "underexposure", "glare", "obstruction", "blackout", "freeze"].map(k => [k, { min_recall: 1, max_detection_s: 2, max_recovery_s: 2, min_events: 1 }])),
  max_false_alarms_per_hour: 0, min_normal_seconds: 30, max_age_s: 0.5,
  max_unknown_fraction: 0.1, max_api_failure_fraction: 0,
};

export function CameraForm({ system, busy, initial, onStart }: { system: System; busy: boolean; initial?: RunRequest; onStart: (id: string) => void }) {
  const datasets = system.camera_datasets ?? [];
  const [datasetId, setDatasetId] = useState(initial?.camera?.dataset ?? "oxford-development");
  const [error, setError] = useState("");
  const [acting, setActing] = useState(false);
  const dataset = datasets.find(d => d.id === datasetId);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || dataset.error) return;
    const data = new FormData(event.currentTarget);
    const num = (key: string) => Number(data.get(key));
    setError(""); setActing(true);
    try {
      const body: RunRequest = {
        workload: "camera_health", name: String(data.get("name")), strategy: String(data.get("strategy")) as RunRequest["strategy"],
        budget: num("budget"), repetitions: num("repetitions"), seed: num("seed"),
        hourly_price: data.get("price") ? num("price") : null,
        camera: {
          dataset: dataset.id, dataset_sha256: dataset.sha256,
          baseline: JSON.parse(String(data.get("baseline"))), goals: JSON.parse(String(data.get("goals"))),
          thresholds: JSON.parse(String(data.get("thresholds"))), scenarios: JSON.parse(String(data.get("scenarios"))),
          concurrent_streams: num("streams"), allow_image_requests: data.has("permission"),
          max_image_requests: num("requests"), api_timeout_s: num("timeout"),
          cool_hourly_price: data.get("softwarePrice") ? num("softwarePrice") : null,
        },
      };
      const result = await request<{id: string}>("/api/runs", body); onStart(result.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Invalid request."); }
    finally { setActing(false); }
  }
  return <section className="camera-workbench">
    <div className="page-heading"><h1>Camera-feed health</h1><p>Recorded replay, not vehicle control or camera repair. Optimize measured processing without accepting missed faults.</p></div>
    {error && <Notice>{error}</Notice>}
    <form onSubmit={submit}>
      <fieldset disabled={busy || acting}>
        <legend>Frozen experiment contract</legend>
        <label>Run name<input name="name" required maxLength={100} defaultValue={initial?.name ?? "Camera-health development"} /></label>
        <label>Recording set<select value={datasetId} onChange={e => setDatasetId(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id} disabled={!!d.error}>{d.id}{d.error ? " (unavailable)" : ""}</option>)}</select></label>
        {dataset?.error && <Notice>{dataset.error}</Notice>}
        {dataset && !dataset.error && <><p>{dataset.development_only ? "Development only. No independent validation; apply is disabled." : "Session-disjoint tuning and validation. Selection freezes before validation."}</p><p className="muted">Contract SHA-256: {dataset.sha256}</p>
          <ul>{dataset.clips.map(c => <li key={c.id}>{c.id} · {number(c.duration_s)} s · {c.split} · {c.session}</li>)}</ul></>}
        <div className="camera-fields">
          <label>Search<select name="strategy" defaultValue={initial?.strategy ?? "baseline"}><option value="baseline">Baseline only</option><option value="random">Seeded random</option><option value="agent" disabled={!system.agent.configured}>Nebius agent</option></select></label>
          <label>Candidate budget<input name="budget" type="number" min={1} max={30} defaultValue={initial?.budget ?? 3} required /></label>
          <label>Repetitions<input name="repetitions" type="number" min={1} max={10} defaultValue={initial?.repetitions ?? 1} required /></label>
          <label>Seed<input name="seed" type="number" min={0} max={2147483647} defaultValue={initial?.seed ?? 42} required /></label>
          <label>Concurrent replay streams<input name="streams" type="number" min={1} max={8} defaultValue={initial?.camera?.concurrent_streams ?? 1} required /></label>
          <label>Host USD/hour<input name="price" type="number" min={0.000001} step="any" defaultValue={initial?.hourly_price ?? ""} placeholder="Unknown" /></label>
          <label>COOL software USD/hour<input name="softwarePrice" type="number" min={0} step="any" defaultValue={initial?.camera?.cool_hourly_price ?? ""} placeholder="Unknown; enter 0 only if confirmed" /></label>
        </div>
        <label>Reference configuration (JSON)<textarea name="baseline" rows={8} defaultValue={JSON.stringify(initial?.camera?.baseline ?? baseline, null, 2)} required spellCheck={false} /></label>
        <p>Permitted search: width 320/640/960/1280, sample every 1/2/4, threads 1/2/4, bounded queue 1/2/4, local/scheduled/hybrid, review interval 1/2/5 seconds. Never changes thresholds, labels or delivery rate.</p>
        <label>Acceptance limits (JSON)<textarea name="goals" rows={14} defaultValue={JSON.stringify(initial?.camera?.goals ?? proposedGoals, null, 2)} required spellCheck={false} /></label>
        <p>These starting limits are unvalidated development examples, not safety standards. Edit per-fault limits and minimum evidence before running.</p>
        <label><input type="checkbox" required /> I reviewed and accept these limits for this experiment.</label>
        <details><summary>Calibration and delivery scenarios</summary>
          <label>Frozen threshold overrides (JSON)<textarea name="thresholds" rows={5} defaultValue={JSON.stringify(initial?.camera?.thresholds ?? {}, null, 2)} spellCheck={false} /></label>
          <p>Empty overrides use documented development defaults. Recalibrate only on development footage.</p>
          <label>Replay scenarios (JSON)<textarea name="scenarios" rows={7} defaultValue={JSON.stringify(initial?.camera?.scenarios ?? [], null, 2)} spellCheck={false} /></label>
          <p>Example: {JSON.stringify([{clip:"centre_reference", interruptions:[{start_s:4,end_s:8}], processing_delay_ms:200, processing_delay_interval:{start_s:10,end_s:14}}])}. Delivery pauses and processing load are separate from video effects.</p>
        </details>
        <details><summary>Optional image transmission</summary>
          <p>Local checks continue independently. Images go to the configured OpenRouter Decisions model, not the optimizer. Verify rights and provider privacy terms before enabling; unavailable responses stay unknown.</p>
          <label><input name="permission" type="checkbox" /> I authorize sending selected images for this run, including candidates and validation.</label>
          <label>Maximum requests per experiment (all clips, replicas and repetitions)<input name="requests" type="number" min={0} max={100} defaultValue={initial?.camera?.max_image_requests ?? 0} required /></label>
          <label>API timeout seconds<input name="timeout" type="number" min={0.1} max={30} step="any" defaultValue={initial?.camera?.api_timeout_s ?? 5} required /></label>
          <p>Maximum experiment count is candidate budget + baseline + up to two validation measurements. The optimizer uses its separate existing provider.</p>
        </details>
        <button className="button primary" disabled={!dataset || !!dataset.error}>{acting ? "Starting…" : "Run measured replay"}</button>
      </fieldset>
    </form>
  </section>;
}

export function CameraRun({identifier, busy, onEdit, openRun}: {identifier: string; busy: boolean; onEdit: (r: RunRequest) => void; openRun: (id: string) => void}) {
  const resource = useResource<CameraRunData>(`/api/runs/${identifier}`);
  const active = useResource<{experiment_id: number; previous_id: number | null} | null>("/api/active?workload=camera_health");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState(""); const [acting, setActing] = useState(false);
  const run = resource.data;
  async function action(url: string) {
    setActing(true); setError("");
    try { const result = await request<{id?: string}>(url, {}); refresh("/api/active", "/api/history", `/api/runs/${identifier}`); if (result.id) openRun(result.id); }
    catch (e) { setError(e instanceof Error ? e.message : "Action failed."); }
    finally { setActing(false); }
  }
  if (!run) return <Notice>{resource.error ?? "Loading camera evidence…"}</Notice>;
  const chosen = run.experiments.find(e => e.id === selected) ?? run.experiments.find(e => e.id === run.recommendation) ?? [...run.experiments].reverse().find(e => e.status === "completed");
  const running = ["queued", "running"].includes(run.status);
  return <section className="camera-workbench">
    <div className="page-heading"><h1>{run.request.name}</h1><Status value={run.status} /><p>{run.summary ?? "Measurements appear when each experiment completes."}</p></div>
    {(error || resource.error || run.error) && <Notice>{error || resource.error || run.error}</Notice>}
    <p>{run.recommendation ? "Held-out recommendation available. Apply changes this workload only." : "No held-out recommendation. Development footage cannot authorize apply."}</p>
    <div className="camera-actions">
      <a href={`/api/runs/${identifier}/export`}>Export full evidence</a>
      <button onClick={() => onEdit(run.request)}>Reuse contract</button>
      {running && <button disabled={acting} onClick={() => action(`/api/runs/${identifier}/cancel`)}>Cancel run</button>}
      <button disabled={busy || acting || !run.recommendation || active.data?.experiment_id === run.recommendation} onClick={() => { if (window.confirm("Apply this held-out validated camera-health configuration to the workbench? Physical cameras are unchanged.")) void action(`/api/experiments/${run.recommendation}/apply`); }}>Apply camera configuration</button>
      <button disabled={busy || acting || !active.data?.previous_id} onClick={() => { if (window.confirm("Restore the previous validated camera-health configuration?")) void action("/api/active/rollback?workload=camera_health"); }}>Rollback camera configuration</button>
      <button disabled={busy || acting || !active.data} onClick={() => action("/api/active/benchmark?workload=camera_health")}>Verify active configuration</button>
    </div>
    <div className="table-scroll"><table><thead><tr><th>Experiment</th><th>Gate</th><th>CPU s/camera s</th><th>Max arrival age</th><th>USD/camera h</th><th>Image requests</th></tr></thead><tbody>{run.experiments.map(e => <tr key={e.id}><td><button onClick={() => setSelected(e.id)}>#{e.id} {e.kind}</button><p>{e.status}</p></td><td>{e.gate ? e.gate.passed ? "Passed" : "Rejected" : "Not measured"}</td><td>{e.metrics ? number(e.metrics.cpu_seconds_per_camera_second, 4) : "—"}</td><td>{e.metrics ? `${number(e.metrics.max_age_s, 3)} s` : "—"}</td><td>{e.metrics?.cost_per_camera_hour == null ? "Unknown" : number(e.metrics.cost_per_camera_hour, 5)}</td><td>{e.metrics?.image_requests ?? "—"}</td></tr>)}</tbody></table></div>
    {chosen && <CameraEvidence key={chosen.id} experiment={chosen} dataset={run.request.camera!.dataset} />}
    <details><summary>Optimizer trace and usage</summary><pre>{JSON.stringify(run.events, null, 2)}</pre></details>
    <details><summary>Frozen request</summary><pre>{JSON.stringify(run.request, null, 2)}</pre></details>
  </section>;
}

function CameraEvidence({experiment, dataset}: {experiment: CameraExperiment; dataset: string}) {
  const detail = useResource<CameraExperiment>(`/api/experiments/${experiment.id}`, 0);
  const [streamIndex, setStreamIndex] = useState(0);
  const streams = detail.data?.trace?.streams ?? [];
  const stream = streams[streamIndex];
  const metrics = experiment.metrics;
  return <section><h2>Experiment #{experiment.id}</h2><p>{experiment.rationale}</p>
    {experiment.error && <Notice>{experiment.error}</Notice>}
    <pre>{JSON.stringify(experiment.config, null, 2)}</pre>
    {metrics && <><p>Analysis p95: {metrics.p95_ms == null ? "Unknown" : number(metrics.p95_ms)} ms · Peak process RSS: {number(metrics.peak_rss_mb)} MB · Timed replica count: {metrics.streams_tested}. This is not measured maximum fleet capacity.</p>
      <div className="table-scroll"><table><thead><tr><th>Clip / repetition / stream</th><th>Fault</th><th>Events / missed</th><th>Detection / recovery s</th><th>Premature or uncleared</th></tr></thead><tbody>{metrics.evaluations.flatMap(row => Object.entries(row.by_fault).map(([kind, v]) => <tr key={`${row.clip}-${row.repetition}-${row.stream}-${kind}`}><td>{row.clip} / {row.repetition + 1} / {row.stream + 1}</td><td>{kind}</td><td>{v.events} / {v.missed}</td><td>{v.detection_s == null ? "Missed" : number(v.detection_s)} / {v.recovery_s == null ? "Unresolved" : number(v.recovery_s)}</td><td>{v.bad_recovery}</td></tr>))}</tbody></table></div>
      <p>Normal-duration and false-alarm denominators, coverage and dropped frames:</p><pre>{JSON.stringify({repetitions: metrics.repetition_evidence, coverage: metrics.evaluations.map(e => ({clip: e.clip, repetition: e.repetition, stream: e.stream, unknown_fraction: e.unknown_fraction, dropped: e.dropped}))}, null, 2)}</pre>
    </>}
    {experiment.gate && <details open><summary>{experiment.gate.passed ? "All gates passed" : "Quality gate rejected"}</summary><ul>{experiment.gate.checks.map((c, i) => <li key={i}>{c.passed ? "Pass" : "Fail"}: {c.metric} — {c.actual == null ? "No evidence" : number(c.actual, 4)} {c.operator} {c.limit}</li>)}</ul></details>}
    {detail.error && <Notice>{detail.error}</Notice>}
    {streams.length > 0 && <><label>Evidence stream<select value={streamIndex} onChange={e => setStreamIndex(Number(e.target.value))}>{streams.map((s, i) => <option key={i} value={i}>{s.clip} / repetition {s.repetition + 1} / stream {s.stream + 1}</option>)}</select></label>{stream && <Playback key={streamIndex} stream={stream} dataset={dataset} />}</>}
  </section>;
}

function Playback({stream, dataset}: {stream: CameraStream; dataset: string}) {
  const video = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const state = [...(stream.transitions ?? [])].reverse().find(s => s.time_s <= time);
  const observed = [...(stream.observations ?? [])].reverse().find(s => s.analysis_s <= time);
  return <section>
    <h3>Recorded evidence playback</h3><p>{stream.session} · {stream.camera}. Video shows source PTS; status shows measured replay wall time. Not a live camera.</p>
    <video ref={video} controls preload="metadata" onTimeUpdate={e => setTime(e.currentTarget.currentTime)} src={`/api/camera/${encodeURIComponent(dataset)}/${encodeURIComponent(stream.clip)}/video`} aria-label="Recorded camera evidence" />
    <p role="status">{number(time)} s · Pipeline: {state?.pipeline_status ?? "Not recorded"} · Image: {state?.quality_status ?? "Not recorded"} · {state?.unknown !== false ? "Unknown evidence coverage" : "Evidence available"} · {state?.visual_observations?.join(", ") || "No observation description recorded"} · Queue age: {state ? `${number(state.queue_age_s, 3)} s` : "Unknown"}</p>
    {observed && <><p>Latest analyzed frame PTS {number(observed.pts_s, 3)} s, arrival-to-result age {number(observed.arrival_age_s, 3)} s. Excludes upstream capture/network delay.</p><div className="camera-regions" aria-label="Four by four image measurement regions">{observed.regions.map((r, i) => <div key={i} className={r.suspected_obstruction ? "region-suspect" : ""}>Region {i + 1}<br />Intensity {number(r.mean, 0)}<br />Detail {number(r.detail, 0)}<br />Clipped {number(r.clipped * 100, 0)}%{r.suspected_obstruction && <strong> Suspected loss</strong>}</div>)}</div></>}
    <div className="table-scroll"><table><thead><tr><th>Annotation (evaluator only)</th><th>Onset / recovery</th><th>Provenance / severity</th></tr></thead><tbody>{stream.truth.map((e, i) => <tr key={i}><td>{e.type}</td><td><button onClick={() => { if (video.current) video.current.currentTime = e.start_s; }}>{number(e.start_s)} s</button> / {number(e.end_s)} s</td><td>{e.provenance} / {e.severity ?? "Unspecified"}</td></tr>)}</tbody></table></div>
    <details><summary>Detected episodes and image decisions</summary><pre>{JSON.stringify({episodes: stream.episodes, reviews: stream.reviews}, null, 2)}</pre></details>
  </section>;
}

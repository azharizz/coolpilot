import { useRef, useState, type CSSProperties, type FormEvent } from "react";
import { request, refresh, useResource } from "./api";
import type { CameraConfig, CameraExperiment, CameraRunData, CameraSettings, CameraStream, RunRequest, System } from "./types";
import { Callout, Icon, Notice, PageHead, Status, number } from "./ui";

const baseline: CameraConfig = { width: 640, sample_every: 1, threads: 1, queue_size: 2, mode: "local", review_interval_s: 2 };
const proposedGoals: CameraSettings["goals"] = {
  faults: Object.fromEntries(["blur", "underexposure", "glare", "obstruction", "blackout", "freeze"].map(k => [k, { min_recall: 1, max_detection_s: 2, max_recovery_s: 2, min_events: 1 }])),
  max_false_alarms_per_hour: 0, min_normal_seconds: 30, max_age_s: 0.5,
  max_unknown_fraction: 0.1, max_api_failure_fraction: 0,
};

const configLabels: [keyof CameraConfig, string, string][] = [
  ["width", "Analysis width", "px"], ["sample_every", "Sample every", "frames"], ["threads", "Threads", ""],
  ["queue_size", "Queue", "frames"], ["mode", "Review mode", ""], ["review_interval_s", "Review interval", "s"],
];
export function ConfigGrid({ config }: { config: CameraConfig }) {
  return (
    <dl className="config-grid">
      {configLabels.map(([key, label, unit]) => (
        <div key={key}><dt>{label}</dt><dd><b className="mono">{String(config[key])}</b>{unit && <small> {unit}</small>}</dd></div>
      ))}
    </dl>
  );
}

const strategies = [
  { value: "baseline", title: "Baseline only", detail: "Measure the reference configuration." },
  { value: "random", title: "Seeded random", detail: "Sample the bounded search space." },
  { value: "agent", title: "Nebius agent", detail: "A model proposes each candidate." },
] as const;

export function CameraForm({ system, busy, initial, onStart }: { system: System; busy: boolean; initial?: RunRequest; onStart: (id: string) => void }) {
  const datasets = system.camera_datasets ?? [];
  const [datasetId, setDatasetId] = useState(initial?.camera?.dataset ?? "oxford-development");
  const [strategy, setStrategy] = useState<string>(initial?.strategy ?? "baseline");
  const [budget, setBudget] = useState(initial?.budget ?? 3);
  const [error, setError] = useState("");
  const [acting, setActing] = useState(false);
  const dataset = datasets.find(d => d.id === datasetId);
  const longest = Math.max(1, ...(dataset?.clips.map(c => c.duration_s) ?? []));
  const total = dataset?.clips.reduce((sum, c) => sum + c.duration_s, 0) ?? 0;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || dataset.error) return;
    const data = new FormData(event.currentTarget);
    const num = (key: string) => Number(data.get(key));
    setError(""); setActing(true);
    try {
      const body: RunRequest = {
        workload: "camera_health", name: String(data.get("name")), strategy: strategy as RunRequest["strategy"],
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
      const result = await request<{ id: string }>("/api/runs", body); onStart(result.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Invalid request."); }
    finally { setActing(false); }
  }
  return (
    <section className="validate">
      <PageHead title="Validate a configuration" lead="Freeze the contract, then measure. Gates never move after the run starts." />
      {error && <Notice>{error}</Notice>}
      {system.readonly && <Callout>This serverless deployment replays and inspects saved evidence. Validation runs need an always-on server, so the form is read-only here. Live replay and History work normally.</Callout>}
      <form onSubmit={submit} className="validate-form">
        <fieldset disabled={busy || acting || !!system.readonly} className="validate-main">
          <section className="panel step">
            <h2><span className="step-n">1</span> Recordings</h2>
            <div className="field-row">
              <label className="field">Run name<input name="name" required maxLength={100} defaultValue={initial?.name ?? "Camera-health development"} /></label>
              <label className="field">Recording set
                <select value={datasetId} onChange={e => setDatasetId(e.target.value)}>
                  {datasets.map(d => <option key={d.id} value={d.id} disabled={!!d.error}>{d.id}{d.error ? " (unavailable)" : ""}</option>)}
                </select>
              </label>
            </div>
            {dataset?.error && <Notice>{dataset.error}</Notice>}
            {dataset && !dataset.error && (
              <>
                <ul className="clip-bars" aria-label="Clips in this recording set">
                  {dataset.clips.map((c, i) => (
                    <li key={c.id} style={{ "--w": c.duration_s / longest, "--i": i } as CSSProperties}>
                      <span className="clip-name" title={`${c.camera} · ${c.session}`}>{c.id.replaceAll("_", " ")} <small>{c.split.replaceAll("_", " ")}</small></span>
                      <span className="clip-track"><i className={`split-${c.split}`} /></span>
                      <span className="mono clip-dur">{number(c.duration_s)} s</span>
                    </li>
                  ))}
                </ul>
                <p className="hint">
                  <span className={`chip ${dataset.development_only ? "chip-interrupted" : "chip-completed"}`}>{dataset.development_only ? "Development only" : "Held-out split"}</span>
                  {dataset.development_only ? "No independent validation, so apply stays disabled." : "Selection freezes before validation sessions run."}
                </p>
              </>
            )}
          </section>

          <section className="panel step">
            <h2><span className="step-n">2</span> Search</h2>
            <div className="choice-grid" role="radiogroup" aria-label="Search strategy">
              {strategies.map(s => {
                const off = s.value === "agent" && !system.agent.configured;
                return (
                  <label key={s.value} className={`choice${off ? " is-off" : ""}`}>
                    <input type="radio" name="strategy" value={s.value} checked={strategy === s.value} disabled={off} onChange={() => setStrategy(s.value)} />
                    <strong>{s.title}</strong>
                    <span>{off ? "Not configured on this server." : s.detail}</span>
                  </label>
                );
              })}
            </div>
            <div className="field-grid">
              <label className="field">Candidate budget<input name="budget" type="number" min={1} max={30} value={budget} onChange={e => setBudget(e.target.valueAsNumber)} required /></label>
              <label className="field">Repetitions<input name="repetitions" type="number" min={1} max={10} defaultValue={initial?.repetitions ?? 1} required /></label>
              <label className="field">Seed<input name="seed" type="number" min={0} max={2147483647} defaultValue={initial?.seed ?? 42} required /></label>
              <label className="field">Replay streams<input name="streams" type="number" min={1} max={8} defaultValue={initial?.camera?.concurrent_streams ?? 1} required /></label>
              <label className="field">Host USD / hour<input name="price" type="number" min={0.000001} step="any" defaultValue={initial?.hourly_price ?? ""} placeholder="Unknown" /></label>
              <label className="field">COOL USD / hour<input name="softwarePrice" type="number" min={0} step="any" defaultValue={initial?.camera?.cool_hourly_price ?? ""} placeholder="Unknown" /></label>
            </div>
            <p className="hint">Search space: width 320 to 1280, sampling 1/2/4, threads 1/2/4, queue 1/2/4, review mode and interval. Thresholds, labels and delivery rate never change.</p>
          </section>

          <section className="panel step">
            <h2><span className="step-n">3</span> Acceptance limits</h2>
            <div className="code-pair">
              <label className="field">Reference configuration
                <textarea className="code" name="baseline" rows={9} defaultValue={JSON.stringify(initial?.camera?.baseline ?? baseline, null, 2)} required spellCheck={false} />
              </label>
              <label className="field">Gates
                <textarea className="code" name="goals" rows={9} defaultValue={JSON.stringify(initial?.camera?.goals ?? proposedGoals, null, 2)} required spellCheck={false} />
              </label>
            </div>
            <label className="check"><input type="checkbox" required /> <span>I reviewed these limits. They are development examples, not safety standards.</span></label>
          </section>

          <details className="panel disclosure">
            <summary>Calibration and delivery scenarios</summary>
            <label className="field">Threshold overrides
              <textarea className="code" name="thresholds" rows={5} defaultValue={JSON.stringify(initial?.camera?.thresholds ?? {}, null, 2)} spellCheck={false} />
            </label>
            <label className="field">Replay scenarios
              <textarea className="code" name="scenarios" rows={6} defaultValue={JSON.stringify(initial?.camera?.scenarios ?? [], null, 2)} spellCheck={false} />
            </label>
            <p className="hint">Empty overrides use development defaults. Example scenario: <code>{JSON.stringify({ clip: "centre_reference", interruptions: [{ start_s: 4, end_s: 8 }], processing_delay_ms: 200 })}</code></p>
          </details>

          <details className="panel disclosure">
            <summary>Image upload for remote review</summary>
            <p className="hint">Local checks always run. Selected images go to the configured OpenRouter Decisions model. Check rights and provider privacy terms first.</p>
            <label className="check"><input name="permission" type="checkbox" /> <span>Send selected images for this run, including candidates and validation.</span></label>
            <div className="field-row">
              <label className="field">Max requests per experiment<input name="requests" type="number" min={0} max={100} defaultValue={initial?.camera?.max_image_requests ?? 0} required /></label>
              <label className="field">Timeout (s)<input name="timeout" type="number" min={0.1} max={30} step="any" defaultValue={initial?.camera?.api_timeout_s ?? 5} required /></label>
            </div>
          </details>
        </fieldset>

        <aside className="panel summary" aria-label="Run summary">
          <h2>Contract</h2>
          <dl>
            <div><dt>Recordings</dt><dd>{dataset ? `${dataset.clips.length} clips · ${number(total, 0)} s` : "None"}</dd></div>
            <div><dt>Strategy</dt><dd>{strategies.find(s => s.value === strategy)?.title}</dd></div>
            <div><dt>Max experiments</dt><dd className="mono">{Number.isFinite(budget) ? budget + 3 : "—"}</dd></div>
            <div><dt>Apply</dt><dd>{dataset?.development_only ? "Disabled" : "After held-out pass"}</dd></div>
          </dl>
          {dataset?.sha256 && <code className="hash" title="Contract SHA-256">{dataset.sha256.slice(0, 16)}…</code>}
          <button className="btn btn-primary btn-lg btn-block" disabled={busy || acting || !!system.readonly || !dataset || !!dataset.error}>
            {acting ? <><span className="spinner" aria-hidden="true" /> Starting…</> : <><Icon name="play" /> Run measured replay</>}
          </button>
          {busy && <p className="hint">Another run is in progress.</p>}
        </aside>
      </form>
    </section>
  );
}

export function CameraRun({ identifier, busy, readonly, onEdit, openRun }: { identifier: string; busy: boolean; readonly?: boolean; onEdit: (r: RunRequest) => void; openRun: (id: string) => void }) {
  const resource = useResource<CameraRunData>(`/api/runs/${identifier}`);
  const active = useResource<{ experiment_id: number; previous_id: number | null } | null>("/api/active?workload=camera_health");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState(""); const [acting, setActing] = useState(false);
  const run = resource.data;
  async function action(url: string) {
    setActing(true); setError("");
    try { const result = await request<{ id?: string }>(url, {}); refresh("/api/active", "/api/history", `/api/runs/${identifier}`); if (result.id) openRun(result.id); }
    catch (e) { setError(e instanceof Error ? e.message : "Action failed."); }
    finally { setActing(false); }
  }
  if (!run) return resource.error ? <Notice>{resource.error}</Notice> : <div className="skeleton-rows" role="status" aria-label="Loading run"><i /><i /><i /></div>;
  const chosen = run.experiments.find(e => e.id === selected) ?? run.experiments.find(e => e.id === run.recommendation) ?? [...run.experiments].reverse().find(e => e.status === "completed");
  const running = ["queued", "running"].includes(run.status);
  const maxCpu = Math.max(1e-9, ...run.experiments.map(e => e.metrics?.cpu_seconds_per_camera_second ?? 0));
  return (
    <section className="run">
      <a className="back" href="#/history"><Icon name="back" size={16} /> History</a>
      <PageHead title={<>{run.request.name} <Status value={run.status} /></>} lead={run.summary ?? "Measurements appear as each experiment completes."} />
      {(error || resource.error || run.error) && <Notice>{error || resource.error || run.error}</Notice>}

      <div className={`verdict ${run.recommendation ? "is-go" : "is-hold"}`}>
        <Icon name={run.recommendation ? "check" : "shield"} size={22} />
        <div>
          <strong>{run.recommendation ? `Experiment #${run.recommendation} passed held-out validation` : "No held-out recommendation"}</strong>
          <span>{run.recommendation ? "Apply changes this workbench setting only." : "Development footage cannot authorize apply."}</span>
        </div>
        {running && <span className="live-dot" aria-label="Running" />}
      </div>

      <div className="action-bar">
        <a className="btn btn-sm" href={`/api/runs/${identifier}/export`}><Icon name="download" size={16} /> Export evidence</a>
        <button className="btn btn-sm" onClick={() => onEdit(run.request)}><Icon name="copy" size={16} /> Reuse contract</button>
        {running && <button className="btn btn-sm btn-danger" disabled={acting || readonly} onClick={() => action(`/api/runs/${identifier}/cancel`)}><Icon name="stop" size={16} /> Cancel</button>}
        <span className="action-sep" />
        <button className="btn btn-sm" disabled={busy || acting || readonly || !run.recommendation || active.data?.experiment_id === run.recommendation}
          onClick={() => { if (window.confirm("Apply this held-out validated camera-health configuration to the workbench? Physical cameras are unchanged.")) void action(`/api/experiments/${run.recommendation}/apply`); }}>
          <Icon name="check" size={16} /> Apply
        </button>
        <button className="btn btn-sm" disabled={busy || acting || readonly || !active.data?.previous_id}
          onClick={() => { if (window.confirm("Restore the previous validated camera-health configuration?")) void action("/api/active/rollback?workload=camera_health"); }}>
          <Icon name="undo" size={16} /> Rollback
        </button>
        <button className="btn btn-sm" disabled={busy || acting || readonly || !active.data} onClick={() => action("/api/active/benchmark?workload=camera_health")}>
          <Icon name="target" size={16} /> Verify active
        </button>
      </div>

      <section className="panel">
        <h2>Experiments</h2>
        <div className="table-scroll">
          <table className="board">
            <thead><tr><th>Experiment</th><th>Gate</th><th>CPU s / camera s</th><th>Max arrival age</th><th>USD / camera h</th><th>Image requests</th></tr></thead>
            <tbody>
              {run.experiments.map((e, i) => (
                <tr key={e.id} className={chosen?.id === e.id ? "is-selected" : undefined} style={{ "--i": i } as CSSProperties}>
                  <th scope="row">
                    <button className="row-button" onClick={() => setSelected(e.id)} aria-pressed={chosen?.id === e.id}>
                      <b className="mono">#{e.id}</b> {e.kind}
                    </button>
                    <small>{e.status}</small>
                  </th>
                  <td>{e.gate ? <span className={`chip ${e.gate.passed ? "chip-passed" : "chip-rejected"}`}>{e.gate.passed ? "Passed" : "Rejected"}</span> : <span className="muted">Not measured</span>}</td>
                  <td>
                    {e.metrics ? (
                      <span className="bar-cell">
                        <span className="bar"><i style={{ "--w": e.metrics.cpu_seconds_per_camera_second / maxCpu } as CSSProperties} /></span>
                        <span className="mono">{number(e.metrics.cpu_seconds_per_camera_second, 4)}</span>
                      </span>
                    ) : "—"}
                  </td>
                  <td className="mono">{e.metrics ? `${number(e.metrics.max_age_s, 3)} s` : "—"}</td>
                  <td className="mono">{e.metrics?.cost_per_camera_hour == null ? "Unknown" : number(e.metrics.cost_per_camera_hour, 5)}</td>
                  <td className="mono">{e.metrics?.image_requests ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!run.experiments.length && <p className="muted">Waiting for the first experiment…</p>}
      </section>

      {chosen && <CameraEvidence key={chosen.id} experiment={chosen} dataset={run.request.camera!.dataset} />}

      <details className="panel disclosure"><summary>Optimizer trace and usage</summary><pre className="code">{JSON.stringify(run.events, null, 2)}</pre></details>
      <details className="panel disclosure"><summary>Frozen request</summary><pre className="code">{JSON.stringify(run.request, null, 2)}</pre></details>
    </section>
  );
}

function CameraEvidence({ experiment, dataset }: { experiment: CameraExperiment; dataset: string }) {
  const detail = useResource<CameraExperiment>(`/api/experiments/${experiment.id}`, 0);
  const [streamIndex, setStreamIndex] = useState(0);
  const streams = detail.data?.trace?.streams ?? [];
  const stream = streams[streamIndex];
  const metrics = experiment.metrics;
  return (
    <section className="panel evidence">
      <div className="evidence-head">
        <h2>Experiment <span className="mono">#{experiment.id}</span> <small>{experiment.kind}</small></h2>
        {experiment.gate && <span className={`chip ${experiment.gate.passed ? "chip-passed" : "chip-rejected"}`}>{experiment.gate.passed ? "All gates passed" : "Gate rejected"}</span>}
      </div>
      {experiment.rationale && <p className="muted">{experiment.rationale}</p>}
      {experiment.error && <Notice>{experiment.error}</Notice>}
      <ConfigGrid config={experiment.config} />

      {metrics && (
        <dl className="stat-strip">
          <div><dt>Analysis p95</dt><dd className="mono">{metrics.p95_ms == null ? "Unknown" : `${number(metrics.p95_ms)} ms`}</dd></div>
          <div><dt>Peak RSS</dt><dd className="mono">{number(metrics.peak_rss_mb)} MB</dd></div>
          <div><dt>Timed replicas</dt><dd className="mono">{metrics.streams_tested}</dd></div>
          <div><dt>Wall time</dt><dd className="mono">{number(metrics.wall_seconds)} s</dd></div>
        </dl>
      )}

      {experiment.gate && (() => {
        const checks = [...experiment.gate.checks].sort((a, b) => Number(a.passed) - Number(b.passed));
        const passed = checks.filter(c => c.passed).length;
        return <>
        <div className="gate-meter">
          <span><b className="mono">{passed}</b> of <b className="mono">{checks.length}</b> checks passed{passed < checks.length && ", failures first"}</span>
          <span className="gate-bar" aria-hidden="true">{checks.map((c, i) => <i key={i} className={c.passed ? "is-pass" : "is-fail"} style={{ "--i": i } as CSSProperties} />)}</span>
        </div>
        <ul className="gates" aria-label="Gate checks">
          {checks.map((c, i) => (
            <li key={i} className={c.passed ? "is-pass" : "is-fail"} style={{ "--i": i } as CSSProperties}>
              <Icon name={c.passed ? "check" : "close"} size={16} />
              <span>{c.metric.replaceAll("_", " ")}</span>
              <span className="mono">{c.actual == null ? "No evidence" : number(c.actual, 4)} <em>{c.operator}</em> {c.limit}</span>
            </li>
          ))}
        </ul>
        </>;
      })()}

      {metrics && (
        <>
          <h3>Per-fault results</h3>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Clip / rep / stream</th><th>Fault</th><th>Events / missed</th><th>Detect / recover (s)</th><th>Premature or uncleared</th></tr></thead>
              <tbody>
                {metrics.evaluations.flatMap(row => Object.entries(row.by_fault).map(([kind, v]) => (
                  <tr key={`${row.clip}-${row.repetition}-${row.stream}-${kind}`}>
                    <td>{row.clip} <span className="muted">/ {row.repetition + 1} / {row.stream + 1}</span></td>
                    <td><span className={`fault-tag${v.missed ? " is-missed" : ""}`}>{kind}</span></td>
                    <td className="mono">{v.events} / {v.missed}</td>
                    <td className="mono">{v.detection_s == null ? "Missed" : number(v.detection_s)} / {v.recovery_s == null ? "Unresolved" : number(v.recovery_s)}</td>
                    <td className="mono">{v.bad_recovery}</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
          <details className="disclosure"><summary>Coverage, dropped frames and false-alarm denominators</summary>
            <pre className="code">{JSON.stringify({ repetitions: metrics.repetition_evidence, coverage: metrics.evaluations.map(e => ({ clip: e.clip, repetition: e.repetition, stream: e.stream, unknown_fraction: e.unknown_fraction, dropped: e.dropped })) }, null, 2)}</pre>
          </details>
        </>
      )}

      {detail.error && <Notice>{detail.error}</Notice>}
      {streams.length > 0 && (
        <>
          <div className="evidence-head">
            <h3>Recorded playback</h3>
            <label className="field field-inline">Stream
              <select value={streamIndex} onChange={e => setStreamIndex(Number(e.target.value))}>
                {streams.map((s, i) => <option key={i} value={i}>{s.clip} / rep {s.repetition + 1} / stream {s.stream + 1}</option>)}
              </select>
            </label>
          </div>
          {stream && <Playback key={streamIndex} stream={stream} dataset={dataset} />}
        </>
      )}
    </section>
  );
}

const pipelineTone = (s?: string) => s === "healthy" ? "ok" : s ? "alarm" : "unknown";
const imageTone = (s?: string) => s === "no_issue_detected" ? "ok" : s === "suspected" ? "alarm" : "unknown";

function Playback({ stream, dataset }: { stream: CameraStream; dataset: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [aspect, setAspect] = useState(4 / 3);
  const [overlay, setOverlay] = useState(true);
  const transitions = stream.transitions ?? [];
  const state = [...transitions].reverse().find(s => s.time_s <= time);
  const observed = [...(stream.observations ?? [])].reverse().find(s => s.analysis_s <= time);
  const span = duration || Math.max(1, ...stream.truth.map(t => t.end_s), ...stream.episodes.map(e => e.end_s ?? e.start_s));
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / span) * 100))}%`;
  const seek = (t: number) => { if (video.current) video.current.currentTime = t; };
  const maxDetail = Math.max(1, ...(observed?.regions.map(r => r.detail) ?? []));
  const segments = (key: "pipeline_status" | "quality_status", tone: (s?: string) => string) =>
    transitions.map((t, i) => {
      const end = transitions[i + 1]?.time_s ?? span;
      return <i key={i} className={`seg tone-${t.unknown ? "unknown" : tone(t[key])}`} style={{ left: pct(t.time_s), width: pct(end - t.time_s) }}
        title={`${number(t.time_s)}–${number(end)} s: ${t.unknown ? "unknown" : (t[key] ?? "not recorded").replaceAll("_", " ")}`} />;
    });
  return (
    <div className="playback">
      <div className="hud hud-lg" style={{ aspectRatio: String(aspect) }}>
        <video ref={video} controls preload="metadata"
          onLoadedMetadata={e => { setDuration(e.currentTarget.duration || 0); if (e.currentTarget.videoWidth) setAspect(e.currentTarget.videoWidth / e.currentTarget.videoHeight); }}
          onTimeUpdate={e => setTime(e.currentTarget.currentTime)}
          src={`/api/camera/${encodeURIComponent(dataset)}/${encodeURIComponent(stream.clip)}/video`} aria-label="Recorded camera evidence" />
        {overlay && observed && (
          <div className="region-overlay" aria-hidden="true">
            {observed.regions.map((r, i) => (
              <i key={i} className={r.suspected_obstruction ? "is-suspect" : undefined}
                style={{ left: `${r.box[0] * 100}%`, top: `${r.box[1] * 100}%`, width: `${r.box[2] * 100}%`, height: `${r.box[3] * 100}%`, "--v": r.detail / maxDetail } as CSSProperties} />
            ))}
          </div>
        )}
        <div className="hud-status">
          <span className={`hud-pill tone-${state?.unknown ? "unknown" : pipelineTone(state?.pipeline_status)}`}>Pipeline · {state?.pipeline_status?.replaceAll("_", " ") ?? "not recorded"}</span>
          <span className={`hud-pill tone-${state?.unknown ? "unknown" : imageTone(state?.quality_status)}`}>Image · {state?.quality_status?.replaceAll("_", " ") ?? "not recorded"}</span>
        </div>
        <span className="hud-time mono">{number(time, 2)} s</span>
      </div>

      <p className="readout" role="status">
        <span>{stream.session} · {stream.camera}</span>
        <span>Queue age <b className="mono">{state ? `${number(state.queue_age_s, 3)} s` : "Unknown"}</b></span>
        <span>Arrival age <b className="mono">{observed ? `${number(observed.arrival_age_s, 3)} s` : "Unknown"}</b></span>
        <span>{state?.visual_observations?.join(", ") || "No observation"}</span>
        <label className="check check-inline"><input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} /> <span>Region detail overlay</span></label>
      </p>

      <div className="tracks" aria-label="Evidence timeline">
        <div className="track"><span>Annotated</span><div className="track-lane">
          {stream.truth.map((e, i) => (
            <button key={i} className="seg seg-truth" style={{ left: pct(e.start_s), width: pct(e.end_s - e.start_s) }}
              onClick={() => seek(e.start_s)} aria-label={`Seek to ${e.type} at ${number(e.start_s)} seconds (${e.provenance})`} title={`${e.type} · ${e.provenance} · ${e.severity ?? "unspecified"}`} />
          ))}
          <i className="playhead" style={{ left: pct(time) }} />
        </div></div>
        <div className="track"><span>Detected</span><div className="track-lane">
          {stream.episodes.map((e, i) => (
            <i key={i} className="seg seg-detect" style={{ left: pct(e.start_s), width: pct((e.end_s ?? span) - e.start_s) }} title={`${e.type}: ${number(e.start_s)}–${e.end_s == null ? "open" : number(e.end_s)} s`} />
          ))}
          <i className="playhead" style={{ left: pct(time) }} />
        </div></div>
        <div className="track"><span>Pipeline</span><div className="track-lane">{segments("pipeline_status", pipelineTone)}<i className="playhead" style={{ left: pct(time) }} /></div></div>
        <div className="track"><span>Image</span><div className="track-lane">{segments("quality_status", imageTone)}<i className="playhead" style={{ left: pct(time) }} /></div></div>
      </div>
      <p className="hint">Video shows source time; status shows measured replay time. Annotations are for scoring only; click one to jump there.</p>

      <details className="disclosure"><summary>Detected episodes and image decisions</summary><pre className="code">{JSON.stringify({ episodes: stream.episodes, reviews: stream.reviews }, null, 2)}</pre></details>
    </div>
  );
}

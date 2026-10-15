import { useResource } from "./api";
import type { CameraConfig, System } from "./types";
import { Notice } from "./ui";

export function Runtime({ system, openRun }: { system: System; openRun: (id: string) => void }) {
  const camera = useResource<{experiment: {run_id: string; config: CameraConfig}} | null>("/api/active");
  return <>
    <div className="page-heading"><div><h1>Camera-health runtime</h1><p>The actual engine behind local analysis and recorded validation.</p></div></div>
    <div className="runtime-layout">
      <section>
        <h2>Execution environment</h2>
        <dl className="fact-list">
          <div><dt>Platform</dt><dd>{system.runtime.system} / {system.runtime.architecture} · {system.runtime.cpu_count} CPUs</dd></div>
          <div><dt>Vision engine</dt><dd>{system.runtime.distribution} {system.runtime.opencv_version}</dd></div>
          <div><dt>COOL runtime</dt><dd>{system.cool.available ? "Vendor module detected; performance unverified" : "Not installed on this host"}</dd></div>
          <div><dt>Experiment planner</dt><dd>{system.agent.configured ? system.agent.model : "Not configured; baseline and random search remain available"}</dd></div>
        </dl>
        <p className="field-help">{system.cool.detail}</p>
        <p>Use the licensed COOL environment on a supported AWS Graviton host to run the same camera pipeline. Keep its vendor OpenCV installation; do not install the standard OpenCV wheel over it.</p>
        <a href="https://opencv.org/cloud/" target="_blank" rel="noreferrer">OpenCV COOL requirements</a>
        <details className="advanced"><summary>Hardware provenance</summary><p>{system.runtime.hardware_note}</p><code>{system.runtime.build_sha256}</code></details>
      </section>
      <section>
        <h2>Applied camera configuration</h2>
        {camera.error && <Notice>{camera.error}</Notice>}
        {camera.data ? <><button onClick={() => openRun(camera.data!.experiment.run_id)}>Open validated run and apply/rollback controls</button><pre>{JSON.stringify(camera.data.experiment.config, null, 2)}</pre></> : <p>No camera-health configuration applied. Development-only recordings cannot be promoted.</p>}
        <p>Apply changes the saved workbench configuration. It does not alter physical cameras or control a vehicle.</p>
        <a href="#/camera">Configure camera validation</a>
        <h2>Recording sets</h2>
        {system.camera_datasets.length ? <ul>{system.camera_datasets.map(dataset => <li key={dataset.id}>{dataset.id} · {dataset.error ?? (dataset.development_only ? "development only" : "session-disjoint validation available")}</li>)}</ul> : <p>No recording sets registered. Add local timestamped footage before validation.</p>}
      </section>
    </div>
    <section className="measurement-details">
      <h2>What the measurements establish</h2>
      <p>Local OpenCV analysis reports low detail, brightness, clipping, regional detail loss and repeated imagery. Delivery freshness is measured separately. These observations can have multiple causes.</p>
      <p>Validation holds thresholds and per-fault limits fixed while comparing processing configurations. Candidate selection freezes before held-out sessions. CPU time, evidence age, missed faults and costs must be evaluated together.</p>
      <p>Optional Decisions calls review individual images asynchronously. Their advice expires with source-image age and cannot clear local alarms. Network and model latency do not benefit from COOL acceleration.</p>
    </section>
  </>;
}

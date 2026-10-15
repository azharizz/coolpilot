import { useResource } from "./api";
import type { CameraConfig, System } from "./types";
import { RuntimeStack } from "./Diagrams";
import { ConfigGrid } from "./Camera";
import { Icon, Notice, PageHead } from "./ui";

export function Runtime({ system, openRun }: { system: System; openRun: (id: string) => void }) {
  const camera = useResource<{ experiment: { run_id: string; config: CameraConfig } } | null>("/api/active");
  const rt = system.runtime;
  return (
    <>
      <PageHead title="Runtime" lead="The engine that actually runs your analysis." />
      <div className="runtime-grid">
        <section className="panel">
          <h2>Execution stack</h2>
          <RuntimeStack layers={[
            { title: "Host", value: `${rt.system} · ${rt.architecture}`, active: true, note: `${rt.cpu_count} CPUs` },
            { title: "Vision engine", value: `${rt.distribution} ${rt.opencv_version}`, active: true },
            { title: "OpenCV COOL", value: system.cool.available ? "Vendor module detected" : "Not installed on this host", active: system.cool.available, note: system.cool.available ? "Performance unverified" : undefined },
            { title: "Experiment planner", value: system.agent.configured ? system.agent.model : "Not configured", active: system.agent.configured, note: system.agent.configured ? undefined : "Baseline and random search still work" },
          ]} />
          <p className="muted small">{system.cool.detail}</p>
          <a className="link" href="https://opencv.org/cloud/" target="_blank" rel="noreferrer">COOL requirements <Icon name="external" size={14} /></a>
          <details className="disclosure">
            <summary>Hardware provenance</summary>
            <p className="small">{rt.hardware_note}</p>
            <code className="hash">{rt.build_sha256}</code>
          </details>
        </section>

        <div className="runtime-side">
          <section className="panel">
            <h2>Applied configuration</h2>
            {camera.error && <Notice>{camera.error}</Notice>}
            {camera.data ? (
              <>
                <ConfigGrid config={camera.data.experiment.config} />
                <button className="btn" onClick={() => openRun(camera.data!.experiment.run_id)}>Open source run <Icon name="arrow" /></button>
              </>
            ) : (
              <div className="empty empty-inline">
                <Icon name="shield" size={26} />
                <p>Nothing applied. Only held-out validated runs can be applied.</p>
                <a className="btn btn-sm" href="#/camera">Configure validation</a>
              </div>
            )}
            <p className="muted small">Apply changes the saved workbench setting only. Physical cameras are never touched.</p>
          </section>

          <section className="panel">
            <h2>Recording sets</h2>
            {system.camera_datasets.length ? (
              <ul className="dataset-list">
                {system.camera_datasets.map(d => (
                  <li key={d.id}>
                    <strong>{d.id}</strong>
                    <span className={`chip ${d.error ? "chip-failed" : d.development_only ? "chip-interrupted" : "chip-completed"}`}>
                      {d.error ? "Unavailable" : d.development_only ? "Development only" : "Held-out ready"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="muted">No recording sets registered.</p>}
          </section>
        </div>
      </div>

      <section className="truths">
        <h2>What the numbers mean</h2>
        <ul>
          <li><Icon name="layers" /><p><b>Observations, not diagnoses.</b> Low detail, brightness, clipping and repeated frames each have several possible causes.</p></li>
          <li><Icon name="shield" /><p><b>Gates stay frozen.</b> Thresholds and per-fault limits are fixed before held-out sessions are scored.</p></li>
          <li><Icon name="target" /><p><b>Remote review is advisory.</b> Decisions scores expire with image age and never clear a local alarm.</p></li>
        </ul>
      </section>
    </>
  );
}

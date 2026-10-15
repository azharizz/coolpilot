import { useState } from "react";
import { request, refresh, useResource } from "./api";
import type { Active, System } from "./types";
import { ConfigList, Notice, Status } from "./ui";

export function Runtime({
  system,
  active,
  openRun,
  busy,
}: {
  system: System;
  active: Active;
  openRun: (id: string) => void;
  busy: boolean;
}) {
  const [error, setError] = useState("");
  const [acting, setActing] = useState(false);
  const camera = useResource<{experiment: {run_id: string; config: unknown; environment?: unknown}} | null>("/api/active?workload=camera_health");
  async function action(url: string) {
    setActing(true);
    setError("");
    try {
      const result = await request<{ id?: string }>(url, {});
      refresh("/api/active", "/api/history");
      if (url.endsWith("benchmark") && result.id) openRun(result.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed.");
    } finally {
      setActing(false);
    }
  }
  const dataset = system.dataset;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Runtime</h1>
          <p>Your local engine and applied configuration.</p>
        </div>
        <Status value={system.dataset_state.status} />
      </div>
      {error && <Notice>{error}</Notice>}
      {system.dataset_state.error && (
        <Notice>{system.dataset_state.error}</Notice>
      )}
      <section>
        <h2>Camera-health configuration</h2>
        {camera.error && <Notice>{camera.error}</Notice>}
        {camera.data ? <><button onClick={() => openRun(camera.data!.experiment.run_id)}>Open validated camera run and apply/rollback controls</button><pre>{JSON.stringify(camera.data.experiment.config, null, 2)}</pre></> : <p>No camera-health configuration applied. Development-only recordings cannot be promoted.</p>}
        <a href="#/camera">Configure camera-health replay</a>
      </section>
      <div className="runtime-layout">
        <section>
          <h2>Execution environment</h2>
          <dl className="fact-list">
            <div>
              <dt>Platform</dt>
              <dd>
                {system.runtime.system} / {system.runtime.architecture} ·{" "}
                {system.runtime.cpu_count} CPUs
              </dd>
            </div>
            <div>
              <dt>Vision engine</dt>
              <dd>
                {system.runtime.distribution} {system.runtime.opencv_version}
              </dd>
            </div>
            <div>
              <dt>Agent model</dt>
              <dd>
                {system.agent.model || "Not configured"}
                <Status
                  value={system.agent.configured ? "configured" : "missing"}
                />
              </dd>
            </div>
            <div>
              <dt>COOL acceleration</dt>
              <dd>
                {system.cool.available
                  ? "Detected"
                  : "Unavailable on this host"}
              </dd>
            </div>
          </dl>
          <p className="field-help">{system.cool.detail}</p>
          <details className="advanced">
            <summary>Hardware provenance</summary>
            <p>{system.runtime.hardware_note}</p>
            <code>{system.runtime.build_sha256}</code>
          </details>
        </section>
        <section className="active-workload">
          <h2>Active configuration</h2>
          {active ? (
            <>
              <p>
                From experiment #{active.experiment_id}.{" "}
                <a href={`#/runs/${active.experiment.run_id}`}>
                  View source run
                </a>
              </p>
              <ConfigList config={active.experiment.config} />
              <div className="actions">
                <button
                  className="button primary"
                  disabled={
                    acting || busy || system.dataset_state.status !== "ready"
                  }
                  onClick={() => void action("/api/active/benchmark")}
                >
                  {acting ? "Working…" : "Run active workload"}
                </button>
                <button
                  className="button secondary"
                  disabled={acting || active.previous_id === null}
                  onClick={() => void action("/api/active/rollback")}
                >
                  Roll back
                </button>
              </div>
            </>
          ) : (
            <div className="empty-inline">
              <p>No configuration applied yet.</p>
              <a href="#/">Start an optimization</a>
            </div>
          )}
        </section>
      </div>
      {dataset && (
        <section className="dataset-details">
          <img
            src="/api/frames/tuning/0"
            alt="CTU mouse-pad tracking dataset"
          />
          <div>
            <h2>{dataset.name}</h2>
            <p>
              {dataset.frame_count.toLocaleString()} frames · {dataset.width} ×{" "}
              {dataset.height} · {dataset.fps} fps
            </p>
            <a href={dataset.source} target="_blank" rel="noreferrer">
              Dataset source
            </a>
            <details>
              <summary>Annotations & provenance</summary>
              <p>{dataset.annotation}</p>
              <p className="field-help">{dataset.citation}</p>
              <code>{dataset.sha256}</code>
            </details>
          </div>
        </section>
      )}
      <details className="measurement-details method">
        <summary>How measurements work</summary>
        <dl className="fact-list">
          <div>
            <dt>Throughput</dt>
            <dd>
              Source frames covered per second across concurrent stream
              replicas, including decoding, preprocessing, tracking and
              initialization. Evaluation and artifact writing are excluded.
            </dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd>
              p95 wall time of processed frames, including decoding. Skipped
              frames and startup do not dilute the distribution.
            </dd>
          </div>
          <div>
            <dt>Quality</dt>
            <dd>
              Success is polygon IoU ≥ 0.5. Corner error uses original-image
              pixels. Every frame after initialization is scored; missing tracks
              incur the frame diagonal as error.
            </dd>
          </div>
          <div>
            <dt>Validation</dt>
            <dd>
              The best passing candidate is frozen before a disjoint clip is
              evaluated. The reference is also validated as a fallback. There is
              no further search against validation results.
            </dd>
          </div>
          <div>
            <dt>Resources & cost</dt>
            <dd>
              CPU time is normalized to available CPUs. Memory sums worker peak
              RSS, an upper bound. Host cost per video-hour is supplied hourly
              price × source fps ÷ throughput; inference, storage and networking
              are excluded.
            </dd>
          </div>
        </dl>
      </details>
    </>
  );
}

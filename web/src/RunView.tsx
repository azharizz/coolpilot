import { useState } from "react";
import { request, refresh, useResource } from "./api";
import type { Active, Experiment, Run, RunRequest, System } from "./types";
import { Evidence, Frontier } from "./Evidence";
import { number, Status, Icon, Notice, Pagination, experimentName } from "./ui";
import { CameraRun } from "./Camera";

export function RunView({
  identifier,
  system,
  active,
  busy,
  openRun,
  onEdit,
}: {
  identifier: string;
  system: System;
  active: Active;
  busy: boolean;
  openRun: (id: string) => void;
  onEdit: (request: RunRequest) => void;
}) {
  const resource = useResource<Run>(`/api/runs/${identifier}`);
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState("result");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [acting, setActing] = useState(false);
  const run = resource.data;
  async function action(url: string, body: unknown = {}) {
    setActing(true);
    setError("");
    try {
      const result = await request<{ id?: string }>(url, body);
      refresh("/api/active", "/api/history", `/api/runs/${identifier}`);
      if (url === "/api/runs" && result.id) openRun(result.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed.");
    } finally {
      setActing(false);
    }
  }
  if (!run)
    return resource.error ? (
      <Notice>
        {resource.error} <a href="#/history">Back to history</a>
      </Notice>
    ) : (
      <p className="loading" role="status">
        Loading results…
      </p>
    );
  if (run.request.camera) return <CameraRun identifier={identifier} busy={busy} openRun={openRun} onEdit={onEdit} />;
  const experiments = run.experiments;
  const running = ["running", "queued"].includes(run.status);
  const recommendation = experiments.find((e) => e.id === run.recommendation);
  const reference = experiments.find((e) => e.kind === "reference_validation");
  const comparison =
    recommendation?.metrics && reference?.metrics
      ? { before: reference.metrics, after: recommendation.metrics }
      : null;
  const gain = comparison
    ? (comparison.after.throughput_fps / comparison.before.throughput_fps - 1) *
      100
    : null;
  const chosen =
    experiments.find((e) => e.id === selected) ??
    recommendation ??
    [...experiments].reverse().find((e) => e.status === "completed");
  const measuring = experiments.find((e) => e.status === "running");
  const finished = experiments.filter((e) => e.status === "completed").length;
  const usedCandidates = experiments.filter(
    (e) => e.kind === "candidate",
  ).length;
  const applied = Boolean(
    recommendation && active?.experiment_id === recommendation.id,
  );
  const title = running
    ? measuring
      ? `Measuring ${experimentName(measuring).toLowerCase()}`
      : "Reviewing measurements"
    : recommendation?.kind === "reference_validation"
      ? "Reference retained"
      : recommendation
        ? "Validated configuration ready"
        : run.status === "completed"
          ? "No configuration passed validation"
          : `Run ${run.status}`;
  const detail = running
    ? `${finished} measurements complete. Results appear as each experiment finishes.`
    : recommendation?.kind === "reference_validation"
      ? "The reference passed validation. This search found no better configuration that passed."
      : recommendation
        ? "Passed accuracy and latency limits on the held-out clip."
        : run.status === "completed"
          ? "Review the measurements or edit your limits before running again."
          : "Completed measurements are saved. You can reuse this setup for another run.";
  function inspect(id: number) {
    setSelected(id);
    setView("result");
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>{run.request.name}</h1>
          <div className="run-meta">
            <Status value={run.status} />
            <span>
              {run.request.strategy === "agent"
                ? "Nebius agent"
                : run.request.strategy === "random"
                  ? "Random search"
                  : "Baseline"}{" "}
              · {run.request.frames} frames · {run.request.repetitions}{" "}
              repetitions
            </span>
          </div>
        </div>
        <div className="actions">
          {running ? (
            <button
              className="button secondary"
              disabled={acting}
              onClick={() => void action(`/api/runs/${identifier}/cancel`)}
            >
              Cancel run
            </button>
          ) : (
            <>
              <button
                className="button secondary"
                onClick={() => onEdit(run.request)}
              >
                Edit setup
              </button>
              <button
                className="button primary"
                disabled={
                  acting ||
                  busy ||
                  system.dataset_state.status !== "ready" ||
                  (run.request.strategy === "agent" && !system.agent.configured)
                }
                onClick={() => void action("/api/runs", run.request)}
              >
                {acting ? "Working…" : "Run again"}
                <Icon name="arrow" />
              </button>
            </>
          )}
        </div>
      </div>
      {(error || run.error || resource.error) && (
        <Notice>{error || run.error || resource.error}</Notice>
      )}
      <section className="result-summary" aria-live="polite">
        <div className="result-decision">
          <div>
            <h2>{title}</h2>
            <p>{detail}</p>
          </div>
          {recommendation && (
            <div className="apply-action">
              <button
                className="button primary"
                disabled={acting || applied}
                onClick={() =>
                  void action(`/api/experiments/${recommendation.id}/apply`)
                }
              >
                {applied ? "Configuration active" : "Apply configuration"}
              </button>
              <small>Updates the local workload runner</small>
            </div>
          )}
        </div>
        {running && run.request.strategy !== "baseline" && (
          <div className="run-progress">
            <span className="runtime-dot" />
            {usedCandidates} of{" "}
            {run.request.budget}{" "}
            candidate experiments started
            {measuring?.kind.endsWith("validation")
              ? " · Validating on unseen frames"
              : ""}
          </div>
        )}
        {comparison && (
          <div className="comparison">
            <div className="comparison-label">
              <strong>Held-out comparison</strong>
              <span>Reference → Selected</span>
            </div>
            <div>
              <span>Throughput</span>
              <strong>
                {number(comparison.before.throughput_fps)} <span>→</span>{" "}
                {number(comparison.after.throughput_fps)} <small>fps</small>
              </strong>
              {gain !== null &&
                recommendation?.kind !== "reference_validation" && (
                  <small className={gain > 0 ? "gain" : "muted"}>
                    {gain > 0 ? "+" : ""}
                    {number(gain)}% throughput
                  </small>
                )}
            </div>
            <div>
              <span>p95 latency</span>
              <strong>
                {number(comparison.before.p95_ms)} <span>→</span>{" "}
                {number(comparison.after.p95_ms)} <small>ms</small>
              </strong>
            </div>
            <div>
              <span>Corner error</span>
              <strong>
                {number(comparison.before.corner_error_px, 2)} <span>→</span>{" "}
                {number(comparison.after.corner_error_px, 2)} <small>px</small>
              </strong>
            </div>
          </div>
        )}
      </section>
      <div className="view-navigation">
        <nav aria-label="Run details" className="view-switch">
          {[
            ["result", "Result"],
            ["experiments", `Experiments (${experiments.length})`],
            [
              "notes",
              run.request.strategy === "agent" ? "Agent notes" : "Run notes",
            ],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={view === value}
              onClick={() => setView(value)}
            >
              {label}
            </button>
          ))}
        </nav>
        <a className="download-link" href={`/api/runs/${identifier}/export`}>
          <Icon name="download" />
          Export evidence
        </a>
      </div>
      {view === "result" && (
        <>
          {chosen && system.dataset ? (
            <>
              <div className="section-heading inspection-heading">
                <h2>Tracking evidence</h2>
                <label className="filter-label">
                  <span className="sr-only">Inspect experiment</span>
                  <select
                    value={chosen.id}
                    onChange={(event) =>
                      setSelected(Number(event.target.value))
                    }
                  >
                    {experiments
                      .filter((e) => e.status === "completed")
                      .map((e) => (
                        <option key={e.id} value={e.id}>
                          {experimentName(e)} · #{e.id}
                          {e.id === recommendation?.id ? " · Recommended" : ""}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <Evidence
                key={chosen.id}
                experiment={chosen}
                baseline={
                  chosen.kind.endsWith("validation")
                    ? reference
                    : experiments.find((e) => e.kind === "baseline")
                }
                dataset={system.dataset}
              />
            </>
          ) : (
            <div className="empty-state">
              <h3>
                {running
                  ? "First measurement in progress"
                  : "No measured frames yet"}
              </h3>
              <p>
                {running
                  ? "The real tracking preview appears when the reference run finishes."
                  : "Run again to collect tracking evidence."}
              </p>
            </div>
          )}
        </>
      )}
      {view === "experiments" && (
        <>
          <div className="contract-line">
            Limits: success ≥{" "}
            {Number((run.request.goals.min_success * 100).toPrecision(12))}% ·
            error ≤ {run.request.goals.max_corner_error_px} px · p95 ≤{" "}
            {run.request.goals.max_p95_ms} ms
          </div>
          <div
            className="table-scroll"
            role="region"
            aria-label="Experiment measurements"
            tabIndex={0}
          >
            <table className="ledger">
              <thead>
                <tr>
                  <th>Experiment</th>
                  <th>Configuration</th>
                  <th>Throughput</th>
                  <th>p95 latency</th>
                  <th>Error</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {experiments.slice((page - 1) * 6, page * 6).map((e) => (
                  <ExperimentRow key={e.id} experiment={e} onSelect={inspect} />
                ))}
              </tbody>
            </table>
            {!experiments.length && (
              <p className="empty-inline">Waiting for the first measurement.</p>
            )}
          </div>
          <Pagination
            page={page}
            pageSize={6}
            total={experiments.length}
            onPage={setPage}
            label="Experiment pages"
          />
          <details className="advanced">
            <summary>Speed and accuracy chart</summary>
            <div className="frontier-section">
              <Frontier
                experiments={experiments.filter(
                  (e) => !e.kind.endsWith("validation"),
                )}
                frontier={run.frontier}
                selected={chosen?.id ?? 0}
                maxError={run.request.goals.max_corner_error_px}
                onSelect={inspect}
              />
            </div>
          </details>
        </>
      )}
      {view === "notes" && <AgentNotes run={run} />}
    </>
  );
}

function ExperimentRow({
  experiment: e,
  onSelect,
}: {
  experiment: Experiment;
  onSelect: (id: number) => void;
}) {
  return (
    <tr>
      <th scope="row">
        <button
          className="text-button"
          disabled={e.status !== "completed"}
          onClick={() => onSelect(e.id)}
        >
          {experimentName(e)}
        </button>
        <small>
          #{e.id} ·{" "}
          {e.kind.endsWith("validation") ? "Held-out clip" : "Tuning clip"}
        </small>
      </th>
      <td>
        {e.config.width}px · {e.config.features} features
        <small>
          stride {e.config.frame_stride} · {e.config.workers} streams ×{" "}
          {e.config.threads} threads
        </small>
      </td>
      <td>
        {e.metrics ? `${number(e.metrics.throughput_fps)} fps` : "Pending"}
      </td>
      <td>{e.metrics ? `${number(e.metrics.p95_ms)} ms` : "Pending"}</td>
      <td>
        {e.metrics ? `${number(e.metrics.corner_error_px, 2)} px` : "Pending"}
      </td>
      <td>
        <Status
          value={
            e.status !== "completed"
              ? e.status
              : e.gate?.passed
                ? "passed"
                : "rejected"
          }
        />
      </td>
    </tr>
  );
}

function AgentNotes({ run }: { run: Run }) {
  const [page, setPage] = useState(1);
  const candidates = run.experiments.filter((e) => e.kind === "candidate");
  const tokens = run.events.reduce(
    (total, event) =>
      total +
      Number(
        (event.payload.usage as { total_tokens?: number } | undefined)
          ?.total_tokens ?? 0,
      ),
    0,
  );
  return (
    <section className="agent-notes">
      {run.summary && (
        <div className="model-summary">
          <h2>
            {run.request.strategy === "agent"
              ? "Agent conclusion"
              : "Run summary"}
          </h2>
          <p>{run.summary}</p>
          {run.request.strategy === "agent" && (
            <small>
              Model commentary. The recorded validation verdict determines
              whether a configuration can be applied.
            </small>
          )}
        </div>
      )}
      <div className="section-heading">
        <h2>Experiment reasoning</h2>
        {tokens > 0 && (
          <span className="muted">{tokens.toLocaleString()} model tokens</span>
        )}
      </div>
      {candidates.slice((page - 1) * 4, page * 4).map((e) => (
        <article className="note" key={e.id}>
          <h3>
            {experimentName(e)}
            <Status
              value={
                e.status !== "completed"
                  ? e.status
                  : e.gate?.passed
                    ? "passed"
                    : "rejected"
              }
            />
          </h3>
          <p>{e.rationale}</p>
          {e.error && <p className="error-text">{e.error}</p>}
        </article>
      ))}
      {!candidates.length && (
        <p className="empty-inline">
          {run.request.strategy === "baseline"
            ? "Baseline runs do not search for new configurations."
            : "No candidate reasoning recorded yet."}
        </p>
      )}
      <Pagination
        page={page}
        pageSize={4}
        total={candidates.length}
        onPage={setPage}
        label="Agent note pages"
      />
    </section>
  );
}

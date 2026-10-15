import { useState, type FormEvent } from "react";
import { request } from "./api";
import type { Configuration, RunRequest, System } from "./types";
import { defaultConfig, configLabels, Icon, Notice } from "./ui";

export function RunForm({
  system,
  busy,
  onStart,
  initial,
  onReset,
}: {
  system: System;
  busy: boolean;
  onStart: (id: string) => void;
  initial?: RunRequest;
  onReset: () => void;
}) {
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [customize, setCustomize] = useState(Boolean(initial));
  const [strategy, setStrategy] = useState<RunRequest["strategy"]>(
    initial?.strategy ?? "agent",
  );
  const ready = system.dataset_state.status === "ready";
  const providerMissing = strategy === "agent" && !system.agent.configured;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSending(true);
    const data = new FormData(event.currentTarget);
    const value = (key: string) => Number(data.get(key));
    const body: RunRequest = {
      name: String(data.get("name")),
      strategy,
      budget: value("budget"),
      repetitions: value("repetitions"),
      frames: value("frames"),
      seed: value("seed"),
      goals: {
        min_success: value("success") / 100,
        max_corner_error_px: value("error"),
        max_p95_ms: value("latency"),
      },
      baseline: Object.fromEntries(
        Object.keys(defaultConfig).map((key) => [key, value(key)]),
      ) as Configuration,
      hourly_price: data.get("price") ? value("price") : null,
    };
    try {
      const result = await request<{ id: string }>("/api/runs", body);
      onStart(result.id);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Run could not be started.",
      );
    } finally {
      setSending(false);
    }
  }
  return (
    <form onSubmit={submit} onInvalid={() => setCustomize(true)}>
      <section className="start-panel">
        <div className="start-copy">
          <h1>
            Faster tracking.
            <br />
            Keep the accuracy.
          </h1>
          <p>
            Let the agent tune OpenCV, measure each change, and validate the
            result.
          </p>
          <button
            type="submit"
            className="button light"
            disabled={sending || busy || !ready || providerMissing}
          >
            {sending
              ? "Starting…"
              : strategy === "baseline"
                ? "Measure baseline"
                : strategy === "random"
                  ? "Start random search"
                  : "Optimize tracking"}
            <Icon name="arrow" />
          </button>
          <small>
            {strategy === "agent"
              ? "Uses your Nebius account. Runs locally."
              : "Runs locally. No model calls."}
          </small>
        </div>
        <figure className="source-preview">
          {system.dataset ? (
            <img
              src="/api/frames/tuning/0"
              width={system.dataset.width}
              height={system.dataset.height}
              alt="Real CTU tracking workload: a mouse pad on a desk"
            />
          ) : (
            <div className="preview-pending">
              Preparing the tracking dataset…
            </div>
          )}
          <figcaption>
            CTU mouse-pad tracking <span>Annotated benchmark</span>
          </figcaption>
        </figure>
      </section>
      {error && <Notice>{error}</Notice>}
      {!ready && (
        <Notice>
          {system.dataset_state.error ??
            "Preparing the dataset. Optimization unlocks when it is ready."}{" "}
          <a href="#/runtime">View runtime</a>
        </Notice>
      )}
      {providerMissing && (
        <Notice>
          Configure Nebius in .env and restart to use the agent. Baseline and
          random search are available under Customize.
        </Notice>
      )}
      <details
        className="customize"
        open={customize}
        onToggle={(event) => setCustomize(event.currentTarget.open)}
      >
        <summary>
          <span>Customize run</span>
          <span className="summary-hint">
            {initial
              ? "Reusing a saved setup"
              : "Quality limits, budget & reference"}
          </span>
        </summary>
        <div className="settings-body">
          <div className="section-heading">
            <h2>Run setup</h2>
            {initial && (
              <button type="button" className="text-button" onClick={onReset}>
                Reset to defaults
              </button>
            )}
          </div>
          <div className="field-grid two">
            <label className="field">
              Run name
              <input
                name="name"
                defaultValue={initial?.name ?? "Mouse-pad optimization"}
                maxLength={100}
                required
              />
            </label>
            <label className="field">
              Search method
              <select
                value={strategy}
                onChange={(event) =>
                  setStrategy(event.target.value as RunRequest["strategy"])
                }
              >
                <option value="agent">Nebius agent</option>
                <option value="random">Random search</option>
                <option value="baseline">Baseline only</option>
              </select>
            </label>
          </div>
          <fieldset>
            <legend>Quality limits</legend>
            <div className="field-grid three">
              <label className="field">
                Minimum success (%)
                <input
                  name="success"
                  type="number"
                  min="0"
                  max="100"
                  step="any"
                  defaultValue={(initial?.goals.min_success ?? 0.95) * 100}
                  required
                />
              </label>
              <label className="field">
                Maximum error (px)
                <input
                  name="error"
                  type="number"
                  min="0.1"
                  max="1000"
                  step="any"
                  defaultValue={initial?.goals.max_corner_error_px ?? 4}
                  required
                />
              </label>
              <label className="field">
                Maximum p95 latency (ms)
                <input
                  name="latency"
                  type="number"
                  min="0.1"
                  max="10000"
                  step="any"
                  defaultValue={initial?.goals.max_p95_ms ?? 40}
                  required
                />
              </label>
            </div>
          </fieldset>
          <fieldset>
            <legend>Measurement budget</legend>
            <div className="field-grid three">
              <label className="field">
                Candidate experiments
                <input
                  name="budget"
                  type="number"
                  min="1"
                  max="30"
                  defaultValue={initial?.budget ?? 6}
                  required
                />
              </label>
              <label className="field">
                Repetitions
                <input
                  name="repetitions"
                  type="number"
                  min="1"
                  max="10"
                  defaultValue={initial?.repetitions ?? 3}
                  required
                />
              </label>
              <label className="field">
                Frames per clip
                <input
                  name="frames"
                  type="number"
                  min="30"
                  max="1000"
                  defaultValue={initial?.frames ?? 300}
                  required
                />
              </label>
            </div>
            <p className="field-help">
              Reference and validation checks run in addition to the candidate
              budget.
            </p>
          </fieldset>
          <details className="advanced">
            <summary>Reference configuration & cost</summary>
            <div className="field-grid three">
              {(
                Object.entries(initial?.baseline ?? defaultConfig) as [
                  keyof Configuration,
                  number,
                ][]
              ).map(([key, value]) => (
                <label className="field" key={key}>
                  {configLabels[key]}
                  <input
                    name={key}
                    type="number"
                    required
                    min={key === "width" ? 160 : key === "features" ? 20 : 1}
                    max={
                      {
                        width: 1280,
                        features: 2000,
                        frame_stride: 6,
                        threads: 8,
                        workers: 4,
                        pyramid_levels: 5,
                      }[key]
                    }
                    defaultValue={value}
                  />
                </label>
              ))}
              <label className="field">
                Host price (USD/hour)
                <input
                  name="price"
                  type="number"
                  min="0.0001"
                  max="10000"
                  step="any"
                  placeholder="Optional"
                  defaultValue={initial?.hourly_price ?? ""}
                />
              </label>
              <label className="field">
                Random-search seed
                <input
                  name="seed"
                  type="number"
                  min="0"
                  max="2147483647"
                  defaultValue={initial?.seed ?? 42}
                  required
                />
              </label>
            </div>
          </details>
          <button
            className="button primary"
            type="submit"
            disabled={sending || busy || !ready || providerMissing}
          >
            {sending ? "Starting…" : "Start with these settings"}
            <Icon name="arrow" />
          </button>
        </div>
      </details>
    </form>
  );
}

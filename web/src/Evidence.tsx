import { useState } from "react";
import { useResource } from "./api";
import { ConfigList, Notice, number, Status } from "./ui";
import type { Dataset, Experiment } from "./types";

export function Evidence({
  experiment,
  baseline,
  dataset,
}: {
  experiment: Experiment;
  baseline?: Experiment;
  dataset: Dataset;
}) {
  const detailed = useResource<Experiment>(
    `/api/experiments/${experiment.id}`,
    0,
  );
  const [frame, setFrame] = useState(0);
  const [loadedFrame, setLoadedFrame] = useState(-1);
  const [imageError, setImageError] = useState(false);
  const [showTruth, setShowTruth] = useState(true);
  const [showPrediction, setShowPrediction] = useState(true);
  const result = detailed.data;
  if (detailed.error) return <Notice>{detailed.error}</Notice>;
  if (!result?.trace || !result.metrics)
    return <p className="empty-inline">Loading tracking evidence…</p>;
  const trace = result.trace;
  const prediction = trace.polygons[frame];
  const truth = trace.truth[frame];
  const points = (polygon: number[][]) =>
    polygon.map((point) => point.join(",")).join(" ");
  const m = result.metrics;
  const maxStage = Math.max(
    ...Object.values(m.stages_ms),
    ...Object.values(baseline?.metrics?.stages_ms ?? {}),
  );
  return (
    <>
      <div className="evidence-layout">
        <section className="viewer" aria-label="Tracking frame viewer">
          <div className="frame-image">
            <img
              src={`/api/frames/${result.split}/${frame}`}
              alt={`Original tracking frame ${frame + 1}`}
              width={dataset.width}
              height={dataset.height}
              onLoad={() => setLoadedFrame(frame)}
              onError={() => setImageError(true)}
              style={{ opacity: loadedFrame === frame && !imageError ? 1 : 0 }}
            />
            {loadedFrame === frame && !imageError ? (
              <>
                <svg
                  viewBox={`0 0 ${dataset.width} ${dataset.height}`}
                  role="img"
                  aria-label="Dashed white: ground truth. Green: tracking prediction."
                >
                  {showTruth && truth && (
                    <>
                      <polygon
                        points={points(truth)}
                        fill="none"
                        stroke="#222"
                        strokeWidth="5"
                        strokeDasharray="9 5"
                      />
                      <polygon
                        points={points(truth)}
                        fill="none"
                        stroke="white"
                        strokeWidth="2.5"
                        strokeDasharray="9 5"
                      />
                    </>
                  )}
                  {showPrediction && prediction && (
                    <polygon
                      points={points(prediction)}
                      fill="none"
                      stroke="#56ef56"
                      strokeWidth="2.5"
                    />
                  )}
                </svg>
                {!prediction && (
                  <span className="lost-label">Tracking lost</span>
                )}
              </>
            ) : (
              <span className="frame-loading" role="status">
                {imageError
                  ? "Image unavailable. Choose another frame to retry."
                  : "Loading frame…"}
              </span>
            )}
            <span className="clip-label">
              {result.split === "validation" ? "Held-out clip" : "Tuning clip"}
            </span>
          </div>
          <div className="frame-controls">
            <label htmlFor={`frame-${experiment.id}`}>
              Frame {frame + 1} / {trace.polygons.length}
            </label>
            <input
              id={`frame-${experiment.id}`}
              type="range"
              min="0"
              max={trace.polygons.length - 1}
              value={frame}
              onChange={(event) => {
                setFrame(Number(event.target.value));
                setImageError(false);
              }}
            />
            <span>
              {frame === 0
                ? "Initialization"
                : `${number(trace.errors_px[frame - 1], 2)} px error`}
            </span>
          </div>
          <div className="overlay-legend">
            <label>
              <input
                type="checkbox"
                checked={showTruth}
                onChange={(event) => setShowTruth(event.target.checked)}
              />
              Ground truth
            </label>
            <label>
              <input
                type="checkbox"
                checked={showPrediction}
                onChange={(event) => setShowPrediction(event.target.checked)}
              />
              Prediction
            </label>
            <span>
              {frame % experiment.config.frame_stride
                ? "Held prediction"
                : "Processed frame"}
            </span>
          </div>
        </section>
        <section className="quality-panel">
          <div className="section-heading">
            <h3>Quality check</h3>
            <Status value={result.gate?.passed ? "passed" : "rejected"} />
          </div>
          <dl className="quality-checks">
            {result.gate?.checks.map((check) => {
              const success = check.metric === "Tracking success";
              return (
                <div key={check.metric}>
                  <dt>
                    {check.metric
                      .replace("Processed-frame p95 (ms)", "p95 latency")
                      .replace("Mean corner error (px)", "Corner error")}
                    <small>
                      {check.operator === ">=" ? "At least" : "At most"}{" "}
                      {success
                        ? Number((check.limit * 100).toPrecision(12))
                        : check.limit}
                      {success
                        ? "%"
                        : check.metric.includes("ms")
                          ? " ms"
                          : " px"}
                    </small>
                  </dt>
                  <dd>
                    {number(
                      check.actual * (success ? 100 : 1),
                      success ? 1 : 2,
                    )}
                    {success
                      ? "%"
                      : check.metric.includes("ms")
                        ? " ms"
                        : " px"}
                    <small className={check.passed ? "gain" : "error-text"}>
                      {check.passed ? "Passed" : "Outside limit"}
                    </small>
                  </dd>
                </div>
              );
            })}
          </dl>
          <details className="config-details">
            <summary>Tracking configuration</summary>
            <ConfigList config={result.config} />
          </details>
          <p className="field-help">
            All source frames are scored, including held predictions.
          </p>
        </section>
      </div>
      <details className="measurement-details">
        <summary>Timing, resources & repetitions</summary>
        <div className="measurement-layout">
          <section className="stage-profile">
            <h3>Time per processed frame</h3>
            <p className="field-help">
              Gray: reference. Blue: selected. Same clip.
            </p>
            {Object.entries(m.stages_ms).map(([name, value]) => (
              <div className="stage" key={name}>
                <div>
                  <span>{name.replaceAll("_", " ")}</span>
                  <strong>{number(value, 2)} ms</strong>
                </div>
                <div className="stage-track">
                  <span
                    className="reference-bar"
                    style={{
                      width: `${((baseline?.metrics?.stages_ms[name] ?? 0) / maxStage) * 100}%`,
                    }}
                  />
                  <span
                    className="selected-bar"
                    style={{ width: `${(value / maxStage) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </section>
          <dl className="fact-list">
            <div>
              <dt>CPU capacity</dt>
              <dd>{number(m.cpu_capacity_pct)}%</dd>
            </div>
            <div>
              <dt>Worker peak RSS sum</dt>
              <dd>{number(m.worker_peak_rss_sum_mb)} MB</dd>
            </div>
            <div>
              <dt>Missing predictions</dt>
              <dd>{m.lost_frames}</dd>
            </div>
            <div>
              <dt>Prediction interval</dt>
              <dd>{number(m.prediction_interval_ms, 0)} ms</dd>
            </div>
            <div>
              <dt>Source frames scored / stream</dt>
              <dd>{m.scored_frames_per_stream}</dd>
            </div>
            <div>
              <dt>USD / video-hour</dt>
              <dd>
                {m.cost_per_video_hour === null
                  ? "No host price supplied"
                  : `$${number(m.cost_per_video_hour, 4)}`}
              </dd>
            </div>
          </dl>
        </div>
        <div className="table-scroll">
          <table>
            <caption>Measured repetitions</caption>
            <thead>
              <tr>
                <th>Repetition</th>
                <th>Throughput</th>
                <th>p95 latency</th>
                <th>Wall time</th>
              </tr>
            </thead>
            <tbody>
              {result.rounds?.map((round, index) => (
                <tr key={index}>
                  <th>{index + 1}</th>
                  <td>{number(round.throughput_fps)} fps</td>
                  <td>{number(round.p95_ms)} ms</td>
                  <td>{number(round.wall_seconds, 2)} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

export function Frontier({
  experiments,
  frontier,
  selected,
  maxError,
  onSelect,
}: {
  experiments: Experiment[];
  frontier: number[];
  selected: number;
  maxError: number;
  onSelect: (id: number) => void;
}) {
  const points = experiments.filter((e) => e.metrics);
  const xMax =
    Math.max(1, ...points.map((e) => e.metrics!.throughput_fps)) * 1.15;
  const yMax =
    Math.max(maxError * 1.4, ...points.map((e) => e.metrics!.corner_error_px)) *
    1.15;
  const x = (v: number) => 48 + (v / xMax) * 380;
  const y = (v: number) => 205 - (v / yMax) * 170;
  return (
    <>
      <svg
        className="frontier-chart"
        viewBox="0 0 460 256"
        role="group"
        aria-label="Throughput versus corner error. Lower error and higher throughput are better. The dashed line is the error limit."
      >
        {[0, 0.5, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1="48"
              x2="432"
              y1={y(yMax * fraction)}
              y2={y(yMax * fraction)}
              stroke="#dce3e2"
            />
            <text x="38" y={y(yMax * fraction) + 4} textAnchor="end">
              {number(yMax * fraction, 1)}
            </text>
            <text x={x(xMax * fraction)} y="226" textAnchor="middle">
              {number(xMax * fraction, 0)}
            </text>
          </g>
        ))}
        <line
          x1="48"
          x2="432"
          y1={y(maxError)}
          y2={y(maxError)}
          stroke="#936329"
          strokeDasharray="5 4"
        />
        <text
          x="432"
          y={y(maxError) - 6}
          textAnchor="end"
          className="chart-limit"
        >
          Error limit
        </text>
        <text x="48" y="16">
          Corner error · px
        </text>
        <text x="240" y="250" textAnchor="middle">
          Source frames / second
        </text>
        {points.map((e) => (
          <circle
            key={e.id}
            cx={x(e.metrics!.throughput_fps)}
            cy={y(e.metrics!.corner_error_px)}
            r={selected === e.id ? 7 : 5}
            fill={e.gate?.passed ? "#16823b" : "#bf2534"}
            stroke={selected === e.id ? "#222222" : "white"}
            strokeWidth={frontier.includes(e.id) ? 2.5 : 1.5}
            tabIndex={0}
            role="button"
            aria-label={`Inspect experiment ${e.id}: ${number(e.metrics!.throughput_fps)} fps, ${number(e.metrics!.corner_error_px)} pixel error, ${e.gate?.passed ? "passed" : "rejected"}`}
            onClick={() => onSelect(e.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(e.id);
              }
            }}
          >
            <title>
              #{e.id} · {e.gate?.passed ? "Passed" : "Rejected"}
              {frontier.includes(e.id) ? " · Pareto frontier" : ""}
            </title>
          </circle>
        ))}
      </svg>
      <div className="chart-legend">
        <span>
          <i className="valid-dot" />
          Passed
        </span>
        <span>
          <i className="invalid-dot" />
          Rejected
        </span>
        <span>Outlined: Pareto frontier</span>
      </div>
    </>
  );
}

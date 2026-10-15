import { useRef, useState } from "react";
import { request, useResource } from "./api";

type Camera = { id: string; label: string; video_url: string };
type Sources = { sources: Camera[]; decision_configured: boolean; distribution: string };
type Profile = {
  camera: string;
  label: string;
  width: number;
  height: number;
  frames: number;
  source_fps: number;
  source_seconds: number;
  decode_ms_per_frame: number;
  analysis_p95_ms: number;
  processing_fps: number;
  cpu_seconds_per_source_second: number;
  mean_brightness: number;
  mean_detail: number;
  black_fraction: number;
};
type Comparison = {
  profiles: Profile[];
  decision: {
    status: string;
    probabilities?: Record<string, number>;
    cost?: number | null;
    latency_s?: number;
    error?: string;
  };
  cool: { available: boolean; detail: string };
};
const SAMPLE_STEP_SECONDS = 0.05;
const SAMPLE_END_GUARD_SECONDS = 0.1;

export function CameraCompare() {
  const source = useResource<Sources>("/api/camera-comparison", 60000);
  const videos = useRef<(HTMLVideoElement | null)[]>([]);
  const durations = useRef<number[]>([]);
  const refCallbacks = useRef(new Map<number, (video: HTMLVideoElement | null) => void>());
  const [duration, setDuration] = useState(18);
  const [time, setTime] = useState(4);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState("");
  const [includeDecision, setIncludeDecision] = useState(false);
  const [result, setResult] = useState<Comparison>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function videoRef(index: number) {
    let callback = refCallbacks.current.get(index);
    if (!callback) {
      callback = (video) => { videos.current[index] = video; };
      refCallbacks.current.set(index, callback);
    }
    return callback;
  }

  function seek(seconds: number) {
    const sample = Math.max(0, Math.min(seconds, duration));
    setTime(sample);
    for (const video of videos.current) {
      if (video && video.readyState > 0) video.currentTime = sample;
    }
  }
  async function togglePlayback() {
    if (playing) {
      for (const video of videos.current) video?.pause();
      setPlaying(false);
    } else {
      try {
        await Promise.all(videos.current.filter((video): video is HTMLVideoElement => video !== null).map((video) => video.play()));
        setPlaying(true);
      } catch {
        setError("Wait for all three video previews to load, then try again.");
      }
    }
  }

  async function analyzeCameras() {
    setBusy(true);
    setError("");
    try {
      setResult(await request<Comparison>("/api/camera-comparison/analyze", {
        request_decision: includeDecision,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Camera comparison failed.");
    } finally {
      setBusy(false);
    }
  }

  const probabilities = result?.decision.probabilities;
  const ranked = probabilities ? Object.entries(probabilities).sort((a, b) => b[1] - a[1]) : [];
  const recommendation = ranked.length === 3 && ranked[0][1] >= 0.5 && ranked[0][1] - ranked[1][1] >= 0.05
    ? source.data?.sources.find((camera) => camera.id === ranked[0][0])?.label
    : null;
  const fastest = result?.profiles.reduce((best, profile) => profile.processing_fps > best.processing_fps ? profile : best);

  return (
    <section className="camera-workbench camera-comparison">
      <div className="page-heading">
        <p className="eyebrow">Synchronized source footage</p>
        <h1>Compare camera views</h1>
        <p>Review left, centre, and right views from the same Oxford RobotCar recording. Choose a view manually; model scores are advisory.</p>
      </div>
      {!source.data && <p className="loading" role="status">Loading camera sources…</p>}
      {source.error && <p className="notice" role="alert">{source.error}</p>}
      {source.data && (
        <>
          <div className="camera-comparison-grid">
            {source.data.sources.map((camera, index) => (
              <article className="camera-comparison-card" key={camera.id}>
                <h2>{camera.label}</h2>
                <video
                  ref={videoRef(index)}
                  src={camera.video_url}
                  preload="metadata"
                  muted
                  playsInline
                  aria-label={`${camera.label} camera video`}
                  onLoadedMetadata={(event) => {
                    durations.current[index] = event.currentTarget.duration;
                    const loadedDurations = durations.current.filter(Number.isFinite);
                    if (loadedDurations.length === source.data?.sources.length) {
                      const safeEnd = Math.min(...loadedDurations) - SAMPLE_END_GUARD_SECONDS;
                      setDuration(Math.max(0, Math.floor(safeEnd / SAMPLE_STEP_SECONDS) * SAMPLE_STEP_SECONDS));
                    }
                    event.currentTarget.currentTime = Math.min(time, duration);
                  }}
                  onTimeUpdate={(event) => {
                    const current = Math.min(event.currentTarget.currentTime, duration);
                    if (current !== event.currentTarget.currentTime) event.currentTarget.currentTime = current;
                    setTime(current);
                    for (const [otherIndex, video] of videos.current.entries()) {
                      if (otherIndex !== 0 && video?.readyState && Math.abs(video.currentTime - current) > 0.08) video.currentTime = current;
                    }
                  }}
                  onPause={() => setPlaying(false)}
                  onEnded={() => setPlaying(false)}
                />
                <label className="camera-pick">
                  <input type="radio" name="preferred-camera" value={camera.id} checked={selected === camera.id} onChange={() => setSelected(camera.id)} />
                  Select this view for the comparison
                </label>
              </article>
            ))}
          </div>
          <div className="camera-comparison-controls">
            <button type="button" onClick={togglePlayback}>{playing ? "Pause all" : "Play all"}</button>
            <label>Shared time: {time.toFixed(2)} s
              <input type="range" min="0" max={duration} step="0.05" value={Math.min(time, duration)} onChange={(event) => seek(Number(event.currentTarget.value))} />
            </label>
            <label className="camera-decision-consent">
              <input type="checkbox" checked={includeDecision} disabled={!source.data.decision_configured} onChange={(event) => setIncludeDecision(event.currentTarget.checked)} />
              Send one synchronized frame per camera to the configured Decisions model for an advisory visual-usability comparison.
              {!source.data.decision_configured && <span> Model credentials are unavailable to this app.</span>}
            </label>
            <button type="button" disabled={busy} onClick={analyzeCameras}>
              {busy ? "Measuring…" : includeDecision ? "Measure and ask Decisions" : "Measure local OpenCV"}
            </button>
          </div>
          {error && <p className="notice" role="alert">{error}</p>}
          <p className="camera-runtime-note" role="note">
            {source.data.distribution === "COOL"
              ? "COOL-linked OpenCV runtime detected; the measurement below still covers this local replay only."
              : "COOL performance is unavailable here. Results are local OpenCV measurements, not Graviton/COOL results."}
          </p>
          {selected && <p role="status">Current comparison selection: {source.data.sources.find((camera) => camera.id === selected)?.label}. This selection is not applied to a live monitor.</p>}
          {result && (
            <section aria-labelledby="camera-comparison-results">
              <h2 id="camera-comparison-results">Measured replay</h2>
              {recommendation && <p role="status">Decision model advisory: {recommendation} has the highest sampled visual-usability score ({(ranked[0][1] * 100).toFixed(0)}%). Confirm against the footage before choosing.</p>}
              {fastest && <p>Highest measured local replay throughput: {fastest.label} at {fastest.processing_fps.toFixed(1)} fps. Throughput alone does not determine the best view.</p>}
              {includeDecision && result.decision.status !== "ok" && <p className="notice" role="status">Decision model unavailable: {result.decision.error ?? result.decision.status}</p>}
              {result.decision.status === "ok" && <p>Decision model latency: {result.decision.latency_s?.toFixed(2)} s · reported cost: {result.decision.cost == null ? "not supplied" : `$${result.decision.cost.toFixed(6)}`}</p>}
              <div className="table-scroll">
                <table>
                  <thead><tr><th>View</th><th>Size / frames / duration</th><th>Decode ms/frame</th><th>Analysis p95 ms</th><th>Replay fps</th><th>CPU s/source s</th><th>Brightness proxy</th><th>Detail proxy</th><th>Black fraction</th><th>Visual usability</th></tr></thead>
                  <tbody>{result.profiles.map((profile) => (
                    <tr key={profile.camera}>
                      <th scope="row">{profile.label}{selected === profile.camera ? " · selected" : ""}</th>
                      <td>{profile.width}×{profile.height} · {profile.frames} · {profile.source_seconds.toFixed(2)} s · {profile.source_fps.toFixed(1)} source fps</td>
                      <td>{profile.decode_ms_per_frame.toFixed(2)}</td>
                      <td>{profile.analysis_p95_ms.toFixed(2)}</td>
                      <td>{profile.processing_fps.toFixed(1)}</td>
                      <td>{profile.cpu_seconds_per_source_second.toFixed(3)}</td>
                      <td>{profile.mean_brightness.toFixed(1)}</td>
                      <td>{profile.mean_detail.toFixed(1)}</td>
                      <td>{(profile.black_fraction * 100).toFixed(2)}%</td>
                      <td>{probabilities ? `${(probabilities[profile.camera] * 100).toFixed(0)}% · model` : "Not assessed"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <p>{result.cool.detail}</p>
            </section>
          )}
        </>
      )}
    </section>
  );
}

import { useState } from "react";
import { Icon, PageHead } from "./ui";

type Segment = { type: string; observation: string; start_s: number; end_s: number; open_at_end: boolean; thumbnail: string;
  verification?: { verdict: string; reason: string } | null };
type Decision = { time_s: number; verdict: string; reason: string; tiles: number[]; engine?: string | null };
type Report = { type: "report"; frames: number; fps: number; duration_s: number; resolution: number[] | null; segments: Segment[];
  verifier_decisions: Decision[]; flagged_seconds: number; processing_s: number; cpu_s: number; speed_x_realtime: number | null;
  opencv: string; scope: string };
type Slot = { id: string; upload: { method: "PUT" | "POST"; url: string; fields?: Record<string, string> }; max_bytes: number; max_seconds: number };

const MAX_MB = 50;

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

export function Footage() {
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [phase, setPhase] = useState("");
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const tooBig = !!file && file.size > MAX_MB * 1024 * 1024;

  async function start() {
    if (!file) return;
    setBusy(true); setError(""); setReport(undefined); setProgress(0);
    try {
      setPhase("Requesting an upload slot…");
      const slotResponse = await fetch("/api/footage", { method: "POST" });
      if (!slotResponse.ok) throw new Error((await slotResponse.json()).detail ?? "Upload refused.");
      const slot = await slotResponse.json() as Slot;
      setPhase("Uploading…");
      let uploaded: Response;
      if (slot.upload.method === "POST") {
        const form = new FormData();
        Object.entries(slot.upload.fields ?? {}).forEach(([k, v]) => form.append(k, v));
        form.append("file", file);
        uploaded = await fetch(slot.upload.url, { method: "POST", body: form });
      } else {
        uploaded = await fetch(slot.upload.url, { method: "PUT", body: file });
      }
      if (!uploaded.ok) throw new Error(`Upload failed (HTTP ${uploaded.status}).`);
      setPhase("Screening with OpenCV…");
      const response = await fetch(`/api/footage/${slot.id}/analyze`, { method: "POST" });
      if (!response.ok || !response.body) throw new Error((await response.json()).detail ?? "Screening refused.");
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
        for (const line of lines.filter(Boolean)) {
          const message = JSON.parse(line);
          if (message.type === "error") throw new Error(message.error);
          if (message.type === "progress") setProgress(message.total ? message.frames / message.total : 0);
          if (message.type === "report") { setReport(message); setProgress(1); }
        }
        if (done) break;
      }
      setPhase("Done. The uploaded file has been deleted.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Screening failed.");
      setPhase("");
    } finally { setBusy(false); }
  }

  const csv = report ? ["type,start_s,end_s,open_at_end,verifier", ...report.segments.map(s =>
    [s.type, s.start_s, s.end_s, s.open_at_end, s.verification?.verdict ?? ""].join(","))].join("\n") : "";
  const clean = report ? Math.max(0, report.duration_s - report.flagged_seconds) : 0;

  return <section>
    <PageHead title="Check footage" lead="Screen a short recording for camera-side problems before you label, train on or review it." />
    <div className="panel footage-panel">
      <p className="hint">At most {MAX_MB} MB and 60 s. The file is analysed once, then deleted; nothing is kept. Do not upload footage of people
        who have not agreed to it. Results come from rules calibrated on one recorded drive and are not a safety judgement.</p>
      <fieldset disabled={busy} className="deck-settings">
        <label className="field">Video file
          <input type="file" accept="video/mp4,video/quicktime,video/x-msvideo,.mp4,.mov,.avi,.mkv" onChange={e => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> I have the right to upload this footage</label>
        <button type="button" className="btn btn-primary" onClick={start} disabled={!file || !consent || tooBig}><Icon name="play" /> Screen footage</button>
      </fieldset>
      {tooBig && <p className="notice" role="alert">The file is larger than {MAX_MB} MB.</p>}
      {phase && <p role="status">{phase}</p>}
      {busy && <progress max={1} value={progress} aria-label="Screening progress" />}
      {error && <p className="notice" role="alert">{error}</p>}
    </div>
    {report && <div className="panel">
      <h2>Report</h2>
      <dl className="mini-stats">
        <div><dt>Duration</dt><dd className="mono">{report.duration_s} s</dd></div>
        <div><dt>Flagged</dt><dd className="mono">{report.flagged_seconds} s</dd></div>
        <div><dt>No issue found</dt><dd className="mono">{clean.toFixed(1)} s</dd></div>
        <div><dt>Frames</dt><dd className="mono">{report.frames} @ {report.fps} fps</dd></div>
        <div><dt>Speed</dt><dd className="mono">{report.speed_x_realtime}× real time</dd></div>
        <div><dt>OpenCV</dt><dd className="mono">{report.opencv}</dd></div>
      </dl>
      {report.segments.length ? <div className="table-scroll"><table className="compact">
        <thead><tr><th>Frame</th><th>Problem</th><th>From s</th><th>To s</th><th>Second-stage check</th></tr></thead>
        <tbody>{report.segments.map((s, i) => <tr key={i}>
          <td>{s.thumbnail && <img src={s.thumbnail} alt={`Frame at the start of the ${s.type} segment`} width={120} />}</td>
          <td>{s.observation}</td><td className="mono">{s.start_s}</td><td className="mono">{s.end_s}{s.open_at_end ? " (open)" : ""}</td>
          <td className="small">{s.verification ? `${s.verification.verdict}: ${s.verification.reason}` : "n/a"}</td></tr>)}</tbody>
      </table></div> : <p>No camera-side problem flagged.</p>}
      {report.verifier_decisions.some(d => d.verdict === "dismiss") && <p className="hint">
        Dismissed suspicions: {report.verifier_decisions.filter(d => d.verdict === "dismiss").map(d => `${d.time_s} s`).join(", ")} (scene, not the lens).</p>}
      <p className="hint">{report.scope}</p>
      <p className="verify-actions">
        <button type="button" className="btn" onClick={() => download("footage-report.json", JSON.stringify(report, null, 1), "application/json")}>Download JSON</button>
        <button type="button" className="btn" onClick={() => download("footage-segments.csv", csv, "text/csv")}>Download CSV</button>
      </p>
    </div>}
  </section>;
}

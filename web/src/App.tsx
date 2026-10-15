import { useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { refresh, useResource } from "./api";
import type { History, RunRequest, System } from "./types";
import { Icon, Notice, PageHead, Pagination, RunRows } from "./ui";
import { Runtime } from "./Runtime";
import { CameraForm, CameraRun } from "./Camera";
import { CameraCompare } from "./CameraCompare";
import { PipelineFlow, SensorField } from "./Diagrams";

const subscribeRoute = (listener: () => void) => {
  const navigate = () => {
    listener();
    window.scrollTo(0, 0);
  };
  window.addEventListener("hashchange", navigate);
  return () => window.removeEventListener("hashchange", navigate);
};
const getRoute = () => window.location.hash.slice(1) || "/";

const links = [
  { href: "/", label: "Overview" },
  { href: "/camera-comparison", label: "Live replay" },
  { href: "/camera", label: "Validate" },
  { href: "/history", label: "History" },
  { href: "/runtime", label: "Runtime" },
];

export function App() {
  const main = useRef<HTMLElement>(null);
  const route = useSyncExternalStore(subscribeRoute, getRoute);
  const system = useResource<System>("/api/system", 15000);
  const recent = useResource<History>("/api/history?page_size=4");
  const [draft, setDraft] = useState<RunRequest | undefined>();
  const runId = route.startsWith("/runs/") ? route.slice(6) : null;
  const busy = Boolean(recent.data?.running_id);
  const section = runId ? "/history" : route;
  function openRun(id: string) {
    window.location.hash = `/runs/${id}`;
    refresh("/api/history");
  }
  function editRun(request: RunRequest) {
    setDraft({ ...request });
    window.location.hash = "/camera";
  }
  const runtime = system.data?.runtime;
  return (
    <>
      <a className="skip-link" href="#main" onClick={(event) => { event.preventDefault(); main.current?.focus(); }}>
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/" aria-label="COOLPilot home" onClick={() => setDraft(undefined)}>
            <img src="/coolpilot-mark.svg" alt="" width="34" height="34" />
            <span>COOL<span className="brand-light">Pilot</span></span>
          </a>
          <nav aria-label="Main navigation">
            {links.map(link => (
              <a key={link.href} href={`#${link.href}`} aria-current={section === link.href ? "page" : undefined}
                onClick={() => link.href === "/camera" || link.href === "/" ? setDraft(undefined) : undefined}>
                {link.label}
              </a>
            ))}
          </nav>
          <a className={`sys-chip${system.data?.cool.available ? " is-cool" : ""}`} href="#/runtime" title="Runtime details">
            <span className="sys-dot" aria-hidden="true" />
            {runtime ? <>{runtime.distribution} <b className="mono">{runtime.opencv_version}</b> · {runtime.architecture}</> : "Connecting…"}
          </a>
        </div>
        {recent.data?.running_id && recent.data.running_id !== runId && (
          <a className="activity" role="status" href={`#/runs/${recent.data.running_id}`}>
            <span className="activity-bar" aria-hidden="true" />
            Validation running · <b>View progress</b>
          </a>
        )}
      </header>
      <main id="main" className="workspace" ref={main} tabIndex={-1}>
        {(system.error || recent.error) && <Notice>{system.error || recent.error}</Notice>}
        {system.loading && <div className="boot" role="status"><span className="boot-mark" aria-hidden="true" />Connecting to the workbench…</div>}
        {system.data && (
          <div className="view" key={runId ? "run" : route}>
            {route === "/runtime" ? (
              <Runtime system={system.data} openRun={openRun} />
            ) : route === "/camera-comparison" ? (
              <CameraCompare />
            ) : route === "/camera" ? (
              <CameraForm key={draft?.camera ? JSON.stringify(draft) : "camera"} system={system.data} busy={busy}
                initial={draft?.camera ? draft : undefined} onStart={openRun} />
            ) : route === "/history" ? (
              <RunHistory onNew={() => setDraft(undefined)} />
            ) : runId ? (
              <CameraRun key={runId} identifier={runId} busy={busy} openRun={openRun} onEdit={editRun} />
            ) : (
              <Overview system={system.data} recent={recent.data} onNew={() => setDraft(undefined)} />
            )}
          </div>
        )}
      </main>
      <footer className="footer">
        <span className="footer-brand"><img src="/coolpilot-mark.svg" alt="" width="18" height="18" /> COOLPilot</span>
        <span>Research workbench. Not validated for driving decisions or vehicle control.</span>
        <a href="https://opencv.org/" target="_blank" rel="noreferrer">Built with OpenCV</a>
      </footer>
    </>
  );
}

function Overview({ system, recent, onNew }: { system: System; recent: History | null; onNew: () => void }) {
  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <h1 id="hero-title">Camera health,<br /><span>measured frame by frame.</span></h1>
          <p>Replay three forward views through OpenCV. Delivery and image quality are tracked separately, then held to frozen gates.</p>
          <div className="hero-actions">
            <a className="btn btn-primary btn-lg" href="#/camera-comparison"><Icon name="play" /> Start live replay</a>
            <a className="btn btn-lg" href="#/camera" onClick={onNew}>Validate a configuration</a>
          </div>
          <dl className="hero-facts">
            <div><dt>Engine</dt><dd className="mono">OpenCV {system.runtime.opencv_version}</dd></div>
            <div><dt>COOL</dt><dd>{system.cool.available ? "Detected · unverified" : "Not installed"}</dd></div>
            <div><dt>Analysis</dt><dd>Local by default</dd></div>
          </dl>
        </div>
        <SensorField />
      </section>


      <section className="how" aria-labelledby="how-title">
        <div className="section-head"><h2 id="how-title">How a frame is judged</h2></div>
        <PipelineFlow />
      </section>

      <section className="recent" aria-labelledby="recent-title">
        <div className="section-head">
          <h2 id="recent-title">Recent runs</h2>
          <a href="#/history">All runs{recent ? ` (${recent.total})` : ""} <Icon name="arrow" size={16} /></a>
        </div>
        {recent ? <RunRows runs={recent.items} /> : <div className="skeleton-rows" aria-hidden="true"><i /><i /><i /></div>}
      </section>
    </>
  );
}

const statuses = ["completed", "running", "queued", "failed", "cancelled", "interrupted"];

function RunHistory({ onNew }: { onNew: () => void }) {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const history = useResource<History>(`/api/history?page=${page}&q=${encodeURIComponent(query)}&status=${status}`);
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(String(new FormData(event.currentTarget).get("search")).trim());
    setPage(1);
  }
  return (
    <>
      <PageHead title="History" lead="Every run, including rejected ones.">
        <a className="btn btn-primary" href="#/camera" onClick={onNew}><Icon name="plus" /> New validation</a>
      </PageHead>
      <div className="toolbar">
        <form onSubmit={search} role="search" className="search">
          <label className="sr-only" htmlFor="search">Search run names</label>
          <Icon name="search" />
          <input id="search" name="search" type="search" placeholder="Search run names" maxLength={100}
            onChange={(event) => { if (!event.target.value) { setQuery(""); setPage(1); } }} />
        </form>
        <div className="segmented" role="radiogroup" aria-label="Filter by status">
          {["", ...statuses].map(value => (
            <label key={value || "all"}>
              <input type="radio" name="status" value={value} checked={status === value}
                onChange={() => { setStatus(value); setPage(1); }} />
              <span>{value ? value[0].toUpperCase() + value.slice(1) : "All"}</span>
            </label>
          ))}
        </div>
      </div>
      {history.error && <Notice>{history.error}</Notice>}
      {history.loading && <div className="skeleton-rows" role="status" aria-label="Loading runs"><i /><i /><i /><i /></div>}
      {history.data && (
        <>
          <RunRows runs={history.data.items} filtered={Boolean(query || status)} />
          <Pagination page={history.data.page} pageSize={history.data.page_size} total={history.data.total}
            onPage={setPage} label="Run history pages" />
        </>
      )}
    </>
  );
}

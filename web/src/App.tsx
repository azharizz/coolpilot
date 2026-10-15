import { useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { refresh, useResource } from "./api";
import type { Active, History, RunRequest, System } from "./types";
import { Notice, Pagination, RunRows } from "./ui";
import { RunForm } from "./RunForm";
import { RunView } from "./RunView";
import { Runtime } from "./Runtime";
import { CameraForm } from "./Camera";
import { CameraCompare } from "./CameraCompare";

const subscribeRoute = (listener: () => void) => {
  const navigate = () => {
    listener();
    window.scrollTo(0, 0);
  };
  window.addEventListener("hashchange", navigate);
  return () => window.removeEventListener("hashchange", navigate);
};
const getRoute = () => window.location.hash.slice(1) || "/";

export function App() {
  const main = useRef<HTMLElement>(null);
  const route = useSyncExternalStore(subscribeRoute, getRoute);
  const system = useResource<System>("/api/system", 15000);
  const recent = useResource<History>("/api/history?page_size=3");
  const active = useResource<Active>("/api/active");
  const [draft, setDraft] = useState<RunRequest | undefined>();
  const runId = route.startsWith("/runs/") ? route.slice(6) : null;
  const busy = Boolean(recent.data?.running_id);
  function openRun(id: string) {
    window.location.hash = `/runs/${id}`;
    refresh("/api/history");
  }
  function editRun(request: RunRequest) {
    setDraft({ ...request });
    window.location.hash = request.camera ? "/camera" : "/";
  }
  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a
            className="brand"
            href="#/"
            aria-label="COOLPilot home"
            onClick={() => setDraft(undefined)}
          >
            <img src="/coolpilot-mark.svg" alt="" width="43" height="43" />
            <span>
              COOL<span className="brand-light">Pilot</span>
            </span>
          </a>
          <nav aria-label="Main navigation">
            <a
              href="#/"
              aria-current={route === "/" ? "page" : undefined}
              onClick={() => setDraft(undefined)}
            >
              Optimize
            </a>
            <a href="#/camera" aria-current={route === "/camera" ? "page" : undefined}>Camera health</a>
            <a href="#/camera-comparison" aria-current={route === "/camera-comparison" ? "page" : undefined}>Compare cameras</a>
            <a
              href="#/history"
              aria-current={route === "/history" || runId ? "page" : undefined}
            >
              History
            </a>
            <a
              href="#/runtime"
              aria-current={route === "/runtime" ? "page" : undefined}
            >
              Runtime
            </a>
          </nav>
          <span className="header-runtime">
            {system.data
              ? `${system.data.runtime.distribution} · ${system.data.runtime.architecture}`
              : "Connecting…"}
          </span>
        </div>
      </header>
      <main id="main" className="workspace" ref={main} tabIndex={-1}>
        {(system.error || recent.error || active.error) && (
          <Notice>{system.error || recent.error || active.error}</Notice>
        )}
        {recent.data?.running_id && recent.data.running_id !== runId && (
          <div className="activity-banner" role="status">
            A run is in progress.{" "}
            <a href={`#/runs/${recent.data.running_id}`}>View progress</a>
          </div>
        )}
        {system.loading && (
          <p className="loading" role="status">
            Connecting to your workspace…
          </p>
        )}
        {system.data &&
          (route === "/runtime" ? (
            <Runtime
              system={system.data}
              active={active.data}
              openRun={openRun}
              busy={busy}
            />
          ) : route === "/camera-comparison" ? (
            <CameraCompare />
          ) : route === "/camera" ? (
            <CameraForm key={draft?.camera ? JSON.stringify(draft) : "camera"} system={system.data} busy={busy} initial={draft?.camera ? draft : undefined} onStart={openRun} />
          ) : route === "/history" ? (
            <RunHistory onNew={() => setDraft(undefined)} />
          ) : runId ? (
            <RunView
              key={runId}
              identifier={runId}
              system={system.data}
              active={active.data}
              busy={busy}
              openRun={openRun}
              onEdit={editRun}
            />
          ) : (
            <>
              <RunForm
                key={draft ? JSON.stringify(draft) : "default"}
                initial={draft}
                system={system.data}
                busy={busy || recent.loading}
                onStart={openRun}
                onReset={() => setDraft(undefined)}
              />
              <section className="recent-section">
                <div className="section-heading">
                  <h2>Recent runs</h2>
                  <a href="#/history">
                    View all{recent.data ? ` (${recent.data.total})` : ""}
                  </a>
                </div>
                {recent.data && <RunRows runs={recent.data.items} />}
                {recent.loading && <p className="muted">Loading saved runs…</p>}
              </section>
            </>
          ))}
      </main>
      <footer className="site-footer">
        <span>COOLPilot</span>
        <span>
          Local OpenCV measurements. <a href="#/runtime">Runtime details</a>
        </span>
        <a href="https://opencv.org/" target="_blank" rel="noreferrer">
          Built with OpenCV
        </a>
      </footer>
    </>
  );
}

function RunHistory({ onNew }: { onNew: () => void }) {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const history = useResource<History>(
    `/api/history?page=${page}&q=${encodeURIComponent(query)}&status=${status}`,
  );
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(String(new FormData(event.currentTarget).get("search")).trim());
    setPage(1);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Run history</h1>
          <p>Revisit results or reuse a setup.</p>
        </div>
        <a className="button primary" href="#/" onClick={onNew}>
          New optimization
        </a>
      </div>
      <div className="history-toolbar">
        <form onSubmit={search} role="search" className="search-form">
          <label className="sr-only" htmlFor="search">
            Search run names
          </label>
          <input
            id="search"
            name="search"
            type="search"
            placeholder="Search run names"
            maxLength={100}
            onChange={(event) => {
              if (!event.target.value) {
                setQuery("");
                setPage(1);
              }
            }}
          />
          <button className="button secondary">Search</button>
        </form>
        <label className="filter-label">
          Status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All statuses</option>
            {[
              "completed",
              "running",
              "queued",
              "failed",
              "cancelled",
              "interrupted",
            ].map((value) => (
              <option value={value} key={value}>
                {value[0].toUpperCase() + value.slice(1)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {history.error && <Notice>{history.error}</Notice>}
      {history.loading && (
        <p className="loading" role="status">
          Loading runs…
        </p>
      )}
      {history.data && (
        <>
          <RunRows
            runs={history.data.items}
            filtered={Boolean(query || status)}
          />
          <Pagination
            page={history.data.page}
            pageSize={history.data.page_size}
            total={history.data.total}
            onPage={setPage}
            label="Run history pages"
          />
        </>
      )}
    </>
  );
}

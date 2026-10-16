import type { CSSProperties, ReactNode } from "react";
import type { RunSummary } from "./types";

export const number = (value: number | undefined, digits = 1) =>
  value === undefined
    ? "Not measured"
    : value !== 0 && Math.abs(value) < 10 ** -digits
      ? value.toLocaleString("en-US", { maximumSignificantDigits: 2 })
      : value.toLocaleString("en-US", {
          maximumFractionDigits: digits,
          minimumFractionDigits: digits,
        });

export function Status({ value }: { value: string }) {
  return <span className={`chip chip-${value}`}>{value.replaceAll("_", " ")}</span>;
}

const paths = {
  target: "M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5M8 12h8m-4-4v8",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  back: "M19 12H5m6-6-6 6 6 6",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  close: "m6 6 12 12M6 18 18 6",
  play: "M7 4.5v15l12-7.5z",
  pause: "M8 5v14M16 5v14",
  stop: "M6 6h12v12H6z",
  dice: "M4 4h16v16H4zM8.5 8.5h.01M15.5 15.5h.01M15.5 8.5h.01M8.5 15.5h.01M12 12h.01",
  check: "m5 12.5 4.5 4.5L19 7",
  copy: "M9 9h11v11H9zM5 15V4h11",
  undo: "M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
  shield: "M12 3 4.5 6v6c0 4.4 3.2 7.8 7.5 9 4.3-1.2 7.5-4.6 7.5-9V6z",
  external: "M14 4h6v6m0-6-9 9M18 14v6H4V6h6",
  search: "m20 20-4.5-4.5M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13",
  layers: "m12 3 9 5-9 5-9-5zM3 13l9 5 9-5",
};
export type IconName = keyof typeof paths;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={paths[name]} />
    </svg>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return <div role="alert" className="notice">{children}</div>;
}

export function Callout({ children }: { children: ReactNode }) {
  return <div role="status" className="callout">{children}</div>;
}

export function PageHead({ title, lead, children }: { title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {lead && <p>{lead}</p>}
      </div>
      {children && <div className="page-head-actions">{children}</div>}
    </header>
  );
}

export function Pagination({ page, pageSize, total, onPage, label }: {
  page: number; pageSize: number; total: number; onPage: (page: number) => void; label: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (!total) return null;
  return (
    <nav className="pagination" aria-label={label}>
      <span>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}</span>
      {pages > 1 && (
        <div>
          <button className="btn btn-sm" disabled={page === 1} onClick={() => onPage(page - 1)}>Previous</button>
          <span className="mono">{page} / {pages}</span>
          <button className="btn btn-sm" disabled={page === pages} onClick={() => onPage(page + 1)}>Next</button>
        </div>
      )}
    </nav>
  );
}

const method = (strategy: string) =>
  strategy === "agent" ? "Nebius agent" : strategy === "random" ? "Seeded random" : "Baseline";

export function RunRows({ runs, filtered = false }: { runs: RunSummary[]; filtered?: boolean }) {
  if (!runs.length)
    return (
      <div className="empty">
        <Icon name="layers" size={28} />
        <h3>{filtered ? "No matching runs" : "No runs yet"}</h3>
        <p>{filtered ? "Try another name or status." : "Validate a configuration and its evidence lands here."}</p>
        {!filtered && <a className="btn btn-sm" href="#/camera">New validation</a>}
      </div>
    );
  return (
    <ol className="run-list" aria-label="Saved camera-health runs">
      {runs.map((run, i) => (
        <li key={run.id} style={{ "--i": i } as CSSProperties}>
          <a href={`#/runs/${run.id}`}>
            <span className={`run-dot dot-${run.status}`} aria-hidden="true" />
            <span className="run-name">{run.request.name}</span>
            <span className="run-meta">{method(run.request.strategy)}</span>
            <time className="run-meta mono" dateTime={run.created}>
              {new Date(run.created).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </time>
            <Status value={run.status} />
            <Icon name="arrow" />
          </a>
        </li>
      ))}
    </ol>
  );
}

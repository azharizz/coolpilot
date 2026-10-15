import type { ReactNode } from "react";
import type { Configuration, Experiment, RunSummary } from "./types";

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
  return (
    <span className={`status status-${value}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function Icon({
  name,
}: {
  name: "target" | "plus" | "arrow" | "download" | "close";
}) {
  const paths = {
    target: "M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5M8 12h8m-4-4v8",
    plus: "M12 5v14M5 12h14",
    arrow: "M5 12h14m-6-6 6 6-6 6",
    download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
    close: "m6 6 12 12M6 18 18 6",
  };
  return (
    <svg
      aria-hidden="true"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={paths[name]} />
    </svg>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="notice">
      {children}
    </div>
  );
}

export const defaultConfig: Configuration = {
  width: 640,
  features: 600,
  frame_stride: 1,
  threads: 1,
  workers: 1,
  pyramid_levels: 3,
};
export const configLabels: Record<keyof Configuration, string> = {
  width: "Processing width",
  features: "Max features",
  frame_stride: "Frame stride",
  threads: "Threads per worker",
  workers: "Concurrent streams",
  pyramid_levels: "Pyramid levels",
};
export function ConfigList({ config }: { config: Configuration }) {
  return (
    <dl className="config-list">
      {Object.entries(config).map(([key, value]) => (
        <div key={key}>
          <dt>{configLabels[key as keyof Configuration]}</dt>
          <dd>
            {value}
            {key === "width" ? " px" : ""}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function experimentName(experiment: Experiment) {
  return experiment.kind === "baseline"
    ? "Reference"
    : experiment.kind === "reference_validation"
      ? "Reference validation"
      : experiment.kind === "validation"
        ? "Candidate validation"
        : `Candidate ${experiment.sequence}`;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  label,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  label: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (!total) return null;
  return (
    <nav className="pagination" aria-label={label}>
      <span>
        {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of{" "}
        {total}
      </span>
      {pages > 1 && (
        <div>
          <button
            className="button secondary"
            disabled={page === 1}
            onClick={() => onPage(page - 1)}
          >
            Previous
          </button>
          <span>
            Page {page} of {pages}
          </span>
          <button
            className="button secondary"
            disabled={page === pages}
            onClick={() => onPage(page + 1)}
          >
            Next
          </button>
        </div>
      )}
    </nav>
  );
}

export function RunRows({
  runs,
  filtered = false,
}: {
  runs: RunSummary[];
  filtered?: boolean;
}) {
  if (!runs.length)
    return (
      <div className="empty-state">
        <h3>
          {filtered ? "No matching runs" : "Your first result starts here"}
        </h3>
        <p>
          {filtered
            ? "Try another name or status."
            : "Start an optimization above. Your results will be saved here."}
        </p>
      </div>
    );
  return (
    <div className="table-scroll">
      <table className="history-table">
        <caption className="sr-only">Saved optimization runs</caption>
        <thead>
          <tr>
            <th>Run</th>
            <th>Method</th>
            <th>Created</th>
            <th>Status</th>
            <th>
              <span className="sr-only">Open run</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <th scope="row">
                <a href={`#/runs/${run.id}`}>{run.request.name}</a>
              </th>
              <td>
                {run.request.strategy === "agent"
                  ? "Nebius agent"
                  : run.request.strategy === "random"
                    ? "Random search"
                    : "Baseline"}
              </td>
              <td>
                <time dateTime={run.created}>
                  {new Date(run.created).toLocaleString(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </td>
              <td>
                <Status value={run.status} />
              </td>
              <td>
                <a
                  href={`#/runs/${run.id}`}
                  aria-label={`Open ${run.request.name}`}
                >
                  <Icon name="arrow" />
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

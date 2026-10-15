import type { CSSProperties, ReactNode } from "react";

// Wedge from the camera origin, angles in degrees from straight ahead (negative = left).
function wedge(cx: number, cy: number, r: number, from: number, to: number) {
  const point = (a: number) => {
    const rad = ((a - 90) * Math.PI) / 180;
    return `${(cx + r * Math.cos(rad)).toFixed(1)} ${(cy + r * Math.sin(rad)).toFixed(1)}`;
  };
  return `M${cx} ${cy} L${point(from)} A${r} ${r} 0 0 1 ${point(to)} Z`;
}

const CX = 260, CY = 352, R = 330;
const cones = [
  { id: "l", label: "Left", from: -58, to: -8, tag: [-33] },
  { id: "c", label: "Centre", from: -24, to: 24, tag: [0] },
  { id: "r", label: "Right", from: 8, to: 58, tag: [33] },
] as const;

/** Illustration: ego vehicle with three overlapping forward camera fields and a scanning pulse. */
export function SensorField() {
  return (
    <figure className="sensor-field">
      <svg viewBox="0 0 520 470" role="img" aria-label="Illustration: a vehicle seen from above with three overlapping forward camera fields, left, centre and right. A pulse sweeps through each field; the right field briefly flags a suspected fault, then recovers.">
        <defs>
          <radialGradient id="cone-fill" cx={CX} cy={CY} r={R} gradientUnits="userSpaceOnUse">
            <stop offset="0" style={{ stopColor: "var(--blue)" }} stopOpacity="0.38" />
            <stop offset="1" style={{ stopColor: "var(--blue)" }} stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cone-alarm" cx={CX} cy={CY} r={R} gradientUnits="userSpaceOnUse">
            <stop offset="0" style={{ stopColor: "var(--red)" }} stopOpacity="0.5" />
            <stop offset="1" style={{ stopColor: "var(--red)" }} stopOpacity="0" />
          </radialGradient>
          <clipPath id="fov-clip">
            <path d={wedge(CX, CY, R, -58, 58)} />
          </clipPath>
        </defs>

        {/* Road: lane markings stream toward the viewer. */}
        <g className="sf-road">
          <path d="M120 0 V470 M400 0 V470" />
          <path className="sf-lane" d="M213 -40 V470 M307 -40 V470" />
        </g>

        {/* Range rings, unlabelled: geometry only. */}
        <g className="sf-rings" clipPath="url(#fov-clip)">
          {[90, 170, 250, 330].map(r => <circle key={r} cx={CX} cy={CY} r={r} />)}
        </g>

        {cones.map(c => (
          <g key={c.id} className={`sf-cone sf-cone-${c.id}`}>
            <path className="sf-cone-base" d={wedge(CX, CY, R, c.from, c.to)} fill="url(#cone-fill)" />
            {c.id === "r" && <path className="sf-cone-alarm" d={wedge(CX, CY, R, c.from, c.to)} fill="url(#cone-alarm)" />}
            <path className="sf-cone-edge" d={wedge(CX, CY, R, c.from, c.to)} />
          </g>
        ))}

        {/* Expanding scan pulses inside the combined field of view. */}
        <g clipPath="url(#fov-clip)" className="sf-pulses">
          {[0, 1, 2].map(i => <circle key={i} cx={CX} cy={CY} r="330" style={{ "--d": `${i * 1.2}s` } as CSSProperties} />)}
        </g>

        {/* Lead vehicle ahead, tracked by the centre field. */}
        <g className="sf-lead">
          <rect x="241" y="112" width="38" height="62" rx="9" />
          <path className="sf-lead-box" d="M232 104h10M232 104v10M288 104h-10M288 104v10M232 182h10M232 182v-10M288 182h-10M288 182v-10" />
        </g>

        {/* Ego vehicle. */}
        <g className="sf-ego">
          <rect x="226" y="340" width="68" height="118" rx="20" />
          <path className="sf-glass" d="M236 372 Q260 360 284 372 L280 392 Q260 386 240 392Z" />
          <path className="sf-glass" d="M240 432 Q260 438 280 432 L282 446 Q260 452 238 446Z" />
          <circle className="sf-cam" cx={CX} cy={CY} r="4.5" />
        </g>

        <g className="sf-labels">
          {cones.map(c => {
            const a = ((c.tag[0] - 90) * Math.PI) / 180;
            const x = CX + 300 * Math.cos(a), y = CY + 300 * Math.sin(a) + 4;
            return (
              <g key={c.id} transform={`translate(${x.toFixed(0)} ${y.toFixed(0)})`} className={`sf-tag sf-tag-${c.id}`}>
                <rect x="-46" y="-15" width="92" height="30" rx="15" />
                <circle className="sf-tag-dot" cx="-30" cy="0" r="4" />
                <text x="-20" y="4.5">{c.label}</text>
              </g>
            );
          })}
        </g>
      </svg>
      <figcaption>
        <span><i className="key key-ok" /> On time</span>
        <span><i className="key key-alarm" /> Suspected fault</span>
        <span className="sf-note">Overlapping forward views, not surround coverage</span>
      </figcaption>
    </figure>
  );
}

type Node = { title: string; detail: string; tone?: "blue" | "green" | "red" | "muted"; visual?: ReactNode };

function RegionPulse() {
  return (
    <span className="region-pulse" aria-hidden="true">
      {Array.from({ length: 16 }, (_, i) => <i key={i} style={{ "--d": `${((i * 7) % 16) * 0.18}s` } as CSSProperties} />)}
    </span>
  );
}

/** How a frame travels: replay, OpenCV analysis, two independent channels, frozen gates, evidence. */
export function PipelineFlow() {
  const nodes: (Node | [Node, Node])[] = [
    { title: "Recorded feeds", detail: "Three views, timestamp paced", tone: "muted" },
    { title: "OpenCV analysis", detail: "4 × 4 regions: detail, brightness, clipping", tone: "blue", visual: <RegionPulse /> },
    [
      { title: "Pipeline", detail: "Freshness, drops, backlog", tone: "blue" },
      { title: "Image", detail: "Blur, glare, dark, obstruction, freeze", tone: "green" },
    ],
    { title: "Frozen gates", detail: "Recall, detection time, false alarms", tone: "red" },
    { title: "Evidence", detail: "Every run kept and exportable", tone: "muted" },
  ];
  return (
    <figure className="flow" aria-label="Processing pipeline">
      {nodes.map((node, i) => (
        <div className="flow-step" key={i} style={{ "--i": i } as CSSProperties}>
          {i > 0 && <span className="flow-link" aria-hidden="true"><i /></span>}
          {Array.isArray(node) ? (
            <div className="flow-fork">{node.map(n => <FlowNode key={n.title} node={n} />)}</div>
          ) : <FlowNode node={node} />}
        </div>
      ))}
    </figure>
  );
}

function FlowNode({ node }: { node: Node }) {
  return (
    <div className={`flow-node tone-${node.tone ?? "muted"}`}>
      {node.visual}
      <strong>{node.title}</strong>
      <span>{node.detail}</span>
    </div>
  );
}

/** Vertical stack diagram for the runtime page; a missing layer renders as a dashed, inactive node. */
export function RuntimeStack({ layers }: { layers: { title: string; value: string; active: boolean; note?: string }[] }) {
  return (
    <ol className="stack" aria-label="Runtime stack">
      {layers.map((layer, i) => (
        <li key={layer.title} className={layer.active ? "is-on" : "is-off"} style={{ "--i": i } as CSSProperties}>
          <span className="stack-dot" aria-hidden="true" />
          <div>
            <small>{layer.title}</small>
            <strong>{layer.value}</strong>
            {layer.note && <span>{layer.note}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

# COOLPilot interface

<!-- impeccable:design-schema 1 -->

## Direction

Night-drive instrument cluster. Graphite surfaces (`--bg #06080b`, `--panel #0d1117`), white primary actions, Poppins 400 to 700 self-hosted, and a system mono stack only for measurements. The COOLPilot mark (green, blue and red chevrons) is unchanged and supplies the only signal colours: green means on time or passed, red means alarm or rejected, blue means active, selected or analysed. Amber marks development-only or interrupted states. Tokens live on `:root` in `web/src/style.css`.

## Hierarchy

Navigation: Overview, Live replay, Validate, History, Runtime. A runtime chip in the top bar shows the actual distribution, OpenCV version and architecture.

Overview: headline, two actions (live replay, validate) and runtime facts beside an animated top-down diagram of three overlapping forward camera fields. Below are the three source recordings in HUD frames, the processing pipeline diagram (feeds, OpenCV 4 × 4 regions, separate Pipeline and Image channels, frozen gates, evidence) and recent runs.

Live replay: control deck, chart and region-overlay lenses, three camera monitors and a sticky transport bar with per-camera injection marks. Each monitor shows the analysed frame with HUD status pills, an optional 4 × 4 region heatmap over the frame, Pipeline and Image readouts, status tracks, three charts and collapsible diagnostics.

Validate: three numbered steps (recordings, search, acceptance limits), with a sticky contract summary and the run button. Run detail: verdict banner, action bar, experiment board with CPU bars, gate meter with failures first, per-fault table, and recorded playback with region overlay and annotated, detected, pipeline and image tracks.

## Motion

Motion conveys state: live scan line and alarm glow on monitors, breathing status dots, flowing packets in pipeline and runtime diagrams, bar growth on data. The Overview diagram is the one authored showcase (lane flow, scan pulses, a periodic illustrative fault on the right field). Everything collapses under `prefers-reduced-motion`; source previews then show native controls instead of autoplaying.

## Truth constraints

Diagrams are labelled illustrations; every number on screen comes from actual execution. Overlapping forward views are never described as surround coverage. Pipeline and image health stay separate. Development-only evidence cannot authorize apply. The footer states once that this is not validated for driving decisions or vehicle control. No em dashes in copy.

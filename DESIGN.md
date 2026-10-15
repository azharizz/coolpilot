# COOLPilot interface

<!-- impeccable:design-schema 1 -->

## Direction

Desktop operating interface using the user-selected OpenCV visual language. The official homepage was inspected directly on 2026-09-20, including a browser screenshot and computed typography. Reference capture: `.impeccable/review/revamp/opencv-reference.png`.

Black navigation and start surface, white working surfaces, charcoal text, Poppins typography, compact rectangular buttons and OpenCV blue links. Poppins 400/500/600/700 is self-hosted with its OFL license. The custom COOLPilot mark uses three open RGB rings and a pilot arrow. It is a COOLPilot identity, not an assertion of official OpenCV ownership.

## Hierarchy

Navigation contains Overview, Validate cameras, Compare cameras, History and Runtime. Overview presents three real source-video previews, replay/validation entrypoints, actual COOL availability and camera-only recent history. Validation defaults to a local baseline; external agent or image-review requests are explicit choices.

The Overview hero retains the black start surface: white heading and primary action, outlined secondary action, light supporting text and three source recordings. History and the other working surfaces remain white.

Camera runs expose passed and rejected gates, per-fault results, recorded evidence playback, regional measurements and exports. Apply and rollback change only the stored workbench configuration. Development-only evidence cannot authorize either a driving decision or configuration promotion.

Edit setup prefills camera fields, excluding retired tracking settings. Hash links make runs bookmarkable and support browser back/forward. Historic tracking rows remain archived on disk but are not part of the active UI.

## Interaction and accessibility

React state and native controls own interaction. There are no effects, DOM styling mutations or custom menu widgets. A ref moves keyboard focus for the skip link without changing the hash route. Native details progressively reveal settings. All controls have labels and focus indicators, and statuses include readable text. Animation is limited to a running-state pulse and short control transitions, respecting reduced-motion preferences.

Recorded replay separates Pipeline and Image channels and labels synthetic injection independently. Scrubbing uses measured historical samples; missing or stale evidence remains unknown. Regions and charts show measurements, not validated safety judgments. Native video controls show the original source views on Overview.

## Scope and review

Desktop retains the compact OpenCV-inspired layout; narrow screens stack video previews and runtime details. Source videos, local heuristics and safety gates are unchanged by the camera-only homepage cutover.

No stock imagery, fabricated acceleration or certified-safety claims. `UX_REVAMP.md`, `RESEARCH_AND_PLAN.md`, old screenshots and `video/` retain historical tracking-era material; they do not describe the current camera-only application.

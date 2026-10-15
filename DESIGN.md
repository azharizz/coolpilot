# COOLPilot interface

<!-- impeccable:design-schema 1 -->

## Direction

Desktop operating interface using the user-selected OpenCV visual language. The official homepage was inspected directly on 2026-09-20, including a browser screenshot and computed typography. Reference capture: `.impeccable/review/revamp/opencv-reference.png`.

Black navigation and start surface, white working surfaces, charcoal text, Poppins typography, compact rectangular buttons and OpenCV blue links. Poppins 400/500/600/700 is self-hosted with its OFL license. The custom COOLPilot mark uses three open RGB rings and a pilot arrow. It is a COOLPilot identity, not an assertion of official OpenCV ownership.

## Hierarchy

The main navigation contains Optimize, History and Runtime. Optimize has one primary start action with no required field entry. Native Customize details contain the existing editable contract and budget. The default uses the real Nebius optimizer and the real annotated CTU dataset. Recent history is limited to three rows; full history supports server-side name search, status filtering and eight-row pages without the previous 100-run visibility ceiling.

Run pages lead with the validation outcome and an actionable recommendation. A before/after comparison uses the reference validation and recommended validation from the same run and split. A retained reference does not claim an improvement. Aggregate throughput is identified as throughput, never live camera fps. Result, Experiments and Agent notes separate evidence from diagnostics. Experiments use six-row pages; notes use four-item pages. Repetitions have the existing ten-item maximum and sit inside collapsed measurement details.

Run again posts the stored request to the existing coordinator. Edit setup prefills the optional form. Hash links make runs bookmarkable and support browser back/forward. Applying a recommendation still changes only the real local workload configuration; rollback and execution remain in Runtime.

## Interaction and accessibility

React state and native controls own interaction. There are no effects, DOM styling mutations or custom menu widgets. A ref moves keyboard focus for the skip link without changing the hash route. Native details progressively reveal settings. All controls have labels and focus indicators, and statuses include readable text. Animation is limited to a running-state pulse and short control transitions, respecting reduced-motion preferences.

Real frames and stored geometry share the same index. Overlays are withheld while the requested frame loads. Dashed white identifies ground truth, green the predicted polygon. Toggles and scrubbing remain available. Quality limits and measured values sit next to the image. Stage comparisons use a reference from the same clip.

## Scope and review

Desktop is the requested target. The page preserves a 720 px minimum working width; a new mobile layout is deliberately outside this revision. The benchmark engine, Nebius contract, safety gates and datasets remain unchanged.

The user's chosen OpenCV visual system overrides generic design preferences. Review against the Impeccable 67-pattern catalog focuses on unnecessary cards, overdecorated controls, vague copy and diagnostic overload. No marketing carousel, stock imagery, decorative gradients, artificial progress percentages or invented metrics are included. Visual review and test status for this revision are recorded in `UX_REVAMP.md`; earlier review artifacts describe the prior interface.

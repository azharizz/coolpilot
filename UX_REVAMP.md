# COOLPilot desktop simplification

> Historical tracking UI revision. The current homepage and navigation are camera-only; see `DESIGN.md`, `README.md` and `IMPROVEMENT_PLAN.md`. Screenshots and tracking-era results below are archival.

Date: 2026-09-20

## Problems confirmed

The prior desktop screenshot put a long run-history rail and the full experiment ledger before the recommendation. Starting a run exposed naming, strategy, quality and budget fields before the user could act. History had no pagination and silently stopped at 100 runs. Evidence, timings, quality, configuration, frontier and model notes stacked into one long page. The visual system did not match the user's OpenCV reference.

## Decision

Two approaches were considered:

1. Progressive disclosure around the real start-to-result workflow. Keep full controls, but make one click sufficient to start; lead with the validated result and paginate supporting records.
2. A new workload-upload flow with annotation ingestion, dataset management and isolation. This would require a new data contract and a separate validated execution path.

Implement approach 1 for this revision. It directly resolves the confirmed friction without pretending that arbitrary uploads are supported. The scope question was offered asynchronously; no upload selection had been received when implementation began.

## Reference and implementation

- [OpenCV official homepage](https://opencv.org/): black header and primary surface, white content, Poppins, blue links, RGB logo family, rectangular buttons and short hover transitions.
- Screenshot: `.impeccable/review/revamp/opencv-reference.png`.
- Self-hosted font source: the homepage's Poppins CSS; license retained in `web/public/fonts/OFL.txt` from the Google Fonts Poppins package.
- Custom COOLPilot RGB ring/pilot mark and favicon.
- Start with zero required edits. Customize and reuse any existing request.
- Same-run, held-out before/after comparison above supporting measurements.
- Three recent runs, eight-row server history with search/status filters, six-row experiments, four-item reasoning pages.
- Stable run links, repeat-run action, clearly scoped apply operation, original evidence export and rollback retained.
- Tracking preview keeps image and overlay aligned during frame loading.

## Completion and verification boundary

All frontend and API pagination code is implemented before verification begins. A single pagination/API-boundary check is added to the existing unit suite. The benchmark engine and provider behavior are unchanged.

The user explicitly asked not to run tests yet. Unit, integration and live benchmark tests are deferred. A production build is needed to render the requested desktop screenshots; screenshot review is visual inspection and will not start optimization, apply configurations, or create benchmark evidence. No test pass from the previous revision certifies this revision.

## Desktop visual review

The final production build passed TypeScript compilation and Vite bundling in ARM Docker. The Impeccable detector exited successfully with no emitted findings. This is not a functional test result.

The first screenshot pass at the browser's native desktop viewport (1163 × 654 CSS pixels) covered home, saved results, history and runtime. It exposed italic font binaries mistakenly selected from the source's multi-style CSS; these were replaced with normal-style Poppins. The result heading and comparison spacing were tightened, an unnecessary back link was removed, and the applied-state button was made more readable. The confirmation screenshots show the corrected upright fonts and compact layout. The replacement font files use new URLs so existing browser font caches cannot preserve the old italic assets. The app uses existing recorded evidence; no new run, promotion or benchmark was performed for the review.

Screenshots live in `.impeccable/review/revamp/`. The standalone font source remains OpenCV's published CSS; the local binaries are its normal Latin 400, 500, 600 and 700 faces. Unit and live tests remain deferred.

## Handoff

The Docker service is running and healthy at http://127.0.0.1:8769. No functional test or live benchmark was run during this revision. Existing run history and active experiment #39 were preserved.

- `home.png`: one primary start action, Customize collapsed.
- `result.png`: held-out decision and before/after comparison.
- `result-evidence.png`: real source frame, stored polygon overlays and quality limits.
- `history.png` and `history-pagination.png`: compact rows and bounded page navigation.
- `runtime.png`: local runtime and active configuration.

All capture paths are relative to `.impeccable/review/revamp/`. These are native desktop viewport captures, not mockups.

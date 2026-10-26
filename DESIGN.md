# SagaAgent studio design

Mode: Operate. A desktop operations workbench that remains usable on mobile. The phase specification supplies the task, information architecture and interactions; this records implementation choices without adding product claims.

Use warm white work surfaces, slate text, a restrained pine-green action color and amber/red uncertainty and failure states. IBM Plex Sans supplies readable UI lettering; fixed-width system text is reserved for hashes, IDs and JSON. Fonts are bundled locally. Borders and aligned rows organize the work; shadows are reserved for the inspector drawer.

Keep the guided scenarios immediately visible. Place RFQ launch controls in a compact left workspace and the run status, revision pipelines and resource tables in the main area. Approval and sandbox actions follow the trace. Node statuses and action feedback use explicit text in addition to color. The inspector is a focus-managed native dialog with a chronological attempt list and complete payload/evidence JSON.

Use visible labels, keyboard focus, native forms, polite progress announcements, actionable errors, reduced-motion support, responsive grids and contained table scrolling. Preserve entered form data on errors. Disable conflicting commands while an invocation is pending. No page-level horizontal scrolling, external font requests, decorative charts or fabricated data.

## Visual refinement — 2026-10-26

Use a 15px base, 14–15px step names and at least 12px supporting UI text. Darken secondary text and increase control heights to 44px on desktop and 46px on mobile. Keep headings, quote totals and task actions visually distinct from diagnostic metadata.

The run header carries a contextual action panel: review, reconcile, resume, inspect a failed step, or read a terminal outcome. Review quote moves keyboard focus to the approval section without approving. Highlight the step requiring attention with a stronger outline and explicit text; distinguish recovered writes with a Reconciled label based on verification_evidence.status=APPLIED. Runtime statuses stay visible alongside these explanations.

Connect the six steps with directional lines. Use a horizontal pipeline when its container exceeds 830px, and a vertical timeline below that width. Compensated history remains visible with a separate tone. A single short transition accompanies the current-action panel, and reduced-motion preferences disable it.

At viewport widths of 760px or less, collapse the creation form after a trace loads and allow explicit reopening without losing input. Keep all five scenarios visible in a compact two-column grid; hide their supplementary descriptions while retaining the action names and active scenario instructions. Tables retain contained scrolling so financial values and record columns stay readable.

## Task and company workspaces — 2026-10-27

Keep the same typography, pine-green palette, semantic state colors and keyboard focus rules. The task workspace has an objective/source/mode form beside a task outcome, human approval, evidence checks and chronological observations. Show whether a real model was called. Clarification is an inline continuation of the same persisted task. Keep the company-record view separate and link to the durable trace rather than duplicating its diagnostics. Use one-column stacking with explicit zero-minimum grid tracks and wrapped record IDs on mobile.

# Glossary

These terms are used throughout the documentation.

| Term | Definition |
|------|------------|
| **QC record** | One unit of review: a single participant and session. |
| **QC page** | The page that shows one QC record, with one or more QC tasks. |
| **QC task** | A named set of files to review, defined as one top-level key in `qc.json`. |
| **Pipeline** | The neuroimaging pipeline whose outputs are being reviewed. |
| **Panel** | One of the three optional views on a QC page: 3D MRI (NiiVue viewer), Montage, or QC Metrics (IQM distributions). See [Display panels](../guides/configuration.md#display-panels). |
| **Montage** | A 2D grid of images (SVG, PNG, JPG/JPEG). |
| **IQM** | Image quality metric, typically an MRIQC group-level table or a per-participant JSON sidecar, shown as a distribution plot. |
| **Rating** | A QC decision (by default **PASS**, **FAIL**, or **UNCERTAIN**), recorded per QC task per QC record. See also [Rating schemes](../guides/ratings.md). |
| **Facet** | A named aspect of the image (such as motion) or a brain region, rated separately in a multi-facet task. |
| **Checkpoint** | A timestamped snapshot of the current QC records, which can be loaded later to resume. |
| **Autoplay** | Timed auto-advance from one QC page to the next. See [Autoplay](../guides/autoplay.md). |
| **Evidence bundle** | The exported QC evidence for one scan: `bundle.json`, `PACKAGE.md` and 2D views. See [Evidence bundle export](../guides/evidence_bundle.md). |
| **Protocol signature** | The rounded acquisition fields that define which scans are comparable. |
| **Acquisition deviation** | A protocol-signature field whose value differs from the most common value for that suffix. |
| **Support tier** | How an evidence bundle interprets a scan's IQMs: `supported`, `fallback` or `unsupported`. |

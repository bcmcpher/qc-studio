# Rating schemes

Each QC task in `qc.json` is rated using one of two schemes:

| Scheme | What you rate | Typical use |
|--------|---------------|-------------|
| **Single** (default) | One overall rating per QC task | Quick pass/fail screening |
| **Multi-facet** | One rating per *facet*, i.e. a named aspect of the image | Detailed QC, e.g. rating motion, ringing and cropping separately, or rating multiple brain regions from the same QC task |

## Configuration

The rating scheme is set per task with the optional `rating` field in `qc.json`.
If it is omitted, the task uses a single PASS / FAIL / UNCERTAIN rating.
See [Rating fields](configuration.md#rating-fields) for the available options and an example.

## Multi-facet rating interface

For a multi-facet task, the **📊 Rate** section of the QC page has:

- one rating choice for each facet
- an **Apply same rating to all facets** option that sets every facet at once. You can then change individual facets as needed.

Each QC record also gets an overall rating based on the set of facet ratings:

| Overall rating | Meaning |
|----------------|---------|
| **All-Pass** | Every facet is PASS |
| **All-Fail** | Every facet is FAIL |
| **All-Uncertain** | Every facet is UNCERTAIN |
| **Mixed** | Every facet is rated, but not all the same |

For how facet ratings are written to the results file, see [Exported results](configuration.md#exported-results-tsv).

## Default rating

To speed up rating, QC-Studio allows preselecting a rating on pages you haven't rated yet.
For multi-facet tasks, every facet is preselected.

This can be configured in two places:

- **At launch**, with `--default_qc_rating` (`PASS`, `FAIL`, `UNCERTAIN` or `None`). The default is **PASS**.
- **On the landing page**, under **Default QC rating** in the sidebar. Choose `None` to leave everything unselected until you rate it.

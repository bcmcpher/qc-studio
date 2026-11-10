# Fetching MRIQC reference data

## Why we need reference data

Image Quality Metrics (IQMs) are quantitative measures derived from image
data that help characterize image quality and support the QC process.
On their own, however, raw IQM values are hard to interpret — a single
number tells you very little without something to compare it against.

One way to make IQMs meaningful is to compare each subject's values to a
baseline distribution. IQM ranges are sensitive to scanner manufacturer,
magnetic field strength, sequence parameters, and other acquisition
factors, so the choice of baseline matters. Comparing only against the
current dataset is often not informative either, especially when the
dataset is small.

The [NIH MRIQC Web API](https://mriqc.nimh.nih.gov/) exposes a large
public collection of IQMs across many datasets and modalities, which
makes it a natural reference population. QC-Studio uses this data in two
ways:

- **Visually**, to overlay reference distributions on the IQM viewer so
  reviewers can see where a subject falls relative to a large
  manufacturer-matched population.
- **As input to downstream summarization**, providing population-level
  statistics that an LLM can use to better judge data quality.

Because the API is slow and paginated, we don't query it live. Instead,
this script downloads the data once and saves it to disk, so QC-Studio
can read from local TSVs.

## What the script does

`scripts/fetch_mriqc_reference.py` pages through the MRIQC Web API for
each modality in `MODALITIES` (currently `T1w` and `bold`) and writes
one TSV per modality. For each record it keeps the IQM columns and
lifts a few `bids_meta` fields — `Manufacturer`,
`MagneticFieldStrength`, and `ManufacturersModelName` — into top-level
columns so they can be used as filters when building reference
distributions.

Rows are appended to the output TSV as each page is fetched, so partial
progress survives interruptions. The script also writes a log file and,
if any pages failed after retries, a JSON failure log.

## Location

```
scripts/fetch_mriqc_reference.py
```

Run from the QC-Studio repository root.

## Running the script

```bash
python scripts/fetch_mriqc_reference.py --output_dir reference_data/
```

### Arguments

| Argument | Default | Description |
| --- | --- | --- |
| `--output_dir`, `-o` | `reference_data` | Directory where output files are written. Created if it does not exist. |

### Configuration

Behavior is controlled by module-level constants at the top of the
script:

| Constant | Purpose |
| --- | --- |
| `MODALITIES` | Which modalities to download (default: `["T1w", "bold"]`). |
| `BIDS_METADATA_FIELDS` | `bids_meta` keys lifted into top-level columns. |
| `MAX_RESULTS_PER_PAGE` | Page size requested from the API. |
| `REQUEST_DELAY_SECONDS` | Delay between successful requests, to be polite to the API. |
| `MAX_RETRIES_PER_PAGE` | How many times a failing page is retried before being recorded as a failure. |
| `BACKOFF_BASE_SECONDS` | Base for exponential backoff between retries. |

### Requirements

Standard Python data stack: `requests` and `pandas`. No API key is
required — the MRIQC endpoint is public.

## Output

All output goes into `--output_dir`. For the default arguments:

```
reference_data/
├── group_T1w.tsv               # T1w reference IQMs
├── group_bold.tsv              # BOLD reference IQMs
├── fetch_mriqc_reference.log   # Run log (console output mirrored here)
└── fetch_failures.json         # Only written if any pages failed after retries
```

Each `group_<modality>.tsv` is a tab-separated table with one row per
record returned by the API. It contains the IQM columns plus the
lifted `bids_meta` columns (`Manufacturer`, `MagneticFieldStrength`,
`ManufacturersModelName`). Existing files at these paths are deleted
at the start of a run, so each run produces a fresh snapshot.

## Where to store the generated files

QC-Studio expects the reference TSVs at a known location so the IQM
distribution viewer can load them. Place the generated `group_*.tsv`
files in the QC-Studio reference data directory (the path QC-Studio
reads from when building manufacturer-filtered reference distributions).
The log and failure JSON are not needed at runtime and can be kept
alongside the TSVs or archived separately.

## How QC-Studio uses the data

The IQM distribution viewer (`iqm_viewer.py`) loads the
`group_<modality>.tsv` for the relevant modality and uses the
`Manufacturer` column to build a manufacturer-matched reference
distribution for each IQM. The current subject's value is then
overlaid on that distribution so reviewers can see where it falls
relative to a large external population. The MRIQC reference
distributions are kept strictly separate from the IQM pipeline SVGs.

## Future follow-ups

These are intentionally out of scope for this first pass and can be
tracked as separate issues:

- Document the MRIQC API endpoints and query parameters.
- Document the output schema and the full list of expected columns per
  modality.
- Document caching strategy and rate-limit handling (currently a
  fixed inter-request delay plus exponential backoff on retry).
- Define when reference data should be refreshed (e.g. on a schedule,
  or when the MRIQC dataset is known to have grown meaningfully).
- Add basic validation checks that the generated TSVs are well-formed
  (expected columns present, non-empty, no obviously malformed rows)
  before they are used downstream.

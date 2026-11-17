# MRI QC Evidence Package

- **Participant:** {participant_id}
- **Session:** {session_id}
- **Pipeline / QC task:** {pipeline} / {qc_task}
- **Scan:** {bids_name}
- **Suffix:** {suffix} (support: {support})

{support_text}

## Acquisition

| Group | Field | Value |
|---|---|---|
{acquisition_table}

### Acquisition deviations

{deviations}

## Comparison distributions

{project}
{reference}

## Metrics

Flagged metrics: {flagged}

| Metric | Value | Direction of concern | Evidence strength | Project percentile | Reference percentile | Flags | Context category |
|---|---|---|---|---|---|---|---|
{metric_rows}

### Outlier score

{outlier}

## Views

{views}

## Rater QC

{rater_qc}

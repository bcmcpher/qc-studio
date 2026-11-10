#!/usr/bin/env bash
# Run QC-Studio against bundled XCP-D sample data (invoke from this directory: cd ui && ./xcpd_test.sh)
#
# Optional arguments:
#   $1 — path to qc.json (default: ../pipelines/xcpd/qc.json)
#   $2 — qc_task name (default: atlas_coverage_qc). Same as env QC_TASK. Use "all" for every task in qc.json on one page.
# Examples:
#   ./xcpd_test.sh
#   ./xcpd_test.sh ../pipelines/xcpd/qc.json atlas_coverage_qc
#   ./xcpd_test.sh ../pipelines/xcpd/qc.json all
#   QC_TASK=coreg_wf_qc ./xcpd_test.sh

set -euo pipefail

qc_launch_script="main.py"
qc_pipeline="xcpd"
qc_json="${1:-${QC_JSON:-../pipelines/xcpd/qc.json}}"
qc_task="${2:-${QC_TASK:-atlas_coverage_qc}}"
dataset_dir="../sample_data"
participant_list="../sample_data/qc_participants.tsv"
output_dir="./output"
port_number="${PORT:-8501}"
# Comma-separated BIDS sessions (one QC "page" per participant × session)
session_list="${SESSION_LIST:-ses-01}"

echo "Using qc_json=${qc_json}  qc_task=${qc_task}  port=${port_number}  session_list=${session_list}"
if [[ "${qc_task}" != "all" && "${qc_task}" != "ALL" ]]; then
	echo "Tip: for every task in qc.json on one page, run:  QC_TASK=all $0  or  $0 \"${qc_json}\" all"
fi

streamlit run "$qc_launch_script" --server.port="$port_number" -- \
  --qc_json "$qc_json" \
  --qc_task "$qc_task" \
  --qc_pipeline "$qc_pipeline" \
  --dataset_dir "$dataset_dir" \
  --participant_list "$participant_list" \
  --session_list "$session_list" \
  --output_dir "$output_dir"

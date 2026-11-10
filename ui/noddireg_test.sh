#!/usr/bin/env bash
# Run QC-Studio with noddireg qc.json (invoke: cd ui && ./noddireg_test.sh)
#
# Optional arguments:
#   $1 — path to qc.json (default: ../pipelines/noddireg/qc.json)
#   $2 — qc_task name (default: noddireg_density). Same as env QC_TASK. Use "all" for every task in qc.json on one page.
# Examples:
#   ./noddireg_test.sh
#   ./noddireg_test.sh ../pipelines/noddireg/qc.json noddireg_od_icvf_isovf
#   ./noddireg_test.sh ../pipelines/noddireg/qc.json all
#
# Point --dataset_dir at the BIDS dataset root (see sample_data/README.md).

set -euo pipefail

qc_launch_script="main.py"
qc_pipeline="noddireg"
qc_json="${1:-${QC_JSON:-../pipelines/noddireg/qc.json}}"
qc_task="${2:-${QC_TASK:-noddireg_density}}"
dataset_dir="../sample_data"
participant_list="../sample_data/qc_participants.tsv"
output_dir="./output"
port_number="${PORT:-8501}"
session_list="${SESSION_LIST:-ses-01,ses-02}"

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

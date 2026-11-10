#!/usr/bin/env bash
# Run QC-Studio against bundled QSIPrep sample data (invoke from this directory: cd ui && ./qsiprep_test.sh)
#
# Optional arguments:
#   $1 — path to qc.json (default: ../pipelines/qsiprep/qc.json)
#   $2 — qc_task name (default: seg_brainmask_qc). Same as env QC_TASK. Use "all" for every task in qc.json on one page.
# Examples:
#   ./qsiprep_test.sh
#   ./qsiprep_test.sh ../pipelines/qsiprep/qc.json sdc_wf_qc
#   ./qsiprep_test.sh ../pipelines/qsiprep/qc.json all
#   QC_TASK=coreg_wf_qc ./qsiprep_test.sh

set -euo pipefail

qc_launch_script="main.py"
qc_pipeline="qsiprep"
qc_json="${1:-${QC_JSON:-../pipelines/qsiprep/qc.json}}"
qc_task="${2:-${QC_TASK:-seg_brainmask_qc}}"
dataset_dir="../sample_data"
participant_list="../sample_data/qc_participants.tsv"
output_dir="./output"
port_number="${PORT:-8501}"
session_list="${SESSION_LIST:-ses-01,ses-02}"

echo "Using qc_json=${qc_json}  qc_task=${qc_task}  port=${port_number}  session_list=${session_list}"
if [[ "${qc_task}" != "all" && "${qc_task}" != "ALL" ]]; then
	echo "Tip: for every task in qc.json on one page, run:  QC_TASK=all $0  or  $0 \"${qc_json}\" all"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_STREAMLIT="${SCRIPT_DIR}/../.venv/bin/streamlit"
if [[ -x "${VENV_STREAMLIT}" ]]; then
	STREAMLIT_CMD="${VENV_STREAMLIT}"
elif command -v streamlit >/dev/null 2>&1; then
	STREAMLIT_CMD="streamlit"
else
	echo "❌ streamlit not found. Activate the project venv first:"
	echo "   cd ${SCRIPT_DIR}/.. && source .venv/bin/activate && pip install -r requirements.txt"
	exit 1
fi

"${STREAMLIT_CMD}" run "$qc_launch_script" --server.port="$port_number" -- \
  --qc_json "$qc_json" \
  --qc_task "$qc_task" \
  --qc_pipeline "$qc_pipeline" \
  --dataset_dir "$dataset_dir" \
  --participant_list "$participant_list" \
  --session_list "$session_list" \
  --output_dir "$output_dir"

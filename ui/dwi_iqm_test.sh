#!/usr/bin/env bash
# Run QC-Studio against bundled MRIQC DWI sample data (invoke from anywhere, e.g. ./ui/dwi_iqm_test.sh)
#
# Purpose of this test — three things it exercises together:
#   1. DWI modality — the only *_test.sh script covering the DWI IQM viewer
#      (multi-shell metrics like efc_shell01, bValues, snr_cc_shell1_best).
#   2. Group TSV + per-subject JSON, in the same run — dwi_iqm_test_qc.json's
#      iqm_path lists BOTH group_dwi.tsv (group distribution plot) and a
#      per-subject dwi.json sidecar (metrics-table view), so both tabs
#      render for the same qc_task.
#   3. Multi-session with one missing — sub-CMH0003 only has ses-02 DWI data;
#      both sessions are requested on purpose to exercise the app's handling
#      of a participant missing one of the requested sessions.
#
# Uses ../pipelines/mriqc/dwi_iqm_test_qc.json — not a real pipeline config
# (group_dwi.tsv/dwi.json aren't wired into pipelines/qsiprep/qc.json yet),
# but committed alongside this script so the test is reproducible.
#
# Optional arguments:
#   $1 — path to qc.json (default: ../pipelines/mriqc/dwi_iqm_test_qc.json)
#   $2 — qc_task name (default: dwi_iqm_qc). Same as env QC_TASK.
# Examples:
#   ./dwi_iqm_test.sh
#   PORT=8502 ./dwi_iqm_test.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

qc_launch_script="main.py"
qc_pipeline="mriqc"
qc_json="${1:-${QC_JSON:-${SCRIPT_DIR}/../pipelines/mriqc/dwi_iqm_test_qc.json}}"
qc_task="${2:-${QC_TASK:-dwi_iqm_qc}}"
dataset_dir="${SCRIPT_DIR}/../sample_data"
participant_list="${SCRIPT_DIR}/../sample_data/dwi_iqm_test_participants.tsv"
output_dir="${SCRIPT_DIR}/output"
port_number="${PORT:-8501}"
# See purpose #3 above: sub-CMH0003 is missing ses-01 on purpose.
session_list="${SESSION_LIST:-ses-01,ses-02}"

echo "Using qc_json=${qc_json}  qc_task=${qc_task}  port=${port_number}  session_list=${session_list}"

cd "${SCRIPT_DIR}"
streamlit run "$qc_launch_script" --server.port="$port_number" -- \
  --qc_json "$qc_json" \
  --qc_task "$qc_task" \
  --qc_pipeline "$qc_pipeline" \
  --dataset_dir "$dataset_dir" \
  --participant_list "$participant_list" \
  --session_list "$session_list" \
  --output_dir "$output_dir"

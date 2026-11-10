#!/usr/bin/env bash
set -euo pipefail

qc_launch_script="ui/main.py"
qc_pipeline="fmriprep"
qc_task="${QC_TASK:-anat_wf_qc}"
qc_json="${QC_JSON:-./pipelines/fmriprep/qc_demo.json}"
dataset_dir="sample_data"
participant_list="${PARTICIPANT_LIST:-sample_data/qc_participants_demo.tsv}"
output_dir="./output"
port_number="${PORT:-8501}"

# Optional: set SESSION_LIST (for example "ses-01,ses-02").
# Default to ses-01 for bundled fMRIPrep demo derivatives.
session_list="${SESSION_LIST:-ses-01}"

# ui/main.py resolves --qc_json relative to ui/ (its own location), not repo root.
# Keep qc_json user-facing path root-relative, then translate before passing.
case "$qc_json" in
  /*)
    qc_json_for_ui="$qc_json"
    ;;
  ./*)
    qc_json_for_ui="../${qc_json#./}"
    ;;
  *)
    qc_json_for_ui="../$qc_json"
    ;;
esac

cmd=(
  streamlit run "$qc_launch_script" --server.port="$port_number" --
  --qc_json "$qc_json_for_ui"
  --qc_task "$qc_task"
  --qc_pipeline "$qc_pipeline"
  --dataset_dir "$dataset_dir"
  --participant_list "$participant_list"
  --output_dir "$output_dir"
)

cmd+=(--session_list "$session_list")

if ! command -v streamlit >/dev/null 2>&1; then
  echo "Error: streamlit is not available in PATH." >&2
  echo "Activate your environment and install dependencies, e.g. pip install -r requirements.txt" >&2
  exit 127
fi

if [[ ! -f "$qc_json" ]]; then
  echo "Error: qc_json not found: $qc_json" >&2
  exit 1
fi

if [[ ! -f "$participant_list" ]]; then
  echo "Error: participant_list not found: $participant_list" >&2
  exit 1
fi

if [[ ! -d "$dataset_dir" ]]; then
  echo "Error: dataset_dir not found: $dataset_dir" >&2
  exit 1
fi

echo "Launching QC-Studio with:"
echo "  qc_json=$qc_json"
echo "  qc_json_for_ui=$qc_json_for_ui"
echo "  qc_task=$qc_task"
echo "  dataset_dir=$dataset_dir"
echo "  participant_list=$participant_list"
echo "  session_list=$session_list"
echo "  port=$port_number"

"${cmd[@]}"

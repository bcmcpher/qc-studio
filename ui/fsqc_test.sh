set -euo pipefail

qc_launch_script="main.py"
qc_pipeline="fsqc"
qc_json="${1:-${QC_JSON:-../pipelines/fsqc/qc.json}}"
qc_task="${2:-${QC_TASK:-FS_preproc_workflow}}"
dataset_dir="../sample_data"
participant_list="../sample_data/qc_participants.tsv"
output_dir="./output"
port_number="${PORT:-8501}"
session_list="${SESSION_LIST:-ses-01,ses-02}"
rater_id="odysseus"

streamlit run $qc_launch_script --server.port=$port_number -- \
  --qc_json $qc_json \
  --qc_task $qc_task \
  --qc_pipeline $qc_pipeline \
  --dataset_dir $dataset_dir \
  --participant_list $participant_list \
  --session_list $session_list \
  --output_dir $output_dir \
  --rater_id $rater_id 
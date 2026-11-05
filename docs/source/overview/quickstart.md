# Quickstart

The fastest way to see QC-Studio end to end is the fMRIPrep demo.
It runs on a small BIDS dataset with fMRIPrep derivatives, included in the repository under `sample_data/`.

## 1. Install

Follow [Installation](installation.md) if you have not already.

## 2. Run the demo

From the repository root:

```bash
./fmriprep_demo.sh
```

Streamlit starts on port 8501 and prints the launch configuration:

```text
Launching QC-Studio with:
  qc_json=./pipelines/fmriprep/qc_demo.json
  qc_json_for_ui=../pipelines/fmriprep/qc_demo.json
  qc_task=anat_wf_qc
  dataset_dir=sample_data
  participant_list=sample_data/qc_participants_demo.tsv
  session_list=ses-01
  port=8501
```

Open <http://localhost:8501> in your browser.

## 3. Take your first ratings

### Landing page

1. **👤 Rater Information** — enter your rater name or ID, and adjust the other rater details and autoplay settings as needed.
2. **🖼️ Display Panels** — choose which panels to show, and set the montage grid's maximum rows and columns. At least one panel is required.
3. **📤 Upload Existing QC File** — optional. Pick a previous results or checkpoint file to resume where you left off.

The sidebar lets you choose the QC task to rate and the [default rating](../guides/ratings.md#default-rating)
preselected on unrated pages.

Click **Continue to QC 🚀**.

### QC pages

There is one QC page per QC record.

- The left sidebar has **▶️ Play** and **⏸️ Pause** for [Autoplay](../guides/autoplay.md),
  **◀️ Previous** and **Next ▶️** buttons, and a page counter.
- The main area shows the selected panels for the task, followed by **📊 Rate**, with the rating
  choices and a notes box.

Click a rating to record it. To add notes, click **Add notes** first, since the notes box stays
disabled until you do. Notes are saved when you next change a rating or move to another page.

**Next** saves every rating and note on the current page, then moves on. You can move past a page
without rating it, but the summary page opens only once every page is rated. If the page shows
several QC tasks, each one needs its own rating.

Ratings are kept in the app's memory until you save them to a file. Click **🏁 Create checkpoint**
at any time to write a timestamped snapshot to the output directory.

### Summary page

Once every QC page is rated, **Next** opens a summary of your ratings.
Click **💾 Export Final Results** to write one results TSV per QC task.

## Running QC-Studio on your own data

The demo script is a wrapper around a `streamlit run` command. To review your own data, run that
command directly with your own paths:

```bash
streamlit run ui/main.py --server.port=8501 -- \
    --dataset_dir /path/to/dataset \
    --participant_list /path/to/participants.tsv \
    --session_list ses-01 \
    --qc_json /path/to/qc.json \
    --qc_task <task-name> \
    --qc_pipeline <pipeline-name> \
    --output_dir /path/to/output
```

A few things to note:

- The `--` separates Streamlit's own options (such as `--server.port`) from QC-Studio's flags.
- Use `--session_list none` if your dataset has no sessions.
- A relative `--qc_json` path is resolved against the `ui/` directory, so absolute paths are safest.

See [Configuration](../guides/configuration.md) for what each flag does, or run `python ui/main.py --help`.

## Next steps

- [Configuration](../guides/configuration.md) — every flag, the `qc.json` schema, substitutions, and output columns.
- [Rating schemes](../guides/ratings.md) — single and multi-facet ratings.
- [Autoplay](../guides/autoplay.md) — timed auto-advance for a quick first pass over many QC records.
- [Software Architecture](../development/architecture.md) — how the code is organized, if you plan to contribute.

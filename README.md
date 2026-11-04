# QC-Studio

A web-based quality control (QC) application for neuroimaging data. QC-Studio allows raters to visualize and assess MRI data, 2D image montages, and IQM metrics in an interactive Streamlit interface.

[See design overview →](docs/DEV_PLAN.md)

## 🎯 Goals

- Create an interactive web app to visualize neuroimaging data - raw and processed! 
- Support multiple image types: 3D MRI (NIfTI), 2D image montages, and IQM metrics
- Enable structured quality control ratings through a clean, intuitive interface

## 📚 Documentation

| Document | Purpose | Audience |
|----------|---------|----------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Complete architecture overview | All |
| [DEV_PLAN.md](docs/DEV_PLAN.md) | Product scope and design overview | Contributors |
| [ui/tests/README.md](ui/tests/README.md) | Test suite usage and testing patterns | Developers |
| [SCanD QC guidelines](https://github.com/TIGRLab/SCanD_project/tree/Fir/docs) | Pipeline QC pass/fail criteria (fMRIPrep, FreeSurfer, QSIPrep, XCP-D, NODDIreg) | Raters / supervisors |

## 🚀 Quick Start

### Prerequisites

- **Python**: 3.10+ (3.12 tested in CI/DEV environment)
- **pip/venv** OR **[uv](https://github.com/astral-sh/uv)** (recommended for faster installs)

### Option A: Using uv (Recommended - Fastest)

```bash
# Clone the repository
git clone https://github.com/nipoppy/qc-studio.git
cd qc-studio

# Create and activate virtual environment with uv
uv venv

# Activate the environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies with uv
uv pip install -r requirements.txt

# Install niivue-streamlit component
uv pip install --index-url https://test.pypi.org/simple/ --no-deps niivue-streamlit

# Install development checks
uv pip install -r requirements-test.txt
pre-commit install
```

### Option B: Using pip & venv (Traditional)

```bash
# Clone the repository
git clone https://github.com/nipoppy/qc-studio.git
cd qc-studio

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Upgrade pip
python -m pip install --upgrade pip setuptools wheel

# Install runtime dependencies
pip install -r requirements.txt

# Install niivue-streamlit component
pip install --index-url https://test.pypi.org/simple/ --no-deps niivue-streamlit

# Install development checks
python -m pip install -r requirements-test.txt
pre-commit install
```

Before pushing, run all pre-commit checks. This includes the same UI test command used in CI.

```bash
pre-commit run --all-files
```

### Run the Application

```bash
# Run the web app
streamlit run ui/app.py

# Or use the CLI entry point
python ui/main.py --help
```

### Try the Demo (Optional)

```bash
# Test with sample fMRIPrep data
cd ui
./fmriprep_test.sh
```

### Multi-user deployment (Cloudflare Access)

Several raters can use one running QC-Studio at the same time. Each rater sees only their assigned participants and writes their ratings to their own folder. Users are identified by the email Cloudflare Access authenticated.

1. **Describe the raters** in a `users.json` (see [`pipelines/users_config.example.json`](pipelines/users_config.example.json)):

   ```json
   {
     "rater_root": "/data/qc-datasets/qc-raters",
     "users": {
       "alice@mcgill.ca": {
         "rater_id": "alice",
         "rater_dir": "alice",
         "participant_list": "alice_primary_participant_list.tsv"
       },
       "bob@mcgill.ca": {"participant_list": "bob.tsv", "session_list": "ses-BL"}
     }
   }
   ```

   | Key | Required | Meaning |
   |-----|----------|---------|
   | `rater_root` (top level) | no | Folder holding the rater folders: absolute, or relative to `users.json`. Defaults to the folder containing `users.json`. |
   | `rater_id` | no | Used in file names. Defaults to the part of the email before the `@`. |
   | `rater_dir` | no | The rater's folder, relative to `rater_root` (an absolute path ignores `rater_root`). Defaults to `<rater_id>`. |
   | `participant_list` | yes | Tab-separated file inside `rater_dir` with a `participant_id` column and an optional `session_id` column. |
   | `session_list` | no | Overrides the launcher's `--session_list` for this rater. A `session_id` column takes precedence over both. |
   | `output_dir` | no | Where ratings are saved, relative to `rater_dir`. Defaults to `<rater_dir>/qc-output`. |

   - Email keys are case-insensitive.
   - A broken entry only affects that rater. Entries that share an email, rater ID or output folder are all rejected, so raters never overwrite each other.
   - You can edit the file while the app runs: changes apply on the next page load. Re-run the check below after editing.
   - Emails that aren't in the file, or whose setup is incomplete, are refused at sign-in.

2. **Check the setup.** This changes nothing and prints a status table for every rater (ready, needs an output folder, not ready, invalid entry) plus the reasons:

   ```bash
   cd ui
   python check_users_setup.py /data/qc-datasets/qc-raters/users.json --session_list ses-BL
   ```

3. **Launch** with [`ui/launch_studio_multi.sh`](ui/launch_studio_multi.sh) (edit the dataset and pipeline settings at the top first). It runs the check, asks for confirmation, creates missing `qc-output` folders for ready raters, and starts Streamlit on `127.0.0.1` so the tunnel is the only way in:

   ```bash
   ./launch_studio_multi.sh /data/qc-datasets/qc-raters/users.json 8501           # interactive
   ./launch_studio_multi.sh /data/qc-datasets/qc-raters/users.json 8501 --check   # summary only
   ./launch_studio_multi.sh /data/qc-datasets/qc-raters/users.json 8501 --yes     # no prompt
   ```

4. **Verify identity (recommended).** Set `CF_ACCESS_TEAM_DOMAIN` (e.g. `myteam.cloudflareaccess.com`) and `CF_ACCESS_AUD` in `.env`. The AUD is the Application Audience tag in Zero Trust → Access → Applications → your app → Overview. With both set, the signed `Cf-Access-Jwt-Assertion` token is checked against Cloudflare's public keys. Without them, the `Cf-Access-Authenticated-User-Email` header is trusted as-is, which is safe only when Streamlit can't be reached except through the tunnel.

Each rater's files end up in `<output_dir>/checkpoints/*.tsv` and `<output_dir>/<rater_id>_<pipeline>_<task>_qc_status.tsv`. Raters can't edit their rater ID, and importing another rater's file won't change it.

To test locally without a tunnel, set `QC_STUDIO_DEV_USER_EMAIL=alice@mcgill.ca` in the environment. Never set it on a server: the check and the launcher refuse to run while it is set.

## 🔗 Related Projects

- [Nipoppy](https://github.com/nipoppy/nipoppy) - Lightweight framework for standardized organization and processing of neuroimaging-clinical datasets.
- [NiiVue](https://github.com/niivue/niivue) - 3D medical image viewer
- [Streamlit](https://streamlit.io/) - Python web app framework

## 📄 License

See LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please:

1. Read the [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design patterns
2. Check [ui/tests/README.md](ui/tests/README.md) for testing practices
3. Follow the code organization described above
4. Ensure all tests pass before submitting PR

## ❓ Support

For issues, questions, or suggestions open an issue on GitHub with detailed description

# Installation

## Requirements

| | |
|---|---|
| **Python** | 3.10 or newer |
| **Git** | any recent version |
| **Browser** | required to interact with the app once it is running |
| **OS** | macOS or Linux |

## Get the code

```bash
git clone https://github.com/nipoppy/qc-studio.git
cd qc-studio
```

## Create an environment

### Option A — `uv` (recommended)

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install --index-url https://test.pypi.org/simple/ --no-deps niivue-streamlit
```

### Option B — `pip` and `venv`

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install --index-url https://test.pypi.org/simple/ --no-deps niivue-streamlit
```

## Verify the installation

```bash
python ui/main.py --help
```

## Upgrading

```bash
git pull
pip install -r requirements.txt
pip install --index-url https://test.pypi.org/simple/ --no-deps niivue-streamlit
```

## Developer setup

```bash
pip install -r requirements-test.txt
pre-commit install
```

### Building the documentation locally

```bash
pip install -r docs/requirements.txt
make -C docs html
```

The built site is written to `docs/_build/html`. To view it, open `docs/_build/html/index.html`
in a web browser, or serve it locally and browse to `http://localhost:8000`:

```bash
python -m http.server 8000 --directory docs/_build/html
```

Re-run `make -C docs html` and refresh the page after editing the docs.

## Next steps

Proceed to the [Quickstart](quickstart.md) to run a demo, or read [Configuration](../guides/configuration.md) first if you want to understand the flags.

"""Configuration file for the Sphinx documentation builder.

For the full list of built-in configuration values, see the documentation:
https://www.sphinx-doc.org/en/master/usage/configuration.html
"""

import datetime

# -- Project information -----------------------------------------------------

project = "QC-Studio"
copyright = f"{datetime.datetime.now(tz=datetime.timezone.utc).year}, NeuroDataScience-ORIGAMI Lab"
author = "NeuroDataScience-ORIGAMI Lab"

version = ""
release = ""

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

exclude_patterns = ["Thumbs.db", ".DS_Store"]

# Cross-references to objects that are not documented are left unresolved
# rather than failing the build
nitpicky = False

# -- Options for HTML output -------------------------------------------------

html_theme = "furo"
html_static_path = ["../_static"]
html_css_files = ["custom.css"]

html_theme_options = {
    "source_repository": "https://github.com/nipoppy/qc-studio",
    "source_branch": "main",
    "source_directory": "docs/source/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/nipoppy/qc-studio",
            "html": "",
            "class": "fa-brands fa-solid fa-github fa-2x",
        },
    ],
}

html_title = "QC-Studio"

# -- MyST configuration -------------------------------------------------------

myst_enable_extensions = ["colon_fence", "fieldlist", "substitution"]

myst_heading_anchors = 4

# -- Mermaid configuration -----------------------------------------------------
mermaid_output_format = "raw"
mermaid_width = "100%"
mermaid_height = "auto"
mermaid_init_config = {"startOnLoad": False, "flowchart": {"useMaxWidth": False}}

# -- Copybutton configuration ---------------------------------------------------
copybutton_exclude = ".linenos, .gp"

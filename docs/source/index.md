# QC-Studio documentation

QC-Studio is a web-based quality control (QC) application for neuroimaging data. It gives raters
a unified, portable interface, accessible from any web browser, to review raw imaging data, processed
pipeline derivatives, and image quality metrics (IQMs), and export ratings as a tab-separated table.

Key benefits:

- **Local and Remote QC** — QC-Studio can run locally or on a remote server that holds the data. Raters with access can review it in a local browser, without having to copy data.
- **Broad format support** — QC-Studio is built on [NiiVue](https://github.com/niivue/niivue), which displays volumetric and surface data in most common neuroimaging formats.
- **Custom QC protocols** — choose which images to show and which rating scales to use for each QC task.

![QC-Studio design overview](https://raw.githubusercontent.com/nipoppy/qc-studio/main/assets/nipoppy-qc-studio_overview.jpg)


## Related projects

- [Nipoppy](https://github.com/nipoppy/nipoppy) — standardized organization and processing of
  neuroimaging-clinical datasets.
- [NiiVue](https://github.com/niivue/niivue) — the 3D medical image viewer behind the 3D MRI
  panel.
- [Streamlit](https://streamlit.io/) — the Python web app framework QC-Studio is built on.
- [MRIQC](https://github.com/nipreps/mriqc) — the usual source of image quality metrics.


## Start here

- **[Why QC-Studio](overview/why_qc-studio.md)** — the motivation behind QC-Studio and the terms used throughout the
  documentation.
- **[Installation](overview/installation.md)** — set up a working environment from a clean machine.
- **[Quickstart](overview/quickstart.md)** — run the bundled demo on the sample dataset with one command and
  take your first QC ratings.

```{toctree}
---
caption: Overview
maxdepth: 2
titlesonly:
hidden:
includehidden:
---
overview/why_qc-studio
overview/installation
overview/glossary
overview/quickstart
```

```{toctree}
---
caption: Guides
maxdepth: 2
titlesonly:
hidden:
includehidden:
---
guides/configuration
guides/ratings
guides/autoplay
```

```{toctree}
---
caption: Development
maxdepth: 2
titlesonly:
hidden:
includehidden:
---
development/design_reqs
development/architecture

# Why QC-Studio

Neuroimaging workflows produce variety of data artifacts including volumes, surfaces, networks, tables, figures, and summary metrics that often need to be reviewed for every participant and visit. Reviewing those outputs usually means opening files by hand, in one tool per output type, inspecting them visually, and noting quality ratings in a spreadsheet. This is slow, prone to error, and hard to scale.

QC-Studio simplifies the mechanics of this tedious process. It acknowledges that no single QC protocol fits all, and therefore offers the flexibility to prescribe study-, datatype-, and pipeline-specific "QC tasks" (see [qc.json](../guides/configuration.md#qc-task-config)) to ensure analysis-ready datasets are thoroughly checked.

In practice, it integrates "visual evidence" from the 3D volumes, 2D montages, and calculated image quality metrics for human auditing - which can be performed both locally and remotely!

We aspire that neuroimagers should be able to ***QC Anything, Anywhere, All at Once!***

## Supported imaging datatypes
- Anat (e.g. T1w, T2w, FLAIR)
- Diffusion
- BOLD
- Surface meshes
- Slice montages
- Image quality metrics (IQMs)

## Supported pipelines

Sample `qc.json` files are available in the [`pipelines/`](https://github.com/nipoppy/qc-studio/tree/main/pipelines)
directory for these pipelines:

- fMRIPrep
- FreeSurfer
- FreeSurfer QC (fsqc)
- QSIPrep
- XCP-D
- NODDIreg

You can also write your own `qc.json` for any other pipeline. See [Configuration](../guides/configuration.md#qc-task-config).

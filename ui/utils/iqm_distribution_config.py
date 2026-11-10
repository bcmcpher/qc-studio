"""IQM distribution group definitions.

Each supported modality maps to named metric groups from MRIQC group-level
tables. DWI includes a dynamic builder because shell-specific metric columns
depend on the acquisition.
"""

from itertools import product
from pathlib import Path

DISTRIBUTION_T1W_GROUPS = {
    "EFC": ["efc"],
    "FBER": ["fber"],
    "CJV": ["cjv"],
    "WM2MAX": ["wm2max"],
    "FWHM": ["fwhm_avg", "fwhm_x", "fwhm_y", "fwhm_z"],
    "SNR": ["snr_csf", "snr_gm", "snr_wm"],
    "SNRD": ["snrd_csf", "snrd_gm", "snrd_wm"],
    "QI": ["qi_1", "qi_2"],
    "INU": ["inu_range", "inu_med"],
    "ICSV": ["icvs_csf", "icvs_gm", "icvs_wm"],
    "RPVE": ["rpve_csf", "rpve_gm", "rpve_wm"],
    "TPM_OVERLAP": ["tpm_overlap_csf", "tpm_overlap_gm", "tpm_overlap_wm"],
    "SUMMARY_BG": [
        "summary_bg_mean",
        "summary_bg_median",
        "summary_bg_stdv",
        "summary_bg_mad",
        "summary_bg_k",
        "summary_bg_p05",
        "summary_bg_p95",
    ],
    "SUMMARY_CSF": [
        "summary_csf_mean",
        "summary_csf_median",
        "summary_csf_stdv",
        "summary_csf_mad",
        "summary_csf_k",
        "summary_csf_p05",
        "summary_csf_p95",
    ],
    "SUMMARY_GM": [
        "summary_gm_mean",
        "summary_gm_median",
        "summary_gm_stdv",
        "summary_gm_mad",
        "summary_gm_k",
        "summary_gm_p05",
        "summary_gm_p95",
    ],
    "SUMMARY_WM": [
        "summary_wm_mean",
        "summary_wm_median",
        "summary_wm_stdv",
        "summary_wm_mad",
        "summary_wm_k",
        "summary_wm_p05",
        "summary_wm_p95",
    ],
}

DISTRIBUTION_BOLD_GROUPS = {
    "EFC": ["efc"],
    "FBER": ["fber"],
    "SNR": ["snr"],
    "FWHM": ["fwhm_x", "fwhm_y", "fwhm_z"],
    "GSR": ["gsr_x", "gsr_y"],
    "DVARS": ["dvars_nstd", "dvars_std"],
    "DVARSn": ["dvars_vstd"],
    "FD_MEAN": ["fd_mean"],
    "FD_NUM": ["fd_num"],
    "FD_PERC": ["fd_perc"],
    "SPIKES_NUM": ["spikes_num"],
    "DUMMY": ["dummy_trs"],
    "GCOR": ["gcor"],
    "TNSR": ["tnsr"],
    "AOR": ["aor"],
    "AQI": ["aqi"],
    "SUMMARY_BG": [
        "summary_bg_mean",
        "summary_bg_stdv",
        "summary_bg_k",
        "summary_bg_p05",
        "summary_bg_p95",
    ],
    "SUMMARY_FG": [
        "summary_fg_mean",
        "summary_fg_stdv",
        "summary_fg_k",
        "summary_fg_p05",
        "summary_fg_p95",
    ],
}

# DWI groups with fixed columns. Shell-dependent groups are added by
# build_dwi_groups() after inspecting the loaded group_dwi.tsv columns.
DISTRIBUTION_DWI_GROUPS = {
    "BDIFFS": ["bdiffs_max", "bdiffs_mean", "bdiffs_median", "bdiffs_min"],
    "FA": ["fa_degenerate", "fa_nans"],
    "FD_MEAN": ["fd_mean"],
    "FD_NUM": ["fd_num"],
    "FD_PERC": ["fd_perc"],
    "NDC": ["ndc"],
    "SIGMA_CC": ["sigma_cc"],
    "SIGMA": ["sigma_pca", "sigma_piesno"],
    "SPIKES": ["spikes_global", "spikes_slice_i", "spikes_slice_j", "spikes_slice_k"],
    "SUMMARY_LOCATION": [
        "summary_bg_p05",
        "summary_fg_p05",
        "summary_wm_p05",
        "summary_bg_mean",
        "summary_fg_mean",
        "summary_wm_mean",
        "summary_bg_median",
        "summary_fg_median",
        "summary_wm_median",
    ],
    "SUMMARY_P95": ["summary_bg_p95", "summary_fg_p95", "summary_wm_p95"],
    "SUMMARY_DISPERSION": [
        "summary_bg_stdv",
        "summary_fg_stdv",
        "summary_wm_stdv",
        "summary_bg_mad",
        "summary_fg_mad",
        "summary_wm_mad",
    ],
    "SUMMARY_K_BG": ["summary_bg_k"],
    "SUMMARY_K_FG_WM": ["summary_fg_k", "summary_wm_k"],
}


def build_dwi_groups(columns, keep_only_present=True):
    """Return the full, ordered DWI group dict for a given group_dwi.tsv.

    Expands the three shell-dependent groups (EFC_SHELLS, FBER_SHELLS, SNR_CC)
    to match the actual acquisition, then interleaves them into MRIQC's plotting
    order.

    Parameters
    ----------
    columns : iterable of str
        The columns of the group_dwi.tsv (e.g. ``list(df.columns)``). Used to
        infer the number of shells and, if ``keep_only_present``, to drop any
        metric MRIQC didn't emit for this dataset.
    keep_only_present : bool
        If True, prune columns not found in ``columns`` and drop empty groups.
    """
    columns = list(columns)
    n_shells = sum(c.startswith("efc_shell") for c in columns)
    shells = range(1, n_shells + 1)

    shell_groups = {
        "EFC_SHELLS": [f"efc_shell{i:02d}" for i in shells],
        "FBER_SHELLS": [f"fber_shell{i:02d}" for i in shells],
        "SNR_CC": ["snr_cc_shell0"] + [f"snr_cc_shell{s}_{t}" for s, t in product(shells, ("best", "worst"))],
    }

    # MRIQC panel order.
    ordered = [
        "BDIFFS",
        "EFC_SHELLS",
        "FA",
        "FBER_SHELLS",
        "FD_MEAN",
        "FD_NUM",
        "FD_PERC",
        "NDC",
        "SIGMA_CC",
        "SIGMA",
        "SNR_CC",
        "SPIKES",
        "SUMMARY_LOCATION",
        "SUMMARY_P95",
        "SUMMARY_DISPERSION",
        "SUMMARY_K_BG",
        "SUMMARY_K_FG_WM",
    ]
    merged = {**DISTRIBUTION_DWI_GROUPS, **shell_groups}
    groups = {name: merged[name] for name in ordered}

    if keep_only_present:
        colset = set(columns)
        groups = {name: [c for c in cols if c in colset] for name, cols in groups.items()}
        groups = {name: cols for name, cols in groups.items() if cols}

    return groups


IQM_DISTRIBUTION_GROUPS = {
    "t1w": DISTRIBUTION_T1W_GROUPS,
    "bold": DISTRIBUTION_BOLD_GROUPS,
    "dwi": build_dwi_groups,
}


def infer_pipeline_from_iqm_path(path: Path) -> str:
    """Infer the pipeline name from an IQM path."""

    parts = Path(path).parts
    if "derivatives" in parts:
        idx = parts.index("derivatives")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return Path(path).stem


def is_mriqc_pipeline(pipeline_name: str) -> bool:
    """Check if a pipeline name is MRIQC, bare or version-suffixed."""
    name = pipeline_name.lower()
    return name == "mriqc" or name.startswith("mriqc-")

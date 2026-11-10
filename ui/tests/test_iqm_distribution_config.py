"""Tests for utils/iqm_distribution_config.py."""

from utils.iqm_distribution_config import (
    DISTRIBUTION_DWI_GROUPS,
    build_dwi_groups,
    infer_pipeline_from_iqm_path,
    is_mriqc_pipeline,
)

DWI_PANEL_ORDER = [
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

_ALL_STATIC_DWI_COLUMNS = [c for cols in DISTRIBUTION_DWI_GROUPS.values() for c in cols]

# Copied from sample_data/derivatives/mriqc/group_dwi.tsv's header.
REAL_GROUP_DWI_COLUMNS = [
    "bids_name",
    "NumberOfShells",
    "bValues",
    "bValuesEstimation",
    "bdiffs_max",
    "bdiffs_mean",
    "bdiffs_median",
    "bdiffs_min",
    "efc_shell01",
    "efc_shell02",
    "efc_shell03",
    "fa_degenerate",
    "fa_nans",
    "fber_shell01",
    "fber_shell02",
    "fber_shell03",
    "fd_mean",
    "fd_num",
    "fd_perc",
    "ndc",
    "sigma_cc",
    "sigma_pca",
    "sigma_piesno",
    "snr_cc_shell0",
    "snr_cc_shell1_best",
    "snr_cc_shell1_worst",
    "snr_cc_shell2_best",
    "snr_cc_shell2_worst",
    "spikes_global",
    "spikes_slice_i",
    "spikes_slice_j",
    "spikes_slice_k",
    "summary_bg_k",
    "summary_bg_mad",
    "summary_bg_mean",
    "summary_bg_median",
    "summary_bg_n",
    "summary_bg_p05",
    "summary_bg_p95",
    "summary_bg_stdv",
    "summary_fg_k",
    "summary_fg_mad",
    "summary_fg_mean",
    "summary_fg_median",
    "summary_fg_n",
    "summary_fg_p05",
    "summary_fg_p95",
    "summary_fg_stdv",
    "summary_wm_k",
    "summary_wm_mad",
    "summary_wm_mean",
    "summary_wm_median",
    "summary_wm_n",
    "summary_wm_p05",
    "summary_wm_p95",
    "summary_wm_stdv",
    "efc_shell04",
    "efc_shell05",
    "fber_shell04",
    "fber_shell05",
    "snr_cc_shell3_best",
    "snr_cc_shell3_worst",
    "snr_cc_shell4_best",
    "snr_cc_shell4_worst",
]


def test_build_dwi_groups_returns_keys_in_mriqc_panel_order():
    groups = build_dwi_groups(_ALL_STATIC_DWI_COLUMNS, keep_only_present=False)

    assert list(groups.keys()) == DWI_PANEL_ORDER


def test_build_dwi_groups_expands_efc_and_fber_shells():
    columns = ["efc_shell01", "efc_shell02", "efc_shell03"]

    groups = build_dwi_groups(columns, keep_only_present=False)

    assert groups["EFC_SHELLS"] == ["efc_shell01", "efc_shell02", "efc_shell03"]
    assert groups["FBER_SHELLS"] == ["fber_shell01", "fber_shell02", "fber_shell03"]


def test_build_dwi_groups_snr_cc_interleaves_best_worst_per_shell():
    columns = ["efc_shell01", "efc_shell02"]

    groups = build_dwi_groups(columns, keep_only_present=False)

    assert groups["SNR_CC"] == [
        "snr_cc_shell0",
        "snr_cc_shell1_best",
        "snr_cc_shell1_worst",
        "snr_cc_shell2_best",
        "snr_cc_shell2_worst",
    ]


def test_build_dwi_groups_zero_shells_when_no_shell_columns_present():
    columns = ["bdiffs_max"]

    groups = build_dwi_groups(columns, keep_only_present=False)

    assert groups["EFC_SHELLS"] == []
    assert groups["FBER_SHELLS"] == []
    assert groups["SNR_CC"] == ["snr_cc_shell0"]


def test_build_dwi_groups_keep_only_present_prunes_missing_columns():
    columns = [
        "efc_shell01",
        "efc_shell02",
        "efc_shell03",
        "fber_shell01",
        "fber_shell02",
        "fber_shell03",
        "snr_cc_shell0",
        "snr_cc_shell1_best",
        "snr_cc_shell1_worst",
        "bdiffs_max",
        "bdiffs_mean",
    ]

    groups = build_dwi_groups(columns, keep_only_present=True)

    assert groups["SNR_CC"] == ["snr_cc_shell0", "snr_cc_shell1_best", "snr_cc_shell1_worst"]
    assert groups["BDIFFS"] == ["bdiffs_max", "bdiffs_mean"]


def test_build_dwi_groups_keep_only_present_drops_fully_empty_groups():
    columns = ["bdiffs_max"]

    groups = build_dwi_groups(columns, keep_only_present=True)

    assert list(groups.keys()) == ["BDIFFS"]
    assert groups["BDIFFS"] == ["bdiffs_max"]
    assert "EFC_SHELLS" not in groups
    assert "FBER_SHELLS" not in groups
    assert "SNR_CC" not in groups


def test_build_dwi_groups_keep_only_present_false_keeps_full_canonical_lists():
    columns = ["bdiffs_max"]

    groups = build_dwi_groups(columns, keep_only_present=False)

    assert list(groups.keys()) == DWI_PANEL_ORDER
    assert groups["BDIFFS"] == DISTRIBUTION_DWI_GROUPS["BDIFFS"]
    assert groups["SPIKES"] == DISTRIBUTION_DWI_GROUPS["SPIKES"]
    assert groups["EFC_SHELLS"] == []


def test_build_dwi_groups_matches_real_mriqc_dwi_columns():
    groups = build_dwi_groups(REAL_GROUP_DWI_COLUMNS, keep_only_present=True)

    assert groups["EFC_SHELLS"] == [
        "efc_shell01",
        "efc_shell02",
        "efc_shell03",
        "efc_shell04",
        "efc_shell05",
    ]
    assert groups["FBER_SHELLS"] == [
        "fber_shell01",
        "fber_shell02",
        "fber_shell03",
        "fber_shell04",
        "fber_shell05",
    ]
    assert groups["SNR_CC"] == [
        "snr_cc_shell0",
        "snr_cc_shell1_best",
        "snr_cc_shell1_worst",
        "snr_cc_shell2_best",
        "snr_cc_shell2_worst",
        "snr_cc_shell3_best",
        "snr_cc_shell3_worst",
        "snr_cc_shell4_best",
        "snr_cc_shell4_worst",
    ]
    assert "snr_cc_shell5_best" not in groups["SNR_CC"]
    assert list(groups.keys()) == DWI_PANEL_ORDER


def test_is_mriqc_pipeline_matches_bare_name():
    assert is_mriqc_pipeline("mriqc") is True
    assert is_mriqc_pipeline("MRIQC") is True


def test_is_mriqc_pipeline_matches_version_suffixed_name():
    """Real MRIQC output uses a versioned derivatives folder name, e.g.
    derivatives/mriqc-0.16.1/ - an exact-string match alone would miss
    this and silently fall back to the generic per-column grouping
    instead of the curated metric groups."""
    assert is_mriqc_pipeline("mriqc-0.16.1") is True
    assert is_mriqc_pipeline("mriqc-23.1.0") is True
    assert is_mriqc_pipeline("MRIQC-0.16.1") is True


def test_is_mriqc_pipeline_rejects_unrelated_names():
    assert is_mriqc_pipeline("fmriprep") is False
    assert is_mriqc_pipeline("qsiprep") is False
    assert is_mriqc_pipeline("mriqcx") is False
    assert is_mriqc_pipeline("custom-mriqc") is False


def test_infer_pipeline_from_iqm_path_with_version_suffix():
    assert infer_pipeline_from_iqm_path("derivatives/mriqc-0.16.1/group_T1w.tsv") == "mriqc-0.16.1"
    assert is_mriqc_pipeline(infer_pipeline_from_iqm_path("derivatives/mriqc-0.16.1/group_T1w.tsv")) is True

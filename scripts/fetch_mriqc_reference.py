"""Download MRIQC reference data from the web API and save as TSV.
 
Usage:
    python scripts/fetch_mriqc_reference.py --output_dir reference_data/
 
This script queries the MRIQC Web API (https://mriqc.nimh.nih.gov/)
for T1w and BOLD population data, flattens the bids_meta fields
(Manufacturer, MagneticFieldStrength, ManufacturersModelName) into columns, and saves the
result as TSV files that can be used by iqm_viewer.py for reference
distribution comparisons.
 
The API paginates at ~1000 records per page. This script follows
pagination links to download all available records.
"""

import json
import time
import requests
import argparse
import logging
import pandas as pd
from pathlib import Path

MODALITIES = ["T1w", "bold"]
BIDS_METADATA_FIELDS = ["Manufacturer", "MagneticFieldStrength", "ManufacturersModelName"]

BASE = "https://mriqc.nimh.nih.gov/api/v1"
MAX_RESULTS_PER_PAGE = 200
REQUEST_DELAY_SECONDS = 1  # To avoid hitting rate limits
MAX_RETRIES_PER_PAGE = 5
BACKOFF_BASE_SECONDS = 2


def _build_logger(output_dir: Path) -> logging.Logger:
    """Configure logger with both console and file handlers."""
    logger = logging.getLogger("fetch_mriqc_reference")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Clear existing handlers to avoid duplicate logs when rerunning in-session.
    if logger.handlers:
        logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    file_handler = logging.FileHandler(output_dir / "fetch_mriqc_reference.log")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def _flatten_item(item: dict) -> dict:
    row = {k: v for k, v in item.items() if k not in ("_meta", "_created", "_etag", "_links", "_updated", "provenance", "bids_meta")}
    bids_metadata = item.get("bids_meta", {})
    for field in BIDS_METADATA_FIELDS:
        row[field] = bids_metadata.get(field, "Unknown")
    return row


def iter_reference_pages(modality, logger: logging.Logger, failed_pages: list[dict]):
    """Yield (page_number, flattened_rows) for each successful page."""

    page = 1

    while True:
        params = {
            "page": page,
            "max_results": MAX_RESULTS_PER_PAGE,
        }
        logger.info("Fetching %s data, page %s...", modality, page)
        response = None
        last_error = None
        last_status = None

        for attempt in range(1, MAX_RETRIES_PER_PAGE + 1):
            try:
                response = requests.get(f"{BASE}/{modality}", params=params, timeout=120)
                response.raise_for_status()
                break
            except requests.RequestException as e:
                is_last_attempt = attempt == MAX_RETRIES_PER_PAGE
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                last_error = str(e)
                last_status = status_code
                response = None

                if is_last_attempt:
                    logger.error(
                        "Failed on page %s after %s attempts: %s",
                        page,
                        MAX_RETRIES_PER_PAGE,
                        e,
                    )
                    break

                if status_code is None or status_code >= 500:
                    sleep_s = BACKOFF_BASE_SECONDS**attempt
                    logger.warning(
                        "Attempt %s/%s failed on page %s (status=%s). Retrying in %ss...",
                        attempt,
                        MAX_RETRIES_PER_PAGE,
                        page,
                        status_code,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue

                logger.error("Non-retryable request failure on page %s: %s", page, e)
                break

        if response is None:
            failed_pages.append(
                {
                    "page": page,
                    "status_code": last_status,
                    "error": last_error,
                }
            )
            page += 1
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        data = response.json()
        items = data.get("_items", [])

        if not items:
            logger.info("No more records found for %s after page %s.", modality, page - 1)
            break

        page_rows = [_flatten_item(item) for item in items]
        yield page, page_rows

        links = data.get("_links", {})
        if not links.get("next"):
            logger.info("Reached last page for %s.", modality)
            break

        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)


def _read_reference_json(json_path, save_path=None):
    # this should be used once for the retrived json file

    with open(json_path, "r") as f:
        data = json.load(f)
    items = data.get("_items", [])
    rows = []
    for item in items:
        row = {k: v for k, v in item.items() if k not in ("_id", "_created", "_etag", "_links", "_updated", "provenance", "bids_meta")}
        bids_metadata = item.get("bids_meta", {})
        row["Manufacturer"] = bids_metadata.get("Manufacturer", "Unknown")
        row["MagneticFieldStrength"] = bids_metadata.get("MagneticFieldStrength", "Unknown")
        rows.append(row)

    if save_path:
        df = pd.DataFrame(rows)
        df.to_csv(save_path, sep="\t", index=False)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch MRIQC reference data from the Web API and save as TSV.")
    parser.add_argument("--output_dir", "-o", type=str, default="reference_data", help="Directory to save the TSV files.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = _build_logger(output_dir)
    failure_log = {}

    for modality in MODALITIES:
        save_path = output_dir / f"group_{modality}.tsv"
        if save_path.exists():
            save_path.unlink()

        failed_pages = []
        wrote_header = False
        total_rows = 0

        for page, page_rows in iter_reference_pages(modality, logger, failed_pages):
            page_df = pd.DataFrame(page_rows)
            page_df.to_csv(
                save_path,
                sep="\t",
                index=False,
                mode="a",
                header=not wrote_header,
            )
            wrote_header = True
            total_rows += len(page_df)

            if page == 1 or page % 25 == 0:
                logger.info(
                    "Checkpoint update for %s: page=%s rows_written=%s",
                    modality,
                    page,
                    total_rows,
                )

        if not wrote_header:
            pd.DataFrame().to_csv(save_path, sep="\t", index=False)

        logger.info("Saved %s records for %s to %s", total_rows, modality, save_path)

        if failed_pages:
            failure_log[modality] = failed_pages
            for failure in failed_pages:
                logger.error(
                    "Failed page logged | modality=%s page=%s status=%s error=%s",
                    modality,
                    failure.get("page"),
                    failure.get("status_code"),
                    failure.get("error"),
                )

    if failure_log:
        failure_log_path = output_dir / "fetch_failures.json"
        with open(failure_log_path, "w") as f:
            json.dump(failure_log, f, indent=2)
        logger.info("Saved failure JSON log to %s", failure_log_path)

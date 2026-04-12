import json
import os
import time
from pathlib import Path

import requests

from pipeline_utils import DATA_DIR, LOGS_DIR, ensure_layout, load_jsonl, read_json, setup_logger, write_json


CVE_DETAILS_PATH = DATA_DIR / "cve_details.json"
RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
ERROR_LOG = LOGS_DIR / "fetch_nvd_errors.log"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


def extract_details(payload):
    vuln = (payload.get("vulnerabilities") or [{}])[0].get("cve", {})
    metrics = vuln.get("metrics", {})
    score = None
    severity = None
    for key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
        metric = metrics.get(key)
        if metric:
            score = metric[0]["cvssData"].get("baseScore")
            severity = metric[0]["cvssData"].get("baseSeverity") or metric[0].get("baseSeverity")
            break
    weaknesses = vuln.get("weaknesses") or []
    cwes = []
    for weakness in weaknesses:
        for desc in weakness.get("description", []):
            if desc.get("value", "").startswith("CWE-"):
                cwes.append(desc["value"])
    descriptions = vuln.get("descriptions") or []
    desc = next((item["value"] for item in descriptions if item.get("lang") == "en"), "")
    return {
        "cvss_score": score,
        "severity": severity,
        "cwe_ids": sorted(set(cwes)),
        "description": desc,
    }


def main():
    ensure_layout()
    logger = setup_logger("fetch_nvd", ERROR_LOG)
    cache = read_json(CVE_DETAILS_PATH, {})
    rows = load_jsonl(RAW_PRS_PATH)
    cves = sorted({cve for row in rows for cve in row.get("cve_ids", []) if cve})

    session = requests.Session()
    api_key = os.environ.get("NVD_API_KEY")
    headers = {"apiKey": api_key} if api_key else {}
    delay = 0.02 if api_key else 1.2

    for idx, cve in enumerate(cves, start=1):
        if cve in cache:
            continue
        params = {"cveId": cve}
        while True:
            try:
                resp = session.get(NVD_URL, params=params, headers=headers, timeout=30)
                if resp.status_code == 503:
                    time.sleep(6)
                    continue
                if resp.status_code == 404:
                    logger.warning("NVD missing entry for %s; caching null metadata", cve)
                    cache[cve] = {
                        "cvss_score": None,
                        "severity": None,
                        "cwe_ids": [],
                        "description": "",
                    }
                    write_json(CVE_DETAILS_PATH, cache)
                    break
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    sleep_s = int(retry_after) if retry_after and retry_after.isdigit() else 30
                    sleep_s = max(sleep_s, 30)
                    logger.warning("NVD rate limited for %s; sleeping %ss", cve, sleep_s)
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                cache[cve] = extract_details(resp.json())
                write_json(CVE_DETAILS_PATH, cache)
                time.sleep(delay)
                break
            except requests.RequestException as exc:
                logger.exception("NVD fetch failed for %s: %s", cve, exc)
                time.sleep(15)
        if idx % 50 == 0:
            print(f"NVD progress: {idx}/{len(cves)}")
    print(f"Fetched NVD details for {len(cache)} CVEs")


if __name__ == "__main__":
    main()

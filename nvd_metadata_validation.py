"""NVD affected-version metadata validation (handoff Step 8).

Recent work (e.g. arXiv:2609.01187, arXiv:2609.01186, arXiv:2609.01503) reports that a
large share of vulnerability-database entries carry incorrect package coordinates or
affected-version ranges. SecBreak's cohort inherits CVE metadata from NVD without
independently checking it. This script does a lightweight external check: for a random
sample of CVE-linked Maven PRs in the analyzed set, it verifies that the version the PR
upgrades *from* (the claimed-vulnerable version, `old_version`) and the version it
upgrades *to* (`new_version`) both actually exist as published artifacts in Maven Central.

A missing `old_version` means the "affected" coordinate/version we carried from NVD does
not resolve to a real artifact -- the class of error the papers above describe. A missing
`new_version` is a separate data-quality issue (bad fixed-version metadata or a bad
title-regex extraction).

Output: data/nvd_metadata_validation.csv + a printed summary.
No network writes; HEAD requests only; failures are logged and skipped, never fatal.
"""

import sys
import time

import pandas as pd
import requests

DATASET = "data/analysis_dataset_corrected.csv"
OUT = "data/nvd_metadata_validation.csv"
SAMPLE_N = 100
SEED = 42
MAVEN_BASE = "https://repo1.maven.org/maven2"
TIMEOUT = 15
RETRIES = 3


def maven_dir_url(dep: str, version: str) -> str:
    group_id, artifact_id = dep.split(":", 1)
    group_path = group_id.strip().replace(".", "/")
    return f"{MAVEN_BASE}/{group_path}/{artifact_id.strip()}/{str(version).strip()}/"


def exists_in_maven_central(dep: str, version: str) -> bool | None:
    """True/False if resolvable; None if the check itself could not be performed."""
    if not isinstance(version, str) or not version.strip() or version.strip() in {"|", "-", "?"}:
        return None
    try:
        url = maven_dir_url(dep, version)
    except ValueError:
        return None
    last_err = None
    for attempt in range(RETRIES):
        try:
            r = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 405:  # some mirrors reject HEAD; fall back to GET
                r = requests.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
            if r.status_code in (200, 404):
                return r.status_code == 200
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:  # noqa: PERF203
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    print(f"  [skip] {dep} {version}: {last_err}", file=sys.stderr)
    return None


def main() -> None:
    df = pd.read_csv(DATASET, low_memory=False)

    # Rows the pipeline actually analyzed, that carry a CVE, and are Maven coordinates.
    if "analyzed_ok" in df.columns:
        analyzed = df[df["analyzed_ok"] == True]  # noqa: E712
    else:
        analyzed = df[df["analysis_error"].isna()]
    cand = analyzed[
        analyzed["cve_ids"].notna()
        & (analyzed["ecosystem"].str.lower() == "maven")
        & analyzed["dependency_name"].astype(str).str.contains(":")
    ].copy()

    n = min(SAMPLE_N, len(cand))
    sample = cand.sample(n=n, random_state=SEED)
    print(f"Analyzed CVE-linked Maven PRs available: {len(cand)}; sampling {n}")

    rows = []
    for i, (_, row) in enumerate(sample.iterrows(), 1):
        dep = str(row["dependency_name"])
        v_before = row["old_version"]
        v_after = row["new_version"]
        before_ok = exists_in_maven_central(dep, v_before)
        after_ok = exists_in_maven_central(dep, v_after)
        rows.append(
            {
                "repo_full_name": row.get("repo_full_name"),
                "pr_number": row.get("pr_number"),
                "dependency_name": dep,
                "cve_ids": row["cve_ids"],
                "claimed_affected_version": v_before,
                "fixed_version": v_after,
                "affected_version_resolves": before_ok,
                "fixed_version_resolves": after_ok,
                "has_bc": row.get("has_bc"),
            }
        )
        if i % 10 == 0:
            print(f"  {i}/{n} checked")

    res = pd.DataFrame(rows)
    res.to_csv(OUT, index=False)

    checkable = res["affected_version_resolves"].notna()
    n_checkable = int(checkable.sum())
    n_uncheckable = int((~checkable).sum())
    affected_match = res.loc[checkable, "affected_version_resolves"].mean() if n_checkable else float("nan")
    affected_mismatch = 1 - affected_match if n_checkable else float("nan")

    fixed_checkable = res["fixed_version_resolves"].notna()
    fixed_match = (
        res.loc[fixed_checkable, "fixed_version_resolves"].mean() if int(fixed_checkable.sum()) else float("nan")
    )

    print("\n==== NVD affected-version metadata validation ====")
    print(f"Sample size (Maven, CVE-linked, analyzed): {len(res)}")
    print(f"Checkable (version string well-formed, network OK): {n_checkable}")
    print(f"Not checkable (garbage version string / network): {n_uncheckable}")
    print(f"Claimed-affected version resolves in Maven Central: {affected_match*100:.1f}%")
    print(f"  -> affected-version mismatch rate: {affected_mismatch*100:.1f}%")
    print(f"Fixed (new) version resolves in Maven Central: {fixed_match*100:.1f}%")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()

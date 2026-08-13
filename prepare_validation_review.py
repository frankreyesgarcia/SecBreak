"""Phase 6 (paper strengthening): pre-fetch review context for manual BC
validation, WITHOUT performing the adjudication itself.

The actual manual_bc_label/manual_bc_confidence/manual_bc_notes/
manual_validation_status columns in bc_validation_sample_corrected.csv are
left untouched — that adjudication is Frank's to do by hand. This script
turns each row's review from a cold investigation into "open one link, read
one summary, type yes/no/unsure" by pre-fetching, for each of the 100 rows:
  - a direct link to the PR diff
  - a best-effort link to the dependency's own changelog/release notes
    (Maven: parsed from the POM's <scm> URL on Maven Central; PyPI: parsed
    from PyPI's JSON API project_urls) — logged, not blocking, if not found
  - the raw Roseau/griffe bc_types output, formatted human-readably
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pandas as pd

from pipeline_utils import RESULTS_DIR, load_jsonl

SAMPLE_PATH = RESULTS_DIR / "validation" / "bc_validation_sample_corrected.csv"
OUT_PATH = RESULTS_DIR / "validation" / "review_context.jsonl"
DECISIONS_LOG = Path("logs/strengthening_decisions.log")
MAVEN_CENTRAL_BASE = "https://repo.maven.apache.org/maven2"


def dec_log(message: str):
    with DECISIONS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


def http_get(url: str, timeout: int = 15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SecBreak-validation-review/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def maven_changelog_links(dependency_name: str, new_version: str):
    """Best-effort: fetch the POM from Maven Central and parse <scm><url>."""
    if not dependency_name or ":" not in dependency_name or not new_version:
        return None
    group_id, artifact_id = dependency_name.split(":", 1)
    group_path = group_id.replace(".", "/")
    pom_url = f"{MAVEN_CENTRAL_BASE}/{urllib.parse.quote(group_path)}/{urllib.parse.quote(artifact_id)}/{urllib.parse.quote(new_version)}/{urllib.parse.quote(artifact_id)}-{urllib.parse.quote(new_version)}.pom"
    content = http_get(pom_url)
    if not content:
        return None
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    scm_url = None
    for elem in root.iter():
        if strip_ns(elem.tag) == "scm":
            for child in elem:
                if strip_ns(child.tag) == "url" and child.text:
                    scm_url = child.text.strip()
                    break
    if not scm_url:
        return None
    repo_url = re.sub(r"^scm:git:", "", scm_url).rstrip("/")
    repo_url = re.sub(r"\.git$", "", repo_url)
    if "github.com" not in repo_url:
        return {"repo_url": repo_url, "changelog_guess": None, "releases_guess": None}
    return {
        "repo_url": repo_url,
        "changelog_guess": f"{repo_url}/blob/HEAD/CHANGELOG.md",
        "releases_guess": f"{repo_url}/releases",
    }


def pypi_changelog_links(dependency_name: str):
    """Best-effort: PyPI JSON API project_urls."""
    if not dependency_name:
        return None
    pkg = dependency_name.split("[")[0]
    content = http_get(f"https://pypi.org/pypi/{urllib.parse.quote(pkg)}/json")
    if not content:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    info = data.get("info", {})
    urls = dict(info.get("project_urls") or {})
    if info.get("home_page"):
        urls.setdefault("Homepage", info["home_page"])
    changelog = next((v for k, v in urls.items() if "chang" in k.lower()), None)
    repo_url = next((v for k, v in urls.items() if any(t in k.lower() for t in ["source", "repo", "code", "homepage"]) and v and "github.com" in v), None)
    return {
        "repo_url": repo_url,
        "changelog_guess": changelog,
        "releases_guess": f"{repo_url}/releases" if repo_url else None,
        "project_urls": urls,
    }


def format_bc_types(raw) -> str:
    if isinstance(raw, str):
        try:
            items = eval(raw)
        except Exception:
            items = [raw]
    else:
        items = raw or []
    counts = Counter(items)
    return "; ".join(f"{name} x{count}" for name, count in counts.most_common())


def main():
    df = pd.read_csv(SAMPLE_PATH)
    print(f"[prepare_validation_review] {len(df)} rows in validation sample")

    done_keys = set()
    if OUT_PATH.exists():
        for row in load_jsonl(OUT_PATH):
            done_keys.add((row["repo_full_name"], row["pr_number"]))

    lookups_ok = 0
    lookups_failed = 0
    with OUT_PATH.open("a", encoding="utf-8") as fh:
        for idx, row in df.iterrows():
            key = (row["repo_full_name"], int(row["pr_number"]))
            if key in done_keys:
                continue
            pr_diff_url = f"https://github.com/{row['repo_full_name']}/pull/{int(row['pr_number'])}/files"

            dep_links = None
            try:
                if row["ecosystem"] == "maven":
                    dep_links = maven_changelog_links(row.get("dependency_name"), row.get("new_version"))
                elif row["ecosystem"] == "pypi":
                    dep_links = pypi_changelog_links(row.get("dependency_name"))
            except Exception as exc:
                dec_log(f"prepare_validation_review: dependency link lookup failed for {row['repo_full_name']}#{row['pr_number']}: {exc}")

            if dep_links and dep_links.get("repo_url"):
                lookups_ok += 1
            else:
                lookups_failed += 1

            context = {
                "repo_full_name": row["repo_full_name"],
                "pr_number": int(row["pr_number"]),
                "ecosystem": row["ecosystem"],
                "dependency_name": row.get("dependency_name"),
                "old_version": row.get("old_version"),
                "new_version": row.get("new_version"),
                "version_bump_type": row.get("version_bump_type"),
                "detector_verdict": "has_bc" if row.get("has_bc") else "no_bc",
                "bc_count": row.get("bc_count"),
                "tool_used": row.get("tool_used"),
                "pr_diff_url": pr_diff_url,
                "dependency_links": dep_links,
                "bc_types_formatted": format_bc_types(row.get("bc_types")),
            }
            fh.write(json.dumps(context, ensure_ascii=False) + "\n")
            fh.flush()
            if (idx + 1) % 10 == 0:
                print(f"  progress: {idx + 1}/{len(df)}", flush=True)
            time.sleep(0.2)  # be polite to Maven Central / PyPI

    print(f"[prepare_validation_review] dependency link found: {lookups_ok}, not found: {lookups_failed}")
    dec_log(
        f"Phase6 validation review prep: {len(df)} rows, dependency changelog/repo link "
        f"found for {lookups_ok}, not found for {lookups_failed} (logged, non-blocking). "
        f"manual_bc_label/confidence/notes/status columns left untouched for human adjudication."
    )
    print(f"[DONE] prepare_validation_review — {len(df)} records processed, {lookups_ok} links found")


if __name__ == "__main__":
    main()

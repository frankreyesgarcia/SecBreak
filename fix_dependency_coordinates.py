"""Resolve missing Maven groupId:artifactId coordinates by inspecting PR diffs.

parse_dependency_name() in collect_prs.py only captures whatever token appears
in the Dependabot PR title, which for older-style titles ("bump X from A to B")
is just the artifactId with no groupId — 425/554 Maven rows in raw_prs.jsonl
have a dependency_name with no ":" as a result. detect_maven_bcs() then bails
out immediately with analysis_error=missing_dependency_coordinates and those
rows get defaulted to has_bc=False, silently inflating the negative count.

This script fetches each affected PR's changed pom.xml / build.gradle(.kts)
files at base_sha and head_sha, finds the dependency whose version moved from
old_version to new_version, and fills in the real groupId:artifactId. Rows
where no confident match is found are marked coordinate_source=unresolved and
must stay excluded from analysis rather than silently becoming has_bc=False.
"""

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from github import Github
from github.GithubException import GithubException, RateLimitExceededException

from pipeline_utils import DATA_DIR, LOGS_DIR, ensure_layout, load_jsonl, read_json, write_json

RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
CORRECTED_PATH = DATA_DIR / "raw_prs_corrected.jsonl"
CHECKPOINT_PATH = DATA_DIR / "progress_fix_coords.json"
ERROR_LOG = LOGS_DIR / "fix_dependency_coordinates_errors.log"
DECISIONS_LOG = Path("logs/rectification_decisions.log")

GRADLE_BASENAMES = {"build.gradle", "build.gradle.kts"}
GRADLE_TRIPLE_RE = re.compile(r"([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+)")


def setup_loggers():
    ensure_layout()
    Path("logs").mkdir(parents=True, exist_ok=True)
    err = logging.getLogger("fix_coords_errors")
    err.setLevel(logging.INFO)
    err.handlers.clear()
    fh = logging.FileHandler(ERROR_LOG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    err.addHandler(fh)

    dec = logging.getLogger("rectification_decisions")
    dec.setLevel(logging.INFO)
    dec.handlers.clear()
    dh = logging.FileHandler(DECISIONS_LOG)
    dh.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))
    dec.addHandler(dh)
    return err, dec


def require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    token_file = Path("token.txt")
    if token_file.exists():
        candidate = token_file.read_text(encoding="utf-8").strip()
        if candidate:
            return candidate
    raise SystemExit("ERROR: no GitHub token found in GITHUB_TOKEN env var or token.txt")


def with_retry(fn, max_attempts: int = 6):
    attempt = 1
    while True:
        try:
            return fn()
        except RateLimitExceededException:
            if attempt >= max_attempts:
                raise
            delay = min(900, 60 * (2 ** (attempt - 1)))
            time.sleep(delay)
            attempt += 1
        except GithubException as exc:
            if exc.status in {403, 429, 502, 503} and attempt < max_attempts:
                delay = min(900, 60 * (2 ** (attempt - 1)))
                time.sleep(delay)
                attempt += 1
                continue
            raise


def strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_pom(text: str):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], {}
    props = {}
    for elem in root.iter():
        if strip_ns(elem.tag) == "properties":
            for child in elem:
                props[strip_ns(child.tag)] = (child.text or "").strip()
    deps = []
    for elem in root.iter():
        if strip_ns(elem.tag) == "dependency":
            g = a = v = None
            for child in elem:
                name = strip_ns(child.tag)
                if name == "groupId":
                    g = (child.text or "").strip()
                elif name == "artifactId":
                    a = (child.text or "").strip()
                elif name == "version":
                    v = (child.text or "").strip()
            if g and a:
                deps.append((g, a, v))
    return deps, props


def resolve_version(v, props):
    if v and v.startswith("${") and v.endswith("}"):
        return props.get(v[2:-1])
    return v


def narrow_by_hint(candidates, dep_hint):
    if len(candidates) <= 1 or not dep_hint:
        return candidates
    hint = dep_hint.lower()
    narrowed = [c for c in candidates if hint in c[1].lower() or c[1].lower() in hint]
    return narrowed if len(narrowed) == 1 else candidates


def match_pom_dependency(old_text, new_text, old_version, new_version, dep_hint):
    old_deps, old_props = parse_pom(old_text)
    new_deps, new_props = parse_pom(new_text)
    old_map = {(g, a): resolve_version(v, old_props) for g, a, v in old_deps}
    new_map = {(g, a): resolve_version(v, new_props) for g, a, v in new_deps}

    candidates = [key for key, ov in old_map.items() if ov == old_version and new_map.get(key) == new_version]
    candidates = narrow_by_hint(candidates, dep_hint)
    if len(candidates) == 1:
        g, a = candidates[0]
        return f"{g}:{a}"

    if not candidates:
        changed_props = [
            name for name, ov in old_props.items()
            if ov == old_version and new_props.get(name) == new_version
        ]
        if changed_props:
            prop_candidates = [
                (g, a) for g, a, v in new_deps
                if v and v.startswith("${") and v[2:-1] in changed_props
            ]
            prop_candidates = narrow_by_hint(prop_candidates, dep_hint)
            if len(prop_candidates) == 1:
                g, a = prop_candidates[0]
                return f"{g}:{a}"
    return None


def match_gradle_dependency(old_text, new_text, old_version, new_version, dep_hint):
    old_triples = {(g, a): v for g, a, v in GRADLE_TRIPLE_RE.findall(old_text)}
    new_triples = {(g, a): v for g, a, v in GRADLE_TRIPLE_RE.findall(new_text)}
    candidates = [key for key, ov in old_triples.items() if ov == old_version and new_triples.get(key) == new_version]
    candidates = narrow_by_hint(candidates, dep_hint)
    if len(candidates) == 1:
        g, a = candidates[0]
        return f"{g}:{a}"
    return None


def get_file_content(repo, path, ref, err_logger, ctx):
    try:
        result = with_retry(lambda: repo.get_contents(path, ref=ref))
        return result.decoded_content.decode("utf-8", errors="replace")
    except GithubException as exc:
        if exc.status != 404:
            err_logger.warning("get_contents failed %s @ %s (%s): %s", path, ref, ctx, exc)
        return None
    except Exception as exc:
        err_logger.warning("get_contents error %s @ %s (%s): %s", path, ref, ctx, exc)
        return None


def resolve_row(gh, row, err_logger, dec_logger):
    repo_full_name = row["repo_full_name"]
    pr_number = row["pr_number"]
    old_version = row.get("old_version")
    new_version = row.get("new_version")
    dep_hint = row.get("dependency_name")
    ctx = f"{repo_full_name}#{pr_number}"

    try:
        repo = with_retry(lambda: gh.get_repo(repo_full_name))
        pr = with_retry(lambda: repo.get_pull(pr_number))
        files = with_retry(lambda: list(pr.get_files()))
    except Exception as exc:
        err_logger.warning("PR fetch failed for %s: %s", ctx, exc)
        return None, "fetch_failed"

    build_files = [f for f in files if Path(f.filename).name == "pom.xml"]
    gradle_files = [f for f in files if Path(f.filename).name in GRADLE_BASENAMES]

    for f in build_files:
        old_text = get_file_content(repo, f.filename, row["base_sha"], err_logger, ctx)
        new_text = get_file_content(repo, f.filename, row["head_sha"], err_logger, ctx)
        if not old_text or not new_text:
            continue
        match = match_pom_dependency(old_text, new_text, old_version, new_version, dep_hint)
        if match:
            dec_logger.info("%s: resolved via pom.xml (%s) -> %s", ctx, f.filename, match)
            return match, "pr_diff_pom"

    for f in gradle_files:
        old_text = get_file_content(repo, f.filename, row["base_sha"], err_logger, ctx)
        new_text = get_file_content(repo, f.filename, row["head_sha"], err_logger, ctx)
        if not old_text or not new_text:
            continue
        match = match_gradle_dependency(old_text, new_text, old_version, new_version, dep_hint)
        if match:
            dec_logger.info("%s: resolved via %s -> %s", ctx, f.filename, match)
            return match, "pr_diff_gradle"

    dec_logger.info(
        "%s: unresolved (build_files=%d gradle_files=%d old=%s new=%s hint=%s)",
        ctx, len(build_files), len(gradle_files), old_version, new_version, dep_hint,
    )
    return None, "unresolved"


def main():
    ensure_layout()
    err_logger, dec_logger = setup_loggers()
    token = require_token()
    gh = Github(token, per_page=100)

    rows = load_jsonl(RAW_PRS_PATH)
    checkpoint = read_json(CHECKPOINT_PATH, {})

    targets = [
        row for row in rows
        if row.get("ecosystem") == "maven"
        and (not row.get("dependency_name") or ":" not in row.get("dependency_name"))
    ]
    print(f"[fix_dependency_coordinates] {len(targets)} Maven rows need coordinate resolution")

    resolved_pom = resolved_gradle = unresolved = fetch_failed = 0
    already = 0
    for idx, row in enumerate(targets, start=1):
        key = f"{row['repo_full_name']}#{row['pr_number']}"
        if key in checkpoint:
            already += 1
            outcome = checkpoint[key]
        else:
            match, source = resolve_row(gh, row, err_logger, dec_logger)
            outcome = {"dependency_name": match, "coordinate_source": source}
            checkpoint[key] = outcome
            if idx % 20 == 0 or idx == len(targets):
                write_json(CHECKPOINT_PATH, checkpoint)
                print(f"  progress: {idx}/{len(targets)}")

        source = outcome["coordinate_source"]
        if source == "pr_diff_pom":
            resolved_pom += 1
        elif source == "pr_diff_gradle":
            resolved_gradle += 1
        elif source == "fetch_failed":
            fetch_failed += 1
        else:
            unresolved += 1

    write_json(CHECKPOINT_PATH, checkpoint)

    corrected_rows = []
    for row in rows:
        key = f"{row['repo_full_name']}#{row['pr_number']}"
        if key in checkpoint:
            outcome = checkpoint[key]
            row = dict(row)
            if outcome["dependency_name"]:
                row["dependency_name"] = outcome["dependency_name"]
            row["coordinate_source"] = outcome["coordinate_source"]
        else:
            row = dict(row)
            row.setdefault("coordinate_source", "original" if row.get("dependency_name") and ":" in (row.get("dependency_name") or "") else None)
        corrected_rows.append(row)

    with CORRECTED_PATH.open("w", encoding="utf-8") as fh:
        import json
        for row in corrected_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    resolved_total = resolved_pom + resolved_gradle
    pct_resolved = 100 * resolved_total / len(targets) if targets else 0.0
    print("[fix_dependency_coordinates] summary")
    print(f"  total needing resolution: {len(targets)} (from checkpoint cache: {already})")
    print(f"  resolved via pom.xml:     {resolved_pom}")
    print(f"  resolved via gradle:      {resolved_gradle}")
    print(f"  resolved total:           {resolved_total} ({pct_resolved:.1f}%)")
    print(f"  fetch failed (PR/API):    {fetch_failed}")
    print(f"  unresolved (no guess):    {unresolved}")
    print(f"  wrote: {CORRECTED_PATH}")
    print(f"[DONE] fix_dependency_coordinates — {len(rows)} records processed, {resolved_total} changed")


if __name__ == "__main__":
    main()

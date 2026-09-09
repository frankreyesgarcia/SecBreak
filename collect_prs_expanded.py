"""Expanded cohort collection (cohort-growth pass, 2026-09).

Same population definition as collect_prs.py -- Dependabot security PRs in
Java/Python repos with a CI configuration and stars >= MIN_STARS -- but two
sampling limits are relaxed so the cohort stops being under-sampled:

  1. PER_MONTH_CAP raised 100 -> 400 (the original threw away most of every
     busy month; 2023-2024 in particular had far more than 100 qualifying
     Dependabot security PRs per month).
  2. Window widened from 2022-2024 to START_YEAR..END_YEAR = 2021..2025
     (2025 is now a complete year of data).

MIN_STARS, the language filter, and the .github/workflows requirement are
unchanged, so the paper's cohort definition and selection-bias discussion do
not need to be rewritten -- only the "collection period" wording and the
cohort-flow counts.

Appends to data/raw_prs.jsonl; the existing (repo, pr_number) dedup in the
original collector is reused, so the 1,180 rows already collected are not
re-fetched. Run:

    GITHUB_TOKEN=$(tr -d ' \\n' < token.txt) .venv/bin/python collect_prs_expanded.py
"""

import calendar
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Set

from github import Github
from github.GithubException import GithubException

from pipeline_utils import DATA_DIR, LOGS_DIR, append_jsonl, ensure_layout, setup_logger

# Reuse everything that did not need to change.
from collect_prs import (
    guarded_call,
    load_progress,
    repo_matches,
    require_github_token,
    save_progress,
    serialize_pr,
)

RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
ERROR_LOG = LOGS_DIR / "collect_expanded_errors.log"

MIN_STARS = 20
START_YEAR = 2021
END_YEAR = 2025
PER_MONTH_CAP = 400
MAX_CANDIDATES = 20000


def pr_matches(pr, start_year: int = START_YEAR, end_year: int = END_YEAR) -> bool:
    author_login = (pr.user.login or "").lower() if pr.user else ""
    if author_login not in {"dependabot[bot]", "dependabot"}:
        return False
    title = pr.title or ""
    body = pr.body or ""
    labels = {label.name.lower() for label in pr.labels}
    if "security" not in title.lower() and "cve-" not in body.lower() and "security" not in labels:
        return False
    cutoff_start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    cutoff_end = datetime(end_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    closed_at = pr.closed_at or pr.updated_at or pr.created_at
    return bool(closed_at and cutoff_start <= closed_at <= cutoff_end)


def search_security_pr_candidates(gh, logger, progress, start_year, end_year):
    results = []
    seen = set()
    for year in range(end_year, start_year - 1, -1):
        for month in range(12, 0, -1):
            last_day = calendar.monthrange(year, month)[1]
            query = (
                f"is:pr is:closed author:app/dependabot security "
                f"closed:{year}-{month:02d}-01..{year}-{month:02d}-{last_day:02d}"
            )
            issues = guarded_call(gh.search_issues, logger, progress, query=query, sort="updated", order="desc")
            month_count = 0
            for issue in issues:
                key = (issue.repository.full_name, issue.number)
                if key in seen:
                    continue
                seen.add(key)
                results.append(issue)
                month_count += 1
                if month_count >= PER_MONTH_CAP or len(results) >= MAX_CANDIDATES:
                    break
            logger.info("Monthly candidate window %04d-%02d added %s items (running %s)", year, month, month_count, len(results))
            time.sleep(2)
            if len(results) >= MAX_CANDIDATES:
                return results
    return results


def collect() -> None:
    ensure_layout()
    logger = setup_logger("collect_prs_expanded", ERROR_LOG)
    gh = Github(require_github_token(), per_page=100)
    progress = load_progress()
    processed_repos: Set[str] = set(progress.get("processed_repos", []))

    seen_prs = set()
    if RAW_PRS_PATH.exists():
        with RAW_PRS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                seen_prs.add((row["repo_full_name"], row["pr_number"]))

    prior_count = len(seen_prs)
    total_prs = sum(1 for _ in RAW_PRS_PATH.open("r", encoding="utf-8")) if RAW_PRS_PATH.exists() else 0
    repos_with_prs: Set[str] = {repo for repo, _ in seen_prs}
    added = 0

    logger.info(
        "Expanded collection start: window %s-%s, per-month cap %s, min_stars %s, prior unique PRs %s",
        START_YEAR, END_YEAR, PER_MONTH_CAP, MIN_STARS, prior_count,
    )
    candidates = search_security_pr_candidates(gh, logger, progress, START_YEAR, END_YEAR)
    logger.info("Candidate issues gathered: %s", len(candidates))

    for idx, issue in enumerate(candidates, start=1):
        repo = issue.repository
        if (repo.full_name, issue.number) in seen_prs:
            continue
        try:
            if repo.stargazers_count is None or repo.stargazers_count < MIN_STARS:
                continue
            ecosystem = repo_matches(repo, logger, progress)
            if not ecosystem:
                continue
            pr = guarded_call(repo.get_pull, logger, progress, issue.number)
            if not pr_matches(pr):
                continue
            row = serialize_pr(repo, pr, ecosystem)
            append_jsonl(RAW_PRS_PATH, [row])
            seen_prs.add((repo.full_name, pr.number))
            total_prs += 1
            added += 1
            repos_with_prs.add(repo.full_name)
            if added % 25 == 0:
                print(f"Progress: +{added} new PRs ({total_prs} rows total)")
        except Exception as exc:  # noqa: BLE001 -- never stop on one candidate
            logger.exception("Failed candidate %s#%s: %s", repo.full_name, issue.number, exc)
        finally:
            processed_repos.add(repo.full_name)
            if idx % 100 == 0:
                progress["processed_repos"] = sorted(processed_repos)
                progress["pr_count"] = total_prs
                progress["repo_count"] = len(repos_with_prs)
                save_progress(progress)

    progress["processed_repos"] = sorted(processed_repos)
    progress["pr_count"] = total_prs
    progress["repo_count"] = len(repos_with_prs)
    save_progress(progress)
    print(
        f"EXPANDED COLLECTION DONE: +{added} new unique PRs "
        f"(cohort {prior_count} -> {len(seen_prs)}), {len(repos_with_prs)} repositories, "
        f"{total_prs} raw rows in {RAW_PRS_PATH.name}"
    )


if __name__ == "__main__":
    collect()

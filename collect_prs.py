import calendar
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from github import Github
from github.GithubException import GithubException, RateLimitExceededException

from pipeline_utils import (
    DATA_DIR,
    LOGS_DIR,
    append_jsonl,
    ensure_layout,
    ecosystem_from_repo_files,
    extract_cves,
    extract_versions,
    infer_bump_type,
    read_json,
    setup_logger,
    trimmed_text,
    write_json,
)


RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
PROGRESS_PATH = DATA_DIR / "progress_collect.json"
ERROR_LOG = LOGS_DIR / "collect_errors.log"


def require_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable is required. Set it and re-run.")
        raise SystemExit(1)
    return token


def load_progress() -> Dict:
    return read_json(
        PROGRESS_PATH,
        {"processed_repos": [], "request_count": 0, "pr_count": 0, "repo_count": 0},
    )


def save_progress(progress: Dict) -> None:
    write_json(PROGRESS_PATH, progress)


def sleep_for_rate_limit(progress: Dict) -> None:
    progress["request_count"] = progress.get("request_count", 0) + 1
    if progress["request_count"] % 30 == 0:
        time.sleep(1)


def guarded_call(func, logger, progress: Dict, *args, **kwargs):
    attempt = 1
    while True:
        try:
            value = func(*args, **kwargs)
            sleep_for_rate_limit(progress)
            return value
        except RateLimitExceededException as exc:
            logger.warning("GitHub rate limit exceeded: %s", exc)
            delay = min(900, 60 * (2 ** (attempt - 1)))
            time.sleep(delay)
            attempt += 1
        except GithubException as exc:
            if exc.status in {403, 429}:
                logger.warning("GitHub backoff status=%s message=%s", exc.status, exc.data)
                delay = min(900, 60 * (2 ** (attempt - 1)))
                time.sleep(delay)
                attempt += 1
                continue
            raise


def repo_has_ci(repo, logger, progress) -> bool:
    try:
        contents = guarded_call(repo.get_contents, logger, progress, ".github/workflows")
        return isinstance(contents, list) and len(contents) > 0
    except GithubException:
        return False


def repo_matches(repo, logger, progress) -> Optional[str]:
    if repo.stargazers_count is None or repo.stargazers_count < 0:
        return None
    if repo.language not in {"Java", "Python"}:
        return None
    if not repo_has_ci(repo, logger, progress):
        return None
    ecosystem = ecosystem_from_repo_files(repo)
    return ecosystem


def parse_dependency_name(title: str, body: str) -> Optional[str]:
    patterns = [
        r"bump ([\w\.\-:\/]+) from ",
        r"update ([\w\.\-:\/]+) from ",
        r"dependency ([\w\.\-:\/]+)",
    ]
    haystack = f"{title}\n{body}"
    for pattern in patterns:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def classify_state(pr) -> str:
    if pr.merged_at:
        return "merged"
    return "closed"


def pr_matches(pr, start_year: int = 2022) -> bool:
    author_login = (pr.user.login or "").lower() if pr.user else ""
    if author_login not in {"dependabot[bot]", "dependabot"}:
        return False
    title = pr.title or ""
    body = pr.body or ""
    labels = {label.name.lower() for label in pr.labels}
    if "security" not in title.lower() and "cve-" not in body.lower() and "security" not in labels:
        return False
    cutoff_start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    cutoff_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    closed_at = pr.closed_at or pr.updated_at or pr.created_at
    return bool(closed_at and cutoff_start <= closed_at <= cutoff_end)


def serialize_pr(repo, pr, ecosystem: str) -> Dict:
    title = pr.title or ""
    body = pr.body or ""
    old_version, new_version = extract_versions(f"{title}\n{body}")
    return {
        "repo_full_name": repo.full_name,
        "repo_stars": repo.stargazers_count,
        "pr_number": pr.number,
        "pr_title": title,
        "pr_body": trimmed_text(body),
        "pr_state": classify_state(pr),
        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
        "closed_at": pr.closed_at.isoformat() if pr.closed_at else None,
        "base_sha": pr.base.sha,
        "head_sha": pr.head.sha,
        "ecosystem": ecosystem,
        "dependency_name": parse_dependency_name(title, body),
        "old_version": old_version,
        "new_version": new_version,
        "cve_ids": extract_cves(title, body),
        "version_bump_type": infer_bump_type(old_version, new_version),
    }


def search_security_pr_candidates(
    gh: Github,
    logger,
    progress: Dict,
    start_year: int,
    max_candidates: int = 5000,
):
    results = []
    seen = set()
    for year in range(2024, start_year - 1, -1):
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
                if month_count >= 100 or len(results) >= max_candidates:
                    break
            logger.info("Monthly candidate window %04d-%02d added %s items", year, month, month_count)
            time.sleep(2)
            if len(results) >= max_candidates:
                return results
    return results


def search_repositories(
    gh: Github,
    logger,
    progress: Dict,
    min_stars: int,
    start_year: int,
    max_repos_per_language: int = 300,
) -> List:
    results = []
    seen = set()
    for language in ["Java", "Python"]:
        query = f"language:{language} stars:>={min_stars} archived:false pushed:>={start_year}-01-01"
        repos = guarded_call(gh.search_repositories, logger, progress, query=query, sort="stars", order="desc")
        count = 0
        for repo in repos:
            if repo.full_name in seen:
                continue
            seen.add(repo.full_name)
            results.append(repo)
            count += 1
            if count >= max_repos_per_language or len(results) >= max_repos_per_language * 2:
                return results
        logger.info("Repository search added %s %s repos", count, language)
    return results


def collect(min_stars: int = 20, start_year: int = 2022) -> None:
    ensure_layout()
    logger = setup_logger("collect_prs", ERROR_LOG)
    gh = Github(require_github_token(), per_page=100)
    progress = load_progress()
    processed_repos: Set[str] = set(progress.get("processed_repos", []))
    seen_prs = {(row["repo_full_name"], row["pr_number"]) for row in []}
    if RAW_PRS_PATH.exists():
        with RAW_PRS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                seen_prs.add((row["repo_full_name"], row["pr_number"]))

    total_prs = sum(1 for _ in RAW_PRS_PATH.open("r", encoding="utf-8")) if RAW_PRS_PATH.exists() else 0
    repos_with_prs: Set[str] = {repo for repo, _ in seen_prs}
    candidates = search_security_pr_candidates(gh, logger, progress, start_year=start_year)

    for idx, issue in enumerate(candidates, start=1):
        repo = issue.repository
        if repo.full_name in processed_repos and (repo.full_name, issue.number) in seen_prs:
            continue
        try:
            if repo.stargazers_count is None or repo.stargazers_count < min_stars:
                continue
            ecosystem = repo_matches(repo, logger, progress)
            if not ecosystem:
                continue
            pr_number = issue.number
            if (repo.full_name, pr_number) in seen_prs:
                continue
            pr = guarded_call(repo.get_pull, logger, progress, pr_number)
            if not pr_matches(pr, start_year=start_year):
                continue
            row = serialize_pr(repo, pr, ecosystem)
            append_jsonl(RAW_PRS_PATH, [row])
            seen_prs.add((repo.full_name, pr.number))
            total_prs += 1
            repos_with_prs.add(repo.full_name)
            if total_prs % 50 == 0:
                print(f"Progress: {total_prs} PRs")
        except Exception as exc:
            logger.exception("Failed candidate %s#%s: %s", repo.full_name, issue.number, exc)
        finally:
            processed_repos.add(repo.full_name)
            if len(processed_repos) % 100 == 0:
                progress["processed_repos"] = sorted(processed_repos)
                progress["pr_count"] = total_prs
                progress["repo_count"] = len(repos_with_prs)
                save_progress(progress)

    progress["processed_repos"] = sorted(processed_repos)
    progress["pr_count"] = total_prs
    progress["repo_count"] = len(repos_with_prs)
    save_progress(progress)
    print(f"COLLECTED: {total_prs} PRs from {len(repos_with_prs)} repositories")

    if total_prs < 500 and min_stars == 20 and start_year == 2022:
        print("Collection under 500 PRs; widening search to stars>=5 and date range 2020-2024.")
        collect(min_stars=5, start_year=2020)


if __name__ == "__main__":
    collect()

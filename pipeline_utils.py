import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
LOGS_DIR = ROOT / "logs"
REPOS_DIR = ROOT / "repos"
JARS_DIR = ROOT / "jars"
CACHE_DIR = ROOT / "cache"


def ensure_layout() -> None:
    for path in [
        DATA_DIR,
        RESULTS_DIR,
        FIGURES_DIR,
        LOGS_DIR,
        REPOS_DIR,
        JARS_DIR,
        CACHE_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def setup_logger(name: str, log_path: Path) -> logging.Logger:
    ensure_layout()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, obj) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)


def append_jsonl(path: Path, rows: Iterable[Dict]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def semver_key(version: Optional[str]) -> List[int]:
    if not version:
        return [0, 0, 0]
    numbers = [int(part) for part in re.findall(r"\d+", version)]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[:3]


def infer_bump_type(old_version: Optional[str], new_version: Optional[str]) -> str:
    old = semver_key(old_version)
    new = semver_key(new_version)
    if new[0] != old[0]:
        return "major"
    if new[1] != old[1]:
        return "minor"
    if new[2] != old[2]:
        return "patch"
    return "unknown"


def ecosystem_from_repo_files(repo) -> Optional[str]:
    try:
        contents = repo.get_contents("")
    except Exception:
        return None
    names = {item.path for item in contents}
    if "pom.xml" in names:
        return "maven"
    if {"requirements.txt", "setup.py", "pyproject.toml"} & names:
        return "pypi"
    return None


def trimmed_text(text: Optional[str], limit: int = 2000) -> str:
    if not text:
        return ""
    return text[:limit]


def extract_versions(text: str) -> (Optional[str], Optional[str]):
    text = text or ""
    match = re.search(r"from (`?)([^\s`|]+)\1 to (`?)([^\s`|]+)\3", text, re.IGNORECASE)
    if match:
        return match.group(2).strip(".,)"), match.group(4).strip(".,)")

    # Grouped Dependabot PRs often include a markdown table where the row for the
    # security-relevant dependency appears before a more specific prose summary.
    # Fall back to the first well-formed table row instead of mis-parsing the
    # header separator row as old_version/new_version == "|".
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        old_candidate = cells[-2].strip("` ")
        new_candidate = cells[-1].strip("` ")
        if not old_candidate or not new_candidate:
            continue
        if old_candidate.lower() in {"from", "---"} or new_candidate.lower() in {"to", "---"}:
            continue
        if re.search(r"\d", old_candidate) and re.search(r"\d", new_candidate):
            return old_candidate.strip(".,)"), new_candidate.strip(".,)")

    return None, None


def extract_cves(*texts: Optional[str]) -> List[str]:
    found = set()
    for text in texts:
        if not text:
            continue
        found.update(re.findall(r"CVE-\d{4}-\d+", text, re.IGNORECASE))
    return sorted(found)


def sleep_with_backoff(attempt: int, base: int = 60, cap: int = 900) -> None:
    delay = min(cap, base * (2 ** max(attempt - 1, 0)))
    time.sleep(delay)


def wilson_ci(successes: int, total: int, z: float = 1.96) -> (float, float):
    if total == 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1 + (z ** 2) / total
    centre = phat + (z ** 2) / (2 * total)
    adj = z * math.sqrt((phat * (1 - phat) + (z ** 2) / (4 * total)) / total)
    low = (centre - adj) / denom
    high = (centre + adj) / denom
    return low, high


def pct(num: int, den: int) -> float:
    return 0.0 if den == 0 else 100.0 * num / den


def chunked(items: List, size: int) -> Iterable[List]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def bool_int(value) -> int:
    return int(bool(value))

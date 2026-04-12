import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path("/home/kth/SecBreak")
LOGS = ROOT / "logs"
LOCK_PATH = ROOT / ".pipeline_watchdog.lock"
TARGET_PRS = 2000

MANAGED = [
    "collect_prs.py",
    "fetch_nvd.py",
    "detect_bcs.py",
    "build_dataset.py",
    "rq1_analysis.py",
    "rq2_model.py",
    "rq3_analysis.py",
    "generate_report.py",
]


def setup_logger() -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pipeline_watchdog")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(LOGS / "watchdog.log")
    sh = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def unique_pr_keys(path: Path) -> int:
    if not path.exists():
        return 0
    keys = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            keys.add((row["repo_full_name"], row["pr_number"]))
    return len(keys)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def env_with_tokens() -> dict:
    env = os.environ.copy()
    token_file = ROOT / "token.txt"
    if "GITHUB_TOKEN" not in env and token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            env["GITHUB_TOKEN"] = token
    roseau = ROOT / "jars" / "roseau-cli-0.5.0.jar"
    if "ROSEAU_JAR" not in env and roseau.exists():
        env["ROSEAU_JAR"] = str(roseau)
    java25 = Path.home() / ".sdkman" / "candidates" / "java" / "25.0.2-tem"
    if java25.exists():
        env["JAVA_HOME"] = str(java25)
        env["JAVA_BIN"] = str(java25 / "bin" / "java")
        env["PATH"] = f"{java25 / 'bin'}:{env.get('PATH','')}"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def pids_for(script_name: str) -> list[int]:
    try:
        out = subprocess.check_output(["pgrep", "-f", script_name], text=True)
    except subprocess.CalledProcessError:
        return []
    return [int(line.strip()) for line in out.splitlines() if line.strip()]


def dedupe(script_name: str, logger: logging.Logger) -> list[int]:
    pids = sorted(set(pids_for(script_name)))
    if len(pids) <= 1:
        return pids
    keep = max(pids)
    for pid in pids:
        if pid == keep:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Stopped duplicate %s pid=%s; keeping pid=%s", script_name, pid, keep)
        except ProcessLookupError:
            pass
    return [keep]


def start(script_name: str, logger: logging.Logger) -> None:
    out_path = LOGS / f"{script_name}.out"
    cmd = f"cd {ROOT} && nohup python3 -u {script_name} >> {out_path} 2>&1 &"
    subprocess.run(["/usr/bin/zsh", "-lc", cmd], check=False, env=env_with_tokens())
    logger.info("Started %s", script_name)


def unique_cves(raw_path: Path) -> int:
    if not raw_path.exists():
        return 0
    seen = set()
    with raw_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            for cve in row.get("cve_ids", []):
                if cve:
                    seen.add(cve)
    return len(seen)


def main() -> None:
    logger = setup_logger()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("Watchdog already running; exiting")
            return

        for script in MANAGED:
            dedupe(script, logger)

        raw_path = ROOT / "data" / "raw_prs.jsonl"
        cve_path = ROOT / "data" / "cve_details.json"
        bc_path = ROOT / "data" / "bc_results.jsonl"
        dataset_path = ROOT / "data" / "analysis_dataset.csv"
        rq1_path = ROOT / "results" / "rq1_tables.csv"
        rq2_path = ROOT / "results" / "rq2_model_results.csv"
        rq3_path = ROOT / "results" / "rq3_tables.csv"
        report_path = ROOT / "results" / "secbreak_summary.md"

        raw_lines = count_lines(raw_path)
        raw_unique = unique_pr_keys(raw_path)
        bc_lines = unique_pr_keys(bc_path)
        cve_entries = len(load_json(cve_path, {}))
        cve_needed = unique_cves(raw_path)

        logger.info(
            "State raw=%s bc=%s cves=%s/%s dataset=%s rq1=%s rq2=%s rq3=%s report=%s",
            raw_lines,
            bc_lines,
            cve_entries,
            cve_needed,
            dataset_path.exists(),
            rq1_path.exists(),
            rq2_path.exists(),
            rq3_path.exists(),
            report_path.exists(),
        )

        if raw_lines < TARGET_PRS and not pids_for("collect_prs.py"):
            start("collect_prs.py", logger)

        if raw_lines > 0 and cve_entries < cve_needed and not pids_for("fetch_nvd.py"):
            start("fetch_nvd.py", logger)

        if raw_unique > 0 and bc_lines < raw_unique and not pids_for("detect_bcs.py"):
            start("detect_bcs.py", logger)

        collection_done = not pids_for("collect_prs.py")
        nvd_done = cve_entries >= cve_needed
        bc_done = raw_unique > 0 and bc_lines >= raw_unique and not pids_for("detect_bcs.py")

        if collection_done and nvd_done and bc_done:
            if not dataset_path.exists() and not pids_for("build_dataset.py"):
                start("build_dataset.py", logger)
                return
            if dataset_path.exists() and not rq1_path.exists() and not pids_for("rq1_analysis.py"):
                start("rq1_analysis.py", logger)
                return
            if dataset_path.exists() and not rq2_path.exists() and not pids_for("rq2_model.py"):
                start("rq2_model.py", logger)
                return
            if dataset_path.exists() and not rq3_path.exists() and not pids_for("rq3_analysis.py"):
                start("rq3_analysis.py", logger)
                return
            if rq1_path.exists() and rq2_path.exists() and rq3_path.exists() and not report_path.exists() and not pids_for("generate_report.py"):
                start("generate_report.py", logger)
                return

        logger.info("Watchdog cycle complete")


if __name__ == "__main__":
    main()

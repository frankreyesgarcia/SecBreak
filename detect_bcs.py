import json
import os
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from pipeline_utils import (
    CACHE_DIR,
    DATA_DIR,
    JARS_DIR,
    LOGS_DIR,
    REPOS_DIR,
    append_jsonl,
    ensure_layout,
    load_jsonl,
    read_json,
    setup_logger,
    write_json,
)


RAW_PRS_PATH = DATA_DIR / "raw_prs.jsonl"
RESULTS_PATH = DATA_DIR / "bc_results.jsonl"
PROGRESS_PATH = DATA_DIR / "progress_bcs.json"
ERROR_LOG = LOGS_DIR / "bc_errors.log"


def run(cmd: List[str], cwd: Optional[Path] = None, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def maven_copy(artifact: str, out_dir: Path) -> Optional[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            "mvn",
            "dependency:copy",
            f"-Dartifact={artifact}:jar",
            f"-DoutputDirectory={out_dir}",
        ],
        timeout=300,
    )
    if result.returncode != 0:
        return None
    jars = list(out_dir.glob("*.jar"))
    return jars[0] if jars else None


def roseau_available() -> Optional[Path]:
    env_path = os.environ.get("ROSEAU_JAR")
    if env_path and Path(env_path).exists():
        candidate = Path(env_path)
        java_bin = os.environ.get("JAVA_BIN", "java")
        probe = run([java_bin, "-jar", str(candidate), "--help"], timeout=30)
        if probe.returncode == 0:
            return candidate
        return None
    local = list(Path(".").glob("**/roseau-*.jar"))
    for candidate in local:
        java_bin = os.environ.get("JAVA_BIN", "java")
        probe = run([java_bin, "-jar", str(candidate), "--help"], timeout=30)
        if probe.returncode == 0:
            return candidate
    return None


def japicmp_available() -> Optional[Path]:
    path = Path("japicmp.jar")
    return path if path.exists() else None


def parse_roseau_output(path: Path) -> Dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        changes = payload
    else:
        changes = payload.get("breakingChanges") or payload.get("changes") or []
    bc_types = []
    for item in changes:
        if isinstance(item, dict):
            bc_types.append(item.get("kind") or item.get("type") or "UNKNOWN")
        else:
            bc_types.append(str(item))
    return {"has_bc": bool(bc_types), "bc_types": bc_types, "bc_count": len(bc_types)}


def parse_japicmp_output(path: Path) -> Dict:
    tree = ET.parse(path)
    root = tree.getroot()
    bc_types = []
    for elem in root.iter():
        if elem.tag.endswith("compatibilityChange") and elem.attrib.get("binaryCompatible") == "false":
            bc_types.append(elem.attrib.get("type", "INCOMPATIBLE_CHANGE"))
    return {"has_bc": bool(bc_types), "bc_types": bc_types, "bc_count": len(bc_types)}


def detect_maven_bcs(row: Dict, logger) -> Dict:
    dep = row.get("dependency_name")
    old_version = row.get("old_version")
    new_version = row.get("new_version")
    pr_id = f"{row['repo_full_name'].replace('/', '_')}_{row['pr_number']}"
    work_dir = JARS_DIR / pr_id
    try:
        if not dep or ":" not in dep or not old_version or not new_version:
            return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": None, "analysis_error": "missing_dependency_coordinates"}
        old_jar = maven_copy(f"{dep}:{old_version}", work_dir)
        new_jar = maven_copy(f"{dep}:{new_version}", work_dir)
        if not old_jar or not new_jar:
            return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": None, "analysis_error": "jar_download_failed"}

        roseau_jar = roseau_available()
        if roseau_jar:
            out_path = CACHE_DIR / f"{pr_id}_roseau.json"
            java_bin = os.environ.get("JAVA_BIN", "java")
            result = run(
                [
                    java_bin,
                    "-jar",
                    str(roseau_jar),
                    "--diff",
                    "--v1",
                    str(old_jar),
                    "--v2",
                    str(new_jar),
                    "--report",
                    str(out_path),
                    "--format",
                    "JSON",
                ],
                timeout=600,
            )
            if result.returncode == 0 and out_path.exists():
                parsed = parse_roseau_output(out_path)
                parsed["tool_used"] = "roseau"
                parsed["analysis_error"] = None
                return parsed

        japicmp_jar = japicmp_available()
        if japicmp_jar:
            out_path = CACHE_DIR / f"{pr_id}_japicmp.xml"
            result = run(
                [
                    "java",
                    "-jar",
                    str(japicmp_jar),
                    "--old-classpath",
                    str(old_jar),
                    "--new-classpath",
                    str(new_jar),
                    "--xml-file",
                    str(out_path),
                    "--only-incompatible",
                ],
                timeout=600,
            )
            if result.returncode == 0 and out_path.exists():
                parsed = parse_japicmp_output(out_path)
                parsed["tool_used"] = "japicmp"
                parsed["analysis_error"] = None
                return parsed

        return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": None, "analysis_error": "no_bc_tool_available"}
    except Exception as exc:
        logger.exception("Maven BC detection failed for %s#%s: %s", row["repo_full_name"], row["pr_number"], exc)
        return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": None, "analysis_error": str(exc)}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def compare_python_api(old_text: str, new_text: str) -> Dict:
    old_lines = {line.strip() for line in old_text.splitlines() if line.strip().startswith(("def ", "class "))}
    new_lines = {line.strip() for line in new_text.splitlines() if line.strip().startswith(("def ", "class "))}
    removed = sorted(old_lines - new_lines)
    changed = []
    for line in old_lines & new_lines:
        if line.startswith("def "):
            name = line.split("(")[0]
            match = next((candidate for candidate in new_lines if candidate.startswith(name) and candidate != line), None)
            if match:
                changed.append(f"SIGNATURE_CHANGED:{name[4:]}")
    bc_types = [f"API_REMOVED:{item}" for item in removed] + changed
    return {"has_bc": bool(bc_types), "bc_types": bc_types, "bc_count": len(bc_types), "tool_used": "griffe"}


def detect_python_bcs(row: Dict, logger) -> Dict:
    dep = row.get("dependency_name")
    old_version = row.get("old_version")
    new_version = row.get("new_version")
    if not dep or not old_version or not new_version:
        return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": "griffe", "analysis_error": "missing_python_dependency_metadata"}

    with tempfile.TemporaryDirectory(prefix="secbreak_pybc_") as temp_dir:
        base = Path(temp_dir)
        old_env = base / "old_env"
        new_env = base / "new_env"
        venv.EnvBuilder(with_pip=True).create(old_env)
        venv.EnvBuilder(with_pip=True).create(new_env)
        old_python = old_env / "bin" / "python"
        new_python = new_env / "bin" / "python"
        install_old = run([str(old_python), "-m", "pip", "install", f"{dep}=={old_version}", "griffe"], timeout=600)
        install_new = run([str(new_python), "-m", "pip", "install", f"{dep}=={new_version}", "griffe"], timeout=600)
        if install_old.returncode != 0 or install_new.returncode != 0:
            return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": "griffe", "analysis_error": "pip_install_failed"}
        old_dump = run(
            [
                str(old_python),
                "-c",
                "import importlib, inspect, sys; m=importlib.import_module(sys.argv[1]); print(inspect.getsource(m))",
                dep.split("[")[0].replace("-", "_"),
            ],
            timeout=120,
        )
        new_dump = run(
            [
                str(new_python),
                "-c",
                "import importlib, inspect, sys; m=importlib.import_module(sys.argv[1]); print(inspect.getsource(m))",
                dep.split("[")[0].replace("-", "_"),
            ],
            timeout=120,
        )
        if old_dump.returncode != 0 or new_dump.returncode != 0:
            return {"has_bc": False, "bc_types": [], "bc_count": 0, "tool_used": "griffe", "analysis_error": "source_extraction_failed"}
        parsed = compare_python_api(old_dump.stdout, new_dump.stdout)
        parsed["analysis_error"] = None
        return parsed


def clone_repo(repo_full_name: str, sha: str, target: Path) -> bool:
    repo_url = f"https://github.com/{repo_full_name}.git"
    clone = run(["git", "clone", "--depth", "1", repo_url, str(target)], timeout=600)
    if clone.returncode != 0:
        return False
    checkout = run(["git", "fetch", "--depth", "1", "origin", sha], cwd=target, timeout=300)
    if checkout.returncode != 0:
        return False
    return run(["git", "checkout", sha], cwd=target, timeout=120).returncode == 0


def run_repo_tests(repo_path: Path, ecosystem: str) -> Dict:
    if ecosystem == "maven":
        if not (repo_path / "pom.xml").exists():
            return {"tests_available": False, "tests_timeout": False}
        cmd = ["mvn", "test", "-DskipITs"]
    else:
        if not any((repo_path / name).exists() for name in ["pytest.ini", "pyproject.toml", "setup.py", "requirements.txt"]):
            return {"tests_available": False, "tests_timeout": False}
        cmd = ["pytest", "-q"]
    try:
        result = run(cmd, cwd=repo_path, timeout=300)
        failed = []
        for line in (result.stdout + "\n" + result.stderr).splitlines():
            if "FAILED" in line and "::" in line:
                failed.append(line.strip())
        return {
            "tests_available": True,
            "tests_timeout": False,
            "passed": result.returncode == 0,
            "failures": failed[:50],
        }
    except subprocess.TimeoutExpired:
        return {"tests_available": True, "tests_timeout": True, "passed": False, "failures": []}


def behavioral_check(row: Dict, logger) -> Dict:
    repo_name = row["repo_full_name"].replace("/", "_")
    repo_dir = REPOS_DIR / repo_name
    try:
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        if not clone_repo(row["repo_full_name"], row["base_sha"], repo_dir):
            return {
                "tests_available": False,
                "tests_pass_old": None,
                "tests_pass_new": None,
                "test_failures_new": [],
                "tests_timeout": False,
            }
        old_results = run_repo_tests(repo_dir, row["ecosystem"])
        if not old_results["tests_available"]:
            return {
                "tests_available": False,
                "tests_pass_old": None,
                "tests_pass_new": None,
                "test_failures_new": [],
                "tests_timeout": False,
            }
        if run(["git", "checkout", row["head_sha"]], cwd=repo_dir, timeout=120).returncode != 0:
            return {
                "tests_available": True,
                "tests_pass_old": old_results["passed"],
                "tests_pass_new": None,
                "test_failures_new": [],
                "tests_timeout": False,
            }
        new_results = run_repo_tests(repo_dir, row["ecosystem"])
        return {
            "tests_available": True,
            "tests_pass_old": old_results["passed"],
            "tests_pass_new": new_results.get("passed"),
            "test_failures_new": new_results.get("failures", []),
            "tests_timeout": old_results.get("tests_timeout") or new_results.get("tests_timeout"),
        }
    except Exception as exc:
        logger.exception("Behavioral check failed for %s#%s: %s", row["repo_full_name"], row["pr_number"], exc)
        return {
            "tests_available": False,
            "tests_pass_old": None,
            "tests_pass_new": None,
            "test_failures_new": [],
            "tests_timeout": False,
        }
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)


def main():
    ensure_layout()
    logger = setup_logger("detect_bcs", ERROR_LOG)
    rows = load_jsonl(RAW_PRS_PATH)
    processed = {(row["repo_full_name"], row["pr_number"]) for row in load_jsonl(RESULTS_PATH)}
    progress = read_json(PROGRESS_PATH, {"processed": 0})

    out_batch = []
    for idx, row in enumerate(rows, start=1):
        key = (row["repo_full_name"], row["pr_number"])
        if key in processed:
            continue
        if row["ecosystem"] == "maven":
            syntactic = detect_maven_bcs(row, logger)
        else:
            syntactic = detect_python_bcs(row, logger)
        behavioral = behavioral_check(row, logger)
        result = {
            "repo_full_name": row["repo_full_name"],
            "pr_number": row["pr_number"],
            "has_bc": syntactic["has_bc"],
            "bc_types": syntactic["bc_types"],
            "bc_count": syntactic["bc_count"],
            "tool_used": syntactic.get("tool_used"),
            "tests_available": behavioral["tests_available"],
            "tests_pass_old": behavioral["tests_pass_old"],
            "tests_pass_new": behavioral["tests_pass_new"],
            "test_failures_new": behavioral["test_failures_new"],
            "tests_timeout": behavioral["tests_timeout"],
            "analysis_error": syntactic.get("analysis_error"),
        }
        out_batch.append(result)
        processed.add(key)
        if len(out_batch) >= 25:
            append_jsonl(RESULTS_PATH, out_batch)
            out_batch.clear()
            progress["processed"] = len(processed)
            write_json(PROGRESS_PATH, progress)
            print(f"BC progress: {len(processed)}/{len(rows)}")

    if out_batch:
        append_jsonl(RESULTS_PATH, out_batch)
        progress["processed"] = len(processed)
        write_json(PROGRESS_PATH, progress)
    print(f"BC detection completed for {len(processed)} PRs")


if __name__ == "__main__":
    main()

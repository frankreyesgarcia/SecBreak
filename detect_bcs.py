import json
import os
import shutil
import subprocess
import tempfile
import time
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


MAVEN_CENTRAL_BASE = "https://repo.maven.apache.org/maven2"


def maven_copy(artifact: str, out_dir: Path) -> Optional[Path]:
    """Downloads a jar directly from Maven Central via HTTPS instead of
    `mvn dependency:copy`. In this environment, `mvn dependency:copy` (and
    even plain plugin resolution, i.e. before it even reaches the target
    artifact) hangs indefinitely: Maven selects a legacy WagonTransporter
    that never opens a socket to repo.maven.apache.org (confirmed via `ss`
    while it hung), even though a direct curl/HTTPS request to the exact
    same URL resolves in well under a second and `mvn test` reactor builds
    (a different resolver code path) download from Central successfully.
    Bypassing the dependency-plugin mojo entirely sidesteps whatever is
    broken in that specific resolution path.
    """
    import urllib.parse
    import urllib.request
    import urllib.error

    parts = artifact.split(":")
    if len(parts) != 3:
        return None
    group_id, artifact_id, version = parts
    if not group_id or not artifact_id or not version:
        return None

    group_path = group_id.replace(".", "/")
    filename = f"{artifact_id}-{version}.jar"
    url = f"{MAVEN_CENTRAL_BASE}/{urllib.parse.quote(group_path)}/{urllib.parse.quote(artifact_id)}/{urllib.parse.quote(version)}/{urllib.parse.quote(filename)}"

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / filename
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SecBreak-rectification/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        dest.unlink(missing_ok=True)
        return None
    if not dest.exists() or dest.stat().st_size == 0:
        return None
    return dest


def resolve_java_bin() -> str:
    """Roseau's class files require Java >=25 (UnsupportedClassVersionError
    otherwise); the default `java` on PATH in this environment is Java 21.
    If JAVA_BIN isn't explicitly set, auto-discover an sdkman Java 25
    candidate instead of silently falling back to a `java` that can't run
    Roseau at all — that exact silent-fallback caused an entire rerun to
    produce zero roseau results before this was caught."""
    env_bin = os.environ.get("JAVA_BIN")
    if env_bin:
        return env_bin
    sdkman_java = Path.home() / ".sdkman" / "candidates" / "java"
    if sdkman_java.exists():
        candidates = sorted(sdkman_java.glob("25.*"), reverse=True)
        for candidate in candidates:
            java_path = candidate / "bin" / "java"
            if java_path.exists():
                return str(java_path)
    return "java"


def roseau_available() -> Optional[Path]:
    java_bin = resolve_java_bin()
    env_path = os.environ.get("ROSEAU_JAR")
    if env_path and Path(env_path).exists():
        candidate = Path(env_path)
        probe = run([java_bin, "-jar", str(candidate), "--help"], timeout=30)
        if probe.returncode == 0:
            return candidate
        return None
    local = list(Path(".").glob("**/roseau-*.jar"))
    for candidate in local:
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
            java_bin = resolve_java_bin()
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


MAVEN_TEST_TIMEOUT_DEFAULT = 1800  # was 300s; too short for cold-.m2, full-suite runs (Phase 4 diagnosis)
PYPI_TEST_TIMEOUT_DEFAULT = 1200
PYPI_INSTALL_TIMEOUT_DEFAULT = 600

PYTHON_PROJECT_MARKERS = [
    "pytest.ini", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "tox.ini", "Pipfile",
]


def _tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if text else ""


def _log_invocation(logger, ctx: str, cmd, cwd, returncode, elapsed, stdout, stderr, timed_out: bool):
    if logger is None:
        return
    logger.info(
        "[%s] cmd=%s cwd=%s returncode=%s elapsed=%.1fs timed_out=%s\n--- stdout tail ---\n%s\n--- stderr tail ---\n%s",
        ctx, " ".join(cmd), cwd, returncode, elapsed, timed_out, _tail(stdout), _tail(stderr),
    )


def _prepare_python_venv(repo_path: Path, logger, ctx: str, install_timeout: int) -> Optional[Path]:
    """Create a throwaway venv, install the repo's own deps + pytest into it.

    Behavioral testing previously ran the bare `pytest` command against
    PATH, with no guarantee pytest (or the repo's own dependencies) were
    installed anywhere — that's why tests_available was False for 100% of
    PyPI rows: run_repo_tests() raised FileNotFoundError, which propagated
    up through behavioral_check()'s broad except-Exception and silently
    became "tests_available: False" with no record of why.
    """
    venv_dir = repo_path.parent / f"{repo_path.name}_testenv"
    shutil.rmtree(venv_dir, ignore_errors=True)
    start = time.time()
    try:
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    except Exception as exc:
        if logger:
            logger.warning("[%s] venv creation failed: %s", ctx, exc)
        return None
    pip = venv_dir / "bin" / "pip"

    install_cmds = [[str(pip), "install", "--quiet", "pytest"]]
    if (repo_path / "pyproject.toml").exists() or (repo_path / "setup.py").exists():
        install_cmds.append([str(pip), "install", "--quiet", "-e", "."])
    elif (repo_path / "requirements.txt").exists():
        install_cmds.append([str(pip), "install", "--quiet", "-r", "requirements.txt"])

    for cmd in install_cmds:
        try:
            result = run(cmd, cwd=repo_path, timeout=install_timeout)
        except subprocess.TimeoutExpired:
            if logger:
                logger.warning("[%s] install timed out: %s", ctx, " ".join(cmd))
            return None
        elapsed = time.time() - start
        _log_invocation(logger, f"{ctx}:install", cmd, repo_path, result.returncode, elapsed, result.stdout, result.stderr, False)
        if result.returncode != 0 and cmd is install_cmds[-1]:
            # the repo's own install failed; pytest alone still lets us try collection,
            # but record this so it's distinguishable from a harness bug.
            if logger:
                logger.warning("[%s] repo dependency install failed (returncode=%s)", ctx, result.returncode)
    return venv_dir


def run_repo_tests(repo_path: Path, ecosystem: str, logger=None, ctx: str = "", timeout: Optional[int] = None) -> Dict:
    if ecosystem == "maven":
        if not (repo_path / "pom.xml").exists():
            if logger:
                logger.info("[%s] no pom.xml at %s -> tests_available=False", ctx, repo_path)
            return {"tests_available": False, "tests_timeout": False, "harness_error": "no_pom_xml"}
        cmd = ["mvn", "test", "-B", "-fae"]
        effective_timeout = timeout or MAVEN_TEST_TIMEOUT_DEFAULT
    else:
        if not any((repo_path / name).exists() for name in PYTHON_PROJECT_MARKERS):
            if logger:
                logger.info("[%s] no python project markers at %s -> tests_available=False", ctx, repo_path)
            return {"tests_available": False, "tests_timeout": False, "harness_error": "no_python_project_markers"}
        venv_dir = _prepare_python_venv(repo_path, logger, ctx, PYPI_INSTALL_TIMEOUT_DEFAULT)
        if venv_dir is None:
            return {"tests_available": False, "tests_timeout": False, "harness_error": "test_dependency_install_failed"}
        cmd = [str(venv_dir / "bin" / "pytest"), "-q", "--maxfail=50"]
        effective_timeout = timeout or PYPI_TEST_TIMEOUT_DEFAULT

    start = time.time()
    try:
        result = run(cmd, cwd=repo_path, timeout=effective_timeout)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - start
        _log_invocation(logger, ctx, cmd, repo_path, None, elapsed, exc.stdout or "", exc.stderr or "", True)
        return {"tests_available": True, "tests_timeout": True, "passed": False, "failures": [], "elapsed_seconds": elapsed}
    except FileNotFoundError as exc:
        if logger:
            logger.warning("[%s] command not found: %s (%s)", ctx, " ".join(cmd), exc)
        return {"tests_available": False, "tests_timeout": False, "harness_error": f"command_not_found:{cmd[0]}"}

    elapsed = time.time() - start
    _log_invocation(logger, ctx, cmd, repo_path, result.returncode, elapsed, result.stdout, result.stderr, False)
    failed = []
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        if "FAILED" in line and "::" in line:
            failed.append(line.strip())
    return {
        "tests_available": True,
        "tests_timeout": False,
        "passed": result.returncode == 0,
        "failures": failed[:50],
        "elapsed_seconds": elapsed,
    }


def behavioral_check(row: Dict, logger, check_flaky: bool = False, maven_timeout: Optional[int] = None, pypi_timeout: Optional[int] = None) -> Dict:
    repo_name = row["repo_full_name"].replace("/", "_")
    repo_dir = REPOS_DIR / repo_name
    ctx = f"{row['repo_full_name']}#{row['pr_number']}"
    timeout = maven_timeout if row["ecosystem"] == "maven" else pypi_timeout
    empty = {
        "tests_available": False,
        "tests_pass_old": None,
        "tests_pass_new": None,
        "test_failures_new": [],
        "tests_timeout": False,
        "harness_error": None,
        "flaky_old": None,
    }
    try:
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        if not clone_repo(row["repo_full_name"], row["base_sha"], repo_dir):
            out = dict(empty)
            out["harness_error"] = "clone_failed"
            return out
        old_results = run_repo_tests(repo_dir, row["ecosystem"], logger, f"{ctx}:old", timeout)
        if not old_results["tests_available"]:
            out = dict(empty)
            out["harness_error"] = old_results.get("harness_error")
            return out

        flaky_old = None
        if check_flaky:
            old_results_2 = run_repo_tests(repo_dir, row["ecosystem"], logger, f"{ctx}:old_rerun", timeout)
            if old_results_2["tests_available"]:
                flaky_old = old_results["passed"] != old_results_2["passed"]

        # clone_repo() only fetches base_sha (--depth 1); head_sha's commit object
        # is not present in the shallow history yet, so `git checkout head_sha`
        # fails with "fatal: reference is not a tree" unless it's fetched first.
        # This was silently swallowing tests_pass_new to None on essentially every
        # row in the original harness.
        fetch_head = run(["git", "fetch", "--depth", "1", "origin", row["head_sha"]], cwd=repo_dir, timeout=300)
        _log_invocation(logger, f"{ctx}:fetch_head", ["git", "fetch", "--depth", "1", "origin", row["head_sha"]], repo_dir, fetch_head.returncode, 0.0, fetch_head.stdout, fetch_head.stderr, False)
        if fetch_head.returncode != 0:
            return {
                "tests_available": True,
                "tests_pass_old": old_results["passed"],
                "tests_pass_new": None,
                "test_failures_new": [],
                "tests_timeout": old_results.get("tests_timeout", False),
                "harness_error": "head_fetch_failed",
                "flaky_old": flaky_old,
            }
        checkout = run(["git", "checkout", row["head_sha"]], cwd=repo_dir, timeout=120)
        _log_invocation(logger, f"{ctx}:checkout_head", ["git", "checkout", row["head_sha"]], repo_dir, checkout.returncode, 0.0, checkout.stdout, checkout.stderr, False)
        if checkout.returncode != 0:
            return {
                "tests_available": True,
                "tests_pass_old": old_results["passed"],
                "tests_pass_new": None,
                "test_failures_new": [],
                "tests_timeout": old_results.get("tests_timeout", False),
                "harness_error": "head_checkout_failed",
                "flaky_old": flaky_old,
            }
        new_results = run_repo_tests(repo_dir, row["ecosystem"], logger, f"{ctx}:new", timeout)
        return {
            "tests_available": True,
            "tests_pass_old": old_results["passed"],
            "tests_pass_new": new_results.get("passed"),
            "test_failures_new": new_results.get("failures", []),
            "tests_timeout": old_results.get("tests_timeout") or new_results.get("tests_timeout"),
            "harness_error": new_results.get("harness_error"),
            "flaky_old": flaky_old,
        }
    except Exception as exc:
        logger.exception("Behavioral check failed for %s: %s", ctx, exc)
        out = dict(empty)
        out["harness_error"] = f"exception:{exc}"
        return out
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)
        shutil.rmtree(repo_dir.parent / f"{repo_dir.name}_testenv", ignore_errors=True)


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

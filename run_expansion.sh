#!/usr/bin/env bash
# Cohort-growth pass: collect (expanded) -> NVD enrich -> stop before BC detection.
set -u
cd "$(dirname "$0")"
export GITHUB_TOKEN="$(tr -d ' \n' < token.txt)"
LOG=logs/expansion_run.log
echo "=== $(date -u +%FT%TZ) expansion run start ===" >> "$LOG"

echo "--- stage 1: expanded collection ---" >> "$LOG"
.venv/bin/python collect_prs_expanded.py >> "$LOG" 2>&1
echo "collect exit=$? at $(date -u +%FT%TZ)" >> "$LOG"

echo "--- stage 2: NVD enrichment ---" >> "$LOG"
.venv/bin/python fetch_nvd.py >> "$LOG" 2>&1
echo "fetch_nvd exit=$? at $(date -u +%FT%TZ)" >> "$LOG"

python3 - <<'PY' >> "$LOG" 2>&1
import json, collections
rows=[json.loads(l) for l in open("data/raw_prs.jsonl") if l.strip()]
uniq={(r["repo_full_name"], r["pr_number"]) for r in rows}
eco=collections.Counter(r.get("ecosystem") for r in rows)
bump=collections.Counter(r.get("version_bump_type") for r in rows)
cve=sum(1 for r in rows if r.get("cve_ids"))
print("raw rows:", len(rows))
print("unique PRs:", len(uniq))
print("unique repos:", len({r for r,_ in uniq}))
print("with >=1 CVE:", cve)
print("ecosystem:", dict(eco))
print("bump:", dict(bump))
PY

echo "=== $(date -u +%FT%TZ) expansion run DONE (paused before BC detection) ===" >> "$LOG"
touch logs/expansion_STAGE_COLLECT_ENRICH_DONE

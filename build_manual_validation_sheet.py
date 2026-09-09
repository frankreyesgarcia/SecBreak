"""Assemble the manual BC-detector adjudication sheet.

Human-in-the-loop harness for the pre-submission validation gate: this script
only *prepares* the sheet. It does NOT assign labels -- every `label` cell is
left blank for a human reviewer. No network calls; everything is joined from
local artifacts:

  results/validation/bc_validation_sample_corrected.csv  the frozen 100-row sample
  results/validation/review_context.jsonl                P6 pre-fetch (diff URL,
                                                          curated changelog link,
                                                          human-readable bc_types)
  data/raw_prs_corrected.jsonl                           Dependabot PR title/body

Output: results/manual_validation_sheet.csv, ordered so the 65 rows that have a
curated dependency changelog link come first (label those first -- they give the
most confident initial 20-30), then the 35 without.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "results/validation/bc_validation_sample_corrected.csv"
REVIEW = ROOT / "results/validation/review_context.jsonl"
RAW = ROOT / "data/raw_prs_corrected.jsonl"
OUT = ROOT / "results/manual_validation_sheet.csv"

CHANGELOG_WINDOW = 4000   # chars to scan after the section heading (Dependabot nests <details>)
CHANGELOG_MAX_CHARS = 1500
CHANGELOG_MAX_LINES = 18

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


def clean_html(fragment: str) -> str:
    text = html.unescape(fragment)
    text = re.sub(r"<li>", "\n  - ", text)
    text = re.sub(r"</(p|div|h[1-6]|tr|ul|ol|blockquote|pre)>", "\n", text)
    text = _TAG.sub("", text)
    text = _WS.sub(" ", text)
    text = _BLANKS.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def extract_changelog(pr_body: str) -> str:
    """Pull the Release notes / Changelog section from a Dependabot PR body.

    Dependabot nests <details> blocks, so instead of trying to match the closing
    tag we scan a fixed window from the section heading up to the next
    <summary>...</summary> (the following section) and clean that.
    """
    if not pr_body:
        return ""
    for heading in ("Release notes", "Changelog"):
        m = re.search(rf"<summary>\s*{re.escape(heading)}\s*</summary>", pr_body, re.IGNORECASE)
        if not m:
            continue
        window = pr_body[m.end(): m.end() + CHANGELOG_WINDOW]
        nxt = re.search(r"<summary>", window)
        if nxt:
            window = window[: nxt.start()]
        cleaned = clean_html(window)
        if not cleaned:
            continue
        lines = cleaned.splitlines()
        clipped = "\n".join(lines[:CHANGELOG_MAX_LINES])[:CHANGELOG_MAX_CHARS].rstrip()
        if len(lines) > CHANGELOG_MAX_LINES or len(clipped) < len(cleaned):
            clipped += "\n  ... [truncated -- see changelog_link / pr_url]"
        return f"[{heading}] {clipped}"
    return ""


def format_changelog_link(links) -> str:
    """review_context dependency_links is a dict of guessed URLs, or None."""
    if not links:
        return ""
    if isinstance(links, str):
        return links
    parts = []
    for label, key in (("changelog", "changelog_guess"), ("releases", "releases_guess"), ("repo", "repo_url")):
        if links.get(key):
            parts.append(f"{label}: {links[key]}")
    return "  |  ".join(parts)


def compress_bc_types(raw_list: str) -> str:
    """Fallback human-readable rollup if review_context has no formatted string."""
    try:
        items = json.loads(raw_list.replace("'", '"'))
    except Exception:
        return raw_list or ""
    counts: dict[str, int] = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    return "; ".join(f"{k} x{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def diff_snippet(row: pd.Series, pr_title: str, diff_url: str) -> str:
    """Reconstructed manifest-bump view. This is NOT the raw file diff -- for a
    Dependabot PR the changed lines are the single dependency version in the
    build manifest; follow the URL for the exact file hunk."""
    manifest = "pom.xml / build.gradle" if row["ecosystem"] == "maven" else "requirements / setup / pyproject"
    return (
        f"{pr_title.strip()}\n"
        f"manifest ({manifest}) -- dependency version bump only:\n"
        f"  - {row['dependency_name']} : {row['old_version']}\n"
        f"  + {row['dependency_name']} : {row['new_version']}\n"
        f"full file diff: {diff_url}"
    )


def main() -> None:
    sample = pd.read_csv(SAMPLE)
    review = {(r["repo_full_name"], r["pr_number"]): r for r in (json.loads(l) for l in REVIEW.open())}
    raw = {(r["repo_full_name"], r["pr_number"]): r for r in (json.loads(l) for l in RAW.open())}

    rows = []
    for _, s in sample.iterrows():
        key = (s["repo_full_name"], int(s["pr_number"]))
        rc = review.get(key, {})
        pr = raw.get(key, {})
        pr_url = f"https://github.com/{s['repo_full_name']}/pull/{int(s['pr_number'])}"
        diff_url = rc.get("pr_diff_url") or f"{pr_url}/files"
        changelog_link = format_changelog_link(rc.get("dependency_links"))
        excerpt = extract_changelog(pr.get("pr_body", ""))
        rows.append(
            {
                "pr_id": f"{s['repo_full_name']}#{int(s['pr_number'])}",
                "repo_full_name": s["repo_full_name"],
                "pr_number": int(s["pr_number"]),
                "ecosystem": s["ecosystem"],
                "detector": s["tool_used"],
                "dependency": s["dependency_name"],
                "version_from": s["old_version"],
                "version_to": s["new_version"],
                "version_bump_type": s["version_bump_type"],
                "detector_verdict": "BC" if int(s["has_bc"]) == 1 else "no-BC",
                "bc_count": int(s["bc_count"]),
                "bc_types": (
                    (rc.get("bc_types_formatted") or compress_bc_types(s.get("bc_types", "")))
                    if int(s["has_bc"]) == 1
                    else "(detector reported no BC)"
                ),
                "pr_diff_snippet": diff_snippet(s, pr.get("pr_title", ""), diff_url),
                "changelog_excerpt": excerpt,
                "changelog_link": changelog_link,
                "changelog_context": (
                    "curated-link" if changelog_link else ("pr-body-excerpt" if excerpt else "none")
                ),
                "pr_url": pr_url,
                "label": "",
                "notes": "",
            }
        )

    df = pd.DataFrame(rows)
    # Stable order: strongest context first (curated changelog link), then rows
    # with at least a PR-body changelog excerpt, then rows with neither. Within
    # each tier the frozen sample order is preserved.
    tier = {"curated-link": 0, "pr-body-excerpt": 1, "none": 2}
    df["_grp"] = df["changelog_context"].map(tier)
    df = df.sort_values(["_grp"], kind="stable").drop(columns="_grp").reset_index(drop=True)
    df.insert(0, "sort_rank", range(1, len(df) + 1))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)

    n_link = int((df["changelog_context"] == "curated-link").sum())
    n_excerpt_only = int((df["changelog_context"] == "pr-body-excerpt").sum())
    n_any_excerpt = int((df["changelog_excerpt"].str.len() > 0).sum())
    n_none = int((df["changelog_context"] == "none").sum())
    print(f"wrote {OUT}  ({len(df)} rows)")
    print(f"  detector verdict:  BC={int((df.detector_verdict=='BC').sum())}  no-BC={int((df.detector_verdict=='no-BC').sum())}")
    print(f"  detector:          roseau={int((df.detector=='roseau').sum())}  griffe={int((df.detector=='griffe').sum())}")
    print("  changelog context tiers (labeling order):")
    print(f"    rows 1-{n_link}: curated changelog link  (strongest -- label these first)")
    print(f"    rows {n_link + 1}-{n_link + n_excerpt_only}: PR-body changelog/release-notes excerpt only")
    print(f"    rows {n_link + n_excerpt_only + 1}-100: neither ({n_none} rows -- use bc_types + diff URL)")
    print(f"  changelog excerpt populated on {n_any_excerpt}/100 rows overall")
    print(f"  all label cells blank: {(df['label'] == '').all()}")


if __name__ == "__main__":
    main()

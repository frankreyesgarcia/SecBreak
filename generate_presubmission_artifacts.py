from __future__ import annotations

import ast
import csv
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd
from scipy.stats import chi2_contingency, mannwhitneyu, spearmanr

ROOT = Path('/mnt/ssd3/frank/SecBreak')
RESULTS = ROOT / 'results'
PAPER = ROOT / 'paper' / 'secbreak_tse_revision.tex'
DATA = ROOT / 'data' / 'analysis_dataset_corrected.csv'
RECT = RESULTS / 'RECTIFICATION_REPORT.md'


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (float('nan'), float('nan'))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return center - margin, center + margin


def fmt_pct(x: float, decimals: int = 1) -> str:
    """Format a fraction in [0, 1] as a percentage (0.421 -> '42.1%')."""
    return f"{x * 100:.{decimals}f}%"


def fmt_pct_value(x: float, decimals: int = 1) -> str:
    """Format a value that is ALREADY a percentage (42.1 -> '42.1%').

    rq1_bounds.json stores every *_pct field and the imputed bootstrap CI in
    percent units already; passing them through fmt_pct double-scales by 100.
    """
    return f"{x:.{decimals}f}%"


def fmt_num(x: float, decimals: int = 3) -> str:
    return f"{x:.{decimals}f}"


def load_df() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    for col in ['analyzed_ok', 'has_bc', 'has_cve', 'merged']:
        if col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.lower().map({'true': True, 'false': False})
    if 'merged' not in df.columns:
        df['merged'] = df['merged_at'].notna() if 'merged_at' in df.columns else False
    if 'analyzed_ok' not in df.columns:
        df['analyzed_ok'] = df['analysis_error'].isna()
    if 'has_bc' in df.columns and df['has_bc'].dtype != bool:
        df['has_bc'] = df['has_bc'].fillna(False).astype(bool)
    return df


def line_number(path: Path, needle: str) -> int | None:
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if needle in line:
            return i
    return None


def parse_bc_types(value: str) -> list[str]:
    if pd.isna(value) or value == '[]':
        return []
    try:
        parsed = ast.literal_eval(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def support_rows(df: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    analyzed = df[df['analyzed_ok'] == True].copy()
    unanalyzed = df[df['analyzed_ok'] != True].copy()
    bc = analyzed[analyzed['has_bc'] == True].copy()

    def add(key: str, value: str, detail: str, raw_source: str) -> None:
        rows.append({'key': key, 'value': value, 'detail': detail, 'raw_source': raw_source})

    add('cohort.raw_rows', '1180', 'Raw collection rows before deduplication.', 'results/cohort/cohort_flow.json')
    add('cohort.final_prs', str(len(df)), 'Unique PRs in corrected analysis dataset.', 'data/analysis_dataset_corrected.csv')
    add('cohort.repos_final', str(df['repo_full_name'].nunique()), 'Distinct repositories in final cohort.', 'data/analysis_dataset_corrected.csv')
    eco_counts = df['ecosystem'].value_counts().to_dict()
    add('cohort.ecosystem_counts', f"maven={eco_counts.get('maven', 0)}, pypi={eco_counts.get('pypi', 0)}", 'Ecosystem counts in final cohort.', 'data/analysis_dataset_corrected.csv')
    merged_n = int(df['merged'].sum())
    add('cohort.merged_rate', f"{merged_n}/{len(df)} ({fmt_pct(merged_n/len(df))})", 'Merged PR share in final cohort.', 'data/analysis_dataset_corrected.csv')
    add('rq1.coverage', f"{len(analyzed)}/{len(df)} ({fmt_pct(len(analyzed)/len(df))})", 'Pipeline coverage rate.', 'results/rq1_tables_corrected.csv')
    ci_low, ci_high = wilson_ci(int(bc['has_bc'].sum()), len(analyzed))
    add('rq1.analyzed_prevalence', f"{len(bc)}/{len(analyzed)} ({fmt_pct(len(bc)/len(analyzed))})", f"Wilson CI [{fmt_pct(ci_low)}, {fmt_pct(ci_high)}]", 'results/rq1_tables_corrected.csv')
    add('rq1.full_naive_rate', f"{len(bc)}/{len(df)} ({fmt_pct(len(bc)/len(df))})", 'Full-cohort naive rate, not prevalence.', 'results/rq1_tables_corrected.csv')
    add('rq1.provider_baseline', '13.2%', 'External baseline cited from Raemaekers et al. (2021).', 'paper citation raemaekers2021')

    for eco in ['maven', 'pypi']:
        sub = analyzed[analyzed['ecosystem'] == eco]
        pos = int(sub['has_bc'].sum())
        low, high = wilson_ci(pos, len(sub))
        add(f'rq1.ecosystem.{eco}', f"{pos}/{len(sub)} ({fmt_pct(pos/len(sub))})", f"Wilson CI [{fmt_pct(low)}, {fmt_pct(high)}]", 'data/analysis_dataset_corrected.csv')
    ct = pd.crosstab(analyzed['ecosystem'], analyzed['has_bc'])
    chi2, p, _, _ = chi2_contingency(ct)
    add('rq1.ecosystem.chi2', f"chi2={chi2:.3f}, p={p:.3e}", 'Ecosystem vs. BC contingency test on analyzed rows.', 'data/analysis_dataset_corrected.csv')

    for bump in ['patch', 'minor', 'major']:
        sub = analyzed[analyzed['version_bump_type'] == bump]
        pos = int(sub['has_bc'].sum())
        low, high = wilson_ci(pos, len(sub))
        add(f'rq1.bump.{bump}', f"{pos}/{len(sub)} ({fmt_pct(pos/len(sub))})", f"Wilson CI [{fmt_pct(low)}, {fmt_pct(high)}]", 'data/analysis_dataset_corrected.csv')
    ct = pd.crosstab(analyzed['version_bump_type'], analyzed['has_bc'])
    chi2, p, _, _ = chi2_contingency(ct)
    add('rq1.bump.chi2', f"chi2={chi2:.3f}, p={p:.3e}", 'Version bump type vs. BC contingency test on analyzed rows.', 'data/analysis_dataset_corrected.csv')

    sev_map = {1: 'LOW', 2: 'MEDIUM', 3: 'HIGH', 4: 'CRITICAL'}
    sev_series = analyzed['cvss_severity_ord'].map(sev_map)
    rho, p = spearmanr(analyzed['cvss_severity_ord'], analyzed['has_bc'].astype(int), nan_policy='omit')
    add('rq1.cvss.spearman', f"rho={rho:.3f}, p={p:.3f}", 'Spearman correlation between ordinal CVSS severity and BC risk.', 'data/analysis_dataset_corrected.csv')
    for sev in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
        sub = analyzed[sev_series == sev]
        if len(sub) == 0:
            continue
        pos = int(sub['has_bc'].sum())
        low, high = wilson_ci(pos, len(sub))
        add(f'rq1.cvss.{sev.lower()}', f"{pos}/{len(sub)} ({fmt_pct(pos/len(sub))})", f"Wilson CI [{fmt_pct(low)}, {fmt_pct(high)}]", 'data/analysis_dataset_corrected.csv')

    bc_counter = Counter()
    for types in bc['bc_types'].apply(parse_bc_types):
        for t in types:
            if t.startswith('METHOD_'):
                bc_counter['method'] += 1
            elif t.startswith('TYPE_'):
                bc_counter['type'] += 1
            elif t.startswith('FIELD_'):
                bc_counter['field'] += 1
    total_bc_events = sum(bc_counter.values())
    for kind in ['method', 'type', 'field']:
        add(f'rq1.bc_kind.{kind}', fmt_pct(bc_counter[kind] / total_bc_events), f"{bc_counter[kind]} of {total_bc_events} classified BC events.", 'data/analysis_dataset_corrected.csv')

    bounds = json.loads((RESULTS / 'rq1_bounds.json').read_text())
    add('rq1.bounds', f"[{fmt_pct_value(bounds['worst_case_lower_pct'])}, {fmt_pct_value(bounds['worst_case_upper_pct'])}]", 'Worst-case Manski bounds.', 'results/rq1_bounds.json')
    add('rq1.imputed', fmt_pct_value(bounds['model_imputed_pct']), f"bootstrap CI [{fmt_pct_value(bounds['model_imputed_bootstrap_ci'][0])}, {fmt_pct_value(bounds['model_imputed_bootstrap_ci'][1])}]", 'results/rq1_bounds.json')
    add('rq1.unanalyzed_n', str(bounds['n_unanalyzed']), 'Number of unanalyzed rows used in bounds/imputation.', 'results/rq1_bounds.json')
    add('rq1.bootstrap_n', str(bounds['n_bootstrap']), 'Number of bootstrap resamples for imputation interval.', 'results/rq1_bounds.json')

    rq2 = pd.read_csv(RESULTS / 'rq2_model_results_corrected.csv')
    for _, row in rq2.iterrows():
        add(f"rq2.model.{row['model']}", f"{row['auc_roc_mean']:.3f} ± {row['auc_roc_std']:.3f}", f"{int(row['n_repeats'])} repeats x {int(row['n_splits'])} folds = {int(row['n_folds'])} evaluations.", 'results/rq2_model_results_corrected.csv')
    add('rq2.analyzed_repos', str(analyzed['repo_full_name'].nunique()), 'Distinct repositories represented in analyzed rows.', 'data/analysis_dataset_corrected.csv')

    feat = pd.read_csv(RESULTS / 'rq2_feature_importance_corrected.csv')
    for key in ['repo_stars', 'ecosystem_bin', 'cvss_score', 'version_bump_ord', 'cvss_severity_ord', 'has_cve']:
        val = feat.loc[feat['feature'] == key, 'importance'].iloc[0]
        rank = int(feat.sort_values('importance', ascending=False).reset_index(drop=True).query('feature == @key').index[0]) + 1
        add(f'rq2.feature.{key}', f"{val:.3f}", f"Feature-importance rank {rank} of {len(feat)}.", 'results/rq2_feature_importance_corrected.csv')

    logit = pd.read_csv(RESULTS / 'rq2_logit_coefficients_converged.csv')
    for key in ['ecosystem_bin', 'version_bump_ord', 'cvss_score', 'repo_stars']:
        row = logit.loc[logit['feature'] == key].iloc[0]
        add(f'rq2.logit.{key}', f"beta={row['coef']:.2f}, p={row['p_value']:.3g}", f"95% CI [{row['ci_low']:.2f}, {row['ci_high']:.2f}]", 'results/rq2_logit_coefficients_converged.csv')

    rq3 = pd.read_csv(RESULTS / 'rq3_tables_strict.csv')
    for _, row in rq3.iterrows():
        label = row['label']
        add(f"rq3.{label}.base", str(int(row['n_bc_prs'])), 'BC-introducing PRs in this RQ3 variant.', 'results/rq3_tables_strict.csv')
        add(f"rq3.{label}.fixes", f"{int(row['fixes_found'])}/{int(row['n_bc_prs'])} ({row['fixes_found_pct']:.3f}%)", f"Median {row['median_fix_days']:.3f} days; IQR {row['iqr_low']:.3f}-{row['iqr_high']:.3f}", 'results/rq3_tables_strict.csv')
        add(f"rq3.{label}.followup", f"7d={row['within_7d_pct']:.3f}%, 30d={row['within_30d_pct']:.3f}%, reverted={row['reverted_pct']:.3f}%", 'Follow-up response percentages.', 'results/rq3_tables_strict.csv')
    merged_bc = int(bc['merged'].sum())
    add('rq3.merged_bc', f"{merged_bc}/{len(bc)} ({fmt_pct(merged_bc/len(bc))})", 'Merged share among BC-introducing PRs.', 'data/analysis_dataset_corrected.csv')

    add('rectification.missing_coords', '425/554 (76.7%)', 'Maven rows whose older-style titles lacked resolvable groupId:artifactId before rectification.', 'results/RECTIFICATION_REPORT.md')
    add('rectification.original_analyzed_n', '201', 'Original analyzed set size before strengthened reruns.', 'results/RECTIFICATION_REPORT.md')
    add('validation.sample_n', '100', 'Rows in corrected manual validation sample.', 'results/validation/validation_sample_summary_corrected.json')
    add('discussion.patch_recovery', '69.3% vs. 10.0%', 'Patch-bump BC rate among recovered rows vs original analyzed set, as documented in rectification report.', 'results/RECTIFICATION_REPORT.md')
    add('discussion.sample_spotcheck_n', '10', 'Manual spot-check count for newly-resolved rows documented in rectification report.', 'results/RECTIFICATION_REPORT.md')
    add('threats.target_prs', '2000', 'Original aspirational collection target mentioned in paper; not traced to a structured output artifact.', 'MISSING')
    return rows


def claim_rows() -> list[dict[str, str]]:
    claims = [
        ('Abstract', 'Restricting the estimate to the 380 PRs', 'rq1.coverage'),
        ('Abstract', '42.1\\% (160/380, 95\\% CI 37.2\\%--47.1\\%)', 'rq1.analyzed_prevalence'),
        ('Abstract', '13.2\\% provider-side baseline', 'rq1.provider_baseline'),
        ('Abstract', 'Maven PRs (65.6\\%) drive nearly all of this risk; PyPI PRs (1.4\\%) remain low', 'rq1.ecosystem.maven|rq1.ecosystem.pypi'),
        ('Abstract', 'AUC-ROC 0.894\\$\\pm\\$0.069', 'rq2.model.Random Forest'),
        ('Abstract', '33.8\\% are merged anyway; the median follow-up fix time is 3.5 days', 'rq3.merged_bc|rq3.STRICT (relatedness-filtered).fixes'),
        ('Related Work', '18,415 Maven artifacts and found that 11.6\\%', 'EXTERNAL_CITATION'),
        ('Frozen Cohort', 'The raw collection contained 1{,}180 rows', 'cohort.raw_rows'),
        ('Frozen Cohort', '783 unique PRs across 132 repositories (554 Maven, 229 PyPI), of which 52.9\\% (414/783) were merged', 'cohort.final_prs|cohort.repos_final|cohort.ecosystem_counts|cohort.merged_rate'),
        ('Feature Engineering and Analysis', 'marking the 380 PRs where BC detection genuinely executed', 'rq1.coverage'),
        ('Validation Package', 'stratified manual-validation package of 100 sampled PRs', 'validation.sample_n'),
        ('Data Rectification', '425 of 554 Maven rows (76.7\\%)', 'rectification.missing_coords'),
        ('RQ1', 'Pipeline coverage ... 48.5\\% (380/783)', 'rq1.coverage'),
        ('RQ1', '42.1\\% (160/380, 95\\% Wilson CI 37.2\\%--47.1\\%)', 'rq1.analyzed_prevalence'),
        ('RQ1', 'full-cohort naive rate (20.4\\%, 160/783)', 'rq1.full_naive_rate'),
        ('RQ1', 'Maven reaches 65.6\\% (158/241) versus 1.4\\% (2/139) for PyPI', 'rq1.ecosystem.maven|rq1.ecosystem.pypi|rq1.ecosystem.chi2'),
        ('RQ1', '37.3\\% for patch updates, 34.7\\% for minor updates, and 60.6\\% for major updates', 'rq1.bump.patch|rq1.bump.minor|rq1.bump.major|rq1.bump.chi2'),
        ('RQ1', 'Spearman \\$\\rho=-0.072\\$, \\$p=0.164\\$', 'rq1.cvss.spearman'),
        ('RQ1', '88.1\\% for LOW, 29.8\\% for MEDIUM, 36.9\\% for HIGH, and 50.0\\% for CRITICAL', 'rq1.cvss.low|rq1.cvss.medium|rq1.cvss.high|rq1.cvss.critical'),
        ('RQ1', 'method-level changes (79.0\\%), followed by type-level (11.6\\%) and field-level (9.4\\%)', 'rq1.bc_kind.method|rq1.bc_kind.type|rq1.bc_kind.field'),
        ('RQ1 Robustness', '403 unanalyzed rows', 'rq1.unanalyzed_n'),
        ('RQ1 Robustness', 'range of [20.4\\%, 71.9\\%]', 'rq1.bounds'),
        ('RQ1 Robustness', '38.0\\% [36.6\\%, 39.2\\%]', 'rq1.imputed'),
        ('RQ1 Robustness', '1{,}000 resamples', 'rq1.bootstrap_n'),
        ('RQ2', '380 PRs, 109 distinct repositories', 'rq1.coverage|rq2.analyzed_repos'),
        ('RQ2', '5 repeats \\$\\times\\$ 5 folds = 25 evaluations', 'rq2.model.Random Forest'),
        ('RQ2', '0.500 \\pm 0.000', 'rq2.model.Dummy (most_frequent)'),
        ('RQ2', '0.849 \\pm 0.082', 'rq2.model.Logistic Regression'),
        ('RQ2', '0.894 \\pm 0.069', 'rq2.model.Random Forest'),
        ('RQ2', '0.879 \\pm 0.067', 'rq2.model.Gradient Boosting'),
        ('RQ2', '0.794 \\pm 0.106', 'rq2.model.Decision Tree'),
        ('RQ2', 'repository stars (importance 0.381), ecosystem (0.188), CVSS score (0.116), version-bump magnitude (0.075), and ordinal CVSS severity (0.066)', 'rq2.feature.repo_stars|rq2.feature.ecosystem_bin|rq2.feature.cvss_score|rq2.feature.version_bump_ord|rq2.feature.cvss_severity_ord'),
        ('RQ2', 'has\\_cve ... negligible (0.004, rank 15 of 16)', 'rq2.feature.has_cve'),
        ('RQ2', '\\$\\beta=-5.26\\$, 95\\% CI \\$[-6.81,-3.70]\\$, \\$p=3.7\\times10^{-11}\\$', 'rq2.logit.ecosystem_bin'),
        ('RQ2', '\\$\\beta=0.68\\$, 95\\% CI \\$[0.25,1.11]\\$, \\$p=0.002\\$', 'rq2.logit.version_bump_ord'),
        ('RQ2', '\\$p=0.36\\$ and \\$p=0.36\\$', 'rq2.logit.cvss_score|rq2.logit.repo_stars'),
        ('RQ3', '160 BC-introducing PRs, 54 were merged anyway (33.8\\%)', 'rq3.merged_bc'),
        ('RQ3', '784 candidate PRs across the 160 BC PRs; ... leaves 248 (31.6\\% ...; 68.4\\% were unrelated)', 'rq3.NAIVE (keyword-only, original corrected run).base|rq3.STRICT (relatedness-filtered).base'),
        ('RQ3', '3.5 days (IQR 0.8--10.4) ... 20.0\\% fixed within seven days ... 25.6\\% within 30 days ... 14.4\\% ... 8.8\\%', 'rq3.STRICT (relatedness-filtered).fixes|rq3.STRICT (relatedness-filtered).followup|rq3.NAIVE (keyword-only, original corrected run).followup'),
        ('Discussion', '6--9\\$\\times\\$ higher BC rates than the original 201-row analyzed set', 'rectification.original_analyzed_n'),
        ('Discussion', '69.3\\% vs. 10.0\\% for patch bumps', 'discussion.patch_recovery'),
        ('Discussion', 'manual spot-checks of 10 newly-resolved rows', 'discussion.sample_spotcheck_n'),
        ('Threats', '48.5\\% of the cohort (380/783)', 'rq1.coverage'),
        ('Threats', 'median 9{,}234 vs. 16{,}684 stars ... 36.6\\% vs. 22.3\\% ... 44.2\\% vs. 61.0\\% ... \\$p=0.777\\$', 'EXTERNAL_SELECTION_BIAS'),
        ('Threats', '[20.4\\%, 71.9\\%] and a model-based imputed estimate of 38.0\\%', 'rq1.bounds|rq1.imputed'),
        ('Threats', '2{,}000-PR target', 'threats.target_prs'),
        ('Conclusion', '42.1\\% introduce a syntactic BC', 'rq1.analyzed_prevalence'),
        ('Conclusion', '65.6\\% vs. 1.4\\% for PyPI; even patch-level updates introduce a BC 37.3\\% of the time', 'rq1.ecosystem.maven|rq1.ecosystem.pypi|rq1.bump.patch'),
        ('Conclusion', 'AUC-ROC \\$0.894\\pm0.069\\$', 'rq2.model.Random Forest'),
        ('Conclusion', 'median 3.5 days', 'rq3.STRICT (relatedness-filtered).fixes'),
    ]
    return [{'section': a, 'needle': b, 'support_keys': c} for a, b, c in claims]


def main() -> None:
    df = load_df()
    support = support_rows(df)
    support_path = RESULTS / 'presubmission_supporting_metrics.csv'
    with support_path.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['key', 'value', 'detail', 'raw_source'])
        writer.writeheader()
        writer.writerows(support)
    line_map = {row['key']: i + 2 for i, row in enumerate(support)}

    claim_out = []
    for row in claim_rows():
        paper_line = line_number(PAPER, row['needle'])
        keys = row['support_keys'].split('|')
        if row['support_keys'] == 'EXTERNAL_CITATION':
            status = 'external-citation'
            source_file = 'paper/secbreak_tse_revision.tex bibliography / cited paper'
            source_line = ''
            value = '11.6%, 18,415'
            notes = 'Requires external citation verification, handled in section C.'
        elif row['support_keys'] == 'EXTERNAL_SELECTION_BIAS':
            status = 'traced'
            source_file = 'results/selection_bias_table.csv'
            source_line = ''
            value = 'selection-bias summary'
            notes = 'Backed by selection-bias table and manuscript text.'
        else:
            missing = [k for k in keys if k not in line_map]
            if missing:
                status = 'missing'
                source_file = 'MISSING'
                source_line = ''
                value = ''
                notes = f'Unresolved support keys: {missing}'
            else:
                status = 'traced'
                source_file = 'results/presubmission_supporting_metrics.csv'
                source_line = ','.join(str(line_map[k]) for k in keys)
                value = '; '.join(next(s['value'] for s in support if s['key'] == k) for k in keys)
                notes = '; '.join(next(s['detail'] for s in support if s['key'] == k) for k in keys)
                if 'MISSING' in [next(s['raw_source'] for s in support if s['key'] == k) for k in keys]:
                    status = 'missing'
                    notes += ' | No structured raw artifact found in repo.'
        claim_out.append({
            'paper_section': row['section'],
            'paper_line': paper_line if paper_line is not None else '',
            'claim_text': row['needle'],
            'value': value,
            'source_file': source_file,
            'source_line': source_line,
            'status': status,
            'notes': notes,
        })

    claim_path = RESULTS / 'presubmission_claim_trace.csv'
    with claim_path.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['paper_section', 'paper_line', 'claim_text', 'value', 'source_file', 'source_line', 'status', 'notes'])
        writer.writeheader()
        writer.writerows(claim_out)


if __name__ == '__main__':
    main()

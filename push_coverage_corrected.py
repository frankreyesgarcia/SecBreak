import json
from pathlib import Path

from detect_bcs import detect_maven_bcs, detect_python_bcs
from pipeline_utils import DATA_DIR, LOGS_DIR, SUPPORTED_BC_ECOSYSTEMS, detector_ecosystem, load_jsonl, normalize_pr_record, read_json, setup_logger, write_json

RAW_PATH = DATA_DIR / 'raw_prs_corrected.jsonl'
BC_PATH = DATA_DIR / 'bc_results_corrected.jsonl'
CHECKPOINT_PATH = DATA_DIR / 'progress_push_coverage.json'
ERROR_LOG = LOGS_DIR / 'push_coverage_corrected.log'
SAVE_EVERY = 1


def unsupported_result(raw_row):
    dep_ecosystem = raw_row.get('dependency_ecosystem') or 'unknown'
    return {
        'has_bc': False,
        'bc_types': [],
        'bc_count': 0,
        'tool_used': None,
        'analysis_error': f'unsupported_dependency_ecosystem:{dep_ecosystem}',
    }


def row_needs_processing(raw_row, bc_row):
    err = bc_row.get('analysis_error')
    if err is None:
        return False
    dep_detector = detector_ecosystem(raw_row)
    if dep_detector is None:
        # Relabel everything unsupported so it stops being counted as an opaque failure.
        return not str(err).startswith('unsupported_dependency_ecosystem:')
    return True


def main():
    logger = setup_logger('push_coverage_corrected', ERROR_LOG)
    raw_rows = [normalize_pr_record(r) for r in load_jsonl(RAW_PATH)]
    bc_rows = load_jsonl(BC_PATH)
    checkpoint = read_json(CHECKPOINT_PATH, {})

    raw_by_key = {(r['repo_full_name'], r['pr_number']): r for r in raw_rows}
    out_rows = []
    targets = []
    for row in bc_rows:
        key = (row['repo_full_name'], row['pr_number'])
        raw_row = raw_by_key[key]
        if row_needs_processing(raw_row, row):
            targets.append((key, raw_row, row))

    print(f'[push_coverage_corrected] pending rows: {len(targets)}')

    processed = improved = unsupported = 0
    for idx, (key, raw_row, bc_row) in enumerate(targets, start=1):
        ck_key = f'{key[0]}#{key[1]}'
        if ck_key in checkpoint:
            result = checkpoint[ck_key]
        else:
            det = detector_ecosystem(raw_row)
            if det == 'maven':
                result = detect_maven_bcs(raw_row, logger)
            elif det == 'pypi':
                result = detect_python_bcs(raw_row, logger)
            else:
                result = unsupported_result(raw_row)
            checkpoint[ck_key] = result
            if idx % SAVE_EVERY == 0 or idx == len(targets):
                write_json(CHECKPOINT_PATH, checkpoint)
                print(f'  progress: {idx}/{len(targets)}', flush=True)

        merged = dict(bc_row)
        merged['has_bc'] = result['has_bc']
        merged['bc_types'] = result['bc_types']
        merged['bc_count'] = result['bc_count']
        merged['tool_used'] = result.get('tool_used')
        merged['analysis_error_previous'] = bc_row.get('analysis_error')
        merged['analysis_error'] = result.get('analysis_error')
        merged['dependency_ecosystem'] = raw_row.get('dependency_ecosystem')
        merged['detector_ecosystem'] = raw_row.get('detector_ecosystem')
        merged['rectified_in_coverage_push'] = True
        checkpoint[ck_key] = {
            'has_bc': merged['has_bc'],
            'bc_types': merged['bc_types'],
            'bc_count': merged['bc_count'],
            'tool_used': merged['tool_used'],
            'analysis_error': merged['analysis_error'],
        }
        raw_by_key[key]['dependency_ecosystem'] = raw_row.get('dependency_ecosystem')
        raw_by_key[key]['detector_ecosystem'] = raw_row.get('detector_ecosystem')
        raw_by_key[key]['repo_ecosystem'] = raw_row.get('repo_ecosystem')
        processed += 1
        if bc_row.get('analysis_error') is not None and merged.get('analysis_error') is None:
            improved += 1
        if str(merged.get('analysis_error') or '').startswith('unsupported_dependency_ecosystem:'):
            unsupported += 1
        out_rows.append((key, merged))

    write_json(CHECKPOINT_PATH, checkpoint)

    merged_map = {key: row for key, row in out_rows}
    final_bc_rows = []
    for row in bc_rows:
        key = (row['repo_full_name'], row['pr_number'])
        final_bc_rows.append(merged_map.get(key, row))

    with RAW_PATH.open('w', encoding='utf-8') as fh:
        for row in raw_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    with BC_PATH.open('w', encoding='utf-8') as fh:
        for row in final_bc_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')

    print('[push_coverage_corrected] summary')
    print(f'  processed: {processed}')
    print(f'  now analyzed_ok candidates: {improved}')
    print(f'  relabeled unsupported: {unsupported}')
    print(f'  supported detector ecosystems: {sorted(SUPPORTED_BC_ECOSYSTEMS)}')
    print(f'  wrote: {RAW_PATH}')
    print(f'  wrote: {BC_PATH}')
    print(f'  checkpoint: {CHECKPOINT_PATH}')


if __name__ == '__main__':
    main()

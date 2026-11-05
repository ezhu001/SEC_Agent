"""Read existing audits only; create a documentation index, not new app runs."""
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def recompute(calculation):
    inputs = calculation['inputs']
    formula = calculation['formula_id']
    periods = sorted(next(iter(inputs.values())), reverse=True)
    if formula.endswith('growth'):
        values = next(iter(inputs.values()))
        new, old = (values[p] for p in periods)
        return (new - old) / old * 100
    components = {
        'current_ratio': ('current_assets', 'current_liabilities'),
        'operating_margin': ('operating_income', 'revenue'),
        'gross_margin': ('gross_profit', 'revenue'),
        'rd_intensity': ('research_and_development', 'revenue'),
    }
    base = formula.removesuffix('_change')
    numerator, denominator = components[base]
    multiplier = 1 if base == 'current_ratio' else 100
    values = [inputs[numerator][p] / inputs[denominator][p] * multiplier for p in periods]
    return values[0] - values[1] if formula.endswith('_change') else values[0]


def main():
    records = []
    for path in sorted((ROOT / 'artifacts/runs').glob('*/audit.json')):
        raw = json.loads(path.read_text(encoding='utf-8'))
        state = raw.get('state', raw)
        calculation = state.get('calculation_result')
        record = {
            'run_id': path.parent.name,
            'audit_path': path.relative_to(ROOT).as_posix(),
            'recorded_status': state.get('final_status') or 'PARTIAL',
            'question': state.get('user_question'),
            'source_hash': state.get('filing_hash'),
            'source_metadata': state.get('filing_metadata'),
            'formula_id': state.get('formula_id'),
            'required_periods': state.get('required_periods'),
            'accepted_evidence': state.get('accepted_evidence'),
            'decoder_calls': state.get('decoder_call_count'),
            'corrections': state.get('correction_count'),
            'expansions': state.get('expanded_search_count'),
            'total_seconds': state.get('timings', {}).get('total_seconds'),
            'qwen_enabled': state.get('config', {}).get('qwen_enabled', 'UNRECORDED'),
            'calculation': calculation,
            'errors': state.get('errors', []),
        }
        if calculation:
            try:
                actual = recompute(calculation)
                record['arithmetic_consistency'] = {
                    'recomputed_value': actual,
                    'matches_recorded': math.isclose(actual, calculation['value'], rel_tol=1e-12, abs_tol=1e-12),
                    'scope': 'Independent arithmetic from stored calculator inputs only; not evidence or financial-ground-truth validation.',
                }
            except Exception as exc:
                record['arithmetic_consistency'] = {'error': str(exc)}
        records.append(record)
    counts = dict(Counter(r['recorded_status'] for r in records))
    suite = ElementTree.parse(ROOT / 'artifacts/executable-verifier-final.xml').getroot().find('testsuite')
    report = (OUT / 'AGENTIC_AI_RISK_MANAGEMENT_MIDTERM_REPORT.md').read_text(encoding='utf-8')
    referenced = set(re.findall(r'`([0-9a-f]{32})`', report))
    by_id = {r['run_id']: r for r in records}
    missing = sorted(referenced - by_id.keys())
    payload = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'method': 'Read existing canonical artifacts/runs/*/audit.json only. No model calls or pipeline reruns. Partial means no terminal status was recorded. Recovery-only files are outside this count.',
        'warning': 'Development corpus inventory, not a benchmark. Arithmetic consistency does not validate selected financial evidence.',
        'canonical_audits': len(records),
        'status_counts': counts,
        'retained_test_suite': suite.attrib,
        'report_referenced_runs': sorted(referenced),
        'missing_report_run_references': missing,
        'runs': records,
    }
    (OUT / 'RUN_EVIDENCE_INDEX.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    arithmetic = [r for r in records if r.get('arithmetic_consistency')]
    problems = [r['run_id'] for r in arithmetic if not r['arithmetic_consistency'].get('matches_recorded')]
    print(json.dumps({'audits': len(records), 'status_counts': counts,
                      'report_words': len(report.split()), 'referenced_runs': len(referenced),
                      'missing_references': missing, 'stored_calculations_checked': len(arithmetic),
                      'arithmetic_problems': problems}, indent=2))
    assert not missing, missing
    assert not problems, problems


if __name__ == '__main__':
    main()

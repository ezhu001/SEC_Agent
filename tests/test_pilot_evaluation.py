import copy
import json
from pathlib import Path

import pytest

from evaluation.cases import Case, build_cases, expectations, score
from evaluation.batch_runner import write_reports


@pytest.fixture
def case():
    ref = json.loads(Path('evaluation/cases/pilot_references.json').read_text())['references']['TSLA']
    return Case(case_id='test', ticker='TSLA', group='formula', mode='agents', formula='current_ratio_change',
                source='local.html', source_hash='hash', reference=ref, development_company=True)


def correct_result(case):
    expected = expectations(case)
    evidence = {}
    for component, values in expected['inputs'].items():
        evidence[component] = {'label': case.reference['labels'][component][0], 'filing_hash': 'hash',
            'facts': [{'period': p, 'value': v, 'end': case.reference['ends'][i],
                       'unit': 'currency', 'currency': 'USD', 'dimensions': {}} for i, (p, v) in enumerate(values.items())]}
    return {'final_status': 'SUCCESS', 'accepted_evidence': {c: c for c in evidence},
            'calculation_result': {**expected, 'formula_id': case.formula}, 'final_response': {'evidence': evidence}}


def test_independent_correct_answer_and_no_gold_in_request(case):
    assert score(case, correct_result(case))['grade'] == 'CORRECT_ANSWER'
    assert set(case.request()) == {'case_id', 'source', 'periods', 'question', 'formula', 'agents', 'fault'}
    assert 'reference' not in json.dumps(case.request())


@pytest.mark.parametrize('change', ['number', 'unit', 'formula', 'input', 'label', 'scope', 'date', 'missing_value'])
def test_wrong_answers_are_explicit_even_with_success_status(case, change):
    result = correct_result(case)
    calc = result['calculation_result']
    row = result['final_response']['evidence']['current_assets']
    if change == 'number': calc['value'] += 1
    elif change == 'unit': calc['unit'] = 'percent'
    elif change == 'formula': calc['formula_id'] = 'operating_margin_change'
    elif change == 'input': calc['inputs']['current_assets']['FY2025'] += 100
    elif change == 'label': row['label'] = 'Total assets'
    elif change == 'scope': row['facts'][0]['dimensions'] = {'Axis': 'Segment'}
    elif change == 'date': row['facts'][0]['end'] = '2024-12-31'
    elif change == 'missing_value': calc['value'] = None
    assert score(case, result)['grade'] == 'WRONG_ANSWER'


def test_abstention_is_only_correct_for_reviewed_missing_evidence(case):
    result = {'final_status': 'INSUFFICIENT_EVIDENCE', 'calculation_result': None, 'decoder_call_count': 0}
    assert score(case, result)['grade'] == 'UNEXPECTED_ABSTENTION'
    missing = case.model_copy(update={'expected_status': 'INSUFFICIENT_EVIDENCE'})
    assert score(missing, result)['grade'] == 'CORRECT_ABSTENTION'
    result['decoder_call_count'] = 1
    assert score(missing, result)['grade'] == 'WRONG_ANSWER'


def test_matrix_counts_and_separate_repeat_and_fault_groups():
    refs = json.loads(Path('evaluation/cases/pilot_references.json').read_text())
    corpus = {'filings': [{'ticker': t, 'status': 'AVAILABLE', 'local_path': str(Path.cwd() / 'fake.html'), 'sha256': 'hash'} for t in refs['references']]}
    cases = build_cases(corpus, refs)
    assert len(cases) == len({c.case_id for c in cases}) == 96
    assert sum(c.group == 'repeat' for c in cases) == 40
    assert sum(c.fault for c in cases) == 2
    assert sum(c.group == 'planner' for c in cases) == 6
    assert all(c.request()['formula'] is None for c in cases if c.group == 'planner')


def test_report_marks_wrong_answer_and_partial_completion(tmp_path, case):
    record = {'case_id': 'test', 'ticker': 'TSLA', 'group': 'formula', 'mode': 'agents', 'grade': 'WRONG_ANSWER',
              'incorrect_result': True, 'actual_status': 'SUCCESS', 'seconds': 1, 'reasons': ['Wrong evidence']}
    write_reports(tmp_path, [case, case], [record], 'RUNNING')
    aggregate = json.loads((tmp_path / 'aggregate.json').read_text())
    assert aggregate['incorrect_case_ids'] == ['test']
    assert aggregate['planned'] == 2 and aggregate['completed'] == 1
    assert '**WRONG_ANSWER' in (tmp_path / 'report.md').read_text()
    assert 'Wrong evidence' in (tmp_path / 'report.md').read_text()

import copy
import json
from pathlib import Path

import pytest

from evaluation.cases import Case, score
from tests.test_pilot_evaluation import correct_result


@pytest.fixture
def example():
    ref = copy.deepcopy(json.loads(Path('evaluation/cases/pilot_references.json').read_text())['references']['TSLA'])
    case = Case(case_id='equivalence', ticker='TSLA', group='formula', mode='deterministic',
        formula='current_ratio_change', source='local.html', source_hash='hash', reference=ref,
        development_company=True, scoring_version='2')
    result = correct_result(case)
    ref['identity_source_sha256'] = 'hash'
    ref['fact_identities'] = {}
    for component, row in result['final_response']['evidence'].items():
        for fact in row['facts']:
            fact.update(concept='us-gaap:' + ('AssetsCurrent' if component == 'current_assets' else 'LiabilitiesCurrent'),
                context_id='ctx-' + fact['period'], entity_identifier='1318605', entity_scheme='http://www.sec.gov/CIK',
                scale=6, start=None, instant=True)
        ref['fact_identities'][component] = {f['period']: copy.deepcopy(f) for f in row['facts']}
    case.reference = ref
    return case, result


def test_equivalent_fact_with_different_label_has_a_separate_label_flag(example):
    case, result = example
    result['final_response']['evidence']['current_assets']['label'] = 'Assets, current'
    grade = score(case, result)
    assert grade['grade'] == 'CORRECT_ANSWER'
    assert grade['strict_label_grade'] == 'WRONG_ANSWER'
    assert grade['label_reviews']['current_assets'] == {'label_match': False, 'fact_equivalent': True, 'selected_label': 'Assets, current'}


@pytest.mark.parametrize('change', ['concept','context_id','entity_identifier','entity_scheme','period','value','currency','scale','start','end','instant','dimensions','source','reference_source'])
def test_numeric_coincidence_and_bad_source_identity_are_not_equivalence(example, change):
    case, result = example
    row = result['final_response']['evidence']['current_assets']
    row['label'] = 'Assets, current'
    fact = row['facts'][0]
    if change == 'source': row['filing_hash'] = 'foreign'
    elif change == 'reference_source': case.reference['identity_source_sha256'] = 'foreign'
    elif change == 'value': fact['value'] += 1
    elif change == 'scale': fact['scale'] = 3
    elif change == 'instant': fact['instant'] = False
    elif change == 'dimensions': fact['dimensions'] = {'SegmentAxis': 'Retail'}
    else: fact[change] = 'different'
    assert score(case, result)['grade'] == 'WRONG_ANSWER'


def test_matching_label_does_not_hide_a_different_fact_identity(example):
    case, result = example
    result['final_response']['evidence']['current_assets']['facts'][0]['concept'] = 'us-gaap:AssetsNoncurrent'
    assert score(case, result)['grade'] == 'WRONG_ANSWER'


def test_v1_grading_is_retained_and_evaluation_identities_never_enter_requests(example):
    case, result = example
    result['final_response']['evidence']['current_assets']['label'] = 'Assets, current'
    assert score(case.model_copy(update={'scoring_version':'1'}), result)['grade'] == 'WRONG_ANSWER'
    request = json.dumps(case.request())
    assert 'fact_identities' not in request and 'identity_source_sha256' not in request and 'scoring_version' not in request


def test_walmart_net_sales_remains_a_different_financial_fact():
    ref = json.loads(Path('evaluation/cases/scope_references_v2.json').read_text())['references']['WMT']
    case = Case(case_id='wmt', ticker='WMT', group='formula', mode='deterministic', formula='revenue_growth',
        source='wmt.html', source_hash=ref['identity_source_sha256'], reference=ref, development_company=False, scoring_version='2')
    from evaluation.cases import equivalent_facts
    row = {'filing_hash': case.source_hash, 'label':'Net sales', 'facts':list(copy.deepcopy(ref['fact_identities']['revenue']).values())}
    for i, fact in enumerate(row['facts']):
        fact['concept'] = 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
        fact['value'] = [674538e6,642637e6][i]
    assert not equivalent_facts(case, 'revenue', row)


@pytest.mark.parametrize('change', [None, 'value', 'entity', 'currency'])
def test_reference_identity_builder_checks_raw_reviewed_amounts_and_scope(change):
    from evaluation.review_fact_identities import reviewed_identities
    contexts = ''.join(f'<xbrli:context id="c{year}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{year}-01-01</xbrli:startDate><xbrli:endDate>{year}-12-31</xbrli:endDate></xbrli:period></xbrli:context>' for year in [2025,2024])
    facts = ''.join(f'<td><ix:nonFraction name="us-gaap:Revenues" contextRef="c{year}" unitRef="usd" scale="6">{value}</ix:nonFraction></td>' for year,value in [(2025,50),(2024,40)])
    raw = contexts + '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit><table><tr><td>Total revenue</td>' + facts + '</tr></table>'
    if change == 'value': raw = raw.replace('>50<','>51<')
    elif change == 'entity': raw = raw.replace('>123<','>999<')
    elif change == 'currency': raw = raw.replace('iso4217:USD','iso4217:CAD')
    ref = {'primary_rows':{'revenue':[0,0]},'revenue':[50,40],'ends':['2025-12-31','2024-12-31']}
    if change:
        with pytest.raises(ValueError):
            reviewed_identities(raw.encode(), {'ticker':'TEST','cik':123}, ref)
    else:
        result = reviewed_identities(raw.encode(), {'ticker':'TEST','cik':123}, ref)
        assert result['revenue']['FY2025']['value'] == 50e6
        assert result['revenue']['FY2024']['entity_identifier'] == '123'

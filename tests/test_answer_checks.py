from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from lok_sabha_rag.core.answer_checks import audit_answer, generate_checked
from lok_sabha_rag.core.ai_provider import GenerationError


def source(text='Kavach commissioned on 1452 route km. Sections: 667, 96, 336.', date='2026-03-11', idx=1):
    return NS(group_index=idx, date=date, chunks=[NS(text=text)])


def codes(answer, groups=None):
    return {x['code'] for x in audit_answer(answer, groups or [source()])['issues']}


def test_numeric_formatting_and_grouped_citations():
    assert not codes('Kavach: **1,452** route km [Q1].')
    assert not codes('Children: 1,37,861 [Q1].', [source('137861 children')])


def test_detects_known_wrong_subtotal_without_equation_or_citation():
    assert 'number_not_in_passages' in codes('**Delhi-Mumbai total: 999 route km**')


def test_checks_against_cited_records_not_any_other_record():
    groups = [source('1452 route km'), source('999 route km', idx=2)]
    assert 'number_not_in_passages' in codes('999 route km [Q1].', groups)
    assert not codes('999 route km [Q2].', groups)


@pytest.mark.parametrize('equation', ['667 + 96 + 336 = 999', '667 + 96 = 700'])
def test_arithmetic_is_computed_not_accepted_because_number_exists(equation):
    assert 'arithmetic_mismatch' in codes(equation + ' [Q1]', [source('667 96 336 999 700')])


def test_supported_derived_sum_and_decimal_subtraction():
    assert not codes('Calculated subtotal: 667 + 96 + 336 = 1,099 route km [Q1].')
    assert not codes('Calculated difference: 100.75 - 60.45 = 40.30 [Q1].', [source('100.75 and 60.45')])


def test_correct_equation_with_unsupported_operand_still_flagged():
    assert 'number_not_in_passages' in codes('1452 + 100 = 1552 [Q1].')


def test_record_date_checked_separately_from_observation_date():
    groups = [source('As of 28 February 2026: 1452 route km.')]
    assert 'answer_date_mismatch' in codes('The answer on 28 February 2026 reported 1452 route km [Q1].', groups)
    assert not codes('As of 28 February 2026: 1452 route km [Q1].', groups)
    assert not codes('The answer on 11 March 2026 reported 1452 route km [Q1].', groups)


def test_narrow_spending_confusion_and_negation():
    groups = [source('The approved outlay is 1000.75 crore.')]
    assert 'spending_status_review' in codes('Actually spent 1,000.75 crore [Q1].', groups)
    assert not codes('The approved outlay is 1000.75 crore, not money spent [Q1].', groups)
    assert not codes('Spent 1000.75 crore [Q1].', [source('Actual expenditure: 1000.75 crore.')])


def test_small_counts_and_semantic_meaning_are_explicitly_not_certified():
    report = audit_answer('Incorrectly described 5 facilities [Q1].', [source('5 sanctioned facilities')])
    assert report['status'] == 'limited_checks_clear'
    assert 'does not establish' in report['limitations']


def test_invalid_citation_detected():
    assert 'invalid_citation' in codes('1452 route km [Q99].')


def test_clean_answer_uses_one_generation_call():
    gen = Mock()
    gen.generate.return_value = '1452 route km [Q1].'
    answer, report = generate_checked(gen, 'question', 'context', [source()])
    assert answer == gen.generate.return_value
    assert not report['repair_attempted']
    assert gen.generate.call_count == 1


def test_revision_improves_known_wrong_total():
    gen = Mock()
    gen.generate.side_effect = ['Total: 999 route km [Q1].', 'Calculated total: 667 + 96 + 336 = 1099 route km [Q1].']
    answer, report = generate_checked(gen, 'question', 'context', [source()])
    assert '1099' in answer and report['repair_applied']
    assert report['status'] == 'limited_checks_clear'
    assert gen.generate.call_count == 2


def test_failed_or_non_improving_repair_does_not_loop_or_hide_warning():
    gen = Mock()
    gen.generate.side_effect = ['999 route km [Q1].', '888 route km [Q1].']
    answer, report = generate_checked(gen, 'question', 'context', [source()])
    assert answer == '999 route km [Q1].' and report['status'] == 'review_needed'
    assert gen.generate.call_count == 2
    gen.generate.side_effect = ['999 route km [Q1].', GenerationError('unavailable')]
    answer, report = generate_checked(gen, 'question', 'context', [source()])
    assert report['repair_failed'] and report['status'] == 'review_needed'


def test_serialized_api_evidence_supported():
    report = audit_answer('1452 route km [Q1].', [{'group_index': 1, 'date': '2026-03-11', 'chunks': [{'text': '1452 route km'}]}])
    assert not report['issues']

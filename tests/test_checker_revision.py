from types import SimpleNamespace as NS
import pytest
from lok_sabha_rag.core.answer_checks import audit_answer


def check(text, source='Route lengths 420 km and 175 km.', date='2024-05-09'):
    return audit_answer(text,[NS(group_index=1,date=date,chunks=[NS(text=source)])])['issues']


@pytest.mark.parametrize('text',[
    '420 km + 175 km = 595 km [Q1].',
    r'($420\text{ kms} + 175\text{ kms}$) yields a total length of 595 kms [Q1].',
    '420 + 175 equals 595 km [Q1].',
    '420 - 175 = 245 km [Q1].',
])
def test_valid_formatted_explicit_math(text):
    assert not check(text)


@pytest.mark.parametrize('text',[
    '420 km + 175 km = 596 km [Q1].',
    '420 km + 200 km = 620 km [Q1].',
    '420 lakh + 175 crore = 595 crore [Q1].',
    '595 km total [Q1].',
])
def test_incorrect_unsupported_or_mixed_scale_math_stays_flagged(text):
    assert check(text)


@pytest.mark.parametrize('text',[
    'The supplied evidence does not contain a Rajya Sabha reply from 7 July 2012.',
    'The selected evidence lacks the requested reply of 7 July 2012.',
    'The requested reply of 7 July 2012 is entirely missing from the provided evidence.',
])
def test_explicit_scoped_missing_date_not_positive_claim(text):
    assert not check(text)


def test_missing_date_exemption_does_not_hide_other_numbers_or_invalid_cites():
    issues=check('The supplied evidence does not contain a reply from 7 July 2012; the total is 999 [Q99].')
    assert {'invalid_citation','number_not_in_passages'} <= {i['code'] for i in issues}


def test_missing_date_then_positive_wrong_date_still_checked():
    text='The supplied evidence lacks a reply of 7 July 2012; however the reply on 8 July 2012 reports 420 km [Q1].'
    assert 'answer_date_mismatch' in {i['code'] for i in check(text)}


def test_broad_absence_and_positive_historical_claim_not_exempted():
    assert check('No parliamentary reply on 7 July 2012 exists anywhere.')
    assert 'answer_date_mismatch' in {i['code'] for i in check('The reply on 7 July 2012 reports 420 km [Q1].')}


def test_same_line_invented_count_after_missing_date_still_flagged():
    assert 'number_not_in_passages' in {i['code'] for i in check('The supplied evidence lacks a reply of 7 July 2012 and reports 999 km.')}

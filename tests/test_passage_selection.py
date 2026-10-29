from types import SimpleNamespace as NS
from lok_sabha_rag.core.passage_selection import complementary_order, numeric_facets


def test_selects_plain_table_and_separate_money_over_repetitive_intro():
    intro=NS(text='ANSWER\nThe institute describes labs and classrooms. Details follow.')
    table=NS(text='Digital Resource Sanctioned Number\nLabs 42\nSmart Classrooms 67')
    money=NS(text='An allocation of 18.75 lakh was reported for digital initiatives.')
    ranked=complementary_order([intro,money,table], 'How many labs and classrooms were sanctioned, and what allocation was reported?')
    assert ranked[:2]==[table,money]
    assert len(ranked)==3


def test_coverage_prefers_new_facet_to_duplicate_counts():
    a=NS(text='Labs 42; classrooms 67')
    duplicate=NS(text='Labs 42; classrooms 67, repeated')
    money=NS(text='Budget allocation 18.75 lakh')
    assert complementary_order([a,duplicate,money],'Labs, classrooms and budget allocation')[:2]==[a,money]


def test_preserves_single_facet_and_non_numeric_rankings():
    rows=[NS(text='Overview'),NS(text='Vacancies 20')]
    assert complementary_order(rows,'Explain recruitment') is rows
    assert complementary_order(rows,'How many vacancies?') is rows


def test_no_number_elsewhere_is_invented_or_copied():
    text='42 '+('unrelated ' * 30)+'labs and classrooms have no numeric breakdown.'
    assert not numeric_facets(text,{'labs','classrooms'})


def test_question_numbers_before_answer_do_not_supply_coverage():
    text='QUESTION 67 How many labs and classrooms?\nANSWER\nThe details are unavailable.'
    assert not numeric_facets(text,{'labs','classrooms'})


def test_money_before_allocated_and_after_expenditure_are_recognised():
    assert numeric_facets('Rs 18.75 lakh allocated; expenditure 9.25 lakh', {'allocation','expenditure'})=={'allocation','expenditure'}


def test_stable_order_for_equal_coverage_and_zero_coverage():
    a,b=NS(text='Labs 42'),NS(text='Labs 43')
    assert complementary_order([a,b],'Labs and classrooms')==[a,b]


def test_does_not_join_sources_change_units_or_expand_passage_budget():
    a=NS(text='Labs 42; classrooms 67')
    b=NS(text='Allocation 18.75 lakh')
    original=[a.text,b.text]
    selected=complementary_order([a,b],'Labs classrooms allocation')[:1]
    assert len(selected)==1
    assert [a.text,b.text]==original

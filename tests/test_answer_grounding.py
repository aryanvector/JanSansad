from types import SimpleNamespace as NS
from unittest.mock import patch

from lok_sabha_rag.core.retriever import Retriever, _extract_evidence, select_answer_chunks
from lok_sabha_rag.core.synthesizer import Synthesizer, get_system_prompt


def chunk(index, score):
    return NS(chunk_id=f"c{index}", chunk_index=index, score=score, text=f"Passage {index}")


def test_one_chunk_budget_preserves_later_answer_passage():
    answer = chunk(7, .95)
    assert select_answer_chunks([answer], [chunk(0, 0)], 1) == [answer]


def test_two_chunk_budget_adds_introduction_without_losing_answer():
    answer, intro = chunk(7, .95), chunk(0, 0)
    assert select_answer_chunks([answer], [intro, chunk(1, 0)], 2) == [intro, answer]


def test_chunks_are_deduplicated_and_ranked_before_document_order():
    opening, later, best = chunk(0, .2), chunk(3, .4), chunk(7, .9)
    result = select_answer_chunks([opening, later, best], [chunk(0, 0), chunk(1, 0)], 3)
    assert [c.chunk_index for c in result] == [0, 3, 7]
    assert len({c.chunk_id for c in result}) == 3


def test_empty_leading_fetch_retains_matches_within_budget():
    assert [c.chunk_index for c in select_answer_chunks([chunk(5, .4), chunk(2, .8)], [], 1)] == [2]


def test_grouping_retains_matching_answer_only_when_enabled():
    def evidence(index, score):
        return _extract_evidence(NS(id=f'p{index}', score=score, payload={
            'question_id': '18_7_1_UNSTARRED', 'chunk_id': f'c{index}',
            'chunk_index': index, 'text': f'Passage {index}', 'lok_no': 18,
            'session_no': 7, 'ques_no': 1, 'type': 'UNSTARRED'}), score=score)
    r = Retriever.__new__(Retriever)
    match, opening = evidence(7, .9), evidence(0, 0)
    with patch.object(r, '_count_total_chunks', return_value=8), patch.object(r, '_fetch_leading_chunks', return_value=[opening]):
        answer_groups = r.group_evidence([match], top_n=10, chunks_per_question=1, prefer_matches=True)
        document_groups = r.group_evidence([match], top_n=10, chunks_per_question=1)
    assert answer_groups[0].chunks == [match]
    assert document_groups[0].chunks == [opening]
    assert answer_groups[0].total_chunks_available == 8


def test_no_statistics_examples_are_sent_for_normal_topic_question():
    with patch('lok_sabha_rag.core.ai_provider.generate', return_value='Answer [Q1].') as generate:
        Synthesizer().generate('What is Kavach?', '[Q1] Official railway evidence')
    system = generate.call_args.args[0]
    assert 'No metadata statistics block is supplied' in system
    assert '## Using Statistics' not in system
    assert '15,280' not in system


def test_only_actual_metadata_prefix_enables_statistics_instructions():
    with patch('lok_sabha_rag.core.ai_provider.generate', return_value='Answer [Q1].') as generate:
        Synthesizer().generate('Question', '=== MINISTRY STATISTICS (from parliamentary metadata) ===\nTotal questions received: 5\n=== END MINISTRY STATISTICS ===\n[Q1] Evidence')
    assert '## Using Statistics' in generate.call_args.args[0]
    assert 'Copy totals and names exactly' in generate.call_args.args[0]
    assert '17th and 18th' not in generate.call_args.args[0]


def test_prompt_keeps_reporting_period_and_attribution_boundaries():
    prompt = get_system_prompt()
    assert 'partial period' in prompt
    assert 'inventor/developer' in prompt
    assert 'dataset-wide absence' in prompt

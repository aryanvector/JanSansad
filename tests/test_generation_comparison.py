import io
import json
from unittest.mock import Mock, MagicMock
from urllib.error import HTTPError

import pytest

from lok_sabha_rag.evaluation.generate_comparison import ProviderTrace, DraftReplay
from lok_sabha_rag.core.ai_provider import GenerationError


def test_observer_preserves_response_and_records_only_safe_metadata(tmp_path):
    trace = ProviderTrace(tmp_path/'events.jsonl'); trace.tag = 'draft'
    raw = json.dumps({'usageMetadata': {'totalTokenCount': 12}, 'modelVersion': 'test', 'candidates': []}).encode()
    response = MagicMock(); response.read.return_value = raw
    opener = Mock(); opener.open.return_value = response
    observed = trace.observe_builder(lambda: opener)()
    with observed.open('request-secret') as result:
        assert result.read() == raw
    assert trace.calls == 1
    assert trace.events[-1]['usage']['totalTokenCount'] == 12
    assert 'request-secret' not in trace.path.read_text()


def test_quota_stops_without_recording_error_body(tmp_path):
    trace = ProviderTrace(tmp_path/'events.jsonl'); trace.tag = 'draft'
    opener = Mock(); opener.open.side_effect = HTTPError('url',429,'secret message',{},io.BytesIO(b'secret body'))
    observed = trace.observe_builder(lambda: opener)()
    with pytest.raises(HTTPError): observed.open('request')
    assert not trace.allowed('next')[0]
    assert 'secret' not in trace.path.read_text()


def test_cap_blocks_transport_and_draft_replay_avoids_initial_call(tmp_path):
    trace = ProviderTrace(tmp_path/'events.jsonl',max_calls=0)
    opener = Mock(); observed = trace.observe_builder(lambda: opener)()
    with pytest.raises(GenerationError): observed.open('request')
    opener.open.assert_not_called()
    repair = Mock(); repair.generate.return_value = 'revised'
    replay = DraftReplay('original',repair)
    assert replay.generate('q','context') == 'original'
    repair.generate.assert_not_called()
    assert replay.generate('q','context') == 'revised'
    repair.generate.assert_called_once()

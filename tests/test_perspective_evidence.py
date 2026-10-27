"""Prompt contract and structural acceptance for three distinct evidence situations.

Responses are controlled fixtures, not evidence of live-model semantic accuracy.
"""
import copy
import json

import httpx
import pytest

from app import main
from app.facilitation import NOTES_SCHEMA
from app.themes import SCHEMA, ThemeError, suggest_themes


CASES = [
    pytest.param(
        [{'id': 1, 'question': 'I favor landscaping as the first improvement project. Could it be done first?'},
         {'id': 2, 'question': 'I favor accessibility and safety as the first improvement projects. Could they come first?'}],
        'Two submissions express different project priorities: landscaping in one and accessibility and safety in the other.',
        'The cited submissions address which improvement projects to start first.',
        ['What criteria could guide the order of improvement projects?',
         'How could the expressed priorities inform a practical sequence of projects?'],
        'A. Explicitly expressed differing perspectives', id='explicit_positions'),
    pytest.param(
        [{'id': 1, 'question': 'Should our first improvement projects focus on visible changes like landscaping, or less visible needs like accessibility and safety?'}],
        'A question raises a potential tradeoff between visible landscaping and less visible accessibility and safety work. '
        'It does not establish that participants hold opposing positions.',
        'A question raises how to prioritize visible and less visible improvements.',
        ['What criteria could help compare visible improvements with accessibility and safety needs?',
         'How might an improvement plan address these needs together or in sequence?'],
        'B. Potential tensions or tradeoffs', id='single_hypothetical_tradeoff'),
    pytest.param(
        [{'id': 1, 'question': 'When will the accessibility assessment be available?'}],
        'The questions do not establish differing perspectives or a meaningful tradeoff. '
        'There is insufficient evidence of disagreement.',
        'A question asks about the timing of the accessibility assessment.',
        ['What information about the assessment timeline would be useful?',
         'How could assessment updates be shared clearly?'],
        'C. No meaningful disagreement or tradeoff supported', id='no_disagreement'),
    pytest.param(
        [{'id': 1, 'question': 'Could the path entrances be made more accessible?'},
         {'id': 2, 'question': 'Could the meeting space include accessible seating?'}],
        'The questions do not establish differing perspectives. There is insufficient evidence of disagreement.',
        'Several questions address accessibility of entrances and meeting spaces. '
        'Recurring topics do not establish agreement or community consensus.',
        ['What accessibility needs do these questions invite us to examine?',
         'What information would help assess possible changes to entrances and seating?'],
        "prefer 'Several questions address...'", id='recurrence_without_consensus'),
]


@pytest.mark.parametrize('questions,perspectives,concerns,prompts,guard', CASES)
def test_evidence_cases_preserve_response_contract(monkeypatch, questions, perspectives, concerns, prompts, guard):
    expected = {
        'title': 'Discussion priorities',
        'description': 'The cited questions identify issues for further exploration.',
        'question_ids': [q['id'] for q in questions],
        'facilitation_notes': {
            'shared_concerns': concerns, 'different_perspectives': perspectives,
            'discussion_questions': prompts,
        },
    }
    original_expected = copy.deepcopy(expected)
    schema_before = copy.deepcopy(SCHEMA)
    def response(self, url, **kwargs):
        payload = kwargs['json']
        system = payload['messages'][0]['content']
        assert guard in system
        assert json.loads(payload['messages'][1]['content'])['untrusted_questions'] == questions
        assert payload['format'] == schema_before
        assert payload['format']['properties']['themes']['items']['properties']['facilitation_notes'] == NOTES_SCHEMA
        assert payload['options'] == {'temperature': 0.2, 'num_predict': 4800}
        assert payload['stream'] is False and payload['think'] is False
        assert self.timeout.read == 90 and self.timeout.connect == 5
        return httpx.Response(200, json={'done': True, 'done_reason': 'stop',
            'message': {'content': json.dumps({'themes': [expected]})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', response)
    result = suggest_themes(questions, main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)
    assert result == [original_expected]
    assert len(result[0]['facilitation_notes']['discussion_questions']) == 2
    assert SCHEMA == schema_before


def test_prompt_distinguishes_question_alternatives_from_attributed_positions(monkeypatch):
    def inspect(self, url, **kwargs):
        system = kwargs['json']['messages'][0]['content']
        for requirement in (
            'cited submissions actually express distinct positions',
            'citing only supporting submissions in question_ids',
            'Include support for each position',
            'do not infer groups, how many people',
            'a question listing competing options or asking what to prioritize is not evidence',
            'A question raises a potential tradeoff between...',
            'Participants may wish to explore...',
            "Never turn a single question's alternatives into 'Some prioritize X while others emphasize Y'",
            'The questions do not establish differing perspectives',
            "never 'Residents agree that...'",
            'question counts do not establish how many people hold a view',
            'without presupposing opposing groups',
            'Conditional wording is not permission to invent a tradeoff',
            "both alternatives must actually be raised in that theme's cited submissions",
            'Calibration examples below illustrate wording only',
            'NOT source submissions and must never be cited',
            "one cited question means 'A question' or 'One submission'",
            'Check that every asserted position and every side of a tradeoff is present',
            'Use count-neutral shared_concerns wording',
            'never carry over a plural count from the gathering',
            'Suggested prompts must not assume urgency',
            'grounded ONLY in that theme’s own cited questions', 'untrusted data',
        ):
            assert requirement in system
        return httpx.Response(200, json={'done': True, 'message': {'content': '{"themes": []}'}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', inspect)
    with pytest.raises(ThemeError, match='incomplete or invalid'):
        suggest_themes([{'id': 1, 'question': 'Should landscaping or safety come first?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)


@pytest.mark.parametrize('failure', ['missing_notes', 'invalid_source', 'truncation'])
def test_evidence_instructions_do_not_relax_validation(monkeypatch, failure):
    valid = {
        'title': 'Priorities', 'description': 'A question raises possible improvement priorities.', 'question_ids': [1],
        'facilitation_notes': {'shared_concerns': 'A question addresses project priorities.',
            'different_perspectives': 'The question raises a possible tradeoff without establishing opposing views.',
            'discussion_questions': ['What criteria could guide priorities?', 'How could the options be explored?']},
    }
    if failure == 'missing_notes':
        del valid['facilitation_notes']
    elif failure == 'invalid_source':
        valid['question_ids'] = [99]
    def response(self, url, **kwargs):
        return httpx.Response(200, json={'done': True, 'done_reason': 'length' if failure == 'truncation' else 'stop',
            'message': {'content': json.dumps({'themes': [valid]})}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', response)
    with pytest.raises(ThemeError, match='incomplete or invalid'):
        suggest_themes([{'id': 1, 'question': 'Should landscaping or safety come first?'}], main.OLLAMA_BASE_URL, main.OLLAMA_MODEL)

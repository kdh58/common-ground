"""Bounded generated host-private notes. Structural checks do not prove grounding."""
import re

NOTES_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['shared_concerns', 'different_perspectives', 'discussion_questions'],
    'properties': {
        'shared_concerns': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
        'different_perspectives': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
        'discussion_questions': {'type': 'array', 'minItems': 2, 'maxItems': 3,
                                 'items': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
    },
}


def validate_generated_notes(notes):
    if not isinstance(notes, dict) or set(notes) != set(NOTES_SCHEMA['required']):
        raise ValueError('Missing or malformed facilitation notes')
    cleaned = {}
    for field in ('shared_concerns', 'different_perspectives'):
        value = notes[field]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000:
            raise ValueError('Invalid facilitation text')
        if any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in value):
            raise ValueError('Invalid facilitation text')
        sentences = [part for part in re.split(r'[.!?]+(?:\s+|$)', value.strip()) if part.strip()]
        if not 1 <= len(sentences) <= 3 or not re.search(r'\w', value):
            raise ValueError('Invalid facilitation sentences')
        cleaned[field] = value.strip()
    questions = notes['discussion_questions']
    if not isinstance(questions, list) or not 2 <= len(questions) <= 3:
        raise ValueError('Invalid discussion questions')
    seen = set()
    for question in questions:
        if (not isinstance(question, str) or not 1 <= len(question.strip()) <= 300 or
                any(ord(c) < 32 or ord(c) == 127 for c in question)):
            raise ValueError('Invalid discussion question')
        normalized = re.sub(r'\W+', ' ', question.casefold()).strip()
        if not normalized or normalized in seen:
            raise ValueError('Empty or duplicate discussion question')
        seen.add(normalized)
    cleaned['discussion_questions'] = [q.strip() for q in questions]
    return cleaned

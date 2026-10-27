import re
from urllib.parse import urlsplit


def post(client, url, **kwargs):
    page = client.get('/host')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    data = kwargs.pop('data', {})
    path = urlsplit(url).path
    if re.fullmatch(r'/host/gatherings/\d+/themes', path) and 'request_key' not in data:
        gathering_page = client.get(path.rsplit('/themes', 1)[0] + '?tab=themes')
        form = re.search(r'<form action="' + re.escape(path) + r'(?:\?tab=themes)?".*?</form>', gathering_page.text, re.S)
        match = re.search(r'name="request_key" value="([^"]+)"', form[0] if form else '')
        data = {**data, 'request_key': match[1] if match else 'missing'}
    return client.post(url, data={**data, 'csrf_token': token}, **kwargs)


def generated_notes():
    """Complete synthetic structured response for tests unrelated to note validation."""
    return {
        'shared_concerns': 'The cited questions raise issues to explore together.',
        'different_perspectives': 'There is insufficient evidence in the cited questions to infer disagreement.',
        'discussion_questions': ['What issues raised here should be explored further?',
                                 'What tradeoffs do the cited questions invite us to consider?'],
    }

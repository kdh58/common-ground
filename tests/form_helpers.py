import re


def post(client, url, **kwargs):
    page = client.get('/host')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    data = kwargs.pop('data', {})
    if re.fullmatch(r'/host/gatherings/\d+/themes', url) and 'request_key' not in data:
        gathering_page = client.get(url.rsplit('/themes', 1)[0])
        form = re.search(r'<form action="' + re.escape(url) + r'".*?</form>', gathering_page.text, re.S)
        match = re.search(r'name="request_key" value="([^"]+)"', form[0] if form else '')
        data = {**data, 'request_key': match[1] if match else 'missing'}
    return client.post(url, data={**data, 'csrf_token': token}, **kwargs)

import re


def post(client, url, **kwargs):
    page = client.get('/host')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    data = kwargs.pop('data', {})
    if re.fullmatch(r'/host/gatherings/\d+/themes', url) and 'request_key' not in data:
        gathering_page = client.get(url.rsplit('/themes', 1)[0])
        match = re.search(r'name="request_key" value="([^"]+)"', gathering_page.text)
        data = {**data, 'request_key': match[1] if match else 'missing'}
    return client.post(url, data={**data, 'csrf_token': token}, **kwargs)

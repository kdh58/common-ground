import re


def post(client, url, **kwargs):
    page = client.get('/host')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    data = kwargs.pop('data', {})
    return client.post(url, data={**data, 'csrf_token': token}, **kwargs)

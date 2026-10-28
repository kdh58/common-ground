"""Read-only presentation helpers for gathering lists."""
import re
from datetime import datetime, timezone
from app.scheduling import schedule_bounds


def gathering_state(g, now=None):
    if g.get('cancelled'):
        return 'cancelled'
    start, end = schedule_bounds(g)
    if start is None:
        return 'unconfirmed'
    return 'past' if end <= (now or datetime.now(timezone.utc)) else 'upcoming'


def ordered_gatherings(gatherings, now=None):
    now = now or datetime.now(timezone.utc)
    groups = {'upcoming': 0, 'past': 1, 'unconfirmed': 2, 'cancelled': 3}

    def key(g):
        state = gathering_state(g, now)
        start, _ = schedule_bounds(g)
        instant = start.timestamp() if start else 0
        return (groups[state], -instant if state == 'past' else instant, g['id'])

    return sorted(gatherings, key=key)


def listing_sections(gatherings, request, host=False, now=None):
    """Paginate independently, retaining other section pages and fragment targets."""
    from urllib.parse import urlencode
    now = now or datetime.now(timezone.utc)
    states = [('upcoming', 'Upcoming gatherings'), ('unconfirmed', 'Schedule to be confirmed')]
    states += [('past', 'Past gatherings')]
    if host:
        states += [('cancelled', 'Canceled gatherings')]
    rows = ordered_gatherings(gatherings, now)
    sections = []
    for state, title in states:
        entries = [dict(g, list_state=state) for g in rows if gathering_state(g, now) == state]
        pages = max(1, (len(entries) + 4) // 5)
        parameter = state + '_page'
        try:
            page = max(1, min(pages, int(request.query_params.get(parameter, '1'))))
        except (ValueError, TypeError):
            page = 1
        def url(number):
            params = {key: request.query_params[key] for key in
                      ('upcoming_page', 'unconfirmed_page', 'past_page', 'cancelled_page')
                      if key in request.query_params}
            params[parameter] = number
            params['open_section'] = state
            return ('/host' if host else '/') + '?' + urlencode(params) + '#' + state + '-gatherings-heading'
        sections.append(dict(id=state + '-gatherings', title=title, state=state,
                             entries=entries[(page - 1) * 5:page * 5], page=page, pages=pages, count=len(entries),
                             expanded=(state == 'upcoming' or request.query_params.get('open_section') == state
                                       or parameter in request.query_params),
                             previous=url(page - 1) if page > 1 else None,
                             next=url(page + 1) if page < pages else None))
    return sections


def description_preview(value, limit=190):
    """Plain text only, still autoescaped by Jinja; common Markdown is simplified."""
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', value)
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'(?m)^\s{0,3}(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+\.\s+)', '', text)
    text = re.sub(r'[*`~_]', '', text)
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    prefix = text[:limit - 1]
    prefix = prefix.rsplit(' ', 1)[0] if ' ' in prefix else ''
    return prefix.rstrip() + '…'

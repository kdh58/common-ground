"""Allowlisted, best-effort activity events. Never serialize requests or exceptions."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import time
import uuid

context = ContextVar('activity', default=None)
logger = logging.getLogger('common_ground.activity')
logger.propagate = False
logger.setLevel(logging.INFO)
FIELDS = {'role', 'gathering_id', 'analysis_run_id', 'correlation_id', 'duration_ms',
          'http_status', 'model', 'operation', 'prompt_eval_count', 'eval_count', 'reason'}


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)


def configure():
    """One worker owns rotation (the deployment runs a single Uvicorn worker)."""
    if logger.handlers:
        return
    try:
        path = Path(os.environ.get('ACTIVITY_LOG_PATH', '/tmp/common-ground-logs/activity.jsonl'))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        handler = PrivateRotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8', delay=True)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    except Exception:
        # Storage outages must never break application actions.
        pass


def emit(event, status, **fields):
    try:
        record = dict(context.get() or {})
        record.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
        record.update(timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                      event=event, status=status)
        logger.info(json.dumps(record, separators=(',', ':'), ensure_ascii=True))
    except Exception:
        pass


def action_for(method, path):
    if method == 'POST':
        fixed = {'/host/login': 'HOST_LOGIN', '/host/logout': 'HOST_LOGOUT',
                 '/host/gatherings': 'GATHERING_CREATE'}
        if path in fixed:
            return fixed[path]
        match = re.fullmatch(r'/gatherings/\d+/(rsvp|questions)', path)
        if match:
            return {'rsvp': 'RSVP_SUBMIT', 'questions': 'QUESTION_SUBMIT'}[match[1]]
        if re.fullmatch(r'/host/gatherings/\d+/analyses/\d+/print-click', path):
            return 'ANALYSIS_PRINT_REQUEST'
        match = re.fullmatch(r'/host/gatherings/\d+/(.+)', path)
        if match:
            suffix = match[1]
            fixed = {'edit': 'GATHERING_EDIT', 'status': 'GATHERING_STATUS', 'agenda': 'AGENDA_SAVE',
                     'resources': 'RESOURCE_ADD', 'themes': 'AI_ANALYSIS_REQUEST', 'themes/manual': 'THEME_CREATE'}
            if suffix in fixed:
                return fixed[suffix]
            match = re.fullmatch(r'(themes|analyses|resources)/\d+/(edit|remove|notes|approve|publish|unpublish|archive|restore|delete|up|down|inactive|reactivate)', suffix)
            if match:
                return ('RESOURCE_' if match[1] == 'resources' else 'ANALYSIS_' if match[1] == 'analyses' or match[2] in ('approve', 'publish') else 'THEME_') + match[2].upper()
    if method == 'GET':
        if re.fullmatch(r'/host/gatherings/\d+/export/(rsvps|questions)\.csv', path):
            return 'CSV_EXPORT'
        match = re.fullmatch(r'/host/gatherings/\d+/analyses/\d+/(view|export)\.html', path)
        if match:
            return 'ANALYSIS_VIEW' if match[1] == 'view' else 'ANALYSIS_EXPORT'
    return None


class ActivityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        action = action_for(scope['method'], scope['path'])
        if not action:
            return await self.app(scope, receive, send)
        data = {'correlation_id': uuid.uuid4().hex,
                'role': 'host' if scope.get('session', {}).get('admin') else
                        'participant' if action in ('RSVP_SUBMIT', 'QUESTION_SUBMIT') else 'anonymous'}
        match = re.search(r'/gatherings/(\d+)', scope['path'])
        if match:
            data['gathering_id'] = int(match[1])
        match = re.search(r'/analyses/(\d+)', scope['path'])
        if match:
            data['analysis_run_id'] = int(match[1])
        token = context.set(data)
        scope.setdefault('state', {})['activity'] = data
        start = time.monotonic()
        emit(action, 'started')
        code = 500

        async def sending(message):
            nonlocal code
            if message['type'] == 'http.response.start':
                code = message['status']
                message.setdefault('headers', []).append((b'x-correlation-id', data['correlation_id'].encode()))
            await send(message)
        try:
            await self.app(scope, receive, sending)
        finally:
            state = scope['state']
            event = state.get('activity_event', action)
            failed = code >= 400 or state.get('activity_failed', False)
            if action == 'AI_ANALYSIS_REQUEST':
                event = 'AI_ANALYSIS_FAILED' if failed else 'AI_ANALYSIS_COMPLETE'
            emit(event, 'failed' if failed else 'succeeded', http_status=code,
                 duration_ms=round((time.monotonic() - start) * 1000, 3))
            context.reset(token)


def ollama_request(client, method, url, *, model, **kwargs):
    """A response proves HTTP receipt; a send attempt alone proves nothing."""
    fields = {'model': model, 'operation': 'chat' if method == 'post' else 'inventory',
              'correlation_id': (context.get() or {}).get('correlation_id', uuid.uuid4().hex)}
    start = time.monotonic()
    emit('OLLAMA_REQUEST_SUBMITTED', 'started', **fields)
    response = None
    try:
        response = getattr(client, method)(url, **kwargs)
        fields['http_status'] = response.status_code
        emit('OLLAMA_HTTP_RESPONSE', 'succeeded' if response.is_success else 'failed',
             **fields, duration_ms=round((time.monotonic() - start) * 1000, 3))
        response.raise_for_status()
        body = response.json()
        if method == 'post':
            if not isinstance(body, dict) or body.get('done') is not True or body.get('error'):
                raise ValueError('Incomplete model response')
            for key in ('prompt_eval_count', 'eval_count'):
                if type(body.get(key)) is int and body[key] >= 0:
                    fields[key] = body[key]
        emit('OLLAMA_MODEL_RESPONSE' if method == 'post' else 'OLLAMA_REQUEST_COMPLETE',
             'succeeded', **fields, duration_ms=round((time.monotonic() - start) * 1000, 3))
        return response
    except Exception:
        emit('OLLAMA_REQUEST_FAILED', 'failed', **fields,
             duration_ms=round((time.monotonic() - start) * 1000, 3))
        raise

"""Host-only export data: exact run scope, current saved fields, no RSVP query."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app import theme_workflow as workflow
from app.questions import load_questions
from app.timestamps import FALLBACK_TIMEZONE


def export_timezone(requested):
    try:
        if not isinstance(requested, str) or not requested or len(requested) > 100:
            raise ValueError()
        ZoneInfo(requested)
    except (ValueError, ZoneInfoNotFoundError):
        return FALLBACK_TIMEZONE, True
    return requested, False


def load_analysis_export(db, gathering_id, run_id):
    gathering = db.execute('SELECT id,title,when_text,location FROM gatherings WHERE id=?', (gathering_id,)).fetchone()
    if gathering is None:
        raise HTTPException(404, 'Gathering not found')
    run = db.execute('SELECT id,gathering_id,created_at,question_count,status FROM analysis_runs WHERE id=? AND gathering_id=?',
                     (run_id, gathering_id)).fetchone()
    if run is None:
        raise HTTPException(404, 'Analysis run not found')
    run = dict(run)
    state = db.execute('SELECT state FROM analysis_run_states WHERE run_id=?', (run_id,)).fetchone()
    run['inactive'] = bool(state and state['state'] == 'inactive')
    model = db.execute('SELECT model FROM analysis_run_models WHERE run_id=?', (run_id,)).fetchone()
    run['model'] = model['model'] if model and model['model'].strip() else None
    coverage, unavailable = workflow.run_coverage(db, run)
    themes = workflow.load_themes(db, gathering_id, run_id=run_id)
    numbered = {q['id']: q for q in load_questions(db, gathering_id)}
    for theme in themes:
        theme['sources'] = sorted((numbered[q] for q in theme['question_ids'] if q in numbered),
                                  key=lambda q: q['question_number'])
    return {'gathering': dict(gathering), 'run': run, 'themes': themes,
            'coverage': coverage, 'coverage_unavailable': unavailable}

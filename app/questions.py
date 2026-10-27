"""Gathering-local display numbers; database IDs remain citation identifiers."""

# Rank the complete gathering before filtering citations or limiting recent rows.
# New submissions append in creation order; tied timestamps use the database ID.
NUMBERED_QUESTIONS = """SELECT id, gathering_id, question, created_at,
    ROW_NUMBER() OVER (
        PARTITION BY gathering_id ORDER BY created_at, id
    ) AS question_number
    FROM questions"""


def load_questions(db, gathering_id):
    return [dict(row) for row in db.execute(
        f"SELECT * FROM ({NUMBERED_QUESTIONS}) WHERE gathering_id=? ORDER BY question_number",
        (gathering_id,))]

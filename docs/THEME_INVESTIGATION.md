# Discussion theme response investigation

Historical diagnostic record: the 700-token/45-second configuration discussed below
is superseded. Current generation uses 4,800 tokens and a 90-second I/O timeout, plus
a separate readiness check and inline error feedback. See [the current README](../README.md#optional-ollama-assistance).

Reproduced against the running development container using the three existing
fictional questions for gathering 1. No database writes or persistent configuration
changes were made. No question text, model output, thinking trace, endpoint,
credentials, or HTTP exception text was logged.

| Input | Request change | Seconds | done_reason | eval_count | Answer characters | Thinking characters | Validation |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| First two questions | None | 11.27 | stop | 653 | 342 | 2798 | Passed |
| All three questions | None | 11.55 | length | 700 | 3 | 3399 | Failed |
| All three questions | think: false, comparison only | 3.36 | stop | 77 | 285 | 0 | Passed |

These timings differ from the reported approximately seven seconds, but reproduce
the same failure. Generation speed and model loading affect elapsed time. The
failure is token exhaustion, not the 45-second HTTP read timeout.

## Request and parsing

The app posts to /api/chat with stream=false, a structured-output JSON schema,
temperature=0.2 and num_predict=700. It does not specify think. Qwen3 spends
most of that budget on reasoning in this reproduction. done=true means the
response finished; it does not guarantee that a complete answer was generated.
The parser ignores done_reason and attempts json.loads on message.content.
At the limit, a three-character answer is incomplete JSON and reaches the same
generic error handler used for all validation failures.

The schema requires 1–5 themes, each with a 1–120 character title and a nonempty
array of integer question IDs, with no additional properties. It cannot ensure
that the IDs actually belong to the supplied questions: that is checked locally.
Local validation also rejects whitespace-only titles and boolean IDs (Python
otherwise treats booleans as integers). There is no two-question limit.
Structured output constrains answer shape, but cannot guarantee completion
within the output budget. The existing schema is not the cause of this reproduction.

## Original recommendation and follow-up

For the configured Qwen3 model, add top-level think=false to the request. The
comparison retained the same schema, temperature, 700-token limit and strict
validation, and completed successfully. This is the smallest demonstrated
correction; it is now applied to discussion-theme requests. Raising num_predict alone gives reasoning more room but increases
latency and does not reliably bound how much answer budget remains.

Separately, consider explicitly rejecting done_reason=length before parsing and
showing a specific incomplete-generation message. This would also reject a
syntactically valid answer ending at the limit, so it is an application behavior
change; it is now applied so truncated responses never produce drafts, even if their JSON happens to parse. Keep strict source validation;
do not accept partial JSON, strip arbitrary model prose, or silently repair IDs.
Other configured models should be checked for support of the think control.

Ollama documents thinking controls and the separate thinking/content fields at
https://docs.ollama.com/capabilities/thinking and completion metadata at
https://docs.ollama.com/api/chat.

## Diagnostics and regression coverage

Set CG_DEV_THEME_DIAGNOSTICS=1 only in a local development process. Diagnostics
are disabled by default; Compose does not enable them. Failed responses emit a
bounded category: truncated_output (explicit length termination), malformed_json,
schema_mismatch, invalid_question_references, or invalid_envelope. Missing
completion metadata cannot conclusively distinguish truncation from malformed
JSON, so it is not guessed from an arbitrary parse error.

Logs contain only the category, allowlisted completion reason, integer token
count, question count, and character counts. They never include raw response
values, exception messages, titles, questions, reasoning, URLs, or credentials.
The public error remains unchanged. Responses explicitly terminated by the token limit are now rejected before parsing.

Tests cover empty and partial answers at token exhaustion, malformed JSON,
schema mismatches, boolean and unknown references, disabled diagnostics, privacy,
and a valid three-question response. Existing timeout, HTTP, access-control,
draft-only, escaping, and gathering-isolation tests remain in place.

Follow-up regression tests also cover length termination with syntactically valid JSON and model errors containing sensitive text. The output limit remains 700 tokens; HTTP timeouts remain 45 seconds with a 5-second connect timeout.

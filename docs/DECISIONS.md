# Technical decisions

1. **FastAPI and plain HTML:** fewer moving parts than a full JavaScript frontend; easy to teach, test, and containerize.
2. **SQLite for prototype:** no extra database server; mounted volume persists between container restarts. Concurrent/large deployments can migrate to PostgreSQL.
3. **Ollama outside initial core:** participant workflows must function when inference is unavailable. AI will produce host-reviewable suggestions, not automatically publish conclusions.
4. **Synthetic data only:** consent, privacy, retention, identity, and moderation must be designed before real-world testing.
5. **Independent identity:** project belongs to its creators and is not a Resonance product or endorsement.
6. **Deployment gate:** local success is necessary but not sufficient; a public release needs security/privacy changes documented in README.

## 2024-05-24 - [Backend] Concurrent LLM calls in FastAPI routes
**Learning:** Sequential awaits on independent LLM tasks (like auto-title generation and chat response) introduce unnecessary cumulative latency. LLM endpoints are heavily I/O-bound.
**Action:** Always use `asyncio.gather` to execute multiple independent LLM tasks concurrently instead of awaiting them sequentially to cut down wait times for the user.

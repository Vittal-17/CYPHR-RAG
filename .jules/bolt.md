## 2024-05-24 - [Backend] Concurrent LLM calls in FastAPI routes
**Learning:** Sequential awaits on independent LLM tasks (like auto-title generation and chat response) introduce unnecessary cumulative latency. LLM endpoints are heavily I/O-bound.
**Action:** Always use `asyncio.gather` to execute multiple independent LLM tasks concurrently instead of awaiting them sequentially to cut down wait times for the user.

## 2024-05-18 - React List Rendering Bottleneck
**Learning:** Found a severe React performance bottleneck where managing input state (e.g., `editTitle`) in a large parent list component (`Sidebar`) causes the entire list to re-render on every keystroke.
**Action:** Extract list items into their own memoized components (e.g., `ChatRow`) and move local input state down into these child components. Use `React.memo` with a custom equality function for robust prop comparison, especially when dealing with parent callback functions.

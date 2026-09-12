# RAG Architecture Audit: CYPHR

## 1. Pipeline Topology
* **Loaders:** In-memory PDF parsing via `PyPDF` (`extract_text_from_pdf`).
* **Chunking:** Naive fixed-size character iteration (1000 length, 200 overlap). No recursive or semantic boundaries.
* **Embedders:** Remote Jina Embeddings v3 accessed via async batched HTTP clients with exponential backoff and quota locks.
* **Vector Storage:** MongoDB Atlas Vector Search (`$vectorSearch` HNSW index). Queries utilize dynamic metadata pre-filtering (`user_email`, `filename`).
* **Rerankers:** None implemented. Relies purely on `$vectorSearchScore` and naive filename filtering.
* **Synthesis:** AsyncOpenAI-compatible clients communicating dynamically with multiple LLMs (Groq, TokenForge) using static prompt templating.

## 2. Retrieval & Context Vulnerabilities
| File Path | Line Number | Vulnerability / Bottleneck | Remediation |
| --- | --- | --- | --- |
| `backend/services.py` | 121 | **Vulnerability:** False-positive metadata intent detection (`if fname.lower() in query_lower:`). Will trigger incorrect index filtering on substring matches (e.g. file "is.pdf"). | Implement explicit LLM intent extraction or exact regex word boundary matching. |
| `backend/services.py` | 163 | **Vulnerability:** No dynamic token budgeting for the concatenated context. Exposes the API to context window truncation or rejection errors. | Integrate a tokenizer (e.g., `tiktoken`) to safely truncate or summarize context before prompt insertion. |
| `backend/services.py` | 198 | **Vulnerability:** Naive citation heuristic (`if i == 0 or filename in answer:`). Context attribution drops if the LLM paraphrases the source name. | Enforce structured JSON schema output to force the LLM to provide explicit source arrays. |
| `backend/services.py` | 49 | **Bottleneck:** Naive character slicing splits words and sentences abruptly, severely degrading the resulting semantic embedding vectors. | Adopt semantic chunking (NLTK/spaCy) or recursive character splitting. |
| `backend/services.py` | 27 | **Bottleneck:** Entire PDF byte array loaded into RAM (`io.BytesIO(pdf_bytes)`), creating an immediate OOM vector on concurrent large file ingestion. | Stream document parsing directly to temporary storage or spool generator pipelines. |

## 3. Concurrency, I/O & API Bottlenecks
* **Vector Query Latencies:** Synchronously fetching all user document names via `await collection.distinct("filename")` during every chat request adds linearly scaling I/O overhead before vector search can begin.
* **Batching Inefficiencies:** `process_and_store_document` aggregates all parsed chunks and their metadata into a massive list in memory before dispatching embedding requests. Memory usage spikes relative to document size.
* **Unhandled Network Errors:** The `client.chat.completions.create` network call lacks an explicit `timeout` configuration. If the provider hangs, it leaks stream connections and permanently blocks the async worker.
* **Blocking Background Tasks:** `generate_auto_title` executes in the critical path for new chats. This API roundtrip sequentially blocks the generation of the user's chat response, needlessly inflating perceived latency.

## 4. Remediation Priority Checklist
* [ ] P0 (Silent failure/Context leak): Fix substring filename intent detection to prevent inaccurate metadata vector search filtering.
* [ ] P0 (Silent failure/Context leak): Add explicit timeouts to `client.chat.completions.create` to avoid unhandled provider hangs and connection leaks.
* [ ] P1 (Latency/Query cost): Dispatch `generate_auto_title` as a Fastapi `BackgroundTasks` rather than blocking the main `/chat` response path.
* [ ] P1 (Latency/Query cost): Remove or cache the `collection.distinct("filename")` MongoDB aggregation during vector retrieval.
* [ ] P1 (Latency/Query cost): Stream the PDF parsing and chunk array directly into batched embedding tasks instead of memory hoarding.
* [ ] P2 (Dead code/Types): Refactor the naive chunking loop to preserve semantic sentence boundaries.
* [ ] P2 (Dead code/Types): Type-hint the returned dictionary schema in `extract_text_from_pdf` and `generate_chat_response` to prevent untyped contract drift.

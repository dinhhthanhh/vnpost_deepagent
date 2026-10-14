# Routing, metrics, and scale boundary

## What the running prototype now does

The request router is **fast-first**. It normalizes Vietnamese input to NFC and does not call an LLM for a normal one-idea question. A question such as “Nghỉ phép năm được mấy ngày?”, “tại sao…?” or “tóm tắt…” starts at Tier 1; wording alone does not make it deep.

| Tier | Trigger | Runtime path | Sequential LLM calls in the code |
| --- | --- | --- | --- |
| 0 | Greeting | One direct response, no retrieval | 1 |
| 1 (default) | One idea | Retrieve once → source gate → Fast RAG final answer | 1 |
| 2 | Image, comparison, arithmetic, several questions/items, or no Tier-1 evidence | Retrieval evidence → bounded Deep Agent → source gate | Model-dependent; bounded by `DEEP_MAX_AGENT_STEPS` |
| Fallback | Deep budget expires | Reuse Tier-1 evidence and answer via Fast RAG | 1 additional fast answer call |

`LLM_ROUTER_ENABLED=false` is the default. It retains the former semantic LLM router only for an explicit experiment; it is not part of the normal critical path. The service emits `router_decision`, `source_gate`, `route_escalated`, `deep_timeout`, `retrieval`, `retrieval_cache_hit`, `llm_start`, and `llm_end` events.

A Tier-1 retrieval is stored in request context. If its source gate escalates, the Deep Agent receives exactly that evidence. Repeating the same query through `search_documents` uses the per-request cache, so it does not hit the index a second time. The prompt also instructs the supervisor not to delegate an identical RAG query.

Text is emitted before optional TTS starts. `DEEP_TIMEOUT` bounds the deep graph; the outer `REQUEST_TIMEOUT` still caps the full request.

## Reproduce the measurement

```powershell
# Deterministic, no provider calls
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost

# Actual configured BKAI embedding + LLM service
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost --live
```

The command writes `reports/architecture_metrics.json`. It does not save prompts or answers. The report has per-sample and aggregate p50/p95 elapsed time, time-to-first-token (fast streaming path), executed route, initial tier, LLM call count, maximum concurrent LLM calls, retrieval call/cache-hit count, source-gate result, deep timeout, task count, and KB revision/record count. Add real, business-reviewed questions to `evaluation/architecture_benchmark.jsonl` before treating these numbers as an acceptance benchmark.

## 100k-document target: intentional migration boundary

The current `KnowledgeBase` is a pilot implementation. It uses an in-process LlamaIndex snapshot and in-memory BM25 and rebuilds its snapshot on document mutation. It has no trusted department metadata or SSO-derived document ACL. It is therefore **not** a 100,000-document or departmental-authorization implementation.

For Kubernetes, keep the above tier policy in stateless API pods, but replace the pilot storage path with:

```text
API/router pods ──> retrieval gateway ──> Qdrant/pgvector (metadata + ACL filters)
       │                     │
       │                     └──────────> PostgreSQL catalog/version/department ACL
       ├──> Redis (session lock, request cache, rate limit)
       └──> queue ──> ingestion workers (parse/OCR/chunk/embed/upsert)
                         └──> object storage (original documents)
```

Department routing should be added only after ingestion records an authoritative department/ACL field. Then either filter retrieval by the caller’s permitted departments and score each permitted department’s representative vector, or run bounded parallel retrieval across permitted departments. Never route by department before access filtering, and never trust a department supplied by the browser.

The next evidence-based optimisation is to collect real request logs containing only route/tier, latency, source-gate outcome and user evaluation, label a few hundred to a few thousand requests, then train an embedding-feature complexity classifier. That replaces hand-tuned thresholds only after there is data to validate it.

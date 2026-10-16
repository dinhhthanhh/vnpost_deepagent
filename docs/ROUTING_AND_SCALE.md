# Routing, metrics, and scale boundary

## What the running prototype now does

The request router is **fast-first**. It normalizes Vietnamese input to NFC and does not call an LLM for a normal one-idea question. A question such as “Nghỉ phép năm được mấy ngày?”, “tại sao…?” or “tóm tắt…” starts at Tier 1; wording alone does not make it deep.

| Tier | Trigger | Runtime path | Sequential LLM calls in the code |
| --- | --- | --- | --- |
| 0 | Greeting, direct arithmetic (`is_pure_arithmetic`), relative date (`fastpath.py`) | Direct code answer, no retrieval | **0** (instant, 0 tokens) |
| 1 (default) | Standard business inquiry (one idea) | Retrieve once → source gate → Fast RAG final answer | 1 |
| 2 | Image, comparison, multistep, postal operations, several questions, or escalated | Retrieval evidence → bounded Deep Agent (up to 3 parallel sub-agents) → source gate | Model-dependent; bounded by `DEEP_MAX_AGENT_STEPS=12` |
| Fallback | Deep budget expires (timeout 35s) | Reuse prefetched evidence and answer via Fast RAG | 1 additional fast answer call |

`LLM_ROUTER_ENABLED=false` is the default. It retains the former semantic LLM router only for an explicit experiment; it is not part of the normal critical path. The service emits `router_decision`, `source_gate`, `route_escalated`, `deep_timeout`, `retrieval`, `retrieval_cache_hit`, `llm_start`, and `llm_end` events.

A Tier-1 retrieval is stored in request context. If its source gate escalates, the Deep Agent receives exactly that evidence. Repeating the same query through `search_documents` uses the per-request cache, so it does not hit the index a second time. The prompt also instructs the supervisor not to delegate an identical RAG query.

Text is emitted before optional TTS starts. `DEEP_TIMEOUT` (35s) bounds the deep graph; the outer `REQUEST_TIMEOUT` (120s) still caps the full request.

## Reproduce the measurement

```powershell
# Deterministic, no provider calls
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost

# Actual configured BKAI embedding + live LLM service (Gemini 2.5 Flash)
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost --live

# Compare routing modes (auto, fast, deep)
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost --live --mode auto
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost --live --mode fast
.\.venv\Scripts\python scripts\benchmark_architecture.py --tenant vnpost --live --mode deep
```

The command writes `reports/architecture_metrics.json` and `reports/architecture_comparison.json`. Measured on 2026-10-16 with `gemini-2.5-flash`:
- **Overall median latency (P50):** 2.27s (Fast RAG P50: 2.27s, Deep Agent P50: 3.55s, Tier 0 shortcut: 31ms).
- **Completion rate:** 8/8 (100%), 0 errors, 0 timeouts.
- **Tokens saved:** 100% token savings on greetings and arithmetic via Tier 0 AST calculator.

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

"""Mock HTTP providers, but run the REAL ChatOpenAI + OpenAIEmbedding + harness.

No paid model, private server, credentials or network access are used by this test.
"""
import json

import httpx
import respx

from app.config import Settings
from app.schemas import ChatRequest
from app.service import ChatService


async def test_live_provider_contract_with_real_clients(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, demo_mode=False,
                        api_keys_json='{"contract-test-key-123456":"a"}',
                        llm_api_key="dummy", llm_model="tool-model",
                        llm_base_url="https://provider.test/v1",
                        embedding_provider="openai", embedding_api_key="dummy",
                        embedding_base_url="https://provider.test/v1", embedding_model="custom-embedding")
    calls = {"llm": 0, "embedding": 0}

    def embeddings(request):
        calls["embedding"] += 1
        payload = json.loads(request.content)
        assert payload["model"] == "custom-embedding"
        items = payload["input"] if isinstance(payload["input"], list) else [payload["input"]]
        return httpx.Response(200, json={"object": "list", "model": payload["model"],
                                        "data": [{"object": "embedding", "index": i, "embedding": [1.0, 0.0, 0.0]} for i in range(len(items))],
                                        "usage": {"prompt_tokens": 10, "total_tokens": 10}})

    def completions(request):
        calls["llm"] += 1
        payload = json.loads(request.content)
        assert payload["model"] == "tool-model"
        system = str(payload["messages"][0]["content"])
        has_tool = any(m["role"] == "tool" for m in payload["messages"])
        message = {"role": "assistant", "content": None}
        if "ROLE: rag" in system and not has_tool:
            message["tool_calls"] = [{"id": "search", "type": "function", "function": {"name": "search_documents", "arguments": json.dumps({"query": "thời hạn hoàn cước"})}}]
        elif "ROLE: supervisor" in system and not has_tool:
            tasks = [{"id": "research", "agent": "rag-agent", "description": "thời hạn hoàn cước"}]
            message["tool_calls"] = [{"id": "parallel", "type": "function", "function": {"name": "parallel_tasks", "arguments": json.dumps({"tasks": tasks})}}]
        else:
            message["content"] = "Thời hạn hoàn cước là 7 ngày [S1]."
        return httpx.Response(200, json={"id": "chat-test", "object": "chat.completion", "created": 1, "model": "tool-model",
                                        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://provider.test/v1/embeddings").mock(side_effect=embeddings)
        router.post("https://provider.test/v1/chat/completions").mock(side_effect=completions)
        svc = ChatService(settings)
        try:
            svc.knowledge.for_tenant("a").ingest("policy.txt", "Thời hạn hoàn cước là 7 ngày.".encode())
            result = await svc.chat("a", ChatRequest(message="Thời hạn hoàn cước?", mode="deep"))
            assert result.grounding_status == "cited"
            assert len(result.sources) == 1 and result.sources[0].filename == "policy.txt"
            # One query embedding is the mandatory RAG prefetch for grounded Deep mode;
            # the delegated RAG task issues the second query embedding.
            assert calls["llm"] == 4 and calls["embedding"] == 3
        finally:
            await svc.close()

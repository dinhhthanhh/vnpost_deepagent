"""VNPost Deep Agent Chatbot application package.

Architecture:
- app.api: FastAPI application, HTTP endpoints, Pydantic schemas.
- app.core: Configuration, execution context, metrics, LLM providers, prompts, checkpointers.
- app.rag: Knowledge bases, hybrid retrieval, embeddings, reranking, clustering.
- app.tts: ZeroTTS, speech preprocessing, and audio output.
- app.agents: Multi-agent orchestration, tools (calculator, actions), intent signals.
- app.router: 4-tier adaptive query router and fastpath rules.
- app.domain: VNPost services catalog, tariff rules, and terminology.
- app.service: Central coordinator (ChatService) connecting all components.
"""

__version__ = "1.0.0"

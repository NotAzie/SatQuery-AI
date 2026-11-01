# `earth_platform/llm`

**Purpose.** Provider-neutral model access: OpenAI, Claude, Gemini, Ollama, OpenRouter and future providers behind one contract.

**Belongs here**
- Request/response/chunk vocabulary (`types.py`), `LLMProvider`/`ProviderFactory` Protocols, `ProviderManager`, `ModelSelector`, normalised errors
- Concrete adapters, one subpackage per vendor, when implemented (`llm/providers/<kind>/`)

**Never here**
- Conversation state or persistence (sessions)
- Tool execution or agent loops (agent)
- Vendor types in signatures
- Imports of `agent`, `engine` or `vision`

**Depends on.** `settings`, `shared`.

**Public interface.** `LLMProvider.stream/complete/list_models/health`, `ProviderFactory.create`, `ModelRef`, `ModelCapabilities`, `LLMChunk`.

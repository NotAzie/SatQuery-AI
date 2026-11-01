# ADR 0002: The LLM thinks, the Engine executes

**Status:** accepted

**Context.** LLMs reason well and compute unreliably; Earth analysis must be reproducible.

**Decision.** The model chooses tools and interprets evidence. Every number comes from an Engine tool
call. Tools return structured output plus evidence references; the model is expected to explain
discrepancies and uncertainty (for example a 61% vs 63% vegetation estimate) from that evidence.

**Consequences.** Tools are the product surface of the Engine to the model, so tool schemas are
designed for model use. Prompts must not ask the model to calculate. Evidence ids flow end to end so
the UI can show what an answer rests on.

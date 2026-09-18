# Why classify/extract run on a self-hosted model

GDPR doesn't strictly forbid sending email content to a cloud LLM API —
there are compliant paths (DPAs, SCCs, EU-region hosting). But for
clients with a data-residency requirement (common with German
Mittelstand clients), the simplest and most convincing story is that
customer email content never leaves their infrastructure at all. That's
what `LLM_PROVIDER=ollama` buys: classify/extract run against a model
served by the `ollama` container in `docker-compose.yml`, on the same
network as everything else.

This is a product decision, not a substitute for legal review — for an
actual engagement, confirm the final data-flow story with the client's
DPO/counsel.

## Model choice

Default is `mistral:7b-instruct` — Apache 2.0 (genuinely open source,
not just open-weight), from an EU company, strong German-language
performance, and small enough to run classify/extract workloads without
needing a GPU farm. `OLLAMA_MODEL` in `.env` can point at any model
Ollama can pull; worth knowing about as alternatives:

- **Larger Mistral variants** (Mixtral 8x7B, Mistral Small) if
  extraction accuracy on messier emails needs it.
- **Teuken-7B** (OpenGPT-X, EU-funded, explicitly built for EU-language
  "digital sovereignty") — behind Mistral on raw capability, but a
  strong talking point in a pitch to a sovereignty-sensitive client.

## Swapping backends

`app/src/app/llm/base.py` defines `LLMClient` with one method,
`complete_json(system_prompt, user_prompt, json_schema) -> dict`.
`OllamaClient` and `ClaudeClient` both implement it; `llm/factory.py`
picks one based on `LLM_PROVIDER`. `app/src/app/pipeline/classify.py`
and `extract.py` depend only on the interface, so a client without a
data-residency constraint can run this on Claude for a faster/more
accurate POC by flipping one env var — same pipeline code either way.

## Serving in production

Ollama (used here) is the easy path for a demo. For an actual client
deployment with real load, move to
[vLLM](https://github.com/vllm-project/vllm) on a proper GPU host — it
exposes an OpenAI-compatible API, so `OllamaClient` would need only a
new sibling adapter (`VLLMClient`), not a pipeline change.

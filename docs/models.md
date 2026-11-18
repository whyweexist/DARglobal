# OpenRouter model registry and fallbacks

The model catalog is refreshed from the official `GET /api/v1/models` endpoint and filtered server-side to only catalog entries with zero prompt, completion and request pricing and text I/O support. Models are cached in memory for one hour. The special `openrouter/free` router is always selectable; no other entry is shown if catalog discovery fails.

When a user selects a model, the API validates it against the current allowlist. The LLM gateway tries that model, then `openrouter/free` when different, followed by up to two additional confirmed free models. 401/403 authentication errors stop immediately. Other provider errors are bounded and return source evidence without fake AI text if every model fails.

The selected model is reported separately from the provider-returned `model_used` when available. Free model availability is dynamic; a previously free model can disappear or become incompatible. Do not assume tool-calling support from a model slug. The live source tool is deterministic Python so model-native function calling is not required.

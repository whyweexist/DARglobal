# Security and operational trust boundaries

1. **Secrets:** API key is read only from server environment, never compiled into Next.js. `.env` files excluded from Git and Docker builds.
2. **API:** FastAPI Pydantic validation and maximum message size; per-process IP request limiter; same-origin frontend proxy; restrictive CORS, frame denial, no-store, nosniff. Place a reverse-proxy rate limiter or WAF in front of high-traffic production deployments.
3. **Source fetch:** Host allowlists, HTTPS only, DNS public-IP validation, robots checks, redirects only after per-hop policy revalidation, content-type/size/time bounds, limited crawl pages and delay. DNS rebinding is not fully eliminated by DNS pre-checks; container egress firewall policies are recommended for high-risk hosting.
4. **Prompt injection:** Untrusted source HTML is reduced to evidence passages. No arbitrary user/LLM tool invocations. Ingested text cannot modify system policies. Rendering is via React text, not `dangerouslySetInnerHTML`.
5. **Grounding:** Evidence IDs and numeric claims verified against retrieved excerpts; model-supplied citation URLs are ignored. This is a conservative filter, not a formal proof of entailment.
6. **Conversation access:** Per-conversation token digests stored, high-entropy bearer token returned only to the caller. There is no global account management; deployments requiring user isolation should add verified authentication and storage encryption.
7. **Cost abuse:** Free-model registry checks source catalog prices; per-client limiter protects the user's free quota at low traffic. Add edge-level distributed limits for scaled environments.
8. **Container:** Dedicated unprivileged user and volume mounts; only frontend is publicly exposed. Keep base images and dependencies security-updated.
9. **Source rights:** Site terms and authorization have precedence over technical crawl ability. Wasalt is disabled by default.

### Residual risks requiring deployment hardening

- The current rate limiter is per-process memory, not durable distributed enforcement.
- Certificate/DNS pinning is not implemented; use egress restrictions and trusted DNS infrastructure.
- No native user account authentication. Appropriate for controlled assessments, not a multi-tenant public paid service.
- Model output may contain unsupported qualitative conclusions despite conservative citation validation. Human review is required for transaction-critical decisions.
- Add security scanning and a CSP appropriate for the final deployment's Next.js asset policy.

# Debussy — Issues from `ai/` + `normalize/edtf.py` Audit (User-Centered)

**Source:** Layer-1 user-centered audit of `src/kwb/ai/` and `src/kwb/normalize/edtf.py`
**Date:** 2026-04-28
**Scope:** `ai/__init__.py`, `ai/batch.py`, `ai/gpustack.py`, `ai/mock.py`, `ai/ollama.py`, `ai/prompts.py`, `ai/provider.py`, `normalize/edtf.py`
**Calibration:** Severity reflects user impact, not code health. *High* = user is misled or blocked. *Medium* = user is confused or has to guess. *Low* = workable but clumsy.

This audit pairs with `debussy-core-audit-issues.md` and `debussy-analyze-enrich-audit-issues.md`. It uses the prefix `AI-` for `ai/`-area issues and `EDTF-` for date-pattern issues.

## Issue Template

```
## <ID> — <Title>

**Type:** Bug | Enhancement | Refactor | Tech Debt
**Severity:** Critical | High | Medium | Low
**Effort:** S (<1d) | M (1–3d) | L (>3d)
**Affected:** <files/modules>
**Discovered:** <audit reference>

### Problem
What is wrong / suboptimal today, framed from the user's perspective.

### Expected
What the desired user experience looks like.

### Reproduction (bugs only)
Minimal steps or code snippet.

### Suggested approach
How to fix or implement.

### Acceptance criteria
Checkable items defining "done".

### Related
Other issues, dependencies, references.
```

---

# `ai/` — bugs (silent failures, misleading outputs, hidden assumptions)

## AI-BUG-01 — `process_batch` catches `Exception` broadly; `KeyboardInterrupt` and `SystemExit` are swallowed only by accident

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ai/batch.py` — `process_batch()`
**Discovered:** AI audit 2026-04-28

### Problem
`except Exception as e:` in the per-item loop catches everything that derives from `Exception`. That excludes `KeyboardInterrupt` and `SystemExit` (good), but it includes `MemoryError`, `RuntimeError`, and `AttributeError` from completely unrelated bugs in the prompt-building function. From the user's perspective, a developer error in `prompt_fn` looks identical to a network failure: a row is reported as "failed" with a vague error message. The user concludes their data is bad; the real cause is a programming mistake.

### Expected
Network and provider errors are caught and recorded as item failures. Programming errors (bugs in `prompt_fn`, malformed input) are surfaced once with a stack trace, not silently turned into per-item failures.

### Suggested approach
1. Catch a narrow set of expected exceptions: `ConnectionError`, `TimeoutError`, `URLError`, `HTTPError`, `json.JSONDecodeError`, and any provider-defined error class
2. Let `TypeError`, `AttributeError`, `KeyError` (likely bugs in `prompt_fn` or item shape) propagate after the first occurrence — fail fast, fix bug
3. Document which exceptions count as "expected" vs. "bug"
4. UI: "247 of 250 succeeded" looks the same as before to the user, but they're spared a class of hidden bugs

### Acceptance criteria
- [ ] Exception handling distinguishes "expected provider failure" from "programmer error"
- [ ] First programmer error halts the batch with a clear traceback
- [ ] Documentation lists the caught error types
- [ ] Test asserts the distinction

### Related
- EXT-BUG-01 (silent batch failures — same family)
- EXT-BUG-02 (parse failures)

---

## AI-BUG-02 — `BatchReport` does not record which `prompt_fn` was used; results from different runs are indistinguishable

**Type:** Bug / Provenance gap
**Severity:** High
**Effort:** S
**Affected:** `src/kwb/ai/batch.py` — `BatchReport`, `process_batch()`
**Discovered:** AI audit 2026-04-28

### Problem
`BatchReport` records `total`, `succeeded`, `failed`, `total_duration_seconds`, `results` — but not the prompt template that produced them, the model used, or any task identifier. If a user runs three different LLM tasks (NER, EDTF, semantic) on the same dataset, all three batches produce identical-looking reports. There is no way to look at a `BatchReport` and answer "what task was this?" or "which prompt version was active?"

This is the upstream cause of EXT-ENH-08 (prompt versioning). Without batch-level provenance, per-fact provenance is harder to reconstruct correctly.

### Expected
Every `BatchReport` carries: `task_name` (free-text or enum), `prompt_id`, `prompt_version`, `model_used`, `provider_name`, `started_at`, `finished_at`. The dashboard surfaces these. Exports include them.

### Suggested approach
1. Extend `BatchReport` with the fields listed
2. Extend `process_batch()` signature to accept `task_name` and `prompt_id` parameters (keyword-only, default empty for back-compat)
3. Update callers in `analyze/` and `enrich/` to pass these
4. UI: render task and prompt info in batch summary panel

### Acceptance criteria
- [ ] `BatchReport` carries task / prompt / model provenance
- [ ] All callers populate the new fields
- [ ] UI shows them
- [ ] Round-trip preserved in serialised reports

### Related
- EXT-ENH-08 (prompt versioning) — depends on this
- CORE-ENH-03 (provenance fields) — same architectural family
- AI-ENH-01 (prompt object refactor)

---

## AI-BUG-03 — `delay_seconds=0.0` default plus no per-provider rate-limit awareness leads to API bans on real workloads

**Type:** Bug / Operational defect
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/ai/batch.py`, `src/kwb/ai/gpustack.py`, `src/kwb/ai/ollama.py`
**Discovered:** AI audit 2026-04-28

### Problem
`process_batch(..., delay_seconds=0.0)` is the default. For 8,308 records this means hammering the provider as fast as it can respond. Local Ollama or GPUStack instances often handle this fine for a while, then start returning 429s. `gpustack.py` does back off on 429 (`time.sleep(2 ** attempt)`), but only on a single request — not across the batch. Sustained 429 means the user sees "247 of 8,308 succeeded" with no indication that the provider rate-limited the rest.

For the user this looks like "the model is broken" or "the data is bad." Neither is true.

### Expected
- Adaptive batch-level rate limiting: if a request hits 429, the *batch* slows down for subsequent items, not just retries the one
- Default `delay_seconds` is calibrated per provider (Ollama local: 0; GPUStack remote: 0.05–0.1; cloud APIs: provider-specific)
- The user sees the rate-limiting decisions in the batch report ("Provider rate-limited; reduced rate to X/sec mid-batch")

### Suggested approach
1. Add a `rate_limiter` callable parameter to `process_batch` that observes responses and adjusts delay
2. Default rate limiters per provider class
3. Surface adaptive-throttle events in the batch report
4. Document expected throughput per provider

### Acceptance criteria
- [ ] Adaptive throttle on 429
- [ ] Throttle events visible in `BatchReport`
- [ ] Documentation on per-provider tuning
- [ ] Test simulates 429 mid-batch and asserts throttle activates

### Related
- EXT-BUG-01 (silent failures)
- AI-BUG-04 (HTTPError 429 retry exhaustion)

---

## AI-BUG-04 — `gpustack.py` HTTP retry loop has a fall-through bug; on 429 it never re-raises after exhausting retries

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ai/gpustack.py` — `GPUStackProvider.complete()`
**Discovered:** AI audit 2026-04-28

### Problem
The retry loop:
```python
for attempt in range(1, self.config.max_retries + 1):
    try:
        ...
    except HTTPError as e:
        last_error = e; body = e.read().decode(...)
        if e.code == 429: time.sleep(2 ** attempt)
        elif e.code >= 500: time.sleep(1)
        else: raise
    except (URLError, TimeoutError) as e:
        last_error = e; ...; time.sleep(1)
raise ConnectionError(f"Failed after ...")
```

On 429, the loop sleeps and retries. But: the same `Request` object is sent again (`req` was built once before the loop), and the call carries no retry-after honouring. After `max_retries=3` attempts, the final `raise ConnectionError(...)` is reached — but only if the loop exits naturally, which only happens when the *last attempt* hit an exception. If the last attempt got a 429 and `time.sleep` then loop ends, the function falls through to `ConnectionError`. That's misleading: the actual error was rate-limiting, not connection failure. The user sees "Failed after 3 attempts: 429 Too Many Requests" classified as a connection error.

A subtler problem: `e.read()` consumes the body; if a second handler tries to read it, it gets nothing. Code seems OK here, but worth noting.

### Expected
After exhausting retries, the original exception type is preserved so the user knows whether it was rate-limiting, server error, or connection failure. The error message includes the response body.

### Suggested approach
1. After the loop, raise a custom `ProviderError` that wraps `last_error` and exposes `.original_status_code`, `.body`, `.attempts`
2. Honour `Retry-After` header on 429
3. Document max wait time in `ProviderConfig`

### Acceptance criteria
- [ ] Specific error types preserved through retries
- [ ] `Retry-After` honoured
- [ ] Test for 429 with `Retry-After` and exhausted retries

### Related
- AI-BUG-03 (rate-limiting)
- AI-ENH-02 (provider error taxonomy)

---

## AI-BUG-05 — `ollama.py` `is_available()` returns `True` on any 200 response from `/`; doesn't actually verify Ollama is the responder

**Type:** Bug
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ai/ollama.py` — `OllamaProvider.is_available()`
**Discovered:** AI audit 2026-04-28

### Problem
```python
def is_available(self) -> bool:
    url = f"{self.config.base_url.rstrip('/')}/"
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False
```
If the user has misconfigured `KWB_OLLAMA_URL` to point at a different web server (a static HTML page on port 11434 from a previous experiment, for example), this returns `True`. The dashboard says "Ollama: connected" and then every actual request fails with cryptic JSON errors.

### Expected
`is_available()` confirms the responder is Ollama, e.g. by hitting `/api/tags` and verifying the response shape.

### Suggested approach
1. Use `/api/tags` (which Ollama exposes) and verify the response JSON has the expected `models` key
2. Same fix for `gpustack.py` `is_available()` — hit `/v1/models` and verify it returns a JSON list

### Acceptance criteria
- [ ] Both providers verify the responder is the right software
- [ ] Misconfigured URL no longer reports "connected"

### Related
- AI-ENH-04 (provider self-test)

---

## AI-BUG-06 — `MockProvider.with_defaults()` rule order can mask vision detection on non-vision inputs that contain "klassif"

**Type:** Bug / Test reliability
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ai/mock.py` — `MockProvider.with_defaults()`
**Discovered:** AI audit 2026-04-28

### Problem
`with_defaults()` registers two rules in this order:
1. `_is_vision` (matches when last message content is a list)
2. `_classify_rule` (matches when last message text contains "classif" or "klassif")

The vision rule wins for vision inputs (correct). But: a text-only message that contains the word "Klassifikation" *also* matches the classify rule. That's the intent — but the ordering is fragile: any future rule added between these two could change behaviour silently. More importantly, *real* prompts that mention classification but aren't classification calls (e.g. "do not classify") still match.

For the user this manifests only in tests, but tests passing for the wrong reason is a real risk.

### Expected
Mock rules are matched on more specific signals (task name, system prompt hash, prompt template ID) rather than free-text keyword in the user message.

### Suggested approach
1. Tie mock rules to `prompt_id` once AI-ENH-01 lands
2. Until then, document the rule precedence explicitly

### Acceptance criteria
- [ ] Mock rules use stable signals
- [ ] Documentation reflects matching strategy

### Related
- AI-ENH-01 (prompt object)

---

## AI-BUG-07 — `_message_to_dict` silently drops content parts of unknown type

**Type:** Bug / Data loss
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ai/gpustack.py`, `src/kwb/ai/ollama.py` — both implement near-identical `_message_to_dict`
**Discovered:** AI audit 2026-04-28

### Problem
```python
for item in msg.content:
    if item.get("type") == "text":
        parts.append({"type": "text", "text": item["text"]})
    elif item.get("type") == "image_url":
        parts.append({"type": "image_url", "image_url": ...})
```
Anything else (audio, document, future content types) is silently dropped from the message before sending. If a user attaches a document or tries an audio prompt (e.g. for the audio-transcription use case mentioned in earlier conversations), the request goes through with the document missing — and the model "describes a blank image" or hallucinates. The user has no clue the content was stripped.

### Expected
- Unknown content types either pass through verbatim (let the provider reject them) or raise a clear error
- Either way, no silent data loss

### Suggested approach
1. Pass through unknown types verbatim, log a debug warning
2. Or: raise `ValueError` with a clear "unsupported content type X for provider Y"
3. Decide based on which providers actually support what; document per provider

### Acceptance criteria
- [ ] No silent content loss
- [ ] Documented support matrix per provider
- [ ] Test for unknown content type

### Related
- Strategic: required if audio transcription is added

---

## AI-BUG-08 — Duplicate `_message_to_dict` in `gpustack.py` and `ollama.py` will drift; OpenAI compat is fragile

**Type:** Refactor
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ai/gpustack.py`, `src/kwb/ai/ollama.py`
**Discovered:** AI audit 2026-04-28

### Problem
Both files have a near-identical `_message_to_dict`. Any future fix (e.g. AI-BUG-07) needs to be applied twice. They will drift, and a user-visible behavioural difference between providers will appear. The user never asked for that — they want "use whichever provider is configured" to be transparent.

### Expected
A single shared serializer in `ai/provider.py` or a new `ai/openai_compat.py`, used by both providers.

### Suggested approach
1. Move `_message_to_dict` (and related helpers) to a shared module
2. Update both provider implementations
3. Add tests asserting the two providers serialize identically for the same input

### Acceptance criteria
- [ ] Single source of truth for OpenAI-compat message conversion
- [ ] Both providers use it
- [ ] Provider-equivalence test

### Related
- AI-BUG-07 (silent content drop)

---

## AI-BUG-09 — `ProviderConfig` has no `provider_type` field; misconfiguration produces wrong-API errors

**Type:** Bug / UX
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/ai/provider.py` — `ProviderConfig`, plus consumers in `core/config.py`
**Discovered:** AI audit 2026-04-28

### Problem
`ProviderConfig(base_url=..., api_key=..., default_model=..., timeout, retries)` has no field saying *which provider* this config belongs to. The system relies on the user instantiating the right `AIProvider` subclass. If the user enters `KWB_GPUSTACK_URL=http://localhost:11434` (Ollama's port), the GPUStackProvider tries to talk to Ollama, gets HTTP 404 on `/v1/models`, and the user sees "GPUStack unavailable."

### Expected
`ProviderConfig` includes `provider_type`. The factory function that builds providers picks the right class. Misconfigurations are caught with helpful messages: "URL responds like Ollama but provider is GPUStack — did you mean to use OllamaProvider?"

### Suggested approach
1. Add `provider_type: Literal["gpustack", "ollama", "mock"]` to `ProviderConfig`
2. Factory function `make_provider(config) -> AIProvider`
3. Diagnostic check that detects URL-vs-provider-type mismatch

### Acceptance criteria
- [ ] Single factory point for providers
- [ ] Helpful diagnostic on mismatch
- [ ] Documentation

### Related
- AI-BUG-05 (is_available misdiagnosis)
- AI-ENH-04 (provider self-test)

---

# `ai/` — enhancements (user-centered)

## AI-ENH-01 — Prompts as data, not constants; users cannot see, edit, or version them today

**Type:** Enhancement / Refactor
**Severity:** High
**Effort:** L
**Affected:** `src/kwb/ai/prompts.py`, all consumers
**Discovered:** AI audit 2026-04-28

### Problem
`prompts.py` defines prompts as a mix of:
- module-level string constants (`SYSTEM_NER`, `SYSTEM_EDTF`, `SYSTEM_METADATA_EXPERT_DE`)
- functions returning `[AIMessage.system(...), AIMessage.user(...)]` per-call (`prompt_classify_subject`, `prompt_describe_image`, etc.)
- a half-built version registry (`PROMPT_VERSIONS = {...}` lists 5 prompts, but isn't tied to anything)

A curator wanting to:
- read what the system actually says to the model — has to read source
- adjust phrasing for their collection — has to edit source
- compare results across prompt versions — has no version
- understand which prompt produced which output — cannot

This is a structural blocker for most user-centered improvements (provenance, run history, model-quality diagnostics).

### Expected
Each prompt is a `Prompt` object with `id`, `version`, `system`, `user_template`, `output_schema`, `last_modified`, `description`. Stored in `prompts.yaml` (per locale). Loadable, listable, editable from the dashboard. Versions are immutable; bumping the version creates a new entry.

### Suggested approach
1. Define `Prompt` dataclass and a `PromptRegistry` loaded at startup
2. Migrate one prompt as proof-of-concept (NER), keep old constants as adapters during transition
3. Migrate the rest in a follow-up
4. Add a "Prompts" view in the dashboard showing all prompts, their versions, and last-modified
5. Each LLM call records `prompt_id` and `prompt_version` (closes loop with AI-BUG-02 and EXT-ENH-08)

### Acceptance criteria
- [ ] `Prompt` and `PromptRegistry` exist
- [ ] At least 3 prompts migrated end-to-end
- [ ] Dashboard surface for prompts
- [ ] Versions immutable, bumping creates new entry
- [ ] Round-trip preserved

### Related
- AI-BUG-02 (batch provenance)
- EXT-ENH-08 (prompt versioning) — same enhancement, viewed from different layer
- EXT-ENH-07 (user-extensible field semantics) — similar pattern

---

## AI-ENH-02 — Provider error taxonomy; users see raw HTTP errors and cannot triage

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/ai/provider.py`, `gpustack.py`, `ollama.py`
**Discovered:** AI audit 2026-04-28

### Problem
When a provider call fails, the user sees:
- `ConnectionError: Failed after 3 attempts: HTTP Error 429: Too Many Requests`
- `URLError: <urlopen error [Errno 11001] getaddrinfo failed>`
- `ConnectionError: Failed after 3 attempts: HTTPError 401: Unauthorized`

Three completely different problems with three completely different fixes (slow down / fix URL / fix API key), all surfaced as "ConnectionError." A non-technical user cannot tell what to do.

### Expected
A typed error hierarchy: `ProviderError` → `RateLimitError`, `AuthError`, `ConnectionError`, `BadRequestError`, `ModelNotFoundError`. Each carries actionable user-facing message and a suggested next step. Dashboard renders the next step prominently.

### Suggested approach
1. Define error class hierarchy in `ai/provider.py`
2. Map HTTP codes and exception classes to specific error types in each provider
3. Each error has a `.user_message` and `.suggested_action`
4. Dashboard renders both

### Acceptance criteria
- [ ] Error hierarchy exists
- [ ] Both providers map exceptions correctly
- [ ] User-facing messages are actionable
- [ ] Dashboard surfaces suggested actions

### Related
- AI-BUG-04 (retry error type loss)
- AI-BUG-09 (provider mismatch diagnostic)
- EXT-ENH-11 (GeoNames credentials onboarding — same pattern)

---

## AI-ENH-03 — `system_prompt=""` override pattern is implicit and untested; users cannot tell if their override took effect

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** Multiple `analyze/` and `enrich/` modules accept `system_prompt: str = ""`
**Discovered:** AI audit 2026-04-28

### Problem
Functions like `ner_llm`, `_normalize_dates_llm`, `scan_problematic_terms` accept `system_prompt=""` and use the default constant when empty. A user editing a system prompt in the dashboard config and submitting it has no immediate confirmation that the right text went to the model. If their override has a typo and falls through to default behaviour, they will not realise.

### Expected
The actual system prompt sent to the model is recorded in the result (or at least its hash/first 100 chars), and shown in the dashboard. The user can verify "yes, my override was used" without inspecting raw API logs.

### Suggested approach
1. Once AI-ENH-01 lands, every call records the resolved prompt id + override fingerprint
2. UI: per-result "system prompt used" affordance
3. Dashboard "test prompt on one record" button that returns the rendered messages, not the result

### Acceptance criteria
- [ ] User can verify which prompt text was sent
- [ ] Test-on-one-record affordance exists
- [ ] Override fingerprint in result provenance

### Related
- AI-ENH-01 (prompt object)
- EXT-ENH-01 (provenance trail)

---

## AI-ENH-04 — No "test connection" workflow that exercises the actual task path; users only test connectivity, not capability

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** Dashboard "KI-Konfiguration" tab, `provider.py`, `gpustack.py`, `ollama.py`
**Discovered:** AI audit 2026-04-28

### Problem
The dashboard has a "GPUStack testen" button. It probably calls `is_available()` and `list_models()`. A pass means: "URL is reachable, model list returned." It does *not* mean: "the configured model produces valid JSON for the NER prompt at expected speed."

A user passes the connection test, runs NER on 8,000 records, gets 30% parse failures (EXT-BUG-02), and is mystified.

### Expected
A "Capability test" that runs each task type once with a tiny synthetic input and reports: model produces valid JSON for NER (yes/no), model handles vision input (yes/no/n/a), median latency, tokens/sec. The result is a short readable report, not a raw API response.

### Suggested approach
1. Define a fixed micro-fixture per task type (1 record, known-good)
2. "Capability test" button runs each task and aggregates results
3. Render as a table: task × pass/fail × latency
4. Save the result so it can be referenced later ("this model passed/failed the test on date X")

### Acceptance criteria
- [ ] Capability test runs all task types
- [ ] Per-task pass/fail surfaced
- [ ] Saved per workspace
- [ ] Documentation explains test set

### Related
- EXT-BUG-02 (parse failures)
- EXT-ENH-04 (model selection guidance)
- AI-BUG-05 (is_available misdiagnosis)

---

## AI-ENH-05 — `prompt_describe_image` and `prompt_image_description` are aliases; same for `prompt_ocr_analysis` and `prompt_ocr_transcription_quality`

**Type:** Tech Debt
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ai/prompts.py`
**Discovered:** AI audit 2026-04-28

### Problem
```python
def prompt_describe_image(...): return prompt_image_description(...)
def prompt_ocr_analysis(...): return prompt_ocr_transcription_quality(...)
```
Aliases for renamed functions, kept for back-compat. A future contributor reading the code sees both names and doesn't know which is canonical. Tests probably reference both. This adds maintenance friction every time a prompt is touched.

### Expected
Single canonical name per task. Aliases removed after migration window with a deprecation warning.

### Suggested approach
1. Audit callers; migrate to canonical names
2. Add `DeprecationWarning` to aliases for one release
3. Remove aliases

### Acceptance criteria
- [ ] One canonical name per prompt function
- [ ] Aliases deprecated then removed
- [ ] No regressions in tests

### Related
- AI-ENH-01 (prompt registry replaces all of this anyway)

---

## AI-ENH-06 — `MockProvider.with_quality_check_responses()` is 100+ lines of hardcoded GIUB-flavored test data inside `mock.py`

**Type:** Refactor
**Severity:** Low
**Effort:** M
**Affected:** `src/kwb/ai/mock.py`
**Discovered:** AI audit 2026-04-28

### Problem
The mock factory contains specific German-language GIUB examples ("Kutsche", "location_place_name", "Eisenbahnbrücke"). It works for the existing tests but it bleeds collection-specific assumptions into the mock layer. When letters are added, this factory cannot be used; a parallel one will likely be created.

### Expected
Mock fixtures live in `tests/fixtures/` as JSON files, loaded by collection. The mock layer is a generic responder that picks fixtures by task and locale.

### Suggested approach
1. Extract hardcoded responses to JSON fixtures
2. `MockProvider.from_fixtures(path, locale="de")` factory
3. Document fixture format
4. Add letters fixtures alongside slides

### Acceptance criteria
- [ ] Fixtures externalized
- [ ] Factory loads from disk
- [ ] Both slides and letters fixture sets exist

### Related
- EXT-BUG-06 / EXT-BUG-07 (collection-agnosticism)

---

## AI-ENH-07 — No streaming support; long generations block the UI for tens of seconds with no feedback

**Type:** Enhancement
**Severity:** Medium
**Effort:** L
**Affected:** `src/kwb/ai/provider.py`, `gpustack.py`, `ollama.py`, dashboard
**Discovered:** AI audit 2026-04-28

### Problem
`provider.complete()` is fully blocking. For a long batch, the dashboard shows "running…" without progress within a single request. For long-form generations (image descriptions, dataset summaries, OCR with text-heavy images), a single request can take 30+ seconds. The user wonders if it crashed.

### Expected
Streaming token output where the provider supports it (both GPUStack and Ollama do). Even if not fully streamed to the UI, mid-request "still working" pings.

### Suggested approach
1. Add `complete_stream()` to `AIProvider` returning an iterator
2. Default implementation calls `complete()` once and yields once (back-compat)
3. Real streaming for GPUStack and Ollama
4. Dashboard: optional progress for long-form tasks

### Acceptance criteria
- [ ] Streaming interface defined
- [ ] At least one provider streams
- [ ] Dashboard renders streaming output for at least one task

### Related
- EXT-ENH-02 (run history) — streaming improves the live-run UX

---

## AI-ENH-08 — `temperature=0.0` everywhere is undocumented; users cannot tune determinism / creativity tradeoff

**Type:** Enhancement
**Severity:** Low
**Effort:** S
**Affected:** All callers of `provider.complete`
**Discovered:** AI audit 2026-04-28

### Problem
Every call uses `temperature=0.0` (greedy). For extraction tasks this is correct. For tasks like image description or "alternative wording suggestions," 0.0 produces the same response every time, missing the diversity that low-temperature sampling could provide. Users may want occasional creative output (e.g. for descriptive abstract field), but cannot tune this from the dashboard.

### Expected
Per-task temperature default, with UI override for users who want to experiment. Clear documentation: which task uses which temperature and why.

### Suggested approach
1. Add `temperature` to per-task config
2. UI slider for tasks where it makes sense
3. Document the per-task defaults

### Acceptance criteria
- [ ] Per-task temperature defaults
- [ ] UI override
- [ ] Documentation

### Related
- AI-ENH-04 (capability test)

---

# `normalize/edtf.py` — pattern coverage and bugs

The following findings are specific to date pattern handling. They close out EXT-ENH-13 in the previous audit.

## EDTF-BUG-01 — `_RANGE` and `_RANGE_TEXT` patterns produce wrong EDTF when one year is approximate but not the other

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `normalize_edtf()`
**Discovered:** EDTF audit 2026-04-28

### Problem
The pattern handler:
```python
if m := _RANGE.match(text) or _RANGE_TEXT.match(text):
    g = m.groups(); y1, y2 = g[0], g[-1]
    return EDTFResult(original=original, edtf=f"{y1}{q}/{y2}{q}", confidence=0.95, ...)
```
`q` is the global "approximate" qualifier from earlier in the function. If the input is `"ca. 1920-1930"`, both years get `~`. But for `"1920-ca. 1930"` (only second is approximate), the input never matches `_RANGE` because of the embedded `ca.`, falling through to "no pattern matched." The user sees this as "uncovered."

More generally: the function handles approximation as a single boolean, not per-end-of-range. Real GLAM data has "ca. 1920–1925" (both), "1920–ca. 1925" (only end), "ca. 1920–ca. 1925" (both, redundant) — only the first is recognised cleanly.

### Expected
Per-endpoint approximation. EDTF supports it (`1920~/1925` vs `1920/1925~`). Patterns should match each side independently.

### Suggested approach
1. Refactor range handling into a small parser that handles approximate-prefix per side
2. Test fixtures cover the four combinations
3. Document supported syntax

### Acceptance criteria
- [ ] All four "ca." combinations recognised
- [ ] Test fixtures cover them
- [ ] Documentation updated

### Related
- EDTF-BUG-02 (uncertain markers)
- EXT-ENH-13 (pattern coverage)

---

## EDTF-BUG-02 — Combined uncertainty markers (`[ca. 1920]`, `1920?-1925`) not handled

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `normalize_edtf()`
**Discovered:** EDTF audit 2026-04-28

### Problem
Patterns are mutually exclusive in the matching order:
- `_UNCERTAIN_BRACKET` matches `[1920]` but not `[ca. 1920]`
- `_UNCERTAIN_Q` matches `1920?` but not `1920?-1925`
- `_RANGE` matches `1920-1925` but not `1920?-1925`

In real archival catalogue data, combinations like `[ca. 1920]`, `[1920?]`, `1920?–1925`, `[ca. 1920–1925]` are common. None match.

### Expected
Composite uncertainty markers parsed correctly: brackets and `?` are independent qualifiers that compose with approximation and ranges.

### Suggested approach
1. Strip brackets first, set "uncertain" flag
2. Then strip "ca." / "circa", set "approximate" flag
3. Then match base pattern (year, range, decade, century)
4. EDTF qualifiers `?` (uncertain), `~` (approximate), `%` (both) compose accordingly

### Acceptance criteria
- [ ] Composite uncertainty markers handled
- [ ] EDTF `%` qualifier produced when appropriate
- [ ] Test fixtures cover compositions

### Related
- EDTF-BUG-01

---

## EDTF-BUG-03 — `_CENTURY` rule converts "19. Jh." to `18XX` (correct) but no handling of "19./20. Jh." (cross-century)

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py`
**Discovered:** EDTF audit 2026-04-28

### Problem
Common archive notations like `"19./20. Jh."`, `"Wende 19./20. Jh."`, `"Jahrhundertwende"` are not recognised. They appear frequently in GLAM date fields for objects whose date is fuzzy across a century boundary.

### Expected
Cross-century notations produce a range like `18XX/19XX` or specifically the late-19th to early-20th interval `1880/1920` if "Wende" is detected.

### Suggested approach
1. Add `_CROSS_CENTURY` pattern
2. Map to appropriate EDTF range
3. Document the heuristic ("Wende" = ±20 years around the boundary)

### Acceptance criteria
- [ ] Cross-century notations recognised
- [ ] "Wende" handled
- [ ] Tests cover

---

## EDTF-BUG-04 — `_POSITION_CENTURY` only catches a few qualifier words; "frühes 19. Jh.", "spätes 19. Jh." not matched

**Type:** Bug
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `_POSITION_CENTURY`
**Discovered:** EDTF audit 2026-04-28

### Problem
The current pattern handles "Anfang", "Beginn", "Mitte", "Ende", "Erstes Drittel", "Zweites Drittel", "Letztes Drittel". Missing: "frühes/spätes" (early/late), "Erste Hälfte / Zweite Hälfte" (first/second half), "Drittes Viertel" (third quarter).

### Expected
The full common vocabulary of century-position qualifiers is covered.

### Suggested approach
1. Extend the regex with the missing terms
2. For each, decide what EDTF range or year code to emit
3. Document

### Acceptance criteria
- [ ] All common qualifiers covered
- [ ] Test fixtures
- [ ] Documentation

### Related
- EDTF-BUG-03

---

## EDTF-BUG-05 — `_RANGE` does not handle BCE / "v. Chr."

**Type:** Bug
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py`
**Discovered:** EDTF audit 2026-04-28

### Problem
Dates like `"500 v. Chr."`, `"v.Chr. 100"`, `"100 BCE"` produce no match. EDTF supports negative years (`-0500`, `-0100`). For collections containing antiquity-related material this is a real gap; for the GIUB Glasdia or letters, less so.

### Expected
BCE notation recognised in German and English; produces negative-year EDTF.

### Suggested approach
1. Add `_BCE` pattern matching `v\.\s*Chr\.?`, `BCE`, `BC` either before or after the year
2. Emit negative-year EDTF
3. Document scope

### Acceptance criteria
- [ ] BCE notations recognised
- [ ] EDTF emits negative years correctly
- [ ] Test fixtures

### Related
- Low priority unless the project handles antiquity material

---

## EDTF-BUG-06 — `_FULL_DATE_DE` accepts `"32.13.2020"` (invalid date) without validation

**Type:** Bug / Data validity
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `_FULL_DATE_DE`
**Discovered:** EDTF audit 2026-04-28

### Problem
The regex `^(\d{1,2})\.(\d{1,2})\.(\d{4})$` matches `"32.13.2020"` and emits `"2020-13-32"` — invalid as both EDTF and ISO. The user sees a "successful" conversion to nonsense.

### Expected
Day/month range validation. Invalid dates either fall through to LLM fallback or are flagged with a clear "invalid Gregorian date" note.

### Suggested approach
1. After regex match, validate `1 ≤ month ≤ 12` and `1 ≤ day ≤ days_in_month(month, year)`
2. On failure, return `valid=False` with note "invalid Gregorian date — original pattern recognised but values out of range"
3. Same fix for `_ISO_DAY` and `_ISO_DAY_SLASH`

### Acceptance criteria
- [ ] Invalid dates flagged, not silently converted
- [ ] Test fixtures with edge cases
- [ ] Note text is user-readable

### Related
- EDTF-BUG-07 (silent year-zero handling)

---

## EDTF-BUG-07 — `_ISO_YEAR` accepts `"0000"`; EDTF spec is ambiguous

**Type:** Bug / Edge case
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `_ISO_YEAR`
**Discovered:** EDTF audit 2026-04-28

### Problem
`"0000"` matches and produces `"0000"` as EDTF. Per the proleptic Gregorian calendar there is no year 0; per ISO 8601 there is. EDTF inherits the ambiguity. For a curator trying to handle an archival placeholder where someone typed `"0000"` to mean "unknown," the system silently accepts it as year 0 CE.

### Expected
`0000` is treated as suspect (likely placeholder for unknown), not as a normal year. Either flagged or routed to "undated."

### Suggested approach
1. Detect `0000`, `00`, `999`, `9999` as common placeholder patterns
2. Treat as `valid=False` with a clear note
3. Document the heuristic

### Acceptance criteria
- [ ] Placeholder patterns detected
- [ ] Note "likely placeholder, not real date"
- [ ] Documented

---

## EDTF-ENH-01 — Pattern coverage is invisible to users; no listing of supported / unsupported inputs

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/normalize/edtf.py`, dashboard "Datierung" tab
**Discovered:** EDTF audit 2026-04-28

### Problem
A user feeding the system messy date data has no way to know what *will* be recognised. The Funktionskatalog has a small table; the source has detailed regex; the user has neither. They run a batch, see 60% conversion, and don't know whether the missing 40% is "the rules don't cover this" or "the data is genuinely broken."

### Expected
Dashboard "Datierung" tab includes a "What is recognised?" panel: a table of supported patterns with examples and a "test your input" field. Failed conversions in a batch are categorised: "no rule matched" vs. "rule matched but value invalid" vs. "LLM failed."

### Suggested approach
1. Build the supported-pattern table from the regex + tests as documentation
2. Surface in dashboard
3. Categorise failed conversions in `EDTFReport`
4. UI: "test this date" affordance with live result

### Acceptance criteria
- [ ] Pattern documentation visible in UI
- [ ] Failure categories distinguishable
- [ ] Live test affordance works
- [ ] Documentation matches code

### Related
- EXT-ENH-13 (pattern coverage audit) — this issue closes it

---

## EDTF-ENH-02 — `EDTFResult` lacks the original-input position when from batch; users cannot trace back to source row

**Type:** Enhancement
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `EDTFResult`
**Discovered:** EDTF audit 2026-04-28

### Problem
`EDTFResult` has `original`, `edtf`, `record_id`, but not the column or the row-level dataset position. When a curator looks at a failed conversion in a batch report, they cannot click through to "show me this in the source CSV."

### Expected
Result carries enough context to navigate back to the source: column name, row index, source dataset name.

### Suggested approach
1. Add `column`, `row_index`, `source_dataset` fields
2. Populate from the calling code (likely `enrich/edtf.py` `normalize_dates` and `analyze/`)
3. UI: "show in source" link

### Acceptance criteria
- [ ] Result carries source context
- [ ] UI can navigate back
- [ ] Round-trip preserved

### Related
- EXT-ENH-01 (provenance trail) — same family

---

## EDTF-ENH-03 — Hybrid path silently routes valid-but-low-confidence rules to LLM; user cannot see which path produced the result

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/normalize/edtf.py` — `normalize_edtf_llm()`, `enrich/edtf.py` — `normalize_dates()`
**Discovered:** EDTF audit 2026-04-28

### Problem
The hybrid logic in `enrich/edtf.py`:
```python
if norm.valid or norm.note in ("undatiert", "leer"):
    results.append(...)  # rule path
else:
    needs_llm.append(item)  # LLM path
```
A rule that matches with confidence 0.3 is treated the same as confidence 0.95 — both go to "rule path." The user cannot configure: "use rule when confidence > 0.7, otherwise LLM-fallback for confirmation."

The resulting `EDTFResult.method` is set to `"rule"` or `"llm"`, but it's not exposed in the dashboard table by default. Users do not see at a glance which path produced each conversion.

### Expected
A configurable confidence threshold for the rule path. UI surface for the path used per result. Optional "verify low-confidence rule matches with LLM" mode.

### Suggested approach
1. Add `rule_confidence_threshold` parameter
2. Surface `method` in dashboard
3. Add a "verify with LLM" toggle for low-confidence rule matches

### Acceptance criteria
- [ ] Threshold configurable
- [ ] UI shows path
- [ ] Toggle works

### Related
- EDTF-BUG-01 (range approximation — affects confidence)
- EXT-ENH-02 (run history — would compare paths over time)

---

# Summary

| ID | Type | Severity | Effort | Title (short) |
|---|---|---|---|---|
| AI-BUG-01 | Bug | Medium | S | Broad `Exception` catch in `process_batch` |
| AI-BUG-02 | Bug | High | S | `BatchReport` lacks task / prompt / model provenance |
| AI-BUG-03 | Bug | High | M | No batch-level adaptive rate limiting |
| AI-BUG-04 | Bug | Medium | S | GPUStack 429 retry error type loss |
| AI-BUG-05 | Bug | Low | S | Ollama `is_available` accepts any 200 OK |
| AI-BUG-06 | Bug | Low | S | MockProvider rule order fragility |
| AI-BUG-07 | Bug | Medium | S | `_message_to_dict` silently drops unknown content |
| AI-BUG-08 | Refactor | Low | S | Duplicated `_message_to_dict` |
| AI-BUG-09 | Bug | Medium | M | `ProviderConfig` lacks `provider_type` |
| AI-ENH-01 | Refactor | High | L | Prompts as data, not constants |
| AI-ENH-02 | Enhancement | Medium | M | Provider error taxonomy |
| AI-ENH-03 | Enhancement | Medium | S | System-prompt override visibility |
| AI-ENH-04 | Enhancement | Medium | M | Capability test (not just connection test) |
| AI-ENH-05 | Tech Debt | Low | S | Prompt function aliases |
| AI-ENH-06 | Refactor | Low | M | Mock fixtures externalisation |
| AI-ENH-07 | Enhancement | Medium | L | Streaming support |
| AI-ENH-08 | Enhancement | Low | S | Per-task temperature |
| EDTF-BUG-01 | Bug | Medium | S | Range approximation per endpoint |
| EDTF-BUG-02 | Bug | Medium | S | Composite uncertainty markers |
| EDTF-BUG-03 | Bug | Medium | S | Cross-century notation |
| EDTF-BUG-04 | Bug | Low | S | Century-position qualifiers incomplete |
| EDTF-BUG-05 | Bug | Low | S | BCE / v.Chr. not handled |
| EDTF-BUG-06 | Bug | Medium | S | Invalid Gregorian dates accepted |
| EDTF-BUG-07 | Bug | Low | S | Year zero / placeholder patterns |
| EDTF-ENH-01 | Enhancement | Medium | M | Pattern coverage visible to users |
| EDTF-ENH-02 | Enhancement | Low | S | Source-row traceback in result |
| EDTF-ENH-03 | Enhancement | Medium | S | Rule-vs-LLM path visibility |

## Cross-references with previous audits

- AI-BUG-02 (batch provenance) is the upstream cause of EXT-ENH-08 (prompt versioning) and EXT-ENH-01 (provenance trail). The three should be planned together.
- AI-ENH-01 (prompt object) is the upstream prerequisite for EXT-ENH-08, AI-ENH-03, AI-BUG-06, and AI-ENH-05.
- AI-ENH-02 (provider error taxonomy) extends EXT-ENH-11 (GeoNames credentials onboarding) into a general pattern.
- EDTF-ENH-01 closes out EXT-ENH-13 (deferred from the previous audit).
- AI-BUG-09 (provider mismatch) overlaps with AI-BUG-05 (is_available misdiagnosis) — fix together.

## Files audited so far (cumulative)

- `src/kwb/core/` — 14 issues filed (`debussy-core-audit-issues.md`)
- `src/kwb/analyze/` — covered in `debussy-analyze-enrich-audit-issues.md`
- `src/kwb/enrich/` — covered in `debussy-analyze-enrich-audit-issues.md`
- `src/kwb/ai/` — this document
- `src/kwb/normalize/edtf.py` — this document

## Files not yet audited

- `src/kwb/ingest/` (CSV loader, image loader, PDF loader)
- `src/kwb/api/` (routes, dashboard) — recommended only after user-centered redesign direction is decided
- `src/kwb/export/`, `src/kwb/report/` (touched lightly during cross-references)
- `tests/` — sampled audit only, not full

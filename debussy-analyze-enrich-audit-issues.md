# Debussy — Issues from `analyze/` + `enrich/` Audit (User-Centered)

**Source:** Layer-1 user-centered audit of `src/kwb/analyze/` and `src/kwb/enrich/`
**Date:** 2026-04-28
**Scope:** All files reviewed; `kwb/normalize/edtf.py` not yet seen — pattern-level findings deferred to a follow-up issue
**Calibration:** Severity reflects user impact, not code health. *High* = user is misled or blocked. *Medium* = user is confused or has to guess. *Low* = workable but clumsy.

This document captures bugs and enhancements identified in the audit, formatted so each block can be filed as a separate GitHub issue without further editing. Same template as `debussy-core-audit-issues.md`.

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

Issue IDs use the prefix `EXT-` (extraction layer) to distinguish from `CORE-`.

---

# Bugs (silent failures, misleading outputs, hidden assumptions)

## EXT-BUG-01 — Batch sampling silently drops records when LLM calls fail; user sees no warning

**Type:** Bug
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/analyze/ner.py` (`ner_llm`, `ner_hybrid`), `src/kwb/analyze/llm_quality.py`, `src/kwb/analyze/semantic.py`
**Discovered:** Audit 2026-04-28

### Problem
When an LLM call fails (timeout, malformed JSON, network blip), the batch processor records the failure in `BatchReport`, but the *user-facing* result simply contains fewer entities. A curator looks at "247 entities found" and has no way to tell whether 247 came from 250 records (98% success) or from 800 records (31% success). For a curator deciding whether the result is trustworthy, this is the difference between "ship it" and "do not publish."

The numerical impact is invisible because:
- `to_dict_list()` in `NERResult` returns only successful entities
- The `batch_report` field exists but is not surfaced anywhere prominent in dashboard responses
- "Failed" includes both *no entities found* (legitimate) and *call failed* (data quality unknown)

### Expected
Every result that involves LLM calls carries a visible **completion rate** and a **failure summary** the user sees without digging. A red banner if completion < 80%, an amber one if < 95%. The user can click through to see *which* records failed and retry just those.

### Suggested approach
1. Add a `completion_summary` field to `NERResult`, `LlmQualityReport`, and the semantic/visual results, with `total_records / succeeded / llm_failed / parse_failed / empty_result`
2. Expose this in every API endpoint that returns LLM results
3. Render it prominently in the dashboard tab — banner colour-coded
4. Add a "retry failed only" button that re-runs only the failed records
5. Distinguish "LLM said no entities" from "LLM call failed" — both currently look like "no entities"

### Acceptance criteria
- [ ] Every LLM-result type carries an explicit completion summary
- [ ] Dashboard surfaces it before the result table
- [ ] User can identify which records failed
- [ ] Retry-failed-only flow works end-to-end
- [ ] Test asserts completion summary is populated correctly even when all calls fail

### Related
- EXT-BUG-02 (silent JSON parse failures)
- EXT-ENH-01 (provenance per record)

---

## EXT-BUG-02 — JSON parse failures from LLM are silently dropped instead of flagged

**Type:** Bug
**Severity:** High
**Effort:** S
**Affected:** `src/kwb/analyze/ner.py` (`ner_llm`), `src/kwb/analyze/llm_quality.py`, `src/kwb/analyze/semantic.py`
**Discovered:** Audit 2026-04-28

### Problem
In `ner_llm`, the loop is:
```python
if result.parsed and "entities" in result.parsed:
    for ent_data in result.parsed["entities"]:
        ...
```
If the LLM returned text that wasn't valid JSON, or returned valid JSON without an `entities` key, the record is silently skipped. The same pattern repeats in `classify_subjects`, `_normalize_dates_llm`, and the cell/column/record/dataset levels of `llm_quality.py`.

A curator running NER on 100 records and getting back 60 entities cannot distinguish between:
- (A) 100 records had ~60 entities total (correct)
- (B) 70 records returned malformed JSON, 30 returned ~60 entities (broken)

### Expected
Every record that produces a parse failure is logged *and counted* and surfaced to the user. The user sees: "100 records processed, 70 produced unparseable LLM output. Likely cause: model failing to produce JSON. Try a different model or shorten the prompt."

### Suggested approach
1. In `BatchReport`, add a `parse_failures: list[ParseFailure]` field with `record_id`, `raw_response_preview` (first 200 chars), `error_message`
2. In each LLM-using analyzer, capture parse failures explicitly rather than treating them as empty results
3. Surface this in the completion summary from EXT-BUG-01
4. Log a warning per parse failure with the model name (so users notice when a specific model misbehaves systematically)
5. Optional but high-value: provide a sample of raw responses in the UI so the user can diagnose prompt issues

### Acceptance criteria
- [ ] Parse failures are counted and listed separately from "no entities"
- [ ] Raw response preview is captured (truncated, not full text)
- [ ] User can see at least 5 example failures per run
- [ ] Documentation explains common causes ("model not fine-tuned for JSON output", "max_tokens too low", "prompt unclear")

### Related
- EXT-BUG-01 (completion rate)
- EXT-ENH-04 (model selection guidance)

---

## EXT-BUG-03 — Random sampling with `random_state=42` is invisible and irreproducible from user perspective

**Type:** Bug / UX defect
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/analyze/ner.py` (`ner_hybrid`, `scan_problematic_terms`), `src/kwb/analyze/llm_quality.py`, `src/kwb/analyze/semantic.py`
**Discovered:** Audit 2026-04-28

### Problem
When sample-mode is used, the code calls `df.sample(n=sample_size, random_state=42)`. The seed is fixed *in source*, so:
- Two different runs with the same sample size return identical samples — the user has no idea this is happening
- The user cannot see *which* records were sampled
- The user cannot say "I want to see what's in the rest" without changing source code
- A "pilot" with 50 records that looks clean does not generalise — the user thinks they have evidence on the dataset, but they only have evidence on that specific seeded subset

A curator using "Pilot mode, 50 records" twice and seeing the same numbers will conclude the analysis is deterministic and reliable. It is not — it is deterministic *and the same 50 records*.

### Expected
- The sample seed is either user-controlled or random-each-run with the seed shown
- The list of sampled record IDs is part of every result
- The dashboard offers "Run on a different sample" and "Run on remaining records"
- "Pilot" results are visually marked as such, with a warning that aggregates do not generalise

### Suggested approach
1. Make the seed an explicit parameter; default to `None` (random) and log the actual seed used so the run is reproducible if needed
2. Return the list of sampled record IDs in the result object
3. UI: surface "Sampled records: 50 of 8,308 (run #3 used different seed)" prominently
4. Add a "Continue with remaining" button that excludes already-sampled IDs
5. Add a clear visual marker for pilot results vs. full-mode results

### Acceptance criteria
- [ ] Seed is parametrised
- [ ] Sampled record IDs are returned with every result
- [ ] Dashboard shows clear "Pilot — N of M records" badge
- [ ] User can re-sample or extend
- [ ] Documentation warns against generalising pilot statistics

### Related
- EXT-BUG-01 (completion rate)
- EXT-ENH-02 (run history)

---

## EXT-BUG-04 — `bare except` in `_get_affected_ids` swallows all errors silently

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/analyze/structural.py` — `_get_affected_ids()`
**Discovered:** Audit 2026-04-28

### Problem
```python
def _get_affected_ids(df, mask, id_col, limit=10):
    if not id_col or id_col not in df.columns: return []
    try: return df.loc[mask, id_col].head(limit).tolist()
    except: return []
```
The `except:` catches *anything*, including `KeyboardInterrupt` and `SystemExit`. More importantly, it returns `[]` for any failure, meaning a finding can claim "12 records affected" but list zero IDs. The user sees a problem flagged but no records they can investigate.

### Expected
Specific exception handling. If the lookup fails for a real reason (mask shape mismatch, etc.), log it and either fix the call site or surface the issue. An empty `record_ids` list when affected count is non-zero is itself a finding worth reporting.

### Suggested approach
1. Replace `except:` with specific exceptions (`KeyError`, `IndexError`, `ValueError`)
2. Log unexpected exceptions
3. Add a defensive assertion that if the count is non-zero, IDs should be non-empty (or explain why not)

### Acceptance criteria
- [ ] No bare `except` in this function
- [ ] Test covers the error paths
- [ ] Findings always have either zero count *or* non-empty IDs (or a documented reason)

### Related
- General code-health follow-up; not user-facing on its own but enables EXT-BUG-05

---

## EXT-BUG-05 — Findings show capped record-id samples without indicating they are samples

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/analyze/structural.py` (multiple checks), `src/kwb/analyze/quality_report.py`
**Discovered:** Audit 2026-04-28

### Problem
Throughout `structural.py`, `record_ids` is capped (e.g., `head(10)`, `head(5)`, `[:10]`, `[:20]`). The downstream `Finding.record_ids` is a *truncated sample*, but nothing in the data model says so. A finding "Column X has gaps in 3,400 rows" with `record_ids=[id_1, ..., id_10]` looks like 10 affected rows.

`quality_report._estimate_affected_count()` already partially compensates by preferring evidence count fields, but that fix is one-way: the field-name "record_ids" still implies "all of them." UI consumers and humans both fall into this trap.

### Expected
The data model distinguishes "affected_count" from "record_id_sample". The UI clearly labels "showing 10 of 3,400 affected records" with a "show more" affordance.

### Suggested approach
1. Rename `record_ids` to `record_id_sample` in `Finding` (or add `record_id_total: int` alongside)
2. Update all producers and consumers
3. UI: render the count and the sample distinctly, never the sample alone
4. Provide an API endpoint to fetch *all* affected IDs for a given finding when the user clicks "show more"

### Acceptance criteria
- [ ] Data model expresses "sample" semantics
- [ ] UI cannot accidentally display the sample as if it were the full list
- [ ] "Show more" affordance fetches the full list
- [ ] Tests assert the distinction

### Related
- EXT-BUG-04 (general affected-id reliability)
- CORE-ENH-01 (consolidate report types) — same area of the data model

---

## EXT-BUG-06 — Hardcoded subject column `subject_extract_original` makes `classify_subjects` GIUB-specific

**Type:** Bug / Hidden assumption
**Severity:** High
**Effort:** S
**Affected:** `src/kwb/analyze/semantic.py` — `classify_subjects()`
**Discovered:** Audit 2026-04-28

### Problem
```python
def classify_subjects(df, profile, provider, subject_column="subject_extract_original", ...):
```
The default column name is from the GIUB Glasdia dataset. For any other collection, the function would silently report a `SCHEMA_MISMATCH` finding and return — but the user never asked for this column; they asked to "classify subjects." From the user's perspective, the tool simply doesn't work on their data without explanation.

For the letters use case the relevant column might be `transcribed_text`, `inhalt`, or anything else. A curator without access to the source code cannot know what to pass.

### Expected
The function either accepts a list of candidate column names (and tries each), or the dashboard exposes a column picker before invocation — the user picks "the subject-bearing column" from a dropdown of their actual columns.

### Suggested approach
1. Remove the hardcoded default; require the column to be explicit
2. UI: add a column picker to the relevant dashboard tab, with a helpful description ("Which column contains the subject text?")
3. Optionally, auto-suggest based on column name heuristics
4. Document that this function is collection-agnostic

### Acceptance criteria
- [ ] No GIUB-specific column names in default arguments
- [ ] Dashboard prompts user for column selection
- [ ] Function works on letters, slides, and arbitrary CSVs without code changes

### Related
- EXT-ENH-03 (collection-agnostic dashboard)
- Strategic: precondition for letters use case

---

## EXT-BUG-07 — `parse_gnd_columns` hardcodes `named_entity_N` schema (max 11) without configurability

**Type:** Bug / Hidden assumption
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/enrich/gnd.py` — `parse_gnd_columns()`, `build_dictionary_from_gnd_csv()`, `flag_low_confidence()`
**Discovered:** Audit 2026-04-28

### Problem
The functions look for columns named exactly `named_entity_1` through `named_entity_11`, with sub-columns `_gnd_id`, `_gnd_preferredName`, `_gnd_konfidenz`, `_gnd_type`, `_gnd_alternativen`. This is the GIUB master schema. Any other GND-pre-enriched dataset (METS exports, Wikidata-mapped CSVs, etc.) is silently ignored — the function returns `[]` because no columns match.

A user with a perfectly valid GND-enriched dataset under a different naming convention sees "no GND matches found" with no explanation.

### Expected
The schema is configurable via a profile or auto-detected. If the user's dataset doesn't match the expected pattern, the system tells them so explicitly: "Expected columns matching `named_entity_*_gnd_id` not found. Found these candidate authority columns: [...]"

### Suggested approach
1. Define a "GND column schema" config (prefix, suffix patterns, max count)
2. Auto-detect on first dataset load: scan column names for `*_gnd_id` patterns
3. Surface the detected (or undetected) schema to the user
4. Allow override via UI or YAML

### Acceptance criteria
- [ ] No hardcoded column patterns in source
- [ ] Auto-detection covers at least the GIUB pattern and 1-2 common alternatives
- [ ] User sees a clear message when no GND columns are detected
- [ ] Override mechanism documented

### Related
- EXT-BUG-06 (same pattern of hidden GIUB-isms)
- Strategic: needed for any non-GIUB collection

---

## EXT-BUG-08 — `confidence: 0.8` hardcoded in `LobidGNDClient.search` regardless of actual match quality

**Type:** Bug / Misleading output
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/enrich/gnd.py` — `LobidGNDClient.search()`, `gnd_search()`
**Discovered:** Audit 2026-04-28

### Problem
```python
results.append(GNDMatch(
    ...
    confidence=0.8,  # lobid doesn't expose a confidence score
    source="lobid",
))
```
Every result from a Lobid search gets confidence 0.8, regardless of whether it was the only match, the third match, an exact name match, or a fuzzy hit. The number is meaningless but looks authoritative. A user looking at a curation report sees "GND match with 80% confidence" and trusts the number.

For low-quality matches (e.g., the 5th result), this is actively misleading. For high-quality matches (exact preferred-name match), it understates certainty.

### Expected
Either:
- (a) Drop the confidence number and surface the rank instead ("match rank 1 of 5")
- (b) Compute a heuristic confidence from term overlap, name-match exactness, type filter agreement
- (c) Expose Lobid's actual scoring data (the `_score` field in the JSON response is sometimes available)

### Suggested approach
1. Inspect Lobid responses for usable scoring signals
2. If none, replace `confidence` with `match_rank` (1-based position in result list) or compute a Levenshtein-based similarity
3. UI: never display a number called "confidence" that the system fabricated
4. Document the meaning of whatever number is shown

### Acceptance criteria
- [ ] No hardcoded confidence number for live API matches
- [ ] User-facing field has a clear semantic meaning
- [ ] Documentation explains the signal

### Related
- EXT-BUG-09 (confidence inconsistency across providers)
- EXT-ENH-05 (confidence semantics)

---

## EXT-BUG-09 — Confidence values mean different things in different modules; no documented scale

**Type:** Bug / Specification gap
**Severity:** High
**Effort:** L
**Affected:** Project-wide; visible in `analyze/ner.py`, `enrich/edtf.py`, `enrich/gnd.py`, `enrich/wikidata.py`, `analyze/llm_quality.py`
**Discovered:** Audit 2026-04-28

### Problem
A non-exhaustive list of "confidence" semantics in the codebase:
- `ner_spacy` → `0.6` (constant, source: SpaCy entity tag — but no calibration)
- `ner_llm` → LLM self-reported, 0.0–1.0
- `parse_confidence` (GND CSV) → comes from `"70%"` strings in source, divided by 100
- `LobidGNDClient.search` → `0.8` constant
- `LobidGNDClient.lookup_id` → `1.0` constant
- `WikidataResult` → `1.0` constant
- `EDTFResult.confidence` → varies by rule (rule-based) or LLM self-reported
- LLM quality module → LLM self-reported on a 0.0–1.0 scale

These numbers are mixed in tables, sorted, used as thresholds (`< threshold`, `< 0.5`), and shown to the user — but they are not on the same scale and don't measure the same thing. A user comparing "GND confidence 0.8" to "NER confidence 0.6" is comparing two unrelated numbers.

### Expected
A documented confidence model: either a uniform scale with definitions ("0.9+ = exact match by deterministic rule; 0.7–0.9 = LLM-confirmed; 0.5–0.7 = single-signal heuristic; < 0.5 = needs review"), or distinct typed fields (`rule_confidence`, `llm_confidence`, `match_rank`) that the UI never conflates.

### Suggested approach
1. Architectural decision: typed fields vs. uniform scale
2. Document the chosen scheme in `core/models.py` docstring or a `docs/CONFIDENCE.md`
3. Refactor producers to populate the new fields
4. Update consumers (UI, exports) to render them correctly
5. Migrate existing workspace JSON
6. Add a test that compares "what confidence really means" against the docs

### Acceptance criteria
- [ ] Confidence semantics documented in one place
- [ ] All producers conform
- [ ] UI renders confidence with its scale
- [ ] No mixed-meaning sort or threshold operations remain

### Related
- EXT-BUG-08 (Lobid hardcoded)
- CORE-ENH-03 (provenance) — same area of the data model
- Strategic: directly affects user trust in results

---

## EXT-BUG-10 — `_normalize_dates_llm` rebuilds original text via fragile inline expression

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/enrich/edtf.py` — `_normalize_dates_llm()`
**Discovered:** Audit 2026-04-28

### Problem
On LLM failure, the fallback tries to recover the original text:
```python
original=item["text"] if (item := next((x for x in items if x.get("record_id") == r.record_id), None)) else "",
```
This is an O(n) lookup per failed record (so O(n²) total for a fully failing batch), uses a walrus operator inside a ternary inside a constructor argument, and silently produces empty `original` if the lookup fails. A user looking at the failure list sees a row with empty original text and an empty EDTF — useless for debugging.

### Expected
Each item's original text is reliably attached to its result, regardless of success or failure. Code is readable.

### Suggested approach
1. Build an `id → text` lookup dict before the loop
2. Use it in both the success and failure branches
3. Make the function symmetric: every input record produces exactly one output record with `original` populated

### Acceptance criteria
- [ ] No O(n²) lookup
- [ ] Failed records carry their original text
- [ ] Code reads top-to-bottom without mental gymnastics

### Related
- EXT-BUG-01 (failure surfacing)

---

## EXT-BUG-11 — `MERGED` ReviewStatus referenced from `analyze/`-area code; `core/` audit found `MERGED` is a duplicate enum member

**Type:** Bug (cross-module)
**Severity:** Medium
**Effort:** S
**Affected:** Audit cross-reference
**Discovered:** Audit 2026-04-28

### Problem
The core/ audit found that `ReviewStatus` exists twice with different members. While reading `analyze/`, no usage of `MERGED` surfaced — strengthening the case that `MERGED` is dead. This is a confirming data point for `CORE-BUG-02`, not a separate issue.

### Expected
N/A — handled in CORE-BUG-02.

### Suggested approach
Reference this finding in CORE-BUG-02 when triaging.

### Related
- CORE-BUG-02

---

# Enhancements — User-centered

## EXT-ENH-01 — Every result needs a "where did this come from" panel the user can open

**Type:** Enhancement
**Severity:** High
**Effort:** L
**Affected:** All analyze and enrich modules; primarily UI
**Discovered:** Audit 2026-04-28

### Problem
A curator looking at "Berlin → Q64 (Wikidata)" cannot see *why* the system thinks it's Q64. Was it the only Wikidata result? Was it the top result of 5? What was the search query? Which model produced the entity in the first place? Without this trail, the curator either accepts the result blindly or rejects it blindly — neither is curation.

Currently, debussy stores some provenance (`source="hybrid"`, `model_source` on dictionary entries) but it is not consistently captured, not consistently shown, and not reachable from the result table without inspecting raw JSON.

### Expected
Every result row in the dashboard has an "ℹ" affordance that opens a panel with:
- Input that produced it (text, column, record id, raw cell value)
- Pipeline stages: structural-check → NER → GND-search → top-N candidates
- For each stage: model used, prompt version (if LLM), parameters, timestamp
- The candidates that *weren't* picked (and why)
- A link to the raw API response or LLM completion

### Suggested approach
1. Standardise a `ProvenanceTrail` data type (extends `Provenance` from CORE-ENH-03)
2. Each pipeline stage appends to the trail; the trail travels with the result
3. UI: expandable provenance panel per result row
4. Storage: keep the last N raw responses per run for diagnosability

### Acceptance criteria
- [ ] Every result has a non-empty provenance trail
- [ ] User can see all pipeline stages without leaving the dashboard
- [ ] Raw responses are inspectable (with redaction of sensitive fields if applicable)
- [ ] Trail survives serialisation round-trips

### Related
- CORE-ENH-03 (provenance fields)
- EXT-BUG-08 / EXT-BUG-09 (confidence semantics)
- Strategic: foundational for trust

---

## EXT-ENH-02 — Run history per dataset; users need to compare and re-run

**Type:** Enhancement
**Severity:** High
**Effort:** M
**Affected:** Workspace, all analyze modules, dashboard
**Discovered:** Audit 2026-04-28

### Problem
A curator runs NER, gets 247 entities. They tweak the system prompt, run again, get 312. Right now there is no run history — the second run *replaces* the first or gets merged into the entity list with no way to tell which entities came from which run. The user cannot answer "did my prompt change actually help?"

### Expected
Each run is a first-class object with: id, started/finished timestamps, model, prompt, parameters, completion summary, link to the produced facts. The dashboard shows a runs list per dataset. Diff view between runs ("31 entities new in run B vs A, 12 dropped, 204 unchanged"). Roll back to a previous run.

### Suggested approach
1. `Run` dataclass in workspace
2. Every analyze function takes a `run_id` and tags every produced fact with it
3. Dashboard: runs panel per dataset with diff and rollback
4. Export: include run metadata in CSV/JSONLD export

### Acceptance criteria
- [ ] Runs are first-class entities
- [ ] All produced facts carry their run_id
- [ ] Diff view works between any two runs
- [ ] Rollback restores a previous state non-destructively

### Related
- CORE-ENH-04 (fact store) — runs are a natural feature once facts are unified
- EXT-BUG-03 (sampling reproducibility)

---

## EXT-ENH-03 — Dashboard is technique-organised; users think in collection workflows

**Type:** Enhancement / UX redesign
**Severity:** High
**Effort:** L
**Affected:** Dashboard layout, route organisation
**Discovered:** Audit 2026-04-28 (consistent with prior FK-strategy discussion)

### Problem
Tabs are: Daten, NER, Datierung, KI-Konfig, Export, Katalog. This is the technique view: "what tool do I want to run." Curators don't think this way. They think:

- "I just got this collection, what's its current state?"
- "What is missing for an MDS-compliant export?"
- "I want to flag colonial terminology — which tools help and on which records?"
- "Where am I in the workflow for this bestand?"

The current layout makes them translate their problem into "which technique tab do I open" — a translation they shouldn't have to do.

### Expected
Default home is **Sammlungsstatus**: a per-collection dashboard showing what is known, what is missing, what is reviewable. From there, every action is a *task*, not a technique. "Lücken im Feld 'Ort' schliessen" → the system picks NER + GND, runs it, returns reviewable results. Technique tabs remain as expert mode.

### Suggested approach
1. Add a `CollectionView` that aggregates all extant facts/findings/reviews per dataset
2. Surface a "Was fehlt?" panel listing high-impact gaps
3. Each gap-card has a one-click "Bearbeiten" action that maps to the right technique chain
4. Move the technique tabs under "Erweitert" / "Expert"
5. Migration: keep both views available initially, default to the new one

### Acceptance criteria
- [ ] Sammlungsstatus tab exists and shows real per-collection data
- [ ] At least 5 task-cards map to existing techniques without code changes to the techniques
- [ ] Curator user-test: novice user can fill a gap without opening a technique tab
- [ ] Technique tabs remain accessible under Expert mode

### Related
- EXT-ENH-02 (run history)
- CORE-ENH-06 (FK-gap tasks)
- Strategic: directly the user-centered move

---

## EXT-ENH-04 — Model selection lacks guidance; users don't know which model to pick for which task

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** Dashboard "KI-Konfiguration" tab, `ai/provider.py` consumers
**Discovered:** Audit 2026-04-28

### Problem
The "KI-Konfiguration" tab lets the user pick any GPUStack model from a dropdown. There is no information about:
- Which models are good at JSON output (critical for NER, EDTF-fallback, LLM-quality)
- Which support German (relevant for almost everything)
- Which support vision (only some models do)
- Token / context limits (long records may exceed limits silently)
- Cost / speed tradeoffs in batch mode

A user picks a model that doesn't reliably emit JSON, then sees EXT-BUG-02 trigger — and has no idea why.

### Expected
Each task in the UI shows recommended models for that task. The model picker shows capability badges (text / vision / JSON-reliable / German). Selecting an unsuitable model shows a warning before the run.

### Suggested approach
1. Define a `ModelProfile` schema with capability flags
2. Curate a small list of profiles for the GPUStack models the user has
3. Per-task: declare required capabilities; filter the model picker accordingly
4. Show warnings if user overrides the recommendation

### Acceptance criteria
- [ ] Model profiles defined for the deployed GPUStack models
- [ ] Tasks declare requirements
- [ ] UI guides the user to suitable models
- [ ] Override is possible but warned

### Related
- EXT-BUG-02 (parse failures)
- EXT-ENH-08 (prompt versioning)

---

## EXT-ENH-05 — Confidence and severity need user-facing explanations; raw numbers and enum values are inscrutable

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** Dashboard, all result renderers
**Discovered:** Audit 2026-04-28

### Problem
Severities show as `critical / warning / info` and confidences as `0.84`. A curator without a stats background asks reasonable questions: "What does 0.84 mean — is that good?" "Why is this critical and that one warning — what should I do first?" The system gives no answer.

### Expected
Every confidence and severity has a hover/tooltip explanation. Confidence is presented with its scale ("0.84 — high confidence; LLM-self-reported"). Severity is presented with the recommended action ("Critical: must be resolved before MDS-compliant export").

### Suggested approach
1. Define one source of truth for severity meanings and confidence interpretations
2. UI: tooltips on every severity badge and confidence number
3. Help panel that explains the scale once
4. Distinguish "system confidence" from "reviewer confirmed" visually

### Acceptance criteria
- [ ] Tooltips present on every severity and confidence display
- [ ] Help panel exists and is reachable from any tab
- [ ] Reviewer-confirmed status is visually distinct
- [ ] Documentation matches the code

### Related
- EXT-BUG-09 (confidence semantics)

---

## EXT-ENH-06 — `scan_problematic_terms` mixes 10 columns into one prompt; single colonial term hides among neutral ones

**Type:** Enhancement / Effectiveness
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/analyze/ner.py` — `scan_problematic_terms()`
**Discovered:** Audit 2026-04-28

### Problem
The function joins all string-column values per record with `"; "`, truncates to 500 chars, and asks the LLM to find problematic terms. For records with many fields, problematic terms in one column are diluted by neutral text from nine others, and the 500-char cap may even cut them off entirely. A single colonial-era term in a richly populated record may be missed.

For a curator running this scan, "missed terms" are the worst possible failure mode — they think the data is clean.

### Expected
Per-column scanning, with results grouped by column. The user sees "Column X has 4 problematic terms; column Y has 0; column Z has 1." Recall improves; the 500-char issue disappears.

### Suggested approach
1. Loop over columns, one prompt per (record, column) pair
2. Aggregate at the end
3. Optional: ask the LLM only about the columns the user marks as "narrative text" via the column picker (cheaper)
4. Document the recall vs. cost tradeoff

### Acceptance criteria
- [ ] Scan operates per-column
- [ ] Result groups by column
- [ ] Test on a synthetic record with one colonial term among 9 neutral fields shows the term is found
- [ ] Documentation reflects the change

### Related
- EXT-BUG-06 (column hardcoding)
- EXT-BUG-01 (completion rate — applies here too)

---

## EXT-ENH-07 — `_FIELD_SEMANTICS` dictionary in `llm_quality.py` is monolingual, English/German-mixed, and not user-extensible

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/analyze/llm_quality.py`
**Discovered:** Audit 2026-04-28

### Problem
`_FIELD_SEMANTICS` hardcodes ~30 column-name → German-description mappings (`"creator": "Person oder Organisation, die das Objekt erschaffen hat"`). This is great as a default but:
- The user cannot extend it from the UI; they would need to edit source
- No guidance for arbitrary GLAM column names from non-Dublin-Core schemas
- No way to override for collection-specific semantics ("subject_general" might mean different things for different bestände)
- Mixes English column-name keys with German values — fine here, but inconsistent with the rest of the system

### Expected
Field semantics are user-editable per collection profile. A curator opens "Spaltensemantik" and edits the meanings the LLM uses for cell-quality checks on their dataset. Defaults are a starting point, not a ceiling.

### Suggested approach
1. Move `_FIELD_SEMANTICS` to a YAML asset, loaded at startup
2. Allow a per-workspace override file (`workspace/field_semantics.yaml`)
3. UI: an editor for semantics, with the default values pre-filled
4. Each LLM run records which semantics were active (provenance)

### Acceptance criteria
- [ ] Semantics editable without source changes
- [ ] Workspace-specific overrides supported
- [ ] UI editor exists
- [ ] Run provenance captures the semantics used

### Related
- EXT-ENH-01 (provenance)
- EXT-BUG-06 (collection-agnosticism)

---

## EXT-ENH-08 — Prompts have no visible version; users cannot tell which prompt produced an old result

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/ai/prompts.py`, every analyze module that uses LLM
**Discovered:** Audit 2026-04-28

### Problem
Prompt strings (`SYSTEM_NER`, `SYSTEM_EDTF`, etc.) are constants. When a developer iterates on a prompt, every prior result becomes ambiguous: "did this entity come from the v1 prompt or the v2 prompt?" The user cannot tell. This is especially bad for cross-run diff (EXT-ENH-02).

### Expected
Each prompt is versioned. Every produced fact records the prompt version. The dashboard shows the version on each result. Old prompts are archived, not overwritten.

### Suggested approach
1. Convert prompts from constants to `Prompt(id, version, system, user_template, last_modified)` objects
2. Store in `prompts.yaml` per task
3. Bumping the version is a deliberate developer action; the runner uses the current version
4. Each fact carries `prompt_id` + `prompt_version`
5. UI: prompt-version badge on results

### Acceptance criteria
- [ ] All prompts versioned
- [ ] Facts carry prompt version
- [ ] Old prompts retained for re-rendering history
- [ ] UI displays version

### Related
- EXT-ENH-01 (provenance)
- EXT-ENH-02 (run history)
- CORE-ENH-03 (provenance fields)

---

## EXT-ENH-09 — `parse_confidence("70%")` interpreted as 0.70, but no UI affordance shows users the conversion

**Type:** Enhancement / Documentation
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/enrich/gnd.py` — `parse_confidence()`
**Discovered:** Audit 2026-04-28

### Problem
GIUB master CSV has confidences as `"70%"` strings. `parse_confidence` correctly converts to `0.70`. But: a curator looking at the raw CSV sees `70%`, then in the dashboard sees `0.70`, then later somewhere else maybe sees `70` (integer). Three representations, one quantity, no explanation.

### Expected
The dashboard either presents confidence in the same form as the source (`70%`) or, if it normalises, makes the conversion explicit on hover.

### Suggested approach
1. Decide: percent or decimal as canonical UI form
2. Apply consistently across all confidence renders
3. Tooltip that explains the normalisation (relevant when source data uses different units)

### Acceptance criteria
- [ ] One canonical UI representation for confidence
- [ ] Conversion documented in source-data tooltips

### Related
- EXT-BUG-09 (confidence semantics — broader)

---

## EXT-ENH-10 — `flag_low_confidence` threshold of 0.75 is hardcoded; users cannot adjust per dataset

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/enrich/gnd.py` — `flag_low_confidence()`, callers
**Discovered:** Audit 2026-04-28

### Problem
Default `threshold=0.75`. Users with cleaner data want stricter (0.9); users with messier data may need looser (0.6) to surface anything actionable. The threshold is not exposed in the UI; users cannot recalibrate without source changes.

### Expected
Threshold is a UI slider per dataset, with a live preview ("flagging at 0.75 → 312 records, at 0.9 → 1,047 records"). Default is sensible but adjustable.

### Suggested approach
1. Surface the threshold in the GUI as a slider
2. Live preview of the affected count
3. Persist the chosen threshold per workspace

### Acceptance criteria
- [ ] Threshold is UI-controlled
- [ ] Live preview works
- [ ] Persisted per workspace

### Related
- EXT-BUG-09 (confidence semantics)

---

## EXT-ENH-11 — `geonames_search` defaults to `username="demo"` which silently rate-limits or fails

**Type:** Enhancement / Onboarding
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/enrich/geonames.py`
**Discovered:** Audit 2026-04-28

### Problem
The GeoNames API requires a free username. The default is `"demo"`, which is rate-limited (and sometimes blocked). A user without a configured `KWB_GEONAMES_USERNAME` will get a `WARNING` log message but no UI feedback — they see "no GeoNames matches found" and conclude the data is bad.

### Expected
- On first use without credentials, the dashboard shows: "GeoNames requires a free username. Sign up here, then enter it in Konfiguration."
- The link to GeoNames signup is in-product
- Status "no credentials configured" is visible in the dashboard, not buried in logs

### Suggested approach
1. Detect missing/default credentials at the route level
2. Return a structured `auth_required` response with signup link
3. Dashboard handles this case explicitly (banner, not silent failure)
4. Add a "GeoNames-Status" indicator to the KI-Konfiguration tab

### Acceptance criteria
- [ ] User without credentials sees a clear setup banner
- [ ] Direct link to signup
- [ ] Dashboard reflects credential status
- [ ] No silent rate-limit failures

### Related
- EXT-BUG-01 (silent failures generally)

---

## EXT-ENH-12 — Wikidata SPARQL queries are German-locked via hardcoded `lang="de"` defaults; multilingual collections suffer

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/enrich/wikidata.py`
**Discovered:** Audit 2026-04-28

### Problem
`wikidata_search(term, ..., lang="de", ...)`. For collections with English, French, Italian, or other non-German content, this biases results: a French-language entity like "Université de Lausanne" might still resolve, but the labels and descriptions returned are German variants if available, English otherwise — never the original-language form. The user reviewing matches sees German labels for French content, which feels wrong and slows review.

### Expected
The language is per-collection, set at workspace level. Multilingual collections allow per-record language detection or override.

### Suggested approach
1. Move language to workspace settings
2. Optionally: detect language per record and pass it through
3. UI: language preference visible in Konfiguration

### Acceptance criteria
- [ ] Language is workspace-configurable
- [ ] No `de` hardcoded as default in search functions
- [ ] Multilingual test case covered

### Related
- EXT-BUG-06 / EXT-BUG-07 (collection-agnosticism)

---

## EXT-ENH-13 — `EDTF` rule patterns not yet audited; full coverage matrix needed

**Type:** Enhancement / Audit follow-up
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/normalize/edtf.py` (not yet seen) and `src/kwb/enrich/edtf.py`
**Discovered:** Audit 2026-04-28

### Problem
This audit deliberately did not read `kwb.normalize.edtf` because the file was not provided. EDTF is the most user-facing normalization in the tool — date conversion success rate directly determines a curator's perception of the system's competence on their data. A pattern that misses `o.J.` (no date) or `[ca. 1920]` (uncertain in brackets) is invisible to test suites but obvious to a curator on real data.

### Expected
A pattern coverage matrix exists: for each known German GLAM date convention, is there a rule, and does it produce the right EDTF? Patterns the audit recommends checking: `o.J.`, `o.D.`, `[1920]`, `[ca. 1920]`, `1920?`, `<1920`, `>1920`, `1920–25` (en-dash), `1920–1925` (range), `Ende 19. Jh.`, `Anfang 1920er`, `1. Hälfte 19. Jh.`, `19./20. Jh.`, `vor/nach Christus`, mixed-language tokens.

### Suggested approach
1. Read `normalize/edtf.py`
2. Build a coverage table: pattern → rule? → result?
3. Add tests for the gaps
4. Document the coverage so users know what is supported

### Acceptance criteria
- [ ] Coverage matrix produced
- [ ] Gaps logged as separate small issues or addressed in this one
- [ ] Documentation reflects supported patterns
- [ ] User-facing help shows examples

### Related
- This is itself an audit-followup; will likely produce 5–15 small bugs

---

## EXT-ENH-14 — Tests assert structural shape but rarely assert output correctness on realistic data

**Type:** Enhancement / Testing strategy
**Severity:** Medium
**Effort:** L
**Affected:** All `tests/` related to `analyze/` and `enrich/`
**Discovered:** Audit 2026-04-28 (deduced from test counts in funktionskatalog vs. observed code patterns)

### Problem
780 tests pass. Yet bugs of the form "function silently returns []" (EXT-BUG-04, EXT-BUG-08) and "hardcoded column makes function unusable on other datasets" (EXT-BUG-06, EXT-BUG-07) are not caught. The shape-assertion pattern (does the result have the right keys, the right types, the right counts) is well-covered. The semantic pattern (is the *content* correct on plausible inputs) is not.

This is the gap your earlier remark — "not all features had production-level smoke tests" — points at concretely.

### Expected
Each technique has at least one **golden dataset** test: a small, realistic, hand-curated input with hand-curated expected outputs. The test asserts on the content, not just the shape. Failures produce a meaningful diff for the developer.

### Suggested approach
1. Define a golden-test pattern (input fixture, expected output fixture, diff-friendly comparison)
2. Add one golden test per major technique (NER, EDTF, GND parse, structural checks, LLM-quality cell-level)
3. Use realistic but small data — 5–20 records per fixture
4. Document the pattern so future techniques follow it

### Acceptance criteria
- [ ] At least one golden test per major technique
- [ ] Golden fixtures live under `tests/golden/`
- [ ] Failures produce readable diffs
- [ ] Pattern documented for contributors

### Related
- All EXT-BUG-* (each is a candidate for a golden-test addition)

---

# Summary

| ID | Type | Severity | Effort | Title (short) |
|---|---|---|---|---|
| EXT-BUG-01 | Bug | High | M | Silent batch failures, no completion rate visible |
| EXT-BUG-02 | Bug | High | S | LLM JSON parse failures dropped silently |
| EXT-BUG-03 | Bug / UX | High | M | Sampling reproducibility / visibility |
| EXT-BUG-04 | Bug | Medium | S | Bare `except:` in `_get_affected_ids` |
| EXT-BUG-05 | Bug | Medium | S | Capped record-id samples not labelled as samples |
| EXT-BUG-06 | Bug | High | S | Hardcoded subject column in semantic.py |
| EXT-BUG-07 | Bug | High | M | Hardcoded GND column schema |
| EXT-BUG-08 | Bug | High | M | Lobid hardcoded `confidence: 0.8` |
| EXT-BUG-09 | Bug | High | L | Confidence values mean different things |
| EXT-BUG-10 | Bug | Medium | S | EDTF LLM fallback fragile O(n²) lookup |
| EXT-BUG-11 | Bug | — | — | Cross-ref to CORE-BUG-02; not separate |
| EXT-ENH-01 | Enhancement | High | L | Provenance trail panel |
| EXT-ENH-02 | Enhancement | High | M | Run history + diff |
| EXT-ENH-03 | Enhancement | High | L | Sammlungsstatus as default tab |
| EXT-ENH-04 | Enhancement | Medium | M | Model selection guidance |
| EXT-ENH-05 | Enhancement | Medium | S | Severity / confidence tooltips |
| EXT-ENH-06 | Enhancement | Medium | M | Per-column problematic-term scan |
| EXT-ENH-07 | Enhancement | Medium | M | User-extensible field semantics |
| EXT-ENH-08 | Enhancement | Medium | M | Prompt versioning |
| EXT-ENH-09 | Enhancement | Low | S | Confidence display unit consistency |
| EXT-ENH-10 | Enhancement | Medium | S | GND threshold as UI slider |
| EXT-ENH-11 | Enhancement | Medium | S | GeoNames credentials onboarding |
| EXT-ENH-12 | Enhancement | Medium | S | Wikidata language hardcoded |
| EXT-ENH-13 | Enhancement | Medium | M | EDTF pattern coverage audit |
| EXT-ENH-14 | Enhancement | Medium | L | Golden tests for techniques |

## Recommended sequencing

**Phase A — Stop misleading users (S/M effort, immediate trust gain):**
EXT-BUG-01, EXT-BUG-02, EXT-BUG-04, EXT-BUG-05, EXT-BUG-08, EXT-BUG-10. About 1 week. Curators stop seeing fake-precise numbers and fake-complete lists.

**Phase B — Make the tool collection-agnostic (preconditions for letters):**
EXT-BUG-06, EXT-BUG-07, EXT-ENH-12. About 1 week. After this, debussy stops silently breaking on non-GIUB inputs.

**Phase C — Confidence semantics (cross-cutting):**
EXT-BUG-09, EXT-ENH-05, EXT-ENH-09. About 1 week. Single coherent confidence story.

**Phase D — User-centered redesign:**
EXT-ENH-03, EXT-ENH-01, EXT-ENH-02, EXT-ENH-08. About 3–4 weeks. The actual UX shift to outcomes-first.

**Phase E — Quality and onboarding:**
EXT-ENH-04, EXT-ENH-06, EXT-ENH-07, EXT-ENH-10, EXT-ENH-11, EXT-ENH-13, EXT-ENH-14. As capacity allows.

**Phase F — Ongoing audit:**
EXT-BUG-03 (sampling) belongs in Phase A semantically but takes M effort and benefits from EXT-ENH-02 being done first; reasonable to do alongside Phase D.

## Cross-references with previous audit

- EXT-BUG-09 (confidence) overlaps with CORE-ENH-03 (provenance) — both touch the same data shape; resolve together
- EXT-ENH-01 (provenance trail) is the user-facing surface of CORE-ENH-03 (provenance fields)
- EXT-ENH-03 (Sammlungsstatus) overlaps with CORE-ENH-06 (FK-gap tasks) — same UX move, different motivation; the implementations should converge
- EXT-BUG-11 confirms CORE-BUG-02 (`MERGED` is dead) — note in CORE-BUG-02 triage

## Files not yet audited

- `src/kwb/normalize/edtf.py` (referenced; EDTF patterns)
- `src/kwb/ai/` (provider, batch, prompts, mock)
- `src/kwb/ingest/` (loaders)
- `src/kwb/api/` (routes, dashboard)
- `tests/` (sample audit recommended for golden-test gap, not full audit)

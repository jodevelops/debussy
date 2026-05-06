# Cluster 1 — "Silent Failures Made Visible" — Dependency Map & Strategy

**Total issues in M1:** 19 issues (11 original + 8 from express audit)
**Total effort:** ~3–4 weeks (mostly S, some M, 2× L projects embedded in CORE dependencies)
**Goal:** Every batch operation surfaces completion rate + failure summary; users can no longer be misled.

---

## Definition: Silent Failures in Debussy

A **silent failure** occurs when:
1. A record/batch fails to process completely (data loss, parse error, API rejection, etc.)
2. The system completes without raising an error or warning
3. The curator has no way to know which records failed, how many failed, or why
4. The export/report contains partial or incorrect data without acknowledging the loss

**Examples:**
- NER batch processes 100 records, 10 fail due to API timeout → user sees 90 results, assumes all 100 processed
- XML import skips repeated `<subject>` elements due to dict overwrite → user loses data, unaware
- Image ingestion silently falls back to JPEG when PNG MIME is wrong → curator doesn't know which images are degraded
- Goobi export auto-adds `CatalogIDDigital` without showing the curator → unexpected mapping in file

**Visibility Cure:**
- Explicit completion summary: "87/100 records processed, 13 errors (details: [link])"
- Structured error log with affected record IDs and reasons
- Optional "retry failed only" flow to recover
- Preview before export showing what will/won't be included

---

## The 19 Issues in Cluster 1

### **Core/Infrastructure Foundation** (must do first)

| ID | Type | Effort | Title | Notes |
|---|---|---|---|---|
| **EXT-BUG-04** | Bug | S | Bare `except` in `_get_affected_ids` | Infrastructure for the others; quick win |
| **AI-BUG-01** | Bug | S | Broad `Exception` catch in `process_batch` | Clarify what counts as "failure" |
| **AI-BUG-02** | Bug | S | `BatchReport` lacks task/prompt/model metadata | Gates provenance-correct reporting |

### **Data Model / Structural Changes** (do after infrastructure)

| ID | Type | Effort | Title | Notes |
|---|---|---|---|---|
| **CORE-BUG-01** | Bug | S | Duplicate `image_review_stats()` method | Enum discipline; unblock image analysis |
| **CORE-BUG-02** | Bug | M | Two `ReviewStatus` enums | Type safety; blocks workspace model |
| **CORE-ENH-03** | Enhancement | M | Unified `Provenance` dataclass | Cross-listed Cluster 2; enables all reporting |
| **ING-BUG-09** | Bug | M | XML loses repeated MODS structures | Data loss bug; must be visible in completion report |

### **The Headline Deliverables** (the UX that matters)

| ID | Type | Effort | Title | Notes |
|---|---|---|---|---|
| **EXT-BUG-01** | Bug | M | Batch sampling silently drops records | **Primary deliverable:** completion rate + failure summary banner |
| **EXT-BUG-02** | Bug | S | JSON parse failures dropped silently | Feeds into EXT-BUG-01's completion summary |
| **EXT-BUG-05** | Bug | S | Findings show capped samples without labeling | Related to completion-rate visibility |

### **Ingest Layer — Silent Error Swallowing** (parallel with extraction, same UX pattern)

| ID | Type | Effort | Title | Notes |
|---|---|---|---|---|
| **ING-BUG-05** | Bug | S | Bare `except` in image dim extraction | Silent failure → should be logged |
| **ING-BUG-06** | Bug | S | MIME mismatch in image scan, silent | Silent failure → diagnostic message |
| **ING-BUG-07** | Bug | S | PDF pypdf fallback misleading | Silent fallback → explicit in report |
| **ING-BUG-08** | Bug | S | XML loose namespace fallback | Silent fallback → explicit in report |

### **Express Audit Additions** (export/report layer)

| ID | Type | Effort | Title | Notes |
|---|---|---|---|---|
| **EXP-BUG-01** | Bug | M | Two batch-export functions emit different XML roots | Export incompatibility; affects curators |
| **EXP-BUG-02** | Bug | S | Silent auto-add of CatalogIDDigital mapping | Cross-listed Cluster 1+5; silent mutation |
| **EXP-BUG-03** | Bug | S | JSON-LD mentions/contentLocation overwritten by NER | Data loss in export |
| **EXP-BUG-04** | Bug | M | Sanitised record-id filenames can collide → data overwrite | **High risk:** silent data loss |
| **EXP-BUG-05** | Bug | S | JSON-LD sameAs overwritten when both gnd+wikidata present | Data loss in export |
| **EXP-BUG-06** | Bug | M | JSON-LD base_url defaults to example.org | **Publishing footgun** |
| **EXP-BUG-08** | Bug | S | CSV gnd_ids only from ner_persons, other entities dropped | Silent data loss |
| **RPT-BUG-01** | Bug | S | Findings capped at 5 with "+N more", no path to see rest | UI limitation; affects curators |

---

## Dependency Graph

```
┌─────────────────────────────────────────────────────┐
│ PHASE 1: Stabilize Exception Handling (1–2 days)  │
├─────────────────────────────────────────────────────┤
│  EXT-BUG-04  →  Bare except cleanup               │
│  AI-BUG-01   →  Exception handling clarity        │
│  AI-BUG-02   →  BatchReport provenance           │
└────────────────────────┬────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 2: Core Enum Discipline (2–3 days)          │
├─────────────────────────────────────────────────────┤
│  CORE-BUG-01 →  Fix image_review_stats duplication│
│  CORE-BUG-02 →  Unify ReviewStatus enums        │
└────────────────────────┬────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 3: Headline Deliverable (3–4 days)          │
├─────────────────────────────────────────────────────┤
│  CORE-ENH-03 →  Unified Provenance               │
│                                                   │
│  EXT-BUG-01  →  **MAIN: Completion rate + UI**   │
│  EXT-BUG-02  →  Parse failure capture             │
│  EXT-BUG-05  →  Sample-semantics labeling        │
│  RPT-BUG-01  →  Findings pagination               │
└────────────────────────┬────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 4: Ingest/Export Alignment (3–4 days)      │
├─────────────────────────────────────────────────────┤
│  ING-BUG-05/06/07/08  →  Explicit logging        │
│  EXP-BUG-01/03/04/05/06/08  →  Export correctness│
│  EXP-BUG-02  →  Silent mutation cleanup          │
└─────────────────────────────────────────────────────┘
```

---

## Suggested Grouping for Claude Code / Branch Strategy

### **Group 1: Exception Handling Foundation** (1 branch, ~1 day)
**Branch:** `fix/silent-failures-exception-handling`

**Issues:**
- EXT-BUG-04 (bare except in structural.py)
- AI-BUG-01 (broad Exception in batch.py)
- AI-BUG-02 (BatchReport provenance)

**Implementation Details:**
- Replace bare `except:` with `except (SpecificError1, SpecificError2):`
- Add `logger.exception()` calls to capture stack traces
- Extend `BatchReport` with `prompt_fn_used`, `model_used`, `provider_used` fields
- Create `FailureRecord` dataclass: `(record_id, operation, error_message, exception_type, timestamp)`

**Testing:**
- Unit test: each exception type is caught and logged
- Unit test: BatchReport can be serialized/deserialized with metadata
- Integration test: run batch with simulated provider timeout, assert failure is captured

**Manual Test:**
- Start API with intentionally broken provider config
- Run NER batch on 10 records
- Verify BatchReport shows 10 failures with error messages
- Verify dashboard displays "0/10 processed, 10 errors (details)"

**Acceptance Criteria:**
- [ ] No bare `except:` statements remain in batch code paths
- [ ] All exceptions include `logger.exception()` with context
- [ ] `BatchReport` includes full provenance (prompt, model, provider)
- [ ] `FailureRecord` list is populated for each failed record
- [ ] Test suite passes; no regressions in exception handling

---

### **Group 2: Core Model Fixes** (1 branch, ~2 days)
**Branch:** `fix/core-enum-discipline`

**Issues:**
- CORE-BUG-01 (duplicate image_review_stats)
- CORE-BUG-02 (ReviewStatus unification)

**Implementation Details:**
- Find and delete the second `image_review_stats()` method (or consolidate logic)
- Audit all ReviewStatus usage across `core/`, `analyze/`, `api/`
- Create single canonical enum in `core/models.py`:
  ```python
  class ReviewStatus(str, Enum):
      PENDING = "pending"
      APPROVED = "approved"
      FLAGGED = "flagged"
      MERGED = "merged"
  ```
- Replace all imports of the old enum with this canonical one
- Run type checker (mypy) to catch any mismatches

**Testing:**
- Unit test: both enum values are identical
- Unit test: image_review_stats returns dict with enum keys, not string keys
- Type check: mypy passes with strict mode on all affected modules

**Manual Test:**
- Load a workspace with ReviewStatus-tagged records
- Verify dashboard displays correct status colors
- Verify API returns enum values consistently

**Acceptance Criteria:**
- [ ] Only one ReviewStatus enum exists in codebase
- [ ] image_review_stats appears only once in core/
- [ ] All imports point to canonical enum
- [ ] mypy passes on `src/kwb/core/`, `src/kwb/analyze/`, `src/kwb/api/`
- [ ] No string comparisons with ReviewStatus; always use enum

---

### **Group 3: The Headline Deliverable** (1 branch, ~3–4 days)
**Branch:** `feat/silent-failures-completion-visible`

**Issues:**
- CORE-ENH-03 (Unified Provenance — can be a submodule, ~1 day)
- EXT-BUG-01 (Completion rate + UI banner — 2–3 days)
- EXT-BUG-02 (Parse failure capture — 1 day, folded into EXT-BUG-01)
- EXT-BUG-05 (Sample labeling — 1 day)
- RPT-BUG-01 (Findings pagination — 1 day)

**Implementation Details:**

**CORE-ENH-03 Provenance:**
```python
@dataclass
class Provenance:
    source_operation: str  # "ner", "vision", "semantic", "enrich:gnd", etc.
    prompt_fn_used: str | None  # e.g., "prompt_ner_extract"
    model_name: str | None  # "gpt-4o", "llama3", "ollama:mistral", etc.
    provider_name: str | None  # "gpustack", "openai", "ollama"
    timestamp: datetime
    input_hash: str | None  # SHA256 of input for reproducibility
    
    def to_dict(self) -> dict:
        return asdict(self)
```

**EXT-BUG-01 Completion Summary:**
- Add `CompletionSummary` dataclass to NERResult, LlmQualityReport, SemanticAnalysis:
  ```python
  @dataclass
  class CompletionSummary:
      total_records: int
      processed_records: int
      failed_records: int
      errors: list[FailureRecord]
      completion_rate: float = field(init=False)
      
      def __post_init__(self):
          self.completion_rate = self.processed_records / self.total_records if self.total_records > 0 else 1.0
  ```
- Expose in API: `GET /api/batch/{batch_id}/summary` returns `CompletionSummary`
- Dashboard banner:
  ```
  ┌─────────────────────────────────┐
  │ ⚠️  87/100 records processed     │
  │ 13 errors. [View] [Retry failed] │
  └─────────────────────────────────┘
  ```
  - Red if < 80%, amber if < 95%, green if 100%
  - [View] opens modal with error list: record_id, operation, reason
  - [Retry failed] creates new batch with only failed records

**EXT-BUG-02 & EXT-BUG-05 (folded):**
- Ensure JSON parse failures are captured in `FailureRecord`
- Label capped samples in findings: "Showing 5 of 87. [View all]"

**RPT-BUG-01 (Findings Pagination):**
- Render first 5 records by default
- Add `[+N more]` link → modal or separate page listing all affected records
- Optionally export as CSV: `findings_affected_records.csv`

**Testing:**
- Unit test: CompletionSummary calculation is accurate
- Unit test: Provenance dataclass serialization
- Integration test: run batch with 10 records, 3 failures, assert CompletionSummary shows 7/10
- E2E test: load GIUB slides, run NER with simulated failures, verify banner renders, [Retry failed] works
- Manual test: Dashboard displays correct completion banner with interactive elements

**Acceptance Criteria:**
- [ ] Provenance captured for every operation (NER, vision, semantic, etc.)
- [ ] CompletionSummary exposed in API for every batch operation
- [ ] Dashboard banner renders with correct color coding
- [ ] [Retry failed] creates a new batch with failed records only
- [ ] Findings UI shows "[+N more]" with path to full list
- [ ] All Cluster 1 errors are logged and accessible
- [ ] E2E test passes: batch with failures → banner displays → retry works

---

### **Group 4: Ingest Silent Failures** (1 branch, ~1–2 days)
**Branch:** `fix/ingest-silent-failures-visible`

**Issues:**
- ING-BUG-05 (bare except → logging)
- ING-BUG-06 (MIME mismatch → diagnostic)
- ING-BUG-07 (PDF fallback → explicit)
- ING-BUG-08 (XML namespace → explicit)
- ING-BUG-09 (XML data loss → logged)

**Implementation Details:**
- Each silent failure becomes a logged warning + entry in `IngestReport.failures`
- Create `IngestReport` with same `CompletionSummary` pattern as Group 3
- PDF/XML fallbacks are logged as "degradation": "PDF pypdf fallback used (original parse failed)"
- All MIME mismatches logged with reason: "Expected application/pdf, got image/jpeg"

**Testing:**
- Unit test: each failure type is captured in fixture
- Integration test: ingest folder with mixed valid/invalid files, assert report is accurate
- Manual test: ingest GIUB slides with some missing images, verify ingest report shows degradations

**Acceptance Criteria:**
- [ ] No silent exceptions in image ingestion
- [ ] MIME mismatches logged with affected image paths
- [ ] PDF fallbacks recorded as degradations
- [ ] XML data loss logged with affected record IDs
- [ ] IngestReport includes CompletionSummary
- [ ] Dashboard displays ingest completion same as extract completion

---

### **Group 5: Export Correctness & Stability** (1 branch, ~2–3 days)
**Branch:** `fix/export-correctness`

**Issues:**
- EXP-BUG-01 (XML root divergence)
- EXP-BUG-04 (filename collision → data loss)
- EXP-BUG-06 (base_url publishing footgun)
- EXP-BUG-03/05/08 (data loss bugs)
- EXP-BUG-02 (silent mapping auto-add)

**Implementation Details:**

**EXP-BUG-01 (XML Root):**
- Choose canonical root: `<goobi-import-batch>` (likely correct for Goobi)
- Rename `dataframe_to_goobi_xml` → `dataframe_to_goobi_import_batch_xml` (clarify intent)
- Both `export_goobi_batch` and renamed function call shared `_render_batch_xml()` function
- Golden-file test: assert both produce identical XML for same input

**EXP-BUG-04 (Filename Collision):**
```python
safe_ids = {}
for record_id in batch['record_id']:
    safe = re.sub(r'[^\w\-]', '_', str(record_id))
    if safe in safe_ids:
        raise ExportError(
            f"Filename collision: '{record_id}' and '{safe_ids[safe]}' "
            f"both sanitise to '{safe}.xml'"
        )
    safe_ids[safe] = record_id
```

**EXP-BUG-06 (base_url):**
- Add `Workspace.base_url: str | None`
- Make it required for JSON-LD export; raise if unset:
  ```python
  if not workspace.base_url or "example.org" in workspace.base_url:
      raise ExportError(
          "JSON-LD base_url must be set and must not be a placeholder. "
          "Set workspace.base_url to your institution's domain."
      )
  ```

**EXP-BUG-03/05/08 (Data Loss):**
- Convert `mentions`, `contentLocation`, `sameAs` to always-lists
- Append rather than overwrite
- Ensure all entity types (persons, places, orgs) contribute to export, not just persons

**EXP-BUG-02 (Silent Mutation):**
- Remove auto-add of `CatalogIDDigital`
- Require curator to map it explicitly
- Raise clear error if missing: "CatalogIDDigital mapping is required for Goobi export. Configure it in Field Mapping."

**Testing:**
- Golden-file tests for XML structure consistency
- Unit test: filename collision detection works
- Unit test: base_url validation works
- Integration test: export batch with both persons and places, verify both entity types in output
- Manual test: export same batch via both entry points; compare XML; confirm filenames don't collide

**Acceptance Criteria:**
- [ ] XML root is canonical across both export paths
- [ ] No filename collisions possible; raises error upfront
- [ ] base_url validation prevents example.org exports
- [ ] All entity types (persons, places, orgs) included in export
- [ ] No silent overwrites; all data preserved
- [ ] No silent mutations; all mappings explicit
- [ ] Golden-file tests pass; XML structure consistent

---

## Cross-Cluster Dependencies

**Cluster 1 → Cluster 2 (Provenance & Confidence):**
- CORE-ENH-03 (Unified Provenance) is part of Cluster 1 implementation
- Once Provenance is in place, Cluster 2 can build confidence annotations on top
- Provenance includes confidence_score, which feeds into Cluster 3's dashboard presentation

**Cluster 1 → Cluster 4 (Collection-Agnostic):**
- Silent failures in ingest/export often stem from hardcoded assumptions (e.g., GIUB-specific schema)
- Once Cluster 1 makes failures visible, Cluster 4 can address root causes (e.g., hardcoded field names)

**Cluster 1 ← Cluster 9 (Data Model):**
- Cluster 9 consolidates report types and enums (e.g., ReviewStatus unification)
- CORE-BUG-02 is a Cluster 1 issue but feeds into Cluster 9's data-model consolidation
- Should be unblocked by Cluster 1's completion, not delayed

---

## Definition of Done for Cluster 1

A Cluster 1 issue is **complete** when:

1. ✅ **Code:** Issue implemented, passing all unit + integration tests
2. ✅ **Logging:** All silent failures are logged with context (record_id, operation, error_message)
3. ✅ **API:** CompletionSummary or equivalent exposed in API (if relevant to the issue)
4. ✅ **Dashboard:** Curator-facing change is visible in the dashboard (banner, error list, etc.)
5. ✅ **Documentation:** Code comments explain the failure mode and how it's now visible
6. ✅ **Manual Test:** Issue author has manually tested the specific scenario described in the issue

**Cluster 1 Completion Criteria (all 19 issues done):**
- [ ] Every batch operation (ingest, NER, vision, semantic, enrich, export) surfaces completion summary
- [ ] No silent exceptions remain in critical paths
- [ ] Dashboard displays completion rate + error summary for all operations
- [ ] Users can retry failed-only batches without re-running successes
- [ ] All data loss bugs (XML, filenames, export overwrites) are prevented upfront
- [ ] E2E test simulates realistic failure scenario and validates end-to-end visibility

---

## Risk & Mitigation

| Risk | Mitigation |
|---|---|
| **Scope creep:** "visibility" could mean adding 10 new UI panels | Scope to: banner + error modal + retry flow. Details in separate issues (Cluster 7). |
| **Data loss during refactor:** Changing XML/export structure breaks production exports | Use golden-file tests; roll out EXP fixes with caution; provide migration guide for existing exports. |
| **Performance:** Storing all failures in memory for large batches | Failures stored on disk/DB with pagination; API returns paginated results. |
| **Backward compatibility:** API clients expecting old CompletionSummary format | Version the API; provide migration doc in CHANGELOG. |

---

## Testing Strategy (Minimal Test Fixtures)

Since you don't have full GIUB fixtures yet, here's how to generate test data incrementally:

### **Minimal fixture (for Groups 1–3):**
```python
# tests/fixtures/test_data_minimal.py
MINIMAL_NER_BATCH = [
    {"record_id": "img_001", "text": "Luzern Stadtansicht", "extracted_entities": None},
    {"record_id": "img_002", "text": "Zermatt Gletscher", "extracted_entities": None},
    {"record_id": "img_003", "text": "Invalid\\xFF UTF-8", "extracted_entities": None},  # Will parse-fail
]

MINIMAL_IMAGES = [
    ("tests/fixtures/sample.png", b"\x89PNG\r\n..."),  # Valid PNG
    ("tests/fixtures/wrong_mime.png", b"{\"error\": \"fake jpeg\"}"),  # Wrong MIME
]
```

### **Testing Approach:**
1. **Unit tests:** Each silent-failure scenario has a dedicated test
2. **Integration tests:** Load minimal fixture, run operation, assert CompletionSummary is accurate
3. **Manual UI tests:** Start the app locally, run the operation, visually verify banner + affordances

### **Test Naming Convention:**
```
test_silent_failure_<operation>_<scenario>
e.g., test_silent_failure_ner_batch_timeout
e.g., test_silent_failure_ingest_image_wrong_mime
e.g., test_silent_failure_export_filename_collision
```

---

## Priority & Timeline

### **Immediate (Week 1):**
- **Group 1** (Exception Handling): ~1 day
  - Establish logging pattern & FailureRecord
  - Extend BatchReport with provenance
  - Unblock all other groups

### **High Priority (Week 1–2):**
- **Group 3** (Headline Deliverable): ~3–4 days
  - Provenance dataclass (CORE-ENH-03)
  - CompletionSummary & API exposure (EXT-BUG-01)
  - Dashboard banner implementation
  - E2E test: failure scenario end-to-end

### **Medium Priority (Week 2):**
- **Group 2** (Core Enum): ~2 days
  - Unifies type system; unblocks CORE-ENH-04 later
  - Lower UX impact than Groups 1 & 3
- **Group 4** (Ingest): ~1–2 days
  - Applies same pattern as Group 1 to ingest layer
  - Can run in parallel with Group 5

### **Lower Priority (Week 2–3):**
- **Group 5** (Export): ~2–3 days
  - Fixes publishing bugs; lower immediate impact
  - Can wait until ingest is solid

**Total estimated effort:** ~3–4 weeks (all 5 groups)
**Recommended parallelization:**
- Week 1: Group 1 + start Group 3
- Week 2: Finish Group 3 + start Group 2 + Group 4
- Week 3: Finish Group 2, 4, 5 in parallel

---

## Claude Code Briefing Template

Once you confirm this strategy, here's how I'll brief Claude Code:

```markdown
# Claude Code: Cluster 1 Silent Failures M1 — Group [N]

## Context
You're implementing [Group N] of Cluster 1 ("Silent Failures Made Visible").
This is a ~[1–4] day effort, part of a 3–4 week initiative to surface completion rates
and failures in batch operations.

## Your Task
Implement [Group N] issues: [list of issues]

## Branch & Files
- **Branch:** `fix/silent-failures-[group-name]`
- **Files affected:** [list of file paths]
- **New files:** [CompletionSummary.py, etc. if applicable]

## Acceptance Criteria
[Checklist from section above]

## Testing
[Specific test names + fixture references]

## Manual Testing
[Step-by-step UI testing instructions]

## Known Dependencies
[Other groups; when to merge]
```

---

## Next Steps

1. **Review this strategy.** Does the 5-group breakdown make sense?
2. **Confirm priority order.** Should we really start with Group 1, then jump to Group 3?
3. **Approve test fixture approach.** Acceptable to generate minimal synthetic data, or do you have fixtures available?
4. **I'll generate detailed Claude Code briefings for Groups 1–3** (the critical path for M1).
5. **Groups 4–5 can be briefed once M1 is complete** (lower immediate impact).

Sound good?

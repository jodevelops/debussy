# Debussy — Issues from `core/` Audit

**Source:** Layer-1 production-readiness audit of `src/kwb/core/`
**Date:** 2026-04-28
**Scope:** All files in `src/kwb/core/` (auth, config, interfaces, mds, models, normalize, roadmap, tasks, utils, workspace)

This document captures bugs and enhancements identified in the audit, formatted so each block can be filed as a separate GitHub issue without further editing.

## Issue Template

Each issue follows this structure:

```
## <ID> — <Title>

**Type:** Bug | Enhancement | Refactor | Tech Debt
**Severity:** Critical | High | Medium | Low
**Effort:** S (<1d) | M (1–3d) | L (>3d)
**Affected:** <files/modules>
**Discovered:** <audit reference>

### Problem
What is wrong / suboptimal today.

### Expected
What the desired state looks like.

### Reproduction (bugs only)
Minimal steps or code snippet.

### Suggested approach
How to fix or implement.

### Acceptance criteria
Checkable items defining "done".

### Related
Other issues, dependencies, references.
```

Issue IDs are placeholders (`CORE-BUG-NN`, `CORE-ENH-NN`) — replace with GitHub issue numbers on filing. Severity is calibrated against the project goal of FK-driven curation, not generic best practice.

---

# Bugs

## CORE-BUG-01 — Duplicate `image_review_stats()` method on Workspace

**Type:** Bug
**Severity:** High
**Effort:** S
**Affected:** `src/kwb/core/workspace.py` — `Workspace` class
**Discovered:** Core audit 2026-04-28

### Problem
`Workspace` defines `image_review_stats()` twice. Python silently uses the second definition. The first uses the `ImageReviewStatus` enum (`pending`, `accepted`, `rejected`); the second hard-codes `"approved"` instead of `"accepted"`. Any caller that expects an enum-aligned key reads zero, while the real count lives under a misspelled key. This is exactly the kind of defect that test counts hide if no test asserts on the dict's key spelling.

### Expected
A single canonical method whose returned dict has keys matching `ImageReviewStatus` values verbatim (`pending`, `accepted`, `rejected`) plus `total`.

### Reproduction
```python
from kwb.core.workspace import Workspace, ImageAnalysisResult, ImageReviewStatus

ws = Workspace.create("test")
ws.save_image_analysis(ImageAnalysisResult(
    image_id="x", review_status=ImageReviewStatus.ACCEPTED,
))
print(ws.image_review_stats())
# Actual:   {'pending': 0, 'approved': 0, 'rejected': 0, 'total': 1}
# Expected: {'pending': 0, 'accepted': 1, 'rejected': 0, 'total': 1}
```

### Suggested approach
Delete the second definition. Audit all callers (API routes, dashboard JS) for dependence on `"approved"`. Add a regression test asserting the dict's keyset matches `{s.value for s in ImageReviewStatus} | {"total"}`.

### Acceptance criteria
- [ ] Only one `image_review_stats()` definition on `Workspace`
- [ ] Returned dict keys exactly match `ImageReviewStatus` values plus `total`
- [ ] Regression test asserts on keyset, not just on `total`
- [ ] All callers reviewed and updated if necessary

### Related
- CORE-BUG-02 (`ReviewStatus` collision) — both reflect inconsistent enum discipline

---

## CORE-BUG-02 — Two distinct `ReviewStatus` enums with the same name

**Type:** Bug
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/core/models.py`, `src/kwb/core/workspace.py`
**Discovered:** Core audit 2026-04-28

### Problem
`models.py` defines `ReviewStatus(str, Enum)` with values `PENDING / ACCEPTED / REJECTED / NEEDS_EXPERT_REVIEW / APPLIED`. `workspace.py` defines a *different* `ReviewStatus(str, Enum)` with values `PENDING / ACCEPTED / REJECTED / MERGED`. They share members by string but are separate Python types — equality across modules silently fails. Code that compares `EntityReview.status` (workspace) with `ReviewItem.status` (models) cannot work correctly. The trap is that `==` returns `False` even when both are `"pending"`, because enum equality requires identical type.

### Expected
A single `ReviewStatus` enum, used everywhere. The union of members is `PENDING / ACCEPTED / REJECTED / NEEDS_EXPERT_REVIEW / APPLIED / MERGED` — verify each is actually used, and drop unused ones.

### Reproduction
```python
from kwb.core.models import ReviewStatus as RSm
from kwb.core.workspace import ReviewStatus as RSw

print(RSm.PENDING == RSw.PENDING)   # False
print(RSm.PENDING.value == RSw.PENDING.value)  # True
```

### Suggested approach
1. Decide canonical location (likely `models.py`, since it's the lower-level module)
2. Move the enum there with the merged member set
3. Delete the duplicate; update imports
4. Search for `MERGED` usages — if zero, drop it; if non-zero, it stays
5. Add static check or test to prevent re-divergence

### Acceptance criteria
- [ ] Exactly one `ReviewStatus` definition in the codebase
- [ ] All cross-module status comparisons type-check and pass
- [ ] Member set documented and minimal
- [ ] Test asserts equality across modules works

### Related
- CORE-BUG-01 (duplicate method) — same root cause: weak enum discipline

---

## CORE-BUG-03 — `field_mapping` and `dictionary` properties have dual list/dict storage

**Type:** Bug / Tech Debt
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/core/workspace.py` — `Workspace.field_mapping`, `Workspace.dictionary`
**Discovered:** Core audit 2026-04-28

### Problem
`Workspace` keeps two parallel storages for `field_mapping`: `_field_mapping` (list of `FieldMapping`) and `_field_mapping_raw` (dict). The setter accepts both shapes; the getter returns whichever was last set. `dictionary` has a similar dual mode. This is a backwards-compatibility scar that makes refactoring hazardous: any consumer might receive either shape, and there is no documented contract. It also makes serialization round-trips lossy in subtle ways.

### Expected
A single canonical shape (list of `FieldMapping`). Legacy dict-shaped JSON is migrated on load and never re-introduced.

### Suggested approach
1. Audit all callers and tests to find which shape they rely on
2. Add a one-shot migration in `from_dict()` that normalizes legacy dict-shaped data to the list shape
3. Drop `_field_mapping_raw`; getter returns the list
4. Same treatment for `dictionary`
5. Document the canonical JSON shape in a docstring

### Acceptance criteria
- [ ] `_field_mapping_raw` removed
- [ ] Legacy dict-shaped JSON loads correctly via migration
- [ ] All call sites updated
- [ ] JSON shape documented in `Workspace` docstring
- [ ] Round-trip test: `from_dict(to_dict(ws)).to_dict() == ws.to_dict()`

### Related
- CORE-ENH-04 (workspace as fact store) — depends on this being resolved first

---

## CORE-BUG-04 — Silent JSON load failure in `UserStore` can silently re-create default admin

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/core/auth.py` — `UserStore._load()`, `UserStore.ensure_default_admin()`
**Discovered:** Core audit 2026-04-28

### Problem
`_load()` wraps `json.loads` in `except Exception: pass`. A corrupted or partially written `users.json` produces an empty user dict with no log entry. Combined with `ensure_default_admin()`, this means a corrupted store silently re-creates the default admin user with the env-default password. From the operator's perspective, "user accounts disappeared and admin credentials reset" happens with no audit trail.

### Expected
Load failures are logged with severity `ERROR` and include the path. Optionally, a corrupted file is renamed to `users.json.corrupt-<timestamp>` rather than overwritten by the next save, so recovery is possible.

### Suggested approach
1. Replace the bare `except` with `except (OSError, json.JSONDecodeError) as e:` and log
2. On parse error, raise a clear domain exception (`UserStoreCorruptError`) and let the caller decide
3. In `ensure_default_admin`, only create if load *succeeded* with empty result, not if load *failed*
4. Add test for corrupted file handling

### Acceptance criteria
- [ ] Load failures are logged
- [ ] `ensure_default_admin` does not run after load failure
- [ ] Corrupted file is preserved (not overwritten) until operator action
- [ ] Test covers the corrupted-file path

### Related
- CORE-BUG-05 (default admin password)

---

## CORE-BUG-05 — Default admin password `"debussy"` with no warning

**Type:** Bug / Hardening
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/core/auth.py` — `UserStore.ensure_default_admin()`
**Discovered:** Core audit 2026-04-28

### Problem
If `KWB_ADMIN_PASSWORD` is not set, the default admin user is created with the password `"debussy"`. There is no log warning, no UI nag, and no forced password change on first login. For local development this is fine; for any deployment that exposes port 8765 it is a foot-gun.

### Expected
Either: (a) refuse to start without `KWB_ADMIN_PASSWORD` set; or (b) start with a generated random password printed once to stdout and a `must_change_password` flag set on the user.

### Suggested approach
1. Decide policy with project lead — option (b) is more user-friendly for local dev while remaining safe
2. If (b): generate a random password in `ensure_default_admin()`, print to stdout once, set `must_change_password=True` on the user
3. Add a `must_change_password` field to `User` and gate login on it in the API
4. Document in README

### Acceptance criteria
- [ ] No hardcoded default password in source
- [ ] First-run password is printed once and not stored anywhere logged routinely
- [ ] Forced password change works end-to-end
- [ ] README documents the first-run flow

### Related
- CORE-BUG-04 (silent re-creation)

---

## CORE-BUG-06 — `KWBConfig.save_to_dotenv` saves only 4 of 14 config keys

**Type:** Bug
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/core/config.py` — `KWBConfig.save_to_dotenv()`
**Discovered:** Core audit 2026-04-28

### Problem
`load_config()` reads 14 environment variables. `save_to_dotenv()` writes only the four GPUStack ones (`URL`, `KEY`, `MODEL_TEXT`, `MODEL_VISION`). If the API ever lets users edit Goobi or GeoNames config, those changes are lost on restart. Either the asymmetry is intentional and undocumented, or it is a forgotten extension.

### Expected
Either: (a) `save_to_dotenv()` persists all 14 keys; or (b) the docstring states explicitly that only GPUStack settings are persisted by design, and the UI prevents editing the others. Decide which.

### Suggested approach
Most likely (a): extend the `mapping` dict in `save_to_dotenv` to include all 14 keys. Preserve existing comment lines and unrelated entries (the function already does this).

### Acceptance criteria
- [ ] Decision on (a) vs (b) recorded in code or docs
- [ ] If (a): all 14 keys round-trip via `load_config → save_to_dotenv → load_config`
- [ ] Test for the round-trip

### Related
None.

---

## CORE-BUG-07 — Deprecated `datetime.utcnow()` used throughout core

**Type:** Bug / Tech Debt
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/core/auth.py`, `src/kwb/core/tasks.py`, `src/kwb/core/workspace.py`
**Discovered:** Core audit 2026-04-28

### Problem
`datetime.utcnow()` is deprecated as of Python 3.12 and emits a `DeprecationWarning`. It produces a naive datetime, which is also a subtle correctness issue when timestamps are compared across timezones.

### Expected
All usages replaced with `datetime.now(timezone.utc)`. Returned ISO strings include the timezone suffix (`+00:00`).

### Suggested approach
Repo-wide find/replace, then run tests. Some test fixtures may compare ISO strings — update assertions to match the new format or use `.isoformat(timespec="seconds")` consistently.

### Acceptance criteria
- [ ] No `datetime.utcnow()` calls remain in `src/kwb/core/`
- [ ] Tests pass without `DeprecationWarning` from this source
- [ ] ISO strings include timezone offset

### Related
Likely also affects modules outside `core/`. Sweep them in the same PR or open follow-up issues per module.

---

# Enhancements / Refactors

## CORE-ENH-01 — Consolidate three coexisting "report" model generations

**Type:** Refactor
**Severity:** High (blocks FK rendering)
**Effort:** L
**Affected:** `src/kwb/core/models.py`
**Discovered:** Core audit 2026-04-28

### Problem
`models.py` contains three generations of report-related types:

1. `Finding` / `AnalysisReport` (early structural-checks era)
2. `QualityMeasureSummary` / `QualityMeasureReport` (middle era)
3. `QualityAnalysisReport` with `ColumnQualityReport` / `RecordQualityReport` / `CellFinding` / `IssueCluster` (current era)

`AnalysisReport` even embeds `quality_measures: QualityMeasureReport | None`, so generation 1 carries a reference to generation 2. Generation 3 is structurally what FK rendering needs (record-level, column-level, cell-level granularity), but the older types still drive parts of the dashboard. This evolutionary archaeology makes it unclear which type to add to, extend, or read from.

### Expected
A single canonical hierarchy of report types covering dataset / column / record / cell granularity, with a deprecation path for the older types. Each report variant has one home and one purpose.

### Suggested approach
1. Map current usages: which dashboard tab / API route / report renderer consumes which type
2. Pick `QualityAnalysisReport` (gen 3) as canonical
3. Provide thin adapters from gen 1 and gen 2 for backwards compatibility during migration
4. Migrate consumers one by one
5. Mark gen 1 and gen 2 with deprecation warnings, then remove in a later release

### Acceptance criteria
- [ ] Usage map documented
- [ ] Single canonical type for each granularity level
- [ ] Adapters in place for the migration window
- [ ] Older types deprecated with a clear removal version

### Related
- CORE-ENH-02 (Phase 3 review types)
- CORE-ENH-04 (workspace as fact store)
- Strategic: enables FK Statusboard work

---

## CORE-ENH-02 — Phase 3 review types appear disconnected from earlier strata

**Type:** Refactor
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/core/models.py` — `ReviewItem`, `WorkPackage`, `RemediationSuggestion`, `AppliedChangeLog`
**Discovered:** Core audit 2026-04-28

### Problem
The Phase 3 review types are well-designed but their linkage to the earlier strata is unclear. `ReviewItem` references `source_issue_ids: list[str]`, but no earlier type has IDs of that shape (`Finding` has no `id`; `CellFinding` has no `id`). It is unclear whether: (a) the linkage is implemented elsewhere; (b) it was planned and not finished; or (c) Phase 3 is a parallel architecture that has not been adopted yet.

### Expected
Either the wiring is documented and demonstrated end-to-end (cluster → review item → work package → applied change), or the dead code is removed.

### Suggested approach
1. Determine current state via grep of `source_issue_ids`, `ReviewItem`, `WorkPackage` usage
2. If unused: remove or move to a `models_phase3.py` clearly marked "draft / not in active use"
3. If partially used: document the gap and decide finish-or-remove
4. If used: add a docstring to each Phase 3 type pointing to its producer

### Acceptance criteria
- [ ] Status of Phase 3 types is clearly documented
- [ ] No dead code in `models.py`
- [ ] If kept, integration is demonstrated by a test

### Related
- CORE-ENH-01 (consolidate reports)

---

## CORE-ENH-03 — Provenance fields are inconsistent across extraction result types

**Type:** Enhancement
**Severity:** High (blocks FK aggregate publishing)
**Effort:** M
**Affected:** `src/kwb/core/workspace.py` — `EntityReview`, `CuratedDate`, `ImageAnalysisResult`, `DictionaryEntry`
**Discovered:** Core audit 2026-04-28

### Problem
Different extraction-result types carry different provenance fields:

| Type | model | prompt_name | prompt_version | analyzed_at | reviewer | run_id |
|---|---|---|---|---|---|---|
| `ImageAnalysisResult` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `EntityReview` | — | — | — | — | — | — |
| `CuratedDate` | — | — | — | — | — | — |
| `DictionaryEntry` | `model_source` | — | — | `last_edited` | — | — |

For an FK that publishes aggregate statistics with attribution (e.g. "67% of records have a place mention extracted with model X, prompt v3, on 2026-04"), this gap is a blocker. "Which model produced this entity, with which prompt, in which run" is unanswerable from current data.

### Expected
A shared `Provenance` dataclass attached uniformly to every extraction result:

```python
@dataclass
class Provenance:
    model: str = ""
    prompt_name: str = ""
    prompt_version: str = ""
    run_id: str = ""
    extracted_at: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
```

### Suggested approach
1. Define `Provenance` in `models.py`
2. Add `provenance: Provenance` field to `EntityReview`, `CuratedDate`, and as a sibling to existing fields on `ImageAnalysisResult` (during transition)
3. Update producers (NER service, EDTF service, Vision routes) to populate it
4. Update serializers to round-trip it
5. Migrate older workspace JSON files: provenance is empty for legacy data — that is acceptable, but document it

### Acceptance criteria
- [ ] `Provenance` dataclass defined and reused
- [ ] All three result types carry it
- [ ] Producers populate it
- [ ] Round-trip preserved
- [ ] Migration path for legacy workspaces documented

### Related
- CORE-ENH-04 (fact store) — depends on this
- Strategic: prerequisite for FK aggregate-with-attribution rendering

---

## CORE-ENH-04 — Workspace is a fragmented fact store; consolidate into a unified model

**Type:** Refactor
**Severity:** High (central architectural issue)
**Effort:** L
**Affected:** `src/kwb/core/workspace.py`
**Discovered:** Core audit 2026-04-28

### Problem
`Workspace` already functions as a fact store, but the data is fragmented across five lists with different schemas:

- `entity_reviews: list[EntityReview]`
- `dates: list[CuratedDate]`
- `image_analyses: list[ImageAnalysisResult]`
- `authority_candidates: list[AuthorityCandidate]`
- `dictionary: list[DictionaryEntry]`

Each list has its own status enum, provenance fields, and merge logic. To answer a uniform query like "which records have a high-confidence place fact extracted by any technique," a caller has to walk three of these lists with different field names and conventions. This is the largest single obstacle to FK rendering, where recipes must aggregate over a uniform fact table.

### Expected
A single `Fact` table (long-format) keyed by `(record_id, parent_id, fact_type, value, confidence, provenance, validated_by)`. The five existing lists become *views* over this table during a transition period, then are removed.

### Suggested approach
1. Define `Fact` and `FactStore` in `kwb.core.facts`
2. Implement read-side adapters first: `Workspace.facts_for_record(record_id) -> list[Fact]` aggregating from existing lists
3. Migrate one consumer (probably FK rendering, since it is greenfield) to read from `Fact`
4. Migrate writers (NER, EDTF, Vision services) to write `Fact` instead of/in addition to the typed lists
5. Once consumers are migrated, the typed lists become deprecated views

DuckDB-on-disk is a reasonable backing store but premature for the first iteration; an in-memory list of `Fact` objects in `Workspace` is enough to validate the model.

### Acceptance criteria
- [ ] `Fact` dataclass and `FactStore` interface defined
- [ ] Adapter from existing typed lists to `Fact` query implemented
- [ ] One end-to-end consumer reads via the new interface
- [ ] Migration plan for writers documented
- [ ] No regression in existing dashboard tabs

### Related
- CORE-BUG-03 (dual storage) — must be resolved first
- CORE-ENH-03 (provenance) — must be resolved first
- Strategic: prerequisite for FK Statusboard

---

## CORE-ENH-05 — `mds.py` field list does not match Fachkonzept MDS list

**Type:** Enhancement
**Severity:** Medium
**Effort:** M
**Affected:** `src/kwb/core/mds.py` — `MDS_11_FIELDS`
**Discovered:** Core audit 2026-04-28

### Problem
`MDS_11_FIELDS` is a hardcoded list of 14 fields. The Fachkonzept template defines 16 Erfassungsfelder + 11 Exportfelder with Pflicht / Bedingt-Pflicht / Empfohlen distinctions and ties to specific LIDO elements. The two lists overlap but do not match. Continuing to use `mds.py` as-is for FK validation would silently report wrong coverage.

### Expected
MDS field definitions are sourced from a single authoritative list aligned with the FK template. Pflicht / Bedingt-Pflicht / Empfohlen distinctions are first-class. Validation results map to FK field IDs (e.g. `m04_mds_e07_pct`).

### Suggested approach
1. Generate field definitions programmatically from the FK template, or maintain a YAML reference that both sides consume
2. Replace the `MDS_11_FIELDS` constant with a loader pointing at that reference
3. Extend `MdsFieldDef` with the three-level requirement enum
4. Update `validate_mds` to emit results keyed by FK field ID where applicable

### Acceptance criteria
- [ ] Single source for MDS definitions
- [ ] FK Erfassungsfelder and Exportfelder both representable
- [ ] Three-level requirement supported
- [ ] Validation result rows map to FK field IDs

### Related
- CORE-ENH-04 (fact store) — MDS validation becomes a fact-aggregation recipe
- Strategic: enables M04 MDS section of FK Statusboard

---

## CORE-ENH-06 — Generalize `tasks.py` from MDS gaps to FK field gaps

**Type:** Enhancement
**Severity:** Medium (strategic, not urgent)
**Effort:** M
**Affected:** `src/kwb/core/tasks.py`
**Discovered:** Core audit 2026-04-28

### Problem
`generate_tasks_from_mds` is a working pattern: walk a validation report, derive prioritized typed tasks with suggestion text. It is the embryo of the FK Statusboard envisioned in the FK strategy discussion. But it is hardcoded against `MdsValidationReport` and 14 MDS fields. It cannot drive a 250-field FK board.

Crucially, `CurationTask` does not record *which technique* would resolve it (e.g. `resolvable_by: ["ner_llm", "edtf_rules"]`). Without this, the Statusboard cannot offer a "Run" button per FK field.

### Expected
A generalized `generate_tasks_from_fk_gaps(fk_status: FkStatusReport) -> list[CurationTask]`. `CurationTask` gains a `resolvable_by: list[str]` field listing technique IDs registered in a service registry. The Statusboard reads tasks and dispatches to the technique.

### Suggested approach
1. Define `FkField`, `FkFieldStatus`, `FkStatusReport` types
2. Add `resolvable_by: list[str]` to `CurationTask`
3. Implement `generate_tasks_from_fk_gaps`; keep `generate_tasks_from_mds` as a special case
4. Build a tiny technique registry (id → callable) populated by annotated services (see CORE-ENH-07)
5. Wire one FK field end-to-end as proof of concept (e.g. M04 `Ort` coverage via existing GND/NER stack)

### Acceptance criteria
- [ ] `FkField` / `FkStatusReport` types defined
- [ ] `CurationTask.resolvable_by` populated correctly
- [ ] `generate_tasks_from_fk_gaps` covers at least one full FK module
- [ ] Proof-of-concept Statusboard tile dispatches to the right technique
- [ ] Existing MDS task generation still works

### Related
- CORE-ENH-04 (fact store) — fact store provides the data the gap report aggregates over
- CORE-ENH-05 (MDS alignment) — same logic applies to MDS subset
- CORE-ENH-07 (service protocols) — supplies the technique registry
- Strategic: this is the FK Statusboard

---

## CORE-ENH-07 — Complete the service-protocol abstraction

**Type:** Enhancement
**Severity:** Low
**Effort:** M
**Affected:** `src/kwb/core/interfaces.py`
**Discovered:** Core audit 2026-04-28

### Problem
`interfaces.py` defines `NerServiceProtocol` and `DateServiceProtocol`, but stops there. Other techniques (semantic classification, vision analysis, OCR, structural checks, GND enrichment, Wikidata enrichment, GeoNames) have no protocol. The pattern is the right one — runtime-checkable Protocols enable testability and a clean technique registry — but it is half-finished. Without protocols on every technique, the technique registry envisioned in CORE-ENH-06 cannot be uniformly populated.

### Expected
Every analyze / enrich / extract service has a Protocol in `interfaces.py` declaring its inputs, outputs, and the fact types it produces. A `TechniqueRegistry` discovers and lists them.

### Suggested approach
1. List all current services that should be behind a Protocol (audit `analyze/`, `enrich/` first — see follow-up audit)
2. Define one Protocol per service, modeled on the existing two
3. Add `produces_fact_types: list[str]` and `contributes_to_fk_fields: list[str]` as class attributes
4. Implement a small `TechniqueRegistry` that walks instances and indexes them
5. Make the existing services explicit subclasses (or just verify Protocol conformance via tests)

### Acceptance criteria
- [ ] All in-scope services have a Protocol
- [ ] `produces_fact_types` and `contributes_to_fk_fields` populated
- [ ] `TechniqueRegistry` lists and looks up techniques
- [ ] Test asserts every service satisfies its Protocol

### Related
- CORE-ENH-06 (FK gap tasks) — uses the registry
- CORE-ENH-04 (fact store) — fact types referenced here are defined there

---

# Summary

| ID | Type | Severity | Effort | Title (short) |
|---|---|---|---|---|
| CORE-BUG-01 | Bug | High | S | Duplicate `image_review_stats` |
| CORE-BUG-02 | Bug | High | M | Two `ReviewStatus` enums |
| CORE-BUG-03 | Bug / Tech Debt | Medium | M | Dual list/dict storage |
| CORE-BUG-04 | Bug | Medium | S | Silent JSON load failure |
| CORE-BUG-05 | Bug | Medium | S | Default admin password |
| CORE-BUG-06 | Bug | Low | S | Asymmetric `save_to_dotenv` |
| CORE-BUG-07 | Bug / Tech Debt | Low | S | Deprecated `datetime.utcnow` |
| CORE-ENH-01 | Refactor | High | L | Consolidate report types |
| CORE-ENH-02 | Refactor | Medium | M | Phase 3 review types disconnected |
| CORE-ENH-03 | Enhancement | High | M | Unified provenance |
| CORE-ENH-04 | Refactor | High | L | Unified Fact store |
| CORE-ENH-05 | Enhancement | Medium | M | MDS aligned with FK |
| CORE-ENH-06 | Enhancement | Medium | M | Generalize tasks → FK gaps |
| CORE-ENH-07 | Enhancement | Low | M | Complete service Protocols |

## Recommended sequencing

**Phase 1 — Stabilize (S/M effort, no architectural commitment):**
CORE-BUG-01, CORE-BUG-02, CORE-BUG-04, CORE-BUG-06, CORE-BUG-07. About 1–2 days.

**Phase 2 — Prepare for FK work (resolves the dual-storage ambiguity, unifies provenance):**
CORE-BUG-03, CORE-ENH-03. About 3–5 days. After this the codebase is in shape to accept FK additions.

**Phase 3 — FK foundation (the architectural work that enables the Statusboard):**
CORE-ENH-04, CORE-ENH-01, CORE-ENH-05. About 2–3 weeks.

**Phase 4 — FK board itself:**
CORE-ENH-06, CORE-ENH-07, plus new (non-core) modules for FK template parsing and rendering. About 2 weeks.

**Phase 5 — Cleanup:**
CORE-ENH-02 once the new architecture has stabilized.

This ordering ensures every phase ends in a working state, no breaking change without a migration path, and FK work begins only when the data model can support it.

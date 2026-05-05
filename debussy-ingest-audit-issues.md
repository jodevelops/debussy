# Debussy — Issues from `ingest/` Audit (User-Centered)

**Source:** Layer-1 user-centered audit of `src/kwb/ingest/`
**Date:** 2026-04-28
**Scope:** `__init__.py`, `csv_loader.py`, `image_loader.py`, `pdf_loader.py`, `xlsx_loader.py`, `xml_loader.py`
**Calibration:** Severity reflects user impact, not code health. *High* = user is misled or blocked. *Medium* = user is confused or has to guess. *Low* = workable but clumsy.

This audit pairs with the previous three. Issue prefix `ING-`.

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

# Bugs (silent failures, misleading outputs, hidden assumptions)

## ING-BUG-01 — Encoding detection silently falls back to "utf-8" when chardet is missing; users see Mojibake without warning

**Type:** Bug
**Severity:** High
**Effort:** S
**Affected:** `src/kwb/ingest/csv_loader.py` — `detect_encoding()`
**Discovered:** Ingest audit 2026-04-28

### Problem
```python
try:
    import chardet
    result = chardet.detect(raw[:8192])
    enc = result.get("encoding") or "utf-8"
    return enc, False
except ImportError:
    return "utf-8", False
```
If `chardet` is not installed, the function returns `"utf-8"` with no warning. A user with a Latin-1 CSV (extremely common in older German archive exports) will see Mojibake (`Ã¼` instead of `ü`) in every downstream display. The encoding-fallback chain in `load_csv` does try other encodings if UTF-8 decode fails, but if the bytes happen to be valid UTF-8 by chance (most ASCII text is), Latin-1 content with a few umlauts gets decoded successfully but wrongly.

The user has no signal that anything is amiss. The dashboard says "encoding: utf-8" with confidence, and the data is corrupted.

### Expected
- If `chardet` is missing: log a clear warning, recommend installation, and try multiple encodings actively
- The detected encoding is shown to the user with a confidence level
- If chardet is available, its confidence value is preserved and surfaced

### Suggested approach
1. Make `chardet` (or `charset-normalizer`) a required dependency rather than optional
2. Return `(encoding, confidence)` tuple instead of `(encoding, has_bom)`
3. Surface confidence in `DatasetProfile.encoding_detected` (e.g. `"latin-1 (chardet, conf=0.87)"`)
4. UI: warn explicitly when confidence < 0.8 — "Encoding detection uncertain. Sample of decoded text: '...'. Looks correct?"

### Acceptance criteria
- [ ] Encoding detection always uses a real detector
- [ ] Confidence is preserved end-to-end
- [ ] User sees uncertain detections in dashboard
- [ ] Test with Latin-1 file lacking BOM passes correctly

### Related
- ING-BUG-02 (encoding fallback masks Mojibake)
- EXT-ENH-13 (pattern coverage) — same family of "user can't tell what was detected"

---

## ING-BUG-02 — Encoding fallback chain decodes Mojibake without flagging it

**Type:** Bug
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/ingest/csv_loader.py` — `load_csv()`
**Discovered:** Ingest audit 2026-04-28

### Problem
The fallback loop tries `[detected, "utf-8", "cp1252", "latin-1"]` and stops at the first one that doesn't raise `UnicodeDecodeError`. The trap: `cp1252` and `latin-1` will decode *any* byte sequence successfully — they have no invalid bytes. So a UTF-8 file with one stray byte will fall through to `cp1252`, decoding all the multi-byte UTF-8 characters as garbage but raising no error.

Combined with ING-BUG-01, the user sees `LÃ¼beck` instead of `Lübeck` and has no idea why.

### Expected
- After successful decode, run a heuristic check: do common German characters (`ä ö ü ß`) appear, or do their Mojibake equivalents (`Ã¤ Ã¶ Ã¼ ÃŸ`)?
- If Mojibake patterns dominate, flag the file with a clear warning
- If multiple encodings decoded successfully, prefer the one with no Mojibake patterns

### Suggested approach
1. After successful `pd.read_csv` decode, sample 100 rows and run a Mojibake detector
2. If detected, log warning *and* pass it up so the dashboard can show it
3. Test fixture: deliberately encoded-twice file (UTF-8 → Latin-1 → "decoded" as UTF-8)

### Acceptance criteria
- [ ] Mojibake-detection check runs after every load
- [ ] Warnings surface in `DatasetProfile`
- [ ] Test covers the round-trip-Mojibake case
- [ ] Documentation explains the heuristic

### Related
- ING-BUG-01 (chardet missing)
- The structural-checks (`check_encoding_issues` in `analyze/structural.py`) already detect this *after* load — but by that point the user has been seeing wrong text. Fixing it at load time is more user-friendly.

---

## ING-BUG-03 — `detect_id_column` silently returns the *first* unique column it finds, which can be the wrong one

**Type:** Bug
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/ingest/csv_loader.py` — `detect_id_column()`
**Discovered:** Ingest audit 2026-04-28

### Problem
The fallback path:
```python
# Fallback: first fully-unique column
for col in df.columns:
    non_null = df[col].dropna()
    if len(non_null) > 0 and non_null.is_unique:
        return col
```
Order of columns in a CSV is arbitrary. The "first fully-unique column" may be a `filename` field, a row-index leftover from a previous export, a hash, or even a free-text column that happens to be unique in this dataset (titles, descriptions). The user gets back a `DatasetProfile` saying `id_column = "filename"` and from then on every downstream step joins, deduplicates, and reports keyed on filename instead of `record_id`.

The user has no chance to confirm or override this in the load path. They see a proposed ID column only after running structural checks, and by then many things have already used the wrong key.

### Expected
- ID column detection returns *all* candidate columns with a confidence score and a reason
- The user confirms which one is the ID before any downstream operation
- If the user uploads a CSV without confirming, the system either (a) blocks until they confirm or (b) uses the highest-confidence candidate but flags it loudly

### Suggested approach
1. Change `detect_id_column` to return `list[IdCandidate]` with `(column, confidence, reason)` per candidate
2. UI: after upload, the user sees the candidates with sample values and picks one (defaulting to the top candidate)
3. Confidence = combination of name-pattern match + uniqueness + value-shape (UUIDs / numeric / short strings score higher than long free text)
4. Document the heuristic

### Acceptance criteria
- [ ] Multiple ID candidates returned with reasons
- [ ] User confirmation step in dashboard before pipelines run
- [ ] Test cases for CSVs where the right column is not first
- [ ] Documentation

### Related
- ING-ENH-01 (ingest preview / confirmation step)
- EXT-BUG-06 (hardcoded subject column) — same class of "wrong default, no confirmation"

---

## ING-BUG-04 — `MAX_ROWS = 50_000` is hardcoded; users with larger datasets get an opaque error

**Type:** Bug / Hidden limit
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ingest/csv_loader.py`, `xlsx_loader.py`, `xml_loader.py`
**Discovered:** Ingest audit 2026-04-28

### Problem
The constant is declared at module level. `load_csv` raises `CSVLoadError` with a message that says "Split the file or raise MAX_ROWS." For a non-developer user, neither of those is actionable from the dashboard. The user uploads their 60,000-record collection, sees "exceeding the limit," and is stuck.

The same hardcoded limit shows up in `xlsx_loader.py` and `xml_loader.py`, all importing from `csv_loader`. So changing it requires editing source.

### Expected
- The limit is configurable per workspace
- The dashboard explains the limit before upload, not after
- For oversized files, an "expert mode" affordance lets the user proceed with a warning ("memory usage will be high")

### Suggested approach
1. Move `MAX_ROWS` to `core/config.py` as `KWB_MAX_ROWS` env var
2. Surface in dashboard config
3. UI: file size estimate before upload commits ("This CSV has ~62,000 rows, exceeding the 50,000-row limit. Increase limit or split file?")
4. Document memory cost per 10k rows

### Acceptance criteria
- [ ] Limit is configurable
- [ ] User sees the limit before they hit it
- [ ] Documentation includes memory-cost guidance

### Related
- General onboarding pattern, similar to EXT-ENH-11 (GeoNames credentials)

---

## ING-BUG-05 — `ingest_image` silently swallows hash and dimension extraction errors with bare `except`

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ingest/image_loader.py` — `_jpeg_dims()`, `_png_dims()`
**Discovered:** Ingest audit 2026-04-28

### Problem
```python
def _jpeg_dims(path):
    try:
        with open(path,"rb") as f: data=f.read()
        ...
    except: pass
    return None,None

def _png_dims(path):
    try:
        ...
    except: return None,None
```
Bare `except:` catches everything including `KeyboardInterrupt` and `SystemExit`. More importantly, the user gets back an `ImageProfile` with `width=None, height=None` and no indication of *why* dimension extraction failed. Was the file truncated? Is it a malformed JPEG? Was it a TIFF that the function doesn't handle? They look identical.

For a curator processing a folder of 5,000 scanned plates, "why does this one have no dimensions?" becomes an investigation per file.

### Expected
- Specific exception handling (`OSError`, `struct.error`, `ValueError`)
- Failures populate `ImageProfile.errors` with a useful message
- Dashboard surfaces files with extraction failures distinctly

### Suggested approach
1. Replace bare `except` with specific catches
2. Log the actual error per file
3. Add to `ImageProfile.errors`
4. Test: corrupted JPEG fixture, truncated PNG fixture

### Acceptance criteria
- [ ] No bare `except` in this module
- [ ] Failed extractions populate `errors` field with reason
- [ ] Test fixtures cover common corruption modes

### Related
- EXT-BUG-04 (same pattern in `analyze/structural.py`)

---

## ING-BUG-06 — `_detect_mime` returns `"application/octet-stream"` for unrecognised image bytes; downstream treats them as images anyway

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ingest/image_loader.py` — `_detect_mime()`, `scan_image_directory()`
**Discovered:** Ingest audit 2026-04-28

### Problem
The directory scanner filters by file *extension*, then calls `ingest_image` which detects MIME by *content*. For a file with extension `.jpg` but corrupted/wrong content, MIME comes back as `application/octet-stream` — but the file is still added to the result list with that MIME. Downstream code (vision LLM calls, base64 encoding) treats it as image data anyway.

Worst case: a renamed text file with `.jpg` extension goes through the entire pipeline as an "image" until the vision model returns gibberish.

### Expected
- MIME mismatch (extension says image, content says octet-stream) is flagged
- Such files are listed separately from "real images" and not included in image-processing pipelines without explicit user opt-in
- The user sees "47 images, 3 files with mismatched extensions"

### Suggested approach
1. Verify content MIME matches extension
2. On mismatch: add to a separate `mismatched_files` list in scan results
3. UI: surface the mismatch list

### Acceptance criteria
- [ ] Mismatched files are quarantined
- [ ] Dashboard surfaces the count
- [ ] Test: txt file with .jpg extension is flagged, not processed

### Related
- ING-BUG-05 (image error visibility)

---

## ING-BUG-07 — `pdf_loader._load_with_pypdf` returns base64 of the *entire PDF* on page 1 only, then empty strings — confusing fallback semantics

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ingest/pdf_loader.py` — `_load_with_pypdf()`
**Discovered:** Ingest audit 2026-04-28

### Problem
```python
profiles.append(ImageProfile(
    ...
    base64_data=b64 if i == 0 else "",
))
```
When pdf2image isn't available, the fallback creates one `ImageProfile` per PDF page, but only the first page carries base64 data — and that data is the *entire PDF file*, not a rendered image. The MIME is `application/pdf`, not `image/png`. Downstream code expecting per-page images will:
- Send the whole PDF as "page 1" to a vision LLM (which may or may not handle it)
- Send empty strings for pages 2+
- Find that "page count" looks right but actual analysis only happened on page 1

### Expected
The fallback either works correctly (one valid image per page) or fails loudly with a clear "pdf2image required for per-page rendering" error. Mixed-success silent fallback is the worst of both worlds.

### Suggested approach
1. Drop the silent pypdf fallback
2. Either: hard-require `pdf2image` for PDF support; or: return a single profile per PDF (not per page) labelled "metadata-only fallback"
3. Document clearly which features need which dependencies

### Acceptance criteria
- [ ] Fallback either fully works or fails loudly
- [ ] No fake per-page profiles
- [ ] Documentation explicit about dependency requirements

### Related
- ING-ENH-04 (dependency self-check)

---

## ING-BUG-08 — `xml_loader` falls through three different namespace strategies; the third one matches *anything tagged "mods"*, including non-MODS XML

**Type:** Bug
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ingest/xml_loader.py` — `load_mets_mods()`
**Discovered:** Ingest audit 2026-04-28

### Problem
```python
mods_records = root.findall(".//mods:mods", NS)
if not mods_records:
    mods_records = root.findall(".//{http://www.loc.gov/mods/v3}mods")
if not mods_records:
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "mods":
            mods_records.append(el)
```
The third fallback matches any element whose local name happens to be `"mods"` regardless of namespace — including a hypothetical `<myorg:mods xmlns:myorg="..."/>` that has nothing to do with MODS. The function then tries to extract MODS-specific subelements from it and produces an empty record.

The user uploads "weird XML" and gets back `pd.DataFrame` with empty rows — no error, no clue.

### Expected
- Either match strictly on namespace, or warn the user that a non-namespaced fallback was used
- If no MODS-shaped content is found, raise a clear error rather than silently returning empty

### Suggested approach
1. Drop the third fallback or gate it behind an explicit "permissive parsing" flag
2. After extraction, if all records are empty, raise `XMLLoadError("No MODS records with content found")`
3. Documentation lists supported namespaces

### Acceptance criteria
- [ ] No silent fallback on bare-tag matching
- [ ] Empty-result detection raises informative error
- [ ] Test fixture for non-MODS `mods`-named element is rejected

### Related
- ING-BUG-02 (silent decode), same family

---

## ING-BUG-09 — `xml_loader._extract_mods_record` extracts only the first matching element and silently drops repeated MODS structures

**Type:** Bug / Data loss
**Severity:** High
**Effort:** M
**Affected:** `src/kwb/ingest/xml_loader.py` — `_extract_mods_record()`
**Discovered:** Ingest audit 2026-04-28

### Problem
For most fields, the extractor uses `.find` (first match only):
```python
ti = mods.find("mods:titleInfo/mods:title", NS)
record["title"] = _text(ti)
```
MODS records routinely have multiple `<titleInfo>` (main, alternative, uniform), multiple `<originInfo>` (creation, publication), multiple `<identifier type="...">` (local, doi, url). The extractor takes the first one, silently. A record with `<titleInfo type="alternative">` *before* the main title gets the alternative as `record["title"]`. A record with multiple identifiers loses all but one.

For libraries and archives where MODS is used precisely *because* it allows nuanced repetition, this is the worst possible failure: it looks like the data loaded successfully but lost the structure that made MODS the right format in the first place.

The `<identifier>` extraction does iterate, but the way it picks one (`identifiers.get("local") or "uri" or first`) silently overwrites.

### Expected
- Repeated MODS elements are preserved, either as semicolon-joined strings (matching CSV multi-value convention) or as parallel columns (`title_main`, `title_alternative`, `identifier_local`, `identifier_uri`)
- The user is told what was extracted

### Suggested approach
1. For known-multi-value fields (`titleInfo`, `name`, `subject`, `identifier`, `originInfo`, `note`), iterate and collect
2. Decide: semicolon-join vs. typed columns; document the choice
3. Surface the extraction strategy in the loader's docstring and dashboard tooltip
4. Test fixture with a multi-titled MODS record

### Acceptance criteria
- [ ] Multi-valued MODS structures preserved
- [ ] Strategy documented
- [ ] Test fixture with a real-world MODS record passes

### Related
- ING-ENH-02 (MODS extraction transparency)

---

## ING-BUG-10 — `_NULLISH` set in `xlsx_loader` does not match `csv_loader`; the same string `"N/A"` produces different results between formats

**Type:** Bug
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ingest/csv_loader.py`, `xlsx_loader.py`
**Discovered:** Ingest audit 2026-04-28

### Problem
Both files define `_NULLISH = {"", "nan", "NaN", "NULL", "None", "N/A", "n/a"}` literally inline. They happen to agree today. Tomorrow a developer adjusts one and not the other. A user who exports the same dataset as both CSV and XLSX (a common archive workflow) sees fill rates differ between the two.

### Expected
Single canonical NULL-string set, imported by all loaders.

### Suggested approach
1. Move `_NULLISH` to `core/utils.py` or a new `ingest/common.py`
2. Both loaders import from there
3. Test both formats produce identical fill rates on the same data

### Acceptance criteria
- [ ] Single source for the NULL-string set
- [ ] Equivalence test
- [ ] No regressions

### Related
- ING-BUG-11 (similar shared-config drift)

---

## ING-BUG-11 — `xlsx_loader` and `xml_loader` import internals from `csv_loader` (private-ish helpers); refactor would break them

**Type:** Tech Debt
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ingest/xlsx_loader.py`, `xml_loader.py`
**Discovered:** Ingest audit 2026-04-28

### Problem
Both import `MAX_ROWS`, `profile_column`, `detect_id_column` from `csv_loader`. These are not in a clear public API — the cross-imports tie all loaders to `csv_loader`'s internals. If `csv_loader` is refactored (likely under any user-centred redesign, e.g. for ING-ENH-01), the others break.

### Expected
Shared helpers live in `ingest/common.py` (or `core/`) and are imported from there.

### Suggested approach
1. Create `ingest/common.py` with the shared helpers
2. Update imports
3. `csv_loader` re-exports for back-compat during transition

### Acceptance criteria
- [ ] Cross-loader imports go through a shared module
- [ ] No regressions

### Related
- ING-BUG-10
- AI-BUG-08 (similar pattern between `gpustack.py` and `ollama.py`)

---

# Enhancements — User-centered

## ING-ENH-01 — No "ingest preview" step; users have no opportunity to confirm encoding, ID column, or column types before commitment

**Type:** Enhancement / UX
**Severity:** High
**Effort:** L
**Affected:** All loaders, dashboard
**Discovered:** Ingest audit 2026-04-28

### Problem
The current flow: user uploads a file → loader runs → DataFrame and Profile are produced → workspace is updated. There is no "is this what you expected?" step. Encoding, ID column, delimiter, sheet selection (XLSX), MODS namespace handling — all decided silently. If any decision is wrong, the user discovers it later through downstream weirdness (Mojibake, wrong joins, missing fields).

For a curator, this is the highest-leverage user-experience improvement: catching ingest mistakes at ingest time costs minutes; catching them after running NER + GND + export costs hours.

### Expected
After upload, the user sees a preview panel:
- First 10 rows of the parsed data
- Detected encoding (with confidence)
- Detected delimiter
- Proposed ID column with alternatives
- Per-column dtype and fill rate
- For XLSX: sheet selector (if multi-sheet)
- For XML: detected namespace, record count
- For PDF: page count, dependency status (pdf2image / pypdf)

The user clicks "Looks right, proceed" or adjusts. Only then does ingest commit.

### Suggested approach
1. Split current `ingest_*` functions into `preview()` and `commit()` phases
2. Preview returns the same `DatasetProfile` plus a head sample
3. UI: preview panel with editable fields
4. Commit applies the user-confirmed config

### Acceptance criteria
- [ ] Preview phase exists and is non-destructive
- [ ] User can adjust encoding, delimiter, ID column, sheet
- [ ] Commit uses user-confirmed config
- [ ] Existing single-shot ingest paths still work for tests / CLI

### Related
- ING-BUG-01, ING-BUG-02, ING-BUG-03 (all close out partially)
- EXT-ENH-03 (Sammlungsstatus) — preview is the natural entry to that view
- Strategic: this is the most user-impactful single ingest enhancement

---

## ING-ENH-02 — No folder-drop ingest; the architecture document mentioned "alle Daten in einen Ordner werfen" but no such code exists

**Type:** Enhancement
**Severity:** High
**Effort:** M
**Affected:** New module, dashboard
**Discovered:** Ingest audit 2026-04-28

### Problem
You described early in the project the wish for a workflow where curators throw all collection data — CSVs, images, PDFs, XML — into a single folder and the pipeline picks it up. Today, ingest is per-file: the user uploads each file separately. For a collection with 1 metadata CSV plus 5,000 images plus a few PDFs, this is not feasible.

`scan_image_directory` exists for images but is not wired through to a unified collection-level intake. There is no orchestrator that says "I see one CSV, 5,000 JPEGs, and 12 PDFs — which goes with which?"

### Expected
A `Collection` ingest workflow:
1. User points the dashboard at a folder (local path or upload)
2. The system scans, classifies files by type, proposes pairings (image filenames matched against CSV ID column values)
3. Preview shows: "1 metadata file, 5,000 images, 12 PDFs. 4,847 image filenames match record IDs in the CSV. 153 unmatched."
4. User confirms, then a single `Collection` object holds all of it

### Suggested approach
1. Define `Collection` data type holding the bundled artifacts
2. New `ingest/folder.py` that scans, classifies, proposes
3. Image-to-record matching as a configurable rule (filename = record_id; filename contains record_id; etc.)
4. Dashboard: folder-drop UI with preview
5. Same preview-then-commit pattern as ING-ENH-01

### Acceptance criteria
- [ ] Folder ingest exists end-to-end
- [ ] File classification covers all five existing loaders
- [ ] Image-to-record matching with reportable match rate
- [ ] Preview before commit
- [ ] Documentation

### Related
- ING-ENH-01 (preview pattern)
- EXT-ENH-03 (Sammlungsstatus)
- Strategic: directly enables the folder-drop UX you've described

---

## ING-ENH-03 — `DatasetProfile` does not record loader version, ingest timestamp, or chosen options

**Type:** Enhancement / Provenance
**Severity:** Medium
**Effort:** S
**Affected:** `src/kwb/ingest/*`, `core/models.py` (`DatasetProfile`)
**Discovered:** Ingest audit 2026-04-28

### Problem
`DatasetProfile` records `source_path`, `source_name`, row/column counts, ID column, encoding, BOM, line ending. It does not record:
- Ingest timestamp
- Loader version (different debussy versions may parse differently)
- Confirmed-vs-detected choices (was the encoding detected or chosen by user?)
- Sheet name (XLSX) or namespace (XML)
- MAX_ROWS in effect at ingest time
- Pre-ingest file hash (so re-ingests can detect changes)

A user who comes back to a workspace months later cannot answer "where did this data come from and how was it loaded?"

### Expected
Profile carries full ingest provenance, mirroring the broader provenance push (CORE-ENH-03, EXT-ENH-01).

### Suggested approach
1. Extend `DatasetProfile` with `ingested_at`, `loader`, `loader_version`, `loader_options` (dict), `source_hash`
2. All loaders populate these
3. UI: ingest provenance visible in workspace details

### Acceptance criteria
- [ ] Profile carries provenance
- [ ] All loaders populate
- [ ] Round-trip preserved
- [ ] UI surface

### Related
- CORE-ENH-03 (provenance fields, project-wide)
- AI-BUG-02 (batch provenance)

---

## ING-ENH-04 — Dependency requirements (`chardet`, `pdf2image`, `pypdf`, `openpyxl`) checked late and per-call; a "system check" view would prevent surprise

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** `csv_loader.py`, `pdf_loader.py`, `xlsx_loader.py`, dashboard
**Discovered:** Ingest audit 2026-04-28

### Problem
A user installs debussy and tries to load a PDF, gets `PDFLoadError("PDF support requires pdf2image or pypdf")`. They install `pypdf`, try again, get a "fallback" pseudo-result (ING-BUG-07). They install `pdf2image`, get `cannot import name 'convert_from_path' from 'pdf2image'` because they need *poppler* on the system too. Each step is a separate friction-fail loop.

XLSX has the same pattern: error on first use ("openpyxl required"). Chardet does not error but silently degrades (ING-BUG-01).

### Expected
A "System check" panel in the dashboard, also runnable via CLI: lists every optional capability, shows which are working, with install instructions for the missing ones. User sees the full picture once.

### Suggested approach
1. Build `kwb.system_check` module that probes for each optional dependency
2. CLI: `python -m kwb.cli system-check`
3. Dashboard: "Funktionsübersicht" panel
4. Each missing dependency shows install command + link to docs

### Acceptance criteria
- [ ] System-check module exists
- [ ] CLI and dashboard both expose it
- [ ] All optional deps are listed
- [ ] Install commands accurate per OS

### Related
- ING-BUG-07 (PDF fallback)
- AI-BUG-05 / AI-BUG-09 (provider self-test) — same pattern

---

## ING-ENH-05 — `csv_loader.split_multivalued` is the only multi-value handler; XLSX and XML have no equivalent

**Type:** Enhancement
**Severity:** Medium
**Effort:** S
**Affected:** `xlsx_loader.py`, `xml_loader.py`
**Discovered:** Ingest audit 2026-04-28

### Problem
Multi-valued semicolon-separated cells are a GLAM convention. CSV loader has `split_multivalued`. The XLSX loader produces all-string columns the same way as CSV — but offers no equivalent split helper, so callers either re-implement it or skip it. XML loader hard-codes semicolon-joining for `subjects` and `name`, but doesn't expose a generic split.

The user gets inconsistent treatment of multi-value fields depending on the source format.

### Expected
A shared `split_multivalued` helper usable across all formats with consistent semantics.

### Suggested approach
1. Move `split_multivalued` to `ingest/common.py`
2. Document the semicolon convention
3. UI: "split multi-value fields" toggle works regardless of source format

### Acceptance criteria
- [ ] Shared helper
- [ ] Used identically across formats
- [ ] Documented
- [ ] Test parity

### Related
- ING-BUG-11 (cross-loader imports)

---

## ING-ENH-06 — `image_loader.ingest_image` always loads base64 by default, which is wasteful for directory scans

**Type:** Enhancement
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ingest/image_loader.py`
**Discovered:** Ingest audit 2026-04-28

### Problem
`ingest_image(path, load_base64=True)` defaults to loading base64 content. A scan of 8,000 images at default settings holds ~8 GB of base64 strings in memory. `scan_image_directory` overrides this to `False`, but anyone calling `ingest_image` directly gets the heavy default.

The user doesn't typically know which call path they're in. For interactive workflows, the default should be light; for analysis runs, base64 is loaded on demand.

### Expected
Default `load_base64=False`. Callers that need it pass `True`. Document the memory cost.

### Suggested approach
1. Flip the default
2. Audit callers; add `load_base64=True` where actually needed
3. Document memory expectations

### Acceptance criteria
- [ ] Default flipped
- [ ] Callers reviewed
- [ ] Memory expectations documented

### Related
- General performance / footprint concern

---

## ING-ENH-07 — XML loader hard-codes English MODS field names but data is bilingual; users see English column headers next to German content

**Type:** Enhancement / Localisation
**Severity:** Low
**Effort:** S
**Affected:** `src/kwb/ingest/xml_loader.py` — `_extract_mods_record()`
**Discovered:** Ingest audit 2026-04-28

### Problem
Resulting columns: `title`, `subtitle`, `name`, `place_of_origin`, `date_issued`, `date_created`, `language`, `physical_form`, `extent`, `abstract`, `subjects`, etc. — all English. The dashboard, error messages, and most curator-facing text in debussy is German. The result: a German-language workspace with mixed-language column names.

This is minor on its own, but is a small symptom of a larger pattern: language choice is implicit per file.

### Expected
Loader-produced column names match the dashboard locale. Either default to German for German-installed instances, or make column-name locale a workspace setting.

### Suggested approach
1. Add a `locale` parameter to `ingest_xml`
2. German label map for MODS fields
3. Document
4. Same approach extensible to other loaders

### Acceptance criteria
- [ ] Locale-aware column naming
- [ ] German labels for MODS
- [ ] Documentation

### Related
- General localisation concern

---

# Summary

| ID | Type | Severity | Effort | Title (short) |
|---|---|---|---|---|
| ING-BUG-01 | Bug | High | S | Encoding detection silent UTF-8 fallback |
| ING-BUG-02 | Bug | High | M | Encoding chain decodes Mojibake silently |
| ING-BUG-03 | Bug | High | M | `detect_id_column` returns wrong unique column |
| ING-BUG-04 | Bug | Medium | S | `MAX_ROWS=50_000` hardcoded |
| ING-BUG-05 | Bug | Medium | S | Bare `except` in image dim extraction |
| ING-BUG-06 | Bug | Medium | S | MIME mismatch in image scan |
| ING-BUG-07 | Bug | Medium | S | PDF pypdf fallback misleading |
| ING-BUG-08 | Bug | Medium | S | XML loose namespace fallback |
| ING-BUG-09 | Bug | High | M | XML extraction loses repeated structures |
| ING-BUG-10 | Bug | Low | S | `_NULLISH` set duplicated |
| ING-BUG-11 | Tech Debt | Low | S | Cross-loader private imports |
| ING-ENH-01 | Enhancement | High | L | Ingest preview / confirmation step |
| ING-ENH-02 | Enhancement | High | M | Folder-drop ingest |
| ING-ENH-03 | Enhancement | Medium | S | Ingest provenance in `DatasetProfile` |
| ING-ENH-04 | Enhancement | Medium | S | System check / dependency overview |
| ING-ENH-05 | Enhancement | Medium | S | Shared `split_multivalued` |
| ING-ENH-06 | Enhancement | Low | S | `load_base64=False` default |
| ING-ENH-07 | Enhancement | Low | S | XML column localisation |

## Cross-references with previous audits

- ING-BUG-03 (wrong ID column) — same family as EXT-BUG-06 / EXT-BUG-07 (wrong default, no confirmation)
- ING-ENH-01 (ingest preview) closes the user-side of ING-BUG-01, BUG-02, BUG-03 simultaneously
- ING-ENH-02 (folder drop) is the foundation for the EXT-ENH-03 Sammlungsstatus view to feel natural
- ING-ENH-03 (ingest provenance) extends CORE-ENH-03 / EXT-ENH-01 / AI-BUG-02 into the loader layer
- ING-ENH-04 (system check) extends AI-BUG-05 / AI-BUG-09 (provider self-test) into a unified pattern

## Files audited so far (cumulative)

- `src/kwb/core/` — `debussy-core-audit-issues.md` (14 issues)
- `src/kwb/analyze/` — `debussy-analyze-enrich-audit-issues.md`
- `src/kwb/enrich/` — `debussy-analyze-enrich-audit-issues.md`
- `src/kwb/ai/` — `debussy-ai-edtf-audit-issues.md`
- `src/kwb/normalize/edtf.py` — `debussy-ai-edtf-audit-issues.md`
- `src/kwb/ingest/` — this document

## Files not yet audited

- `src/kwb/api/` — explicitly deferred until user-centered redesign direction is decided
- `src/kwb/export/`, `src/kwb/report/` — touched only via cross-references
- `tests/` — sampled audit recommended

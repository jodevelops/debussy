#!/usr/bin/env python3
"""
Apply cluster labels to debussy GitHub issues.

Phase 1 (lookup): Loads all issues, fuzzy-matches each audit-ID to a GitHub
issue number, writes audit-to-github-mapping.json.

Phase 2 (apply): Creates the 12 cluster labels (idempotent), applies labels
to each matched issue. Dry-runs first; user must type 'yes' to execute.

Usage:
    export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
    python3 apply_cluster_labels.py lookup
    # (review/edit audit-to-github-mapping.json if needed)
    python3 apply_cluster_labels.py apply
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

REPO = "jodevelops/debussy"
GITHUB_API = "https://api.github.com"
WORK_DIR = Path(".")

AUDIT_FILES = [
    "debussy-core-audit-issues.md",
    "debussy-analyze-enrich-audit-issues.md",
    "debussy-ai-edtf-audit-issues.md",
    "debussy-ingest-audit-issues.md",
    "debussy-export-report-tests-audit-issues.md",
]

LOOKUP_FILE = "audit-to-github-mapping.json"
LABELS_FILE = "cluster-labels.json"
LABEL_MAP_FILE = "cluster-label-map.json"

CONFIDENT_SCORE = 0.65
RUNNER_UP_GAP = 0.15
MINIMUM_SCORE = 0.20


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if not t:
        sys.exit("ERROR: GITHUB_TOKEN environment variable is not set.")
    return t


def _request(method: str, path: str, payload=None):
    url = GITHUB_API + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "debussy-cluster-labeler",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        try:
            body = json.loads(body_txt)
        except Exception:
            body = {"raw": body_txt}
        return e.code, body
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: Network failure: {e.reason}")


def fetch_all_issues():
    issues = []
    page = 1
    while True:
        status, body = _request("GET", f"/repos/{REPO}/issues?state=all&per_page=100&page={page}")
        if status != 200 or not isinstance(body, list):
            sys.exit(f"ERROR: Failed to fetch issues page {page}: HTTP {status}")
        page_issues = [i for i in body if "pull_request" not in i]
        issues.extend(page_issues)
        if len(body) < 100:
            break
        page += 1
        time.sleep(0.2)
    return issues


ISSUE_HEADER_RE = re.compile(r"^## ([A-Z]+-[A-Z]+-\d+)\s*[—\-–]\s*(.+?)\s*$")


def parse_audit_files(work_dir: Path):
    audit_titles = {}
    for fname in AUDIT_FILES:
        path = work_dir / fname
        if not path.exists():
            print(f"  WARNING: {fname} not found, skipping")
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = ISSUE_HEADER_RE.match(line)
            if m:
                audit_id, title = m.group(1), m.group(2).strip()
                if audit_id in audit_titles:
                    print(f"  WARNING: duplicate {audit_id} in {fname}, keeping first")
                else:
                    audit_titles[audit_id] = title
    return audit_titles


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in",
    "on", "at", "for", "with", "by", "from", "and", "or", "but", "as", "it",
    "no", "not", "this", "that", "these", "those", "user", "users",
    "users'", "value", "values", "field", "fields", "data", "issue", "issues",
    "audit", "fix", "bug", "der", "die", "das", "und", "oder",
})


def _tokens(s: str):
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return {t for t in s.split() if t and t not in _STOPWORDS and len(t) > 2}


def _has_strong_anchor(audit_title, github_title):
    audit_anchors = set(re.findall(r"[a-z]+(?:_[a-z0-9]+)+|[a-z]+\.[a-z_]+|[A-Z][A-Za-z]+[0-9]", audit_title))
    if not audit_anchors:
        return False
    return any(a in github_title for a in audit_anchors)


def score_match(audit_title, github_title):
    a_tok = _tokens(audit_title)
    g_tok = _tokens(github_title)
    if not a_tok or not g_tok:
        return 0.0
    overlap = len(a_tok & g_tok) / len(a_tok)
    seq_sim = SequenceMatcher(None, audit_title.lower(), github_title.lower()).ratio()
    anchor = 0.20 if _has_strong_anchor(audit_title, github_title) else 0.0
    return min(1.0, 0.55 * overlap + 0.25 * seq_sim + anchor)


def best_matches(audit_title, issues, top_n=3):
    scored = [(score_match(audit_title, i["title"]), i) for i in issues]
    scored.sort(key=lambda x: -x[0])
    return [(s, i) for s, i in scored[:top_n] if s >= MINIMUM_SCORE]


def phase_lookup():
    print(f"Phase 1: Building audit-ID → GitHub-issue lookup for {REPO}\n")
    print("Loading audit titles from Markdown files...")
    audit_titles = parse_audit_files(WORK_DIR)
    print(f"  Found {len(audit_titles)} audit issues\n")

    print("Fetching all issues from GitHub...")
    issues = fetch_all_issues()
    print(f"  Loaded {len(issues)} issues (PRs filtered)\n")

    print("Matching...")
    confident, unclear, nomatch = {}, {}, []
    for audit_id, audit_title in sorted(audit_titles.items()):
        candidates = best_matches(audit_title, issues, top_n=3)
        if not candidates:
            nomatch.append(audit_id)
            continue
        best_score = candidates[0][0]
        runner_up_score = candidates[1][0] if len(candidates) > 1 else 0.0
        gap = best_score - runner_up_score
        if best_score >= CONFIDENT_SCORE and gap >= RUNNER_UP_GAP:
            issue = candidates[0][1]
            confident[audit_id] = {
                "github_number": issue["number"],
                "github_title": issue["title"],
                "audit_title": audit_title,
                "score": round(best_score, 3),
            }
        else:
            unclear[audit_id] = [
                {"github_number": i["number"], "github_title": i["title"], "score": round(s, 3)}
                for s, i in candidates
            ]

    duplicates = {}
    for audit_id, info in confident.items():
        n = info["github_number"]
        duplicates.setdefault(n, []).append(audit_id)
    duplicates = {n: ids for n, ids in duplicates.items() if len(ids) > 1}

    out = {
        "_comment": "Audit-ID -> GitHub-issue lookup. Edit 'unclear' manually: "
                    "pick a github_number and move into 'confident'. Then run 'apply'.",
        "repo": REPO,
        "confident": confident,
        "unclear": unclear,
        "no_match": nomatch,
        "duplicates_detected": duplicates,
    }
    Path(LOOKUP_FILE).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"  Confident matches:  {len(confident):3d}")
    print(f"  Unclear:            {len(unclear):3d}  (need manual review)")
    print(f"  No match found:     {len(nomatch):3d}")
    print(f"  Duplicate targets:  {len(duplicates):3d}")
    print("=" * 60)
    print(f"\nLookup written to {LOOKUP_FILE}\n")

    if unclear:
        print("UNCLEAR — manual review required. Open the file and for each entry,")
        print("pick the right github_number and move into 'confident'.\n")
        for audit_id, cands in list(unclear.items())[:10]:
            print(f"  {audit_id}: {audit_titles[audit_id][:60]}")
            for c in cands:
                print(f"      [{c['score']:.2f}] #{c['github_number']}: {c['github_title'][:60]}")
            print()
        if len(unclear) > 10:
            print(f"  ... and {len(unclear) - 10} more (see {LOOKUP_FILE})\n")

    if nomatch:
        print("NO MATCH — these audit IDs found no candidate above threshold:")
        for audit_id in nomatch:
            print(f"  {audit_id}: {audit_titles[audit_id][:70]}")
        print()

    if duplicates:
        print("DUPLICATES — same GitHub issue targeted by multiple audit IDs:")
        for n, ids in duplicates.items():
            print(f"  #{n} <- {', '.join(ids)}")
        print()

    if not unclear and not nomatch and not duplicates:
        print("All matches confident. Ready to run 'apply'.")


def phase_apply():
    print(f"Phase 2: Apply cluster labels to {REPO}\n")
    if not Path(LOOKUP_FILE).exists():
        sys.exit(f"ERROR: {LOOKUP_FILE} not found. Run 'lookup' first.")
    lookup = json.loads(Path(LOOKUP_FILE).read_text(encoding="utf-8"))
    confident = lookup.get("confident", {})
    if not confident:
        sys.exit("ERROR: No confident matches in lookup file.")
    if lookup.get("unclear"):
        ans = input(f"WARNING: {len(lookup['unclear'])} unclear matches will be skipped. Continue? [yes/no] ").strip()
        if ans.lower() != "yes":
            sys.exit("Aborted.")

    labels = json.loads(Path(LABELS_FILE).read_text(encoding="utf-8"))
    label_map = json.loads(Path(LABEL_MAP_FILE).read_text(encoding="utf-8"))
    label_map = {k: v for k, v in label_map.items() if not k.startswith("_")}

    print(f"Step 1: Ensure {len(labels)} cluster labels exist...")
    for lbl in labels:
        status, body = _request("POST", f"/repos/{REPO}/labels", payload={
            "name": lbl["name"], "color": lbl["color"], "description": lbl["description"],
        })
        if status == 201:
            print(f"  + created  {lbl['name']}")
        elif status == 422:
            print(f"  · exists   {lbl['name']}")
        else:
            print(f"  ! HTTP {status} for {lbl['name']}: {body}")
        time.sleep(0.3)

    plan, skipped = [], []
    for audit_id, info in confident.items():
        labels_for_id = label_map.get(audit_id)
        if not labels_for_id:
            skipped.append(audit_id)
            continue
        plan.append((audit_id, info["github_number"], labels_for_id))

    print(f"\nStep 2: Dry-run plan — {len(plan)} issues to label, {len(skipped)} skipped\n")
    for audit_id, num, lbls in plan[:20]:
        print(f"  #{num:4d}  {audit_id:14s}  →  {', '.join(lbls)}")
    if len(plan) > 20:
        print(f"  ... and {len(plan) - 20} more")
    if skipped:
        print(f"\nSkipped (no entry in {LABEL_MAP_FILE}):")
        for sid in skipped:
            print(f"  {sid}")

    ans = input(f"\nApply labels to {len(plan)} issues? [yes/no] ").strip()
    if ans.lower() != "yes":
        sys.exit("Aborted, no labels applied.")

    print("\nStep 3: Applying labels...")
    successes, failures = 0, []
    for audit_id, num, lbls in plan:
        status, body = _request("POST", f"/repos/{REPO}/issues/{num}/labels", payload={"labels": lbls})
        if status == 200:
            successes += 1
            if successes % 10 == 0:
                print(f"  ... {successes} done")
        else:
            failures.append((audit_id, num, status))
            print(f"  ! HTTP {status} for {audit_id} (#{num}): {body}")
        time.sleep(0.3)

    print(f"\n{'=' * 60}")
    print(f"  Successes: {successes}")
    print(f"  Failures:  {len(failures)}")
    print("=" * 60)
    if failures:
        print("\nFailures (re-running apply is safe):")
        for audit_id, num, status in failures:
            print(f"  {audit_id} #{num}: HTTP {status}")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("lookup", "apply"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "lookup":
        phase_lookup()
    else:
        phase_apply()


if __name__ == "__main__":
    main()

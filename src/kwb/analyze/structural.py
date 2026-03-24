"""Structural analysis — rule-based quality checks."""
from __future__ import annotations
import pandas as pd
from kwb.core.models import AnalysisReport, Finding, FindingCategory, Severity
from kwb.analyze.quality_measures import compute_quality_measures

def _get_affected_ids(df, mask, id_col, limit=10):
    if not id_col or id_col not in df.columns: return []
    try: return df.loc[mask, id_col].head(limit).tolist()
    except: return []

def check_missing_values(df, profile):
    findings=[]; dfa=df.replace("",pd.NA)
    for cp in profile.columns:
        col=cp.name; mr=1.0-cp.fill_rate
        if mr==0: continue
        if mr>=0.95: sev,msg=Severity.INFO,f"Column '{col}' nearly empty ({cp.fill_rate:.1%})"
        elif mr>=0.5: sev,msg=Severity.WARNING,f"Column '{col}' half empty ({cp.fill_rate:.1%})"
        elif mr>=0.1: sev,msg=Severity.WARNING,f"Column '{col}' has gaps ({cp.fill_rate:.1%})"
        else: sev,msg=Severity.INFO,f"Column '{col}' minor gaps ({cp.fill_rate:.1%})"
        mask=dfa[col].isna()
        findings.append(Finding(category=FindingCategory.MISSING_VALUES,severity=sev,message=msg,
            column=col,record_ids=_get_affected_ids(df,mask,profile.id_column),
            evidence={"fill_rate":cp.fill_rate,"missing_count":cp.total_count-cp.non_null_count}))
    return findings

def check_duplicate_records(df, profile):
    if not profile.id_column:
        return [Finding(category=FindingCategory.SCHEMA_MISMATCH,severity=Severity.CRITICAL,
                       message="No unique ID column detected")]
    dupes=df[df.duplicated(subset=[profile.id_column],keep=False)]
    if not len(dupes): return []
    dupe_ids=dupes[profile.id_column].unique().tolist()[:20]
    return [Finding(category=FindingCategory.DUPLICATE_RECORDS,severity=Severity.CRITICAL,
                   message=f"Found {len(dupes)} rows with duplicate IDs",
                   column=profile.id_column,record_ids=dupe_ids,
                   evidence={"duplicate_row_count":len(dupes)})]

def check_encoding_issues(df, profile):
    findings=[]
    patterns={"\u00c3\u00a4":"UTF-8/Latin-1 ae-umlaut","\u00c3\u00b6":"UTF-8/Latin-1 oe-umlaut",
               "\u00c3\u00bc":"UTF-8/Latin-1 ue-umlaut","\u00c2":"Stray Latin-1 artifact"}
    for col in df.columns:
        cs=df[col].astype(str)
        for pat,desc in patterns.items():
            mask=cs.str.contains(pat,na=False)
            if mask.any():
                findings.append(Finding(category=FindingCategory.ENCODING_ISSUES,severity=Severity.WARNING,
                    message=f"Encoding artifact in '{col}': {desc} ({mask.sum()} occurrences)",
                    column=col,record_ids=_get_affected_ids(df,mask,profile.id_column,5),
                    evidence={"pattern":pat,"count":int(mask.sum())}))
    if profile.has_bom:
        findings.append(Finding(category=FindingCategory.ENCODING_ISSUES,severity=Severity.INFO,
            message="File has UTF-8 BOM"))
    if profile.line_ending=="CRLF":
        findings.append(Finding(category=FindingCategory.ENCODING_ISSUES,severity=Severity.INFO,
            message="File uses Windows CRLF line endings"))
    return findings

def check_format_inconsistency(df, profile):
    findings=[]
    for col in df.columns:
        vals=df[col].replace("",pd.NA).dropna().astype(str)
        if not len(vals): continue
        semi=vals.str.contains(";",na=False); comma=vals.str.contains(",",na=False)
        if semi.any() and comma.any():
            both=semi&comma
            if both.any():
                findings.append(Finding(category=FindingCategory.FORMAT_INCONSISTENCY,severity=Severity.WARNING,
                    message=f"Column '{col}' uses mixed delimiters (;  and ,) in {both.sum()} rows",
                    column=col,record_ids=_get_affected_ids(df,both,profile.id_column,5),
                    evidence={"both_rows":int(both.sum())}))
        ws=vals.str.match(r"^\s+.*|.*\s+$")
        if ws.any():
            findings.append(Finding(category=FindingCategory.FORMAT_INCONSISTENCY,severity=Severity.WARNING,
                message=f"Column '{col}' has leading/trailing whitespace in {ws.sum()} values",
                column=col,record_ids=_get_affected_ids(df,ws,profile.id_column,5),
                evidence={"whitespace_count":int(ws.sum())}))
    return findings

def check_term_variants(df, profile):
    findings=[]
    for col in df.columns:
        vals=df[col].replace("",pd.NA).dropna().astype(str)
        if not len(vals) or len(vals.unique())>1000: continue
        all_terms=[]
        for v in vals:
            for d in [";","|"]:
                if d in v: [all_terms.append(t.strip()) for t in v.split(d)]; break
            else: all_terms.append(v.strip())
        lower_map={}
        for t in all_terms:
            if t: lower_map.setdefault(t.lower(),[]).append(t)
        variants=[{"canonical":k,"forms":list(set(v)),"counts":{f:v.count(f) for f in set(v)}}
                  for k,v in lower_map.items() if len(set(v))>1]
        if variants:
            findings.append(Finding(category=FindingCategory.TERM_VARIANTS,severity=Severity.WARNING,
                message=f"Column '{col}' has {len(variants)} term variant groups",
                column=col,evidence={"variant_count":len(variants),"examples":variants[:5]},
                suggestion="Normalize to consistent form before export"))
    return findings

def check_cross_file_linkage(datasets):
    findings=[]
    if len(datasets)<2: return findings
    id_sets=[(p.source_name,set(df[p.id_column].dropna().astype(str))) for df,p in datasets if p.id_column]
    for i,(na,ia) in enumerate(id_sets):
        for nb,ib in id_sets[i+1:]:
            shared=ia&ib; oa=ia-ib; ob=ib-ia
            for n,o,t in [(na,oa,nb),(nb,ob,na)]:
                if o:
                    findings.append(Finding(category=FindingCategory.ORPHAN_RECORDS,severity=Severity.WARNING,
                        message=f"{len(o)} records in '{n}' have no match in '{t}'",
                        record_ids=sorted(o)[:10],evidence={"orphan_count":len(o),"shared_count":len(shared)}))
            if shared:
                findings.append(Finding(category=FindingCategory.CROSS_FILE_MISMATCH,severity=Severity.INFO,
                    message=f"'{na}' and '{nb}' share {len(shared)} record IDs",
                    evidence={"shared_count":len(shared),"only_in_a":len(oa),"only_in_b":len(ob)}))
    return findings

def check_gnd_coverage(df, profile):
    findings=[]
    gnd_id_cols=[c for c in df.columns if "gnd_id" in c.lower()]
    if not gnd_id_cols: return findings
    gnd_k_cols=[c for c in df.columns if "konfidenz" in c.lower()]
    gnd_b_cols=[c for c in df.columns if "begruendung" in c.lower()]
    total=filled=no_match=api_rec=0
    for c in gnd_id_cols:
        v=df[c].replace("",pd.NA); total+=len(v); filled+=v.notna().sum()
    for c in gnd_b_cols:
        v=df[c].astype(str)
        no_match+=v.str.contains("Kein GND-Match",case=False,na=False).sum()
        api_rec+=v.str.contains("API-Abfrage empfohlen",case=False,na=False).sum()
    if total>0:
        cov=filled/total
        findings.append(Finding(category=FindingCategory.GND_MATCH_MISSING,
            severity=Severity.WARNING if cov<0.5 else Severity.INFO,
            message=f"GND coverage: {filled}/{total} slots ({cov:.1%})",
            evidence={"total_ne_slots":total,"filled_gnd_ids":int(filled),
                      "coverage_rate":round(cov,4),"no_match_count":no_match,"api_recommended":api_rec},
            suggestion=f"{api_rec} entries recommend API lookup"))
    return findings

SINGLE_DATASET_CHECKS=[check_missing_values,check_duplicate_records,check_encoding_issues,
                        check_format_inconsistency,check_term_variants,check_gnd_coverage]

def analyze_datasets(datasets):
    report=AnalysisReport()
    for df,profile in datasets:
        report.datasets.append(profile)
        for fn in SINGLE_DATASET_CHECKS: report.findings.extend(fn(df,profile))
    if len(datasets)>1: report.findings.extend(check_cross_file_linkage(datasets))
    by=report.findings_by_severity
    report.summary={"total_findings":len(report.findings),"critical":len(by[Severity.CRITICAL]),
        "warnings":len(by[Severity.WARNING]),"info":len(by[Severity.INFO]),
        "datasets_analyzed":len(datasets),"total_records":sum(p.row_count for p in report.datasets),
        "total_columns":sum(p.column_count for p in report.datasets)}
    report.quality_measures = compute_quality_measures(report)
    return report

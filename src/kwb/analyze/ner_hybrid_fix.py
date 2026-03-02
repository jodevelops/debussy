# This shows the fixed ner_hybrid function — to be pasted into ner.py

def ner_hybrid_FIXED(
    df, columns, provider=None, id_column=None,
    sample_size=None, model=None, system_prompt="",
    use_spacy=True, use_llm=True,
):
    """Fixed: deduplicates after merge, sets source='hybrid' on overlap."""
    working = df.copy()
    if sample_size and sample_size < len(working):
        working = working.sample(n=sample_size, random_state=42)

    texts = []
    for _, row in working.iterrows():
        rid = str(row.get(id_column, "")) if id_column else ""
        for col in columns:
            if col in row and pd.notna(row[col]) and str(row[col]).strip():
                texts.append({
                    "record_id": rid,
                    "text": str(row[col]).strip(),
                    "column": col,
                })

    result = NERResult()
    batch = None

    spacy_set: dict[str, Entity] = {}
    llm_set: dict[str, Entity] = {}

    if use_spacy:
        for e in ner_spacy(texts):
            k = f"{e.record_id}||{e.column}||{e.text}||{e.entity_type.value}"
            if k not in spacy_set or e.confidence > spacy_set[k].confidence:
                spacy_set[k] = e

    if use_llm and provider:
        llm_ents, batch = ner_llm(texts, provider, model=model, system_prompt=system_prompt)
        for e in llm_ents:
            k = f"{e.record_id}||{e.column}||{e.text}||{e.entity_type.value}"
            if k not in llm_set or e.confidence > llm_set[k].confidence:
                llm_set[k] = e
        result.batch_report = batch

    # Merge: LLM wins on confidence, mark overlaps as "hybrid"
    merged: dict[str, Entity] = {}
    for k, e in spacy_set.items():
        merged[k] = e
    for k, e in llm_set.items():
        if k in merged:
            # Both found it — use LLM result (higher quality) but mark as hybrid
            winner = e if e.confidence >= merged[k].confidence else merged[k]
            winner.source = "hybrid"
            merged[k] = winner
        else:
            merged[k] = e

    result.entities = list(merged.values())
    return result

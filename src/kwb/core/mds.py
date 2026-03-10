"""
Mindestdatenstandard (MDS) validation.

Checks whether required and recommended MDS fields are mapped and filled.
Supports MDS 1.1 standard plus custom field definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class MdsFieldRequirement(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


@dataclass
class MdsFieldDef:
    """Definition of one MDS field."""
    mds_name: str                     # e.g. "Identifikator"
    goobi_type: str                   # expected Goobi metadata type
    requirement: MdsFieldRequirement = MdsFieldRequirement.REQUIRED
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "mds_name": self.mds_name,
            "goobi_type": self.goobi_type,
            "requirement": self.requirement.value,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: dict) -> "MdsFieldDef":
        return MdsFieldDef(
            mds_name=d.get("mds_name", ""),
            goobi_type=d.get("goobi_type", ""),
            requirement=MdsFieldRequirement(d.get("requirement", "required")),
            note=d.get("note", ""),
        )


# MDS 1.1 standard fields (minimaldatensatz.de)
MDS_11_FIELDS: list[MdsFieldDef] = [
    MdsFieldDef("Identifikator", "CatalogIDDigital", MdsFieldRequirement.REQUIRED,
                "Eindeutige ID (UUID, Signatur …)"),
    MdsFieldDef("Titel", "TitleDocMain", MdsFieldRequirement.REQUIRED,
                "Haupttitel des Objekts"),
    MdsFieldDef("Objekttyp", "DocStruct", MdsFieldRequirement.REQUIRED,
                "Art des Objekts (Gemälde, Brief …)"),
    MdsFieldDef("Aufbewahrungsort", "PlaceOfPublication", MdsFieldRequirement.REQUIRED,
                "Institution / Standort"),
    MdsFieldDef("Rechtliche Informationen", "Rights", MdsFieldRequirement.REQUIRED,
                "Lizenz oder Rechtehinweis"),
    MdsFieldDef("Beschreibung", "Description", MdsFieldRequirement.RECOMMENDED,
                "Inhaltliche Beschreibung"),
    MdsFieldDef("Datierung", "DateCreated", MdsFieldRequirement.RECOMMENDED,
                "Entstehungsdatum (EDTF-Format empfohlen)"),
    MdsFieldDef("Abmessungen/Umfang", "Dimensions", MdsFieldRequirement.RECOMMENDED,
                "Maße oder Seitenumfang"),
    MdsFieldDef("Material/Technik", "MaterialDescription", MdsFieldRequirement.RECOMMENDED,
                "Material und Herstellungstechnik"),
    MdsFieldDef("Hersteller/Urheber", "Creator", MdsFieldRequirement.RECOMMENDED,
                "Person oder Körperschaft"),
    MdsFieldDef("Abbildungsnachweis", "Source", MdsFieldRequirement.RECOMMENDED,
                "Bildquelle oder Fotograf"),
    MdsFieldDef("Schlagwörter", "SubjectTopic", MdsFieldRequirement.RECOMMENDED,
                "Thematische Schlagwörter"),
    MdsFieldDef("Herstellungsort", "SubjectGeographic", MdsFieldRequirement.RECOMMENDED,
                "Entstehungsort des Objekts"),
    MdsFieldDef("Sammlung", "singleDigCollection", MdsFieldRequirement.RECOMMENDED,
                "Sammlung oder Bestand"),
]


@dataclass
class MdsFieldResult:
    """Validation result for one MDS field."""
    mds_name: str
    goobi_type: str
    requirement: str      # required / recommended / optional
    mapped: bool          # True if a CSV column is mapped to this goobi_type
    csv_column: str       # which CSV column is mapped (empty if unmapped)
    fill_rate: float      # 0.0–1.0, how many records have a value
    record_count: int     # how many records total
    filled_count: int     # how many records have a non-empty value
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "mds_name": self.mds_name,
            "goobi_type": self.goobi_type,
            "requirement": self.requirement,
            "mapped": self.mapped,
            "csv_column": self.csv_column,
            "fill_rate": round(self.fill_rate, 4),
            "record_count": self.record_count,
            "filled_count": self.filled_count,
            "note": self.note,
        }


@dataclass
class MdsValidationReport:
    """Full MDS validation report."""
    schema_name: str                      # e.g. "MDS 1.1"
    field_results: list[MdsFieldResult] = field(default_factory=list)

    @property
    def required_mapped(self) -> int:
        return sum(1 for f in self.field_results
                   if f.requirement == "required" and f.mapped)

    @property
    def required_total(self) -> int:
        return sum(1 for f in self.field_results if f.requirement == "required")

    @property
    def required_filled(self) -> int:
        return sum(1 for f in self.field_results
                   if f.requirement == "required" and f.fill_rate > 0)

    @property
    def completeness_score(self) -> float:
        """0.0–1.0 score based on required+recommended fill rates."""
        if not self.field_results:
            return 0.0
        weights = {"required": 2.0, "recommended": 1.0, "optional": 0.5}
        total_weight = sum(weights.get(f.requirement, 0.5) for f in self.field_results)
        weighted_fill = sum(
            f.fill_rate * weights.get(f.requirement, 0.5)
            for f in self.field_results if f.mapped
        )
        return weighted_fill / total_weight if total_weight else 0.0

    def to_dict(self) -> dict:
        return {
            "schema_name": self.schema_name,
            "required_mapped": self.required_mapped,
            "required_total": self.required_total,
            "required_filled": self.required_filled,
            "completeness_score": round(self.completeness_score, 4),
            "fields": [f.to_dict() for f in self.field_results],
        }


def validate_mds(
    df: pd.DataFrame,
    field_mappings: list,
    mds_fields: list[MdsFieldDef] | None = None,
    custom_fields: list[MdsFieldDef] | None = None,
) -> MdsValidationReport:
    """
    Validate a DataFrame against MDS field definitions.

    Args:
        df: The dataset DataFrame.
        field_mappings: List of FieldMapping objects from the workspace.
        mds_fields: MDS field definitions (defaults to MDS 1.1).
        custom_fields: Additional custom field definitions.
    """
    schema_name = "MDS 1.1"
    fields = list(mds_fields or MDS_11_FIELDS)
    if custom_fields:
        fields.extend(custom_fields)
        schema_name += " + Benutzerdefiniert"

    # Build mapping lookup: goobi_type → csv_column
    mapping_lookup: dict[str, str] = {}
    for m in field_mappings:
        gt = m.goobi_type if hasattr(m, "goobi_type") else str(m)
        col = m.csv_column if hasattr(m, "csv_column") else ""
        enabled = m.enabled if hasattr(m, "enabled") else True
        if enabled and col:
            mapping_lookup[gt] = col

    results = []
    for fdef in fields:
        csv_col = mapping_lookup.get(fdef.goobi_type, "")
        mapped = bool(csv_col)
        filled_count = 0
        fill_rate = 0.0

        if mapped and csv_col in df.columns:
            non_empty = df[csv_col].replace("", pd.NA).dropna()
            filled_count = len(non_empty)
            fill_rate = filled_count / len(df) if len(df) > 0 else 0.0

        results.append(MdsFieldResult(
            mds_name=fdef.mds_name,
            goobi_type=fdef.goobi_type,
            requirement=fdef.requirement.value,
            mapped=mapped,
            csv_column=csv_col,
            fill_rate=fill_rate,
            record_count=len(df),
            filled_count=filled_count,
            note=fdef.note,
        ))

    return MdsValidationReport(schema_name=schema_name, field_results=results)

"""Variant Agent"""

import asyncio
import warnings
import json
from pathlib import Path
from typing import List
from dataclasses import dataclass
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    select,
    func,
    exc as sa_exc,
)
from duckdb_engine import DuckDBEngineWarning
import pandas as pd
from agents import Agent, ModelSettings, function_tool, RunContextWrapper

warnings.simplefilter("ignore", sa_exc.SAWarning)
warnings.simplefilter("ignore", DuckDBEngineWarning)


class VariantAgentResources:
    """Class to hold Variant Agent resources."""

    def __init__(self, database_file: Path, prompt_file: Path):
        print("Loading Variant resources...")
        self.prompt = prompt_file.read_text(encoding="utf-8")
        print("Variant resources loaded successfully.")

        database_url = f"duckdb:///{database_file}?access_mode=READ_ONLY"
        self.engine = create_engine(database_url)

    def transcripts_summary(self, variant: dict) -> str:
        """Generate a summary of transcript information for a variant."""
        summary = ""
        for transcript in variant.get("transcripts", []):
            summary += (
                f"HGNC: {transcript['hgnc']}, "
                + f"transcript: {transcript['transcript']}, "
                + f"consequences: {', '.join(transcript.get('consequence', []))}, "
                + f"hgvsc: {transcript.get('hgvsc', '<none>')}\n"
            )
        return summary

    def clinvar_summary(self, variant: dict) -> str:
        """Generate a summary of ClinVar information for a variant."""
        if not variant.get("clinvar-preview"):
            return "<no ClinVar data>"
        summary = ""
        for entry in variant["clinvar-preview"]:
            germline_classification = entry.get("classifications", {}).get(
                "germlineClassification", {}
            )
            diseases = filter(
                lambda condition: condition.get("type") == "Disease",
                germline_classification.get("conditions", []),
            )
            if diseases:
                disease_list = []
                for disease in diseases:
                    disease_list.extend(
                        trait.get("name", {}).get("value", "<unknown>")
                        for trait in disease.get("traits", [])
                    )
            else:
                disease_list = ["<unknown>"]
            classification = germline_classification.get("classification", "<unknown>")
            review_status = entry.get("reviewStatus", "<unknown>")
            summary += (
                f"ClinVar ID: {entry.get('accession', '<unknown>')}, "
                + f"Reference allele: {entry.get('refAllele', '<unknown>')}, "
                + f"Alternate allele: {entry.get('altAllele', '<unknown>')}, "
                + f"Allele-specific: {entry.get('isAlleleSpecific', '<unknown>')}, "
                + f"Classification: {classification}, "
                + f"Review Status: {review_status}, "
                + f"Diseases: {', '.join(disease_list)}"
            )
        return summary


@dataclass
class VariantQueryResults:
    """Class to hold variant query results."""

    variants: pd.DataFrame
    total_variants: int


@function_tool
async def query_variants(
    wrapper: RunContextWrapper[VariantAgentResources],
    gene: str | None = None,
    clinvar: List[str] | None = None,
    consequence: List[str] | None = None,
    max_gnomad_freq: float | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Fetch variants, filtered by any combination of:
      - gene (in gene_symbols array)
      - clinvar: List of classifications, at least one of which must appear in the
                 variant's clinvar_classifications array
      - consequence: List of transcript consequences, at least one of which must appear
                     in the variant's transcript_consequences array
      - maximum gnomAD allele frequency
    Supports paging via `limit` and `offset`.
    """
    print("Querying variants with filters:")
    if gene:
        print(f"  Gene: {gene}")
    if clinvar:
        print(f"  ClinVar: {', '.join(clinvar)}")
    if consequence:
        print(f"  Consequence: {', '.join(consequence)}")
    if max_gnomad_freq is not None:
        print(f"  Max gnomAD frequency: {max_gnomad_freq}")
    print(f"  Limit: {limit}, Offset: {offset}")

    def _build_and_execute_query() -> VariantQueryResults:
        with wrapper.context.engine.connect() as conn:
            md = MetaData()
            variants = Table("variants", md, autoload_with=conn)
            var_genes = Table("variant_genes", md, autoload_with=conn)
            var_consequences = Table("variant_consequences", md, autoload_with=conn)
            clinvar_classifications = Table(
                "clinvar_classifications", md, autoload_with=conn
            )

            query = select(variants).distinct()

            if gene:
                query = query.join(
                    var_genes,
                    (var_genes.c.vid == variants.c.vid)
                    & (var_genes.c.chromosome == variants.c.chromosome),
                ).where(var_genes.c.gene_symbol == gene)

            if clinvar:
                query = query.join(
                    clinvar_classifications,
                    (clinvar_classifications.c.vid == variants.c.vid)
                    & (clinvar_classifications.c.chromosome == variants.c.chromosome),
                ).where(clinvar_classifications.c.classification.in_(clinvar))

            if consequence:
                query = query.join(
                    var_consequences,
                    (var_consequences.c.vid == variants.c.vid)
                    & (var_consequences.c.chromosome == variants.c.chromosome),
                ).where(var_consequences.c.consequence.in_(consequence))

            if max_gnomad_freq is not None:
                query = query.where(variants.c.gnomad_af <= max_gnomad_freq)

            total_variants: int = conn.execute(
                select(func.count()).select_from(query.subquery())
            ).scalar_one()

            order_cols = [
                variants.c.chromosome,
                variants.c.begin_pos,
                variants.c.variant_index,
            ]
            query = query.order_by(*(c.asc() for c in order_cols))
            query = query.offset(offset)

            df = pd.read_sql_query(query, conn)
        return VariantQueryResults(variants=df, total_variants=total_variants)

    query_results = await asyncio.to_thread(_build_and_execute_query)
    print(f"Fetched {len(query_results.variants)} variants starting at offset {offset}")

    # Parse JSON column
    query_results.variants["raw"] = query_results.variants["raw"].map(json.loads)

    result_text = ""
    for row in query_results.variants.itertuples(index=False):
        depth_row = (
            f"Total Depth: {row.total_depth}, " f"Allele Depths: {row.allele_depths}"
        )
        result_text += "\n".join(
            [
                "<variant>",
                f"Chromosome: {row.chromosome}",
                f"Position: {row.position}",
                f"Ref Allele: {row.ref_allele}",
                f"Alt Allele: {row.alt_allele}",
                f"Gene Symbols: {', '.join(row.gene_symbols)}",
                f"gnomAD AF: {row.gnomad_af}",
                f"ClinVar Summary: {wrapper.context.clinvar_summary(row.raw)}",
                wrapper.context.transcripts_summary(row.raw),
                f"Genotype: {row.genotype}, GQ: {row.genotype_quality}",
                depth_row,
                f"Maternal Genotype: {row.maternal_genotype}, ",
                f"Paternal Genotype: {row.paternal_genotype}",
                f"Variant Type: {row.variant_type}",
                "</variant>\n",
            ]
        )
    result_text = (
        f"Total variants found: {query_results.total_variants}\n"
        + f"Displaying {len(query_results.variants)} variants at offset {offset}:\n"
        + result_text
    )
    return result_text


def create_variant_agent(resources: VariantAgentResources) -> Agent:
    """Create a variant agent."""
    variant_agent = Agent(
        name="Variant Assistant",
        instructions=resources.prompt,
        tools=[query_variants],
        model="gpt-5",
        model_settings=ModelSettings(tool_choice="required"),
    )
    return variant_agent

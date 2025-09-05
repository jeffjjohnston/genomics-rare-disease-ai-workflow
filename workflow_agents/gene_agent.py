"""Gene Agent"""

from pathlib import Path
import pandas as pd
from pydantic import BaseModel
from agents import Agent, ModelSettings, function_tool, RunContextWrapper


class GeneAgentResources:
    """Class to hold Gene Agent resources."""

    def __init__(self, phenotypes_to_gene_file: Path, prompt_file: Path):
        print("Loading Gene resources...")
        self.prompt = prompt_file.read_text(encoding="utf-8")
        self.phenotypes_to_gene_df = pd.read_csv(phenotypes_to_gene_file, sep="\t")
        self.phenotypes_to_gene_df = self.phenotypes_to_gene_df[
            ["hpo_id", "gene_symbol"]
        ]
        self.phenotypes_to_gene_df = self.phenotypes_to_gene_df.drop_duplicates()
        print("Gene resources loaded successfully.")

    def associated_genes(self, hpo_ids: list[str], max_genes=30) -> pd.DataFrame:
        """Get associated genes for a given HPO ID."""
        matches = self.phenotypes_to_gene_df[
            self.phenotypes_to_gene_df["hpo_id"].isin(hpo_ids)
        ].copy()

        # group by gene and count occurrences, add comma-separated list of hpo_ids
        matches = (
            matches.groupby("gene_symbol")
            .agg(hpo_ids=("hpo_id", lambda x: ", ".join(x)), count=("hpo_id", "size"))
            .reset_index()
        )

        # sort by count descending
        matches = matches.sort_values(by="count", ascending=False).head(max_genes)
        matches.reset_index(drop=True, inplace=True)
        return matches


@function_tool
async def ranked_genes_for_hpo_terms(
    wrapper: RunContextWrapper[GeneAgentResources], term_ids: list[str]
) -> str:
    """Get a ranked list of genes for a set of HPO terms.
    Args:
        term_ids (list[str]): List of HPO term IDs.
    Returns:
        str: Formatted string of gene symbols ranked by HPO term count
    """
    print(f"Finding genes for HPO terms: {', '.join(term_ids)}")

    matches = wrapper.context.associated_genes(term_ids)

    results = []
    for row in matches.itertuples(index=False):
        results.append(
            f"Gene: {row.gene_symbol}; "
            f"HPO IDs: {row.hpo_ids}; "
            f"Count: {row.count}"
        )
    return "\n".join(results)


class RankedGene(BaseModel):
    """Model for ranked gene."""

    gene: str
    """ Gene symbol """

    rank: int
    """ Rank based on HPO term count """

    reasoning: str
    """ Reasoning for the ranking"""

    hpo_ids: list[str]
    """ Comma-separated list of HPO term IDs """


class RankedGeneList(BaseModel):
    """Model for a list of ranked genes."""

    genes: list[RankedGene]
    """ List of ranked genes """


def create_gene_agent(resources: GeneAgentResources) -> Agent:
    """Create a Gene Agent."""
    return Agent(
        name="Gene Assistant",
        instructions=resources.prompt,
        tools=[ranked_genes_for_hpo_terms],
        model="gpt-4o",
        output_type=RankedGeneList,
        model_settings=ModelSettings(tool_choice="required"),
    )

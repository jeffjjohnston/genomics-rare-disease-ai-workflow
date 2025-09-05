#! /usr/bin/env python
# pylint: disable=invalid-name

"""Multi-agent genomics workflow"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import asyncio
from agents import Runner, trace
from dotenv import load_dotenv
from workflow_agents.hpo_agent import HPOAgentResources, HPOTermList, create_hpo_agent
from workflow_agents.gene_agent import (
    GeneAgentResources,
    RankedGeneList,
    create_gene_agent,
)
from workflow_agents.variant_agent import VariantAgentResources, create_variant_agent

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()


@dataclass
class Args:
    """Command-line arguments with types"""

    symptoms: Path
    hpo_db: Path
    phenotypes_to_gene_file: Path
    variant_db: Path
    output: Path


def parse_args() -> Args:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run the genomics workflow.")
    parser.add_argument(
        "--symptoms",
        type=Path,
        required=True,
        help="File path to a text description of the patient's symptoms.",
    )
    parser.add_argument(
        "--hpo-db",
        type=Path,
        default=BASE_DIR / "resources/hpo_agent/SapBERT-PubMedBERT_hpo.json.gz",
        help="Path to the HPO database JSON file.",
    )
    parser.add_argument(
        "--phenotypes-to-gene-file",
        type=Path,
        default=BASE_DIR / "resources/gene_agent/phenotype_to_genes.txt",
        help="Path to the phenotype to gene mapping file.",
    )
    parser.add_argument(
        "--variant-db",
        type=Path,
        required=True,
        help="Path to the variant DuckDB database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default="results.txt",
        help="File path to save the agent's output.",
    )
    args = parser.parse_args()
    return Args(**vars(args))


async def main():
    """Main function to run the multi-agent workflow."""

    args = parse_args()
    args.symptoms = args.symptoms.expanduser().resolve()
    args.hpo_db = args.hpo_db.expanduser().resolve()
    args.phenotypes_to_gene_file = args.phenotypes_to_gene_file.expanduser().resolve()
    args.variant_db = args.variant_db.expanduser().resolve()
    args.output = args.output.expanduser().resolve()

    for required_file in [args.symptoms, args.hpo_db, args.phenotypes_to_gene_file]:
        if not required_file.is_file():
            print(f"File not found: {required_file}")
            return

    symptoms_description = args.symptoms.read_text(encoding="utf-8").strip()

    hpo_resources = HPOAgentResources(
        index_json=args.hpo_db, prompt_file=BASE_DIR / "prompts/hpo_agent.md"
    )
    hpo_agent = create_hpo_agent(hpo_resources)

    gene_resources = GeneAgentResources(
        phenotypes_to_gene_file=args.phenotypes_to_gene_file,
        prompt_file=BASE_DIR / "prompts/gene_agent.md",
    )
    gene_agent = create_gene_agent(gene_resources)

    variant_resources = VariantAgentResources(
        database_file=args.variant_db,
        prompt_file=BASE_DIR / "prompts/variant_agent.md",
    )
    variant_agent = create_variant_agent(variant_resources)

    with trace("genomics-workflow"):
        print("Starting HPO search...")
        hpo_result = await Runner.run(
            starting_agent=hpo_agent,
            context=hpo_resources,
            input=symptoms_description,
            max_turns=20,
        )
        hpo_terms = hpo_result.final_output_as(HPOTermList)
        print("HPO search completed. Found terms:")
        terms_input = ""
        for term in hpo_terms.terms:
            terms_input += f"{term.id}: {term.text} (Reasoning: {term.reasoning})\n"
        print(terms_input)

        print("Starting gene search...")
        gene_result = await Runner.run(
            starting_agent=gene_agent, context=gene_resources, input=terms_input
        )
        ranked_genes = gene_result.final_output_as(RankedGeneList)
        print("Gene search completed. Ranked genes:")
        genes_input = ""
        for gene in ranked_genes.genes:
            genes_input += (
                f"Gene: {gene.gene}, "
                f"Rank: {gene.rank}, "
                f"Reasoning: {gene.reasoning}\n"
            )
        print(genes_input)

        print("Starting variant search...")
        variant_result = await Runner.run(
            starting_agent=variant_agent,
            context=variant_resources,
            input=symptoms_description + "\n\nCandidate genes:\n" + genes_input,
            max_turns=20,
        )
        print("Variant search completed. Results:")
        print(variant_result.final_output)
        with open(args.output, "w", encoding="utf-8") as out_file:
            out_file.write(variant_result.final_output)
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())

"""HPO Agent"""

import json
import gzip
from pathlib import Path
from sentence_transformers import SentenceTransformer
import hnswlib
from agents import Agent, ModelSettings, function_tool, RunContextWrapper
from pydantic import BaseModel


class HPOAgentResources:
    """Class to hold HPO resources."""

    def __init__(self, index_json: Path, prompt_file: Path):
        print("Loadinging HPO resources...")
        self.prompt = prompt_file.read_text(encoding="utf-8")

        # load the gzipped JSON file
        with gzip.open(index_json, "rt", encoding="utf-8") as f:
            index_info = json.load(f)

        index_file = str(index_json.parent / index_info.get("index_file", "index.bin"))

        self.term_texts = index_info["term_texts"]
        self.index = hnswlib.Index(
            space="cosine", dim=index_info["embeddings_dimension"]
        )
        self.index.load_index(index_file)
        self.index.set_ef(200)
        self.model = SentenceTransformer(index_info["transformer_model"])
        print("HPO resources loaded successfully.")


@function_tool
async def hpo_search(
    wrapper: RunContextWrapper[HPOAgentResources],
    phenotype_text: str,
    top_k: int = 10,
) -> str:
    """Search for HPO terms similar to a phenotype description.
    Args:
        phenotype_text (str): The text description of the phenotype.
        top_k (int): Number of top similar terms to return.
    Returns:
        str: Formatted string containing HPO term id, text, and similarity score.
    """
    print(f"Searching for: {phenotype_text}")
    query_embedding = wrapper.context.model.encode(
        sentences=[phenotype_text], normalize_embeddings=True
    )
    labels, distances = wrapper.context.index.knn_query(query_embedding, k=top_k)
    results = []
    for idx, dist in zip(labels[0], distances[0]):
        sim = 1.0 - dist
        # format with up to 3 decimal places
        sim_text = f"{sim:.3f}"
        results.append(
            f"{wrapper.context.term_texts[idx]} (similarity distance: {sim_text})"
        )

    return "\n".join(results)


class HPOTerm(BaseModel):
    """Model for HPO term."""

    id: str
    """HPO term ID."""

    text: str
    """HPO term text."""

    reasoning: str
    """Reasoning behind the term's relevance."""


class HPOTermList(BaseModel):
    """Model for a list of HPO terms."""

    terms: list[HPOTerm]
    """List of HPO terms."""


def create_hpo_agent(resources: HPOAgentResources) -> Agent:
    """Create an HPO agent."""
    return Agent(
        name="HPO Assistant",
        instructions=resources.prompt,
        tools=[hpo_search],
        model="gpt-4.1",
        output_type=HPOTermList,
        model_settings=ModelSettings(tool_choice="required"),
    )

#!/usr/bin/env python3
# pylint: disable=invalid-name

"""
Generate an index for the Human Phenotype Ontology (HPO) using Sentence Transformers
and HNSW. This script parses the HPO OBO file, generates embeddings for each term,
and saves the index along with the term texts and dimensions to disk.
"""

import os
import argparse
import json
import gzip
from sentence_transformers import SentenceTransformer
import hnswlib
import pronto


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Generate HPO index.")
    parser.add_argument(
        "--model",
        type=str,
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model to use for embeddings.",
    )
    parser.add_argument(
        "--obo_file", type=str, default="hp.obo", help="Path to the HPO OBO file."
    )
    parser.add_argument(
        "--index_base",
        type=str,
        default="hpo_index",
        help="Base path to save the HPO index.",
    )
    return parser.parse_args()


def main():
    """Main function to generate the HPO index."""
    args = parse_args()

    if not os.path.isfile(args.obo_file):
        raise FileNotFoundError(f"HPO OBO file {args.obo_file} not found.")

    model = SentenceTransformer(args.model)

    # 1. Parse the OBO
    print("Parsing HPO OBO file...")
    hpo = pronto.Ontology(args.obo_file)

    # Select all terms under Phenotypic Abnormality (HP:0000118)
    pheno_abnormal = hpo["HP:0000118"]

    term_texts = []
    term_ids = []
    for term in pheno_abnormal.subclasses():
        if term.obsolete:
            continue
        parts = [
            term.id,
            term.name or "",
            term.definition or "",
        ]
        parts += [syn.description for syn in term.synonyms]
        term_texts.append(" | ".join(parts))
        term_ids.append(term.id)

    print(f"Parsed {len(term_texts)} HPO terms.")

    embs = model.encode(term_texts, normalize_embeddings=True, show_progress_bar=True)
    dim = embs.shape[1]
    print("Embeddings dimensions: ", dim)
    index = hnswlib.Index(space="cosine", dim=dim)
    index.init_index(max_elements=len(embs), ef_construction=200, M=16)
    index.add_items(embs)
    index.set_ef(200)

    index.save_index(f"{args.index_base}.bin")
    index_info = {
        "index_file": os.path.basename(f"{args.index_base}.bin"),
        "embeddings_dimension": dim,
        "term_texts": term_texts,
        "term_ids": term_ids,
        "transformer_model": args.model,
    }
    # 2. Save the term texts and dimensions as a gzipped JSON
    with gzip.open(f"{args.index_base}.json.gz", "wt") as f:
        json.dump(index_info, f, indent=2)
    print(f"HPO index saved to {args.index_base}.bin")
    print(f"HPO index info saved to {args.index_base}.json.gz")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# pylint: disable=invalid-name

"""Add variants from a  Nirvana JSON file to a new or exisiting DuckDB database."""

import argparse
import gzip
import json
from decimal import Decimal
from typing import Any, Dict, Iterable, List
import ijson
import duckdb


def decimal_default(obj: Any):
    """JSON serializer for Decimal types."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def stream_positions(json_gz_path: str) -> Iterable[Dict[str, Any]]:
    """
    Stream position objects from a gzipped JSON file.
    """
    with gzip.open(json_gz_path, "rb") as f:
        yield from ijson.items(f, "positions.item")


def create_variant_table(conn: duckdb.DuckDBPyConnection):
    """Ensure the variant table exists with the appropriate schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS variants (
            vid                     VARCHAR NOT NULL,
            chromosome              VARCHAR NOT NULL,
            variant_index           INTEGER NOT NULL,
            position                INTEGER NOT NULL,
            quality                 DOUBLE NOT NULL,
            begin_pos               INTEGER NOT NULL,
            end_pos                 INTEGER NOT NULL,
            ref_allele              VARCHAR NOT NULL,
            alt_allele              VARCHAR NOT NULL,
            genotype                VARCHAR,
            genotype_quality        DOUBLE,
            total_depth             INTEGER,
            allele_depths           INTEGER[],
            maternal_genotype       VARCHAR,
            paternal_genotype       VARCHAR,
            variant_type            VARCHAR,
            gene_symbols            VARCHAR[],
            canonical_transcripts   VARCHAR[],
            transcript_consequences VARCHAR[],
            gnomad_af               DOUBLE,
            clinvar_classifications VARCHAR[],
            raw                     JSON NOT NULL,
            PRIMARY KEY (vid, chromosome)
        );

        CREATE INDEX IF NOT EXISTS v_chr_begin_idx ON variants(chromosome, begin_pos);
        CREATE INDEX IF NOT EXISTS v_gnomad_af_idx ON variants(gnomad_af);
        """
    )


def create_mapping_tables(conn: duckdb.DuckDBPyConnection):
    """Create mapping tables for variants."""
    conn.execute(
        """
        DROP TABLE IF EXISTS variant_genes;
        CREATE TABLE variant_genes AS
        SELECT
        vid,
        chromosome,
        UNNEST(gene_symbols) AS gene_symbol
        FROM variants
        WHERE gene_symbols IS NOT NULL;

        CREATE INDEX vg_gene_idx ON variant_genes(gene_symbol);
        CREATE INDEX vg_vid_chr_idx ON variant_genes(vid, chromosome);

        DROP TABLE IF EXISTS variant_consequences;
        CREATE TABLE variant_consequences AS
        SELECT
        vid,
        chromosome,
        UNNEST(transcript_consequences) AS consequence
        FROM variants
        WHERE transcript_consequences IS NOT NULL;

        CREATE INDEX vtc_consequence_idx ON variant_consequences(consequence);
        CREATE INDEX vtc_vid_chr_idx ON variant_consequences(vid, chromosome);

        DROP TABLE IF EXISTS clinvar_classifications;
        CREATE TABLE clinvar_classifications AS
        SELECT
        vid,
        chromosome,
        UNNEST(clinvar_classifications) AS classification
        FROM variants
        WHERE clinvar_classifications IS NOT NULL;

        CREATE INDEX vcc_classification_idx ON clinvar_classifications(classification);
        CREATE INDEX vcc_vid_chr_idx ON clinvar_classifications(vid, chromosome);
        """
    )


def batch_insert(
    conn: duckdb.DuckDBPyConnection, rows: List[tuple], columns: List[str]
):
    """Insert a batch of rows into the variants table."""
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO variants ({', '.join(columns)}) VALUES ({placeholders})", rows
    )


def build_variant_record(
    variant: Dict[str, Any], variant_index: int, position: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build a variant record by combining variant and position information.
    """
    chromosome = position.get("chromosome")
    vid = variant.get("vid")
    vid_position = position.get("position")
    quality = position.get("quality")
    begin_pos = variant.get("begin")
    end_pos = variant.get("end")
    ref_allele = variant.get("refAllele")
    alt_allele = variant.get("altAllele")

    # Samples:
    # [0] = proband,
    # [1] = paternal (if present)
    # [2] = maternal (if present)
    samples = position.get("samples", [])
    proband = samples[0] if len(samples) > 0 else {}
    paternal = samples[1] if len(samples) > 1 else {}
    maternal = samples[2] if len(samples) > 2 else {}

    genotype = proband.get("genotype")
    if isinstance(genotype, str):
        genotype = genotype.replace("|", "/").replace(".", "0")
    genotype_quality = proband.get("genotypeQuality")
    total_depth = proband.get("totalDepth")
    allele_depths = proband.get("alleleDepths", [])
    if not isinstance(allele_depths, list):
        allele_depths = []

    paternal_genotype = paternal.get("genotype")
    maternal_genotype = maternal.get("genotype")
    if isinstance(paternal_genotype, str):
        paternal_genotype = paternal_genotype.replace("|", "/").replace(".", "0")
    if isinstance(maternal_genotype, str):
        maternal_genotype = maternal_genotype.replace("|", "/").replace(".", "0")

    variant_type = variant.get("variantType")

    # Transcripts: collect gene symbols, canonical transcripts, and flat consequences
    transcripts = variant.get("transcripts", [])
    gene_names = set()
    canonical_txs = set()
    consequences = set()

    for transcript in transcripts:
        gs = transcript.get("hgnc")
        if gs:
            gene_names.add(str(gs))

        is_canonical = transcript.get("isCanonical")
        if is_canonical:
            canonical_txs.add(transcript.get("transcript"))

        consequences.update(transcript.get("consequence", []))

    # gnomAD AF: try multiple common Nirvana/annotation layouts
    gnomad_af = variant.get("gnomad", {}).get("allAf")
    if gnomad_af is None:
        gnomad_af = 0.0

    clinvar_classifications = set()
    for clinvar_entry in variant.get("clinvar-preview", []):
        entry_classification = (
            clinvar_entry.get("classifications", {})
            .get("germlineClassification", {})
            .get("classification")
        )
        if entry_classification:
            clinvar_classifications.add(entry_classification)

    # Raw variant JSON text
    raw_json_text = json.dumps(variant, default=decimal_default)

    return {
        "chromosome": chromosome,
        "vid": vid,
        "variant_index": variant_index,
        "position": int(vid_position) if vid_position is not None else None,
        "quality": float(quality) if quality is not None else None,
        "begin_pos": int(begin_pos) if begin_pos is not None else None,
        "end_pos": int(end_pos) if end_pos is not None else None,
        "ref_allele": ref_allele,
        "alt_allele": alt_allele,
        "genotype": genotype,
        "genotype_quality": (
            float(genotype_quality) if genotype_quality is not None else None
        ),
        "total_depth": int(total_depth) if total_depth is not None else None,
        "allele_depths": [int(x) for x in allele_depths if isinstance(x, (int, float))],
        "paternal_genotype": paternal_genotype,
        "maternal_genotype": maternal_genotype,
        "variant_type": variant_type,
        "gene_symbols": list(gene_names),
        "canonical_transcripts": list(canonical_txs),
        "transcript_consequences": list(consequences),
        "gnomad_af": gnomad_af,
        "clinvar_classifications": list(clinvar_classifications),
        "raw": raw_json_text,
    }


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-j",
        "--json",
        required=True,
        help="Path to gzipped Nirvana JSON (e.g., *.json.gz)",
    )
    parser.add_argument(
        "-d",
        "--db",
        required=True,
        help="DuckDB database file",
    )
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    create_variant_table(conn)

    total = 0
    batch = []
    batch_size = 5000
    seen = set()

    cols = [
        "chromosome",
        "vid",
        "variant_index",
        "position",
        "quality",
        "begin_pos",
        "end_pos",
        "ref_allele",
        "alt_allele",
        "genotype",
        "genotype_quality",
        "total_depth",
        "allele_depths",
        "paternal_genotype",
        "maternal_genotype",
        "variant_type",
        "gene_symbols",
        "canonical_transcripts",
        "transcript_consequences",
        "gnomad_af",
        "clinvar_classifications",
        "raw",
    ]

    conn.execute("BEGIN;")
    try:
        for position in stream_positions(args.json):
            for variant_index in range(len(position.get("variants", []))):
                variant = position["variants"][variant_index]

                key = variant.get("vid")
                if key in seen:
                    continue
                seen.add(key)

                record = build_variant_record(variant, variant_index, position)
                row_tuple = tuple(record[c] for c in cols)
                batch.append(row_tuple)

            if len(batch) >= batch_size:
                batch_insert(conn, batch, cols)
                total += len(batch)
                print(f"Inserted {total:,} records...")
                batch.clear()

        if batch:
            batch_insert(conn, batch, cols)
            total += len(batch)
            batch.clear()

        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise

    print(f"Total processed variants: {total:,}")

    create_mapping_tables(conn)
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()

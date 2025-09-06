## Overview

This repo is an experimental agent-based workflow designed to search for disease-causing variants in a patient's genomic sequencing results based on a description of the patient's symptoms. 

See my blog post, [Can an AI agent help diagnose genetic diseases?](https://jeffjjohnston.github.io/2025/07/20/genomics-ai-agent/) for additional discussion.

## Getting started

Here's what you'll need to run this workflow:

- An [OpenAI API key](https://platform.openai.com/docs/libraries#create-and-export-an-api-key)
- Annotated variants from [Illumina Nirvana](https://illumina.github.io/NirvanaDocumentation/3.18/)
- An `hpo.obo` file downloaded from [the HPO website](https://hpo.jax.org/data/ontology)
- A `phenotype_to_genes.txt` file downloaded from [the HPO website](https://hpo.jax.org/data/annotations)

## Set up the Python environment

```bash
git clone https://github.com/jeffjjohnston/genomics-rare-disease-ai-workflow.git
cd genomics-rare-disease-ai-workflow
uv venv -p python3.12
source .venv/bin/activate
uv pip install -r requirements.txt
echo OPENAI_API_KEY=YOUR_API_KEY > .env
```

## Generate required resources

Build the HPO terms vector database from the downloaded `hpo.obo` file:

```bash
mkdir -p resources/hpo_agent
python generate-hpo-index.py \
    --model cambridgeltl/SapBERT-from-PubMedBERT-fulltext \
    --obo_file hp.obo \
    --index_base resources/hpo_agent/SapBERT-PubMedBERT_hpo
```

Create a new DuckDB database from the Nirvana JSON:

```bash
mkdir patients
python add-variants.py \
    --json /path/to/variants.json.gz \
    --db patients/variants.duckdb
```

For instructions on running Nirvana on a VCF, see [this guide](Nirvana_guide.md)

## Run the workflow

First, describe your patient's symptoms in a plain text file (for example, `patient_symptomps.txt`).

Run the workflow:

```bash
python run-workflow.py \
    --symptoms patient_symptoms.txt \
    --hpo-db resources/hpo_agent/SapBERT-PubMedBERT_hpo.json.gz \
    --phenotypes-to-gene-file phenotype_to_genes.txt \
    --variant-db patients/variants.duckdb \
    --output results.txt
```

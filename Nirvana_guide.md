# Annotating variants with Nirvana 3.18.1

## Overview

The last public release of Nirvana, v3.18.1, can still be used with annotation resources downloaded from Illumina. However, the compression library used by Nirvana uses x86-specific AVX instructions. This prevents it from running on Apple Silicon Macs, even under emulation. I was able to get it working on a M1 Mac inside an `amd64` Docker image by recompiling the compression library with AVX disabled. Below are instructions for annotating a VCF with Nirvana on an M1 Mac with Docker Desktop.

## Build the Docker image

Create this `Dockerfile`:

```Dockerfile
FROM ubuntu:24.04 AS builder
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        make \
        gcc \
        g++ \
        unzip \
    && rm -rf /var/lib/apt/lists/*

ARG NIRVANA_VERSION=3.18.1
COPY Nirvana-3.18.1-net6.0.zip /tmp/Nirvana.zip
RUN mkdir -p /opt && unzip -q /tmp/Nirvana.zip -d /opt && \
    mv /opt/Nirvana-v${NIRVANA_VERSION} /opt/Nirvana && \
    rm -f /opt/Nirvana/libBlockCompression.* /tmp/Nirvana.zip

RUN git clone \
        --depth=1 \
        --recurse-submodules \
        https://github.com/Illumina/BlockCompression.git \
        /tmp/BlockCompression && \
    cd /tmp/BlockCompression && \
    sed -i 's/-march=ivybridge/-march=native/' Makefile && \
    make -j && \
    cp bin/libBlockCompression.* /opt/Nirvana/ && \
    cd && \
    rm -rf /tmp/BlockCompression

FROM mcr.microsoft.com/dotnet/runtime:6.0

COPY --from=builder /opt/Nirvana /Nirvana
WORKDIR /data
```

Download `Nirvana-3.18.1-net6.0.zip` from the [Nirvana GitHub releases page](https://github.com/Illumina/Nirvana/releases). Build the Docker image:

```bash
# ensure Nirvana-3.18.1-net6.0.zip is present alongside the Dockerfile
docker build --platform=linux/amd64 . -t nirvana
```

## Download annotation resources

Nirvana's GRCh38 annotation data is about 57GB in size, so use a bind mount to point the container's `/data` path to a local directory with sufficient free space (`~/nirvana_data` in the example below):

```bash
docker run \
    --platform=linux/amd64 \
    -ti \
    -v ~/nirvana_data:/data \
    nirvana \
    bash
mkdir /data/Data
dotnet /Nirvana/Downloader.dll \
    --ga GRCh38 \
    -o /data/Data
```

## Run Nirvana

Place your VCF in `~/nirvana_data` so that it is accessible to the container via the bind mount, then run Nirvana:

```bash
dotnet /Nirvana/Nirvana.dll \
  -c /data/Data/Cache/GRCh38/Both \
  -r /data/Data/References/Homo_sapiens.GRCh38.Nirvana.dat \
  --sd /data/Data/SupplementaryAnnotation/GRCh38 \
  -i /data/variants.vcf.gz \
  -o /data/variants
```

# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
# SPDX-License-Identifier: MPL-2.0
FROM python:3.13-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

ARG RUFF_VERSION=0.16.1
ARG PYTEST_VERSION=8.4.2
ARG ULG_VERSION=0.1.0b1
ARG ULG_SOURCE_REVISION=unknown

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        ca-certificates \
        golang-go \
        nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir \
        "pytest==${PYTEST_VERSION}" \
        "ruff==${RUFF_VERSION}" \
    && groupadd --gid 65532 ulg-runner \
    && useradd --no-create-home --uid 65532 --gid 65532 \
        --shell /usr/sbin/nologin ulg-runner \
    && mkdir -p /usr/share/ulg-runner \
    && dpkg-query -W -f='${binary:Package}\t${Version}\n' \
        > /usr/share/ulg-runner/dpkg-sbom.tsv \
    && python -m pip list --format=json \
        > /usr/share/ulg-runner/python-sbom.json

COPY --chmod=0555 entrypoint.py /usr/local/bin/ulg-runner-entrypoint

LABEL org.opencontainers.image.title="Under LLM Governance offline runner" \
      org.opencontainers.image.licenses="MPL-2.0" \
      org.opencontainers.image.base.digest="sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8" \
      org.opencontainers.image.source="https://github.com/aminobutyric/under-llm-governance" \
      org.opencontainers.image.version="${ULG_VERSION}" \
      org.opencontainers.image.revision="${ULG_SOURCE_REVISION}"

USER 65532:65532
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/ulg-runner-entrypoint"]

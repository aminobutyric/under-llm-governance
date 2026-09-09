#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Fail closed when Python release artifacts do not match the beta contract."""

from __future__ import annotations

import argparse
import email.parser
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_NAME = "under-llm-governance"
WHEEL_NAME = "under_llm_governance"
RUNNER_PATTERN = re.compile(
    r"^ghcr\.io/aminobutyric/under-llm-governance-runner@sha256:[0-9a-f]{64}$"
)


def _safe_member(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe archive member: {name!r}")


def _metadata_values(raw: bytes) -> dict[str, str]:
    message = email.parser.BytesParser().parsebytes(raw)
    return {key: value for key, value in message.items()}


def _verify_metadata(metadata: dict[str, str], expected_version: str) -> None:
    expected = {
        "Name": PROJECT_NAME,
        "Version": expected_version,
        "Requires-Python": ">=3.11",
        "License-Expression": "MPL-2.0",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(
                f"metadata {key!r} is {metadata.get(key)!r}, expected {value!r}"
            )


def _verify_policy(raw: bytes) -> None:
    policy = tomllib.loads(raw.decode("utf-8"))
    image = policy.get("sandbox", {}).get("image")
    if not isinstance(image, str) or RUNNER_PATTERN.fullmatch(image) is None:
        raise ValueError("packaged policy lacks the approved immutable GHCR runner")


def _verify_wheel(path: Path, expected_version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("wheel contains duplicate member names")
        for name in names:
            _safe_member(name)
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("wheel must contain exactly one METADATA file")
        _verify_metadata(
            _metadata_values(archive.read(metadata_names[0])), expected_version
        )
        policy_name = "ulg/resources/policy.toml"
        if names.count(policy_name) != 1:
            raise ValueError(f"wheel is missing {policy_name}")
        _verify_policy(archive.read(policy_name))


def _verify_sdist(path: Path, expected_version: str) -> None:
    with tarfile.open(path, mode="r:gz") as archive:
        members = archive.getmembers()
        member_names = [member.name for member in members]
        if len(member_names) != len(set(member_names)):
            raise ValueError("source distribution contains duplicate member names")
        for member in members:
            _safe_member(member.name)
            if member.issym() or member.islnk():
                raise ValueError(
                    f"source distribution contains a link: {member.name!r}"
                )
            if not member.isfile() and not member.isdir():
                raise ValueError(
                    f"source distribution contains a special file: {member.name!r}"
                )
        names = set(member_names)
        prefix = f"{WHEEL_NAME}-{expected_version}/"
        required = {
            f"{prefix}PKG-INFO",
            f"{prefix}LICENSE",
            f"{prefix}config/policy.example.toml",
            f"{prefix}src/ulg/__init__.py",
        }
        missing = required - names
        if missing:
            raise ValueError(f"source distribution is missing: {sorted(missing)!r}")

        def read(name: str) -> bytes:
            extracted = archive.extractfile(name)
            if extracted is None:
                raise ValueError(f"source distribution entry is not a file: {name!r}")
            return extracted.read()

        _verify_metadata(_metadata_values(read(f"{prefix}PKG-INFO")), expected_version)
        _verify_policy(read(f"{prefix}config/policy.example.toml"))
        version_source = read(f"{prefix}src/ulg/__init__.py").decode("utf-8")
        if f'__version__ = "{expected_version}"' not in version_source:
            raise ValueError(
                "source distribution version module does not match its name"
            )


def verify(dist: Path, expected_version: str) -> None:
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    expected_wheel = f"{WHEEL_NAME}-{expected_version}-py3-none-any.whl"
    expected_sdist = f"{WHEEL_NAME}-{expected_version}.tar.gz"
    if [item.name for item in wheels] != [expected_wheel]:
        raise ValueError(f"unexpected wheel set: {[item.name for item in wheels]!r}")
    if [item.name for item in sdists] != [expected_sdist]:
        raise ValueError(
            f"unexpected source distribution set: {[item.name for item in sdists]!r}"
        )
    _verify_wheel(wheels[0], expected_version)
    _verify_sdist(sdists[0], expected_version)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    verify(args.dist, args.version)
    print(f"verified {PROJECT_NAME} {args.version} release artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

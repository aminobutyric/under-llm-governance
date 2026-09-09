# SPDX-License-Identifier: MPL-2.0

import tomllib
from pathlib import Path

from pydantic import ValidationError

from ulg.config.models import AppConfig


class ConfigError(ValueError):
    """Trusted configuration could not be parsed or validated."""


def load_config(path: Path) -> AppConfig:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ConfigError(f"invalid policy configuration: {error}") from error
    return parse_config(payload)


def parse_config(payload: bytes) -> AppConfig:
    try:
        return AppConfig.model_validate(tomllib.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f"invalid policy configuration: {error}") from error

# SPDX-License-Identifier: MPL-2.0

import tomllib
from pathlib import Path

from pydantic import ValidationError

from ulg.config.models import AppConfig


class ConfigError(ValueError):
    """Trusted configuration could not be parsed or validated."""


def load_config(path: Path) -> AppConfig:
    try:
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        return AppConfig.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f"invalid policy configuration: {error}") from error

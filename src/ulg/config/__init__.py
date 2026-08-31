# SPDX-License-Identifier: MPL-2.0
"""Strict trusted configuration loading."""

from ulg.config.loader import ConfigError, load_config, parse_config
from ulg.config.models import AppConfig

__all__ = ["AppConfig", "ConfigError", "load_config", "parse_config"]

# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from pathspec import GitIgnoreSpec

MANDATORY_EXCLUDES = (
    ".git/",
    ".git/**",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    ".aws/",
    ".aws/**",
    ".config/gcloud/",
    ".config/gcloud/**",
)


@dataclass(frozen=True)
class ScopedGitIgnore:
    base: PurePosixPath
    spec: GitIgnoreSpec


class ExclusionPolicy:
    """Non-overridable secret exclusions plus scoped gitignore rules."""

    def __init__(self, extra_patterns: tuple[str, ...] = ()) -> None:
        self._mandatory = GitIgnoreSpec.from_lines(MANDATORY_EXCLUDES)
        self._extra = GitIgnoreSpec.from_lines(extra_patterns)

    @staticmethod
    def _match_path(path: PurePosixPath, *, is_directory: bool) -> str:
        value = path.as_posix()
        return f"{value}/" if is_directory else value

    def is_permanently_excluded(
        self, path: PurePosixPath, *, is_directory: bool
    ) -> bool:
        candidate = self._match_path(path, is_directory=is_directory)
        mandatory = self._mandatory.check_file(candidate).include is True
        extra = self._extra.check_file(candidate).include is True
        return mandatory or extra

    def is_gitignored(
        self,
        path: PurePosixPath,
        *,
        is_directory: bool,
        rules: tuple[ScopedGitIgnore, ...],
    ) -> bool:
        ignored = False
        for scoped in rules:
            try:
                relative = path.relative_to(scoped.base)
            except ValueError:
                continue
            result = scoped.spec.check_file(
                self._match_path(relative, is_directory=is_directory)
            )
            if result.include is not None:
                ignored = result.include
        return ignored

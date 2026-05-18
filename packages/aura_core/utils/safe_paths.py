# -*- coding: utf-8 -*-
"""Shared path and archive safety helpers."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Iterable


WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class UnsafePathError(ValueError):
    """Raised when user-controlled path input escapes an allowed root."""


def is_windows_absolute_like(value: str) -> bool:
    """Return true for Windows absolute, drive-qualified or UNC-like paths."""

    token = str(value or "").strip()
    if not token:
        return False
    win = PureWindowsPath(token)
    return bool(win.is_absolute() or win.drive or token.startswith(("\\\\", "//")))


def validate_safe_relative_path(value: str, *, label: str = "path") -> str:
    """Normalize and validate a user-provided relative path string."""

    raw = str(value or "").strip()
    if not raw:
        raise UnsafePathError(f"{label} must not be empty.")
    if "\x00" in raw:
        raise UnsafePathError(f"{label} contains a NUL byte.")
    if Path(raw).is_absolute() or is_windows_absolute_like(raw):
        raise UnsafePathError(f"{label} must be relative.")

    normalized = os.path.normpath(raw.replace("\\", "/")).replace("\\", "/")
    if normalized in {"", "."}:
        raise UnsafePathError(f"{label} must name a file or directory below the root.")

    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise UnsafePathError(f"{label} must not contain traversal segments.")
    for part in parts:
        _validate_windows_segment(part, label=label)
    return "/".join(parts)


def safe_resolve_under(root: str | Path, user_path: str | Path, *, label: str = "path") -> Path:
    """Resolve a user path under root and reject traversal/symlink escape."""

    root_path = Path(root).resolve()
    relative = validate_safe_relative_path(str(user_path), label=label)
    resolved = (root_path / relative).resolve()
    ensure_path_under(root_path, resolved, label=label)
    return resolved


def ensure_path_under(
    root: str | Path,
    path: str | Path,
    *,
    label: str = "path",
    allow_root: bool = False,
) -> Path:
    """Ensure an already-resolved path remains under root."""

    root_path = Path(root).resolve()
    resolved = Path(path).resolve()
    if not allow_root and resolved == root_path:
        raise UnsafePathError(f"{label} must not resolve to the root directory.")
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise UnsafePathError(f"{label} escapes allowed root: {resolved}") from exc
    return resolved


def safe_remove_tree(root: str | Path, target: str | Path, *, label: str = "path") -> None:
    """Remove a child path after proving it is under root and not the root."""

    resolved = ensure_path_under(root, target, label=label, allow_root=False)
    if resolved.is_symlink():
        resolved.unlink()
    elif resolved.exists():
        shutil.rmtree(resolved)


def validate_package_id(value: object, *, label: str = "package id") -> str:
    """Return a normalized internal package id or raise UnsafePathError."""

    raw = str(value or "").strip().lstrip("@").replace("\\", "/").strip("/")
    if not raw:
        raise UnsafePathError(f"{label} must not be empty.")
    parts = raw.split("/")
    if len(parts) < 2:
        raise UnsafePathError(f"{label} must include a scope and package name.")
    for part in parts:
        if not part:
            raise UnsafePathError(f"{label} contains an empty segment.")
        if part in {".", ".."}:
            raise UnsafePathError(f"{label} contains a traversal segment.")
        if part != part.strip(" ."):
            raise UnsafePathError(f"{label} segment must not start/end with space or dot.")
        _validate_windows_segment(part, label=label)
        if not all(("a" <= ch.lower() <= "z") or ch.isdigit() or ch in {"_", "-", "."} for ch in part):
            raise UnsafePathError(f"{label} contains unsupported characters: {part!r}")
    return "/".join(parts)


def safe_package_leaf(package_id: str) -> str:
    """Return the install directory leaf for a validated package id."""

    normalized = validate_package_id(package_id)
    return normalized.split("/")[-1]


def safe_extract_zip(archive_path: str | Path, destination: str | Path) -> None:
    """Extract a zip/aura archive after validating all member paths."""

    archive_path = Path(archive_path)
    destination = Path(destination).resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            name = str(info.filename or "").replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if _is_zip_symlink(info):
                raise UnsafePathError(f"Archive contains symlink member: {info.filename}")
            relative = validate_safe_relative_path(name, label="archive member")
            target = (destination / relative).resolve()
            ensure_path_under(destination, target, label="archive member")
            key = os.path.normcase(str(target))
            if key in seen:
                raise UnsafePathError(f"Archive contains duplicate target path: {info.filename}")
            seen.add(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)


def safe_extract_tar(archive_path: str | Path, destination: str | Path, *, mode: str = "r:*") -> None:
    """Extract a tar archive after rejecting traversal and link members."""

    destination = Path(destination).resolve()
    seen: set[str] = set()
    with tarfile.open(archive_path, mode) as archive:
        for member in archive.getmembers():
            if member.isdir():
                validate_safe_relative_path(member.name, label="archive member")
                continue
            if not member.isfile():
                raise UnsafePathError(f"Archive contains unsupported member type: {member.name}")
            relative = validate_safe_relative_path(member.name, label="archive member")
            target = (destination / relative).resolve()
            ensure_path_under(destination, target, label="archive member")
            key = os.path.normcase(str(target))
            if key in seen:
                raise UnsafePathError(f"Archive contains duplicate target path: {member.name}")
            seen.add(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise UnsafePathError(f"Archive member cannot be read: {member.name}")
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)


def iter_safe_files(root: str | Path, *, skip_parts: Iterable[str] = ()) -> Iterable[Path]:
    """Yield regular files under root without following symlinked files."""

    root_path = Path(root).resolve()
    skip = set(skip_parts)
    for path in sorted(root_path.rglob("*")):
        if any(part in skip for part in path.parts):
            continue
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        ensure_path_under(root_path, path, label="package file")
        yield path


def scan_symlinks(root: str | Path, *, skip_parts: Iterable[str] = ()) -> list[dict[str, object]]:
    """Return symlinks below root with target and root-escape metadata."""

    root_path = Path(root).resolve()
    skip = set(skip_parts)
    rows: list[dict[str, object]] = []
    candidates: list[Path] = []
    raw_root = Path(root)
    if raw_root.is_symlink():
        candidates.append(raw_root)
    elif raw_root.exists():
        candidates.extend(sorted(raw_root.rglob("*")))
    for path in candidates:
        if any(part in skip for part in path.parts):
            continue
        if not path.is_symlink():
            continue
        try:
            target_raw = os.readlink(path)
        except OSError:
            target_raw = ""
        target_path = Path(target_raw)
        if not target_path.is_absolute() and not is_windows_absolute_like(target_raw):
            target_path = path.parent / target_path
        try:
            resolved_target = target_path.resolve(strict=False)
        except OSError:
            resolved_target = target_path.absolute()
        try:
            resolved_target.relative_to(root_path)
            escapes_root = False
        except ValueError:
            escapes_root = True
        rows.append(
            {
                "code": "package_symlink_disallowed",
                "path": str(path),
                "target": target_raw,
                "resolved_target": str(resolved_target),
                "escapes_root": escapes_root,
                "message": "Package symlinks are not allowed.",
            }
        )
    return rows


def iter_package_files(
    root: str | Path,
    *,
    skip_parts: Iterable[str] = (),
    strict_symlinks: bool = True,
) -> Iterable[Path]:
    """Yield package files, optionally failing closed when any symlink exists."""

    root_path = Path(root)
    if strict_symlinks:
        symlinks = scan_symlinks(root_path)
        if symlinks:
            first = symlinks[0]
            raise UnsafePathError(
                f"package_symlink_disallowed: {first.get('path')} -> {first.get('target')}"
            )
    yield from iter_safe_files(root_path, skip_parts=skip_parts)


def _validate_windows_segment(part: str, *, label: str) -> None:
    base = part.split(".", 1)[0].lower()
    if base in WINDOWS_RESERVED_NAMES:
        raise UnsafePathError(f"{label} uses a reserved Windows name: {part!r}")
    if ":" in part or "/" in part or "\\" in part:
        raise UnsafePathError(f"{label} contains path separators or drive syntax: {part!r}")


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK

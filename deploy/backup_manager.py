#!/usr/bin/env python3
"""Create, verify, and retain private Fulton deployment backups.

The SQLite database is copied with SQLite's online-backup API. Other durable
files are archived separately, with environment files and operational churn
excluded. Retention is dry-run unless --apply is supplied explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


BACKUP_FORMAT_VERSION = 1
BACKUP_NAME_RE = re.compile(
    r"^fultons-quiz-(?P<stamp>\d{8}T\d{6}Z)-(?P<nonce>[0-9a-f]{8})$"
)
MANIFEST_NAME = "manifest.json"
MANIFEST_CHECKSUM_NAME = "manifest.sha256"
OFFHOST_ATTESTATION_NAME = "offhost-copy.verified"
DATABASE_NAME = "fultons.db"
PAYLOAD_NAME = "durable-files.tar.gz"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DURABLE_FILES = 100_000
RESERVED_BACKUP_NAMES = frozenset(
    {MANIFEST_NAME, MANIFEST_CHECKSUM_NAME, OFFHOST_ATTESTATION_NAME, PAYLOAD_NAME}
)
APPLICATION_NAME = "fultons-quiz"
MANIFEST_KEYS = frozenset(
    {"formatVersion", "application", "createdAt", "database", "artifacts", "exclusionPolicy"}
)
ARTIFACT_KEYS = frozenset({"path", "kind", "size", "sha256", "metadata"})
EXCLUSION_POLICY = {
    "environmentFiles": True,
    "qaAndCaches": True,
    "logsAndTemporaryFiles": True,
    "sqliteSidecars": True,
}

EXCLUDED_PARTS = frozenset(
    {
        ".cache",
        ".qa",
        "__pycache__",
        "backups",
        "cache",
        "localai",
        "log",
        "logs",
        "qa",
        "tmp",
    }
)
EXCLUDED_EXACT_NAMES = frozenset(
    {
        ".env",
        "app.env",
        "local-ops-settings.json",
        "local-ops-snapshot.json",
    }
)
EXCLUDED_SUFFIXES = (
    ".db-journal",
    ".log",
    ".log.1",
    ".pid",
    ".pyc",
    ".shm",
    ".tmp",
    ".wal",
    "-journal",
    "-shm",
    "-wal",
)


class BackupError(RuntimeError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackupError(f"Duplicate key in backup manifest: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise BackupError(f"Invalid JSON constant in backup manifest: {value}")


@dataclass(frozen=True)
class BackupCandidate:
    path: Path
    created_at: datetime


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _has_link_component(path: Path) -> bool:
    current = Path(os.path.abspath(path))
    while True:
        try:
            if _is_link_like(current):
                return True
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _readonly_sqlite_uri(path: Path, *, immutable: bool = False) -> str:
    immutable_query = "&immutable=1" if immutable else ""
    return f"{path.resolve(strict=True).as_uri()}?mode=ro{immutable_query}"


def _write_private(path: Path, data: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _copy_private(source: Path, destination: Path) -> None:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as destination_handle:
            descriptor = -1
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _ensure_private_directory(path: Path) -> Path:
    if _has_link_component(path):
        raise BackupError(f"Backup directory cannot traverse a link: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise BackupError(f"Backup directory is not a safe directory: {path}")
    try:
        os.chmod(resolved, stat.S_IRWXU)
    except OSError:
        pass
    return resolved


def _validate_backup_root(path: Path) -> Path:
    resolved = _ensure_private_directory(path)
    anchor = Path(resolved.anchor)
    home = Path.home().resolve(strict=False)
    broad_paths = {anchor, home}
    if os.name != "nt":
        broad_paths.update(Path(item) for item in ("/home", "/srv", "/var", "/tmp"))
    if resolved in broad_paths:
        raise BackupError(f"Refusing broad backup root: {resolved}")
    return resolved


def _is_excluded(relative_path: Path, database_name: str) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    name = relative_path.name.casefold()
    if name in {database_name.casefold(), f"{database_name.casefold()}-wal", f"{database_name.casefold()}-shm"}:
        return True
    if (
        name in EXCLUDED_EXACT_NAMES
        or name == "env"
        or name.startswith((".env", "env."))
        or name.endswith(".env")
        or ".env." in name
    ):
        return True
    if any(part in EXCLUDED_PARTS for part in parts):
        return True
    return name.endswith(EXCLUDED_SUFFIXES)


def _durable_files(data_dir: Path, database_name: str) -> Iterable[tuple[Path, Path]]:
    for source in sorted(data_dir.rglob("*")):
        relative = source.relative_to(data_dir)
        if _is_excluded(relative, database_name):
            continue
        if source.is_symlink():
            continue
        if source.is_file():
            yield source, relative


def _private_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o600
    info.pax_headers = {}
    return info


def _verify_durable_archive(path: Path, expected_file_count: int) -> None:
    if expected_file_count > MAX_DURABLE_FILES:
        raise BackupError("Durable-files archive exceeds the safe file-count limit.")
    names: set[str] = set()
    member_count = 0
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                member_count += 1
                if member_count > expected_file_count:
                    raise BackupError(
                        "Durable-files archive count does not match its manifest metadata."
                    )
                relative = PurePosixPath(member.name)
                if (
                    not member.isfile()
                    or relative.is_absolute()
                    or not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or "\\" in member.name
                    or any(
                        ord(character) < 32 or ord(character) == 127
                        for character in member.name
                    )
                ):
                    raise BackupError(
                        f"Durable-files archive member is unsafe: {member.name!r}"
                    )
                normalized = relative.as_posix()
                if normalized in names:
                    raise BackupError(f"Duplicate durable-files archive member: {normalized}")
                names.add(normalized)
    except (OSError, tarfile.TarError) as error:
        raise BackupError(f"Durable-files archive is unreadable: {error}") from error
    if member_count != expected_file_count:
        raise BackupError("Durable-files archive count does not match its manifest metadata.")


def _sqlite_online_backup(source_path: Path, destination_path: Path) -> dict[str, Any]:
    if source_path.is_symlink() or not source_path.is_file():
        raise BackupError(f"SQLite source is not a regular file: {source_path}")
    source_uri = _readonly_sqlite_uri(source_path)
    source = sqlite3.connect(source_uri, uri=True, timeout=30)
    destination = sqlite3.connect(destination_path, timeout=30)
    try:
        source.backup(destination, pages=256, sleep=0.05)
        destination.commit()
        quick_check = destination.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise BackupError(f"Backup SQLite quick_check failed: {quick_check}")
        page_count = int(destination.execute("PRAGMA page_count").fetchone()[0])
    finally:
        destination.close()
        source.close()
    try:
        os.chmod(destination_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return {"quickCheck": "ok", "pageCount": page_count}


def _artifact(path: Path, *, kind: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path.name,
        "kind": kind,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def create_backup(
    data_dir: Path,
    backup_root: Path,
    *,
    database_name: str = DATABASE_NAME,
    now: datetime | None = None,
) -> Path:
    if _has_link_component(data_dir):
        raise BackupError(f"Data directory cannot traverse a link: {data_dir}")
    if (
        not database_name
        or Path(database_name).name != database_name
        or database_name in RESERVED_BACKUP_NAMES
        or "\\" in database_name
        or any(ord(character) < 32 or ord(character) == 127 for character in database_name)
    ):
        raise BackupError("Database name must be a single filename.")
    source_root = data_dir.resolve(strict=True)
    if not source_root.is_dir():
        raise BackupError(f"Data directory is not a safe directory: {data_dir}")
    destination_root = _validate_backup_root(backup_root)
    if destination_root == source_root or destination_root.is_relative_to(source_root):
        raise BackupError("Backup root cannot be inside the live data directory.")

    created_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"fultons-quiz-{stamp}-{uuid.uuid4().hex[:8]}"
    final_path = destination_root / backup_name
    stage_path = destination_root / f".{backup_name}.partial-{uuid.uuid4().hex[:8]}"
    stage_path.mkdir(mode=0o700)

    try:
        artifacts: list[dict[str, Any]] = []
        database_source = source_root / database_name
        database_target = stage_path / database_name
        # SQLite's destination connection can fail on FUSE/mergerfs even when the
        # same filesystem safely stores and verifies an immutable database file.
        # Build the consistent snapshot locally, then seal it into backup storage.
        with tempfile.TemporaryDirectory(prefix="fultons-backup-sqlite-") as sqlite_stage:
            local_database_target = Path(sqlite_stage) / database_name
            sqlite_metadata = _sqlite_online_backup(database_source, local_database_target)
            _fsync_file(local_database_target)
            _copy_private(local_database_target, database_target)
        artifacts.append(_artifact(database_target, kind="sqlite-online-backup", metadata=sqlite_metadata))

        durable_files = list(_durable_files(source_root, database_name))
        if len(durable_files) > MAX_DURABLE_FILES:
            raise BackupError("Durable file count exceeds the safe backup limit.")
        if durable_files:
            payload_path = stage_path / PAYLOAD_NAME
            with tarfile.open(payload_path, mode="w:gz", compresslevel=9) as archive:
                for source, relative in durable_files:
                    archive.add(
                        source,
                        arcname=relative.as_posix(),
                        recursive=False,
                        filter=_private_tar_info,
                    )
            try:
                os.chmod(payload_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            _fsync_file(payload_path)
            artifacts.append(
                _artifact(
                    payload_path,
                    kind="durable-files",
                    metadata={"fileCount": len(durable_files)},
                )
            )

        manifest = {
            "formatVersion": BACKUP_FORMAT_VERSION,
            "application": APPLICATION_NAME,
            "createdAt": created_at.isoformat().replace("+00:00", "Z"),
            "database": database_name,
            "artifacts": artifacts,
            "exclusionPolicy": EXCLUSION_POLICY,
        }
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        manifest_path = stage_path / MANIFEST_NAME
        _write_private(manifest_path, manifest_text)
        _write_private(
            stage_path / MANIFEST_CHECKSUM_NAME,
            f"{_sha256(manifest_path)}  {MANIFEST_NAME}\n",
        )
        verify_backup(stage_path)
        _fsync_directory(stage_path)
        os.replace(stage_path, final_path)
        _fsync_directory(destination_root)
        verify_backup(final_path)
        return final_path
    except BaseException:
        if stage_path.exists() and stage_path.parent == destination_root and stage_path.name.startswith("."):
            shutil.rmtree(stage_path)
        raise


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    if _has_link_component(backup_dir):
        raise BackupError(f"Backup path cannot traverse a link: {backup_dir}")
    root = backup_dir.resolve(strict=True)
    if not root.is_dir():
        raise BackupError(f"Backup path is not a safe directory: {backup_dir}")
    manifest_path = root / MANIFEST_NAME
    checksum_path = root / MANIFEST_CHECKSUM_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupError("Backup manifest is missing or unsafe.")
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise BackupError("Backup manifest checksum is missing or unsafe.")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES or checksum_path.stat().st_size > 256:
        raise BackupError("Backup metadata exceeds its safe size limit.")

    checksum_line = checksum_path.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  manifest\.json", checksum_line)
    if not match or _sha256(manifest_path) != match.group(1):
        raise BackupError("Backup manifest checksum verification failed.")
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise BackupError("Backup manifest schema is invalid.")
    if (
        isinstance(manifest["formatVersion"], bool)
        or not isinstance(manifest["formatVersion"], int)
        or manifest["formatVersion"] != BACKUP_FORMAT_VERSION
    ):
        raise BackupError("Unsupported backup manifest format.")
    if manifest["application"] != APPLICATION_NAME:
        raise BackupError("Backup manifest application is invalid.")
    created_at = manifest["createdAt"]
    if not isinstance(created_at, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", created_at
    ):
        raise BackupError("Backup manifest timestamp is invalid.")
    try:
        manifest_created_at = datetime.fromisoformat(created_at[:-1] + "+00:00")
    except ValueError as error:
        raise BackupError("Backup manifest timestamp is invalid.") from error
    directory_match = BACKUP_NAME_RE.fullmatch(root.name)
    if directory_match is not None:
        try:
            directory_created_at = datetime.strptime(
                directory_match.group("stamp"), "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise BackupError("Backup directory timestamp is invalid.") from error
        if manifest_created_at.replace(microsecond=0) != directory_created_at:
            raise BackupError("Backup directory timestamp does not match its manifest.")

    database = manifest["database"]
    if (
        not isinstance(database, str)
        or not database
        or PurePosixPath(database).name != database
        or database in {".", ".."}
        or database in RESERVED_BACKUP_NAMES
        or "\\" in database
        or any(ord(character) < 32 or ord(character) == 127 for character in database)
    ):
        raise BackupError("Backup manifest database name is invalid.")
    exclusion_policy = manifest["exclusionPolicy"]
    if (
        not isinstance(exclusion_policy, dict)
        or set(exclusion_policy) != set(EXCLUSION_POLICY)
        or any(exclusion_policy[key] is not True for key in EXCLUSION_POLICY)
    ):
        raise BackupError("Backup manifest exclusion policy is invalid.")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise BackupError("Backup manifest contains no artifacts.")

    expected_files = {MANIFEST_NAME, MANIFEST_CHECKSUM_NAME}
    artifact_paths: set[str] = set()
    database_artifacts = 0
    durable_artifacts = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_KEYS:
            raise BackupError("Backup manifest artifact is invalid.")
        artifact_name = artifact["path"]
        if not isinstance(artifact_name, str):
            raise BackupError("Backup artifact path is invalid.")
        if "\\" in artifact_name or any(
            ord(character) < 32 or ord(character) == 127 for character in artifact_name
        ):
            raise BackupError("Backup artifact path is invalid.")
        relative = PurePosixPath(artifact_name)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name in {"", ".", ".."}:
            raise BackupError("Backup artifact path is unsafe.")
        if relative.name in artifact_paths:
            raise BackupError(f"Duplicate backup artifact path: {relative.name}")
        artifact_paths.add(relative.name)

        kind = artifact["kind"]
        metadata = artifact["metadata"]
        size = artifact["size"]
        checksum = artifact["sha256"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupError(f"Backup artifact size is invalid: {relative.name}")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise BackupError(f"Backup artifact checksum is invalid: {relative.name}")
        if not isinstance(metadata, dict):
            raise BackupError(f"Backup artifact metadata is invalid: {relative.name}")

        if kind == "sqlite-online-backup":
            database_artifacts += 1
            if relative.name != database:
                raise BackupError("SQLite backup artifact does not match the manifest database.")
            if set(metadata) != {"quickCheck", "pageCount"}:
                raise BackupError("SQLite backup metadata is invalid.")
            page_count = metadata["pageCount"]
            if (
                metadata["quickCheck"] != "ok"
                or isinstance(page_count, bool)
                or not isinstance(page_count, int)
                or page_count < 1
            ):
                raise BackupError("SQLite backup metadata is invalid.")
        elif kind == "durable-files":
            durable_artifacts += 1
            if relative.name != PAYLOAD_NAME or set(metadata) != {"fileCount"}:
                raise BackupError("Durable-files backup metadata is invalid.")
            file_count = metadata["fileCount"]
            if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count < 1:
                raise BackupError("Durable-files backup metadata is invalid.")
        else:
            raise BackupError(f"Unknown backup artifact kind: {kind!r}")

        artifact_path = root / relative.name
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise BackupError(f"Backup artifact is missing or unsafe: {relative.name}")
        if artifact_path.stat().st_size != size:
            raise BackupError(f"Backup artifact size mismatch: {relative.name}")
        if _sha256(artifact_path) != checksum:
            raise BackupError(f"Backup artifact checksum mismatch: {relative.name}")
        if kind == "sqlite-online-backup":
            # The artifact is complete and will never change during verification.
            # Immutable mode prevents a WAL-mode database header from creating
            # unmanifested -wal/-shm files in the sealed backup directory.
            connection = sqlite3.connect(
                _readonly_sqlite_uri(artifact_path, immutable=True),
                uri=True,
            )
            try:
                quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
                actual_page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            finally:
                connection.close()
            if quick_check != "ok":
                raise BackupError(f"Backup SQLite verification failed: {quick_check}")
            if actual_page_count != metadata["pageCount"]:
                raise BackupError("Backup SQLite page count does not match its manifest metadata.")
        else:
            _verify_durable_archive(artifact_path, metadata["fileCount"])
        expected_files.add(relative.name)

    if database_artifacts != 1:
        raise BackupError("Backup must contain exactly one SQLite database artifact.")
    if durable_artifacts > 1:
        raise BackupError("Backup contains more than one durable-files artifact.")

    attestation_path = root / OFFHOST_ATTESTATION_NAME
    if attestation_path.exists():
        verify_offhost_attestation(root)
        expected_files.add(OFFHOST_ATTESTATION_NAME)
    actual_entries = {item.name for item in root.iterdir()}
    if actual_entries != expected_files:
        raise BackupError("Backup contains unmanifested or missing entries.")
    return manifest


def verify_offhost_attestation(backup_dir: Path) -> str:
    if _has_link_component(backup_dir):
        raise BackupError(f"Backup path cannot traverse a link: {backup_dir}")
    root = backup_dir.resolve(strict=True)
    if not root.is_dir():
        raise BackupError(f"Backup path is not a safe directory: {backup_dir}")
    manifest_path = root / MANIFEST_NAME
    checksum_path = root / MANIFEST_CHECKSUM_NAME
    marker_path = root / OFFHOST_ATTESTATION_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupError("Backup manifest is missing or unsafe.")
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise BackupError("Backup manifest checksum is missing or unsafe.")
    if marker_path.is_symlink() or not marker_path.is_file():
        raise BackupError("Off-host verification attestation is missing or unsafe.")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES or checksum_path.stat().st_size > 256:
        raise BackupError("Backup metadata exceeds its safe size limit.")
    if marker_path.stat().st_size > 128:
        raise BackupError("Off-host verification attestation exceeds its safe size limit.")
    marker = marker_path.read_text(encoding="ascii").strip()
    expected = _sha256(manifest_path)
    checksum_line = checksum_path.read_text(encoding="ascii").strip()
    checksum_match = re.fullmatch(r"([0-9a-f]{64})  manifest\.json", checksum_line)
    if not checksum_match or checksum_match.group(1) != expected:
        raise BackupError("Backup manifest checksum verification failed.")
    if not re.fullmatch(r"[0-9a-f]{64}", marker) or marker != expected:
        raise BackupError("Off-host verification attestation does not match the manifest.")
    return marker


def _candidate(path: Path) -> BackupCandidate | None:
    match = BACKUP_NAME_RE.fullmatch(path.name)
    if not match or path.is_symlink() or not path.is_dir():
        return None
    created_at = datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(
        tzinfo=timezone.utc
    )
    return BackupCandidate(path=path, created_at=created_at)


def retention_plan(
    backup_root: Path,
    *,
    daily: int = 30,
    monthly: int = 12,
    annual: int = 3,
) -> dict[str, Any]:
    if min(daily, monthly, annual) < 0:
        raise BackupError("Retention counts cannot be negative.")
    root = _validate_backup_root(backup_root)
    candidates: list[BackupCandidate] = []
    protected: list[dict[str, str]] = []
    for path in sorted(root.iterdir()):
        try:
            candidate = _candidate(path)
        except ValueError as error:
            protected.append({"path": path.name, "reason": f"invalid backup timestamp: {error}"})
            continue
        if candidate is None:
            continue
        if candidate.created_at > datetime.now(timezone.utc) + timedelta(days=1):
            protected.append({"path": path.name, "reason": "backup timestamp is in the future"})
            continue
        try:
            verify_backup(path)
        except (BackupError, OSError, ValueError, json.JSONDecodeError) as error:
            protected.append({"path": path.name, "reason": str(error)})
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item.created_at, item.path.name), reverse=True)

    keep: set[Path] = set()
    seen_days: set[tuple[int, int, int]] = set()
    seen_months: set[tuple[int, int]] = set()
    seen_years: set[int] = set()
    for item in candidates:
        day_key = (item.created_at.year, item.created_at.month, item.created_at.day)
        if len(seen_days) < daily and day_key not in seen_days:
            seen_days.add(day_key)
            keep.add(item.path)
        month_key = (item.created_at.year, item.created_at.month)
        if len(seen_months) < monthly and month_key not in seen_months:
            seen_months.add(month_key)
            keep.add(item.path)
        if len(seen_years) < annual and item.created_at.year not in seen_years:
            seen_years.add(item.created_at.year)
            keep.add(item.path)

    delete = [item.path for item in candidates if item.path not in keep]
    return {
        "backupRoot": str(root),
        "policy": {"daily": daily, "monthly": monthly, "annual": annual},
        "keep": [item.path.name for item in candidates if item.path in keep],
        "delete": [item.name for item in delete],
        "protected": protected,
    }


def apply_retention(plan: dict[str, Any]) -> list[str]:
    root = _validate_backup_root(Path(str(plan["backupRoot"])))
    targets: list[tuple[str, Path]] = []
    for name in plan.get("delete", []):
        if not isinstance(name, str) or not BACKUP_NAME_RE.fullmatch(name):
            raise BackupError(f"Unsafe retention candidate: {name!r}")
        unresolved_candidate = root / name
        if _has_link_component(unresolved_candidate):
            raise BackupError(f"Retention candidate cannot traverse a link: {name}")
        candidate = unresolved_candidate.resolve(strict=True)
        if candidate.parent != root or not candidate.is_dir():
            raise BackupError(f"Retention candidate escaped backup root: {name}")
        try:
            verify_backup(candidate)
        except (BackupError, OSError, ValueError, json.JSONDecodeError) as error:
            raise BackupError(
                f"Retention candidate failed verification and nothing was deleted: {name}: {error}"
            ) from error
        targets.append((name, candidate))

    removed: list[str] = []
    for name, candidate in targets:
        shutil.rmtree(candidate)
        removed.append(name)
    return removed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Create and verify an online backup")
    create.add_argument("--data-dir", type=Path, required=True)
    create.add_argument("--backup-root", type=Path, required=True)
    create.add_argument("--database-name", default=DATABASE_NAME)

    verify = commands.add_parser("verify", help="Verify a backup and its manifest")
    verify.add_argument("backup_dir", type=Path)

    verify_offhost = commands.add_parser(
        "verify-offhost", help="Verify the off-host-copy attestation for a backup"
    )
    verify_offhost.add_argument("backup_dir", type=Path)

    retention = commands.add_parser("retention", help="Plan or apply backup retention")
    retention.add_argument("--backup-root", type=Path, required=True)
    retention.add_argument("--daily", type=int, default=30)
    retention.add_argument("--monthly", type=int, default=12)
    retention.add_argument("--annual", type=int, default=3)
    retention.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            path = create_backup(
                args.data_dir,
                args.backup_root,
                database_name=args.database_name,
            )
            print(path)
        elif args.command == "verify":
            manifest = verify_backup(args.backup_dir)
            print(json.dumps({"ok": True, "manifest": manifest}, sort_keys=True))
        elif args.command == "verify-offhost":
            digest = verify_offhost_attestation(args.backup_dir)
            print(json.dumps({"ok": True, "manifestSha256": digest}, sort_keys=True))
        else:
            plan = retention_plan(
                args.backup_root,
                daily=args.daily,
                monthly=args.monthly,
                annual=args.annual,
            )
            removed = apply_retention(plan) if args.apply else []
            plan["mode"] = "apply" if args.apply else "dry-run"
            plan["removed"] = removed
            print(json.dumps(plan, indent=2, sort_keys=True))
    except (BackupError, OSError, ValueError, TypeError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"backup error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

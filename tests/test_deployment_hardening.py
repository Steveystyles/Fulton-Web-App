from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEPLOY_DIR = PROJECT_DIR / "deploy"
UPDATE_SCRIPT = DEPLOY_DIR / "homeserver-update.sh"
COMPOSE_FILE = DEPLOY_DIR / "compose.yaml"
RESTART_SCRIPT = DEPLOY_DIR / "restart-fultons-home-server.ps1"
POWER_RECOVERY_SCRIPT = DEPLOY_DIR / "check-and-fix-after-power-outage.ps1"
SET_GEMINI_SCRIPT = DEPLOY_DIR / "set-gemini-key.ps1"
PROMO_COMPOSE_FILE = DEPLOY_DIR / "promo-test" / "compose.yaml"
BUILD_WORKFLOW = PROJECT_DIR / ".github" / "workflows" / "build.yml"
BANDIT_CONFIG = PROJECT_DIR / "bandit.yaml"
BANDIT_BASELINE = PROJECT_DIR / "bandit-baseline.json"
SAST_REQUIREMENTS = PROJECT_DIR / "requirements-sast.txt"

SPEC = importlib.util.spec_from_file_location("backup_manager", DEPLOY_DIR / "backup_manager.py")
assert SPEC is not None and SPEC.loader is not None
backup_manager = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup_manager
SPEC.loader.exec_module(backup_manager)


def build_database(path: Path, rows: int = 2) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO items(value) VALUES (?)",
            [(f"value-{index}",) for index in range(rows)],
        )
        connection.commit()
    finally:
        connection.close()


def rewrite_manifest(backup_dir: Path, payload: object) -> None:
    manifest_path = backup_dir / backup_manager.MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (backup_dir / backup_manager.MANIFEST_CHECKSUM_NAME).write_text(
        f"{backup_manager._sha256(manifest_path)}  {backup_manager.MANIFEST_NAME}\n",
        encoding="ascii",
    )


class BackupManagerTests(unittest.TestCase):
    def test_wal_mode_backup_verification_does_not_create_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            database = data_dir / "fultons.db"
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode = WAL").fetchone()[0],
                    "wal",
                )
                connection.execute(
                    "CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute("INSERT INTO items(value) VALUES ('committed in WAL')")
                connection.commit()

                created = backup_manager.create_backup(data_dir, root / "backups")
            finally:
                connection.close()

            manifest = backup_manager.verify_backup(created)
            self.assertEqual(
                {item.name for item in created.iterdir()},
                {
                    "fultons.db",
                    backup_manager.MANIFEST_NAME,
                    backup_manager.MANIFEST_CHECKSUM_NAME,
                },
            )
            self.assertEqual(manifest["database"], "fultons.db")

    def test_create_uses_online_sqlite_backup_and_excludes_secrets_and_churn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            backup_root = root / "backup-root"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db", rows=3)
            (data_dir / "durable.json").write_text('{"kept":true}', encoding="utf-8")
            (data_dir / "app.env").write_text("SECRET=do-not-copy\n", encoding="utf-8")
            (data_dir / "worker.log").write_text("noise", encoding="utf-8")
            (data_dir / "qa").mkdir()
            (data_dir / "qa" / "probe.json").write_text("{}", encoding="utf-8")
            (data_dir / "fultons.db-wal").write_text("sidecar", encoding="utf-8")

            created = backup_manager.create_backup(
                data_dir,
                backup_root,
                now=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
            )
            manifest = backup_manager.verify_backup(created)

            connection = sqlite3.connect(created / "fultons.db")
            try:
                count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 3)
            kinds = {item["kind"] for item in manifest["artifacts"]}
            self.assertIn("sqlite-online-backup", kinds)
            self.assertTrue(manifest["exclusionPolicy"]["environmentFiles"])

            archive = created / backup_manager.PAYLOAD_NAME
            import tarfile

            with tarfile.open(archive, "r:gz") as handle:
                names = set(handle.getnames())
            self.assertEqual(names, {"durable.json"})
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(created.stat().st_mode), 0o700)
                for item in created.iterdir():
                    self.assertEqual(stat.S_IMODE(item.stat().st_mode), 0o600)

    def test_manifest_detects_artifact_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(data_dir, root / "backups")
            with (created / "fultons.db").open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

    def test_manifest_schema_rejects_non_object_and_unexpected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(data_dir, root / "backups")

            rewrite_manifest(created, [])
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

            manifest = {
                "formatVersion": 1,
                "application": "fultons-quiz",
                "createdAt": "2026-08-15T12:00:00Z",
                "database": "fultons.db",
                "artifacts": [],
                "exclusionPolicy": dict(backup_manager.EXCLUSION_POLICY),
                "unexpected": True,
            }
            rewrite_manifest(created, manifest)
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

    def test_manifest_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(data_dir, root / "backups")
            manifest_path = created / backup_manager.MANIFEST_NAME
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest_text = manifest_text.replace(
                '  "application": "fultons-quiz",',
                '  "application": "fultons-quiz",\n  "application": "fultons-quiz",',
                1,
            )
            manifest_path.write_text(manifest_text, encoding="utf-8")
            (created / backup_manager.MANIFEST_CHECKSUM_NAME).write_text(
                f"{backup_manager._sha256(manifest_path)}  {backup_manager.MANIFEST_NAME}\n",
                encoding="ascii",
            )

            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

    def test_manifest_rejects_duplicate_or_misclassified_database_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(data_dir, root / "backups")
            manifest = json.loads(
                (created / backup_manager.MANIFEST_NAME).read_text(encoding="utf-8")
            )

            manifest["artifacts"].append(dict(manifest["artifacts"][0]))
            rewrite_manifest(created, manifest)
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

            manifest["artifacts"] = [dict(manifest["artifacts"][0])]
            manifest["artifacts"][0]["kind"] = "durable-files"
            rewrite_manifest(created, manifest)
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

    def test_durable_archive_count_must_match_strict_manifest_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            (data_dir / "durable.json").write_text("{}", encoding="utf-8")
            created = backup_manager.create_backup(data_dir, root / "backups")
            manifest = json.loads(
                (created / backup_manager.MANIFEST_NAME).read_text(encoding="utf-8")
            )
            durable = next(
                item for item in manifest["artifacts"] if item["kind"] == "durable-files"
            )
            durable["metadata"]["fileCount"] += 1
            rewrite_manifest(created, manifest)

            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(created)

    def test_backup_directory_timestamp_must_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(
                data_dir,
                root / "backups",
                now=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
            )
            renamed = created.with_name("fultons-quiz-20260816T120000Z-deadbeef")
            created.rename(renamed)

            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(renamed)

    def test_sqlite_uri_quotes_fragment_characters_in_database_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            database_name = "fultons#production.db"
            build_database(data_dir / database_name)
            created = backup_manager.create_backup(
                data_dir,
                root / "backups",
                database_name=database_name,
            )
            manifest = backup_manager.verify_backup(created)
            self.assertEqual(manifest["database"], database_name)
            self.assertTrue((created / database_name).is_file())

    def test_verify_and_retention_reject_symlink_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            backup_root = root / "backups"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(data_dir, backup_root)
            alias = backup_root / "fultons-quiz-20200101T000000Z-deadbeef"
            try:
                alias.symlink_to(created, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Directory symlinks unavailable: {error}")
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_backup(alias)
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.apply_retention(
                    {"backupRoot": str(backup_root), "delete": [alias.name]}
                )
            self.assertTrue(created.exists())

    def test_offhost_attestation_must_match_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            created = backup_manager.create_backup(data_dir, root / "backups")
            marker = created / backup_manager.OFFHOST_ATTESTATION_NAME
            marker.write_text("0" * 64 + "\n", encoding="ascii")
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.verify_offhost_attestation(created)
            marker.write_text(
                backup_manager._sha256(created / backup_manager.MANIFEST_NAME) + "\n",
                encoding="ascii",
            )
            digest = backup_manager.verify_offhost_attestation(created)
            self.assertEqual(len(digest), 64)
            backup_manager.verify_backup(created)

    def test_backup_root_inside_live_data_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.create_backup(data_dir, data_dir / "backups")

    def test_retention_is_dry_run_by_default_and_apply_deletes_only_planned_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            backup_root = root / "backups"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            for index in range(50):
                backup_manager.create_backup(
                    data_dir,
                    backup_root,
                    now=start + timedelta(days=index * 37),
                )
            invalid = backup_root / "fultons-quiz-20190101T000000Z-deadbeef"
            invalid.mkdir()
            unrelated = backup_root / "do-not-delete"
            unrelated.mkdir()

            before = {item.name for item in backup_root.iterdir()}
            plan = backup_manager.retention_plan(backup_root)
            after_dry_run = {item.name for item in backup_root.iterdir()}
            self.assertEqual(before, after_dry_run)
            self.assertLessEqual(len(plan["keep"]), 30 + 12 + 3)
            self.assertTrue(plan["delete"])
            self.assertIn(invalid.name, {item["path"] for item in plan["protected"]})

            removed = backup_manager.apply_retention(plan)
            self.assertEqual(set(removed), set(plan["delete"]))
            self.assertTrue(invalid.exists())
            self.assertTrue(unrelated.exists())

    def test_retention_prevalidates_every_candidate_before_deleting_any(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            backup_root = root / "backups"
            data_dir.mkdir()
            build_database(data_dir / "fultons.db")
            first = backup_manager.create_backup(
                data_dir,
                backup_root,
                now=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
            invalid = backup_root / "fultons-quiz-20200102T000000Z-deadbeef"
            invalid.mkdir()
            plan = {
                "backupRoot": str(backup_root),
                "delete": [first.name, invalid.name],
            }
            with self.assertRaises(backup_manager.BackupError):
                backup_manager.apply_retention(plan)
            self.assertTrue(first.exists())

    def test_retention_protects_timestamp_shaped_directories_with_invalid_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_root = Path(temp_dir) / "backups"
            backup_root.mkdir()
            invalid = backup_root / "fultons-quiz-20261340T250000Z-deadbeef"
            invalid.mkdir()

            plan = backup_manager.retention_plan(backup_root)

            self.assertEqual(plan["delete"], [])
            self.assertIn(invalid.name, {item["path"] for item in plan["protected"]})


class DeploymentScriptStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = UPDATE_SCRIPT.read_text(encoding="utf-8")
        cls.compose = COMPOSE_FILE.read_text(encoding="utf-8")

    def test_requires_full_sha_and_reviewed_reachability_override(self) -> None:
        self.assertIn("^[0-9a-f]{40}$", self.script)
        self.assertIn("merge-base --is-ancestor", self.script)
        self.assertIn('rev-parse HEAD', self.script)
        self.assertIn('status --porcelain --untracked-files=all', self.script)
        self.assertIn('does not match requested commit', self.script)
        self.assertIn('Source checkout must be clean', self.script)
        self.assertIn('FULTONS_REVIEWED_COMMIT', self.script)
        self.assertIn('FULTONS_ALLOW_UNREACHABLE_COMMIT', self.script)

    def test_enforces_canonical_source_and_digest_by_default(self) -> None:
        canonical = "https://github.com/Steveystyles/Fulton-Web-App.git"
        self.assertIn(canonical, self.script)
        self.assertIn("git@github.com:Steveystyles/Fulton-Web-App.git", self.script)
        self.assertIn("expected canonical HTTPS or SSH origin", self.script)
        self.assertIn("@sha256:<64 hex>", self.script)
        self.assertIn("docker pull", self.script)
        self.assertIn("ghcr.io/steveystyles/fulton-web-app", self.script)
        self.assertIn("command -v cosign", self.script)
        self.assertIn("cosign verify", self.script)
        self.assertIn("https://token.actions.githubusercontent.com", self.script)
        self.assertIn("build\\.yml@refs/heads/main", self.script)
        self.assertIn("FULTONS_ALLOW_LOCAL_BUILD_DEV_OVERRIDE", self.script)
        self.assertNotIn("local/fulton-web-app:latest", self.script)
        self.assertIn("org.opencontainers.image.source", self.script)
        self.assertIn("org.opencontainers.image.revision", self.script)

    def test_compose_has_no_implicit_build_or_mutable_default(self) -> None:
        self.assertNotIn("build:", self.compose)
        self.assertIn("FULTONS_IMAGE:?", self.compose)
        self.assertIn("pull_policy: never", self.compose)
        self.assertNotIn(":latest", self.compose)

    def test_preflight_backup_and_offhost_gate_precede_rollout(self) -> None:
        rollout = self.script.index('ROLLOUT_STARTED=1')
        self.assertLess(self.script.index('backup_manager.py" create'), rollout)
        self.assertLess(self.script.index("FULTONS_OFFHOST_BACKUP_REQUIRED"), rollout)
        self.assertLess(self.script.index("docker compose --env-file"), rollout)
        pre_rollout = self.script[:rollout]
        self.assertNotIn("docker rm", pre_rollout)
        self.assertNotIn("docker compose down", pre_rollout)
        self.assertIn("flock -n", pre_rollout)

    def test_err_trap_restores_compose_image_and_verifies_health_and_revision(self) -> None:
        self.assertIn("trap on_error ERR", self.script)
        self.assertIn("rollback_deployment", self.script)
        rollback = self.script[
            self.script.index("rollback_deployment()") : self.script.index("on_error()")
        ]
        self.assertIn("compose up -d --no-build --force-recreate", rollback)
        self.assertIn('wait_for_health "Rollback"', rollback)
        self.assertIn("rollback_image", rollback)
        self.assertIn('does not match ${PREVIOUS_IMAGE}', rollback)
        self.assertIn("rollback_revision", rollback)

    def test_no_broad_destructive_patterns(self) -> None:
        forbidden = ("rm -rf", "git clean -fdx", "git reset --hard", "docker system prune")
        for pattern in forbidden:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, self.script)
        self.assertIn("umask 077", self.script)

    def test_compose_dotenv_is_parsed_as_data_not_sourced_as_shell(self) -> None:
        self.assertIn("read_compose_path_setting", self.script)
        self.assertNotIn('. "${COMPOSE_ENV_FILE}"', self.script)
        self.assertIn('"FULTONS_OFFHOST_BACKUP_REQUIRED"', self.script)
        self.assertIn('"FULTONS_OFFHOST_BACKUP_COMMAND"', self.script)
        self.assertIn('verify-offhost', self.script)

    def test_any_offhost_command_is_followed_by_local_backup_reverification(self) -> None:
        command = self.script.index('"${OFFHOST_BACKUP_COMMAND}" "${BACKUP_DIR}"')
        rollout = self.script.index('ROLLOUT_STARTED=1')
        post_copy = self.script[command:rollout]
        self.assertIn('backup_manager.py" verify "${BACKUP_DIR}"', post_copy)

    def test_first_database_bootstrap_is_explicit_signed_and_staged_before_backup(self) -> None:
        self.assertIn("FULTONS_ALLOW_DATABASE_BOOTSTRAP", self.script)
        self.assertIn(
            'ALLOW_DATABASE_BOOTSTRAP="${FULTONS_ALLOW_DATABASE_BOOTSTRAP:-0}"',
            self.script,
        )
        self.assertNotIn(
            'read_compose_path_setting "${COMPOSE_ENV_FILE}" "FULTONS_ALLOW_DATABASE_BOOTSTRAP"',
            self.script,
        )
        self.assertIn('FULTONS_REVIEWED_COMMIT=${APP_COMMIT}', self.script)
        self.assertIn("Database bootstrap requires a signed registry digest", self.script)
        self.assertIn("--network none", self.script)
        self.assertIn("signed bootstrap preflight", self.script)
        self.assertIn("finalize_bootstrap_environment", self.script)
        bootstrap = self.script.index("Initializing the first database")
        backup = self.script.index('backup_manager.py" create')
        rollout = self.script.index("ROLLOUT_STARTED=1")
        self.assertLess(bootstrap, backup)
        self.assertLess(backup, rollout)

    def test_restart_preserves_current_immutable_image_and_does_not_source_dotenv(self) -> None:
        restart = RESTART_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("read_compose_path_setting", restart)
        self.assertNotIn('. "$COMPOSE_ENV_FILE"', restart)
        self.assertIn("CURRENT_IMAGE", restart)
        self.assertIn("RESTARTED_IMAGE", restart)
        self.assertIn('--env-file "$COMPOSE_ENV_FILE"', restart)

    def test_retention_defaults_match_policy(self) -> None:
        source = (DEPLOY_DIR / "backup_manager.py").read_text(encoding="utf-8")
        self.assertIn('default=30', source)
        self.assertIn('default=12', source)
        self.assertIn('default=3', source)
        self.assertIn('action="store_true"', source)

    def test_recovery_and_key_rotation_parse_dotenv_as_data_and_pin_restart_image(self) -> None:
        recovery = POWER_RECOVERY_SCRIPT.read_text(encoding="utf-8")
        key_rotation = SET_GEMINI_SCRIPT.read_text(encoding="utf-8")
        for source in (recovery, key_rotation):
            self.assertIn("read_compose_setting", source)
            self.assertNotIn('. "$COMPOSE_ENV_FILE"', source)
            self.assertNotIn("set -a", source)
            self.assertIn('--env-file "$COMPOSE_ENV_FILE"', source)
            self.assertIn("EXPECTED_IMAGE_ID", source)
            self.assertIn("RESTARTED_IMAGE", source)
        self.assertIn("os.replace(temporary, env_path)", key_rotation)
        self.assertIn("base64.b64decode", key_rotation)

    def test_promo_api_is_only_on_an_internal_network(self) -> None:
        promo = PROMO_COMPOSE_FILE.read_text(encoding="utf-8")
        api_block = promo[promo.index("  promo-api:") : promo.index("  promo-test:")]
        frontend_block = promo[promo.index("  promo-test:") : promo.index("\nnetworks:\n")]
        self.assertIn("- promo-internal", api_block)
        self.assertNotIn("- proxy", api_block)
        self.assertIn("pull_policy: never", api_block)
        self.assertIn('FULTONS_REQUIRE_EXISTING_DB: "1"', api_block)
        self.assertIn('FULTONS_MIN_DB_USERS: "1"', api_block)
        self.assertIn("- promo-internal", frontend_block)
        self.assertIn("- proxy", frontend_block)
        self.assertIn("promo-internal:\n    internal: true", promo)
        self.assertIn("nginx:1.30.4-alpine@sha256:", promo)

    def test_release_workflow_smokes_exact_digest_before_signing_and_uses_peeled_shas(self) -> None:
        workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("beta/daily-map-game", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn('cron: "23 4 * * 1"', workflow)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1", workflow)
        self.assertIn('python-version: "3.12"', workflow)
        self.assertIn("gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7", workflow)
        self.assertNotIn("github/codeql-action", workflow)
        self.assertIn("--require-hashes --only-binary=:all: -r requirements-sast.txt", workflow)
        self.assertIn("sigstore/cosign-installer@398d4b0eeef1380460a10c8013a76f728fb906ac", workflow)
        self.assertEqual(workflow.count("upload-artifact: false"), 2)
        smoke = workflow.index("Smoke-test the exact release digest")
        cosign = workflow.index("Install Cosign")
        signing = workflow.index("Sign and verify the immutable digest")
        self.assertLess(smoke, cosign)
        self.assertLess(cosign, signing)
        smoke_block = workflow[smoke:cosign]
        self.assertIn("IMAGE_REF: ${{ steps.image.outputs.ref }}", smoke_block)
        self.assertIn("docker run -d", smoke_block)
        self.assertIn("/api/health", smoke_block)

    def test_release_requires_fail_closed_python_sast(self) -> None:
        workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
        sast_start = workflow.index("  sast:\n")
        release_start = workflow.index("  release-image:\n")
        sast_block = workflow[sast_start:release_start]
        release_block = workflow[release_start:]

        self.assertIn("requirements-sast.txt", sast_block)
        self.assertIn("--require-hashes", sast_block)
        self.assertIn("--only-binary=:all:", sast_block)
        self.assertIn("-r . -c bandit.yaml", sast_block)
        self.assertIn("--severity-level medium", sast_block)
        self.assertIn("--confidence-level medium", sast_block)
        self.assertIn("--baseline bandit-baseline.json", sast_block)
        self.assertNotIn("continue-on-error", sast_block)
        needs_block = release_block[release_block.index("    needs:\n") : release_block.index("    runs-on:")]
        self.assertIn("      - sast\n", needs_block)

    def test_sast_baseline_is_reviewed_and_cross_platform(self) -> None:
        self.assertTrue(BANDIT_CONFIG.is_file())
        requirements = SAST_REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("bandit==1.9.4", requirements)
        self.assertEqual(requirements.count("--hash=sha256:"), 8)
        baseline = json.loads(BANDIT_BASELINE.read_text(encoding="utf-8"))
        results = baseline["results"]

        self.assertEqual({result["issue_severity"] for result in results}, {"MEDIUM"})
        self.assertEqual(
            {result["test_id"] for result in results},
            {"B108", "B310", "B314", "B608"},
        )
        normalized_findings = {
            (
                result["filename"].replace("\\", "/"),
                result["test_id"],
                result["issue_text"],
                result["line_number"],
            )
            for result in results
        }
        self.assertEqual(len(normalized_findings), 41)
        self.assertEqual(len(results), len(normalized_findings) * 2)

    def test_workflow_actions_use_full_commit_pins(self) -> None:
        workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
        references = re.findall(r"^\s*uses:\s+[^\s@]+@([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreater(len(references), 0)
        for reference in references:
            self.assertRegex(reference, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()

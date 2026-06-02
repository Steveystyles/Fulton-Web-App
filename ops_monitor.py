from __future__ import annotations

import base64
import copy
import json
import os
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import local_ops_settings

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = KeyError  # type: ignore[assignment]


REMOTE_PROBE_SCRIPT = r"""
from __future__ import annotations

import base64
import glob
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_command(command: list[str], timeout: int = 12) -> dict[str, Any]:
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": process.returncode == 0,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "returncode": process.returncode,
        }
    except Exception as error:
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(error),
            "returncode": None,
        }


def parse_json_lines(value: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            output.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return output


def parse_percent(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip().rstrip("%")
    try:
        return round(float(value), 2)
    except ValueError:
        return None


def parse_bytes_token(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.strip().replace("iB", "ib").replace("B", "b")
    number = ""
    unit = ""
    for char in cleaned:
        if char.isdigit() or char == ".":
            number += char
        elif not char.isspace():
            unit += char
    if not number:
        return None
    try:
        numeric = float(number)
    except ValueError:
        return None
    unit = unit.lower()
    scale = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "pb": 1000**5,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "pib": 1024**5,
    }.get(unit or "b")
    if scale is None:
        return None
    return int(numeric * scale)


def parse_io_pair(value: str | None) -> dict[str, int | None]:
    if not value:
        return {"inBytes": None, "outBytes": None}
    parts = [part.strip() for part in value.split("/", 1)]
    left = parse_bytes_token(parts[0]) if parts else None
    right = parse_bytes_token(parts[1]) if len(parts) > 1 else None
    return {"inBytes": left, "outBytes": right}


def parse_memory_pair(value: str | None) -> dict[str, int | None]:
    if not value:
        return {"usedBytes": None, "limitBytes": None}
    parts = [part.strip() for part in value.split("/", 1)]
    used = parse_bytes_token(parts[0]) if parts else None
    limit = parse_bytes_token(parts[1]) if len(parts) > 1 else None
    return {"usedBytes": used, "limitBytes": limit}


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                number = raw.strip().split(" ", 1)[0]
                values[key] = int(number) * 1024
    except (OSError, ValueError):
        return {}
    return values


def filesystem_payload(target: str) -> dict[str, Any]:
    path = Path(target)
    if not path.exists():
        return {"path": target, "exists": False}
    stats = os.statvfs(path)
    total = stats.f_blocks * stats.f_frsize
    free = stats.f_bavail * stats.f_frsize
    used = max(total - free, 0)
    percent = round((used / total) * 100, 2) if total else None
    payload: dict[str, Any] = {
        "path": target,
        "exists": True,
        "totalBytes": total,
        "usedBytes": used,
        "freeBytes": free,
        "usedPct": percent,
    }
    mount_info = run_command(["findmnt", "-T", target, "-n", "-o", "TARGET,SOURCE,FSTYPE"])
    if mount_info["ok"]:
        parts = mount_info["stdout"].strip().split(None, 2)
        if len(parts) == 3:
            payload["mountPoint"] = parts[0]
            payload["source"] = parts[1]
            payload["fsType"] = parts[2]
    return payload


def read_power_payload() -> dict[str, Any]:
    ac_online = None
    batteries: list[dict[str, Any]] = []

    for ac_path in glob.glob("/sys/class/power_supply/AC*/online"):
        try:
            with open(ac_path, "r", encoding="utf-8") as handle:
                ac_online = handle.read().strip() == "1"
                break
        except OSError:
            continue

    for battery_dir in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        payload: dict[str, Any] = {"name": os.path.basename(battery_dir)}
        for key, field in (
            ("status", "status"),
            ("capacityPct", "capacity"),
            ("energyNow", "energy_now"),
            ("energyFull", "energy_full"),
            ("energyFullDesign", "energy_full_design"),
        ):
            try:
                with open(os.path.join(battery_dir, field), "r", encoding="utf-8") as handle:
                    raw = handle.read().strip()
                payload[key] = int(raw) if raw.isdigit() else raw
            except OSError:
                payload[key] = None
        batteries.append(payload)

    return {"acOnline": ac_online, "batteries": batteries}


def docker_payload(errors: list[str]) -> dict[str, Any]:
    containers_output = run_command(["docker", "ps", "-a", "--format", "{{json .}}"])
    container_rows = parse_json_lines(containers_output["stdout"]) if containers_output["ok"] else []
    if not containers_output["ok"]:
        errors.append(f"docker ps failed: {containers_output['stderr'].strip() or 'unknown error'}")

    ids_output = run_command(["docker", "ps", "-aq"])
    ids = [item.strip() for item in ids_output["stdout"].splitlines() if item.strip()] if ids_output["ok"] else []
    if not ids_output["ok"]:
        errors.append(f"docker ps -aq failed: {ids_output['stderr'].strip() or 'unknown error'}")

    inspect_rows: list[dict[str, Any]] = []
    if ids:
        inspect_output = run_command(["docker", "inspect", *ids])
        if inspect_output["ok"]:
            try:
                inspect_rows = json.loads(inspect_output["stdout"])
            except json.JSONDecodeError:
                errors.append("docker inspect returned invalid JSON.")
        else:
            errors.append(
                f"docker inspect failed: {inspect_output['stderr'].strip() or 'unknown error'}"
            )

    stats_output = run_command(["docker", "stats", "--no-stream", "--format", "{{json .}}"])
    stats_rows = parse_json_lines(stats_output["stdout"]) if stats_output["ok"] else []
    if not stats_output["ok"]:
        errors.append(
            f"docker stats failed: {stats_output['stderr'].strip() or 'unknown error'}"
        )

    stats_by_name = {str(row.get("Name") or ""): row for row in stats_rows}
    inspect_by_name = {
        str(row.get("Name") or "").lstrip("/"): row
        for row in inspect_rows
    }

    containers: list[dict[str, Any]] = []
    for row in container_rows:
        name = str(row.get("Names") or "")
        inspect = inspect_by_name.get(name, {})
        stats = stats_by_name.get(name, {})
        state = inspect.get("State") if isinstance(inspect.get("State"), dict) else {}
        health = state.get("Health") if isinstance(state.get("Health"), dict) else {}
        network_settings = (
            inspect.get("NetworkSettings")
            if isinstance(inspect.get("NetworkSettings"), dict)
            else {}
        )
        ports = []
        raw_ports = network_settings.get("Ports")
        if isinstance(raw_ports, dict):
            for container_port, mappings in raw_ports.items():
                if not mappings:
                    ports.append(container_port)
                    continue
                for mapping in mappings:
                    host_ip = mapping.get("HostIp", "")
                    host_port = mapping.get("HostPort", "")
                    ports.append(f"{host_ip}:{host_port}->{container_port}".lstrip(":"))
        memory = parse_memory_pair(str(stats.get("MemUsage") or ""))
        containers.append(
            {
                "name": name,
                "image": row.get("Image"),
                "state": state.get("Status") or row.get("State"),
                "status": row.get("Status"),
                "health": health.get("Status"),
                "startedAt": state.get("StartedAt"),
                "restarts": inspect.get("RestartCount"),
                "ports": ports,
                "networks": sorted(
                    (
                        network_settings.get("Networks") or {}
                    ).keys()
                )
                if isinstance(network_settings.get("Networks"), dict)
                else [],
                "mounts": [
                    {
                        "type": mount.get("Type"),
                        "source": mount.get("Source"),
                        "destination": mount.get("Destination"),
                        "rw": mount.get("RW"),
                    }
                    for mount in inspect.get("Mounts", [])
                    if isinstance(mount, dict)
                ],
                "cpuPct": parse_percent(str(stats.get("CPUPerc") or "")),
                "memory": {
                    **memory,
                    "usedPct": parse_percent(str(stats.get("MemPerc") or "")),
                },
                "networkIO": parse_io_pair(str(stats.get("NetIO") or "")),
                "blockIO": parse_io_pair(str(stats.get("BlockIO") or "")),
                "pids": int(stats.get("PIDs") or 0) if str(stats.get("PIDs") or "").isdigit() else None,
            }
        )

    volume_names_output = run_command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    volume_names = [
        item.strip() for item in volume_names_output["stdout"].splitlines() if item.strip()
    ] if volume_names_output["ok"] else []
    if not volume_names_output["ok"]:
        errors.append(
            f"docker volume ls failed: {volume_names_output['stderr'].strip() or 'unknown error'}"
        )
    volumes: list[dict[str, Any]] = []
    if volume_names:
        volumes_output = run_command(["docker", "volume", "inspect", *volume_names])
        if volumes_output["ok"]:
            try:
                for row in json.loads(volumes_output["stdout"]):
                    volumes.append(
                        {
                            "name": row.get("Name"),
                            "driver": row.get("Driver"),
                            "mountpoint": row.get("Mountpoint"),
                            "scope": row.get("Scope"),
                            "createdAt": row.get("CreatedAt"),
                        }
                    )
            except json.JSONDecodeError:
                errors.append("docker volume inspect returned invalid JSON.")
        else:
            errors.append(
                f"docker volume inspect failed: {volumes_output['stderr'].strip() or 'unknown error'}"
            )

    network_names_output = run_command(["docker", "network", "ls", "--format", "{{.Name}}"])
    network_names = [
        item.strip() for item in network_names_output["stdout"].splitlines() if item.strip()
    ] if network_names_output["ok"] else []
    if not network_names_output["ok"]:
        errors.append(
            f"docker network ls failed: {network_names_output['stderr'].strip() or 'unknown error'}"
        )
    networks: list[dict[str, Any]] = []
    if network_names:
        networks_output = run_command(["docker", "network", "inspect", *network_names])
        if networks_output["ok"]:
            try:
                for row in json.loads(networks_output["stdout"]):
                    ipam = row.get("IPAM") if isinstance(row.get("IPAM"), dict) else {}
                    configs = ipam.get("Config") if isinstance(ipam.get("Config"), list) else []
                    containers_map = (
                        row.get("Containers") if isinstance(row.get("Containers"), dict) else {}
                    )
                    labels = row.get("Labels") if isinstance(row.get("Labels"), dict) else {}
                    name = str(row.get("Name") or "")
                    compose_project = labels.get("com.docker.compose.project")
                    compose_network = labels.get("com.docker.compose.network")
                    builtin = name in {"bridge", "host", "none"}
                    networks.append(
                        {
                            "name": name,
                            "driver": row.get("Driver"),
                            "scope": row.get("Scope"),
                            "builtin": builtin,
                            "composeProject": compose_project,
                            "composeNetwork": compose_network,
                            "orphaned": bool(compose_project) and not builtin and not containers_map,
                            "subnets": [
                                config.get("Subnet")
                                for config in configs
                                if isinstance(config, dict) and config.get("Subnet")
                            ],
                            "gateways": [
                                config.get("Gateway")
                                for config in configs
                                if isinstance(config, dict) and config.get("Gateway")
                            ],
                            "attachedContainers": sorted(
                                value.get("Name")
                                for value in containers_map.values()
                                if isinstance(value, dict) and value.get("Name")
                            ),
                        }
                    )
            except json.JSONDecodeError:
                errors.append("docker network inspect returned invalid JSON.")
        else:
            errors.append(
                f"docker network inspect failed: {networks_output['stderr'].strip() or 'unknown error'}"
            )

    return {
        "containers": containers,
        "volumes": volumes,
        "networks": networks,
    }


def sqlite_summary(db_path: str, today_date: str, tomorrow_date: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dbPath": db_path,
        "dbExists": os.path.exists(db_path),
        "tableCounts": {},
        "todayQuiz": None,
        "tomorrowQuiz": None,
    }
    if not payload["dbExists"]:
        return payload

    payload["dbSizeBytes"] = os.path.getsize(db_path)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        def table_columns(table: str) -> set[str]:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {str(row[1]) for row in rows}

        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        payload["quickCheck"] = quick_check[0] if quick_check else None
        for table in (
            "users",
            "news_items",
            "daily_quiz_sets",
            "daily_quiz_questions",
            "daily_quiz_attempts",
            "quiz_results",
            "wordle_results",
        ):
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if row and row["count"]:
                payload["tableCounts"][table] = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
        users_exists = conn.execute(
            "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()["count"]
        payload["userCount"] = (
            conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            if users_exists
            else None
        )

        def quiz_preview(quiz_date: str) -> dict[str, Any]:
            quiz_set_columns = table_columns("daily_quiz_sets")
            select_fields = ["id", "quiz_date", "status"]
            if "failure_reason" in quiz_set_columns:
                select_fields.append("failure_reason")
            if "updated_at" in quiz_set_columns:
                select_fields.append("updated_at")
            quiz_set = conn.execute(
                f"SELECT {', '.join(select_fields)} FROM daily_quiz_sets WHERE quiz_date = ?",
                (quiz_date,),
            ).fetchone()
            if quiz_set is None:
                return {
                    "date": quiz_date,
                    "status": "missing",
                    "acceptedQuestions": 0,
                    "failedAttempts": 0,
                    "failureReason": None,
                    "questions": [],
                }
            accepted_questions = conn.execute(
                "SELECT COUNT(*) AS count FROM daily_quiz_questions WHERE quiz_set_id = ?",
                (quiz_set["id"],),
            ).fetchone()["count"]
            failed_attempts = conn.execute(
                "SELECT COUNT(*) AS count FROM daily_quiz_attempts WHERE quiz_date = ? AND passed = 0",
                (quiz_date,),
            ).fetchone()["count"]
            question_rows = conn.execute(
                '''
                SELECT subject, difficulty, question, choices_json, correct_answer, explanation
                FROM daily_quiz_questions
                WHERE quiz_set_id = ?
                ORDER BY CASE subject WHEN 'general_knowledge' THEN 0 ELSE 1 END,
                         CASE difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
                ''',
                (quiz_set["id"],),
            ).fetchall()
            return {
                "date": quiz_date,
                "status": quiz_set["status"],
                "acceptedQuestions": accepted_questions,
                "failedAttempts": failed_attempts,
                "failureReason": quiz_set["failure_reason"] if "failure_reason" in quiz_set.keys() else None,
                "updatedAt": quiz_set["updated_at"] if "updated_at" in quiz_set.keys() else None,
                "questions": [
                    {
                        "subject": row["subject"],
                        "difficulty": row["difficulty"],
                        "question": row["question"],
                        "choices": json.loads(row["choices_json"]),
                        "correctAnswer": row["correct_answer"],
                        "explanation": row["explanation"],
                    }
                    for row in question_rows
                ],
            }

        payload["todayQuiz"] = quiz_preview(today_date)
        payload["tomorrowQuiz"] = quiz_preview(tomorrow_date)
    finally:
        conn.close()
    return payload


def read_health_response(url: str, response: Any, started: float) -> dict[str, Any]:
    body = json.loads(response.read().decode("utf-8"))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "url": url,
        "status": response.status,
        "responseTimeMs": elapsed_ms,
        "payload": body,
        "ok": response.status == 200 and bool(body.get("ok")),
    }


def application_health_from_url(url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with urlopen(url, timeout=4) as response:
            return read_health_response(url, response, started)
    except HTTPError as error:
        body = None
        try:
            raw = error.read().decode("utf-8")
            body = json.loads(raw) if raw else None
        except Exception:
            body = None
        return {
            "url": url,
            "status": error.code,
            "responseTimeMs": int((time.perf_counter() - started) * 1000),
            "payload": body,
            "ok": False,
        }


def guess_application_container(docker: dict[str, Any], app_port: int) -> str | None:
    containers = docker.get("containers") if isinstance(docker, dict) else []
    for container in containers or []:
        if not isinstance(container, dict):
            continue
        name = str(container.get("name") or "")
        if not name or container.get("state") != "running":
            continue
        ports = container.get("ports") if isinstance(container.get("ports"), list) else []
        port_strings = {str(port) for port in ports}
        if f"{app_port}/tcp" in port_strings or any(
            port.endswith(f"->{app_port}/tcp") for port in port_strings
        ):
            return name
    return None


def application_health_from_container(container_name: str, app_port: int) -> dict[str, Any]:
    probe_code = (
        "import json,time,urllib.request;"
        f"url='http://127.0.0.1:{app_port}/api/health';"
        "started=time.perf_counter();"
        "response=urllib.request.urlopen(url, timeout=4);"
        "body=json.loads(response.read().decode('utf-8'));"
        "print(json.dumps({'url':url,'status':response.status,'responseTimeMs':int((time.perf_counter()-started)*1000),'payload':body,'ok':response.status==200 and bool(body.get('ok'))}))"
    )
    attempts = [
        ["docker", "exec", container_name, "python3", "-c", probe_code],
        ["docker", "exec", container_name, "python", "-c", probe_code],
    ]
    errors: list[str] = []
    for command in attempts:
        result = run_command(command, timeout=10)
        if not result["ok"]:
            errors.append(result["stderr"].strip() or result["stdout"].strip() or "unknown error")
            continue
        try:
            payload = json.loads(result["stdout"].strip())
        except json.JSONDecodeError as error:
            errors.append(f"invalid JSON: {error}")
            continue
        payload["probeSource"] = "container"
        payload["containerName"] = container_name
        return payload
    raise RuntimeError("; ".join(errors) or "container health probe failed")


def application_health(app_port: int, docker: dict[str, Any]) -> dict[str, Any]:
    url = f"http://127.0.0.1:{app_port}/api/health"
    try:
        payload = application_health_from_url(url)
        payload["probeSource"] = "host"
        return payload
    except (URLError, TimeoutError) as error:
        container_name = guess_application_container(docker, app_port)
        if not container_name:
            raise
        try:
            return application_health_from_container(container_name, app_port)
        except Exception as container_error:
            raise RuntimeError(
                f"Host probe failed: {error}; container probe failed in {container_name}: {container_error}"
            ) from container_error


def main() -> None:
    config = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
    errors: list[str] = []
    tests: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    today_date = config["todayDate"]
    tomorrow_date = config["tomorrowDate"]

    host: dict[str, Any] = {
        "hostname": run_command(["hostname"])["stdout"].strip() or None,
        "generatedAt": utc_now(),
        "uptimeSeconds": None,
        "loadAverage": None,
        "cpuCount": os.cpu_count(),
        "power": read_power_payload(),
    }
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            host["uptimeSeconds"] = int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        pass
    try:
        host["loadAverage"] = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        pass

    meminfo = read_meminfo()
    total_memory = meminfo.get("MemTotal")
    available_memory = meminfo.get("MemAvailable")
    used_memory = (
        total_memory - available_memory
        if total_memory is not None and available_memory is not None
        else None
    )
    memory_payload = {
        "totalBytes": total_memory,
        "availableBytes": available_memory,
        "usedBytes": used_memory,
        "usedPct": round((used_memory / total_memory) * 100, 2)
        if total_memory and used_memory is not None
        else None,
    }

    disk_targets = []
    for candidate in [
        "/",
        config["dataDir"],
        str(Path(config["dbPath"]).parent),
        "/var/lib/docker",
    ]:
        if candidate not in disk_targets:
            disk_targets.append(candidate)
    disks = [filesystem_payload(target) for target in disk_targets]

    for label, path_key in (
        ("Compose file", "composeFile"),
        ("Env file", "envFile"),
        ("Data dir", "dataDir"),
        ("Database", "dbPath"),
    ):
        path = config[path_key]
        exists = os.path.exists(path)
        tests.append(
            {
                "id": path_key,
                "label": label,
                "status": "pass" if exists else "fail",
                "detail": path,
            }
        )
        if not exists:
            errors.append(f"{label} missing at {path}")

    docker = docker_payload(errors)
    sqlite = sqlite_summary(config["dbPath"], today_date, tomorrow_date)
    if sqlite.get("quickCheck") is not None:
        tests.append(
            {
                "id": "sqlite_quick_check",
                "label": "SQLite quick_check",
                "status": "pass" if sqlite.get("quickCheck") == "ok" else "fail",
                "detail": str(sqlite.get("quickCheck")),
            }
        )

    try:
        health = application_health(int(config["appPort"]), docker)
        tests.append(
            {
                "id": "internal_health",
                "label": "Internal /api/health",
                "status": "pass" if health.get("ok") else "fail",
                "detail": f"HTTP {health.get('status')} in {health.get('responseTimeMs')}ms",
            }
        )
    except Exception as error:
        health = {
            "url": f"http://127.0.0.1:{config['appPort']}/api/health",
            "ok": False,
            "error": str(error),
        }
        tests.append(
            {
                "id": "internal_health",
                "label": "Internal /api/health",
                "status": "fail",
                "detail": str(error),
            }
        )
        errors.append(f"Internal health probe failed: {error}")

    tomorrow_quiz = sqlite.get("tomorrowQuiz") or {}
    tomorrow_status = str(tomorrow_quiz.get("status") or "missing")
    tests.append(
        {
            "id": "tomorrow_quiz",
            "label": "Tomorrow quiz",
            "status": "pass"
            if tomorrow_status == "published"
            else "warn"
            if tomorrow_status in {"generating", "ready", "draft"}
            else "fail",
            "detail": f"{tomorrow_status} / accepted {tomorrow_quiz.get('acceptedQuestions', 0)}",
        }
    )

    payload = {
        "ok": not errors,
        "generatedAt": utc_now(),
        "host": host,
        "resources": {
            "memory": memory_payload,
            "disks": disks,
        },
        "docker": docker,
        "application": {
            "composeFile": config["composeFile"],
            "envFile": config["envFile"],
            "dataDir": config["dataDir"],
            "dbPath": config["dbPath"],
            "health": health,
            "sqlite": sqlite,
        },
        "quiz": {
            "today": sqlite.get("todayQuiz"),
            "tomorrow": sqlite.get("tomorrowQuiz"),
        },
        "tests": tests,
        "errors": errors,
    }
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
"""

REMOTE_ACTION_SCRIPT = r"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_command(command: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": process.returncode == 0,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "returncode": process.returncode,
        }
    except Exception as error:
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(error),
            "returncode": None,
        }


def parse_json_lines(value: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            output.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return output


def parse_container_name_from_compose(compose_file: str) -> str | None:
    if not compose_file:
        return None
    try:
        text = Path(compose_file).read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^\s*container_name:\s*['\"]?([^'\"\s#]+)", text, re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip()


def guess_application_container(config: dict[str, Any]) -> str:
    preferred_name = parse_container_name_from_compose(str(config.get("composeFile") or ""))
    if preferred_name:
        inspect_result = run_command(["docker", "inspect", preferred_name])
        if inspect_result["ok"]:
            try:
                payload = json.loads(inspect_result["stdout"])
            except json.JSONDecodeError:
                payload = []
            if payload and payload[0].get("State", {}).get("Running"):
                return preferred_name

    rows = parse_json_lines(run_command(["docker", "ps", "--format", "{{json .}}"])["stdout"])
    app_port = str(config.get("appPort") or "")
    for row in rows:
        name = str(row.get("Names") or "")
        ports = str(row.get("Ports") or "")
        if app_port and f"{app_port}/tcp" in ports:
            return name
    for row in rows:
        name = str(row.get("Names") or "")
        image = str(row.get("Image") or "")
        if "fulton" in name.lower() or "fulton" in image.lower():
            return name
    raise RuntimeError("Could not determine the app container for quiz generation.")


def generate_tomorrow_quiz(config: dict[str, Any]) -> dict[str, Any]:
    container_name = guess_application_container(config)
    app_port = int(config.get("appPort") or 3000)
    tomorrow_date = str(config.get("tomorrowDate") or "")
    probe_code = (
        "import json,os,urllib.request;"
        f"url='http://127.0.0.1:{app_port}/internal/generate-daily-quiz';"
        f"payload=json.dumps({{'date': {tomorrow_date!r}}}).encode('utf-8');"
        "headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['INTERNAL_QUIZ_TOKEN']};"
        "request=urllib.request.Request(url, data=payload, headers=headers, method='POST');"
        "print(urllib.request.urlopen(request, timeout=240).read().decode('utf-8'))"
    )
    attempts = [
        ["docker", "exec", container_name, "python3", "-c", probe_code],
        ["docker", "exec", container_name, "python", "-c", probe_code],
    ]
    errors: list[str] = []
    for command in attempts:
        result = run_command(command, timeout=260)
        if not result["ok"]:
            errors.append(result["stderr"].strip() or result["stdout"].strip() or "unknown error")
            continue
        try:
            payload = json.loads(result["stdout"].strip())
        except json.JSONDecodeError as error:
            errors.append(f"invalid JSON: {error}")
            continue
        return {
            "ok": True,
            "containerName": container_name,
            "generatedDate": tomorrow_date,
            "result": payload,
            "message": f"Tomorrow quiz generated for {tomorrow_date}.",
        }
    raise RuntimeError("; ".join(errors) or "Tomorrow quiz generation failed.")


def regenerate_question(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    container_name = guess_application_container(config)
    quiz_date = str(params.get("date") or config.get("tomorrowDate") or "").strip()
    subject = str(params.get("subject") or "").strip()
    difficulty = str(params.get("difficulty") or "").strip()
    if not quiz_date:
        raise RuntimeError("quiz_date is required for question regeneration.")
    if subject not in {"general_knowledge", "football"}:
        raise RuntimeError("subject must be general_knowledge or football.")
    if difficulty not in {"easy", "medium", "hard"}:
        raise RuntimeError("difficulty must be easy, medium, or hard.")

    probe_code = (
        "import json\n"
        "import server\n"
        f"quiz_date = {quiz_date!r}\n"
        f"subject = {subject!r}\n"
        f"difficulty = {difficulty!r}\n"
        "conn = server.connect_db()\n"
        "try:\n"
        "    with conn:\n"
        "        status = server.daily_quiz.regenerate_question(\n"
        "            conn,\n"
        "            quiz_date=quiz_date,\n"
        "            subject=subject,\n"
        "            difficulty=difficulty,\n"
        "            config=server.DAILY_QUIZ_CONFIG,\n"
        "            log=server.safe_log,\n"
        "        )\n"
        "        payload = server.daily_quiz.quiz_payload(conn, quiz_date)\n"
        "finally:\n"
        "    conn.close()\n"
        "print(json.dumps({'status': status, 'quiz': payload}, ensure_ascii=True))\n"
    )
    attempts = [
        ["docker", "exec", container_name, "python3", "-c", probe_code],
        ["docker", "exec", container_name, "python", "-c", probe_code],
    ]
    errors: list[str] = []
    for command in attempts:
        result = run_command(command, timeout=260)
        if not result["ok"]:
            errors.append(result["stderr"].strip() or result["stdout"].strip() or "unknown error")
            continue
        try:
            payload = json.loads(result["stdout"].strip())
        except json.JSONDecodeError as error:
            errors.append(f"invalid JSON: {error}")
            continue
        return {
            "ok": True,
            "containerName": container_name,
            "date": quiz_date,
            "subject": subject,
            "difficulty": difficulty,
            "result": payload,
            "message": f"Regenerated {subject} / {difficulty} for {quiz_date}.",
        }
    raise RuntimeError("; ".join(errors) or "Question regeneration failed.")


def remove_orphaned_networks() -> dict[str, Any]:
    list_result = run_command(["docker", "network", "ls", "--format", "{{.Name}}"])
    if not list_result["ok"]:
        raise RuntimeError(list_result["stderr"].strip() or "docker network ls failed.")
    network_names = [item.strip() for item in list_result["stdout"].splitlines() if item.strip()]
    if not network_names:
        return {
            "ok": True,
            "orphanedNetworks": [],
            "removedNetworks": [],
            "errors": [],
            "message": "No orphaned compose-managed networks were found.",
        }
    inspect_result = run_command(["docker", "network", "inspect", *network_names])
    if not inspect_result["ok"]:
        raise RuntimeError(inspect_result["stderr"].strip() or "docker network inspect failed.")
    try:
        rows = json.loads(inspect_result["stdout"])
    except json.JSONDecodeError as error:
        raise RuntimeError("docker network inspect returned invalid JSON.") from error

    orphaned: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "")
        if name in {"bridge", "host", "none"}:
            continue
        containers_map = row.get("Containers") if isinstance(row.get("Containers"), dict) else {}
        labels = row.get("Labels") if isinstance(row.get("Labels"), dict) else {}
        if containers_map:
            continue
        if not labels.get("com.docker.compose.project"):
            continue
        orphaned.append(name)

    removed: list[str] = []
    errors: list[str] = []
    for name in sorted(set(orphaned)):
        result = run_command(["docker", "network", "rm", name], timeout=25)
        if result["ok"]:
            removed.append(name)
        else:
            errors.append(result["stderr"].strip() or result["stdout"].strip() or f"Failed to remove {name}")

    return {
        "ok": not errors,
        "orphanedNetworks": sorted(set(orphaned)),
        "removedNetworks": removed,
        "errors": errors,
        "message": (
            f"Removed {len(removed)} orphaned network(s)."
            if removed
            else "No orphaned compose-managed networks were found."
        ),
    }


def main() -> None:
    payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
    action = str(payload.get("action") or "")
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    if action == "generate_tomorrow_quiz":
        print(json.dumps(generate_tomorrow_quiz(config), sort_keys=True))
        return

    if action == "regenerate_question":
        print(json.dumps(regenerate_question(config, params), sort_keys=True))
        return

    if action == "remove_orphaned_networks":
        print(json.dumps(remove_orphaned_networks(), sort_keys=True))
        return

    raise RuntimeError(f"Unsupported ops action: {action}")


if __name__ == "__main__":
    main()
"""


@dataclass(frozen=True)
class MonitorConfig:
    enabled: bool
    cache_ttl_sec: int
    ssh_target: str
    ssh_port: int
    ssh_key_path: str
    ssh_connect_timeout_sec: int
    public_health_url: str
    internal_base_url: str
    internal_quiz_token: str
    compose_file: str
    env_file: str
    data_dir: str
    db_path: str
    app_port: int

    @classmethod
    def from_env(cls) -> "MonitorConfig":
        home_dir = Path.home()
        file_settings = local_ops_settings.load_monitor_settings()
        return cls(
            enabled=os.environ.get("FULTONS_MONITOR_ENABLED", "0") == "1",
            cache_ttl_sec=max(
                5,
                int(os.environ.get("FULTONS_MONITOR_CACHE_TTL_SEC", str(file_settings["cacheTtlSec"]))),
            ),
            ssh_target=os.environ.get("FULTONS_MONITOR_SSH_TARGET", file_settings["sshTarget"]).strip(),
            ssh_port=max(1, int(os.environ.get("FULTONS_MONITOR_SSH_PORT", str(file_settings["sshPort"])))),
            ssh_key_path=os.environ.get(
                "FULTONS_MONITOR_SSH_KEY_PATH",
                str(file_settings.get("sshKeyPath") or (home_dir / ".ssh" / "codex_fultons_ed25519")),
            ).strip(),
            ssh_connect_timeout_sec=max(
                2,
                int(
                    os.environ.get(
                        "FULTONS_MONITOR_SSH_CONNECT_TIMEOUT_SEC",
                        str(file_settings["sshConnectTimeoutSec"]),
                    )
                ),
            ),
            public_health_url=os.environ.get(
                "FULTONS_MONITOR_PUBLIC_HEALTH_URL",
                file_settings["publicHealthUrl"],
            ).strip(),
            internal_base_url=os.environ.get(
                "FULTONS_MONITOR_INTERNAL_BASE_URL",
                file_settings["internalBaseUrl"],
            ).strip(),
            internal_quiz_token=os.environ.get(
                "FULTONS_MONITOR_INTERNAL_QUIZ_TOKEN",
                file_settings["internalQuizToken"],
            ).strip(),
            compose_file=os.environ.get(
                "FULTONS_MONITOR_COMPOSE_FILE",
                file_settings["composeFile"],
            ).strip(),
            env_file=os.environ.get(
                "FULTONS_MONITOR_ENV_FILE",
                file_settings["envFile"],
            ).strip(),
            data_dir=os.environ.get(
                "FULTONS_MONITOR_DATA_DIR",
                file_settings["dataDir"],
            ).strip(),
            db_path=os.environ.get(
                "FULTONS_MONITOR_DB_PATH",
                file_settings["dbPath"],
            ).strip(),
            app_port=max(1, int(os.environ.get("FULTONS_MONITOR_APP_PORT", str(file_settings["appPort"])))),
        )


_CACHE_LOCK = threading.Lock()
_CACHED_SNAPSHOT: dict[str, Any] | None = None
_CACHED_AT_MONOTONIC = 0.0
SSH_RETRY_ATTEMPTS = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def london_dates() -> tuple[str, str]:
    if ZoneInfo is not None:
        try:
            now = datetime.now(ZoneInfo("Europe/London"))
        except ZoneInfoNotFoundError:
            now = datetime.now()
    else:  # pragma: no cover - fallback only
        now = datetime.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    return today.isoformat(), tomorrow.isoformat()


def is_retryable_ssh_error(message: str) -> bool:
    detail = message.lower()
    return any(
        token in detail
        for token in (
            "connection timed out",
            "operation timed out",
            "connection reset",
            "connection refused",
            "no route to host",
            "could not resolve hostname",
        )
    )


def ssh_python_command(config: MonitorConfig, encoded_payload: str) -> list[str]:
    return [
        "ssh",
        "-i",
        str(config.ssh_key_path),
        "-p",
        str(config.ssh_port),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={config.ssh_connect_timeout_sec}",
        config.ssh_target,
        "python3",
        "-",
        encoded_payload,
    ]


def run_ssh_script(
    config: MonitorConfig,
    script: str,
    encoded_payload: str,
    *,
    timeout_sec: int,
) -> subprocess.CompletedProcess[str]:
    command = ssh_python_command(config, encoded_payload)
    last_process: subprocess.CompletedProcess[str] | None = None
    for attempt in range(SSH_RETRY_ATTEMPTS):
        process = subprocess.run(
            command,
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
        last_process = process
        if process.returncode == 0:
            return process
        detail = process.stderr.strip() or process.stdout.strip() or "unknown SSH failure"
        if attempt >= SSH_RETRY_ATTEMPTS - 1 or not is_retryable_ssh_error(detail):
            return process
        time.sleep(min(4, attempt + 1))
    assert last_process is not None
    return last_process


def disabled_snapshot(reason: str) -> dict[str, Any]:
    return {
        "enabled": False,
        "status": "disabled",
        "ok": False,
        "generatedAt": utc_now_iso(),
        "cacheAgeSec": 0,
        "stale": False,
        "reason": reason,
        "publicProbe": None,
        "remote": None,
        "alerts": [],
        "errors": [],
    }


def probe_public_health(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    hostname = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    resolved_addresses: list[str] = []
    if hostname:
        try:
            resolved_addresses = sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
                }
            )
        except OSError as error:
            resolved_addresses = [f"DNS error: {error}"]

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FultonsOpsMonitor/1.0 (+https://fultons-quiz.co.uk)",
        },
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "url": url,
                "ok": response.status == 200 and bool(payload.get("ok")),
                "status": response.status,
                "responseTimeMs": elapsed_ms,
                "resolvedAddresses": resolved_addresses,
                "payload": payload,
                "error": None,
                "checkedAt": utc_now_iso(),
            }
    except HTTPError as error:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "url": url,
            "ok": False,
            "status": error.code,
            "responseTimeMs": elapsed_ms,
            "resolvedAddresses": resolved_addresses,
            "payload": None,
            "error": f"HTTP {error.code}",
            "checkedAt": utc_now_iso(),
        }
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "url": url,
            "ok": False,
            "status": None,
            "responseTimeMs": elapsed_ms,
            "resolvedAddresses": resolved_addresses,
            "payload": None,
            "error": str(error),
            "checkedAt": utc_now_iso(),
        }


def collect_remote_snapshot(config: MonitorConfig) -> dict[str, Any]:
    if not config.ssh_target:
        raise RuntimeError("FULTONS_MONITOR_SSH_TARGET is not configured.")
    if not config.ssh_key_path:
        raise RuntimeError("FULTONS_MONITOR_SSH_KEY_PATH is not configured.")
    key_path = Path(config.ssh_key_path)
    if not key_path.exists():
        raise RuntimeError(f"SSH key not found at {key_path}.")

    today_date, tomorrow_date = london_dates()
    remote_config = {
        "composeFile": config.compose_file,
        "envFile": config.env_file,
        "dataDir": config.data_dir,
        "dbPath": config.db_path,
        "appPort": config.app_port,
        "todayDate": today_date,
        "tomorrowDate": tomorrow_date,
    }
    encoded_config = base64.b64encode(json.dumps(remote_config).encode("utf-8")).decode("ascii")
    started = time.perf_counter()
    process = run_ssh_script(
        config,
        REMOTE_PROBE_SCRIPT,
        encoded_config,
        timeout_sec=max(10, config.ssh_connect_timeout_sec + 16),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if process.returncode != 0:
        stderr = process.stderr.strip() or process.stdout.strip() or "unknown SSH failure"
        raise RuntimeError(stderr)
    try:
        payload = json.loads(process.stdout.strip())
    except json.JSONDecodeError as error:
        raise RuntimeError("Remote monitor returned invalid JSON.") from error
    payload["responseTimeMs"] = elapsed_ms
    return payload


def run_remote_action(
    config: MonitorConfig,
    action: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not config.ssh_target:
        raise RuntimeError("FULTONS_MONITOR_SSH_TARGET is not configured.")
    if not config.ssh_key_path:
        raise RuntimeError("FULTONS_MONITOR_SSH_KEY_PATH is not configured.")
    key_path = Path(config.ssh_key_path)
    if not key_path.exists():
        raise RuntimeError(f"SSH key not found at {key_path}.")

    _, tomorrow_date = london_dates()
    payload = {
        "action": action,
        "params": params or {},
        "config": {
            "composeFile": config.compose_file,
            "appPort": config.app_port,
            "tomorrowDate": tomorrow_date,
        },
    }
    encoded_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    process = run_ssh_script(
        config,
        REMOTE_ACTION_SCRIPT,
        encoded_payload,
        timeout_sec=max(30, config.ssh_connect_timeout_sec + 300),
    )
    if process.returncode != 0:
        stderr = process.stderr.strip() or process.stdout.strip() or "unknown SSH failure"
        raise RuntimeError(stderr)
    try:
        return json.loads(process.stdout.strip())
    except json.JSONDecodeError as error:
        raise RuntimeError("Remote action returned invalid JSON.") from error


def internal_quiz_request(
    config: MonitorConfig,
    path: str,
    payload: dict[str, Any],
    *,
    timeout_sec: int,
) -> dict[str, Any]:
    base_url = config.internal_base_url.rstrip("/")
    if not base_url:
        raise RuntimeError("Internal base URL is not configured in local ops settings.")
    if not config.internal_quiz_token:
        raise RuntimeError("Internal quiz token is not configured in local ops settings.")

    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {config.internal_quiz_token}",
            "Content-Type": "application/json",
            "User-Agent": "FultonsOpsMonitor/1.0 (+https://fultons-quiz.co.uk)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = f"HTTP {error.code}"
        try:
            payload = json.loads(error.read().decode("utf-8"))
            if isinstance(payload, dict):
                detail = str(payload.get("error") or payload)
        except Exception:
            reason = getattr(error, "reason", None)
            if reason:
                detail = f"{detail}: {reason}"
        raise RuntimeError(f"Internal quiz request failed: {detail}") from error
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Internal quiz request failed: {error}") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Internal quiz request returned invalid JSON.") from error
    if not isinstance(decoded, dict):
        raise RuntimeError("Internal quiz request returned an unexpected payload.")
    return decoded


def quiz_preview_from_payload(
    payload: dict[str, Any],
    *,
    fallback_date: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    status = str(payload.get("status") or ("published" if questions else "missing"))
    accepted_questions = payload.get("acceptedQuestions")
    if not isinstance(accepted_questions, int):
        accepted_questions = payload.get("accepted_questions")
    if not isinstance(accepted_questions, int):
        accepted_questions = len(questions)
    failed_attempts = payload.get("failedAttempts")
    if not isinstance(failed_attempts, int):
        failed_attempts = payload.get("failed_attempts")
    if not isinstance(failed_attempts, int):
        failed_attempts = int(previous.get("failedAttempts") or 0)
    failure_reason = payload.get("failureReason")
    if not isinstance(failure_reason, str):
        raw_reason = payload.get("failure_reason")
        failure_reason = raw_reason if isinstance(raw_reason, str) else None

    return {
        "date": str(payload.get("date") or fallback_date),
        "status": status,
        "acceptedQuestions": accepted_questions,
        "failedAttempts": failed_attempts,
        "failureReason": failure_reason,
        "questions": [
            {
                "subject": str(question.get("subject") or ""),
                "difficulty": str(question.get("difficulty") or ""),
                "question": str(question.get("question") or ""),
                "choices": [str(choice) for choice in question.get("choices", [])],
                "correctAnswer": str(question.get("correct_answer") or question.get("correctAnswer") or ""),
                "explanation": str(question.get("explanation") or ""),
            }
            for question in questions
            if isinstance(question, dict)
        ],
    }


def empty_remote_snapshot() -> dict[str, Any]:
    return {
        "ok": False,
        "generatedAt": utc_now_iso(),
        "responseTimeMs": None,
        "host": {
            "hostname": None,
            "kernel": None,
            "uptimeSec": None,
            "power": {
                "acOnline": None,
                "batteries": [],
            },
        },
        "resources": {
            "memory": {},
            "disks": [],
        },
        "docker": {
            "containers": [],
            "volumes": [],
            "networks": [],
        },
        "application": {
            "composeFile": "",
            "envFile": "",
            "dataDir": "",
            "dbPath": "",
            "health": {},
            "sqlite": {
                "todayQuiz": None,
                "tomorrowQuiz": None,
            },
        },
        "quiz": {
            "today": None,
            "tomorrow": None,
        },
        "tests": [],
        "errors": [],
    }


def merge_quiz_action_snapshot(
    snapshot: dict[str, Any],
    action: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    if action not in {"generate_tomorrow_quiz", "regenerate_question"}:
        return snapshot

    result = details.get("result")
    if not isinstance(result, dict):
        return snapshot

    payload = copy.deepcopy(snapshot)
    previous_remote = payload.get("remote")
    if isinstance(previous_remote, dict):
        remote = copy.deepcopy(previous_remote)
    else:
        remote = empty_remote_snapshot()

    quiz_section = remote.get("quiz")
    if not isinstance(quiz_section, dict):
        quiz_section = {"today": None, "tomorrow": None}
        remote["quiz"] = quiz_section
    application = remote.get("application")
    if not isinstance(application, dict):
        application = empty_remote_snapshot()["application"]
        remote["application"] = application
    sqlite = application.get("sqlite")
    if not isinstance(sqlite, dict):
        sqlite = {"todayQuiz": None, "tomorrowQuiz": None}
        application["sqlite"] = sqlite

    existing_preview = quiz_section.get("tomorrow")
    preview = quiz_preview_from_payload(
        result,
        fallback_date=str(details.get("generatedDate") or details.get("date") or ""),
        previous=existing_preview if isinstance(existing_preview, dict) else None,
    )
    quiz_section["tomorrow"] = preview
    sqlite["tomorrowQuiz"] = copy.deepcopy(preview)

    tests = remote.get("tests")
    if not isinstance(tests, list):
        tests = []
        remote["tests"] = tests
    test_row = {
        "id": "tomorrow_quiz",
        "label": "Tomorrow quiz",
        "status": "pass"
        if preview["status"] == "published"
        else "warn"
        if preview["status"] in {"generating", "ready", "draft"}
        else "fail",
        "detail": f"{preview['status']} / accepted {preview['acceptedQuestions']}",
    }
    replaced = False
    for index, row in enumerate(tests):
        if isinstance(row, dict) and row.get("id") == "tomorrow_quiz":
            tests[index] = test_row
            replaced = True
            break
    if not replaced:
        tests.append(test_row)

    remote["generatedAt"] = utc_now_iso()
    payload["remote"] = remote
    public_probe = payload.get("publicProbe")
    public_probe_dict = public_probe if isinstance(public_probe, dict) else {"ok": False}
    payload["alerts"] = build_alerts(remote, public_probe_dict)
    payload["status"] = summarize_status(remote, public_probe_dict, bool(payload.get("stale")))
    payload["ok"] = payload["status"] == "healthy" and not payload["alerts"]
    return payload


def snapshot_cache_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(snapshot)
    payload.pop("cacheAgeSec", None)
    payload.pop("stale", None)
    payload.pop("lastError", None)
    return payload


def update_cached_snapshot(snapshot: dict[str, Any]) -> None:
    global _CACHED_AT_MONOTONIC, _CACHED_SNAPSHOT
    with _CACHE_LOCK:
        _CACHED_SNAPSHOT = snapshot_cache_payload(snapshot)
        _CACHED_AT_MONOTONIC = time.monotonic()


def generate_tomorrow_quiz_action(config: MonitorConfig) -> dict[str, Any]:
    _, tomorrow_date = london_dates()
    payload = internal_quiz_request(
        config,
        "/internal/generate-daily-quiz",
        {"date": tomorrow_date},
        timeout_sec=240,
    )
    return {
        "ok": True,
        "generatedDate": str(payload.get("date") or tomorrow_date),
        "result": payload,
        "message": f"Tomorrow quiz generated for {tomorrow_date}.",
        "transport": "https",
    }


def regenerate_question_action(config: MonitorConfig, params: dict[str, Any]) -> dict[str, Any]:
    quiz_date = str(params.get("date") or "").strip()
    subject = str(params.get("subject") or "").strip()
    difficulty = str(params.get("difficulty") or "").strip()
    if not quiz_date:
        raise RuntimeError("quiz_date is required for question regeneration.")
    if subject not in {"general_knowledge", "football"}:
        raise RuntimeError("subject must be general_knowledge or football.")
    if difficulty not in {"easy", "medium", "hard"}:
        raise RuntimeError("difficulty must be easy, medium, or hard.")

    payload = internal_quiz_request(
        config,
        "/internal/regenerate-daily-quiz-question",
        {
            "date": quiz_date,
            "subject": subject,
            "difficulty": difficulty,
        },
        timeout_sec=240,
    )
    return {
        "ok": True,
        "date": quiz_date,
        "subject": subject,
        "difficulty": difficulty,
        "result": payload,
        "message": f"Regenerated {subject} / {difficulty} for {quiz_date}.",
        "transport": "https",
    }


def build_alerts(remote: dict[str, Any] | None, public_probe: dict[str, Any]) -> list[str]:
    alerts: list[str] = []
    if not public_probe.get("ok"):
        detail = public_probe.get("error") or public_probe.get("status") or "probe failed"
        alerts.append(f"Public site probe failed: {detail}")

    if remote is None:
        alerts.append("SSH monitor could not collect a live server snapshot.")
        return alerts

    application = remote.get("application") if isinstance(remote.get("application"), dict) else {}
    health = application.get("health") if isinstance(application.get("health"), dict) else {}
    if health and not health.get("ok"):
        alerts.append("Server-side /api/health reports a problem.")

    containers = (
        remote.get("docker", {}).get("containers", [])
        if isinstance(remote.get("docker"), dict)
        else []
    )
    unhealthy = [
        container["name"]
        for container in containers
        if isinstance(container, dict)
        and (
            container.get("state") != "running"
            or container.get("health") not in {None, "healthy"}
        )
    ]
    if unhealthy:
        alerts.append(f"Container issue: {', '.join(sorted(set(unhealthy)))}")

    memory = (
        remote.get("resources", {}).get("memory", {})
        if isinstance(remote.get("resources"), dict)
        else {}
    )
    if isinstance(memory.get("usedPct"), (int, float)) and float(memory["usedPct"]) >= 90:
        alerts.append(f"Memory usage is high at {memory['usedPct']}%.")

    disks = (
        remote.get("resources", {}).get("disks", [])
        if isinstance(remote.get("resources"), dict)
        else []
    )
    for disk in disks:
        if not isinstance(disk, dict):
            continue
        used_pct = disk.get("usedPct")
        if isinstance(used_pct, (int, float)) and float(used_pct) >= 90:
            alerts.append(f"Disk nearly full at {disk.get('path')}: {used_pct}%.")

    power = (
        remote.get("host", {}).get("power", {})
        if isinstance(remote.get("host"), dict)
        else {}
    )
    batteries = power.get("batteries") if isinstance(power, dict) else []
    if power.get("acOnline") is False:
        alerts.append("AC power is offline on the server host.")
    for battery in batteries or []:
        if isinstance(battery, dict) and isinstance(battery.get("capacityPct"), int):
            if battery["capacityPct"] <= 30:
                alerts.append(
                    f"{battery.get('name', 'Battery')} is low at {battery['capacityPct']}%."
                )

    tomorrow_quiz = (
        remote.get("quiz", {}).get("tomorrow", {})
        if isinstance(remote.get("quiz"), dict)
        else {}
    )
    quiz_status = str(tomorrow_quiz.get("status") or "missing")
    accepted = int(tomorrow_quiz.get("acceptedQuestions") or 0)
    if quiz_status != "published":
        alerts.append(f"Tomorrow quiz is {quiz_status} with {accepted}/6 approved questions.")

    return alerts


def summarize_status(remote: dict[str, Any] | None, public_probe: dict[str, Any], stale: bool) -> str:
    if remote is None and not public_probe.get("ok"):
        return "offline"
    if stale or not public_probe.get("ok"):
        return "degraded"
    if remote is None:
        return "degraded"
    if remote.get("errors"):
        return "degraded"
    return "healthy"


def attach_runtime_metadata(
    snapshot: dict[str, Any],
    *,
    cache_age_sec: int,
    stale: bool,
    last_error: str | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(snapshot)
    payload["cacheAgeSec"] = cache_age_sec
    payload["stale"] = stale
    if last_error is not None:
        payload["lastError"] = last_error
    return payload


def collect_dashboard_snapshot(*, force: bool = False) -> dict[str, Any]:
    global _CACHED_AT_MONOTONIC, _CACHED_SNAPSHOT

    config = MonitorConfig.from_env()
    if not config.enabled:
        return disabled_snapshot("Set FULTONS_MONITOR_ENABLED=1 to enable the external ops dashboard.")

    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        if (
            not force
            and _CACHED_SNAPSHOT is not None
            and now_monotonic - _CACHED_AT_MONOTONIC < config.cache_ttl_sec
        ):
            return attach_runtime_metadata(
                _CACHED_SNAPSHOT,
                cache_age_sec=int(now_monotonic - _CACHED_AT_MONOTONIC),
                stale=False,
            )
        cached_snapshot = copy.deepcopy(_CACHED_SNAPSHOT)
        cached_age = int(now_monotonic - _CACHED_AT_MONOTONIC) if _CACHED_SNAPSHOT else 0

    public_probe = probe_public_health(config.public_health_url)
    try:
        remote = collect_remote_snapshot(config)
    except Exception as error:
        if cached_snapshot is not None:
            cached_snapshot["status"] = summarize_status(None, public_probe, True)
            cached_snapshot["ok"] = False
            cached_snapshot["publicProbe"] = public_probe
            cached_snapshot["alerts"] = build_alerts(None, public_probe)
            cached_snapshot["errors"] = [str(error)]
            return attach_runtime_metadata(
                cached_snapshot,
                cache_age_sec=cached_age,
                stale=True,
                last_error=str(error),
            )
        return {
            "enabled": True,
            "status": summarize_status(None, public_probe, True),
            "ok": False,
            "generatedAt": utc_now_iso(),
            "cacheAgeSec": 0,
            "stale": True,
            "publicProbe": public_probe,
            "remote": None,
            "alerts": build_alerts(None, public_probe),
            "errors": [str(error)],
            "reason": "Initial SSH snapshot failed.",
        }

    snapshot = {
        "enabled": True,
        "generatedAt": utc_now_iso(),
        "publicProbe": public_probe,
        "remote": remote,
        "alerts": build_alerts(remote, public_probe),
        "errors": list(remote.get("errors", [])) if isinstance(remote.get("errors"), list) else [],
    }
    snapshot["status"] = summarize_status(remote, public_probe, False)
    snapshot["ok"] = snapshot["status"] == "healthy" and not snapshot["alerts"]

    update_cached_snapshot(snapshot)

    return attach_runtime_metadata(snapshot, cache_age_sec=0, stale=False)


def run_local_action(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = MonitorConfig.from_env()
    if not config.enabled:
        raise RuntimeError("Local ops actions are disabled because the monitor is off.")
    if action not in {"generate_tomorrow_quiz", "remove_orphaned_networks", "regenerate_question"}:
        raise ValueError(f"Unsupported ops action: {action}")
    if action == "generate_tomorrow_quiz":
        details = generate_tomorrow_quiz_action(config)
    elif action == "regenerate_question":
        details = regenerate_question_action(config, params or {})
    else:
        details = run_remote_action(config, action, params=params)
    snapshot = collect_dashboard_snapshot(force=True)
    snapshot = merge_quiz_action_snapshot(snapshot, action, details)
    update_cached_snapshot(snapshot)
    return {
        "action": action,
        "message": str(details.get("message") or "Action completed."),
        "details": details,
        "snapshot": snapshot,
    }

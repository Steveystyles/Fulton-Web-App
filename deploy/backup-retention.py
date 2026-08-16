#!/usr/bin/env python3
"""Dry-run/apply wrapper for the Fulton backup retention policy."""

from backup_manager import main


if __name__ == "__main__":
    raise SystemExit(main(["retention", *__import__("sys").argv[1:]]))

"""Canonical module adapter for the Kammat CLI."""

from kammat.cli.app import main


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())

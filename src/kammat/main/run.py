#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May  7 18:18:04 2024

@author: leonefamily
"""


""" This component run.py: Current non-GUI application adapter for the unified executor."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Union

from kammat.main.configure import ConfigurationError, has_errors, load_run_config
from kammat.main.execution import (
    ExecutionEnvironment,
    PipelineRunner,
    RunEvent,
    build_run_context,
    run_plan, #TODO(idrees): fix the variable naming as per project naming conventions
)
from kammat.main.planning import PlanSelection, build_plan


PathLike = Union[str, Path]


def _present_issue(issue: object) -> None:
    code = getattr(issue, "code", "KAM-ERROR")
    field = getattr(issue, "field", "run")
    message = getattr(issue, "message", str(issue))
    print("{0} {1}: {2}".format(code, field, message), file=sys.stderr)


def _present_event(event: RunEvent) -> None:
    if event.kind == "stage-output":
        print(event.line)
    elif event.kind in {"preflight-failed", "stage-failed", "stage-cancelled"}:
        print(
            "{0}: {1}".format(event.stage, event.message or event.kind),
            file=sys.stderr,
        )


def main(
    config_path: PathLike,
    *,
    emit=None,
    runner: Optional[PipelineRunner] = None,
    environment: Optional[ExecutionEnvironment] = None,
) -> int:
    """Load, plan, and execute one configuration with stable exit codes."""

    try:
        loaded = load_run_config(config_path)
    except ConfigurationError as error:
        for issue in error.issues:
            _present_issue(issue)
        return 3
    except Exception as error:
        print(
            "KAM-EXEC-E101 run: unexpected configuration service failure ({0})".format(
                type(error).__name__
            ),
            file=sys.stderr,
        )
        return 5
    if loaded.config is None or has_errors(loaded.issues):
        for issue in loaded.issues:
            if issue.level == "error":
                _present_issue(issue)
        return 3
    try:
        planned = build_plan(loaded.config, PlanSelection())
    except ConfigurationError as error:
        for issue in error.issues:
            _present_issue(issue)
        return 3
    except Exception as error:
        print(
            "KAM-EXEC-E101 run: unexpected planning service failure ({0})".format(
                type(error).__name__
            ),
            file=sys.stderr,
        )
        return 5
    if planned.plan is None:
        for issue in planned.issues:
            _present_issue(issue)
        return 4
    for warning in planned.issues:
        if warning.level == "warning":
            _present_issue(warning)
    sink = emit or _present_event
    context = build_run_context(loaded.config.workspace, sink)
    try:
        result = run_plan(
            planned.plan,
            context,
            environment=environment,
            runner=runner,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(
            "KAM-EXEC-E101 run: unexpected executor failure ({0})".format(
                type(error).__name__
            ),
            file=sys.stderr,
        )
        return 5
    return result.exit_code


def parse_args(args_list: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config-path",
        required=True,
        help="JSON configuration file for the framework",
    )
    return parser.parse_args(sys.argv[1:] if args_list is None else args_list)


__all__ = ["main", "parse_args"]


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(config_path=args.config_path))

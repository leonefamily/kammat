"""Safe external process execution with live logging and cancellation."""

import codecs
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, TextIO, Tuple

from .model import (
    EventDispatcher,
    ProcessInvocation,
    ProcessOutcome,
    RunContext,
    execution_issue,
    utc_now,
)


MAX_OUTPUT_LINE_CHARACTERS = 65_536


class ProcessPort(Protocol):
    def run(
        self,
        invocation: ProcessInvocation,
        context: RunContext,
        dispatcher: EventDispatcher,
    ) -> ProcessOutcome:
        ...


class ProcessLifecycle(Protocol):
    def creation_options(self) -> Mapping[str, Any]:
        ...

    def terminate_tree(self, process: Any) -> None:
        ...

    def kill_tree(self, process: Any) -> None:
        ...


class PosixProcessLifecycle:
    """Own one POSIX process group per stage."""

    def creation_options(self) -> Mapping[str, Any]:
        return {"start_new_session": True}

    def terminate_tree(self, process: Any) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def kill_tree(self, process: Any) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return


class WindowsProcessLifecycle:
    """Own one Windows process group and force only its exact PID tree."""

    def __init__(self, taskkill_runner: Optional[Callable[..., Any]] = None) -> None:
        self._taskkill_runner = taskkill_runner

    def creation_options(self) -> Mapping[str, Any]:
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}

    def terminate_tree(self, process: Any) -> None:
        process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", 1))

    def kill_tree(self, process: Any) -> None:
        runner = self._taskkill_runner or subprocess.run
        completed = runner(
            ("taskkill.exe", "/PID", str(process.pid), "/T", "/F"),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        if getattr(completed, "returncode", 0) != 0:
            raise RuntimeError("taskkill failed with a nonzero exit code")


def build_child_environment(
    base: Mapping[str, str],
    invocation: ProcessInvocation,
    *,
    path_separator: Optional[str] = None,
) -> Dict[str, str]:
    """Copy a base environment and apply reviewed immutable patches."""

    result = dict(base)
    result.update(invocation.environment_overrides)
    separator = os.pathsep if path_separator is None else path_separator
    for key, parts in invocation.environment_path_prepend.items():
        inherited = result.get(key)
        values = tuple(parts) + ((inherited,) if inherited else ())
        result[key] = separator.join(values)
    return result


class SubprocessPort:
    """Production argv-only subprocess port."""

    def __init__(
        self,
        lifecycle: ProcessLifecycle,
        *,
        popen_factory: Optional[Callable[..., Any]] = None,
        environment_provider: Optional[Callable[[], Mapping[str, str]]] = None,
        utc_clock: Callable[[], Any] = utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
        log_opener: Optional[Callable[[Path], TextIO]] = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._popen_factory = popen_factory
        self._environment_provider = environment_provider or (lambda: dict(os.environ))
        self._utc_clock = utc_clock
        self._monotonic_clock = monotonic_clock
        self._log_opener = log_opener or self._open_log

    @staticmethod
    def _open_log(path: Path) -> TextIO:
        return path.open("w", encoding="utf-8", newline="\n")

    def _terminate_and_wait(
        self,
        process: Any,
        context: RunContext,
    ) -> Tuple[bool, Tuple[Any, ...]]:
        issues = []
        forced = False
        try:
            self._lifecycle.terminate_tree(process)
        except Exception as error:
            issues.append(execution_issue(
                "KAM-EXEC-E202",
                "run:termination",
                "graceful process-tree termination failed ({0})".format(
                    type(error).__name__
                ),
            ))
        deadline = self._monotonic_clock() + context.termination_grace_seconds
        try:
            remaining = max(0.0, deadline - self._monotonic_clock())
            process.wait(timeout=remaining)
            return forced, tuple(issues)
        except subprocess.TimeoutExpired:
            forced = True
        except Exception as error:
            issues.append(execution_issue(
                "KAM-EXEC-E202",
                "run:wait",
                "process wait failed ({0})".format(type(error).__name__),
            ))
            forced = True
        if forced:
            issues.append(execution_issue(
                "KAM-EXEC-W100",
                "run:termination",
                "process-tree termination escalated to kill",
            ))
            try:
                self._lifecycle.kill_tree(process)
            except Exception as error:
                issues.append(execution_issue(
                    "KAM-EXEC-E202",
                    "run:kill",
                    "forced process-tree termination failed ({0})".format(
                        type(error).__name__
                    ),
                ))
            try:
                process.wait()
            except Exception as error:
                issues.append(execution_issue(
                    "KAM-EXEC-E202",
                    "run:wait",
                    "process reap failed ({0})".format(type(error).__name__),
                ))
        return forced, tuple(issues)

    def run(
        self,
        invocation: ProcessInvocation,
        context: RunContext,
        dispatcher: EventDispatcher,
    ) -> ProcessOutcome:
        started = self._utc_clock()
        issues = []
        line_count = 0
        child_exit_code = None
        process = None
        forced = False
        cancelled = False
        infrastructure_failed = False
        callback_failed = False
        log_handle: Optional[TextIO] = None

        try:
            log_handle = self._log_opener(invocation.log_path)
        except Exception as error:
            issues.append(execution_issue(
                "KAM-EXEC-E200",
                invocation.stage + ":log",
                "stage log cannot be opened ({0})".format(type(error).__name__),
            ))
            return ProcessOutcome(
                invocation.stage,
                "failed",
                None,
                started,
                self._utc_clock(),
                invocation.log_path,
                0,
                False,
                tuple(issues),
            )

        try:
            try:
                environment = build_child_environment(
                    self._environment_provider(), invocation
                )
            except Exception as error:
                issues.append(execution_issue(
                    "KAM-EXEC-E201",
                    invocation.stage + ":environment",
                    "child environment cannot be prepared ({0})".format(
                        type(error).__name__
                    ),
                ))
                return ProcessOutcome(
                    invocation.stage,
                    "failed",
                    None,
                    started,
                    self._utc_clock(),
                    invocation.log_path,
                    0,
                    False,
                    tuple(issues),
                )
            factory = self._popen_factory or subprocess.Popen
            try:
                process = factory(
                    invocation.argv,
                    cwd=str(invocation.cwd),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    **dict(self._lifecycle.creation_options())
                )
            except Exception as error:
                issues.append(execution_issue(
                    "KAM-EXEC-E201",
                    invocation.stage + ":process",
                    "child process cannot be started ({0})".format(
                        type(error).__name__
                    ),
                ))
                return ProcessOutcome(
                    invocation.stage,
                    "failed",
                    None,
                    started,
                    self._utc_clock(),
                    invocation.log_path,
                    0,
                    False,
                    tuple(issues),
                )

            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            pending = ""
            continuing_line = False
            termination_requested = False

            def deliver(value: str) -> None:
                nonlocal line_count, infrastructure_failed, callback_failed
                if infrastructure_failed:
                    return
                try:
                    assert log_handle is not None
                    log_handle.write(value + "\n")
                    log_handle.flush()
                except Exception as error:
                    infrastructure_failed = True
                    issues.append(execution_issue(
                        "KAM-EXEC-E202",
                        invocation.stage + ":log",
                        "stage log stream failed ({0})".format(
                            type(error).__name__
                        ),
                    ))
                    return
                line_count += 1
                if not callback_failed and not dispatcher.emit(
                    "stage-output",
                    stage=invocation.stage,
                    line=value,
                    log_path=invocation.log_path,
                ):
                    callback_failed = True
                    if dispatcher.failure is not None:
                        issues.append(dispatcher.failure)

            def drain() -> None:
                nonlocal pending, continuing_line, forced, termination_requested
                if process.stdout is None:
                    raise OSError("child stdout pipe is unavailable")
                while True:
                    raw = process.stdout.read(8192)
                    if not raw:
                        break
                    if isinstance(raw, str):
                        decoded = raw
                    else:
                        decoded = decoder.decode(raw, final=False)
                    pending += decoded
                    while True:
                        newline = pending.find("\n")
                        if newline < 0 and len(pending) < MAX_OUTPUT_LINE_CHARACTERS:
                            break
                        if newline < 0 or newline >= MAX_OUTPUT_LINE_CHARACTERS:
                            value = pending[:MAX_OUTPUT_LINE_CHARACTERS]
                            pending = pending[MAX_OUTPUT_LINE_CHARACTERS:]
                            continuing_line = True
                            ended_by_newline = False
                        else:
                            value = pending[:newline]
                            pending = pending[newline + 1:]
                            if not value and continuing_line:
                                continuing_line = False
                                continue
                            continuing_line = False
                            ended_by_newline = True
                        if ended_by_newline and value.endswith("\r"):
                            value = value[:-1]
                        deliver(value)
                        if (infrastructure_failed or callback_failed) and not termination_requested:
                            termination_requested = True
                            extra_forced, extra_issues = self._terminate_and_wait(
                                process, context
                            )
                            forced = forced or extra_forced
                            issues.extend(extra_issues)
                pending += decoder.decode(b"", final=True)
                if pending:
                    deliver(pending[:-1] if pending.endswith("\r") else pending)
                    continuing_line = False
                    if (infrastructure_failed or callback_failed) and not termination_requested:
                        termination_requested = True
                        extra_forced, extra_issues = self._terminate_and_wait(process, context)
                        forced = forced or extra_forced
                        issues.extend(extra_issues)

            try:
                drain()
            except KeyboardInterrupt:
                cancelled = True
                forced, termination_issues = self._terminate_and_wait(process, context)
                issues.extend(termination_issues)
                try:
                    drain()
                except KeyboardInterrupt:
                    pass
                except Exception as error:
                    issues.append(execution_issue(
                        "KAM-EXEC-E202",
                        invocation.stage + ":stream",
                        "child output stream failed during cancellation ({0})".format(
                            type(error).__name__
                        ),
                    ))
            except Exception as error:
                infrastructure_failed = True
                issues.append(execution_issue(
                    "KAM-EXEC-E202",
                    invocation.stage + ":stream",
                    "child output stream failed ({0})".format(type(error).__name__),
                ))
                forced, termination_issues = self._terminate_and_wait(process, context)
                issues.extend(termination_issues)

            if not cancelled and not infrastructure_failed and not callback_failed:
                try:
                    child_exit_code = process.wait()
                except KeyboardInterrupt:
                    cancelled = True
                    forced, termination_issues = self._terminate_and_wait(process, context)
                    issues.extend(termination_issues)
                except Exception as error:
                    infrastructure_failed = True
                    issues.append(execution_issue(
                        "KAM-EXEC-E202",
                        invocation.stage + ":wait",
                        "child process cannot be reaped ({0})".format(
                            type(error).__name__
                        ),
                    ))
                    forced_after_wait, termination_issues = self._terminate_and_wait(
                        process, context
                    )
                    forced = forced or forced_after_wait
                    issues.extend(termination_issues)
            if child_exit_code is None and process is not None:
                child_exit_code = getattr(process, "returncode", None)

            if dispatcher.failure is not None:
                callback_failed = True
                if dispatcher.failure not in issues:
                    issues.append(dispatcher.failure)
            if cancelled:
                issues.append(execution_issue(
                    "KAM-EXEC-W101",
                    invocation.stage + ":process",
                    "run interrupted by user",
                ))
                status = "cancelled"
            elif infrastructure_failed or callback_failed:
                status = "failed"
            elif child_exit_code != 0:
                issues.append(execution_issue(
                    "KAM-EXEC-E203",
                    invocation.stage + ":process",
                    "child process returned nonzero exit code {0}".format(
                        child_exit_code
                    ),
                ))
                status = "failed"
            else:
                status = "succeeded"
            cleanup_failed = False
            if process is not None and getattr(process, "stdout", None) is not None:
                try:
                    process.stdout.close()
                except Exception as error:
                    cleanup_failed = True
                    issues.append(execution_issue(
                        "KAM-EXEC-E202",
                        invocation.stage + ":stream",
                        "child output stream cannot be closed ({0})".format(
                            type(error).__name__
                        ),
                    ))
                else:
                    process = None
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception as error:
                    cleanup_failed = True
                    issues.append(execution_issue(
                        "KAM-EXEC-E202",
                        invocation.stage + ":log",
                        "stage log cannot be closed ({0})".format(
                            type(error).__name__
                        ),
                    ))
                else:
                    log_handle = None
            if cleanup_failed and status == "succeeded":
                status = "failed"
            return ProcessOutcome(
                invocation.stage,
                status,
                child_exit_code,
                started,
                self._utc_clock(),
                invocation.log_path,
                line_count,
                forced,
                tuple(issues),
            )
        finally:
            if process is not None and getattr(process, "stdout", None) is not None:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass


__all__ = [
    "MAX_OUTPUT_LINE_CHARACTERS",
    "PosixProcessLifecycle",
    "ProcessLifecycle",
    "ProcessPort",
    "SubprocessPort",
    "WindowsProcessLifecycle",
    "build_child_environment",
]

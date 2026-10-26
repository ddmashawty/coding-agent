from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Executor(ABC):
    @abstractmethod
    def run(self, command: str, *, timeout: float) -> CommandResult:
        raise NotImplementedError

    @abstractmethod
    def read_text(self, path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def write_text(self, path: str, content: str) -> None:
        raise NotImplementedError

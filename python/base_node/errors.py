from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    file: str
    line: int
    col: int
    message: str
    # "error", or "warning": the text is read all the same, and something in it should change
    severity: str = "error"

    def __str__(self):
        mark = "" if self.severity == "error" else f"{self.severity}: "
        return f"{self.file}:{self.line}:{self.col}  {mark}{self.message}"


class BnError(Exception):
    """One or more diagnostics, sorted by position."""

    def __init__(self, diagnostics):
        self.diagnostics = sorted(diagnostics, key=lambda d: (d.line, d.col))
        super().__init__("\n".join(str(d) for d in self.diagnostics))

"""The pluggable TestType interface and the small data types around it.

A TestType encapsulates everything that varies between bench tests, so the GUI,
runner, persistence, and reporting all stay generic:

  * required_instruments  -> which roles the Instruments tab must collect
  * default_config()      -> seeds the Setup tab
  * config_schema()       -> tells the Setup tab how to render editors
  * plan(config)          -> ordered list of test points (plain dicts)
  * prepare()/execute_point()/finish() -> run one point, return a result row
  * result_columns        -> drives the results table and report columns
  * csv_fields            -> full ordered column set written to results.csv

Adding a new test = writing one module implementing this interface and
registering it. No GUI, runner, or reporting code changes.
"""
from dataclasses import dataclass, field
from typing import Any, Callable


# --------------------------------------------------------------------------- #
# Config-schema description (consumed by the generic Setup-tab form renderer)
# --------------------------------------------------------------------------- #
@dataclass
class Field:
    """A single scalar field inside a 'group' section."""
    key: str
    label: str
    kind: str = "number"        # "number" | "int" | "text"
    default: Any = None
    suffix: str = ""            # unit shown after the input, e.g. "Hz"


@dataclass
class TableColumn:
    """A column inside a 'table' section (list of row dicts)."""
    key: str
    label: str
    kind: str = "number"        # "number" | "int" | "text"


@dataclass
class Section:
    """One editable block in the Setup tab: a table of rows or a group of fields."""
    key: str
    title: str
    kind: str                   # "table" | "group"
    columns: list = field(default_factory=list)   # list[TableColumn] (table)
    fields: list = field(default_factory=list)     # list[Field]       (group)
    help: str = ""


# --------------------------------------------------------------------------- #
# Result / reporting description
# --------------------------------------------------------------------------- #
@dataclass
class Column:
    """A column shown in the results table and default report."""
    key: str
    label: str
    kind: str = "text"          # "text" | "number" | "result"
    digits: int = 4


# --------------------------------------------------------------------------- #
# Run-time plumbing passed into execute_point()
# --------------------------------------------------------------------------- #
@dataclass
class RunContext:
    run_dir: str                        # absolute output folder for this run
    screenshot_dir: str                 # absolute; already created
    simulate: bool
    prompt: Callable[[str], None]       # blocks until operator confirms; may raise
    status: Callable[[str], None]       # emit a human-readable progress line


@dataclass
class Callbacks:
    """UI/CLI hooks the runner calls. All optional; default to no-ops."""
    on_start: Callable[[int], None] = lambda total: None
    on_point_done: Callable[[int, dict], None] = lambda index, row: None
    on_status: Callable[[str], None] = lambda message: None
    on_screenshot: Callable[[str], None] = lambda path: None
    prompt: Callable[[str], None] = lambda message: None


class AbortError(Exception):
    """Raised by a prompt callback (or the runner) to abort the run cleanly."""


class TestType:
    """Base class for a bench test. Subclass and register in testtypes/."""

    id: str = ""
    name: str = ""
    description: str = ""
    required_instruments: list = []
    result_columns: list = []           # list[Column]
    csv_fields: list = []               # ordered keys written to results.csv

    # Optional datasheet-assist: if True, the Setup tab shows a button that fills
    # datasheet_field = (section_key, field_key) from an uploaded MOSFET PDF.
    wants_datasheet: bool = False
    datasheet_field = None

    # ---- configuration -------------------------------------------------- #
    def default_config(self) -> dict:
        raise NotImplementedError

    def config_schema(self) -> list:
        """Return list[Section] describing the editable config. Default: none."""
        return []

    # ---- execution ------------------------------------------------------ #
    def plan(self, config: dict) -> list:
        """Return the ordered list of test-point dicts (each needs a 'label')."""
        raise NotImplementedError

    def prepare(self, instruments: dict, config: dict, ctx: RunContext) -> None:
        """One-time setup before the point loop (e.g. arm scope measurements)."""

    def execute_point(self, point: dict, instruments: dict, config: dict,
                      ctx: RunContext) -> dict:
        """Run one point and return a result row keyed by csv_fields."""
        raise NotImplementedError

    def finish(self, instruments: dict, config: dict, ctx: RunContext) -> None:
        """Optional teardown hook (instruments are closed by the runner)."""

    # ---- summary helper ------------------------------------------------- #
    @staticmethod
    def summarize(rows: list) -> dict:
        fails = [r for r in rows if r.get("result") == "FAIL"]
        return {"total": len(rows), "pass": len(rows) - len(fails), "fail": len(fails)}

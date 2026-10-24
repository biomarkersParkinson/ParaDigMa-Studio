"""Header-only signal mapping, suggestions and batch validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .axis_mapping import IMU_COLUMNS, validate_axis_inversions
from .preparation_contracts import IMUSignal, SignalColumns

if TYPE_CHECKING:
    import pandas as pd

SIGNALS = {
    "time": "Time",
    **{f"accelerometer_{axis}": f"Accelerometer {axis.upper()}" for axis in "xyz"},
    **{f"gyroscope_{axis}": f"Gyroscope {axis.upper()}" for axis in "xyz"},
    "green": "Green PPG",
}
ALIASES = {
    "time": ("timestamp", "device_time", "time_stamp"),
    **{f"accelerometer_{axis}": (f"acc_{axis}", f"accel_{axis}", f"a{axis}") for axis in "xyz"},
    **{f"gyroscope_{axis}": (f"gyr_{axis}", f"gyro_{axis}", f"g{axis}") for axis in "xyz"},
    "green": ("ppg", "ppg_green", "green_ppg"),
}


def validate_signal_columns(value: object) -> SignalColumns | None:
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or value.keys() != SIGNALS.keys()
        or any(source is not None and not isinstance(source, str) for source in value.values())
    ):
        raise ValueError("Signal columns must assign each signal a source column or null.")
    sources = [source for source in value.values() if source is not None]
    if len(sources) != len(set(sources)):
        raise ValueError("A source column cannot be assigned to multiple signals.")
    # Exact canonical keys and string/null values were checked above.
    return cast("SignalColumns", dict(value))


def selected_signal_sources(columns: Iterable[str], mapping: Mapping[str, str]) -> list[str]:
    """Keep selected signal sources and auxiliary columns, without name fallback."""
    return [column for column in columns if column not in SIGNALS or column in mapping]


def apply_signal_columns(
    frame: pd.DataFrame,
    mapping: Mapping[str, str] | None,
    signal_columns: object = None,
) -> pd.DataFrame:
    """Apply explicit selections, or literal renaming for direct Python callers."""
    selected = validate_signal_columns(signal_columns)
    routes = dict(mapping or {})
    if selected is not None:
        routes = {source: target for source, target in routes.items() if target not in SIGNALS}
        routes.update({source: target for target, source in selected.items() if source is not None})
        columns = selected_signal_sources(frame.columns, routes)
        if len(columns) != len(frame.columns):
            frame = _column_view(frame, columns)
    return frame.rename(columns=routes, copy=False)


def _column_view(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Avoid copying a long recording just to exclude unused signal columns."""
    import pandas as pd

    if not frame.columns.is_unique:
        return frame[columns]  # Preserve duplicate-name errors at the caller's boundary.
    result = pd.DataFrame(
        {column: frame[column] for column in columns}, index=frame.index, copy=False
    )
    result.columns.name = frame.columns.name
    result.attrs = frame.attrs
    return result


def required_signals(modules: Iterable[str]) -> set[str]:
    selected = set(modules)
    required = {"time"}
    if "gait" in selected:
        required.update(f"accelerometer_{axis}" for axis in "xyz")
    if selected & {"gait", "tremor"}:
        required.update(f"gyroscope_{axis}" for axis in "xyz")
    if "pulse_rate" in selected:
        required.add("green")
    return required


@dataclass(frozen=True)
class MappingValidation:
    recordings: int
    compatible: int
    details: tuple[str, ...]


class ColumnMapping:
    """Keep one source choice per signal without owning sample data."""

    def __init__(self) -> None:
        self.schemas: dict[str, tuple[str, ...]] = {}
        self.names: dict[str, str] = {}
        self.choices: dict[str, str | None] = dict.fromkeys(SIGNALS)
        self.inversions: set[str] = set()
        self._explicit: set[str] = set()

    @property
    def columns(self) -> list[str]:
        return list(dict.fromkeys(column for schema in self.schemas.values() for column in schema))

    def set_recordings(
        self, schemas: Mapping[str, Sequence[str]], names: Mapping[str, str]
    ) -> None:
        self.schemas = {key: tuple(columns) for key, columns in schemas.items()}
        self.names = dict(names)
        self._refresh_defaults()

    def _refresh_defaults(self) -> None:
        available = set(self.columns)
        used = {self.choices[target] for target in self._explicit}
        for target in SIGNALS.keys() - self._explicit:
            self.choices[target] = target if target in available - used else None

    def set_mapping(
        self,
        mapping: Mapping[str, str] | None,
        *,
        signal_columns: dict[str, str | None] | None = None,
    ) -> None:
        selected = validate_signal_columns(signal_columns)
        routes = dict(mapping or {})
        if any(target not in SIGNALS for target in routes.values()) or len(
            set(routes.values())
        ) != len(routes):
            raise ValueError("Select one source column per supported signal.")
        inversions = self.inversions.copy()
        self.reset()
        self.inversions = inversions
        if selected is not None:
            self.choices = dict(selected.items())
            self._explicit = set(SIGNALS)
        else:
            self.choices.update({target: source for source, target in routes.items()})
            self._explicit = set(routes.values())
            self._refresh_defaults()

    def choose(self, target: str, source: str | None) -> None:
        if target not in SIGNALS:
            raise ValueError(f"Unknown signal: {target}")
        self.choices[target] = source
        self._explicit.add(target)
        self._refresh_defaults()

    def reset(self) -> None:
        self.inversions.clear()
        self._explicit.clear()
        available = set(self.columns)
        self.choices = {target: target if target in available else None for target in SIGNALS}

    def set_axis_inversions(self, inversions: object) -> None:
        self.inversions = set(validate_axis_inversions(inversions) or [])

    def invert(self, target: str, checked: bool) -> None:
        if target not in IMU_COLUMNS:
            raise ValueError(f"Signal has no axis direction: {target}")
        if checked:
            self.inversions.add(target)
        else:
            self.inversions.discard(target)

    def axis_inversions(self) -> list[IMUSignal]:
        return [target for target in IMU_COLUMNS if target in self.inversions]

    def source_conflicts(self) -> set[str]:
        sources = [source for source in self.choices.values() if source is not None]
        return {source for source, count in Counter(sources).items() if count > 1}

    def mapping(self) -> dict[str, str]:
        conflicts = self.source_conflicts()
        if conflicts:
            raise ValueError(
                "Columns assigned to multiple signals: " + ", ".join(sorted(conflicts))
            )
        return {
            source: target
            for target, source in self.choices.items()
            if source is not None and source != target
        }

    def signal_columns(self) -> SignalColumns:
        self.mapping()  # Reject a source selected for multiple signals.
        # choices is initialized with SIGNALS and only accepts canonical targets.
        return cast("SignalColumns", dict(self.choices))

    def _selected_mapping(self) -> dict[str, str]:
        return {source: target for target, source in self.choices.items() if source is not None}

    def suggestions(self) -> dict[str, str]:
        used = set(self.choices.values())
        return {
            target: source
            for target, source in self.automatic_choices().items()
            if source is not None and self.choices[target] is None and source not in used
        }

    def automatic_choices(self) -> dict[str, str | None]:
        """Match headers independently of manual choices; exact names take precedence."""
        if not self.schemas:
            return dict.fromkeys(SIGNALS)
        common = set.intersection(*(set(columns) for columns in self.schemas.values()))
        choices: dict[str, str | None] = {}
        for target in SIGNALS:
            if target in common:
                choices[target] = target
                continue
            names = {name.casefold() for name in (*ALIASES[target], target)}
            matches = [column for column in common if column.casefold() in names]
            choices[target] = matches[0] if len(matches) == 1 else None
        return choices

    def matches_automatic(self) -> bool:
        return self.choices == self.automatic_choices()

    def auto_match(self) -> None:
        self.choices = self.automatic_choices()
        self._explicit = {
            target
            for target, source in self.choices.items()
            if source is not None and source != target
        }

    def target_conflicts(self) -> dict[str, list[str]]:
        if self.source_conflicts():
            return {}
        mapping = self._selected_mapping()
        conflicts: dict[str, list[str]] = {}
        for key, columns in self.schemas.items():
            renamed = [
                mapping.get(column, column) for column in selected_signal_sources(columns, mapping)
            ]
            for target, count in Counter(renamed).items():
                if count > 1:
                    conflicts.setdefault(target, []).append(self.names.get(key, key))
        return conflicts

    def validate(self, modules: Iterable[str]) -> MappingValidation:
        conflicts = self.source_conflicts()
        if conflicts:
            return MappingValidation(
                len(self.schemas),
                0,
                ("Columns assigned to multiple signals: " + ", ".join(sorted(conflicts)),),
            )
        mapping = self._selected_mapping()
        required = required_signals(modules)
        missing_counts: Counter[str] = Counter()
        duplicate_counts: Counter[str] = Counter()
        compatible = 0
        for columns in self.schemas.values():
            renamed = [
                mapping.get(column, column) for column in selected_signal_sources(columns, mapping)
            ]
            missing = required - set(renamed)
            duplicates = [column for column, count in Counter(renamed).items() if count > 1]
            missing_counts.update(SIGNALS[target] for target in SIGNALS if target in missing)
            duplicate_counts.update(duplicates)
            compatible += not missing and not duplicates
        return MappingValidation(
            len(self.schemas),
            compatible,
            self._issue_details("Missing", missing_counts)
            + self._issue_details("Conflicting column names:", duplicate_counts),
        )

    def _issue_details(self, prefix: str, counts: Counter[str]) -> tuple[str, ...]:
        groups: dict[int, list[str]] = {}
        for name, count in counts.items():
            groups.setdefault(count, []).append(name)
        return tuple(
            f"{prefix} {', '.join(names)}"
            + (f" ({count} of {len(self.schemas)} recordings)" if count < len(self.schemas) else "")
            for count, names in groups.items()
        )

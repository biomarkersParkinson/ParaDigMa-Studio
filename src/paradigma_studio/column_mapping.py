"""Header-only signal mapping, suggestions and batch validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .axis_mapping import IMU_COLUMNS, validate_axis_inversions

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
    """Keep explicit choices and old saved mappings without owning sample data."""

    def __init__(self) -> None:
        self.schemas: dict[str, tuple[str, ...]] = {}
        self.names: dict[str, str] = {}
        self.choices: dict[str, str | None] = dict.fromkeys(SIGNALS)
        self.extra: dict[str, str] = {}
        self.inversions: set[str] = set()
        self._explicit: set[str] = set()
        self._identities: set[str] = set()

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
        used = {self.choices[target] for target in self._explicit} | set(self.extra)
        for target in SIGNALS.keys() - self._explicit:
            self.choices[target] = target if target in available - used else None

    def set_mapping(self, mapping: Mapping[str, str] | None) -> None:
        inversions = self.inversions.copy()
        self.reset()
        self.inversions = inversions
        for source, target in (mapping or {}).items():
            if target in SIGNALS and target not in self._explicit:
                self.choices[target] = source
                self._explicit.add(target)
                if source == target:
                    self._identities.add(source)
            else:
                # Preserve arbitrary legacy names and duplicate targets exactly.
                self.extra[source] = target
        self._refresh_defaults()

    def choose(self, target: str, source: str | None) -> None:
        if target not in SIGNALS:
            raise ValueError(f"Unknown signal: {target}")
        self.choices[target] = (
            source
            if source is not None
            else (target if target in self.columns and target not in self.extra else None)
        )
        self._explicit.add(target)
        self._identities.discard(target)
        self.extra = {key: value for key, value in self.extra.items() if value != target}
        self._refresh_defaults()

    def reset(self) -> None:
        self.inversions.clear()
        self.extra.clear()
        self._explicit.clear()
        self._identities.clear()
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

    def axis_inversions(self) -> list[str]:
        return [target for target in IMU_COLUMNS if target in self.inversions]

    def source_conflicts(self) -> set[str]:
        sources = [source for source in self.choices.values() if source is not None]
        sources.extend(self.extra)
        return {source for source, count in Counter(sources).items() if count > 1}

    def mapping(self) -> dict[str, str]:
        conflicts = self.source_conflicts()
        if conflicts:
            raise ValueError(
                "Columns assigned to multiple signals: " + ", ".join(sorted(conflicts))
            )
        return {
            **self.extra,
            **{
                source: target
                for target, source in self.choices.items()
                if source is not None and (source != target or source in self._identities)
            },
        }

    def suggestions(self) -> dict[str, str]:
        if not self.schemas:
            return {}
        common = set.intersection(*(set(columns) for columns in self.schemas.values()))
        used = set(self.choices.values()) | set(self.extra)
        suggested = {}
        for target, source in self.choices.items():
            if source is not None:
                continue
            names = {name.casefold() for name in (*ALIASES[target], target)}
            matches = [column for column in common - used if column.casefold() in names]
            if len(matches) == 1:
                suggested[target] = matches[0]
                used.add(matches[0])
        return suggested

    def auto_match(self, targets: Iterable[str] = SIGNALS) -> None:
        allowed = set(targets)
        for target, source in self.suggestions().items():
            if target in allowed:
                self.choose(target, source)

    def target_conflicts(self) -> dict[str, list[str]]:
        if self.source_conflicts():
            return {}
        mapping = self.mapping()
        conflicts: dict[str, list[str]] = {}
        for key, columns in self.schemas.items():
            for target, count in Counter(mapping.get(column, column) for column in columns).items():
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
        mapping = self.mapping()
        required = required_signals(modules)
        details = []
        for key, columns in self.schemas.items():
            renamed = [mapping.get(column, column) for column in columns]
            missing = required - set(renamed)
            duplicates = [column for column, count in Counter(renamed).items() if count > 1]
            issues = []
            if missing:
                issues.append(
                    "Missing "
                    + ", ".join(SIGNALS[target] for target in SIGNALS if target in missing)
                )
            if duplicates:
                issues.append("Conflicting column names: " + ", ".join(duplicates))
            if issues:
                details.append(f"{self.names.get(key, key)}: {'; '.join(issues)}")
        return MappingValidation(
            len(self.schemas), len(self.schemas) - len(details), tuple(details)
        )

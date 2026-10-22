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
        if source is None:
            self._explicit.discard(target)
        else:
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
        used = set(self.choices.values()) | set(self.extra)
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

    def _unrelated_mappings(self, choices: Mapping[str, str | None]) -> dict[str, str]:
        used = set(choices.values())
        return {
            source: target
            for source, target in self.extra.items()
            if source not in used and target not in SIGNALS
        }

    def matches_automatic(self) -> bool:
        choices = self.automatic_choices()
        return self.choices == choices and self.extra == self._unrelated_mappings(choices)

    def auto_match(self) -> None:
        self.choices = self.automatic_choices()
        self.extra = self._unrelated_mappings(self.choices)
        self._explicit = {
            target
            for target, source in self.choices.items()
            if source is not None and source != target
        }
        self._identities.clear()

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
        missing_counts: Counter[str] = Counter()
        duplicate_counts: Counter[str] = Counter()
        compatible = 0
        for columns in self.schemas.values():
            renamed = [mapping.get(column, column) for column in columns]
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

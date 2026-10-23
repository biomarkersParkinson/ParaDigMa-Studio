"""Keep the typed lazy adapters aligned with the pinned upstream API."""

from inspect import signature

import numpy as np
import pandas as pd
import pytest
from paradigma import load, orchestrator, prepare_data, segmenting

from paradigma_studio import paradigma_api
from paradigma_studio.preparation_contracts import OfficialRunOptions


def test_orchestrator_keyword_contract_matches_pinned_upstream():
    assert (
        OfficialRunOptions.__optional_keys__
        == signature(orchestrator.run_paradigma).parameters.keys()
    )
    assert not OfficialRunOptions.__required_keys__


@pytest.mark.parametrize(
    "upstream, name, args, kwargs",
    [
        (load, "load_single_data_file", ("sensor.csv",), {}),
        (prepare_data, "prepare_raw_data", (pd.DataFrame(),), {}),
        (
            prepare_data,
            "prepare_raw_data",
            (),
            {
                "df": pd.DataFrame(),
                "accelerometer_units": "g",
                "gyroscope_units": "rad/s",
                "time_input_unit": "difference_ms",
                "resampling_frequency": 64.0,
                "column_mapping": {"ppg": "green"},
                "device_orientation": ["-y", "x", "z"],
                "validate": False,
                "auto_segment": True,
                "max_segment_gap_s": 3.0,
                "min_segment_length_s": 2.0,
            },
        ),
        (
            prepare_data,
            "correct_watch_orientation",
            (pd.DataFrame(), ["x", "-y", "z"]),
            {"sensor": "gyroscope"},
        ),
        (segmenting, "create_segments", (np.array([0.0, 0.1, 2.0]),), {"max_segment_gap_s": 1.5}),
        (
            segmenting,
            "discard_segments",
            (pd.DataFrame(), "section", 1.5, 29.97),
            {"format": "windows"},
        ),
    ],
)
def test_adapters_forward_objects_and_preserve_official_defaults(
    monkeypatch, upstream, name, args, kwargs
):
    original = signature(getattr(upstream, name))
    adapter = getattr(paradigma_api, name)
    # Check defaults against upstream rather than duplicating them in this test.
    assert {
        key: (param.kind, param.default) for key, param in signature(adapter).parameters.items()
    } == {key: (param.kind, param.default) for key, param in original.parameters.items()}
    expected = original.bind(*args, **kwargs)
    supplied = set(expected.arguments)
    expected.apply_defaults()
    returned = object()

    def capture(*received_args, **received_kwargs):
        actual = original.bind(*received_args, **received_kwargs)
        actual.apply_defaults()
        assert actual.arguments.keys() == expected.arguments.keys()
        for key, value in actual.arguments.items():
            if key in supplied:
                assert value is expected.arguments[key], key
            else:
                assert value == expected.arguments[key], key
        return returned

    monkeypatch.setattr(upstream, name, capture)
    assert adapter(*args, **kwargs) is returned


def test_orchestrator_forwards_only_supplied_keywords_without_copying(monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0], "green": [1.0, 2.0]})
    settings = {
        "dfs": {"recording_001": frame},
        "pipelines": ["pulse_rate"],
        "time_input_unit": "relative_s",
        "device_orientation": None,
        "return_intermediate": ["classification", "quantification"],
    }
    returned = {"errors": []}

    def capture(**actual):
        assert actual.keys() == settings.keys()
        for key, value in actual.items():
            assert value is settings[key], key
        return returned

    monkeypatch.setattr(orchestrator, "run_paradigma", capture)
    assert paradigma_api.run_paradigma(**settings) is returned

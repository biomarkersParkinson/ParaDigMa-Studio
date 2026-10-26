"""Field guidance for the pinned ParaDigMa 1.1.2 API and Studio input settings.

References point to the official source revision recorded in scientific tests.
Desktop exclusion/combined execution options are identified as wrapper behavior.
"""

SOURCE = "https://github.com/biomarkersParkinson/paradigma/blob/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/src/paradigma/"

# Pinned 1.1.2 prepare_raw_data defaults; kept lightweight for desktop startup.
DEFAULT_MAX_GAP_SECONDS = 1.5
DEFAULT_MIN_SECTION_SECONDS = 1.5
# Studio policies are enabled on new input; the Python API keeps them opt-in.
DEFAULT_DROP_MISSING_SAMPLES = True
DEFAULT_SPLIT_BY_GAPS = True

SIGNAL_COLUMNS_HELP_BEFORE_HTML = (
    "<p>Choose the column in your recordings that supplies each signal. Dropdowns list the "
    "available columns, and only your selections are used for analysis. Select "
    "<b>Not included</b> to leave a signal unassigned.</p>"
    "<p>Studio automatically matches column names shared by all loaded recordings. "
    "<b>From file</b> marks each automatic match. You can change any selection; "
    "<b>Default</b> restores the automatic matches for all signals, including optional "
    "signals, while keeping your axis inversions.</p>"
    "<p>One set of column selections and inversions applies to the whole batch. Check "
    "that column names and axis conventions are consistent across your recordings. "
    "Loading new files resets Analyze and prefills available settings from the new input.</p>"
    "<p>Map your recording’s accelerometer and gyroscope columns to the positive axis "
    "directions shown for the wrist on which the sensor was worn. Use <b>Invert axis</b> "
    "where a source axis points in the opposite direction.</p>"
)
SIGNAL_COLUMNS_HELP_AFTER_HTML = (
    "<p>Select the actual <b>Watch side</b>. ParaDigMa adjusts for left/right wrist "
    "differences during processing. <b>Do not apply that wrist-side adjustment yourself</b>"
    "—provide the data in the orientation illustrated above.</p>"
    "<p><b>Show optional signals</b> reveals additional channels. The compatibility summary "
    "shows which recordings have the signals needed by the selected modules. Click a "
    "warning icon to read its explanation, or use <b>Show details</b> for matching and "
    "compatibility information. If a previously selected column is unavailable, choose "
    "a replacement or <b>Not included</b>; its warning identifies the missing column.</p>"
)

FIELD_HELP = {
    "Time origin": (
        "Calendar date and time corresponding to analysis time zero. The default comes from the selected "
        "absolute Time column or recording-start metadata for relative/difference time. Other date columns "
        "are ignored. Without an available origin, the field displays Not set. "
        "Use Default to restore the automatic value. Uncheck to show "
        "elapsed seconds. This desktop display setting does not change the sensor times or scientific analysis.",
        "util.py",
    ),
    "Analysis modules": (
        "Select any combination. Gait needs time, accelerometer_x/y/z and gyroscope_x/y/z; "
        "tremor needs time and gyroscope_x/y/z. Pulse-rate analysis needs time and green (raw PPG); "
        "accelerometer channels are optional. ParaDigMa 1.1.2's high-level pulse-rate pipeline "
        "assesses quality from PPG only. A device's exported heart-rate values are not raw PPG. "
        "The desktop runs IMU and pulse-rate workflows separately when selected together.",
        "orchestrator.py",
    ),
    "Watch side": (
        "Select the actual wrist on which the sensor was worn. Provide the input axes in the "
        "orientation shown in the Signal columns explanation. ParaDigMa adjusts for left/right "
        "wrist differences during pipeline preprocessing; do not apply that wrist-side adjustment "
        "yourself. Supported imports do not currently select the wrist from metadata. "
        "This field is used for gait and is inactive for tremor or pulse rate alone. "
        "Use the source-column mapping and Invert axis to align the original device axes "
        "with the illustrated input directions.",
        "preprocessing.py#L364",
    ),
    "Acceleration units": (
        "Choose the units in the input file: g (gravitational acceleration) or m/s². "
        "ParaDigMa converts m/s² to g during preparation. A stationary gravity axis is typically "
        "about 1 g or 9.81 m/s². Use the device's documentation to confirm. "
        "The field is inactive when no accelerometer axis is mapped to an available column.",
        "prepare_data.py",
    ),
    "Gyroscope units": (
        "Choose deg/s (degrees per second) or rad/s (radians per second), as stored in the file. "
        "ParaDigMa converts rad/s to deg/s during preparation. "
        "The field is inactive when no gyroscope axis is mapped to an available column.",
        "prepare_data.py",
    ),
    "Time units": (
        "relative_s: elapsed seconds (0, 0.01, 0.02); relative_ms: elapsed milliseconds (0, 10, 20). "
        "absolute_s / absolute_ms: Unix timestamps in seconds / milliseconds. "
        "difference_s / difference_ms: time increments between samples (0, 0.01, 0.01 / 0, 10, 10). "
        "These options require numeric values, not date strings. ParaDigMa converts time to relative seconds.",
        "util.py",
    ),
    "Split recordings at time gaps": (
        "Analyze continuous recording sections independently. A time interval larger than Maximum gap "
        "starts a new section; sections shorter than Minimum section duration are excluded. "
        "Enabled by default in Studio; the Python API keeps this opt-in. "
        "Multiple sections are identified by file_key.",
        "orchestrator.py",
    ),
    "Exclude missing sensor samples": (
        "Enabled by default in Studio: exclude rows with missing or non-finite channels required by the selected workflow, "
        "then analyze valid sections independently. Exclusion counts are saved in metadata. "
        "Unchecked: reject invalid required values. Non-monotonic timestamps and missing time increments need correction; "
        "the app does not invent sensor values. IMU and pulse-rate workflows check their own channels.",
        "prepare_data.py",
    ),
    "Maximum gap": (
        "Maximum allowed interval between successive samples, in seconds. With gap splitting enabled, "
        "a larger interval starts a new continuous section. The official preparation default is 1.5 s; "
        "Default restores this value. This is a gap between samples, not an analysis window length. "
        "Choose a threshold appropriate to your device's sampling interval and recording interruptions.",
        "prepare_data.py",
    ),
    "Minimum section duration": (
        "Minimum continuous section length in seconds when gap splitting is enabled. "
        "Shorter sections are discarded. The official preparation default is 1.5 s; Default restores this value. "
        "Individual algorithms may require longer windows and can return no measurements for short sections.",
        "prepare_data.py",
    ),
    "Signal columns": (
        # Trusted HTML paragraphs are split around the illustration in the UI.
        SIGNAL_COLUMNS_HELP_BEFORE_HTML + SIGNAL_COLUMNS_HELP_AFTER_HTML,
        "https://biomarkersparkinson.github.io/paradigma/guides/coordinate_system.html",
    ),
}

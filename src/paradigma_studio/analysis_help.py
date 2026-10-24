"""Field guidance from the pinned ParaDigMa 1.1.2 API docstrings.

References point to the official source revision recorded in scientific tests.
Desktop exclusion/combined execution options are identified as wrapper behavior.
"""

SOURCE = "https://github.com/biomarkersParkinson/paradigma/blob/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/src/paradigma/"

# Pinned 1.1.2 prepare_raw_data defaults; kept lightweight for desktop startup.
DEFAULT_MAX_GAP_SECONDS = 1.5
DEFAULT_MIN_SECTION_SECONDS = 1.5

FIELD_HELP = {
    "Time origin": (
        "Calendar date and time corresponding to analysis time zero. The default comes from the selected "
        "absolute Time column or recording-start metadata for relative/difference time. Other date columns "
        "are ignored. Use Default to restore it. Uncheck to show "
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
        "Choose the wrist on which the sensor was worn. ParaDigMa applies its right-wrist IMU inversion "
        "during pipeline preprocessing. Supported imports do not currently select the wrist from metadata. "
        "Set this separately from the device-axis mapping; "
        "do not manually invert axes merely because the watch was on the right wrist.",
        "preprocessing.py#L364",
    ),
    "Acceleration units": (
        "Choose the units in the input file: g (gravitational acceleration) or m/s². "
        "ParaDigMa converts m/s² to g during preparation. A stationary gravity axis is typically "
        "about 1 g or 9.81 m/s². Use the device's documentation to confirm.",
        "prepare_data.py",
    ),
    "Gyroscope units": (
        "Choose deg/s (degrees per second) or rad/s (radians per second), as stored in the file. "
        "ParaDigMa converts rad/s to deg/s during preparation.",
        "prepare_data.py",
    ),
    "Time units": (
        "relative_s: elapsed seconds (0, 0.01, 0.02); relative_ms: elapsed milliseconds (0, 10, 20). "
        "absolute_s / absolute_ms: Unix timestamps in seconds / milliseconds. "
        "difference_s / difference_ms: time increments between samples (0, 0.01, 0.01 / 0, 10, 10). "
        "These options require numeric values, not date strings. ParaDigMa converts time to relative seconds.",
        "util.py",
    ),
    "Already prepared": (
        "Skip the wrapper's unit and device-axis conversions only when data already uses relative seconds, "
        "acceleration in g and gyroscope values in deg/s, with axes in ParaDigMa orientation. "
        "Column mapping still applies. Official pipeline resampling, filtering and watch-side correction "
        "still run; do not select this simply because a file has been loaded.",
        "prepare_data.py",
    ),
    "Split recordings at time gaps": (
        "Analyze continuous recording sections independently. A time interval larger than Maximum gap "
        "starts a new section; sections shorter than Minimum section duration are excluded. "
        "Disabled by default, matching the official orchestrator. Multiple sections are identified by file_key.",
        "orchestrator.py",
    ),
    "Exclude missing sensor samples": (
        "Desktop option: exclude rows with missing or non-finite channels required by the selected workflow, "
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
        "Minimum continuous section length in seconds when gap splitting is enabled for raw data. "
        "Shorter sections are discarded. The official preparation default is 1.5 s; Default restores this value. "
        "Individual algorithms may require longer windows and can return no measurements for short sections.",
        "prepare_data.py",
    ),
    "Signal columns": (
        "Choose the column in your files for each required signal. Exact ParaDigMa names are recognized "
        "automatically. Processing uses the dropdown selections only: a different selected source "
        "replaces the standard-name source, and unselected standard-name columns are not used as a fallback. "
        "Choose Not included to leave any signal unassigned, including when its standard-name column exists. "
        "Selections remain in effect for the current loaded recording or batch. Loading new files "
        "resets Analyze and fills available settings from the new input. "
        "Signal columns are matched automatically on load from names shared "
        "by every recording. Exact names take precedence over unique aliases such as timestamp, ax, "
        "gyr_x or ppg. From file marks each automatically matched signal. "
        "Default restores all automatic matches, including optional signals, replacing manual selections "
        "and clearing fields without an unambiguous match. Axis inversions are kept. "
        "Show optional signals exposes other channels. "
        "Compare your device manual's X/Y/Z arrows with ParaDigMa's reference figure below. "
        "Select the source column that should become each ParaDigMa axis; tick Invert axis when "
        "its arrow points in the opposite direction. For example, choose sensor Y for Accelerometer X "
        "and tick Invert axis: toolbox X = minus sensor Y. Set accelerometer and gyroscope directions "
        "independently; use each source column once. Set Watch side separately. "
        "One mapping and set of inversions applies to all loaded recordings. Click warning icons to "
        "read their messages. Warning icons and "
        "Show details summarize missing signals and conflicting names across recordings without "
        "listing filenames; counts identify issues affecting only some recordings. "
        "Source-column options list only loaded columns; missing saved choices "
        "remain in settings and are named in their warning until replaced. "
        "Already prepared skips inversions, while column mapping still applies. Missing signals remain "
        "subject to the existing per-recording and per-module analysis validation.",
        "https://biomarkersparkinson.github.io/paradigma/guides/coordinate_system.html",
    ),
}

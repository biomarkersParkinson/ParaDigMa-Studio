test_data.CWA is the unmodified public Axivity example recording from the
official ParaDigMa project (ParaDigMa contributors), used for regression tests
and the packaged executable's smoke test.

Source:
https://github.com/biomarkersParkinson/paradigma/blob/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/example_data/axivity/test_data.CWA

SHA-256: 32119972958fd19d110183650e611f1eda9d26b118336a931e5dd5308532a409

Distributed under the source project's Apache License 2.0; see the accompanying
notices/LICENSE-paradigma.txt. This is a test recording, not a patient's import or a
scientific reference result. No changes were made to the recording.

test_data.avro is also an unmodified public ParaDigMa example, distributed
under the same Apache License 2.0. It contains accelerometer samples and an
empty gyroscope stream, reproducing the optional-gyroscope import failure.

Source:
https://github.com/biomarkersParkinson/paradigma/blob/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/example_data/empatica/test_data.avro

SHA-256: cf31d723385ed74af5c3cc4ab2311929628e105b9152b94ac45b705cf0ba664f

physilog_excerpt.parquet contains two unmodified sample ranges from the public
Physilog recording below: zero-based rows [115929,121939) and [552507,558507).
The rows are concatenated, keeping original channel values and timestamps.
The new Parquet file contains 12,010 rows, including the ten missing gyroscope
samples and a real recording gap. One additional gap reflects omitted rows
between excerpts. These are excerpts, not the complete recording. After
exclusion and gap splitting they form four valid sections of 12,000 samples.

Source (same ParaDigMa Apache 2.0 license):
https://github.com/biomarkersParkinson/paradigma/blob/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/example_data/gait_up_physilog/test_file.parquet

Full source SHA-256: 29b27e2c3c59c35b95086d838b8873b3b11f8bdd81f3855095d23667bad14187
Excerpt SHA-256: 1067a4fce9bf7998cfa12c13c7236ee0c0309ca266eab3b1d1feece5330f447f

app-icon.png and app-icon.ico are based on the orange smartwatch/waveform
figure supplied by the repository owner on 2026-10-06 for this application's
icon. The PNG is an icon-ready version prepared with transparent surroundings;
the ICO contains 16, 24, 32, 48, 64, 128 and 256 pixel representations.
These application graphics are separate from the upstream ParaDigMa example
recordings described above and their accompanying Apache 2.0 license.

notices/ groups the ParaDigMa acknowledgement, unchanged upstream licence,
BibTeX citation and unchanged upstream CITATION.cff metadata. These files are
also copied beside the executable for distribution. See ACKNOWLEDGEMENTS.md
in that folder for citation sources and the desktop's relationship to ParaDigMa.

chevron-down.svg is the application's dropdown indicator, created for the
integrated page layout in version 0.2.1. It is separate from the upstream
recordings and the repository owner's smartwatch icon.

checkmark.svg and select-time.svg are Studio's checkbox and Results cursor
graphics. These original application graphics follow Studio's Apache 2.0
licence in notices/LICENSE-studio.txt.

directions_axes.png is the unchanged ParaDigMa device-orientation reference
figure from docs/source/_static/img/ at the same upstream revision above.
It follows the upstream Apache 2.0 licence; see notices/ACKNOWLEDGEMENTS.md
for its Coordinate System guide link and attribution.

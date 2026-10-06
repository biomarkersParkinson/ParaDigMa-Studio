test_data.CWA is the unmodified public Axivity example recording from the
official ParaDigMa project (ParaDigMa contributors), used for regression tests
and the packaged executable's smoke test.

Source:
https://github.com/biomarkersParkinson/paradigma/blob/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/example_data/axivity/test_data.CWA

SHA-256: 32119972958fd19d110183650e611f1eda9d26b118336a931e5dd5308532a409

Distributed under the source project's Apache License 2.0; see the accompanying
LICENSE-paradigma.txt. This is a test recording, not a patient's import or a
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

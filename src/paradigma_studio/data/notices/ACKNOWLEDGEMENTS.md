# ParaDigMa acknowledgement

ParaDigMa Studio uses the **ParaDigMa (Parkinson's disease Digital Markers)**
Python toolbox for its scientific processing, trained classifiers and analysis
pipelines. Credit for those methods and software belongs to the ParaDigMa authors
and contributors. The desktop provides the Windows interface, import adaptation,
orchestration and result presentation; it is a separate wrapper application.
Its name and acknowledgement do not imply endorsement by the upstream project.

The device-orientation reference figure (`directions_axes.png`) is reproduced
unchanged from ParaDigMa's [Coordinate System guide](https://biomarkersparkinson.github.io/paradigma/guides/coordinate_system.html),
source revision `4735d6d21b2a62b764a0bc7e0f677577e6ce1668`,
`docs/source/_static/img/directions_axes.png`, under the upstream Apache 2.0 licence.

[Official source](https://github.com/biomarkersParkinson/paradigma) ·
[Official documentation](https://biomarkersparkinson.github.io/paradigma/)

## Application development

OpenAI Codex was used to support the development, testing and documentation of ParaDigMa Studio.

## Authors and project acknowledgements

**Core team:** Erik Post, Kars Veldkamp, Nienke Timmermans, Diogo Coutinho Soriano,
Vedran Kasalica, Peter Kok, Twan van Laarhoven and Luc Evers.

**Advisors:** Max Little, Jordan Raykov, Hayriye Cagnan and Bas Bloem.

As acknowledged by the upstream project, the initial release was funded by the
Michael J Fox Foundation (grant #020425) and the Dutch Research Council
(grants #ASDI.2020.060 and #2023.010).

## Citation for research

The official README asks researchers using ParaDigMa to cite:

Post, E., Veldkamp, K., Timmermans, N., Soriano, D. C., Kasalica, V., Kok, P.,
& Evers, L. (2024). **ParaDigMa: Parkinson's disease Digital Markers** [Software].
[https://doi.org/10.5281/zenodo.13838392](https://doi.org/10.5281/zenodo.13838392)

The accompanying **PARADIGMA-CITATION.bib** reproduces the upstream README's
BibTeX entry. **PARADIGMA-CITATION.cff** preserves the upstream citation metadata
unchanged, including its upstream version field. The app's About window reports
the installed toolbox and desktop versions separately.

For research using individual pipelines, also acknowledge their methods and
validation publications, as listed in the official README:

- **Gait:** Post et al. (2025), *Quantifying arm swing in Parkinson's disease*,
  [doi:10.1186/s12984-025-01578-z](https://doi.org/10.1186/s12984-025-01578-z).
  Post et al. (2026), *Longitudinal progression of digital arm swing measures
  during free-living gait in early Parkinson's disease* (preprint),
  [doi:10.64898/2026.01.06.26343500](https://doi.org/10.64898/2026.01.06.26343500).
- **Tremor:** Timmermans et al. (2025), *A generalizable and open-source algorithm
  for real-life monitoring of tremor in Parkinson's disease*,
  [doi:10.1038/s41531-025-01056-2](https://doi.org/10.1038/s41531-025-01056-2).
  Timmermans et al. (2026), *Daily-Life, Sensor-Derived Tremor Measures Are
  Sensitive to Progression in Early Parkinson's Disease*,
  [doi:10.1002/ana.78236](https://doi.org/10.1002/ana.78236).
- **Pulse rate:** Veldkamp et al. (2026), *Heart rate monitoring using wrist
  photoplethysmography in Parkinson disease: feasibility and relation with
  autonomic dysfunction*,
  [doi:10.1186/s12984-026-01994-9](https://doi.org/10.1186/s12984-026-01994-9).

## Licence and redistribution

**ParaDigMa Studio** is licensed under **Apache License 2.0**, supplied in
**LICENSE-studio.txt**. Copyright 2026 ParaDigMa Studio contributors.
This covers the application's original code, documentation and graphics.
Dependencies and third-party assets retain their own licences and notices.

ParaDigMa is licensed under **Apache License 2.0**. The complete, unmodified
upstream licence is supplied in **LICENSE-paradigma.txt**, including this notice:

Copyright (c) 2023, Peter Kok, Vedran Kasalica, Erik Post, Kars Veldkamp,
Nienke Timmermans, Diogo Coutinho Soriano, Luc Evers

Redistributions must retain the applicable upstream notices and supply the
licence; modified upstream files must carry prominent change notices. The
desktop does not modify ParaDigMa's installed package files. Adapted scientific
test generators and converted/excerpted recordings identify their changes in
their source comments and fixture provenance files. The pinned upstream source
does not include a separate NOTICE file. Research citation is the upstream
project's request; the Apache licence's redistribution conditions are separate.

The ParaDigMa attribution and both citation files follow the official README,
LICENSE and CITATION.cff at source revision
[4735d6d21b2a62b764a0bc7e0f677577e6ce1668](https://github.com/biomarkersParkinson/paradigma/tree/4735d6d21b2a62b764a0bc7e0f677577e6ce1668),
matching the pinned ParaDigMa 1.1.2 package. The upstream licence applies to the
ParaDigMa software and its supplied recordings; it does not assign a licence
to the desktop's independently supplied graphics or other dependencies.

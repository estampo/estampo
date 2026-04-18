# Changelog

All notable changes to this project are documented here.

<!-- towncrier release notes start -->

## 0.4.0b2 — 2026-04-18

### Features

- ``estampo validate`` now detects CuraEngine template variables in start gcode and errors when no ``resolve_templates`` stage is configured. ([#557](https://github.com/estampo/estampo/pull/557))
- ``build_config_toml`` now auto-adds ``resolve_templates`` and ``pack`` command stages for CuraEngine + Bambu printer configurations. ([#560](https://github.com/estampo/estampo/pull/560))
- Add ``--workflow-only`` flag to ``estampo init`` for generating just the GitHub Actions workflow. ([#568](https://github.com/estampo/estampo/pull/568))

### Bugfixes

- Set ``docker = true`` on generated command stages (resolve_templates, pack) so container-only tools like ``cura-p1s`` run inside the Docker image. Validation now warns when a command stage executable is not on PATH and ``docker`` is not enabled. ([#570](https://github.com/estampo/estampo/pull/570))
- Include machine dimensions (``machine_width``, ``machine_depth``, ``machine_height``) in ``cura_settings.json`` so template variables like ``{machine_height}`` in CuraEngine end gcode are resolved correctly. ([#572](https://github.com/estampo/estampo/pull/572))
- Add actionable fix instructions to validation warnings (profile not found, unknown pipeline stage, unresolvable profiles).

### Misc

- Update AI setup prompt to document required ``resolve_templates`` stage for CuraEngine + Bambu printers. ([#559](https://github.com/estampo/estampo/pull/559))
- Update ``ai-setup-prompt.md`` validation note to reflect actionable warning messages. ([#566](https://github.com/estampo/estampo/pull/566))
- Bundle bambox 0.4.4 in Docker images (bambox-bridge binary and Python package).
- Fix import ordering lint error in ``http-cloud-print.py``.


## 0.4.0b1 — 2026-04-18

### Features

- Make GitHub Action engine-agnostic — auto-detects OrcaSlicer or CuraEngine from ``estampo.toml`` ([#513](https://github.com/estampo/estampo/pull/513))
- Add ``--workflow`` flag to ``estampo init`` to generate a GitHub Actions slice workflow. ([#538](https://github.com/estampo/estampo/pull/538))

### Bugfixes

- Fix ``validate`` falsely flagging command stages (e.g. ``pack``) as unknown, and update AI setup prompt to use Docker-based CI workflows ([#511](https://github.com/estampo/estampo/pull/511))
- Fix ``{sliced_3mf}`` command variable to resolve to the sliced output file instead of the directory ([#516](https://github.com/estampo/estampo/pull/516))
- Fix credential path in AI setup prompt from ``~/.config/estampo/`` to ``~/.config/bambox/`` ([#518](https://github.com/estampo/estampo/pull/518))
- Make ``estampo validate`` exit non-zero when override keys are invalid, with clearer error messages. ([#541](https://github.com/estampo/estampo/pull/541))
- Error when ``{sliced_3mf}`` cannot resolve to an actual file instead of silently falling back to directory path. ([#543](https://github.com/estampo/estampo/pull/543))
- Include CuraEngine definition IDs (e.g. ``bambox_p1s``) in profile validation so ID-based printer references are recognized. ([#546](https://github.com/estampo/estampo/pull/546))
- Give actionable guidance when CuraEngine printer definition is not found locally instead of a bare error. ([#548](https://github.com/estampo/estampo/pull/548))
- Fix CuraEngine pinned definitions failing at slice time by preserving ``inherits`` for root definitions. ([#552](https://github.com/estampo/estampo/pull/552))
- Include CuraEngine definition IDs in pinned profile validation so ``bambox_p1s`` is recognized after ``estampo profiles pin``. ([#554](https://github.com/estampo/estampo/pull/554))

### Misc

- Decompose ``orca_slice_plate``, ``load_config``, and ``run_wizard`` into smaller focused functions ([#442](https://github.com/estampo/estampo/pull/442))
- Add command stages, override recipes, and important rules to human docs ([#521](https://github.com/estampo/estampo/pull/521))
- Add CuraEngine CLI comparison to README alongside OrcaSlicer comparison ([#523](https://github.com/estampo/estampo/pull/523))
- Highlight AI-friendly declarative workflow as key differentiator in README ([#531](https://github.com/estampo/estampo/pull/531))
- Improve CuraEngine CLI comparison to highlight declarative, git-friendly config. ([#535](https://github.com/estampo/estampo/pull/535))
- Add floating major version tag (``v1``) for the GitHub Action on each stable release. ([#537](https://github.com/estampo/estampo/pull/537))
- Add safety disclaimers and surface command stage warnings to users. ([#544](https://github.com/estampo/estampo/pull/544))
- Recommend profile pinning in AI setup prompt for reproducible builds. ([#550](https://github.com/estampo/estampo/pull/550))
- Add AI authorship note to README
- Add advanced config features to AI setup prompt and ``gcode-info`` to examples
- Hide untested ``estampo watch`` command from CLI help and remove from docs
- Make AI setup prompt copy-paste-ready — AI asks the user questions instead of requiring placeholder editing
- Replace deprecated printer/credential references in docs with bambox guidance


## 0.4.0a1 — 2026-04-17

### Features

- Remove G-code template post-processing from CuraEngine backend; write ``cura_settings.json`` for external resolvers via command stages ([#485](https://github.com/estampo/estampo/pull/485))
- Validate slicer override keys against full settings lists with cross-engine detection and "did you mean?" suggestions ([#503](https://github.com/estampo/estampo/pull/503))
- Add AI setup prompt template (``docs/ai-setup-prompt.md``) for assisted estampo adoption in new projects ([#506](https://github.com/estampo/estampo/pull/506))
- Support PEP 440 pre-release versions (``0.4.0a1``, ``0.4.0b1``, ``0.4.0rc1``) in the release pipeline ([#508](https://github.com/estampo/estampo/pull/508))
- Add JSON Schema for ``estampo.toml`` and ``llm.md`` reference document for humans and AI assistants
- Add ``--json`` flag to ``validate`` and ``run`` commands for structured output
- Add ``SlicerEngine`` protocol in ``engine.py`` formalizing the contract every slicer module must implement
- Add ``estampo info --json``, ``profiles list --json``, ``profiles pin --yes``, and non-interactive ``estampo init --engine --printer --filament --part``
- Add ``{filament}`` and ``{filaments}`` template variables for command stages
- Bundle bambox, bambox-bridge, and cura-p1s into Docker images; add ``docker`` flag for command stages; fix action image reference and stale workflow paths
- ``estampo init`` offers pack/repack command stages for Bambu Lab printers

### Bugfixes

- Fix ``pin_cura_definitions()`` to also copy extruder definitions referenced by the machine definition ([#455](https://github.com/estampo/estampo/pull/455))
- Fix ``profiles pin`` showing unnecessary overwrite prompt after ``profiles add`` on a fresh project ([#457](https://github.com/estampo/estampo/pull/457))
- Extract CuraEngine extruder definitions from Docker image and copy them automatically on ``profiles add`` ([#459](https://github.com/estampo/estampo/pull/459))
- Fix Docker command wrapping producing backslash paths on Windows ([#497](https://github.com/estampo/estampo/pull/497))
- Auto-generated profile and definition update PRs now trigger CI and reuse a stable branch name, so they can actually merge.
- Fix example pack commands and CuraEngine local definition search path
- Include towncrier changelog fragments in auto-generated profile update PRs

### Misc

- Remove trivial wrapper functions in ``init.py`` — call ``ui.*`` and engine modules directly ([#447](https://github.com/estampo/estampo/pull/447))
- Refresh examples: add quickstart config, validate all examples in CI ([#465](https://github.com/estampo/estampo/pull/465))
- Add multi-part example demonstrating arrangement, orientation, scaling, and slicer overrides ([#466](https://github.com/estampo/estampo/pull/466))
- Add multi-filament example demonstrating OrcaSlicer AMS slot assignment ([#467](https://github.com/estampo/estampo/pull/467))
- Add CuraEngine example with Ultimaker 2; add bambox repack stage to OrcaSlicer examples ([#468](https://github.com/estampo/estampo/pull/468))
- Add CuraEngine + Bambu P1S example with bambox printer definition and pack stage
- Add printing instructions and print stage docs to P1S examples
- Consolidate duplicated filament conversion logic in ``gcode.py`` and remove duplicate ``_load_bundled_manifest()`` from ``cura.py``
- Decouple progress adapter from hardcoded Hamilton node names using ``@tag`` decorators
- Delete C++ cloud bridge source and remove bridge jobs from all CI/CD workflows
- Delete printer, auth, credentials, cloud, and thumbnails modules — estampo is now fully printer-agnostic. Default CuraEngine printer changed from Bambu Lab P1S to Ultimaker 2.
- Extract shared Docker utilities into ``docker.py`` module, removing duplication from engine modules
- Pin profiles in all examples and add richer slicer overrides
- Release-readiness tests now run full pipeline inside Docker (including pack/repack) and verify ``.gcode.3mf`` output
- Remove unused ``bambulabs-api`` and ``bambu-lab-cloud-api`` dependencies, and remove ``_find_in_bambox()`` from ``cura.py`` per ADR-005
- Replace raw ``print()`` with ANSI escape codes with ``ui.*`` functions throughout CLI and engine modules
- Update bundled CuraEngine 5.12.0 definitions


## 0.3.1 — 2026-04-11

### Features

- Multi-mesh CuraEngine slicing: parts on different filament slots are passed as separate ``-g -eN`` groups, preserving plate arrangement and extruder assignments ([#405](https://github.com/estampo/estampo/pull/405))
- Per-extruder filament profiles for CuraEngine: filament type and temperatures are set independently per AMS slot via ``CuraProfile.per_extruder`` ([#406](https://github.com/estampo/estampo/pull/406))
- Pipeline stages can now run external CLI commands defined in TOML (e.g. ``bambox pack``), enabling tool integration without Python dependencies.

### Bugfixes

- Substitute ``{machine_nozzle_size}``, ``{machine_buildplate_type}``, and ``{material_type}`` in CuraEngine G-code output ([#396](https://github.com/estampo/estampo/pull/396))
- Pass ``command_stages`` to ``resolve_outputs()`` so command stages are excluded from Hamilton outputs and pipeline ordering is respected ([#399](https://github.com/estampo/estampo/pull/399))
- Fix default output directory to resolve relative to the config file's directory instead of the caller's working directory ([#400](https://github.com/estampo/estampo/pull/400))
- Sort glob results by mtime before selecting artifacts to prevent stale files being picked in reused output directories ([#401](https://github.com/estampo/estampo/pull/401))
- Add ``pythonpath = ["src"]`` to pytest config so tests run correctly from a fresh checkout without a prior editable install ([#402](https://github.com/estampo/estampo/pull/402))
- Fix ``test_profiles_pin`` which was using the removed flat ``[slicer]`` config format since #358 ([#404](https://github.com/estampo/estampo/pull/404))
- Search bambox package data for CuraEngine printer definitions so `bambox_p1s_ams` and other bambox-provided definitions are found without manual pinning ([#409](https://github.com/estampo/estampo/pull/409))
- Bundle bambox_p1s_ams CuraEngine definitions in cura-ams-p1s example so it works without installing bambox as a Python package ([#411](https://github.com/estampo/estampo/pull/411))
- Fix CuraEngine Docker write failure on Linux due to UID mismatch ([#415](https://github.com/estampo/estampo/pull/415))
- Fix `--local` flag being silently ignored when using the CuraEngine backend ([#416](https://github.com/estampo/estampo/pull/416))
- Fix docker-compose.yml UID resolution so non-1000 UIDs work correctly ([#418](https://github.com/estampo/estampo/pull/418))
- Fix `profiles pin` erroring when printer is set to a local file path (via `profiles add`) ([#420](https://github.com/estampo/estampo/pull/420))
- CuraEngine now accepts raw definition IDs (e.g. ``bambox_p1s_ams``) and copies extruder definitions to Docker staging.
- Fix ``[slicer.cura].filaments`` being silently ignored — Cura now reads its own filament config instead of falling through to OrcaSlicer defaults
- Use CuraEngine ``TIME_ELAPSED`` for print time instead of bogus ``;TIME:`` header placeholder

### Misc

- Remove ``_fix_sliced_3mf`` and ``package_for_printer`` — Bambu 3MF fixup is now handled by ``bambox repack`` as a command stage. ([#393](https://github.com/estampo/estampo/pull/393))
- Stop publishing TestPyPI dev builds from PR branches to avoid version collisions ([#422](https://github.com/estampo/estampo/pull/422))
- Add ``THIRD-PARTY-NOTICES`` file and Docker image labels for CuraEngine (AGPL-3.0) and Cura definition (LGPL-3.0) license attribution ([#426](https://github.com/estampo/estampo/pull/426))
- Align docs and CLAUDE.md with printer-agnostic north star and CLI-only bambox integration ([#428](https://github.com/estampo/estampo/pull/428))
- Add BambuStudio reference slice to cura-ams-p1s example for e2e comparison
- Add CuraEngine multi-filament e2e example for P1S + AMS with comparison instructions against BambuStudio reference slice
- Update cura-ams-p1s example: cylinder upright, white PLA slot 1, black PLA slot 4
- Update roadmap: mark v0.3.0 complete, detail v0.4.0 extraction plan


## 0.3.0 — 2026-04-06

### Features

- Add CuraEngine slicer backend (``engine = "cura"``) as alternative to OrcaSlicer ([#282](https://github.com/estampo/estampo/pull/282))
- Build CuraEngine from source instead of extracting from AppImage, eliminating placeholder G-code header issue ([#299](https://github.com/estampo/estampo/pull/299))
- Add Bambu Lab P1S machine definition for CuraEngine with proper start/end G-code ([#301](https://github.com/estampo/estampo/pull/301))
- Add OrcaSlicer 2.3.2 Docker image builds alongside 2.3.1
- Add ``--engine cura`` support to profile extraction script and CI workflow for automated CuraEngine printer definition discovery
- Add ``EngineConfig`` base class, ``SlicerConfig.active`` property, top-level ``[filaments]`` table for material aliases, and ``PartConfig.material`` field; remove facade fields from ``SlicerConfig``
- Add ``[slicer.filament_overrides]`` to patch all filament profiles (e.g. ``required_nozzle_HRC``)
- Add ``[slicer.machine_overrides]`` for overriding machine profile settings (e.g. ``nozzle_type = "hardened_steel"`` for carbon-fiber filaments).
- Add ``bed_type`` config option to set plate type for filament compatibility
- CuraEngine machine definitions are now stored as JSON files (bundled ``Bambu Lab P1S 0.4 nozzle.json``); add custom printers via ``estampo profiles add``; ``profiles pin`` and ``profiles add`` no longer misroute Cura profiles; override values from config are now coerced to the correct type.
- CuraEngine printer definitions: discoverable selection during ``estampo init``, configurable via ``[slicer.cura] printer``, and dynamic definition resolution at slice time
- Engine-namespaced TOML config: ``[slicer.orca]`` and ``[slicer.cura]`` sections for per-engine settings with backward-compatible legacy format support
- Engine-namespaced profile directories: ``profiles/<engine>/<category>/`` with backward-compatible legacy path fallback
- Extract Bambu Connect 3MF fixup into a ``packaged_output`` pipeline stage so printer-specific packaging is explicit and only runs for Bambu printers
- Show animated status spinners during slow Docker operations (image pull, profile extraction)
- Support CuraEngine in local slicer discovery (``find_slicer``) for all platforms
- ``estampo init`` wizard now prompts for slicer engine (OrcaSlicer or CuraEngine) and adapts version detection and profile discovery accordingly.

### Bugfixes

- Fix CuraEngine Docker image breaking Python by isolating bundled libssl/libcrypto ([#283](https://github.com/estampo/estampo/pull/283))
- Fix CuraEngine Docker image Python access for unprivileged estampo user ([#286](https://github.com/estampo/estampo/pull/286))
- Show CuraEngine error output instead of suppressing stderr ([#288](https://github.com/estampo/estampo/pull/288))
- Show rich UI output (checkmarks, print summary) alongside debug logs in verbose mode ([#300](https://github.com/estampo/estampo/pull/300))
- Fix ``ValueError`` when CuraEngine override values include a ``%`` suffix (e.g. ``sparse_infill_density = "35%"``). ([#310](https://github.com/estampo/estampo/pull/310))
- Fix ``profiles pin`` failing for CuraEngine when printer name includes nozzle suffix or different casing ([#340](https://github.com/estampo/estampo/pull/340))
- Fix CuraEngine slice failing when no separate machine profile JSON exists for the printer ([#345](https://github.com/estampo/estampo/pull/345))
- Fix CuraEngine squashed definitions preserving ``inherits`` for unresolved base definitions like ``fdmprinter`` ([#347](https://github.com/estampo/estampo/pull/347))
- Fix profile extraction push failure when bot-managed branch already exists ([#363](https://github.com/estampo/estampo/pull/363))
- Remove Bambu-specific AMS auto-detect from ``estampo init`` wizard ([#367](https://github.com/estampo/estampo/pull/367))
- Skip printer setup and print stage for CuraEngine in ``estampo init`` ([#380](https://github.com/estampo/estampo/pull/380))
- Broadcast scalar machine overrides to arrays when profile has per-extruder fields
- Error when pinned profiles don't match the target slicer version instead of silently crashing
- Fix CuraEngine binary "not found" by patching ELF interpreter and replace missing ``bambu_3mf`` dependency with inline G-code generation
- Fix CuraEngine reporting zero filament usage — CuraEngine CLI writes placeholder G-code header values that are not updated after slicing; patch with real values from stderr and fall back to E-value analysis.
- Fix CuraEngine slicing by converting 3MF model data to STL before passing to the engine
- Fix CuraEngine slicing: place mesh on bed, resolve G-code template variables, fix header patching
- Fix CuraEngine: disable default brim, center mesh on build plate
- Fix OrcaSlicer 2.3.2 segfault in Docker on Colima by preventing Wayland GL init
- Fix TestPyPI dev version collisions by using git commit count instead of workflow run number.
- Fix filament weight reporting: correct multi-value regex, M83 relative extrusion support, newest-file selection, and layer count in output summary.
- Fix profile extraction push failure when branch already exists from earlier run
- Fix release workflow checkout ref that prevented manual release dispatch
- Fix release workflow job skip cascade on manual dispatch
- Fix release workflow tag-check that used curl flags with ``gh api``
- Narrow bare ``except Exception`` handlers to specific exception types for better debuggability.
- Pass ``--allow-mix-temp`` for multi-filament AMS configurations on OrcaSlicer 2.3.2
- Pass ``--allow-mix-temp`` unconditionally on OrcaSlicer 2.3.2+ to fix grouping errors; gate the flag off for older versions.
- Replace unsafe ``eval()`` in CuraEngine G-code template substitution with AST-based safe evaluators.
- Revert ``xvfb-run`` wrapping that caused OrcaSlicer 2.3.2 to segfault on GL init.
- Set ``infill_line_distance`` directly so CuraEngine respects infill density overrides
- Stage Docker slicer input inside output directory and preserve file extension to fix bind-mount issues

### Misc

- Run e2e slice test from host to match real user flow (Docker-based slicing). ([#275](https://github.com/estampo/estampo/pull/275))
- Fix lint errors in ``scripts/bambu_cloud_login.py`` and ``scripts/test_cloud_print.py`` ([#331](https://github.com/estampo/estampo/pull/331))
- Populate bundled CuraEngine 5.12.0 printer definition manifest with full machine list extracted from Docker image ([#354](https://github.com/estampo/estampo/pull/354))
- Add ADR-006 defining the slicer plugin protocol: each engine is a self-contained module; top-level files are pure dispatch layers; clear contract for adding new slicers
- Add Architecture Decision Records, ROADMAP.md, and module ownership table to CLAUDE.md for long-term architectural coherence
- Add GitHub issue templates, labels, and milestones for structured backlog tracking
- Add ``scripts/compare_engines.py`` utility to compare OrcaSlicer vs CuraEngine G-code output
- Add automatic Claude PR review workflow — checks ADR compliance, exception handling, eval() usage, and missing changelog fragments on every PR
- Add slicer engine research doc: Bambu P1S multi-material support across CuraEngine, PrusaSlicer, and Kiri:Moto.
- Consolidate ``bambu-3mf`` + ``bambu-cloud`` into single ``bambox`` package in docs and ADR-005
- Disable OrcaSlicer 2.3.2 builds (segfaults on slice); re-enable when upstream fixes it
- Extract OrcaSlicer-specific logic from ``slicer.py``, ``profiles.py``, and ``init.py`` into new ``orca.py`` engine module per ADR-006.
- Extract shared magic numbers into ``constants.py`` and migrate example configs to engine-namespaced ``[slicer.orca]``/``[slicer.cura]`` format
- Fix Claude PR review workflow: add missing id-token: write permission for OIDC authentication
- Fix Claude PR review workflow: raise max-turns to 8 and add continue-on-error so turn limit never blocks a merge
- Fix release-readiness jobs skipping on manual dispatch and nightly schedule
- Improve CuraEngine error reporting to include both stdout and stderr
- Mark all ``todo-slicer.md`` items as resolved — slicer-agnostic work is complete.
- Move CuraEngine definition pinning and profile logic from ``profiles.py`` into ``cura.py`` engine module.
- Profile system now handles CuraEngine gracefully — ``profiles list --engine cura`` explains that CuraEngine uses inline settings instead of showing empty results.
- Remove Claude PR review workflow — not working reliably
- Remove legacy flat ``[slicer]`` config format, ``fabprint.toml`` alias, ``FABPRINT_*`` env vars, and ``~/.config/fabprint`` migration.
- Replace hardcoded OrcaSlicer references with engine-agnostic text in CLI help, error messages, and 3MF metadata
- Speed up CI with uv dependency caching, concurrency groups, and conditional bridge builds
- Update docs and README to use engine-namespaced ``[slicer.orca]``/``[slicer.cura]`` config format and document ``[filaments]`` table
- Use ``RELEASE_PAT`` in prepare-release workflow so CI triggers on release PRs automatically


## 0.2.3 — 2026-03-31

### Features

- Add ``prepare-release.yml`` workflow: single-command release preparation with automatic changelog via towncrier
- Add ``workflow_dispatch`` fallback trigger to release workflow
- Adopt towncrier for changelog management — each PR adds a fragment file in ``changes/`` instead of editing CHANGELOG.md
- Restructure release workflow (``release.yml``): auto-tag on release PR merge, TestPyPI dry-run gate, GitHub Release creation

### Bugfixes

- Fix ``publish-fabprint`` workflow to match repo environment configuration
- Remove reusable ``workflow_call`` from release-readiness (fixes startup_failure on tag push)
- Show preview 3MF export in CLI output (was silently written to disk)

### Misc

- Rebuild demo GIF: trim duplicate `estampo status` from setup recording; status now appears as its own phase between setup and init ([#246](https://github.com/estampo/estampo/pull/246))
- Add ``fabprint`` deprecation wrapper package and publish workflow
- Add dark-background logo variant, PNG exports, and favicon
- Add post-release reminder to redeploy estampo.dev
- Fix stale ``pzfreo`` references in action README, update developer guide release process, and add logo to README header
- Fix stale docs: remove completed ``fabprint-plan.md``, outdated ``init-template.cast``, and update ``pzfreo/bnl`` → ``estampo/bnl`` references
- Minor updates to demo flow in cast recordings and animated GIF
- Remove completed internal planning docs (Docker optimization, profile pin fix, init command, migration plan)
- Replace mutable ``cloud-bridge:latest`` Docker tag with versioned ``cloud-bridge:bambu-<version>`` tags
- Update tagline to "The build system for 3D prints"
- Update tagline to "The build system for reproducible 3D prints"


## 0.2.2 — 2026-03-30

- Fix `profiles pin` using stale local system profiles instead of Docker-extracted profiles when `slicer.version` is set
- Fix `profiles pin` inheritance: resolve parent profiles across directories and from Docker-extracted profiles
- Extract full BBL profile tree from Docker (includes root-level base profiles)
- Log warning when a profile's `inherits` parent cannot be found
- Add `output_dir` config setting in `estampo.toml` (default: `estampo_output`)
- Bundle OrcaSlicer profiles in the pip package (fixes `estampo init` for pip/pipx users)
- Add tests to verify bundled profiles exist, are valid, and are loadable
- Fix `estampo status` showing cryptic "non-JSON output" error when Docker is not running; now reports "Docker is not running. Start Docker..." clearly
- Fix release-readiness skipping builds on tag pushes (workflow_call inherits caller's push event)
- Fix profiles job in release workflow: install project before running extract_profiles.py
- Restructure release workflow: build all artifacts before publishing any of them
- Move profile extraction to release-readiness (runs on push to main), keeping profiles up-to-date in source
- Fix release-readiness: add workflow files to change filter, fix job conditions for tag pushes
- Graceful fallback when GitHub Actions cannot create PRs for profile updates

## 0.2.1 — 2026-03-29

- Fix profiles extraction: use correct Docker image tag format (`orca-<version>`)
- Consolidate Docker image tag construction into single `docker_image()` function in `slicer.py`
- Add consistency test to catch Docker image tag drift across the codebase
- Add release-readiness workflow: e2e Docker build, smoke test, profile extraction, and real slice test
- Fix Docker CLI command: `slice` -> `run` in workflows, Dockerfile comment
- Fix profile extraction: use direct path instead of symlink in Docker container
- Slicer now falls back to local OrcaSlicer when Docker image is unavailable (even with pinned version)
- Remove forced `use_relative_e_distances=0` — let OrcaSlicer profile chain decide
- Add nightly schedule to release-readiness workflow
- Gate release workflow on release-readiness passing first

## 0.2.0 — 2026-03-29

**Project renamed from `fabprint` to `estampo`.**

- Rename Python package: `fabprint` → `estampo` (all modules, imports, CLI command)
- Rename config file: `fabprint.toml` → `estampo.toml` (old name still works with deprecation warning)
- Rename config directory: `~/.config/fabprint/` → `~/.config/estampo/` (auto-migrated on first run)
- Rename env vars: `FABPRINT_*` → `ESTAMPO_*`
- Rename Docker images: `fabprint/*` → `estampo/*`
- Rename GitHub Action: `pzfreo/fabprint/action` → `estampo/estampo/action`
- `FabprintError` → `EstampoError` (old name kept as alias)
- New project URL: https://estampo.dev
- New repo: https://github.com/estampo/estampo
- Validate slicer override keys against process profile in `estampo validate` and at the start of `estampo run`
- Warn when override keys are not found in the resolved process profile (likely typos or unsupported keys)

## 0.1.141 — 2026-03-24

- Fix: when slicing via Docker, resolve profiles from the Docker image instead of the local
  OrcaSlicer install — prevents version mismatch between local profiles and Docker slicer
- Fix: orca-base images are now immutable — only rebuilt via manual dispatch or release tags
- Fix: add `libopengl0`, `libglu1-mesa`, `libmspack0` to orca-base runtime deps
- Fix: explicitly set `use_relative_e_distances=0` in flattened process profiles
- Revert OrcaSlicer 2.3.2 support (upstream CLI segfault on `--load-filaments` unfixed)
- Release workflow split into separate jobs for PyPI, Docker images, and profile extraction

## 0.1.140 — 2026-03-22

- `fabprint status --stop` to stop a running print job
- `fabprint status --resume` to resume a paused print
- `fabprint status --clear` to clear FAILED state (sends clean_print_error + uiop dismiss)
- Supports bambu-cloud (via MQTT) and moonraker printers
- Auto-publish: push to main rebuilds Docker images and publishes to TestPyPI
- Split release workflow: tags publish to real PyPI with immutable Docker tags

## 0.1.139 — 2026-03-22

- Make profiles directory configurable via `profiles_dir` in `[slicer]` config (default: `"profiles"`)
- `fabprint profiles pin` now handles existing directories (overwrite/rename) and auto-updates `fabprint.toml`

## 0.1.141 — 2026-03-24

- Validate slicer override keys against process profile in `fabprint validate` and at the start of `fabprint run`
- Warn when override keys are not found in the resolved process profile (likely typos or unsupported keys)

## 0.1.138 — 2026-03-22

- GitHub Action: add job summary with slice metrics (visible on every workflow run, not just PRs)
- Upgrade all GitHub Actions to Node.js 24 versions (checkout v6, setup-python v6, upload-artifact v7, github-script v8)
- Expand GIF recording to 7 phases: setup, status, init, profiles-pin, validate, run, status-w
- Add standalone `record_setup.py` for interactive setup recording
- Add `profiles-pin` and `status` (quick check) as separate recorded phases

## 0.1.137 — 2026-03-22

- Make GIF recording script modular: each phase (init, validate, run, status) records separately, then merges
- Add `--phases` flag to re-record only specific phases
- Setup phase uses pre-recorded cast file (no interactive login needed for rebuild)
- Write `stats.json` to output dir with print time, filament, layers, filament types, and tool changes
- GitHub Action reads `stats.json` instead of parsing logs; PR comment now shows all metrics

## 0.1.136 — 2026-03-22

- Fix Docker image: override cadquery-ocp to 7.9+ for VTK 9.4+ compatibility, enabling STEP file loading

## 0.1.134 — 2026-03-22

- GitHub Action: support PR comments when triggered via `workflow_run` (looks up PR from commit SHA)

## 0.1.133 — 2026-03-22

- Add `upside-down` orientation keyword: flips part 180° around X axis

## 0.1.132 — 2026-03-22

- Add `testpypi` environment to TestPyPI workflow for consistent OIDC trusted publishing across all trigger types
- Fix documentation drift: remove non-existent `fabprint login` command, correct default output dir (`fabprint_output/`), fix default pipeline stages, update cloud credential references to `fabprint setup`

## 0.1.131 — 2026-03-21

- Harden release pipeline: publish only on git tags (`v*`), not on every push to main
- Remove self-mutating version bump — version is set in `pyproject.toml` before tagging
- Drop `GH_PAT` usage; checkout now uses default `GITHUB_TOKEN`
- Profile updates now open a PR instead of pushing directly to main
- Remove mutable `:latest` Docker tags; all images tagged with version only
- Add TestPyPI workflow: publishes `.dev` packages on every PR for pre-release testing
- New release process: bump version in `pyproject.toml`, tag with `git tag v<version>`, push tag

## 0.1.128 — 2026-03-20

- Refresh README: adopt tighter structure from proposed rewrite while keeping OrcaSlicer CLI comparison, rich TOML examples, visuals, and env var docs
- Add "Best fit" and "Status" (maturity tiers) sections
- Lead with tagline and motivation before diving into examples

## 0.1.119 — 2026-03-19

- Speed up `fabprint status` for cloud printers: replace fixed sleeps with event-driven waits in the C++ bridge (~16s → ~3-5s typical)
- Add `watch` mode to cloud bridge: single MQTT login/subscribe for repeated status queries
- `fabprint status -w` now maintains one persistent MQTT session per printer instead of re-logging in every poll

## 0.1.116 — 2026-03-19

- Fix Dockerfile: add stub `src/fabprint/__init__.py` before dep install so hatchling can discover the package

## 0.1.114 — 2026-03-19

- Split OrcaSlicer into a separate base image (`fabprint/orca-base`) for faster code-only rebuilds
- Main `fabprint/fabprint` image now layers on top of pre-built base (~10s vs ~3-5min rebuild)
- CI auto-publishes orca-base when `Dockerfile.orca-base` changes
- Build script: `./scripts/build-docker.sh orca-base 2.3.1`

## 0.1.113 — 2026-03-19

- Faster Docker rebuilds: split dependency and source layers in Orca Dockerfile
- Add BuildKit cache mounts for apt and uv in both Dockerfiles
- Multi-stage cloud-bridge build drops g++ from final image (~100MB smaller)

## 0.1.112 — 2026-03-19

- Skip redundant `docker pull` for cloud-bridge image (pull once per 24h instead of every invocation)
- Add `FABPRINT_DOCKER_PULL` env var override (always/never/auto)

## 0.1.111 — 2026-03-19

- Add tests for PersistentBridge (container lifecycle, status, timeout, token mount)
- Add tests for _run_bridge Docker pull behaviour (pull, fallback, macOS, Linux, mounts)
- Add Docker optimization plan document

## 0.1.106 — 2026-03-19

- Init wizard preview now offers Write / Go back / Quit instead of simple y/n
- "Go back" restarts the wizard so you can change answers

## 0.1.105 — 2026-03-19

- Move slicer overrides prompt after CAD file selection in init wizard

## 0.1.104 — 2026-03-19

- Fix multi-select picker: Space now toggles selection instead of triggering search
- Use `/` for search in multi-select mode, type-to-filter in single-select mode
- Show contextual hints: "(type to filter)" vs "(/ to filter, Space to toggle)"

## 0.1.103 — 2026-03-19

- Show "(type to filter)" search hint in interactive picker
- Validate slicer overrides: auto-append `%` for density, enforce integer/float types
- Fix multi-select file picker prompt (removed stale "comma-separated" hint)

## 0.1.102 — 2026-03-19

- Replace broken Rich Live picker with `simple-term-menu` for reliable interactive selection
- Type-to-search filtering works out of the box (no `/` prefix needed)
- Multi-select support with visual hints
- Note: requires Unix terminal (Linux, macOS, or WSL)
- Fix double verification code during Bambu Cloud login

## 0.1.98 — 2026-03-19

- Fix picker display wrapping on narrow terminals

## 0.1.97 — 2026-03-19

- Default printer name "workshop" in `fabprint setup` (press Enter to accept)
- Init wizard prompts for project name, defaulting to current directory name
- Generated `fabprint.toml` now includes top-level `name` field

## 0.1.96 — 2026-03-19

- Standardize type annotations: `Optional[X]` → `X | None` across cli.py and pipeline.py
- Add `log.debug()` to all silent `except Exception` catches for easier debugging
- Replace `sys.exit(1)` in auth.py with `raise FabprintError` for consistent error handling
- Move `_PRINT_STAGES` dict to module level in cli.py
- Use `TYPE_CHECKING` guard for Rich `Status` import in adapters.py
- Replace bare `print()` with `log.info()` in printer.py
- Add `require_file()` helper to reduce duplicated file-existence checks across cloud.py, slicer.py, gcode.py
- Extract `_resolve_filaments()` helper from `load_config()` for readability
- Split `run_wizard()` into 6 focused step functions
- Add `PrinterCredentials` TypedDict for structured credential returns
- Improve test coverage from 60% to 69%: new tests for auth, adapters, ui, cli, pipeline, credentials, loader
- Split `cloud.py` (1180 lines) into `cloud/` package: `bridge.py`, `http.py`, `ams.py` with backward-compatible re-exports
- Extract thumbnail rendering from `slicer.py` into new `thumbnails.py` module

## 0.1.95 — 2026-03-19

- Fix duplicate printer table shown during cloud setup
- Fix Rich markup rendering in printer status column (green/dim colors now display correctly)
- Live interactive search in `fabprint init` — results filter as you type, auto-selects single match
- Auto-send verification code during cloud login (removes confusing prompt)
- Mask verification code and 2FA code input
- Add slicer override picker to `fabprint init` — choose common settings like infill, supports, seam position with value pickers
- Slicer version picker fetches available Docker image versions from DockerHub instead of free text input
- Enhanced `fabprint validate`: check part file readability, file extensions, duplicate parts, plate size sanity, and pipeline stage ordering

## 0.1.94 — 2026-03-19

- Override cadquery-ocp's vtk==9.3.1 pin to vtk>=9.4, enabling Python 3.13 support
- Remove Python 3.14 from CI matrix (cadquery-ocp lacks cp314 wheels)

## 0.1.92 — 2026-03-19

- Mask printer serial numbers in setup and status output for security (shows last 4 chars only)
- Redesign `setup` and `init` CLI with Rich: styled prompts, tables, section headings, syntax-highlighted TOML preview
- Add interactive search-and-pick for profile selection with highlighted matches
- Add password masking for cloud login input
- Replace manual ANSI escape codes with Rich color swatches
- Drop Python upper bound: now supports Python 3.11+ (including 3.13 and 3.14)

## 0.1.90 — 2026-03-18

- Add `fabprint watch` command — watches input files and re-runs pipeline on changes
- Refactor `run` command to share pipeline logic with `watch`

## 0.1.89 — 2026-03-18

- Add bundled OrcaSlicer profile name lists for Docker-only environments
- Add `fabprint profiles add` command to import custom/third-party profiles from files or URLs
- Add Docker fallback for `fabprint profiles pin` when OrcaSlicer isn't installed locally
- Fix false-positive profile warnings in `fabprint validate` for Docker-only users
- Unify profile discovery with three-tier fallback: system install → pinned → bundled

## 0.1.85 — 2026-03-18

- Add code-CAD workflow tutorial (`docs/code-cad.md`) for OpenSCAD, build123d, CadQuery
- Add common slicer overrides reference table to `docs/config.md`
- Expand `fabprint init` wizard documentation with full feature list
- Add `pipx install fabprint` recommendation in README
- Gitignore `squashfs-root/`, `fabprint_output/`, debug logs
- Remove tracked debug scratch files from docs/

## 0.1.84 — 2026-03-18

- Make `build123d` a default dependency (STEP file support out of the box)
- Require Python 3.11–3.12 (vtk doesn't have 3.13 wheels yet)
- Remove `[step]` optional extra

## 0.1.82 — 2026-03-18

- Default output directory is now `fabprint_output/{name}/` when `name` is set
- Default output directory without `name` is `fabprint_output/`
- Explicit `-o` overrides the default

## 0.1.81 — 2026-03-18

- Avoid resolving the same filament profile multiple times for gap slots
- Warn when `slicer.version` is not set in config (builds may not be reproducible)
- Fix GitHub Action: use `--local` to avoid Docker-in-Docker failure when slicing

## 0.1.80 — 2026-03-18

- Fix GitHub Action: use `--local` to avoid Docker-in-Docker failure when slicing

## 0.1.79 — 2026-03-18

- Include `gcode_stats` in `slice` stage so metrics are always available after slicing
- Fix GitHub Action: metrics now extracted from pipeline output (no extra Docker run)

## 0.1.78 — 2026-03-18

- Merge `watch` command into `status --watch` / `status -w`
- Remove standalone `watch` subcommand
- Warn when Docker not available for cloud printing or slicer fallback
- Fix GitHub Action: use project name in artifact name to avoid collisions
- Fix GitHub Action: per-project PR comment markers for multi-config workflows

## 0.1.77 — 2026-03-18

- Fix GitHub Action: project name extraction matched `[printer] name` in addition to top-level `name`
- Fix GitHub Action: guard metrics parsing against multi-line grep output

## 0.1.74 — 2026-03-18

- Add top-level `name` field to `fabprint.toml` to prefix all output filenames
- Add `docs/printers.md` documenting all printer types and testing status
- Mark bambu-lan as experimental (untested against real hardware)
- Verify Moonraker support against virtual-klipper-printer Docker image
- Fix GitHub Action: metrics parsing, artifact upload, and output wiring
- Fix wizard tests depending on user's real credentials file

## 0.1.53 — 2026-03-17

- Fix LICENSE copyright placeholder
- Add `py.typed` marker for PEP 561 type checking
- Add `__all__` to `__init__.py`
- Add `SECURITY.md`

## 0.1.51 — 2026-03-17

- Add project metadata to `pyproject.toml` (license, authors, keywords, URLs, classifiers)
- Fix Dockerfile missing LICENSE for hatchling build

## 0.1.50 — 2026-03-17

- Fix per-object filament resolution bug (`config.py:262`) — only the last part's
  `[parts.filaments]` overrides were applied in multi-part configs
- Replace `ValueError` with `FabprintError` for consistent user-facing errors
- Narrow bare `except Exception` to specific types in cloud.py
- Extract magic numbers into named constants (cloud.py, gcode.py)

## 0.1.49 — 2026-03-16

- Add "How is this different from OrcaSlicer CLI?" section to README
- Add asciinema recordings for `init` and `run` commands

## 0.1.48 — 2026-03-15

- Flag Moonraker support as experimental (untested against real hardware)

## 0.1.47 — 2026-03-15

- Add multi-printer-type `status`/`watch` commands
- Refactor printer system: unified `fabprint setup`, multi-printer-type support
  (bambu-lan, bambu-cloud, moonraker)
- Move printer secrets from project TOML to `~/.config/fabprint/credentials.toml`
- Skip file permission assertion on Windows

## 0.1.45 — 2026-03-14

- Improve `init` wizard UX: search filter for long profile lists
- Fix README images and links for PyPI rendering

## 0.1.43 — 2026-03-13

- Add `fabprint init`, `validate`, and interactive wizard commands
- Remove BambuStudio slicer engine support (OrcaSlicer only)

## 0.1.41 — 2026-03-12

- Keep build123d as optional extra (vtk lacks Python 3.13 wheels)
- Add developer docs and simplify README

## 0.1.40 — 2026-03-11

- Replace `plate`/`slice`/`print` commands with Hamilton-driven `run` pipeline
- Make config arg optional — auto-discover `./fabprint.toml`
- Split CLI and config reference into separate docs
- Add slicer.overrides support for per-project process tweaks

## 0.1.37 — 2026-03-09

- Add `fabprint login`, `status`, and `watch` subcommands
- Support multi-object 3MF files with per-object filament assignment
- Add sequential printing support
- Add `gcode-info` subcommand for extruder usage analysis

## 0.1.33 — 2026-03-06

- Add cloud printing via C++ bridge (bambu_cloud_bridge)
- Add X.509 RSA-SHA256 command signing for cloud MQTT
- Add pure Python HTTP cloud print mode (partial — signing limitation)

## 0.1.25 — 2026-02-28

- Add Bambu Connect-compatible `.gcode.3mf` export
- Render isometric plate thumbnails with shading
- Docker as default slicer with local fallback

## 0.1.15 — 2026-02-20

- Add `print` subcommand with LAN and cloud printer support
- Add slicer version pinning and Docker integration
- Preserve paint_color from pre-painted 3MF inputs

## 0.1.5 — 2026-02-10

- Add profile discovery, resolution, and pinning
- Add per-part AMS filament assignment
- Add uniform scale factor for parts

## 0.1.0 — 2026-02-05

- Initial release: core plate generation pipeline
- Load STL/3MF, orient, arrange via bin-packing, export plate 3MF
- OrcaSlicer CLI integration (local + Docker)
- Cross-platform support (macOS, Linux, Windows)

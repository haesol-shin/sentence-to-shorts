"""Templates service: generated styles, templates and code BGM.

Design notes:

- State: none between jobs. A generation keeps its working files in a staging
  folder under the job folder; the catalog owns every registered package.
- Persistence: a package is written once to staging and registered through
  `CatalogPort.register_generated`, which moves it to `DATA_DIR/s/`. Packages
  are immutable and the revision is the digest of the file list. A generated
  style stores sprite grids drawn when it was accepted, so a later video
  reuses them without the model or the sandbox. Code BGM stores its WAV and
  program in the same registry, including catalog lookup after a restart.
- Streaming: none. One model answer, one sandbox run per attempt.
- Failure: a sandbox failure goes back to the model with the failure text for
  at most two repairs; the text is never logged. A colour-only style, a face
  modification without a face change, a template that fails the region check
  and an invalid loop fail the job. Staging is removed and every earlier
  package and BGM stay as they were.
- Performance: a style run draws every asset of the base rig once (up to 64
  files). Shape masks are computed with Pillow on the host from validated PNGs
  only. The sandbox adapter caches results by code, runtime, input and seed.
- Extension: builtin parts builders and layer drawers arrive as keyword tables
  from the bootstrap, keyed by the manifest `renderer.module`. A new code
  route needs a prompt folder, an answer model and a check of its output.
"""

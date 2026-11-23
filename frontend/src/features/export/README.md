# Export screen

The workspace owns the current video and stage. Export checks that the edit snapshot belongs to that video. The edit provider owns the submitted generation job and supplies the same job to edit progress and export.

## States

- No video: a short note and a way back to the edit step.
- Not made yet: confirming the scenes opens the output check. It shows the opening promise, ending answer, claims with source excerpts, assumptions, and the fact-checking caveat. Pressing Make the video submits the checked revision and returns to edit for progress.
- Making: one sentence and a way back to edit. The screen draws no progress and no cancel control.
- Interrupted: show the stopped part and allow a retry when the existing job is retryable.
- Made: the result card opens after the job finishes and the latest files have been read. Closing it with the x, Esc or the edit button lands on the edit step's finished video; only the usage view keeps this panel in place. The scene column targets the existing composer without changing stages; saving the settings explicitly applies a preset when starting the next video in this workspace.

## Top bar seat

`ExportNextAction` is the 「mp4 저장」 button. It stays dimmed with a reason until the current video's result is ready.

## Time and usage

Activity spans cover the current video across stages. Visible time is split by job state and hidden tabs do not add working time. An ambiguous batch stays marked unconfirmed and is not resent because the activity endpoint adds spans without deduplication. Build time and regenerated scenes come from job records; values with no evidence read 「미확인」.

## Mock run

Mock mode shares the edit job and current video. The player and the download buttons use synthetic MP4 and SRT data; fixture responses still supply the regular resource shapes.

## Verification

Browser coverage uses synthetic data at 1280px and 1920px. The repository fast check is the local gate; browser suites run in CI.

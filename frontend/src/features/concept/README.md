# Concept screen

The concept screen is a neutral wireframe. Cards, fields and chat edit the same settings snapshot. The API boundary in `api.ts` is a mock implementation, not a network client. Existing shell draft requests remain independent of this mock snapshot.

## State and confirmation

A mock video session outlives route mounts, so step navigation preserves its choices, pending work and confirmation. Starting a new video from the first screen creates a separate session; sending another conversation message does not. A completed job cannot replace edits made after it started. Applying a proposed change does not confirm the concept.

Confirmation saves the selected settings first, including pinned layout and style references, and then freezes story structure, art style and character for this video. Cards, chat and late job results cannot replace those confirmed values. Per-value locked/varied flags govern reuse in the next video and are independent of this confirmation.

The change review lists values before and after, affected locks, user values being replaced and rebuild effects. Notes and unsupported requests remain visible even when the response contains no change. Immediate changes offer one undo.

## Input

The first screen and the conversation rail share `ComposerBox`. Text files retain their contents, media retain their `File` objects, and links retain their URLs until the complete attachment payload reaches the mock API. Failed sends keep the input available. Images are unavailable; hosted deployments cannot accept reference links.

## Integration

Production video IDs, revisions, uploads, downloads and server job polling belong to the application integration layer. Do not connect a second transport from the screen. Supply the production implementation through the existing concept API boundary when that integration is available. Scene-specific editing and script generation belong to their own screens; use the shell stage menu to visit them after confirming the concept.

## Verification

Run `npx vitest run src/features/concept tests/app/composer.test.tsx tests/app/first-screen.test.tsx` and `npx playwright test tests/concept tests/shell/composer.spec.ts` from the frontend directory. Browser coverage uses synthetic data at 390px and 1920px. Real mobile keyboards and iOS Safari require device testing.

# Concept screen

The concept screen is a neutral wireframe. Cards, fields and chat edit the same settings snapshot. The API boundary in `api.ts` defines the contract and a mock implementation; `http-api.ts` is the network client the running app uses against the server, and `VITE_API_MODE=mock` keeps the mock. Existing shell draft requests remain independent of this mock snapshot.

## State and confirmation

A mock video session outlives route mounts, so step navigation preserves its choices, pending work and confirmation. Starting a new video from the first screen creates a separate session; sending another conversation message does not. A completed job cannot replace edits made after it started. Applying a proposed change does not confirm the concept.

Confirmation saves the selected settings first, including pinned layout and style references, and then freezes story structure, art style and character for this video. Cards, chat and late job results cannot replace those confirmed values. Per-value locked/varied flags govern reuse in the next video and are independent of this confirmation.

The change review lists values before and after, affected locks, user values being replaced and rebuild effects. Notes and unsupported requests remain visible even when the response contains no change. Immediate changes offer one undo.

## Fine-tune panel

The reference entry is one band above the three groups. Each story card carries a 「세부 조정」 row; the selected card opens a floating white panel with the card's layout, register and humor. The panel spans the card row's width and keeps one value per card, so changing the card loads that card's values and never copies them into another card. Locks for those values stay in 「세부 설정」.

## Input

The first screen and the conversation rail share `ComposerBox`. Text files retain their contents, media retain their `File` objects, and links retain their URLs until the complete attachment payload reaches the mock API. Failed sends keep the input available. Images are unavailable; hosted deployments cannot accept reference links.

## Integration

The workspace creates the project and video, opens that video here with `beginConcept({ videoId, ... })`, and reads it again once the draft job has written the concept. `HttpConceptApi` sends changed settings as direct change plans against the newest revision, adds a text material to the ones the video already holds, and turns files, links and messages into server jobs whose results carry the revision and materials back. A confirmed concept stays locked by the server stage.

## Verification

Run `npx vitest run src/features/concept tests/app/composer.test.tsx tests/app/first-screen.test.tsx` and `npx playwright test tests/concept tests/shell/composer.spec.ts` from the frontend directory. Browser coverage uses synthetic data at 1280px and 1920px. Mobile is outside the MVP, and real mobile keyboards and iOS Safari require device testing.

# Script screen

The script step edits the video's lines directly. One text box writes `display_text` and `speech_text` with the same value, so the caption and the voice cannot drift apart. The document head owns the target length, the scene count and the tone. Changing the length applies the concept screen's recommended scene count; changing the count field changes the scenes themselves. Scene order changes by the grip or by the up and down controls, and the card menu repeats the settled scene actions.

Choosing a tone shows the old and the new line in every changed scene without applying anything. Applying changes those lines, marks the scene 「바뀜」 and recounts the expected length. When no line can be re-said, the tone choice leaves the register alone and shows 「바꿀 문장이 없어요」 in the existing notice. An applied rewrite can be undone once; while a rewrite review is open the undo waits.

## User script

The route passes the video's original script to the screen. The mock loader puts those lines unchanged in the first scene, keeps `raw_text` and marks `source: 'user'`, and uses the synthetic draft only for the other scenes or when no script is present. The user's sentence is never wrapped or reworded.

## Confirmation gate

The screen never asks for scene previews. The mock boundary answers `script_not_confirmed` until the script is confirmed, so the edit step cannot request a preview before the script gate (SPEC 2, CONTRACTS 4.1). The step button confirms the script, and the app opens Edit from it through the optional `onNext`. After confirmation the lines stay editable, so returning from the edit step shows one document. The shell's top bar carries no script step action; the document footer is the one seat.

The screen opens a session for the video id it receives. The workspace gives every creation attempt its own id and passes the video's language and original script; the interface language never enters the key, so switching labels does not reopen or reset the lines. Returning to the same video keeps the session.

## Scene count

The choices come from the concept screen's own rule. The app route reads `recommendedSceneCount` once and configures the script choices, so this feature keeps no second copy of the `30/60/120` to `5/8/11` mapping. Scene ids this session has issued are never issued again after a count drop, and a dropped scene loses its changed mark and its target.

## Fade and scroll

The document uses the merged ScrollPane, which owns the jump control and does not expose the scroll position for a position-based edge fade. The screen therefore has no fixed fade; that component gap stays a limitation rather than a second overflow calculation here.

## Conversation contract

The conversation pane is not part of this feature. It reads `useScript()` and calls these exports:

- `applyTone()` and `dismissTone()` for the tone decision (「모두 바꾸기」, 「모두 그대로 두기」).
- `applyRewrite()`, `dismissRewrite()` and `retryRewrite()` for the scene review (「바꾸기」, 「그대로 두기」, 「다시」).
- `focusScene(id)` for a changed-scene jump; the screen scrolls to that scene and frames it in blue.
- `clearTarget()` for the 「장면 N ×」 chip. `targetSceneId` names the scene and `sceneNumber(document, id)` gives its number.
- `rewriteScene(id)` and `stopRewrite()` when a chat instruction targets a scene.
- `undo()` for the one step back the screen offers.

## Mock boundary

`api.ts` is a mock boundary, not a network client. It records the requests a transport would send and answers with synthetic data. The rewrite prefixes a scene's first line with a synthetic lead-in so a review can be shown; the tone shifter changes known Korean endings and leaves a line it cannot re-say as written. The real script job owns wording. Confirmation and previews stay in this mock's memory; the connected edit screen is still the existing placeholder and does not read the confirmed script.

The display and speech limits count code points, the same unit as the contract, and the screen error and the confirm boundary share that count.

## Verification

Run `npx vitest run tests/script` and `npx playwright test tests/script` from the frontend directory. The browser tests open the step at 1280 and 1920, check the reorder controls, the rewrite review, the tone preview, the new video and the scroll pane, and write the step captures for the pull request.

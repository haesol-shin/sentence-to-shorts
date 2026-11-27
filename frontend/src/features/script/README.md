# Script screen

The script step edits the video's lines directly. One text box writes `display_text` and `speech_text` with the same value, so the caption and the voice cannot drift apart. The document head owns the target length, the scene count and the tone. Changing the length applies the concept screen's recommended scene count; changing the count field changes the scenes themselves. Scene order changes by the grip or by the up and down controls, and the card menu repeats the settled scene actions. Inside a scene, each line has its own grip for reordering and a delete control; a scene keeps at least one line. Dragging either grip shows the whole card or line under the pointer. A focused line shows one grey border around the whole box, seconds included.

Choosing a tone shows the old and the new line in every changed scene without applying anything. Applying changes those lines, marks the scene 「바뀜」 and recounts the expected length. When no line can be re-said, the tone choice leaves the register alone and shows 「바꿀 문장이 없어요」 in the existing notice. An applied rewrite can be undone once; while a rewrite review is open the undo waits.

## User script

The route passes the video's original script to the screen. The mock loader puts those lines unchanged in the first scene, keeps `raw_text` and marks `source: 'user'`, and uses the synthetic draft only for the other scenes or when no script is present. The user's sentence is never wrapped or reworded.

## Confirmation gate

The screen never asks for scene previews. The step button saves and confirms the script, and the app opens Edit from it through the optional `onNext`. After confirmation the lines stay editable, so returning from the edit step shows one document. The shell's top bar carries no script step action; the document footer is the one seat.

The screen opens a session for the per-attempt key it receives. The workspace gives every creation attempt its own key and passes the video's language and original script; the interface language never enters the key, so switching labels does not reopen or reset the lines. Returning to the same attempt keeps the session. The server video id travels separately as `serverVideoId`, so the session key never reaches the video API paths.

## Scene count

The choices come from the concept screen's own rule. The app route reads `recommendedSceneCount` once and configures the script choices, so this feature keeps no second copy of the `30/60/120` to `5/8/11` mapping. Scene ids this session has issued are never issued again after a count drop, and a dropped scene loses its changed mark and its target.

## Fade and scroll

The document uses the merged ScrollPane, which owns the jump control and does not expose the scroll position for a position-based edge fade. The screen therefore has no fixed fade; that component gap stays a limitation rather than a second overflow calculation here.

## Conversation contract

The conversation pane is not part of this feature. It reads `useScript()` and calls these exports:

- `applyTone()` and `dismissTone()` for the tone decision (「✕ 모두 취소」, 「✓ 모두 적용」).
- `applyRewrite()` and `dismissRewrite()` for the scene review (「✕ 취소」, 「✓ 적용」). The scene's own rewrite button repeats the request.
- `addLine(id)` appends one empty line to a scene, up to the four-line cap the edit panel also uses.
- `focusScene(id)` for a changed-scene jump; the screen scrolls to that scene and gives its card the grey element face.
- `clearTarget()` for the 「장면 N ×」 chip. `targetSceneId` names the scene and `sceneNumber(document, id)` gives its number.
- `rewriteScene(id)` and `stopRewrite()` when a chat instruction targets a scene.
- `undo()` for the one step back; the top bar's undo button calls it, and so does Ctrl or Cmd+Z outside a text box. The screen has no undo button of its own. `deleteLine(sceneId, lineId)` and `moveLineTo(sceneId, lineId, index)` each take one undo step.

## Server and mock paths

With a server video id, the screen waits for the draft job to end with an applied plan (`draftState`). A failed, cancelled or unapplied draft shows the load error and nothing is saved. When the draft has applied, `server-script.ts` reads the video and maps it to the document, putting the original script in the first scene as the user wrote it.

Confirming uses only existing endpoints: it re-reads the head, sends the length, tone, scene count and script as one `POST /videos/{id}/changes`, applies that plan if it asks for confirmation (the footer press is the user's confirmation), then calls `POST /videos/{id}/script/confirm` with the new revision. Edit opens only after the server answers `script_confirmed` or later. If anything fails the screen stays on Script with 「대본을 확인하지 못했어요」 and every edit is kept. A retry rereads the head; a save whose reply was lost is recognized and not sent twice, and any other change to the script text, order, length, tone or scene count on the server is reported instead of overwritten. The change request reuses its idempotency key for the same document and revision. Scene visuals, speakers and highlights a scene already has are carried over; a highlight on a line whose text changed is cleared.

With `VITE_API_MODE=mock`, or when no server video id is passed, `api.ts` stays a mock boundary: it records the requests a transport would send and answers with synthetic data. The rewrite prefixes a scene's first line with a synthetic lead-in so a review can be shown; the tone shifter changes known Korean endings and leaves a line it cannot re-say as written. The real script job owns wording. The display and speech limits count code points, the same unit as the contract, and the screen error and the confirm boundary share that count.

## Verification

Run `npx vitest run tests/script` and `npx vitest run tests/edit` (including `tests/edit/script-server.test.ts`, which checks the draft wait, the save, the lost reply, the confirm failure and the entry into Edit) and `npx playwright test tests/script` from the frontend directory. The browser tests open the step at 1280 and 1920, check the reorder controls, the rewrite review, the tone preview, the new video and the scroll pane, and write the step captures for the pull request.

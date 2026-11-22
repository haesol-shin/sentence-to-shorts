# Runtime

## Voice preparation on the make-video buttons

`usePrepare(language)` reads `GET /runtime` and folds `prepare.groups` into one view for the groups a video waits for: a Korean video needs `voice`, an English one `voice` and `align_en`. The transcriber starts on the server, so no button reads it.

- It reads once, then every second while the tab is visible and every five seconds while it is hidden, and only while a needed group is not ready. A read that never answered counts as ready, so the button never blocks on this reading and never on `capabilities.tts`.
- The percent is bytes done over bytes total of the needed groups. It stops at 99 until every group is ready.
- Every make-video button uses the hook: the edit step's top bar action and the output check's start button. Before the press the label stays as it is. After the press the job waits in the queue and the stop control reads 「준비 중 N%」 in place of 「만들기 멈추기」.
- `retrying` freezes the percent and `PrepareNotice` shows the sentence and the time of the next try. `failed` shows one sentence chosen by `error_code` and a retry that calls `POST /runtime/prepare`.
- When that retry request itself fails, the hook keeps the problem's message key as `retryError` and the notice shows that `errors` sentence in place of the stop reason, still as the one red sentence. It clears on the next retry, and on a read that no longer shows the needed groups as failed. A read that still shows them failed keeps it.

## API key on the first screen

`useRuntimeHead(ready)` reads the display name, `profile` and `llm_auth.state` with one `GET /runtime`. Only the release profile with `missing` or `expired` asks for the user's own key: the first screen shows a masked field and a save button above the composer. Saving calls `PUT /credentials/llm`, reads `/runtime` again, and the block goes away on `ok` or `unknown`. A 400 `validation_failed` shows a field error and a 403 `loopback_only` says the key is entered only on this computer. dev and fixture never show the block.

A draft request refused with `llm_auth_required`, or a draft job that failed with `llm_auth`, shows the block again with the existing error text and keeps the typed sentence in the composer, so a wrong key can be replaced.

## Mock run

Mock mode answers a ready install. Open the app with `?mock_prepare=downloading`, `retrying` or `failed` to see the other states, and with `?mock_llm=missing` to see the release first run without a key.

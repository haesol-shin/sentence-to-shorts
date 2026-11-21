# Runtime

## Voice preparation on the make-video buttons

`usePrepare(language)` reads `GET /runtime` and folds `prepare.groups` into one view for the groups a video waits for: a Korean video needs `voice`, an English one `voice` and `align_en`. The transcriber starts on the server, so no button reads it.

- It reads once, then every second while the tab is visible and every five seconds while it is hidden, and only while a needed group is not ready. A read that never answered counts as ready, so the button never blocks on this reading and never on `capabilities.tts`.
- The percent is bytes done over bytes total of the needed groups. It stops at 99 until every group is ready.
- Every make-video button uses the hook: the edit step's top bar action and the output check's start button. Before the press the label stays as it is. After the press the job waits in the queue and the stop control reads 「준비 중 N%」 in place of 「만들기 멈추기」.
- `retrying` freezes the percent and `PrepareNotice` shows the sentence and the time of the next try. `failed` shows one sentence chosen by `error_code` and a retry that calls `POST /runtime/prepare`.

## Mock run

Mock mode answers a ready install. Open the app with `?mock_prepare=downloading`, `retrying` or `failed` to see the other states.

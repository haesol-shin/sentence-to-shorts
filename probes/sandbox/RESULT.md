# P2 sandbox 거부 시험

생성 코드를 Pyodide on Deno에서 실행할 때 격리가 실제로 거절하는지 양 OS에서 재는 probe다. 이 문서는 고정값과 측정 규칙을 두고, 수치는 이 PR의 Actions 실행 artifact에서 옮겨 적는다. probe 코드는 제품 코드가 아니며 제품 의존성과 lockfile에 넣지 않는다.

## 고정 파일과 SHA-256

`probes/sandbox/runtime.json`이 버전과 파일 해시의 원본이다. `probes/sandbox/fetch_runtime.py`가 공식 release에서 직접 내려받고 이 값과 대조하며, 다르면 실행 전에 멈춘다. 표의 값은 내려받은 파일에서 계산했다.

| 파일 | 버전 | SHA-256 |
| --- | --- | --- |
| `deno-x86_64-unknown-linux-gnu.zip` | Deno 2.9.8 | `e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609` |
| `deno-x86_64-pc-windows-msvc.zip` | Deno 2.9.8 | `cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf` |
| `pyodide-core-314.0.7.tar.bz2` | Pyodide 314.0.7 | `2abdcc2e35208af406e07724cffa85bc582ced97e9028383ecf5462541393f95` |
| `pillow-12.2.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl` | Pillow 12.2.0 | `e29838b7a756e4ee0f27a9cfa9a387ee0dfa2e9dd44be2dd595130b9f9d93ac3` |

Pyodide 고정값은 `core/config/runtime.lock.json`과 같은 버전이어야 한다. 두 값이 다르면 runtime 작업이 멈추고 보고한다. 이 probe는 공식 release 파일을 직접 받으므로 runtime lock 작업과 독립이다.

## 실행 flag

runner는 아래 flag로만 실행한다. 정확한 flag 집합은 이 probe의 양 OS 실행 결과로 굳힌다.

```sh
deno run --quiet --no-prompt --no-config --cached-only \
  --allow-read=<runtime 폴더> \
  --deny-write --deny-net --deny-env --deny-run --deny-ffi --deny-sys --deny-import \
  probes/sandbox/runner.js <runtime 폴더>
```

- `--deny-import`가 필요하다. Deno는 기본으로 여러 registry와 CDN host에서의 원격 import를 허용한다.
- `--frozen`은 2.9.8의 `deno run` flag가 아니다. lockfile 고정은 `--cached-only`와 `--deny-import`가 맡는다.
- CWD는 실행마다 새 빈 폴더이고 Deno cache도 전용 폴더다. 자식 환경변수는 `DENO_DIR`, `DENO_NO_UPDATE_CHECK`, `NO_COLOR`만 준다. Windows에서는 부팅에 필요한 `SystemRoot`, `windir`, `PATHEXT`, `TEMP`, `TMP`를 더한다.
- bootstrap은 runtime 폴더만 읽고 허용한 Pillow wheel만 올린다. 그 뒤 read 권한을 회수하고, 회수 뒤 실제 read가 실패하는지 확인한 다음에 stdin을 읽는다. read 상태가 `denied` 또는 `prompt`가 아니거나 read가 성공하면 harness 오류로 끝난다.

## 측정 규칙

- 거절은 세 가지로만 적는다. 권한 오류는 `permission_denied`, 부모 종료는 `timeout`, `output_limit`, `memory_limit`, 부모 검증 실패는 `invalid_output`이다.
- runner가 보낸 판정 문자열은 믿지 않는다. 부모는 stdout 한 줄의 `protocol`, `run_id`, `status`와 중첩 field 형태를 먼저 검사하고, 어긋나면 결과가 아니라 harness 오류로 적는다.
- 정상 PNG는 signature, IHDR, 한 변 1920 이하, 8MiB 이하, IEND를 확인한 뒤 pixel 상한 안에서 decode하고 RGBA로 다시 encode한다. 이미지 데이터가 없거나 깨진 PNG는 decode 단계에서 거절한다. 부모는 이 검증에만 Pillow를 쓰고 probe workflow에서만 설치한다.
- 정상 WAV는 RIFF와 WAVE, PCM mono 44100Hz 16bit, fmt와 data 외 chunk 없음, data chunk 존재와 비어 있지 않음, block align과 frame 정합성, 16초 이하, 1.5MiB 이하를 본다.
- 프로토콜 line이 없거나 두 줄 이상이면 harness 오류다. 시험 대상의 실패는 결과이고 workflow는 성공으로 끝난다. workflow 실패는 harness 오류만 뜻한다.
- 수치가 없는 칸은 비워 둔다. 추정값이나 다른 OS의 값을 옮겨 적지 않는다.
- 각 실행은 새 Deno 프로세스다. 한 프로세스 안에서 두 코드 단위를 돌리는 `state_leak`만 module, 가상 FS, monkey patch가 다음 단위에 남는지 잰다.

## 결과 표

결과는 이 PR의 Actions 실행 artifact에서 채운다.

| 항목 | linux (ubuntu-24.04) | windows (R1 뒤) |
| --- | --- | --- |
| cold start (ms) | | |
| bootstrap (ms) | | |
| 1080x1920 이하 PNG 왕복 (ms) | | |
| peak RSS (bytes) | | |
| read 회수 확인 | | |
| memory hard cap 적용 | | |
| 정상 프로그램 2개 통과 | | |
| 공격 프로그램 거절 | | |
| gate | | |

`result.json`의 `runs`가 프로그램별 판정과 근거이고, `gate`가 결정 gate다. artifact 이름은 `sandbox-probe-linux`와 `sandbox-probe-windows`다.

## 프로그램

| id | 종류 | 기대 | 기록 |
| --- | --- | --- | --- |
| `style_parts_ok` | 정상 | 통과 | PNG 왕복 시간 |
| `bgm_loop_ok` | 정상 | 통과 | WAV 검증 |
| `js_bridge_sys` | 공격 | 거절 | `js` bridge로 `Deno.systemMemoryInfo()` |
| `file_read` | 공격 | 거절 | 회수한 runtime 파일 read |
| `file_write` | 공격 | 거절 | 작업 폴더 write |
| `network_fetch` | 공격 | 거절 | `fetch` |
| `env_read` | 공격 | 거절 | `Deno.env.get` |
| `subprocess` | 공격 | 거절 | `Deno.Command` |
| `ffi_dlopen` | 공격 | 거절 | `Deno.dlopen` |
| `permission_request` | 공격 | 거절 | `Deno.permissions.request` |
| `remote_import` | 공격 | 거절 | 원격 module import |
| `infinite_loop` | 공격 | 부모 종료 | wall timeout |
| `memory_spike` | 공격 | 부모 종료 또는 거절 | memory cap 또는 wasm 실패 |
| `stdout_flood` | 공격 | 부모 종료 | stdout 상한 |
| `bad_png` | 잘못된 출력 | 검증 실패 | 깨진 PNG |
| `bad_wav_header` | 잘못된 출력 | 검증 실패 | 잘못된 WAVE header |
| `overlong_wav` | 잘못된 출력 | 검증 실패 | 20초 WAV |
| `state_leak` | 측정 | 기록 | module, 가상 FS, monkey patch 잔존 |

## 메모리 상한

- Linux는 `systemd-run --user --scope -p MemoryMax=1GiB`를 자식과 같은 빈 환경에서 먼저 시험한다. 되면 모든 실행에 붙이고, 안 되면 timeout과 출력 상한만 적용하며 `result.json`의 `memory_cap`에 미적용 이유를 적는다.
- Windows는 Job Object의 process memory limit을 쓴다. 적용 여부와 실패 이유를 같은 칸에 적는다. Windows 실행은 설치 작업 뒤로 미룬다.
- RSS 관측은 hard cap의 증거가 아니다. `peak_rss_bytes`는 참고값이며 상한 적용 판정에 쓰지 않는다.

## Gate

- 공격이 모두 거절되면 기록한 flag와 한도로 다음 작업을 진행한다.
- memory hard cap을 한 OS에서 쓸 수 없으면 timeout과 출력 상한으로 진행하고 미확인 사실을 기록한다.
- 파일, network, env, process 중 하나라도 성공하면 gate는 `stop`이다. 결과를 보안 경계 변경으로 보고하고 다음 작업을 멈춘다.
- `state_leak`이 참이면 warmer 재사용을 만들지 않고 실행마다 process를 폐기한다.

## 이 호스트에서 확인한 것과 못 한 것

- 확인: Python 문법, harness 단위 시험, manifest와 프로그램 검사, workflow YAML과 actionlint, 이름과 공개 문서 검사.
- 확인: aarch64 Linux에서 runner 기동, read 회수, 정상 PNG 생성, 파일 read와 write 거절. 이 실행은 harness 확인용이고 결과 표에 적지 않는다.
- 못 함: x64 러너의 양 OS 측정과 Windows Job Object. 이 호스트는 aarch64이고 Windows 실행은 R1 뒤로 미룬다. 측정은 PR을 연 뒤 Actions artifact에서만 채운다.

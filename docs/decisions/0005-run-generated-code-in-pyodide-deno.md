# 0005 생성 코드는 Pyodide on Deno에서 실행한다

## Status

Accepted

## Date

2026-11-14

## Context

사용자가 요청한 새 스타일에는 코드의 표현력이 필요하다. 생성 코드는 신뢰할 수 없다.

## Decision

생성 Python 코드는 Pyodide on Deno에서 실행한다. 신뢰 bootstrap 뒤 권한을 회수한다. Deno는 `--no-prompt`로 실행한다. 외부 감독 process가 시간과 출력의 상한을 적용한다. 메모리 hard cap은 OS 기능을 사용할 수 있을 때 적용한다. Linux에서 cgroup을 사용할 수 없으면 hard cap 미확인을 기록한다. RSS 관찰만으로 hard cap 적용을 주장하지 않는다. 생성 코드는 부품 PNG를 한 번 만든다. 앱의 Pillow가 프레임을 합성한다. 코드 BGM은 같은 실행기에서 WAV만 반환한다. host의 import와 exec로 우회하지 않는다.

## Basis

- Team decision: 권한 회수와 외부 자원 제한을 포함한 Pyodide on Deno 실행 환경을 사용한다.
- [Deno 보안 문서](https://docs.deno.com/runtime/fundamentals/security/)는 기본 권한과 권한 제어를 설명한다.
- [Pyodide 공식 문서](https://pyodide.org/en/stable/)는 WebAssembly Python runtime을 설명한다.

## Considered options

- Pyodide on Deno와 외부 감독: 코드 실행 요구를 유지하는 경로로 선택한다.
- host Python 직접 실행: 보안 경계가 없어 선택하지 않는다.
- 코드 생성 제거: 새 스타일 표현 요구를 충족하지 못해 선택하지 않는다.

## Consequences

- 채택은 sandbox 탈출 방지의 실증이 아니다.
- Windows와 Linux에서 파일 접근과 network와 process 실행 거부를 시험해야 한다.
- PNG와 WAV는 부모의 별도 검증기를 통과해야 한다.
- 거부 시험이 실패하면 해당 기능을 중단해야 한다.

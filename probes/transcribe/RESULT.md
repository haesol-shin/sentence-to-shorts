# 참고 영상 전사 결과

faster-whisper small int8을 CPU에서 돌려 한영 전사 시간, peak RAM, 모델 bytes, 단어 오류를 잰다. 이 문서는 결과 표와 측정 규칙만 둔다.

결과는 이 PR의 Actions 실행 artifact에서 채운다.

## 결과 표

| 실행 | OS | 언어 | 오디오 (초) | 전사 시간 (초) | RTF | peak RAM (MB) | 모델 bytes | 단어 수 | WER | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ubuntu-24.04 | ko | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | - |
| 2 | ubuntu-24.04 | en | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | - |
| 3 | windows-latest | ko | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |
| 4 | windows-latest | en | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |

Windows 행은 설치 작업 전까지 비워 둔다. 같은 실행의 `result.json`은 `probe-transcribe-<OS>` artifact에 있다.

## 표를 채우는 방법

1. pull request의 Actions 실행에서 OS별 artifact를 내려받는다.
2. artifact의 `result.json`에서 `runs[]`의 값을 읽어 위 표에 옮긴다.
3. 표를 채우는 커밋에는 실행 id와 commit을 적는다.

## 측정 규칙

- 전사 시간은 model load 뒤 `transcribe` 호출 전체를 잰다. 첫 segment를 받는 시간이 아니라 generator를 끝까지 소비한 값이다.
- peak RAM은 harness process의 최대 상주 메모리다. Linux는 `ru_maxrss`, Windows는 `GetProcessMemoryInfo`의 `PeakWorkingSetSize`를 쓴다. 값은 실행 횟수에 따라 줄지 않으므로 마지막 행의 수치를 실행 전체 peak로 읽는다.
- 모델 bytes는 내려받은 snapshot의 실제 파일 크기 합이다. 같은 blob을 가리키는 link는 한 번만 센다. int8 양자화는 load 때 일어나므로 이 값은 배포 model 크기다.
- RTF는 전사 시간을 오디오 길이로 나눈 값이다. 1보다 작으면 실시간보다 빠르다.
- WER은 공백 단위 단어의 편집 거리를 기준 단어 수로 나눈 값이다. 문장부호는 지우고 비교한다.
- 입력 음성 선택, 결과 status, 실패 처리 규칙은 [probe 안내](README.md)를 따른다.
- 개발 기기는 aarch64다. x64 수치는 pull request의 Actions 실행에서만 나온다.

## 결정 gate

- 전사가 통과하면 참고 영상 분석이 이 전사를 쓴다.
- 전사가 실패하면 참고 영상 분석은 프레임 분석만으로 진행하고 전사 미지원을 표시한다.
- 판정은 위 표에 실측 수치가 채워진 뒤에 한다. 지금은 판정하지 않는다.

## Windows 실행

- `windows-latest` 행은 설치 작업 전까지 돌리지 않는다.
- 돌릴 때는 [workflow](../../.github/workflows/probe-transcribe.yml)를 수동 실행하고 `windows` 입력을 true로 둔다.
- 결과는 같은 이름의 artifact에서 받는다.

## 이 호스트에서 확인한 것과 못 한 것

- 확인: harness 문법 검사, 단위 시험 15개, stub dry run, workflow YAML 검사, 저장소 검사 스크립트.
- 못 함: x64 CPU의 전사 시간과 peak RAM, 실제 model download와 load, Windows 실행. 모두 Actions 실행이 필요하다.

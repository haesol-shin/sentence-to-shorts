# 참고 영상 전사 결과

faster-whisper small int8을 CPU에서 돌려 한영 전사 시간, peak RAM, 모델 bytes, 단어 오류를 잰다. 이 문서는 결과 표와 측정 규칙만 둔다.

결과는 Actions 실행 `43604143620`(2026-11-14), commit `f26100bbfae1abce7188fbb62ea04b10fbe186fb`의 `probe-transcribe-ubuntu-24.04` artifact에서 옮겼다.

## 결과 표

| 실행 | OS | 언어 | 오디오 (초) | 전사 시간 (초) | RTF | peak RAM (MB) | 모델 bytes | 단어 수 | WER | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ubuntu-24.04 | ko | 32.51 | 8.12 | 0.2498 | 697.8 | 486212372 | 47 | 0.3478 | - |
| 2 | ubuntu-24.04 | en | 30.71 | 7.1 | 0.2312 | 703.0 | 486212372 | 89 | 0.0 | - |
| 3 | windows-latest | ko | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |
| 4 | windows-latest | en | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |

Windows 행은 설치 작업 전까지 비워 둔다. 같은 실행의 `result.json`은 `probe-transcribe-<OS>` artifact에 있다.

- peak RAM은 harness의 `_mb`로 bytes를 MiB로 환산한 값이다. 값은 process peak라서 2행의 703.0 MB가 두 실행 전체의 peak다.
- WER은 ko reference words 46, edits 16, 0.3478이고 en reference words 89, edits 0, 0.0이다.
- 한국어 오류는 고유명사에서 주로 났다. 예: 진앙→진항, 성빈센트→성벤센트, 패터슨→퍼터슨, 리→니, 바울→4월, 정부→정보. 조사와 띄어쓰기 경계가 어긋난 경우도 있었다: 단정하기→단정하게, 경찰봉 세례→경찰 봉세례, 보호 제도→보호자들. 모델 선택은 이 표로 판단하지 않는다.

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

- Linux x64에서 두 언어 전사가 실패 없이 끝났으므로(`status` `ok`) 참고 영상 분석은 이 전사를 쓴다.
- 한국어 WER 0.3478은 고유명사 오류가 주된 원인이다. 모델 선택은 이 표로 판단하지 않는다.
- Windows 판정은 설치 작업 뒤 표를 채운 뒤에 한다.

## Windows 실행

- `windows-latest` 행은 설치 작업 전까지 돌리지 않는다.
- 돌릴 때는 [workflow](../../.github/workflows/probe-transcribe.yml)를 수동 실행하고 `windows` 입력을 true로 둔다.
- 결과는 같은 이름의 artifact에서 받는다.

## 이 호스트에서 확인한 것과 못 한 것

- 확인: harness 문법 검사, 단위 시험 15개, stub dry run, workflow YAML 검사, 저장소 검사 스크립트.
- 못 함: 이 호스트에서 x64 CPU의 전사 시간과 peak RAM, 실제 model download와 load, Windows 실행. x64 Linux 수치는 위 표에 있고, Windows는 R1 뒤다.

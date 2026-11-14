# 시험 음성

`ko.wav`와 `en.wav`는 공개 음성 자료에서 20~40초를 골라 이어 붙인 시험 음성이다. 같은 이름의 `.txt`가 기준 글이다. 두 자료는 CC BY 4.0이고 이 문서가 출처 표시를 겸한다.

| 파일 | 출처 | 저작자 | 라이선스 | 변경 |
| --- | --- | --- | --- | --- |
| `ko.wav` | Zeroth-Korean, 화자 149 | Zeroth Project | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 발화 5개를 0.35초 침묵으로 이어 붙이고 16kHz mono PCM WAV로 변환 |
| `en.wav` | LibriSpeech dev-clean, 화자 2277 | Vassil Panayotov 등 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 발화 6개를 0.35초 침묵으로 이어 붙이고 16kHz mono PCM WAV로 변환 |

## 출처

- Zeroth-Korean: https://www.openslr.org/40/
- LibriSpeech: https://www.openslr.org/12/

## 기준 글

`ko.txt`와 `en.txt`는 자료가 제공한 전사를 발화 순서대로 이어 붙인 것이다. 두 자료의 전사에는 문장부호가 없다.

## 쓰는 법

`probes/transcribe/harness.py`가 이 두 파일을 기본 입력으로 쓴다. 다른 음성으로 재려면 `--audio-dir`에 같은 이름의 `.wav`와 `.txt`를 둔다. 계약은 [probe 안내](../README.md)에 있다.

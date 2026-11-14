# P5 한국어 자막 글꼴

자막 후보 글꼴 3개가 Pillow에서 같은 그림을 그리고 실제 glyph 폭으로 줄을 나눌 수 있는지 재는 probe다. 측정은 `probes/font/probe.py`가 하고, 이 문서의 표는 실행 결과 artifact에서만 채운다.

## 측정 규칙

- 캔버스는 1080×1920, 자막 상자는 x 90~990, y 1030~1230, 글자 크기 64px, 줄 높이 80px, 최대 2줄이다.
- 누락 glyph는 fontTools로 읽은 cmap으로 판정한다. cmap에 없는 code point를 글꼴별 시험 문자열별로 적는다.
- 줄바꿈은 Pillow가 글꼴에서 읽은 실제 advance 폭으로 greedy 하게 한다. 공백에서 끊고, 낱말 하나가 상자보다 넓으면 grapheme cluster 경계에서 끊는다.
- 문자 수 규칙은 한국어 14자, 영어 28자를 grapheme cluster 단위로 세어 줄을 나눈 결과다. 혼합 문자열은 한국어 한도를 쓴다.
- 규칙 줄의 폭은 앞뒤 공백을 지우고 연속 공백을 하나로 줄여 잰다. 렌더러가 그리는 줄과 같은 모양으로 재기 위해서다.
- 한국어 14자와 영어 28자 열은 시험 문자열에서 규칙이 나눈 줄의 폭이 상자를 넘었는지다. 가장 넓은 라틴 글자 28개의 폭은 따로 적는다.
- 픽셀 digest는 렌더한 이미지의 RGB bytes SHA-256이다. PNG digest도 기록하지만 zlib 빌드에 따라 달라질 수 있으므로 같은 그림 판정에는 쓰지 않는다.
- 입력 글꼴과 라이선스 파일의 SHA-256은 실행마다 다시 재서 `result.json`에 기록한다.
- 시험 대상의 실패는 `result.json`의 findings에 적고 실행은 성공으로 끝난다. 실패한 실행은 harness 오류나 입력을 받지 못한 경우만 뜻한다.

## 시험 문자열

| id | 문자열 | 규칙 | 의도 |
| --- | --- | --- | --- |
| ko_long | `오늘은 아주 긴 한국어 자막 문장을 한 줄에 넣어 봅니다` | 한국어 14자 | 긴 한글 |
| en_identifier | `load_balancer_max_connections_per_worker` | 영어 28자 | 영문 식별자 |
| digits | `1234567890 3.14 2^32 50%` | 영어 28자 | 숫자와 기호 |
| paren | `결과(2026년 11월) 확인` | 한국어 14자 | 괄호 |
| mixed | `API 응답 250ms (평균) 처리` | 한국어 14자 | 혼합 문자 |
| jamo | `U+1100 U+1161 U+11A8 U+1109 U+1175 U+11AB` | 한국어 14자 | 자모 분리를 NFD로 쓴 각신 |
| emoji | `설명 😀 끝` | 한국어 14자 | 이모지 하나 |
| typewriter | `타자 효과: 각인 e\u0301 🇰🇷` | 한국어 14자 | 타자 효과용 grapheme 분할 |

## 결과

결과는 Actions 실행 `43604143529`(2026-11-14)의 `font-probe-ubuntu-24.04`와 `font-probe-compare` artifact에서 옮겼다. windows-latest 열은 R1 뒤에 채운다.

| 글꼴 | 글꼴 파일 | 원본 라이선스 | 글꼴 SHA-256 | 누락 glyph | 한국어 14자 | 영어 28자 | 가장 넓은 라틴 28자 | 2줄 안에 들어감 | ubuntu-24.04 픽셀 digest | windows-latest 픽셀 digest | 일치 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Galmuri11 | `Galmuri11.ttf` | OFL-1.1 | `2c709890595668f7bdb6df408420fda957dde0288e95b31a1cc17a2ab98b4b4f` | jamo: U+1100, U+1161, U+11A8, U+1109, U+1175, U+11AB; emoji: U+1F600; typewriter: U+0301, U+1F1F0, U+1F1F7 | 넘지 않음 (최대 746.69 px) | 넘음 (최대 1055.98 px) | 1493.19 px | 들어감 | ko_long `d7c5fc411c996759efcb4108062ac0002a534165f06546abef09073f4e37f923`; en_identifier `8f55ea9b2c73faa3c97784ffd596efa7edb7651e85b7475af4b7233998fa9789`; digits `b29ffd1596e1902b2409dd02fbd002c9c92793e730f3a5eac117817270c5d7e9`; paren `f3b466f09241ffd1ff1b6af5a8f6791f771e7a4376d97c8015c08dc41bb90a4e`; mixed `9820a4e0ac2727ca6dcfe4455efe106eaf9be31cba0479a1961f9d3a2f216553`; jamo `f4995f96bd18361ca28da42b1ecaf5d40a16907a61e2b82cabcf24131a7cb657`; emoji `dc858ecfbf5f4600668c7b19fab7c91c0595943c1375b6811745ffaf25368738`; typewriter `8cba3ba3150083407e8347df49d032c6317f8ff11b3d97e7cf4ef8ed8ec0013d` | 미측정 | 대기 (사례 8건) |
| Galmuri14 | `Galmuri14.ttf` | OFL-1.1 | `d3818c0f2898a3b2d79ccd04ec1e4de5e8940aa26abee261f73e315a44ce8df9` | jamo: U+1100, U+1161, U+11A8, U+1109, U+1175, U+11AB; emoji: U+1F600; typewriter: U+0301, U+1F1F0, U+1F1F7 | 넘지 않음 (최대 742.38 px) | 넘음 (최대 1062.52 px) | 1314.25 px | 들어감 | ko_long `60ff3b544b1ba52b664cb6a66a0822e82ebd7f33e103dcabd0f68226acece5c2`; en_identifier `4eeae806e44714d80aec19645fc7891540067ffa8e3da40ec5a8e4a5839ac044`; digits `4e424d2c6b88c15fcc622a998b9821c3568fe46f5c39d35ee53daace5182b10b`; paren `d39e48c5dd9f3fb761ffa3c325cdca9c1788a07c960cc1ba9dceb665847eb318`; mixed `0c46b7e6c72b2a6d22f83eb6e269cde793200d62ddc71ea5855d9d8f6631d099`; jamo `00dc394f6041d5652d09b048ea7b079fef12334ff67ecad9d38a44592522111a`; emoji `10318c06db7f5bf7ff59c0987c1b8f1f2ba39703c46791d91bbff3606675d73e`; typewriter `971fdbc5de0943c511ce55e270aa05e7ddffff6befb8a08640442f47ff171880` | 미측정 | 대기 (사례 8건) |
| Pretendard | `Pretendard-Regular.otf` | OFL-1.1 | `3ffbacde6ab8411f1d2db54bb9b1f0b3ee2a738932033722cf0388c06aed1c93` | jamo: U+1100, U+1161, U+11A8, U+1109, U+1175, U+11AB; emoji: U+1F600; typewriter: U+1F1F0, U+1F1F7 | 넘지 않음 (최대 617.38 px) | 넘지 않음 (최대 895.09 px) | 1639.75 px | 들어감 | ko_long `35bde4d8ffd927b6852158ae66621eaa0e07b955628e2f463732c49af58056ac`; en_identifier `ad05d65fba39f3d10e4f6983509f4232590bba4da07f96cd67bff4c062750b2b`; digits `4fb142c3fb556fea69463eed24b6e8aa9ceb4663bc16ab4c8ae4b06a7ebe0c35`; paren `8e0355793ff768ace7617aa0da494b4bbf179f3ed6724d03a07d51b93428d33f`; mixed `1679d0f5126fa64fa6d61ee8c41ae6b22671ef0e21049823c4a78c0842c967dc`; jamo `d6ff37549eedd45e8e682746fd6231d32d196a62db3720b071060c92ec07f144`; emoji `978e13f17ee7bad3b5480bbf89da5e9c89aa5bffefe0813df33e165d7ec49cf3`; typewriter `66697b1d9ddae62026d868f08f7bc86a0ac170d967ec84a6088413921e787c89` | 미측정 | 대기 (사례 8건) |

- `ubuntu-24.04 픽셀 digest` 칸은 시험 문자열 8개의 digest를 `id digest` 형태로 적었다. `windows-latest`는 미측정이고, 비교 artifact는 run 1개, same 0, different 0, pending 24라서 `일치`는 사례별 대기다.
- 세 글꼴 모두 한국어 14자와 2줄에 들어갔다. 14자 한국어의 최악 폭은 Galmuri11 896.0 px, Galmuri14 896.0 px, Pretendard 774.38 px로 상자 900 px 안이다.
- Galmuri11과 Galmuri14는 영어 28자 시험 문자열에서 상자를 넘었다. Pretendard는 시험 문자열에서 넘지 않았지만, 가장 넓은 라틴 28자는 1639.75 px로 상자를 넘는다.
- 가장 넓은 라틴 글자는 Galmuri11과 Galmuri14가 `M`, Pretendard가 `W`다.
- jamo는 NFD code point가 cmap에 없지만 raqm이 조합형으로 그려 대체 문자열 `각신`과 픽셀이 같았다(`differs_from_case` false).
- `result.json`의 findings는 19개다.

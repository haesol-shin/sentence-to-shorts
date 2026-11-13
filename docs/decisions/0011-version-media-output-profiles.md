# 0011 버전이 있는 미디어 출력 profile을 제안한다

## Status

Proposed

## Date

2026-11-14

## Context

영상과 음향의 숨은 기본값은 출력 품질을 바꿀 수 있다. 미디어 규격 검토가 끝나기 전에 제안값을 확정 규칙으로 쓰면 안 된다.

## Decision

제안 수치를 승인하기 전까지 이 ADR을 Proposed로 유지한다. 문서 리뷰 통과만으로 Accepted로 바꾸지 않는다. 공통 영상은 1080×1920과 30fps로 시작하도록 제안한다. MP4 안에 H.264와 yuv420p를 사용하도록 제안한다. 최종 음향은 AAC-LC 48kHz stereo로 바꾸도록 제안한다. 기존 계약의 AAC 44.1kHz와 이 제안의 차이는 아직 확정하지 않는다. 내부 mix는 48kHz float로 처리하도록 제안한다. 기본 음량은 -16 LUFS로 유지하도록 제안한다. master true peak 상한은 -2 dBTP로 두도록 제안한다. 최종 AAC decode 뒤 상한은 -1 dBTP로 검사하도록 제안한다. 플랫폼별 bitrate는 profile로 분리하도록 제안한다. 색 변환과 encoder와 음향 설정은 버전이 있는 `core/config/media.yaml` 한 곳에 두도록 제안한다.

## Basis

- Team decision: 미디어 규격을 세세히 정하고 계속 개선할 수 있게 관리한다. 수치의 확정은 뜻하지 않는다.
- [YouTube 권장 encoding 설정](https://support.google.com/youtube/answer/1722171?hl=en)은 업로드 권장값의 근거다.
- [Instagram media API](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media)는 API 업로드 제약의 근거다.
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)는 색과 음량 처리 구현의 근거다.

## Considered options

- 버전 profile과 출력별 검증: 변경 효과를 추적할 수 있어 제안한다.
- 플랫폼마다 코드 상수 사용: 변경 근거와 cache 무효화가 흩어져 선택하지 않는다.
- -14 LUFS를 공통 공식 규격으로 단정: 확인한 근거가 없어 선택하지 않는다.

## Consequences

- 제안 수치는 공식 플랫폼 합격선이 아니다.
- 색 tag만 바꾸지 말고 실제 픽셀 변환을 검증해야 한다.
- AAC 압축 뒤 음량과 peak와 A/V sync를 검사해야 한다.
- profile 변경은 관련 cache key에 반영해야 한다.
- 실제 업로드와 청취 검수는 CI로 대체할 수 없다.

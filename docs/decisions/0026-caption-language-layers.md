# 0026 자막 언어 layer 두 개와 언어 catalog

Status: Accepted | Date: 2026-11-19

## Context

자막이 한 벌뿐이라 같은 영상에 다른 언어의 번역 자막을 함께 보여 줄 수 없었다. 자막 위치는 [0025](0025-own-caption-geometry-in-one-module.md)에서 다섯 값이 됐고, 두 layer를 함께 놓을 상자와 겹침 판정이 필요하다. 언어는 `Language` enum 두 값이었고 글꼴 선택은 코드의 고정 표를 따랐다.

## Decision

`Caption`은 주 언어 layer로 두고 `extra`에 언어 layer 하나를 더한다. layer는 언어 catalog id, 표시 mode, 글꼴 `PinnedRef`, 위치를 갖는다. 줄은 `Line.extra_texts`에 언어별 번역문을 하나 갖고, 그 글은 줄의 전체 시간에 그린다. 언어 catalog는 `core/app/catalog/caption_languages/<id>.json`이며 id, label, 글꼴 script를 갖는다. 기본 행은 `ko`와 `en`이고, 글꼴을 고르는 판정은 이 script를 쓴다.

두 layer의 크기는 `core/app/caption_layout.py`가 함께 고른다. 각 layer의 크기 후보에서 합, 큰 쪽, 주 layer 순서로 조합을 올리고 두 상자가 간격 8px로 안전 영역에 들어가는 첫 조합을 쓴다. 조합이 없으면 `caption_overlap`이다. dialog 상자와 sandbox template는 상자를 고정하므로 layer 두 개를 받지 않는다. 이때는 `caption_layer_unsupported`다.

preset은 주 layer만 저장하고 적용한다. 영상의 두 번째 layer와 번역문은 그대로 둔다. 그래야 preset 적용이 번역문 누락을 만들지 않는다. caption mode는 MVP에서 닫힌 enum으로 두고 catalog 행은 후속 작업으로 미룬다.

버린 대안: 위치를 위와 아래 두 값으로 줄인다(두 layer가 각각 두 줄일 때 가운데 자리가 없어도 선택지를 줄이는 것으로는 작은 글자를 피할 수 없다). 자막 layer를 셋까지 둔다(가장 작은 크기에서만 들어간다).

## Consequences

두 layer의 크기와 자리 판정은 한 모듈에서만 바뀐다. layer가 없는 영상의 still key는 그대로라 기존 cache를 다시 쓰고, 두 번째 layer가 있는 영상만 언어, 번역문, layer별 글꼴을 key에 더한다. SRT는 주 언어만 담는다. 새 언어는 catalog 행과 그 script를 지원하는 글꼴이 함께 필요하다.

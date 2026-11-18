# 0025 자막 기하를 한 모듈이 소유한다

Status: Accepted | Date: 2026-11-19

## Context

자막 안전 영역과 자막 상자는 registry, renderer, template 답변 검사, 렌더 시험에 복사돼 있었다. 위치는 `top`, `middle`, `bottom` 셋이고, 위치를 바꾸려면 복사본을 함께 고쳐야 했다. 다섯 위치와 두 번째 언어 layer를 더하면 복사본이 서로 다른 자리를 가리키게 되고 preview와 clip의 자막 상자가 갈라진다.

## Decision

안전 영역(y 1030~1230), 자막 상자(plate), 상자 사이 간격, 다섯 위치(`top`, `upper`, `middle`, `lower`, `bottom`), 상자 배치 판정을 `core/app/caption_layout.py` 한 곳에 둔다. 다른 모듈은 이 모듈의 값과 판정만 읽는다. 생성 template에는 안전 영역을 prompt 데이터(`current_template.safe_area`)로 넘긴다.

builtin 고정 무대와 장면 중심 template는 자막 상자를 layer에 그리지 않고 앱이 글을 따라 움직이는 상자를 그린다. 대화 상자 template의 말풍선과 sandbox layer의 상자는 고정하고 위치 값으로 글만 그 상자 안에서 옮긴다. layout record는 자막 상자와 위치를 남긴다. layer 내용이 바뀌었으므로 renderer `api_version`은 2다.

버린 대안: 모듈마다 상수를 두고 시험으로 맞춘다(위치를 더할 때마다 복사본이 늘어난다). 대화 상자가 아닌 template도 상자를 layer에 고정하고 글만 옮긴다(다섯 위치가 template 상자 안에 갇히고 두 layer를 놓을 자리가 없다).

## Consequences

preview와 clip이 같은 판정을 쓴다. 새 위치나 겹침 규칙은 이 모듈에서만 바뀐다. builtin layer에서 자막 상자 skin이 빠지므로 그 이전에 만든 `layer_png`는 다시 만든다. 자막 상자의 폭은 template 자막 영역의 좌우 inset을 뺀 값이므로 template는 여전히 자막 영역을 정한다.

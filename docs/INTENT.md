# INTENT

이 문서는 누구를 위해 왜 만드는지, 목표·제약·제외 범위·열린 질문의 원본이다. 사용자 동작과 완료 기준은 [SPEC](SPEC.md), 구현 규칙은 [CONTRACTS](CONTRACTS.md), 용어는 [GLOSSARY](GLOSSARY.md)를 따른다.

> 짧은 영상을 쉽게 만들고 싶은 사람이, 한 공간에서 원하는 포맷의 영상을 빠르고 적은 비용으로 만들고, 필요한 부분만 고친다.
>
> Anyone who wants to make short videos easily can create them in the format they want, quickly and at low cost, in one place, and change only the parts they need.

## 사용자 (user)

- 짧은 영상을 쉽게 만들고 싶은 사람이다. 주제는 학습에 한정하지 않는다.
- 한 주제로 여러 편의 영상(시리즈)을 만드는 사람도 포함한다.

## 목표 (goals)

- 원하는 포맷의 영상을 빠르게 만든다. 시간과 비용을 줄이면서 품질을 높인다.
- 한 공간에서 처음부터 끝까지 만들고 사용자는 필요한 부분만 고친다.
- 참고 형식과 스타일에서 출발해 자기만의 것으로 고치는 것이 핵심이다. 고정 그림체 몇 개보다 형태 생성과 커스터마이즈가 중요하다.

## 제약과 설계 기준

- 생성 모델 대신 코드 렌더링을 쓰는 구조는 [ADR 0002](decisions/0002-render-media-with-code.md)를 따른다. 새로운 형태와 동작은 [sandbox](decisions/0005-run-generated-code-in-pyodide-deno.md) 경계 안에서 확장한다.
- LLM 연결은 [provider 분리](decisions/0003-separate-llm-providers-and-routing.md), 설치물은 [OS별 packaging](decisions/0012-package-for-windows-and-linux.md), 저장소와 코드 라이선스는 [공개 단일 main](decisions/0013-use-public-mainline-repository.md) 결정을 따른다.
- 외부 의존성을 최소로 둔다. 코드는 복잡해지지 않게 쓴다. 관리와 확장이 쉬운지가 기준이며 상속도 이 기준으로 판단한다. 코드 구조 참고 저장소는 리뷰를 거쳐 정한다.
- 포트폴리오와 사업화를 고려한다. 특정 제출 요건만을 위한 것은 바깥 층에 모아 교체·제거할 수 있게 한다. 모델·에셋·음원은 상업 사용 가능 여부를 기록한다.

## MVP 범위의 원본

흐름·카드·세부 조정·고정과 변화·그림체·소리·장면 편집·대화·참고 분석·설치·기기별 동작은 [SPEC 1~10a](SPEC.md#1-범위와-실행-형태)에만 둔다. 비용이 큰 작업을 늦게 작게 수행하는 확인 순서는 [SPEC 2](SPEC.md#2-흐름)를 따른다. 기본값과 추천의 우선순위도 그곳에서 정한다.

## 하지 않는 것 (non-goals, MVP)

- 생성형 이미지·영상·음악 모델. 코드로 만든 음악은 여기에 들지 않는다.
- 타임라인 편집, 사진으로 캐릭터 만들기.
- 프로젝트 피드, 시리즈 화면, 공유, 로그인. 이후 구현 때 인스타그램 등 SNS를 참고한다.
- 그 밖의 기능별 시점과 발음 수정 제외는 [SPEC 11](SPEC.md#11-mvp에서-하지-않는-것)을 따른다.

## 열린 질문

- MVP 이후 후보: 사진·동영상 재료. 글 파일(.md, .txt)은 붙여넣은 글과 같은 MVP 재료다([SPEC 2](SPEC.md#2-흐름)).
- 제품 선택은 [SPEC 열린 질문](SPEC.md#열린-질문), 구현 제안은 [CONTRACTS 열린 질문](CONTRACTS.md#열린-질문), 나머지 시각 값은 디자인 작업에서 다룬다.

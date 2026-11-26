# 갤러리 문구 보기

갤러리의 「문구」 탭에서 앱 문구를 파일별로 읽고 고친다. 왼쪽에서 문구 파일을 고르고, 가운데에서 키나 값으로 검색하고, 행을 눌러 한국어와 영어 값을 고친다. 오른쪽은 그 문구를 쓰는 화면 사례와 소스 위치를 보여 주며, 고친 문장은 저장 전에 사례 안에서 예시 값으로 그려진다.

## 실행

```sh
cd frontend
npm run copy
```

이 명령은 갤러리를 「문구」 탭에서 연다. 다른 방법으로 연 갤러리에서는 주소에 `?tab=copy`를 붙인다.

## 저장

로컬 편집 모드로 연 갤러리에서만 저장할 수 있다. `npm run dev`와 `npm run copy`가 그 모드로 서버를 열며, 저장 요청은 같은 출처의 루프백 연결에서만 받는다. 저장은 `frontend/src/locales/ko/<file>.json`과 `frontend/src/locales/en/<file>.json`의 같은 키를 함께 고치고, 키 순서와 2칸 들여쓰기를 지킨다. 다음 검사를 모두 통과해야 「저장」이 열린다.

- 한국어와 영어 값이 비어 있지 않다.
- 원래 값의 `{placeholder}`가 두 값에 모두 남아 있다.
- 두 파일의 키 집합이 같다.

## 공유용 정적 갤러리

```sh
cd frontend
npm run gallery:build
```

결과는 `frontend/dist/gallery/src/gallery/index.html`에 있고 저장 주소가 없어 읽기 전용이다. 기본 `npm run build`는 앱만 만든다.

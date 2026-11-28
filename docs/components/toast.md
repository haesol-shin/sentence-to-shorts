# Toast

- 언제 쓴다: 이미 끝난 일을 한 줄로 알리고 사용자 답을 기다릴 필요가 없을 때 쓴다. 파일을 저장했다는 확인이 그 예다. 스스로 사라지고 Esc로 닫지 않는다.
- 언제 쓰지 않는다: 화면에 남아야 하는 상태나 주의는 해당 값 옆의 [인라인 안내](notice.md)로, 저장 실패처럼 조치가 필요한 오류는 사라지지 않는 실패 표면으로 알린다. 사용자의 답 없이는 진행할 수 없으면 [확인 창](dialog.md)을 쓴다. 대화 칸과 입력창, 단계 단추 줄을 덮지 않는다.
- variant: 짧은 확인이 기본이다. 정본은 오른쪽 끝에 되돌리기 같은 선택 조작을 하나까지 허용한다. 단추의 보이는 높이는 32px(`--part-small`), 누를 영역은 44px이고 누르면 알림이 사라진다. 별도 `variant`나 지속 시간 제어는 [Toast](../../frontend/src/components/Toast/Toast.tsx)에 없고, 여닫힘과 조작은 호출부가 맡는다. 긴 문구의 말줄임은 한 줄 표시의 결과이지 별도 변형이 아니다.
- 쓰는 토큰 / layer: 높이 `--size-control` 44px, 반경 `--radius-toast` 22px, 좌우 `--space-20` 20px, 보조 글자 15px. [Toast.css](../../frontend/src/components/Toast/Toast.css)는 흰 `--popover`, `--popover-foreground`, `--shadow-float`(아래 12px, 흐림 32px, 검정 16%)를 쓰고 아래에서 56px(`--space-48` + `--space-8`) 띄운다. 일반 층은 `--z-toast` 60이다. 결과 카드의 저장 알림은 막 90과 창 91 위에 보여야 하므로 [출력 전용 규칙](../../frontend/src/features/export/export.css)이 `--z-dialog + 2`, 즉 92로 올린다. 일반 Toast의 층을 바꾸는 규칙이 아니며 현재 출력 호출부는 카드가 닫혀 있어도 같은 클래스를 쓴다.
  - 확인 필요: 가로 기준점은 미정이다. 겹침 검토는 대화 칸을 지키기 위해 작업 칸 가운데를 제안하지만, 갤러리와 현재 `Toast.css`는 화면 가운데(`left: 50%`)다. 아래로 넘기기 단추와 함께 보일 때 두 요소가 닿지 않도록 하는 간격도 확정된 값이 없다.
  - 확인 필요: 자동으로 사라지는 원칙만 확정됐다. 겹침 검토의 4초 제안과 이전 시안의 2.4초를 정본으로 쓰지 않는다. 현재 [SaveToast](../../frontend/src/features/export/save-toast.tsx)는 3초를 쓴다.
- 쓰는 화면: [결과 화면](../../frontend/src/features/export/next-action.tsx)의 파일 저장에서 단추 없는 Toast를 쓴다. 결과 카드에서 저장해도 같은 알림을 받는다. 되돌리기 단추가 달린 제품 호출부는 없다.
  - 확인 필요: 완료 확인은 Toast로 한다는 겹침 규칙과 달리, [첫 화면](../../frontend/src/app/first-screen.tsx)의 키 저장과 [결과 화면](../../frontend/src/features/export/export-screen.tsx)의 다음 영상 설정 저장은 지금 `Notice`로 알린다.
- 갤러리 사례: [기본](../../frontend/src/gallery/index.html?case=25-1-default), [긴 문구 말줄임](../../frontend/src/gallery/index.html?case=25-2-long), [되돌리기 단추](../../frontend/src/gallery/index.html?case=25-3-action). 마지막 사례는 단추 모양을 보이며 제품의 되돌리기나 자동 닫힘을 구현한 예는 아니다.

# 상태

`tokens.json`에서 만든 문서다. 값을 고치고 `node design/tokens/build.mjs`를 실행해 다시 만든다. 이 파일은 직접 고치지 않는다.

## 상태 행렬

부품마다 받을 수 있는 상태, 함께 켜질 수 있는 상태, 같은 속성을 다툴 때 이기는 순서를 적는다. 상태가 없으면 받지 않는다는 뜻이고 이유는 아래 표에 있다.

| 부품 | 상태 | 함께 켜짐 | 우선순위 | 포커스 |
| --- | --- | --- | --- | --- |
| `button.primary` | `default`, `hover`, `pressed`, `disabled`, `loading`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible`, `loading` + `focus-visible` | `disabled` > `focus-visible` > `loading` > `pressed` > `hover` > `default` | 바깥 2px |
| `button.secondary` | `default`, `hover`, `pressed`, `disabled`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `hover` > `default` | 바깥 2px |
| `button.ghost` | `default`, `hover`, `pressed`, `disabled`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `hover` > `default` | 바깥 2px |
| `button.icon` | `default`, `hover`, `pressed`, `selected`, `disabled`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible`, `selected` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `selected` > `hover` > `default` | 바깥 2px |
| `button.trigger` | `default`, `hover`, `pressed`, `open`, `disabled`, `focus-visible` | `open` + `hover`, `open` + `pressed`, `open` + `focus-visible`, `hover` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `open` > `hover` > `default` | 바깥 2px |
| `button.send` | `default`, `hover`, `pressed`, `disabled`, `loading`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible`, `loading` + `focus-visible` | `disabled` > `focus-visible` > `loading` > `pressed` > `hover` > `default` | 바깥 2px |
| `field.trigger` | `default`, `hover`, `open`, `disabled`, `focus-visible` | `open` + `hover`, `open` + `focus-visible` | `disabled` > `focus-visible` > `open` > `hover` > `default` | 바깥 2px |
| `menu.surface` | `default` | 없음 | `default` | 없음 |
| `menu.item` | `default`, `hover`, `pressed`, `selected`, `disabled`, `unavailable`, `focus-visible` | `selected` + `hover`, `selected` + `focus-visible`, `hover` + `focus-visible` | `disabled` > `unavailable` > `focus-visible` > `pressed` > `selected` > `hover` > `default` | 안쪽 -2px |
| `menu.label` | `default` | 없음 | `default` | 없음 |
| `tooltip.surface` | `default` | 없음 | `default` | 없음 |
| `picker.window` | `default` | 없음 | `default` | 없음 |
| `tag` | `default` | 없음 | `default` | 없음 |
| `notice.surface` | `default` | 없음 | `default` | 없음 |
| `notice.title` | `default` | 없음 | `default` | 없음 |
| `notice.body` | `default` | 없음 | `default` | 없음 |
| `text.emphasis` | `default` | 없음 | `default` | 없음 |
| `toast.surface` | `default` | 없음 | `default` | 없음 |
| `composer.surface` | `default`, `disabled`, `focus-visible` | 없음 | `disabled` > `focus-visible` > `default` | 바깥 2px |
| `composer.textarea` | `default`, `disabled` | 없음 | `disabled` > `default` | 없음 |
| `composer.placeholder` | `default` | 없음 | `default` | 없음 |
| `chip.surface` | `default`, `loading`, `error`, `focus-visible` | `loading` + `focus-visible` | `error` > `loading` > `focus-visible` > `default` | 바깥 2px |
| `chip.remove` | `default`, `hover`, `pressed`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible` | `focus-visible` > `pressed` > `hover` > `default` | 바깥 2px |
| `skeleton.block` | `default` | 없음 | `default` | 없음 |
| `card.surface` | `default`, `pressed`, `selected`, `disabled`, `focus-visible` | `selected` + `focus-visible`, `pressed` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `selected` > `default` | 바깥 6px |
| `steps.upcoming` | `default` | 없음 | `default` | 없음 |
| `steps.past` | `default`, `hover`, `pressed`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible` | `focus-visible` > `pressed` > `hover` > `default` | 바깥 2px |
| `steps.current` | `default` | 없음 | `default` | 없음 |
| `tab.item` | `default`, `hover`, `pressed`, `selected`, `disabled`, `focus-visible` | `selected` + `hover`, `selected` + `focus-visible`, `hover` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `selected` > `hover` > `default` | 안쪽 -2px |
| `choice.radio` | `default`, `hover`, `pressed`, `selected`, `disabled`, `focus-visible` | `selected` + `hover`, `selected` + `focus-visible`, `hover` + `focus-visible`, `pressed` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `selected` > `hover` > `default` | 바깥 2px |
| `choice.switch` | `default`, `hover`, `pressed`, `selected`, `disabled`, `focus-visible` | `selected` + `hover`, `selected` + `focus-visible`, `hover` + `focus-visible`, `pressed` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `selected` > `hover` > `default` | 바깥 2px |
| `reorder.row` | `default`, `hover`, `pressed`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible` | `focus-visible` > `pressed` > `hover` > `default` | 바깥 2px |
| `player.control` | `default`, `hover`, `pressed`, `disabled`, `focus-visible` | `hover` + `focus-visible`, `pressed` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `hover` > `default` | 바깥 2px |
| `player.progress` | `default`, `focus-visible` | 없음 | `focus-visible` > `default` | 안쪽 -2px |
| `sidebar.item` | `default`, `hover`, `pressed`, `selected`, `disabled`, `focus-visible` | `selected` + `hover`, `selected` + `focus-visible`, `hover` + `focus-visible` | `disabled` > `focus-visible` > `pressed` > `selected` > `hover` > `default` | 바깥 2px |
| `dropzone.surface` | `default` | 없음 | `default` | 없음 |
| `dropzone.mask` | `default` | 없음 | `default` | 없음 |
| `dialog.surface` | `default` | 없음 | `default` | 없음 |
| `dialog.backdrop` | `default` | 없음 | `default` | 없음 |
| `panel.surface` | `default` | 없음 | `default` | 없음 |
| `panel.scrim` | `default` | 없음 | `default` | 없음 |

## 해당 없는 상태의 이유

| 부품 | 상태 | 이유 |
| --- | --- | --- |
| `button.primary` | `open` | 면을 열지 않는다 |
| `button.primary` | `selected` | 한 번 실행하는 동작이라 고름 상태가 없다 |
| `button.primary` | `error` | 실패는 안내 문장이 알린다 |
| `button.primary` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `button.secondary` | `open` | 면을 열지 않는다 |
| `button.secondary` | `selected` | 한 번 실행하는 동작이라 고름 상태가 없다 |
| `button.secondary` | `loading` | 오래 걸리는 실행을 이 단추가 맡지 않는다 |
| `button.secondary` | `error` | 실패는 안내 문장이 알린다 |
| `button.secondary` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `button.ghost` | `open` | 면을 열지 않는다 |
| `button.ghost` | `selected` | 고름 표시가 필요한 자리는 button.icon을 쓴다 |
| `button.ghost` | `loading` | 오래 걸리는 실행을 이 단추가 맡지 않는다 |
| `button.ghost` | `error` | 실패는 안내 문장이 알린다 |
| `button.ghost` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `button.icon` | `open` | 면을 열지 않는다 |
| `button.icon` | `loading` | 아이콘 단추 안에 진행 표시를 두지 않는다 |
| `button.icon` | `error` | 실패는 안내 문장이 알린다 |
| `button.icon` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `button.trigger` | `selected` | 판을 여는 단추라 고름 상태가 없다 |
| `button.trigger` | `loading` | 판을 여는 동작은 기다리지 않는다 |
| `button.trigger` | `error` | 실패는 안내 문장이 알린다 |
| `button.trigger` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `button.send` | `open` | 면을 열지 않는다 |
| `button.send` | `selected` | 보내는 한 번의 동작이라 고름 상태가 없다 |
| `button.send` | `error` | 실패는 안내 문장이 알린다 |
| `button.send` | `unavailable` | 보낼 수 없음은 disabled로 표시한다 |
| `field.trigger` | `pressed` | 누르면 바로 열리고 누른 표시를 두지 않는다 |
| `field.trigger` | `selected` | 값 하나를 고르는 칸이라 스스로 고름 상태가 없다 |
| `field.trigger` | `loading` | 값을 불러오는 표시는 메뉴 항목이 맡는다 |
| `field.trigger` | `error` | 값 칸 자체에는 오류 표시를 두지 않는다 |
| `field.trigger` | `unavailable` | 값 칸은 늘 쓸 수 있다 |
| `menu.surface` | `hover` | 면 자체는 올림 상태를 받지 않는다 |
| `menu.surface` | `pressed` | 면 자체는 누름 상태를 받지 않는다 |
| `menu.surface` | `open` | 면은 열린 동안에만 존재한다 |
| `menu.surface` | `selected` | 면 자체는 고름 상태를 받지 않는다 |
| `menu.surface` | `disabled` | 면 자체는 쓸 수 없음 상태를 받지 않는다 |
| `menu.surface` | `focus-visible` | 면 자체는 포커스를 받지 않는다 |
| `menu.surface` | `loading` | 면 자체는 불러오는 상태를 받지 않는다 |
| `menu.surface` | `error` | 면 자체는 오류 상태를 받지 않는다 |
| `menu.surface` | `unavailable` | 면 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `menu.item` | `open` | 하위 면을 열지 않는다 |
| `menu.item` | `loading` | 줄 안에 진행 표시를 두지 않는다 |
| `menu.item` | `error` | 실패는 안내 문장이 알린다 |
| `menu.label` | `hover` | 이름 줄은 항목이 아니라 올림 상태를 받지 않는다 |
| `menu.label` | `pressed` | 이름 줄은 항목이 아니다 |
| `menu.label` | `open` | 이름 줄은 면을 열지 않는다 |
| `menu.label` | `selected` | 이름 줄은 고를 수 없다 |
| `menu.label` | `disabled` | 이름 줄은 쓸 수 없음 상태를 받지 않는다 |
| `menu.label` | `focus-visible` | 이름 줄은 포커스를 받지 않는다 |
| `menu.label` | `loading` | 이름 줄은 불러오는 상태를 받지 않는다 |
| `menu.label` | `error` | 이름 줄은 오류 상태를 받지 않는다 |
| `menu.label` | `unavailable` | 이름 줄은 항목이 아니다 |
| `tooltip.surface` | `hover` | 면 자체는 올림 상태를 받지 않는다 |
| `tooltip.surface` | `pressed` | 면 자체는 누름 상태를 받지 않는다 |
| `tooltip.surface` | `open` | 면은 열린 동안에만 존재한다 |
| `tooltip.surface` | `selected` | 면 자체는 고름 상태를 받지 않는다 |
| `tooltip.surface` | `disabled` | 면 자체는 쓸 수 없음 상태를 받지 않는다 |
| `tooltip.surface` | `focus-visible` | 면 자체는 포커스를 받지 않는다 |
| `tooltip.surface` | `loading` | 면 자체는 불러오는 상태를 받지 않는다 |
| `tooltip.surface` | `error` | 면 자체는 오류 상태를 받지 않는다 |
| `tooltip.surface` | `unavailable` | 면 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `picker.window` | `hover` | 창 자체는 올림 상태를 받지 않는다 |
| `picker.window` | `pressed` | 창 자체는 누름 상태를 받지 않는다 |
| `picker.window` | `open` | 창은 열린 동안에만 존재한다 |
| `picker.window` | `selected` | 창 자체는 고름 상태를 받지 않는다 |
| `picker.window` | `disabled` | 창 자체는 쓸 수 없음 상태를 받지 않는다 |
| `picker.window` | `focus-visible` | 창 자체는 포커스를 받지 않는다 |
| `picker.window` | `loading` | 창 안의 목록이 불러오는 상태를 맡는다 |
| `picker.window` | `error` | 오류는 안내 문장이 알린다 |
| `picker.window` | `unavailable` | 창 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `tag` | `hover` | 꼬리표는 올림 상태를 받지 않는다 |
| `tag` | `pressed` | 꼬리표는 누름 상태를 받지 않는다 |
| `tag` | `open` | 꼬리표는 면을 열지 않는다 |
| `tag` | `selected` | 꼬리표는 고를 수 없다 |
| `tag` | `disabled` | 꼬리표는 쓸 수 없음 상태를 받지 않는다 |
| `tag` | `focus-visible` | 꼬리표는 포커스를 받지 않는다 |
| `tag` | `loading` | 꼬리표는 불러오는 상태를 받지 않는다 |
| `tag` | `error` | 오류 꼬리표가 error variant다 |
| `tag` | `unavailable` | 쓸 수 없음은 꼬리표의 neutral variant로 보인다 |
| `notice.surface` | `hover` | 안내 문장은 올림 상태를 받지 않는다 |
| `notice.surface` | `pressed` | 안내 문장은 누름 상태를 받지 않는다 |
| `notice.surface` | `open` | 안내 문장은 면을 열지 않는다 |
| `notice.surface` | `selected` | 안내 문장은 고를 수 없다 |
| `notice.surface` | `disabled` | 안내 문장은 쓸 수 없음 상태를 받지 않는다 |
| `notice.surface` | `focus-visible` | 안내 문장은 포커스를 받지 않는다 |
| `notice.surface` | `loading` | 불러오는 동안은 자리표시가 맡는다 |
| `notice.surface` | `error` | 오류는 notice.title의 error variant가 맡는다 |
| `notice.surface` | `unavailable` | 쓸 수 없음 안내는 notice.title이 맡는다 |
| `notice.title` | `hover` | 안내 제목은 올림 상태를 받지 않는다 |
| `notice.title` | `pressed` | 안내 제목은 누름 상태를 받지 않는다 |
| `notice.title` | `open` | 안내 제목은 면을 열지 않는다 |
| `notice.title` | `selected` | 안내 제목은 고를 수 없다 |
| `notice.title` | `disabled` | 안내 제목은 쓸 수 없음 상태를 받지 않는다 |
| `notice.title` | `focus-visible` | 안내 제목은 포커스를 받지 않는다 |
| `notice.title` | `loading` | 안내 제목은 불러오는 상태를 받지 않는다 |
| `notice.title` | `error` | 오류는 error variant가 맡는다 |
| `notice.title` | `unavailable` | 쓸 수 없음은 neutral variant가 맡는다 |
| `notice.body` | `hover` | 본문은 올림 상태를 받지 않는다 |
| `notice.body` | `pressed` | 본문은 누름 상태를 받지 않는다 |
| `notice.body` | `open` | 본문은 면을 열지 않는다 |
| `notice.body` | `selected` | 본문은 고를 수 없다 |
| `notice.body` | `disabled` | 본문은 쓸 수 없음 상태를 받지 않는다 |
| `notice.body` | `focus-visible` | 본문은 포커스를 받지 않는다 |
| `notice.body` | `loading` | 본문은 불러오는 상태를 받지 않는다 |
| `notice.body` | `error` | 오류 색은 제목과 아이콘에만 쓴다 |
| `notice.body` | `unavailable` | 쓸 수 없음 안내는 제목이 맡는다 |
| `text.emphasis` | `hover` | 글자 자체는 올림 상태를 받지 않는다 |
| `text.emphasis` | `pressed` | 글자 자체는 누름 상태를 받지 않는다 |
| `text.emphasis` | `open` | 글자 자체는 면을 열지 않는다 |
| `text.emphasis` | `selected` | 글자 자체는 고름 상태를 받지 않는다 |
| `text.emphasis` | `disabled` | 쓸 수 없는 글자는 disabled-foreground를 쓴다 |
| `text.emphasis` | `focus-visible` | 글자 자체는 포커스를 받지 않는다 |
| `text.emphasis` | `loading` | 글자 자체는 불러오는 상태를 받지 않는다 |
| `text.emphasis` | `error` | 오류 글자는 destructive를 쓴다 |
| `text.emphasis` | `unavailable` | 쓸 수 없음 안내는 안내 문장이 맡는다 |
| `toast.surface` | `hover` | 면 자체는 올림 상태를 받지 않는다 |
| `toast.surface` | `pressed` | 면 자체는 누름 상태를 받지 않는다 |
| `toast.surface` | `open` | 면은 알림이 뜬 동안에만 존재한다 |
| `toast.surface` | `selected` | 면 자체는 고름 상태를 받지 않는다 |
| `toast.surface` | `disabled` | 면 자체는 쓸 수 없음 상태를 받지 않는다 |
| `toast.surface` | `focus-visible` | 알림 면은 포커스를 받지 않고 안의 단추가 받는다 |
| `toast.surface` | `loading` | 면 자체는 불러오는 상태를 받지 않는다 |
| `toast.surface` | `error` | 오류는 안내 문장이 알린다 |
| `toast.surface` | `unavailable` | 면 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `composer.surface` | `hover` | 입력창은 올림 상태를 받지 않는다 |
| `composer.surface` | `pressed` | 입력창은 누름 상태를 받지 않는다 |
| `composer.surface` | `open` | 입력창은 면을 열지 않는다 |
| `composer.surface` | `selected` | 입력창은 고름 상태를 받지 않는다 |
| `composer.surface` | `loading` | 불러오는 동안은 보내기 단추가 loading을 쓴다 |
| `composer.surface` | `error` | 입력 오류는 안내 문장이 알린다 |
| `composer.surface` | `unavailable` | 입력창은 늘 쓸 수 있다 |
| `composer.textarea` | `hover` | 입력 글자는 올림 상태를 받지 않는다 |
| `composer.textarea` | `pressed` | 입력 글자는 누름 상태를 받지 않는다 |
| `composer.textarea` | `open` | 입력 글자는 면을 열지 않는다 |
| `composer.textarea` | `selected` | 글자 고르기는 브라우저 기본 동작을 따른다 |
| `composer.textarea` | `focus-visible` | 포커스 선은 입력창 테두리가 그린다 |
| `composer.textarea` | `loading` | 입력 글자는 불러오는 상태를 받지 않는다 |
| `composer.textarea` | `error` | 입력 오류는 안내 문장이 알린다 |
| `composer.textarea` | `unavailable` | 입력창은 늘 쓸 수 있다 |
| `composer.placeholder` | `hover` | 자리 안내 글은 올림 상태를 받지 않는다 |
| `composer.placeholder` | `pressed` | 자리 안내 글은 누름 상태를 받지 않는다 |
| `composer.placeholder` | `open` | 자리 안내 글은 면을 열지 않는다 |
| `composer.placeholder` | `selected` | 자리 안내 글은 고를 수 없다 |
| `composer.placeholder` | `disabled` | 입력창이 disabled면 자리 안내 글도 보이지 않는다 |
| `composer.placeholder` | `focus-visible` | 자리 안내 글은 포커스를 받지 않는다 |
| `composer.placeholder` | `loading` | 자리 안내 글은 불러오는 상태를 받지 않는다 |
| `composer.placeholder` | `error` | 자리 안내 글은 오류 상태를 받지 않는다 |
| `composer.placeholder` | `unavailable` | 자리 안내 글은 쓸 수 없음 안내를 받지 않는다 |
| `chip.surface` | `hover` | 칩 전체에는 올림 표시를 두지 않는다 |
| `chip.surface` | `pressed` | 칩 전체를 누르는 동작이 없다 |
| `chip.surface` | `open` | 칩은 면을 열지 않는다 |
| `chip.surface` | `selected` | 칩은 고름 상태를 받지 않는다 |
| `chip.surface` | `disabled` | 쓸 수 없는 칩은 없다 |
| `chip.surface` | `unavailable` | 쓸 수 없음 안내는 메뉴 항목이 맡는다 |
| `chip.remove` | `open` | 지우기 단추는 면을 열지 않는다 |
| `chip.remove` | `selected` | 지우기 단추는 고름 상태를 받지 않는다 |
| `chip.remove` | `disabled` | 지울 수 없는 칩은 없다 |
| `chip.remove` | `loading` | 지우기 전 확인 창이 확인을 맡는다 |
| `chip.remove` | `error` | 실패는 안내 문장이 알린다 |
| `chip.remove` | `unavailable` | 지우기 단추는 늘 쓸 수 있다 |
| `skeleton.block` | `hover` | 자리표시는 올림 상태를 받지 않는다 |
| `skeleton.block` | `pressed` | 자리표시는 누름 상태를 받지 않는다 |
| `skeleton.block` | `open` | 자리표시는 면을 열지 않는다 |
| `skeleton.block` | `selected` | 자리표시는 고를 수 없다 |
| `skeleton.block` | `disabled` | 자리표시는 쓸 수 없음 상태를 받지 않는다 |
| `skeleton.block` | `focus-visible` | 자리표시는 포커스를 받지 않는다 |
| `skeleton.block` | `loading` | 이 부품 자체가 불러오는 동안의 자리표시다 |
| `skeleton.block` | `error` | 불러오기 실패는 안내 문장이 알린다 |
| `skeleton.block` | `unavailable` | 자리표시는 쓸 수 없음 안내 상태를 받지 않는다 |
| `card.surface` | `hover` | 큰 면이라 올림 색을 두지 않는다 |
| `card.surface` | `open` | 카드는 면을 열지 않는다 |
| `card.surface` | `loading` | 불러오는 동안은 자리표시가 맡는다 |
| `card.surface` | `error` | 실패한 카드는 안내 문장이 알린다 |
| `card.surface` | `unavailable` | 쓸 수 없는 카드는 없다 |
| `steps.upcoming` | `hover` | 남은 단계는 누를 수 없다 |
| `steps.upcoming` | `pressed` | 남은 단계는 누를 수 없다 |
| `steps.upcoming` | `open` | 단계 표시는 면을 열지 않는다 |
| `steps.upcoming` | `selected` | 남은 단계는 고른 상태가 아니다 |
| `steps.upcoming` | `disabled` | 남은 단계는 쓸 수 없음 상태가 아니다 |
| `steps.upcoming` | `focus-visible` | 남은 단계는 포커스를 받지 않는다 |
| `steps.upcoming` | `loading` | 단계 표시는 불러오는 상태를 받지 않는다 |
| `steps.upcoming` | `error` | 단계 표시는 오류 상태를 받지 않는다 |
| `steps.upcoming` | `unavailable` | 남은 단계는 쓸 수 없음 안내 상태가 아니다 |
| `steps.past` | `open` | 단계 표시는 면을 열지 않는다 |
| `steps.past` | `selected` | 지난 단계는 고른 상태가 아니다 |
| `steps.past` | `disabled` | 지난 단계는 늘 누를 수 있다 |
| `steps.past` | `loading` | 단계 표시는 불러오는 상태를 받지 않는다 |
| `steps.past` | `error` | 단계 표시는 오류 상태를 받지 않는다 |
| `steps.past` | `unavailable` | 지난 단계는 쓸 수 없음 안내 상태가 아니다 |
| `steps.current` | `hover` | 지금 단계는 누를 수 없다 |
| `steps.current` | `pressed` | 지금 단계는 누를 수 없다 |
| `steps.current` | `open` | 단계 표시는 면을 열지 않는다 |
| `steps.current` | `selected` | 지금 단계 자체가 고른 상태라 default가 그 모양이다 |
| `steps.current` | `disabled` | 지금 단계는 굵은 글자로 보인다 |
| `steps.current` | `focus-visible` | 지금 단계는 포커스를 받지 않는다 |
| `steps.current` | `loading` | 단계 표시는 불러오는 상태를 받지 않는다 |
| `steps.current` | `error` | 단계 표시는 오류 상태를 받지 않는다 |
| `steps.current` | `unavailable` | 지금 단계는 쓸 수 없음 안내 상태가 아니다 |
| `tab.item` | `open` | 탭은 면을 열지 않는다 |
| `tab.item` | `loading` | 탭 안에 진행 표시를 두지 않는다 |
| `tab.item` | `error` | 실패는 안내 문장이 알린다 |
| `tab.item` | `unavailable` | 쓸 수 없는 탭은 disabled로 표시한다 |
| `choice.radio` | `open` | 고르는 항목은 면을 열지 않는다 |
| `choice.radio` | `loading` | 고르는 항목은 불러오는 상태를 받지 않는다 |
| `choice.radio` | `error` | 실패는 안내 문장이 알린다 |
| `choice.radio` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `choice.switch` | `open` | 켜기와 끄기는 면을 열지 않는다 |
| `choice.switch` | `loading` | 켜기와 끄기는 불러오는 상태를 받지 않는다 |
| `choice.switch` | `error` | 실패는 안내 문장이 알린다 |
| `choice.switch` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `reorder.row` | `open` | 순서 바꾸는 줄은 면을 열지 않는다 |
| `reorder.row` | `selected` | 줄을 고르는 동작이 없다 |
| `reorder.row` | `disabled` | 순서 바꾸기는 늘 쓸 수 있다 |
| `reorder.row` | `loading` | 순서 바꾸는 줄은 불러오는 상태를 받지 않는다 |
| `reorder.row` | `error` | 실패는 안내 문장이 알린다 |
| `reorder.row` | `unavailable` | 순서 바꾸는 줄은 쓸 수 없음 안내 상태를 받지 않는다 |
| `player.control` | `open` | 재생 제어는 면을 열지 않는다 |
| `player.control` | `selected` | 재생과 멈춤은 아이콘 모양으로만 구분한다 |
| `player.control` | `loading` | 재생 제어는 불러오는 상태를 받지 않는다 |
| `player.control` | `error` | 실패는 안내 문장이 알린다 |
| `player.control` | `unavailable` | 재생할 것이 없으면 disabled로 표시한다 |
| `player.progress` | `hover` | 막대는 올림 표시를 두지 않는다 |
| `player.progress` | `pressed` | 막대는 누르는 동안의 색을 따로 두지 않는다 |
| `player.progress` | `open` | 막대는 면을 열지 않는다 |
| `player.progress` | `selected` | 막대는 고름 상태를 받지 않는다 |
| `player.progress` | `disabled` | 재생할 것이 없으면 막대를 보이지 않는다 |
| `player.progress` | `loading` | 막대는 불러오는 상태를 받지 않는다 |
| `player.progress` | `error` | 실패는 안내 문장이 알린다 |
| `player.progress` | `unavailable` | 막대는 쓸 수 없음 안내 상태를 받지 않는다 |
| `sidebar.item` | `open` | 하위 면을 열지 않는다 |
| `sidebar.item` | `loading` | 사이드바 항목은 불러오는 상태를 받지 않는다 |
| `sidebar.item` | `error` | 실패는 안내 문장이 알린다 |
| `sidebar.item` | `unavailable` | 쓸 수 없음은 disabled로 표시한다 |
| `dropzone.surface` | `hover` | 끌어 오는 동안에만 보이는 점선이라 올림 상태를 받지 않는다 |
| `dropzone.surface` | `pressed` | 점선은 누를 수 없다 |
| `dropzone.surface` | `open` | 점선은 면을 열지 않는다 |
| `dropzone.surface` | `selected` | 점선은 고름 상태를 받지 않는다 |
| `dropzone.surface` | `disabled` | 점선은 쓸 수 없음 상태를 받지 않는다 |
| `dropzone.surface` | `focus-visible` | 점선은 포커스를 받지 않는다 |
| `dropzone.surface` | `loading` | 점선은 불러오는 상태를 받지 않는다 |
| `dropzone.surface` | `error` | 받을 수 없는 파일은 안내 문장이 알린다 |
| `dropzone.surface` | `unavailable` | 점선은 쓸 수 없음 안내 상태를 받지 않는다 |
| `dropzone.mask` | `hover` | 막 자체는 올림 상태를 받지 않는다 |
| `dropzone.mask` | `pressed` | 막 자체는 누름 상태를 받지 않는다 |
| `dropzone.mask` | `open` | 막은 끌어 오는 동안에만 존재한다 |
| `dropzone.mask` | `selected` | 막 자체는 고름 상태를 받지 않는다 |
| `dropzone.mask` | `disabled` | 막 자체는 쓸 수 없음 상태를 받지 않는다 |
| `dropzone.mask` | `focus-visible` | 막은 포커스를 받지 않는다 |
| `dropzone.mask` | `loading` | 막 자체는 불러오는 상태를 받지 않는다 |
| `dropzone.mask` | `error` | 받을 수 없는 파일은 안내 문장이 알린다 |
| `dropzone.mask` | `unavailable` | 막 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `dialog.surface` | `hover` | 창 자체는 올림 상태를 받지 않는다 |
| `dialog.surface` | `pressed` | 창 자체는 누름 상태를 받지 않는다 |
| `dialog.surface` | `open` | 창은 열린 동안에만 존재한다 |
| `dialog.surface` | `selected` | 창 자체는 고름 상태를 받지 않는다 |
| `dialog.surface` | `disabled` | 창 자체는 쓸 수 없음 상태를 받지 않는다 |
| `dialog.surface` | `focus-visible` | 창 자체는 포커스를 받지 않는다 |
| `dialog.surface` | `loading` | 확인을 기다리는 동안은 단추가 loading을 쓴다 |
| `dialog.surface` | `error` | 실패는 안내 문장이 알린다 |
| `dialog.surface` | `unavailable` | 창 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `dialog.backdrop` | `hover` | 막 자체는 올림 상태를 받지 않는다 |
| `dialog.backdrop` | `pressed` | 막 자체는 누름 상태를 받지 않는다 |
| `dialog.backdrop` | `open` | 막은 창이 열린 동안에만 존재한다 |
| `dialog.backdrop` | `selected` | 막 자체는 고름 상태를 받지 않는다 |
| `dialog.backdrop` | `disabled` | 막 자체는 쓸 수 없음 상태를 받지 않는다 |
| `dialog.backdrop` | `focus-visible` | 막은 포커스를 받지 않는다 |
| `dialog.backdrop` | `loading` | 막 자체는 불러오는 상태를 받지 않는다 |
| `dialog.backdrop` | `error` | 실패는 안내 문장이 알린다 |
| `dialog.backdrop` | `unavailable` | 막 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `panel.surface` | `hover` | 판 자체는 올림 상태를 받지 않는다 |
| `panel.surface` | `pressed` | 판 자체는 누름 상태를 받지 않는다 |
| `panel.surface` | `open` | 판은 열린 동안에만 존재한다 |
| `panel.surface` | `selected` | 판 자체는 고름 상태를 받지 않는다 |
| `panel.surface` | `disabled` | 판 자체는 쓸 수 없음 상태를 받지 않는다 |
| `panel.surface` | `focus-visible` | 판 자체는 포커스를 받지 않는다 |
| `panel.surface` | `loading` | 판 안의 목록이 불러오는 상태를 맡는다 |
| `panel.surface` | `error` | 실패는 안내 문장이 알린다 |
| `panel.surface` | `unavailable` | 판 자체는 쓸 수 없음 안내 상태를 받지 않는다 |
| `panel.scrim` | `hover` | 막 자체는 올림 상태를 받지 않는다 |
| `panel.scrim` | `pressed` | 막 자체는 누름 상태를 받지 않는다 |
| `panel.scrim` | `open` | 막은 판이 열린 동안에만 존재한다 |
| `panel.scrim` | `selected` | 막 자체는 고름 상태를 받지 않는다 |
| `panel.scrim` | `disabled` | 막 자체는 쓸 수 없음 상태를 받지 않는다 |
| `panel.scrim` | `focus-visible` | 막은 포커스를 받지 않는다 |
| `panel.scrim` | `loading` | 막 자체는 불러오는 상태를 받지 않는다 |
| `panel.scrim` | `error` | 실패는 안내 문장이 알린다 |
| `panel.scrim` | `unavailable` | 막 자체는 쓸 수 없음 안내 상태를 받지 않는다 |

## 상태 색표

글자 칸은 글자 색, 아이콘 칸은 아이콘 색이다. 두 칸이 같으면 아이콘이 글자와 같은 색이다. 바뀐 칸이 없으면 그 부품의 쉬는 모양 그대로다.

| 부품 | 변형 | 상태 | 바탕 | 글자 | 아이콘 | 테두리 | 바뀐 칸 | 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `button.primary` | - | `default` | `--primary` | `--primary-foreground` | - | `--primary` | 없음 |  |
| `button.primary` | - | `hover` | `--primary-hover` | `--primary-foreground` | - | `--primary-hover` | 바탕, 테두리 | 올림에서는 바탕을 조금 밝게 한다 |
| `button.primary` | - | `pressed` | `--primary-pressed` | `--primary-foreground` | - | `--primary-pressed` | 바탕, 테두리 |  |
| `button.primary` | - | `disabled` | `--muted` | `--disabled-foreground` | - | `--muted` | 바탕, 글자, 테두리 |  |
| `button.primary` | - | `loading` | `--primary` | `--primary-foreground` | - | `--primary` | 없음 | 바탕과 글자는 default와 같고 진행 표시만 더한다 |
| `button.primary` | - | `focus-visible` | `--primary` | `--primary-foreground` | - | `--ring` | 테두리 |  |
| `button.secondary` | - | `default` | `--background` | `--foreground` | - | `--background` | 없음 |  |
| `button.secondary` | - | `hover` | `--state-hover-gray` | `--foreground` | - | `--state-hover-gray` | 바탕, 테두리 |  |
| `button.secondary` | - | `pressed` | `--state-pressed-gray` | `--foreground` | - | `--state-pressed-gray` | 바탕, 테두리 |  |
| `button.secondary` | - | `disabled` | `--muted` | `--disabled-foreground` | - | `--muted` | 바탕, 글자, 테두리 |  |
| `button.secondary` | - | `focus-visible` | `--background` | `--foreground` | - | `--ring` | 테두리 |  |
| `button.ghost` | - | `default` | `--background` | `--foreground` | - | `--background` | 없음 | 상단바와 사이드바처럼 앱 바탕 위에 놓인다. 흰 면 위에서는 card를 바탕으로 쓴다 |
| `button.ghost` | - | `hover` | `--state-hover-gray` | `--foreground` | - | `--state-hover-gray` | 바탕, 테두리 |  |
| `button.ghost` | - | `pressed` | `--state-pressed-gray` | `--foreground` | - | `--state-pressed-gray` | 바탕, 테두리 |  |
| `button.ghost` | - | `disabled` | `--background` | `--disabled-foreground` | - | `--background` | 글자 |  |
| `button.ghost` | - | `focus-visible` | `--background` | `--foreground` | - | `--ring` | 테두리 |  |
| `button.icon` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 |  |
| `button.icon` | - | `hover` | `--state-hover-white` | `--foreground` | - | `--state-hover-white` | 바탕, 테두리 |  |
| `button.icon` | - | `pressed` | `--state-pressed-white` | `--foreground` | - | `--state-pressed-white` | 바탕, 테두리 |  |
| `button.icon` | - | `selected` | `--state-selected` | `--foreground` | - | `--foreground` | 바탕, 테두리 |  |
| `button.icon` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--card` | 글자 |  |
| `button.icon` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `button.trigger` | - | `default` | `--background` | `--foreground` | - | `--background` | 없음 |  |
| `button.trigger` | - | `hover` | `--state-hover-gray` | `--foreground` | - | `--state-hover-gray` | 바탕, 테두리 |  |
| `button.trigger` | - | `pressed` | `--state-pressed-gray` | `--foreground` | - | `--state-pressed-gray` | 바탕, 테두리 | 열림 표시가 이미 있으면 누름은 바탕만 진하게 바꾼다 |
| `button.trigger` | - | `open` | `--state-selected` | `--foreground` | - | `--state-selected` | 바탕, 테두리 | 열린 동안 회색 바탕과 굵은 글자를 함께 쓴다 |
| `button.trigger` | - | `disabled` | `--background` | `--disabled-foreground` | - | `--background` | 글자 |  |
| `button.trigger` | - | `focus-visible` | `--background` | `--foreground` | - | `--ring` | 테두리 |  |
| `button.send` | - | `default` | `--primary` | `--primary-foreground` | - | `--primary` | 없음 |  |
| `button.send` | - | `hover` | `--primary-hover` | `--primary-foreground` | - | `--primary-hover` | 바탕, 테두리 | 올림에서는 바탕을 조금 밝게 한다 |
| `button.send` | - | `pressed` | `--primary-pressed` | `--primary-foreground` | - | `--primary-pressed` | 바탕, 테두리 |  |
| `button.send` | - | `disabled` | `--muted` | `--disabled-foreground` | - | `--muted` | 바탕, 글자, 테두리 |  |
| `button.send` | - | `loading` | `--primary` | `--primary-foreground` | - | `--primary` | 없음 | 아이콘 대신 진행 표시를 같은 색으로 둔다 |
| `button.send` | - | `focus-visible` | `--primary` | `--primary-foreground` | - | `--ring` | 테두리 |  |
| `field.trigger` | - | `default` | `--muted` | `--foreground` | - | `--muted` | 없음 | 값 칸은 늘 회색 바탕이다 |
| `field.trigger` | - | `hover` | `--state-hover-gray` | `--foreground` | - | `--state-hover-gray` | 바탕, 테두리 | 한 단계 진한 회색으로 올린다. 열린 메뉴의 선택 행 색과 다른 단계다 |
| `field.trigger` | - | `open` | `--muted` | `--foreground` | - | `--muted` | 없음 | 테두리 없이 화살표만 위로 돈다 |
| `field.trigger` | - | `disabled` | `--muted` | `--disabled-foreground` | - | `--muted` | 글자 |  |
| `field.trigger` | - | `focus-visible` | `--muted` | `--foreground` | - | `--ring` | 테두리 |  |
| `menu.surface` | - | `default` | `--popover` | `--popover-foreground` | - | `--popover` | 없음 |  |
| `menu.item` | - | `default` | `--popover` | `--foreground` | - | `--popover` | 없음 |  |
| `menu.item` | - | `hover` | `--state-hover-white` | `--foreground` | - | `--state-hover-white` | 바탕, 테두리 |  |
| `menu.item` | - | `pressed` | `--state-pressed-white` | `--foreground` | - | `--state-pressed-white` | 바탕, 테두리 |  |
| `menu.item` | - | `selected` | `--state-selected` | `--foreground` | - | `--state-selected` | 바탕, 테두리 | 고른 줄은 회색 바탕과 체크를 함께 쓴다 |
| `menu.item` | - | `disabled` | `--popover` | `--disabled-foreground` | - | `--popover` | 글자 |  |
| `menu.item` | - | `unavailable` | `--popover` | `--disabled-foreground` | - | `--popover` | 글자 | 흐린 글자와 곧 지원 꼬리표를 함께 둔다 |
| `menu.item` | - | `focus-visible` | `--popover` | `--foreground` | - | `--ring` | 테두리 | 포커스 선을 줄 안쪽에 그린다. 누른 동안에는 포커스 선을 그리지 않는다 |
| `menu.label` | - | `default` | `--popover` | `--muted-foreground` | - | `--popover` | 없음 |  |
| `tooltip.surface` | - | `default` | `--popover` | `--foreground` | - | `--popover` | 없음 | 한 줄이면 radius.pill, 두 줄 이상이면 radius.content를 쓴다 |
| `picker.window` | - | `default` | `--popover` | `--popover-foreground` | - | `--popover` | 없음 | 옆에서 미끄러져 오는 창은 shadow.slide를 쓴다 |
| `tag` | `neutral` | `default` | `--muted` | `--foreground` | `--muted-foreground` | `--muted` | 없음 | 꼬리표는 회색 바탕을 쓰고 뜻 색은 아이콘에만 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `tag` | `new` | `default` | `--muted` | `--foreground` | `--emphasis` | `--muted` | 없음 | 꼬리표는 회색 바탕을 쓰고 뜻 색은 아이콘에만 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `tag` | `warning` | `default` | `--muted` | `--foreground` | `--warning` | `--muted` | 없음 | 꼬리표는 회색 바탕을 쓰고 뜻 색은 아이콘에만 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `tag` | `error` | `default` | `--muted` | `--foreground` | `--destructive` | `--muted` | 없음 | 꼬리표는 회색 바탕을 쓰고 뜻 색은 아이콘에만 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `notice.surface` | - | `default` | `--muted` | `--foreground` | - | `--muted` | 없음 | 안내 문장은 회색 바탕을 쓰고 뜻 색은 제목 옆 아이콘에만 쓴다 |
| `notice.title` | `neutral` | `default` | `--muted` | `--foreground` | `--muted-foreground` | `--muted` | 없음 | 제목 글자는 foreground이고 아이콘에만 뜻 색을 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `notice.title` | `warning` | `default` | `--muted` | `--foreground` | `--warning` | `--muted` | 없음 | 제목 글자는 foreground이고 아이콘에만 뜻 색을 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `notice.title` | `error` | `default` | `--muted` | `--foreground` | `--destructive` | `--muted` | 없음 | 제목 글자는 foreground이고 아이콘에만 뜻 색을 쓴다. 뜻 색 글자는 --warning만 회색 바탕에서 기준을 넘는다 |
| `notice.body` | - | `default` | `--muted` | `--foreground` | - | `--muted` | 없음 |  |
| `text.emphasis` | - | `default` | `--card` | `--emphasis` | - | `--card` | 없음 | 강조 단어와 안 본 변경 표시에 쓴다. 밝은 바탕에서만 쓴다 |
| `toast.surface` | - | `default` | `--popover` | `--popover-foreground` | - | `--popover` | 없음 | 알림 면은 높이 44, 반경 22, shadow.float를 쓴다 |
| `composer.surface` | - | `default` | `--card` | `--foreground` | - | `--input` | 없음 |  |
| `composer.surface` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--input` | 글자 |  |
| `composer.surface` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 | 입력칸 안에 포커스가 있을 때 입력창 테두리를 ring으로 바꾼다 |
| `composer.textarea` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 |  |
| `composer.textarea` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--card` | 글자 |  |
| `composer.placeholder` | - | `default` | `--card` | `--sub` | - | `--card` | 없음 |  |
| `chip.surface` | - | `default` | `--card` | `--foreground` | - | `--border` | 없음 |  |
| `chip.surface` | - | `loading` | `--card` | `--muted-foreground` | - | `--border` | 글자 | 받는 중에는 종류와 길이 자리에 진행 표시를 둔다 |
| `chip.surface` | - | `error` | `--card` | `--destructive` | - | `--destructive` | 글자, 테두리 | 실패한 칩은 테두리와 글자를 destructive로 바꾼다 |
| `chip.surface` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `chip.remove` | - | `default` | `--card` | `--muted-foreground` | - | `--card` | 없음 |  |
| `chip.remove` | - | `hover` | `--state-hover-white` | `--foreground` | - | `--state-hover-white` | 바탕, 글자, 테두리 |  |
| `chip.remove` | - | `pressed` | `--state-pressed-white` | `--foreground` | - | `--state-pressed-white` | 바탕, 글자, 테두리 |  |
| `chip.remove` | - | `focus-visible` | `--card` | `--muted-foreground` | - | `--ring` | 테두리 |  |
| `skeleton.block` | - | `default` | `--muted` | `--foreground` | - | `--muted` | 없음 | 글자나 그림이 들어올 자리를 회색 면으로 채운다 |
| `card.surface` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 | 카드는 그림자 없이 흰 면을 쓴다 |
| `card.surface` | - | `pressed` | `--accent-pressed` | `--foreground` | - | `--accent-pressed` | 바탕, 테두리 |  |
| `card.surface` | - | `selected` | `--card` | `--foreground` | - | `--card` | 없음 | 고른 카드는 같은 색을 쓰고 글자 굵기와 그림 진하기로 구분한다 |
| `card.surface` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--card` | 글자 |  |
| `card.surface` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `steps.upcoming` | - | `default` | `--card` | `--muted-foreground` | - | `--card` | 없음 | 남은 단계는 회색 글자다. 단계 표시는 흰 화면 위에 놓는다 |
| `steps.past` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 | 지난 단계는 검정 글자이고 누르면 그 단계로 돌아간다 |
| `steps.past` | - | `hover` | `--accent` | `--foreground` | - | `--accent` | 바탕, 테두리 |  |
| `steps.past` | - | `pressed` | `--accent-pressed` | `--foreground` | - | `--accent-pressed` | 바탕, 테두리 |  |
| `steps.past` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `steps.current` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 | 지금 단계는 굵은 글자와 글자 아래 점으로 보인다. 컨셉 단계는 보기만 한다 |
| `tab.item` | - | `default` | `--card` | `--muted-foreground` | - | `--card` | 없음 |  |
| `tab.item` | - | `hover` | `--state-hover-white` | `--foreground` | - | `--state-hover-white` | 바탕, 글자, 테두리 |  |
| `tab.item` | - | `pressed` | `--state-pressed-white` | `--foreground` | - | `--state-pressed-white` | 바탕, 글자, 테두리 |  |
| `tab.item` | - | `selected` | `--card` | `--foreground` | - | `--foreground` | 글자, 테두리 | 고른 탭은 글자 아래 선을 foreground로 그린다 |
| `tab.item` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--card` | 글자 |  |
| `tab.item` | - | `focus-visible` | `--card` | `--muted-foreground` | - | `--ring` | 테두리 | 포커스 선을 줄 안쪽에 그린다. 누른 동안에는 포커스 선을 그리지 않는다 |
| `choice.radio` | - | `default` | `--card` | `--foreground` | - | `--border` | 없음 |  |
| `choice.radio` | - | `hover` | `--state-hover-white` | `--foreground` | - | `--border` | 바탕 |  |
| `choice.radio` | - | `pressed` | `--state-pressed-white` | `--foreground` | - | `--border` | 바탕 |  |
| `choice.radio` | - | `selected` | `--state-selected` | `--foreground` | - | `--primary` | 바탕, 테두리 | 고른 항목은 테두리를 primary로 바꾸고 안쪽 점을 primary로 채운다 |
| `choice.radio` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--border` | 글자 |  |
| `choice.radio` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `choice.switch` | - | `default` | `--card` | `--foreground` | - | `--border` | 없음 |  |
| `choice.switch` | - | `hover` | `--state-hover-white` | `--foreground` | - | `--state-hover-white` | 바탕, 테두리 |  |
| `choice.switch` | - | `pressed` | `--state-pressed-white` | `--foreground` | - | `--state-pressed-white` | 바탕, 테두리 |  |
| `choice.switch` | - | `selected` | `--state-selected` | `--foreground` | - | `--foreground` | 바탕, 테두리 | 고른 칸은 회색 바탕, 굵은 글자, foreground 테두리를 함께 쓴다 |
| `choice.switch` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--border` | 글자 |  |
| `choice.switch` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `reorder.row` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 |  |
| `reorder.row` | - | `hover` | `--accent` | `--foreground` | - | `--accent` | 바탕, 테두리 |  |
| `reorder.row` | - | `pressed` | `--card` | `--foreground` | - | `--card` | 없음 | 끌고 있는 줄은 바탕을 바꾸지 않고 shadow.float로 띄운다 |
| `reorder.row` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `player.control` | - | `default` | `--card` | `--foreground` | - | `--card` | 없음 | 재생과 멈춤은 원 없이 채운 회색 아이콘이다 |
| `player.control` | - | `hover` | `--accent` | `--foreground` | - | `--accent` | 바탕, 테두리 |  |
| `player.control` | - | `pressed` | `--accent-pressed` | `--foreground` | - | `--accent-pressed` | 바탕, 테두리 |  |
| `player.control` | - | `disabled` | `--card` | `--disabled-foreground` | - | `--card` | 글자 |  |
| `player.control` | - | `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 |  |
| `player.progress` | - | `default` | `--muted` | `--foreground` | - | `--muted` | 없음 | 진행 막대는 회색 바탕에 foreground로 채우고 반경은 radius.media다 |
| `player.progress` | - | `focus-visible` | `--muted` | `--foreground` | - | `--ring` | 테두리 |  |
| `sidebar.item` | - | `default` | `--background` | `--muted-foreground` | - | `--background` | 없음 | 사이드바는 아이콘만 두고 이름은 tooltip으로 보인다. text 칸의 색은 아이콘 색이다 |
| `sidebar.item` | - | `hover` | `--state-hover-gray` | `--foreground` | - | `--state-hover-gray` | 바탕, 글자, 테두리 |  |
| `sidebar.item` | - | `pressed` | `--state-pressed-gray` | `--foreground` | - | `--state-pressed-gray` | 바탕, 글자, 테두리 |  |
| `sidebar.item` | - | `selected` | `--state-selected` | `--foreground` | - | `--state-selected` | 바탕, 글자, 테두리 |  |
| `sidebar.item` | - | `disabled` | `--background` | `--disabled-foreground` | - | `--background` | 글자 |  |
| `sidebar.item` | - | `focus-visible` | `--background` | `--muted-foreground` | - | `--ring` | 테두리 |  |
| `dropzone.surface` | - | `default` | `--card` | `--foreground` | - | `--border` | 없음 | 화면 끝에서 24px 안쪽에 점선 테두리를 그린다. 끌어 오는 동안에만 보인다 |
| `dropzone.mask` | - | `default` | `--overlay-scrim` | `--foreground` | - | `--overlay-scrim` | 없음 | 파일을 끌어 오는 동안 사이드바를 뺀 화면 전체를 흐린다 |
| `dialog.surface` | - | `default` | `--popover` | `--popover-foreground` | - | `--popover` | 없음 | 확인 창은 너비 480, 안쪽 여백 24, 반경 24, shadow.float를 쓰고 안의 단추가 포커스를 받는다 |
| `dialog.backdrop` | - | `default` | `--overlay-dialog-scrim` | - | - | `--overlay-dialog-scrim` | 없음 | 확인 창 뒤는 진한 회색 24% 막을 쓰고 막 위에는 글자를 놓지 않는다 |
| `panel.surface` | - | `default` | `--popover` | `--popover-foreground` | - | `--popover` | 없음 | 판은 shadow.float를 쓰고 값 칸은 판 위에서 열린다 |
| `panel.scrim` | - | `default` | `--overlay-scrim` | `--foreground` | - | `--overlay-scrim` | 없음 | 판 뒤의 장면 칸을 흐린다 |

## 조합 색표

함께 켜지는 상태마다 한 줄을 둔다. 같은 칸을 두 상태가 다투면 우선순위가 높은 상태가 이기고, 이긴 상태를 마지막 칸에 적는다.

| 부품 | 변형 | 조합 | 바탕 | 글자 | 아이콘 | 테두리 | 이긴 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `button.primary` | - | `hover` + `focus-visible` | `--primary-hover` | `--primary-foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `button.primary` | - | `pressed` + `focus-visible` | `--primary-pressed` | `--primary-foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `button.primary` | - | `loading` + `focus-visible` | `--primary` | `--primary-foreground` | - | `--ring` | 테두리 focus-visible |
| `button.secondary` | - | `hover` + `focus-visible` | `--state-hover-gray` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `button.secondary` | - | `pressed` + `focus-visible` | `--state-pressed-gray` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `button.ghost` | - | `hover` + `focus-visible` | `--state-hover-gray` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `button.ghost` | - | `pressed` + `focus-visible` | `--state-pressed-gray` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `button.icon` | - | `hover` + `focus-visible` | `--state-hover-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `button.icon` | - | `pressed` + `focus-visible` | `--state-pressed-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `button.icon` | - | `selected` + `focus-visible` | `--state-selected` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 selected |
| `button.trigger` | - | `open` + `hover` | `--state-selected` | `--foreground` | - | `--state-selected` | 바탕 open, 테두리 open |
| `button.trigger` | - | `open` + `pressed` | `--state-pressed-gray` | `--foreground` | - | `--state-pressed-gray` | 바탕 pressed, 테두리 pressed |
| `button.trigger` | - | `open` + `focus-visible` | `--state-selected` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 open |
| `button.trigger` | - | `hover` + `focus-visible` | `--state-hover-gray` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `button.send` | - | `hover` + `focus-visible` | `--primary-hover` | `--primary-foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `button.send` | - | `pressed` + `focus-visible` | `--primary-pressed` | `--primary-foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `button.send` | - | `loading` + `focus-visible` | `--primary` | `--primary-foreground` | - | `--ring` | 테두리 focus-visible |
| `field.trigger` | - | `open` + `hover` | `--state-hover-gray` | `--foreground` | - | `--state-hover-gray` | 바탕 hover, 테두리 hover |
| `field.trigger` | - | `open` + `focus-visible` | `--muted` | `--foreground` | - | `--ring` | 테두리 focus-visible |
| `menu.item` | - | `selected` + `hover` | `--state-selected` | `--foreground` | - | `--state-selected` | 바탕 selected, 테두리 selected |
| `menu.item` | - | `selected` + `focus-visible` | `--state-selected` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 selected |
| `menu.item` | - | `hover` + `focus-visible` | `--state-hover-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `chip.surface` | - | `loading` + `focus-visible` | `--card` | `--muted-foreground` | - | `--ring` | 글자 loading, 테두리 focus-visible |
| `chip.remove` | - | `hover` + `focus-visible` | `--state-hover-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover, 글자 hover |
| `chip.remove` | - | `pressed` + `focus-visible` | `--state-pressed-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed, 글자 pressed |
| `card.surface` | - | `selected` + `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 focus-visible |
| `card.surface` | - | `pressed` + `focus-visible` | `--accent-pressed` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `steps.past` | - | `hover` + `focus-visible` | `--accent` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `steps.past` | - | `pressed` + `focus-visible` | `--accent-pressed` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `tab.item` | - | `selected` + `hover` | `--state-hover-white` | `--foreground` | - | `--foreground` | 글자 selected, 테두리 selected, 바탕 hover |
| `tab.item` | - | `selected` + `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 focus-visible, 글자 selected |
| `tab.item` | - | `hover` + `focus-visible` | `--state-hover-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover, 글자 hover |
| `choice.radio` | - | `selected` + `hover` | `--state-selected` | `--foreground` | - | `--primary` | 바탕 selected, 테두리 selected |
| `choice.radio` | - | `selected` + `focus-visible` | `--state-selected` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 selected |
| `choice.radio` | - | `hover` + `focus-visible` | `--state-hover-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `choice.radio` | - | `pressed` + `focus-visible` | `--state-pressed-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `choice.switch` | - | `selected` + `hover` | `--state-selected` | `--foreground` | - | `--foreground` | 바탕 selected, 테두리 selected |
| `choice.switch` | - | `selected` + `focus-visible` | `--state-selected` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 selected |
| `choice.switch` | - | `hover` + `focus-visible` | `--state-hover-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `choice.switch` | - | `pressed` + `focus-visible` | `--state-pressed-white` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `reorder.row` | - | `hover` + `focus-visible` | `--accent` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `reorder.row` | - | `pressed` + `focus-visible` | `--card` | `--foreground` | - | `--ring` | 테두리 focus-visible |
| `player.control` | - | `hover` + `focus-visible` | `--accent` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover |
| `player.control` | - | `pressed` + `focus-visible` | `--accent-pressed` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 pressed |
| `sidebar.item` | - | `selected` + `hover` | `--state-selected` | `--foreground` | - | `--state-selected` | 바탕 selected, 글자 selected, 테두리 selected |
| `sidebar.item` | - | `selected` + `focus-visible` | `--state-selected` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 selected, 글자 selected |
| `sidebar.item` | - | `hover` + `focus-visible` | `--state-hover-gray` | `--foreground` | - | `--ring` | 테두리 focus-visible, 바탕 hover, 글자 hover |

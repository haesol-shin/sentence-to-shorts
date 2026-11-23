/**
 * The gallery state list for batch 1.
 *
 * Numbers come from these positions, never from a hand written label. Parts
 * and cases are append-only: a new case goes at the end of its part, and a new
 * part at the end of the list, so earlier numbers never move.
 */

export type GallerySurface = 'card' | 'background';

export type GalleryLayout = 'default' | 'top' | 'center' | 'bottom' | 'tight';

export type GalleryCase = {
  /**
   * The state this case shows. Matrix states keep the matrix name; a work
   * state the matrix does not list uses its own name.
   */
  state: string;
  /** The last piece of the number label, for example `hover`. */
  slug: string;
  variant?: string;
  /** Popups open in their own frame so they do not cover another case. */
  portal?: boolean;
  surface?: GallerySurface;
  layout?: GalleryLayout;
  /** The case width at 1920px. It shrinks to the frame at 390px. */
  width?: number;
  /** A visible one line note under the label, when the case needs one. */
  note?: string;
  /** The generated number label, for example `3-2-hover`. */
  label: string;
};

export type GalleryPart = {
  id: string;
  batch: number;
  number: number;
  title: string;
  description: string;
  /** The matrix row that supplies the states and the "not applicable" reasons. */
  matrixPart: string;
  /** Token rows this part also covers. */
  matrixParts: readonly string[];
  notApplicable: Readonly<Record<string, string>>;
  cases: readonly GalleryCase[];
};

type CaseSpec = Omit<GalleryCase, 'label'>;

type PartSpec = Omit<GalleryPart, 'number' | 'cases'> & {
  cases: readonly CaseSpec[];
};

const MATRIX_SKIP = {
  primary: {
    open: '면을 열지 않는다',
    selected: '한 번 실행하는 동작이라 고름 상태가 없다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  secondary: {
    open: '면을 열지 않는다',
    selected: '한 번 실행하는 동작이라 고름 상태가 없다',
    loading: '오래 걸리는 실행을 이 단추가 맡지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  ghost: {
    open: '면을 열지 않는다',
    selected: '고름 표시가 필요한 자리는 button.icon을 쓴다',
    loading: '오래 걸리는 실행을 이 단추가 맡지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  icon: {
    open: '면을 열지 않는다',
    loading: '아이콘 단추 안에 진행 표시를 두지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  chipRemove: {
    open: '지우기 단추는 면을 열지 않는다',
    selected: '지우기 단추는 고름 상태를 받지 않는다',
    disabled: '지울 수 없는 칩은 없다',
    loading: '지우기 전 확인 창이 확인을 맡는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '지우기 단추는 늘 쓸 수 있다',
  },
  chipSurface: {
    hover: '칩 전체에는 올림 표시를 두지 않는다',
    pressed: '칩 전체를 누르는 동작이 없다',
    open: '칩은 면을 열지 않는다',
    selected: '칩은 고름 상태를 받지 않는다',
    disabled: '쓸 수 없는 칩은 없다',
    unavailable: '쓸 수 없음 안내는 메뉴 항목이 맡는다',
  },
  tag: {
    hover: '꼬리표는 올림 상태를 받지 않는다',
    pressed: '꼬리표는 누름 상태를 받지 않는다',
    open: '꼬리표는 면을 열지 않는다',
    selected: '꼬리표는 고를 수 없다',
    disabled: '꼬리표는 쓸 수 없음 상태를 받지 않는다',
    'focus-visible': '꼬리표는 포커스를 받지 않는다',
    loading: '꼬리표는 불러오는 상태를 받지 않는다',
    error: '오류 꼬리표가 error variant다',
    unavailable: '쓸 수 없음은 꼬리표의 neutral variant로 보인다',
  },
  tooltip: {
    open: '면은 열린 동안에만 존재한다',
    hover: '면 자체는 올림 상태를 받지 않는다',
    pressed: '면 자체는 누름 상태를 받지 않는다',
    selected: '면 자체는 고름 상태를 받지 않는다',
    disabled: '면 자체는 쓸 수 없음 상태를 받지 않는다',
    'focus-visible': '면 자체는 포커스를 받지 않는다',
    loading: '면 자체는 불러오는 상태를 받지 않는다',
    error: '면 자체는 오류 상태를 받지 않는다',
    unavailable: '면 자체는 쓸 수 없음 안내 상태를 받지 않는다',
  },
  notice: {
    hover: '안내 문장은 올림 상태를 받지 않는다',
    pressed: '안내 문장은 누름 상태를 받지 않는다',
    open: '안내 문장은 면을 열지 않는다',
    selected: '안내 문장은 고를 수 없다',
    disabled: '안내 문장은 쓸 수 없음 상태를 받지 않는다',
    'focus-visible': '안내 문장은 포커스를 받지 않는다',
    loading: '불러오는 동안은 자리표시가 맡는다',
    error: '오류는 notice.title의 error variant가 맡는다',
    unavailable: '쓸 수 없음 안내는 notice.title이 맡는다',
  },
  tab: {
    open: '탭은 면을 열지 않는다',
    loading: '탭 안에 진행 표시를 두지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없는 탭은 disabled로 표시한다',
  },
  radio: {
    open: '고르는 항목은 면을 열지 않는다',
    loading: '고르는 항목은 불러오는 상태를 받지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  switch: {
    open: '켜기와 끄기는 면을 열지 않는다',
    loading: '켜기와 끄기는 불러오는 상태를 받지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  trigger: {
    selected: '판을 여는 단추라 고름 상태가 없다',
    loading: '판을 여는 동작은 기다리지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  field: {
    pressed: '누르면 바로 열리고 누른 표시를 두지 않는다',
    selected: '값 하나를 고르는 칸이라 스스로 고름 상태가 없다',
    loading: '값을 불러오는 표시는 메뉴 항목이 맡는다',
    error: '값 칸 자체에는 오류 표시를 두지 않는다',
    unavailable: '값 칸은 늘 쓸 수 있다',
  },
  textSurface: {
    hover: '입력창은 올림 상태를 받지 않는다',
    pressed: '입력창은 누름 상태를 받지 않는다',
    open: '입력창은 면을 열지 않는다',
    selected: '입력창은 고름 상태를 받지 않는다',
    loading: '불러오는 동안은 보내기 단추가 loading을 쓴다',
    error: '입력 오류는 안내 문장이 알린다',
    unavailable: '입력창은 늘 쓸 수 있다',
  },
  send: {
    open: '면을 열지 않는다',
    selected: '보내는 한 번의 동작이라 고름 상태가 없다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '보낼 수 없음은 disabled로 표시한다',
  },
  surfaceOnly: {
    open: '면은 열린 동안에만 존재한다',
    hover: '면 자체는 올림 상태를 받지 않는다',
    pressed: '면 자체는 누름 상태를 받지 않는다',
    selected: '면 자체는 고름 상태를 받지 않는다',
    disabled: '면 자체는 쓸 수 없음 상태를 받지 않는다',
    'focus-visible': '면 자체는 포커스를 받지 않는다',
    loading: '면 자체는 불러오는 상태를 받지 않는다',
    error: '오류는 안내 문장이 알린다',
    unavailable: '면 자체는 쓸 수 없음 안내 상태를 받지 않는다',
  },
  sidebar: {
    open: '하위 면을 열지 않는다',
    loading: '사이드바 항목은 불러오는 상태를 받지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '쓸 수 없음은 disabled로 표시한다',
  },
  stepsCurrent: {
    hover: '지금 단계는 누를 수 없다',
    pressed: '지금 단계는 누를 수 없다',
    open: '단계 표시는 면을 열지 않는다',
    selected: '지금 단계 자체가 고른 상태라 default가 그 모양이다',
    disabled: '지금 단계는 굵은 글자로 보인다',
    'focus-visible': '지금 단계는 포커스를 받지 않는다',
    loading: '단계 표시는 불러오는 상태를 받지 않는다',
    error: '단계 표시는 오류 상태를 받지 않는다',
    unavailable: '지금 단계는 쓸 수 없음 안내 상태가 아니다',
  },
  card: {
    hover: '큰 면이라 올림 색을 두지 않는다',
    open: '카드는 면을 열지 않는다',
    loading: '불러오는 동안은 자리표시가 맡는다',
    error: '실패한 카드는 안내 문장이 알린다',
    unavailable: '쓸 수 없는 카드는 없다',
  },
  reorder: {
    open: '순서 바꾸는 줄은 면을 열지 않는다',
    selected: '줄을 고르는 동작이 없다',
    disabled: '순서 바꾸기는 늘 쓸 수 있다',
    loading: '순서 바꾸는 줄은 불러오는 상태를 받지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '순서 바꾸는 줄은 쓸 수 없음 안내 상태를 받지 않는다',
  },
  playerControl: {
    open: '재생 제어는 면을 열지 않는다',
    selected: '재생과 멈춤은 아이콘 모양으로만 구분한다',
    loading: '재생 제어는 불러오는 상태를 받지 않는다',
    error: '실패는 안내 문장이 알린다',
    unavailable: '재생할 것이 없으면 disabled로 표시한다',
  },
} as const;

const SPECS: readonly PartSpec[] = [
  {
    id: 'button-primary',
    batch: 1,
    title: '주 단추',
    description: '한 번 실행하는 대표 동작이다. 실행 중에는 같은 자리에서 ■ 멈춤 단추가 되고 작업이 끝나면 돌아온다.',
    matrixPart: 'button.primary',
    matrixParts: ['button.primary'],
    notApplicable: MATRIX_SKIP.primary,
    cases: [
      { state: 'default', slug: 'default', note: '검정 대표색' },
      { state: 'hover', slug: 'hover', note: '바탕을 조금 밝게' },
      { state: 'pressed', slug: 'pressed' },
      { state: 'disabled', slug: 'disabled' },
      { state: 'loading', slug: 'loading' },
      { state: 'focus-visible', slug: 'focus-visible', note: '키보드 포커스' },
    ],
  },
  {
    id: 'button-secondary',
    batch: 1,
    title: '보조 단추',
    description: '주 동작 옆에 서는 단추다. 회색 바탕에서 올리면 한 단계 진해진다.',
    matrixPart: 'button.secondary',
    matrixParts: ['button.secondary'],
    notApplicable: MATRIX_SKIP.secondary,
    cases: [
      { state: 'default', slug: 'default' },
      { state: 'hover', slug: 'hover' },
      { state: 'pressed', slug: 'pressed' },
      { state: 'disabled', slug: 'disabled' },
      { state: 'focus-visible', slug: 'focus-visible' },
    ],
  },
  {
    id: 'button-ghost',
    batch: 1,
    title: '작은 글자 단추',
    description: '보이는 높이는 32이고 누를 영역은 44다. 앱 바탕 위에 놓는다.',
    matrixPart: 'button.ghost',
    matrixParts: ['button.ghost'],
    notApplicable: MATRIX_SKIP.ghost,
    cases: [
      { state: 'default', slug: 'default', surface: 'background' },
      { state: 'hover', slug: 'hover', surface: 'background' },
      { state: 'pressed', slug: 'pressed', surface: 'background' },
      { state: 'disabled', slug: 'disabled', surface: 'background' },
      { state: 'focus-visible', slug: 'focus-visible', surface: 'background' },
    ],
  },
  {
    id: 'button-icon',
    batch: 1,
    title: '아이콘 단추',
    description: '아이콘만 있는 단추다. 기본은 보이는 크기와 누를 영역이 모두 44다. 줄 안에 들어가는 compact는 보이는 크기 32에 누를 영역 44다.',
    matrixPart: 'button.icon',
    matrixParts: ['button.icon'],
    notApplicable: MATRIX_SKIP.icon,
    cases: [
      { state: 'default', slug: 'default' },
      { state: 'hover', slug: 'hover' },
      { state: 'pressed', slug: 'pressed' },
      { state: 'selected', slug: 'selected' },
      { state: 'disabled', slug: 'disabled' },
      { state: 'focus-visible', slug: 'focus-visible' },
      { state: 'default', slug: 'compact', note: '보이는 32, 누를 영역 44' },
    ],
  },
  {
    id: 'chip-remove',
    batch: 1,
    title: '닫기 x',
    description: '판과 창은 44, 파일 칩은 32로 보인다. 두 크기 모두 누를 영역은 44다.',
    matrixPart: 'chip.remove',
    matrixParts: ['chip.remove'],
    notApplicable: MATRIX_SKIP.chipRemove,
    cases: [
      { state: 'default', slug: 'default' },
      { state: 'hover', slug: 'hover' },
      { state: 'pressed', slug: 'pressed' },
      { state: 'focus-visible', slug: 'focus-visible' },
    ],
  },
  {
    id: 'chip',
    batch: 1,
    title: '파일 칩',
    description: '받는 중과 실패를 같은 칩에서 보인다. 실패하면 테두리와 이름이 빨개지고, 종류 아이콘 자리에 경고 아이콘이 들어가 폭은 그대로다. 종류 아이콘이 없는 칩은 테두리와 이름만 빨개진다. 지우기 x는 닫기 부품을 그대로 쓴다.',
    matrixPart: 'chip.surface',
    matrixParts: ['chip.surface', 'chip.remove'],
    notApplicable: MATRIX_SKIP.chipSurface,
    cases: [
      { state: 'default', slug: 'default', width: 420 },
      { state: 'loading', slug: 'loading', width: 420 },
      { state: 'error', slug: 'error', width: 420 },
      { state: 'focus-visible', slug: 'focus-visible', width: 420 },
      { state: 'default', slug: 'no-lead', width: 420 },
      { state: 'loading', slug: 'no-lead-loading', width: 420 },
      { state: 'default', slug: 'element-default', width: 420 },
      { state: 'error', slug: 'element-error', width: 420 },
    ],
  },
  {
    id: 'tag',
    batch: 1,
    title: '꼬리표',
    description: '뜻은 아이콘 색으로만 보인다. 높이는 26에 반경 13이고 회색 바탕의 글자는 foreground를 지킨다.',
    matrixPart: 'tag',
    matrixParts: ['tag'],
    notApplicable: MATRIX_SKIP.tag,
    cases: [
      { state: 'default', slug: 'neutral', variant: 'neutral' },
      { state: 'default', slug: 'soon', variant: 'neutral' },
      { state: 'default', slug: 'new', variant: 'new' },
      { state: 'default', slug: 'warning', variant: 'warning' },
      { state: 'default', slug: 'error', variant: 'error' },
    ],
  },
  {
    id: 'tooltip',
    batch: 1,
    title: 'tooltip',
    description: '마우스를 올리거나 키보드 초점을 주면 열린다. 한 줄은 알약, 두 줄은 16 반경이다.',
    matrixPart: 'tooltip.surface',
    matrixParts: ['tooltip.surface'],
    notApplicable: MATRIX_SKIP.tooltip,
    cases: [
      { state: 'default', slug: 'default', portal: true, layout: 'center', note: '한 줄' },
      { state: 'default', slug: 'long', portal: true, layout: 'center', note: '두 줄' },
      { state: 'default', slug: 'trigger', layout: 'center', note: '닫힌 trigger' },
    ],
  },
  {
    id: 'notice',
    batch: 1,
    title: '안내 문장',
    description: '회색 바탕에 제목과 본문을 둔다. 뜻 색은 제목 옆 아이콘에만 쓴다.',
    matrixPart: 'notice.surface',
    matrixParts: ['notice.surface', 'notice.title', 'notice.body'],
    notApplicable: MATRIX_SKIP.notice,
    cases: [
      { state: 'default', slug: 'neutral', variant: 'neutral', width: 480 },
      { state: 'default', slug: 'warning', variant: 'warning', width: 480 },
      { state: 'default', slug: 'error', variant: 'error', width: 480 },
      { state: 'default', slug: 'long', variant: 'neutral', width: 480, note: '두 줄 본문' },
    ],
  },
  {
    id: 'tabs',
    batch: 1,
    title: '탭',
    description: '고른 탭은 글자 아래 선으로 표시한다. 화살표 키로 옮기고 고른다.',
    matrixPart: 'tab.item',
    matrixParts: ['tab.item'],
    notApplicable: MATRIX_SKIP.tab,
    cases: [
      { state: 'default', slug: 'default', width: 420 },
      { state: 'hover', slug: 'hover', width: 420 },
      { state: 'pressed', slug: 'pressed', width: 420 },
      { state: 'selected', slug: 'selected', width: 420 },
      { state: 'disabled', slug: 'disabled', width: 420 },
      { state: 'focus-visible', slug: 'focus-visible', width: 420 },
      { state: 'default', slug: 'latin-default', width: 420 },
      { state: 'selected', slug: 'latin-selected', width: 420 },
    ],
  },
  {
    id: 'radio',
    batch: 1,
    title: '단일 선택 그룹',
    description: '여러 값 중 하나를 고른다. 고르지 않은 항목은 이름 폭만 차지하고, 고른 항목만 회색 바탕과 굵은 글자와 체크 자리를 가진다.',
    matrixPart: 'choice.radio',
    matrixParts: ['choice.radio'],
    notApplicable: MATRIX_SKIP.radio,
    cases: [
      { state: 'default', slug: 'default', width: 480 },
      { state: 'hover', slug: 'hover', width: 480 },
      { state: 'pressed', slug: 'pressed', width: 480 },
      { state: 'selected', slug: 'selected', width: 480 },
      { state: 'disabled', slug: 'disabled', width: 480 },
      { state: 'focus-visible', slug: 'focus-visible', width: 480 },
    ],
  },
  {
    id: 'switch',
    batch: 1,
    title: '켜기·끄기',
    description: '켜짐은 선택 색 트랙과 오른쪽 손잡이로 보인다. 트랙은 44x26, 손잡이는 20이고 줄 44가 누를 영역이다.',
    matrixPart: 'choice.switch',
    matrixParts: ['choice.switch'],
    notApplicable: MATRIX_SKIP.switch,
    cases: [
      { state: 'default', slug: 'default' },
      { state: 'hover', slug: 'hover' },
      { state: 'pressed', slug: 'pressed' },
      { state: 'selected', slug: 'selected' },
      { state: 'disabled', slug: 'disabled' },
      { state: 'focus-visible', slug: 'focus-visible' },
      { state: 'selected', slug: 'label-element' },
    ],
  },
  {
    id: 'menu',
    batch: 1,
    title: '열리는 메뉴',
    description: '값 칸 메뉴와 같은 줄 모양을 쓴다. 안 되는 항목은 흐리게 두고 곧 지원 꼬리표와 보이는 이유를 둔다.',
    matrixPart: 'button.trigger',
    matrixParts: ['button.trigger', 'menu.surface', 'menu.label', 'menu.item'],
    notApplicable: MATRIX_SKIP.trigger,
    cases: [
      { state: 'default', slug: 'default', surface: 'background' },
      { state: 'hover', slug: 'hover', surface: 'background' },
      { state: 'pressed', slug: 'pressed', surface: 'background' },
      { state: 'disabled', slug: 'disabled', surface: 'background' },
      { state: 'focus-visible', slug: 'focus-visible', surface: 'background' },
      { state: 'open', slug: 'open', portal: true, surface: 'background' },
      { state: 'default', slug: 'item-default', portal: true, surface: 'background' },
      { state: 'hover', slug: 'item-hover', portal: true, surface: 'background' },
      { state: 'pressed', slug: 'item-pressed', portal: true, surface: 'background' },
      { state: 'selected', slug: 'item-selected', portal: true, surface: 'background' },
      { state: 'disabled', slug: 'item-disabled', portal: true, surface: 'background' },
      { state: 'unavailable', slug: 'item-unavailable', portal: true, surface: 'background' },
      { state: 'focus-visible', slug: 'item-focus-visible', portal: true, surface: 'background' },
      { state: 'open', slug: 'open-long', portal: true, surface: 'background' },
    ],
  },
  {
    id: 'value-field',
    batch: 1,
    title: '값 칸',
    description: '메뉴는 칸 아래에 칸과 같은 폭으로 열린다. 아래 공간이 모자랄 때만 위로 뒤집는다.',
    matrixPart: 'field.trigger',
    matrixParts: ['field.trigger', 'menu.surface', 'menu.label', 'menu.item'],
    notApplicable: MATRIX_SKIP.field,
    cases: [
      { state: 'default', slug: 'default', width: 260 },
      { state: 'hover', slug: 'hover', width: 260 },
      { state: 'focus-visible', slug: 'focus-visible', width: 260 },
      { state: 'open', slug: 'open', portal: true, width: 260, layout: 'top', note: '칸 아래로' },
      { state: 'open', slug: 'open-above', portal: true, width: 260, layout: 'bottom', note: '아래 공간 부족' },
      { state: 'open', slug: 'open-tight', portal: true, width: 260, layout: 'tight', note: '위아래 모두 부족' },
      { state: 'disabled', slug: 'disabled', width: 260 },
    ],
  },
  {
    id: 'text-field',
    batch: 1,
    title: '한 줄 입력',
    description: '오류 설명은 aria-describedby로 입력칸과 연결한다. 오류 색은 글자에만 쓴다.',
    matrixPart: 'composer.surface',
    matrixParts: ['composer.surface', 'composer.textarea', 'composer.placeholder'],
    notApplicable: MATRIX_SKIP.textSurface,
    cases: [
      { state: 'default', slug: 'default', width: 320 },
      { state: 'default', slug: 'filled', variant: 'filled', width: 320 },
      { state: 'focus-visible', slug: 'focus-visible', width: 320 },
      { state: 'disabled', slug: 'disabled', width: 320 },
      { state: 'default', slug: 'error', variant: 'error', width: 320, note: '오류 설명' },
    ],
  },
  {
    id: 'settings-row',
    batch: 1,
    title: '설정 행',
    description: '행은 조작이 아니고 안의 조작이 상태를 가진다. 안의 Switch는 트랙과 손잡이로 켜짐을 보이며, 안 되는 설정은 흐린 조작과 곧 지원 꼬리표로 보인다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [
      { state: 'default', slug: 'default', width: 560 },
      { state: 'selected', slug: 'on', width: 560 },
      { state: 'default', slug: 'field', width: 560 },
      { state: 'unavailable', slug: 'unavailable', width: 560 },
    ],
  },
  {
    id: 'send-button',
    batch: 2,
    title: '보내기',
    description: '보이는 원은 32이고 투명 영역으로 44를 채운다. 답을 기다리는 동안 화살표 자리에 ■가 들어가고 이름은 멈추기가 된다.',
    matrixPart: 'button.send',
    matrixParts: ['button.send'],
    notApplicable: MATRIX_SKIP.send,
    cases: [
      { state: 'default', slug: 'default', width: 160, note: '보이는 32, 누를 영역 44' },
      { state: 'hover', slug: 'hover', width: 160 },
      { state: 'pressed', slug: 'pressed', width: 160 },
      { state: 'disabled', slug: 'disabled', width: 160 },
      { state: 'loading', slug: 'loading', width: 160 },
      { state: 'focus-visible', slug: 'focus-visible', width: 160 },
    ],
  },
  {
    id: 'composer',
    batch: 2,
    title: '입력창',
    description: '글 칸이 위, 단추 줄이 아래다. 열 줄 240까지 자라고 넘으면 칸 안에서 스크롤하며 가려진 쪽을 흐린다. 반경은 28 고정이다.',
    matrixPart: 'composer.surface',
    matrixParts: ['composer.surface', 'composer.textarea', 'composer.placeholder'],
    notApplicable: MATRIX_SKIP.textSurface,
    cases: [
      { state: 'default', slug: 'default', width: 420, note: '자리 안내 글은 --sub' },
      { state: 'default', slug: 'filled', width: 420 },
      { state: 'focus-visible', slug: 'focus-visible', width: 420 },
      { state: 'disabled', slug: 'disabled', width: 420 },
      { state: 'default', slug: 'long', width: 420, note: '열 줄에서 칸 안 스크롤' },
      { state: 'default', slug: 'chips', width: 420, note: '값 칩 36' },
      { state: 'default', slug: 'attachments', width: 420, note: '파일 칩' },
      { state: 'default', slug: 'drop', width: 420, note: '파일 놓는 점선' },
    ],
  },
  {
    id: 'file-chip',
    batch: 2,
    title: '파일 칩',
    description: '종류 그림, 이름, 종류와 길이, 지우기를 한 줄에 둔다. 받는 중에는 아래쪽 진행 막대가 차오른다. 실패는 빨간 테두리, 경고 아이콘, 빨간 문장이고 종류 그림은 회색을 지키며, 재시도는 아이콘 단추로 둔다.',
    matrixPart: 'chip.surface',
    matrixParts: ['chip.surface', 'chip.remove'],
    notApplicable: MATRIX_SKIP.chipSurface,
    cases: [
      { state: 'default', slug: 'default', width: 420 },
      { state: 'loading', slug: 'loading', width: 420, note: '받는 중' },
      { state: 'error', slug: 'error', width: 420 },
      { state: 'focus-visible', slug: 'focus-visible', width: 420 },
      { state: 'error', slug: 'error-retry', width: 420, note: '재시도 아이콘' },
    ],
  },
  {
    id: 'file-drop',
    batch: 2,
    title: '파일 놓는 칸',
    description: '첫 화면은 화면 가장자리 24 안쪽을 덮고, 편집 화면은 파일을 받을 칸 안만 덮는다. 둥근 점선과 가운데 받는 파일은 같다.',
    matrixPart: 'dropzone.surface',
    matrixParts: ['dropzone.surface', 'dropzone.mask'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [
      { state: 'default', slug: 'default', portal: true, layout: 'top', note: '화면 전체' },
      { state: 'default', slug: 'long', portal: true, layout: 'top' },
      { state: 'default', slug: 'container', layout: 'top', note: '대상 칸' },
    ],
  },
  {
    id: 'dialog',
    batch: 2,
    title: '창',
    description: '너비 480, 반경 24, 안쪽 여백 24다. 뒤에는 진한 회색 24% 막을 깐다. Escape로 닫고 포커스는 연 단추로 돌아간다.',
    matrixPart: 'dialog.surface',
    matrixParts: ['dialog.surface', 'dialog.backdrop'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [
      { state: 'default', slug: 'default', portal: true, layout: 'top' },
      { state: 'default', slug: 'long', portal: true, layout: 'top', note: '긴 본문' },
    ],
  },
  {
    id: 'alert',
    batch: 2,
    title: '알림 창',
    description: '확인을 받는 창과 실패를 알리는 창이 같은 모양이다. 회색 단추가 먼저 오고 검정 단추는 오른쪽이다. 실패 창은 제목과 아이콘이 빨갛다.',
    matrixPart: 'dialog.surface',
    matrixParts: ['dialog.surface', 'dialog.backdrop'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [
      { state: 'default', slug: 'confirm', portal: true, layout: 'top' },
      { state: 'default', slug: 'error', portal: true, layout: 'top', note: '실패 안내' },
    ],
  },
  {
    id: 'confirm-delete',
    batch: 2,
    title: '지우기 전 확인 창',
    description: '지우기 전에 한 번 묻는다. 위험은 빨간 제목으로 알리고 확인 단추는 primary로 둔다.',
    matrixPart: 'dialog.surface',
    matrixParts: ['dialog.surface', 'dialog.backdrop'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [{ state: 'default', slug: 'default', portal: true, layout: 'top' }],
  },
  {
    id: 'confirm-range',
    batch: 2,
    title: '다시 만들 범위 확인 창',
    description: '바뀌는 값과 다시 만드는 범위를 적용 전에 보인다. 값 하나만 바뀌는 변경에는 쓰지 않는다.',
    matrixPart: 'dialog.surface',
    matrixParts: ['dialog.surface', 'dialog.backdrop'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [{ state: 'default', slug: 'default', portal: true, layout: 'top' }],
  },
  {
    id: 'toast',
    batch: 2,
    title: '알림',
    description: '방금 한 일을 한 줄로 알린다. 높이 44, 반경 22이고 화면 아래 가운데에 뜬다.',
    matrixPart: 'toast.surface',
    matrixParts: ['toast.surface'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [
      { state: 'default', slug: 'default', portal: true, layout: 'top' },
      { state: 'default', slug: 'long', portal: true, layout: 'top', note: '한 줄 말줄임' },
      { state: 'default', slug: 'action', portal: true, layout: 'top', note: '되돌리기 단추' },
    ],
  },
  {
    id: 'bottom-sheet',
    batch: 2,
    title: '아래에서 올라오는 판',
    description: '아래에서 올라오는 판이다. 390에서는 화면 폭을 채우고 1920에서는 480이다. 바깥 누르기와 Escape로 닫는다.',
    matrixPart: 'picker.window',
    matrixParts: ['picker.window', 'panel.surface', 'panel.scrim'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [
      { state: 'default', slug: 'default', portal: true, layout: 'top' },
      { state: 'default', slug: 'long', portal: true, layout: 'top', note: '긴 목록' },
    ],
  },
  {
    id: 'progress',
    batch: 2,
    title: '진행 표시',
    description: '진행 막대는 높이 6이고 바탕과 채운 부분 모두 끝이 둥글다. 막대, 이름, 값은 모두 foreground다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [
      { state: 'default', slug: 'bar', width: 420 },
      { state: 'default', slug: 'label', width: 420, note: '값 줄' },
      { state: 'default', slug: 'complete', width: 420 },
      { state: 'default', slug: 'indeterminate', width: 420, note: '값 없음' },
      { state: 'default', slug: 'count', width: 420, note: '3 / 5' },
    ],
  },
  {
    id: 'skeleton',
    batch: 2,
    title: '자리표시',
    description: '그림과 글줄이 들어올 자리를 회색 면으로 채운다. 크기는 실제 자리와 같다.',
    matrixPart: 'skeleton.block',
    matrixParts: ['skeleton.block'],
    notApplicable: MATRIX_SKIP.surfaceOnly,
    cases: [
      { state: 'default', slug: 'thumb', width: 420 },
      { state: 'default', slug: 'script', width: 420 },
      { state: 'default', slug: 'media', width: 420 },
      { state: 'default', slug: 'text', width: 420 },
    ],
  },
  {
    id: 'empty-state',
    batch: 2,
    title: '빈 화면',
    description: '그림 없이 제목, 한 문장, 다음 행동을 가운데에 둔다. 폭은 560이다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [
      { state: 'default', slug: 'default', width: 620 },
      { state: 'default', slug: 'long', width: 620, note: '긴 문장' },
    ],
  },
  {
    id: 'error-state',
    batch: 2,
    title: '오류 화면',
    description: '무슨 일이 났고 어떻게 고치는지 쓴다. 빈 화면과 같은 부품에 오류 뜻만 더한다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [
      { state: 'default', slug: 'retry', width: 620 },
      { state: 'default', slug: 'long', width: 620, note: '긴 안내' },
    ],
  },
  {
    id: 'sidebar-item',
    batch: 3,
    title: '사이드바 항목',
    description: '아이콘만 있는 44x44 항목이다. 이름은 tooltip으로 보이고 지금 화면은 회색 바탕으로 표시한다.',
    matrixPart: 'sidebar.item',
    matrixParts: ['sidebar.item'],
    notApplicable: MATRIX_SKIP.sidebar,
    cases: [
      { state: 'default', slug: 'default', surface: 'background' },
      { state: 'hover', slug: 'hover', surface: 'background' },
      { state: 'pressed', slug: 'pressed', surface: 'background' },
      { state: 'selected', slug: 'selected', surface: 'background', note: '지금 화면' },
      { state: 'disabled', slug: 'disabled', surface: 'background' },
      { state: 'focus-visible', slug: 'focus-visible', surface: 'background' },
      { state: 'default', slug: 'tooltip', portal: true, surface: 'background', layout: 'center', note: '이름 tooltip' },
    ],
  },
  {
    id: 'top-bar-item',
    batch: 3,
    title: '상단바 항목',
    description: '평소에는 바탕 없이 글자만 두고, 올리거나 열면 회색 바탕과 굵은 글자를 쓴다. 누르면 메뉴가 열린다.',
    matrixPart: 'button.trigger',
    matrixParts: ['button.trigger'],
    notApplicable: MATRIX_SKIP.trigger,
    cases: [
      { state: 'default', slug: 'default', surface: 'background' },
      { state: 'hover', slug: 'hover', surface: 'background' },
      { state: 'pressed', slug: 'pressed', surface: 'background' },
      { state: 'open', slug: 'open', surface: 'background' },
      { state: 'disabled', slug: 'disabled', surface: 'background' },
      { state: 'focus-visible', slug: 'focus-visible', surface: 'background' },
      { state: 'open', slug: 'menu-open', portal: true, surface: 'background', layout: 'top', note: '메뉴 열림' },
    ],
  },
  {
    id: 'top-bar-status',
    batch: 3,
    title: '상단바 상태',
    description: '저장 상태와 진행 상태를 한 줄로 보이고 누르면 그 판을 연다. 진행 중에는 spinner와 진행 글자(숫자 포함)가 파랑이고 판을 여는 화살표는 회색이며, 판 안 진행 표시의 막대, 이름, 숫자는 검정이다.',
    matrixPart: 'button.trigger',
    matrixParts: ['button.trigger', 'panel.surface'],
    notApplicable: MATRIX_SKIP.trigger,
    cases: [
      { state: 'default', slug: 'default', surface: 'background', note: '저장 실패' },
      { state: 'hover', slug: 'hover', surface: 'background' },
      { state: 'pressed', slug: 'pressed', surface: 'background' },
      { state: 'open', slug: 'open', surface: 'background' },
      { state: 'disabled', slug: 'disabled', surface: 'background' },
      { state: 'focus-visible', slug: 'focus-visible', surface: 'background' },
      { state: 'open', slug: 'panel-open', portal: true, surface: 'background', layout: 'top', note: '상태 판 열림' },
      { state: 'busy', slug: 'working-open', portal: true, surface: 'background', layout: 'top', note: '진행 글자와 판, 멈춤 단추 없음' },
    ],
  },
  {
    id: 'stage-indicator',
    batch: 3,
    title: '단계 표시',
    description: '네 단계 이름과 지금 단계 아래 점이다. 지난 단계는 눌러서 돌아가고 남은 단계는 흐린 글자다.',
    matrixPart: 'steps.current',
    matrixParts: ['steps.current', 'steps.past', 'steps.upcoming'],
    notApplicable: MATRIX_SKIP.stepsCurrent,
    cases: [
      { state: 'default', slug: 'current', width: 520, note: '지금은 편집' },
      { state: 'default', slug: 'past-default', width: 520 },
      { state: 'hover', slug: 'past-hover', width: 520 },
      { state: 'pressed', slug: 'past-pressed', width: 520 },
      { state: 'focus-visible', slug: 'past-focus-visible', width: 520 },
      { state: 'default', slug: 'upcoming', width: 520, note: '남은 단계' },
    ],
  },
  {
    id: 'card',
    batch: 3,
    title: '카드',
    description: '포맷 카드는 폭 216에 4:3 200x150 그림과 이름, 장면 카드는 9:16 그림과 번호와 한 줄이다. 고른 카드는 같은 크기로 글자만 굵어지고 다른 그림은 흐려진다. 고치는 동안에는 이름 줄이 파란 spinner와 고치는 중으로 바뀌고 테두리에 띠가 돈다.',
    matrixPart: 'card.surface',
    matrixParts: ['card.surface'],
    notApplicable: MATRIX_SKIP.card,
    cases: [
      { state: 'default', slug: 'format-default', variant: 'format', width: 320 },
      { state: 'pressed', slug: 'format-pressed', variant: 'format', width: 320 },
      { state: 'selected', slug: 'format-selected', variant: 'format', width: 320 },
      { state: 'disabled', slug: 'format-disabled', variant: 'format', width: 320 },
      { state: 'focus-visible', slug: 'format-focus-visible', variant: 'format', width: 320 },
      { state: 'default', slug: 'scene-default', variant: 'scene', width: 320 },
      { state: 'pressed', slug: 'scene-pressed', variant: 'scene', width: 320 },
      { state: 'selected', slug: 'scene-selected', variant: 'scene', width: 320 },
      { state: 'disabled', slug: 'scene-disabled', variant: 'scene', width: 320 },
      { state: 'focus-visible', slug: 'scene-focus-visible', variant: 'scene', width: 320 },
      { state: 'busy', slug: 'scene-busy', variant: 'scene', width: 320, note: '고치는 중' },
    ],
  },
  {
    id: 'reorder-list',
    batch: 3,
    title: '순서 바꾸는 목록',
    description: '줄 높이는 44이고 손잡이 32와 이동 36은 투명 영역으로 44를 채운다. 끌거나 위아래 단추로 순서를 바꾼다.',
    matrixPart: 'reorder.row',
    matrixParts: ['reorder.row'],
    notApplicable: MATRIX_SKIP.reorder,
    cases: [
      { state: 'default', slug: 'default', width: 460 },
      { state: 'hover', slug: 'hover', width: 460 },
      { state: 'pressed', slug: 'pressed', width: 460, note: '끄는 동안' },
      { state: 'focus-visible', slug: 'focus-visible', width: 460 },
    ],
  },
  {
    id: 'playback-controls',
    batch: 3,
    title: '재생 제어',
    description: '재생, 진행 막대, 시간, 소리를 한 줄에 둔다. 재생과 멈춤에서 자리가 같고 아이콘과 채움만 바뀐다. 막대 바탕과 채운 부분 모두 양 끝이 둥글다.',
    matrixPart: 'player.control',
    matrixParts: ['player.control', 'player.progress'],
    notApplicable: MATRIX_SKIP.playerControl,
    cases: [
      { state: 'default', slug: 'default', width: 440, note: '멈춤' },
      { state: 'default', slug: 'playing', width: 440, note: '재생 중' },
      { state: 'hover', slug: 'hover', width: 440 },
      { state: 'pressed', slug: 'pressed', width: 440 },
      { state: 'disabled', slug: 'disabled', width: 440 },
      { state: 'focus-visible', slug: 'focus-visible', width: 440 },
      { state: 'default', slug: 'progress', width: 440, note: '40% 재생' },
      { state: 'focus-visible', slug: 'progress-focus-visible', width: 440, note: '진행 막대 포커스' },
    ],
  },
  {
    id: 'video-preview',
    batch: 3,
    title: '영상 미리보기',
    description: '9:16 미리보기다. 그림이 없을 때, 준비하는 중, 완성된 영상이 같은 상자를 쓴다. 재생은 아래 재생 줄이 맡는다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [
      { state: 'default', slug: 'empty', width: 320, note: '그림 없음' },
      { state: 'default', slug: 'loading', width: 320 },
      { state: 'default', slug: 'ready', width: 320, note: '완성된 영상' },
    ],
  },
  {
    id: 'result-card',
    batch: 3,
    title: '결과 카드 조립',
    description: '왼쪽에 영상과 재생 줄, 오른쪽에 제목, 한 줄 설명, 사실 네 줄을 위에서부터 둔다. 바닥 단추는 「편집으로」와 「mp4 저장」이고 우상단 x로 닫는다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [{ state: 'default', slug: 'default', width: 460, portal: true, layout: 'top' }],
  },
  {
    id: 'scroll-pane',
    batch: 3,
    title: '아래로 넘기기',
    description: '넘치는 칸의 스크롤바를 그리지 않고, 아래에 더 있을 때만 칸 아래 가운데에 44 둥근 「아래로 넘기기」 단추를 띄운다. 누르면 한 화면의 80퍼센트만큼 내리고 끝에 닿으면 사라진다.',
    matrixPart: '',
    matrixParts: [],
    notApplicable: {},
    cases: [
      { state: 'default', slug: 'long', width: 480, note: '아래에 더 있음' },
      { state: 'default', slug: 'end', width: 480, note: '맨 아래' },
      { state: 'default', slug: 'short', width: 480, note: '단추 없음' },
    ],
  },
];

/** The surfaces a gallery case opens over the page, in one list for every test. */
export const GALLERY_SURFACES =
  '.menu-positioner, .field-positioner, .tooltip-positioner, .status-positioner, .dialog, .sheet-popup, .toast-surface, .file-drop';

/**
 * The batch 2 parts whose controls the gallery hit area record covers. The
 * progress part keeps its own state coverage, so it is not listed here.
 */
export const HIT_AREA_PART_IDS = [
  'send-button',
  'composer',
  'file-chip',
  'file-drop',
  'dialog',
  'alert',
  'confirm-delete',
  'confirm-range',
  'toast',
  'bottom-sheet',
  'skeleton',
  'empty-state',
  'error-state',
] as const;

export const galleryParts: readonly GalleryPart[] = SPECS.map((spec, partIndex) => ({
  ...spec,
  number: partIndex + 1,
  cases: spec.cases.map((entry, caseIndex) => ({
    ...entry,
    portal: entry.portal ?? false,
    surface: entry.surface ?? 'card',
    layout: entry.layout ?? 'default',
    label: `${partIndex + 1}-${caseIndex + 1}-${entry.slug}`,
  })),
}));

export const galleryRanges: readonly { id: string; parts: readonly GalleryPart[] }[] = Array.from(
  { length: Math.ceil(galleryParts.length / 4) },
  (_, index) => {
    const start = index * 4;
    const parts = galleryParts.slice(start, start + 4);
    return { id: `${start + 1}-${start + parts.length}`, parts };
  },
);

export function findPart(id: string): GalleryPart | undefined {
  return galleryParts.find((part) => part.id === id);
}

export function findCase(label: string): { part: GalleryPart; entry: GalleryCase } | undefined {
  for (const part of galleryParts) {
    const entry = part.cases.find((candidate) => candidate.label === label);
    if (entry !== undefined) return { part, entry };
  }
  return undefined;
}

export function inlineCases(part: GalleryPart): readonly GalleryCase[] {
  return part.cases.filter((entry) => !entry.portal);
}

export function portalCases(part: GalleryPart): readonly GalleryCase[] {
  return part.cases.filter((entry) => entry.portal);
}

/** The shared part list every batch must show. Batch 1 and batch 2 cover all of these. */
export const SHARED_PART_IDS = [
  'button-primary',
  'button-secondary',
  'button-ghost',
  'button-icon',
  'chip-remove',
  'chip',
  'tag',
  'tooltip',
  'notice',
  'tabs',
  'radio',
  'switch',
  'menu',
  'value-field',
  'text-field',
  'settings-row',
  'send-button',
  'composer',
  'file-chip',
  'file-drop',
  'dialog',
  'alert',
  'confirm-delete',
  'confirm-range',
  'toast',
  'bottom-sheet',
  'progress',
  'skeleton',
  'empty-state',
  'error-state',
  'sidebar-item',
  'top-bar-item',
  'top-bar-status',
  'stage-indicator',
  'card',
  'reorder-list',
  'playback-controls',
  'video-preview',
  'result-card',
  'scroll-pane',
] as const;

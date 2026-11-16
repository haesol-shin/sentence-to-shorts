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
  /** The state row this case shows from the approved matrix. */
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
} as const;

const SPECS: readonly PartSpec[] = [
  {
    id: 'button-primary',
    batch: 1,
    title: '주 단추',
    description: '한 번 실행하는 대표 동작이다. 로딩은 글자를 지우지 않고 진행 표시만 더한다.',
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
    description: '아이콘만 있는 단추다. 보이는 크기와 누를 영역이 모두 44다.',
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
    description: '받는 중과 실패를 같은 칩에서 보인다. 지우기 x는 닫기 부품을 그대로 쓴다.',
    matrixPart: 'chip.surface',
    matrixParts: ['chip.surface', 'chip.remove'],
    notApplicable: MATRIX_SKIP.chipSurface,
    cases: [
      { state: 'default', slug: 'default', width: 420 },
      { state: 'loading', slug: 'loading', width: 420 },
      { state: 'error', slug: 'error', width: 420 },
      { state: 'focus-visible', slug: 'focus-visible', width: 420 },
    ],
  },
  {
    id: 'tag',
    batch: 1,
    title: '꼬리표',
    description: '뜻은 아이콘 색으로만 보인다. 회색 바탕의 글자는 foreground를 지킨다.',
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
    ],
  },
  {
    id: 'radio',
    batch: 1,
    title: '단일 선택 그룹',
    description: '여러 값 중 하나를 고른다. 고른 항목은 테두리와 안쪽 점으로 보인다.',
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
    description: '켜짐은 회색 바탕과 굵은 글자다. 손잡이 대신 단추 모양을 쓴다.',
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
    description: '행은 조작이 아니고 안의 조작이 상태를 가진다. 안 되는 설정은 흐린 조작과 곧 지원 꼬리표로 보인다.',
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
];

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

export const galleryRanges: readonly { id: string; parts: readonly GalleryPart[] }[] = [
  { id: '1-4', parts: galleryParts.slice(0, 4) },
  { id: '5-8', parts: galleryParts.slice(4, 8) },
  { id: '9-12', parts: galleryParts.slice(8, 12) },
  { id: '13-16', parts: galleryParts.slice(12, 16) },
];

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

/** The shared part list every batch must show. Batch 1 covers all of these. */
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
] as const;

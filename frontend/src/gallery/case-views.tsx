import { useEffect, useRef, type ReactElement, type ReactNode } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  Clapperboard,
  FileText,
  Info,
  Library,
  Settings,
} from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { BottomSheet, BottomSheetClose } from '@/components/BottomSheet/BottomSheet';
import { Card } from '@/components/Card/Card';
import { Chip } from '@/components/Chip/Chip';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Composer } from '@/components/Composer/Composer';
import { ConfirmDialog } from '@/components/ConfirmDialog/ConfirmDialog';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { EmptyState } from '@/components/EmptyState/EmptyState';
import { FileChip } from '@/components/FileChip/FileChip';
import { FileDropZone } from '@/components/FileDropZone/FileDropZone';
import { IconButton } from '@/components/IconButton/IconButton';
import { MenuButton, type MenuItemSpec } from '@/components/MenuButton/MenuButton';
import { Notice, type NoticeTone } from '@/components/Notice/Notice';
import { PlaybackControls } from '@/components/PlaybackControls/PlaybackControls';
import { Progress } from '@/components/Progress/Progress';
import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { RangeDialog } from '@/components/RangeDialog/RangeDialog';
import { ReorderList } from '@/components/ReorderList/ReorderList';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { SendButton } from '@/components/SendButton/SendButton';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { SidebarItem } from '@/components/SidebarItem/SidebarItem';
import { Skeleton } from '@/components/Skeleton/Skeleton';
import { StageIndicator } from '@/components/StageIndicator/StageIndicator';
import { Switch } from '@/components/Switch/Switch';
import { Tabs } from '@/components/Tabs/Tabs';
import { Tag, type TagVariant } from '@/components/Tag/Tag';
import { TextField } from '@/components/TextField/TextField';
import { Toast } from '@/components/Toast/Toast';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { TopBarItem } from '@/components/TopBarItem/TopBarItem';
import { TopBarStatus } from '@/components/TopBarStatus/TopBarStatus';
import { ValueField, type ValueFieldItem } from '@/components/ValueField/ValueField';
import { VideoPreview } from '@/components/VideoPreview/VideoPreview';
import { GalleryToast } from './gallery-toast';
import type { GalleryCase } from './items';

const SOON_TAG = (
  <Tag variant="neutral" icon={<Info aria-hidden="true" />}>
    곧 지원
  </Tag>
);

const TAB_ITEMS = [
  { value: 'script', label: '대본' },
  { value: 'caption', label: '자막' },
  { value: 'voice', label: '목소리' },
];

const LATIN_TABS = [
  { value: 'bgm', label: 'BGM' },
  { value: 'api', label: 'API key' },
  { value: 'mix', label: '믹스' },
];

const RADIO_OPTIONS = [
  { value: 'vertical', label: '세로' },
  { value: 'square', label: '정사각' },
  { value: 'wide', label: '가로' },
];

const VOICES: readonly ValueFieldItem[] = [
  { value: 'bright', label: '밝은 목소리' },
  { value: 'calm', label: '차분한 목소리' },
  { value: 'low', label: '낮은 목소리' },
  { value: 'robot', label: '로봇 목소리', unavailable: true, tag: SOON_TAG },
];

const TIGHT_VOICES: readonly ValueFieldItem[] = [
  ...VOICES.slice(0, 3),
  { value: 'warm', label: '따뜻한 목소리' },
  { value: 'clear', label: '또렷한 목소리' },
  { value: 'soft', label: '부드러운 목소리' },
  { value: 'strong', label: '힘 있는 목소리' },
  { value: 'whisper', label: '속삭이는 목소리' },
  { value: 'fast', label: '빠른 목소리' },
  { value: 'slow', label: '느린 목소리' },
  { value: 'mid', label: '중간 목소리' },
  { value: 'deep', label: '아주 낮은 목소리' },
  { value: 'high', label: '아주 높은 목소리' },
  { value: 'robot', label: '로봇 목소리', unavailable: true, tag: SOON_TAG },
];

function menuItems(slug: string): readonly MenuItemSpec[] {
  if (slug === 'open-long') {
    return [
      { value: 'upload', label: '참고 영상 올리기' },
      ...Array.from({ length: 18 }, (_, index) => ({
        value: `extra-${index + 1}`,
        label: `추가 파일 ${index + 1}`,
      })),
      { value: 'text', label: '글 파일 올리기 (.md, .txt)' },
      { value: 'image', label: '이미지 올리기', unavailable: true, tag: SOON_TAG },
    ];
  }
  const selected = slug === 'open' || slug === 'item-selected';
  return [
    { value: 'upload', label: '참고 영상 올리기' },
    { value: 'link', label: '영상 링크 붙여넣기', disabled: slug === 'item-disabled' },
    { value: 'bgm', label: 'BGM 올리기', selected },
    { value: 'image', label: '이미지 올리기', unavailable: true, tag: SOON_TAG },
    { value: 'text', label: '글 파일 올리기 (.md, .txt)' },
  ];
}

function forceItem(slug: string): { value: string; state: string[] } | undefined {
  switch (slug) {
    case 'item-hover':
      return { value: 'upload', state: ['hover'] };
    case 'item-pressed':
      return { value: 'upload', state: ['pressed'] };
    case 'item-selected':
      return { value: 'bgm', state: ['selected'] };
    case 'item-disabled':
      return { value: 'link', state: ['disabled'] };
    case 'item-unavailable':
      return { value: 'image', state: ['unavailable'] };
    case 'item-focus-visible':
      return { value: 'upload', state: ['focus-visible'] };
    default:
      return undefined;
  }
}

const NOTICE_COPY: Record<'neutral' | 'warning' | 'error' | 'long', { tone: NoticeTone; title: string; body: string }> = {
  neutral: {
    tone: 'neutral',
    title: '바뀐 값을 저장했어요',
    body: '이 영상에서만 쓰는 값이에요.',
  },
  warning: {
    tone: 'warning',
    title: '목소리를 아직 만들지 않았어요',
    body: '미리보기는 목소리를 만든 뒤에 들을 수 있어요.',
  },
  error: {
    tone: 'error',
    title: '영상 링크를 받지 못했어요',
    body: '링크가 공개 상태인지 확인하고 다시 붙여넣어 주세요.',
  },
  long: {
    tone: 'neutral',
    title: '이 기기에만 저장했어요',
    body: '편집하는 동안 바뀐 값은 이\u00A0기기에만 남아요. 다른 기기에서 이어서 편집하려면 같은 계정으로 로그인해 주세요.',
  },
};

const TAG_COPY: Record<string, { variant: TagVariant; label: string }> = {
  neutral: { variant: 'neutral', label: '새 소식' },
  soon: { variant: 'neutral', label: '곧 지원' },
  new: { variant: 'new', label: '새것' },
  warning: { variant: 'warning', label: '주의' },
  error: { variant: 'error', label: '오류' },
};

function tagIcon(variant: TagVariant): ReactNode {
  if (variant === 'new') return undefined;
  if (variant === 'warning') return <AlertTriangle aria-hidden="true" />;
  if (variant === 'error') return <AlertCircle aria-hidden="true" />;
  return <Info aria-hidden="true" />;
}

function menuTrigger(state?: string): ReactElement {
  return (
    <Button variant="trigger" forceState={state} iconEnd={<ChevronDown aria-hidden="true" />}>
      파일 넣기
    </Button>
  );
}

const COMPOSER_LONG = [
  '게임 비유로 바꿔 줘.',
  '차분한 픽셀 그림체로.',
  '낮은 목소리로 읽어 줘.',
  '편의점 앞에서 시작해 줘.',
  '재고를 세는 손을 보여 줘.',
  '계산대 너머로 웃어 줘.',
  '게임 점수판을 보여 줘.',
  '밝은 거리로 끝내 줘.',
  '자막은 짧게 유지해 줘.',
  '효과음은 넣지 말아 줘.',
  '전체 길이는 1분 안으로.',
  '다음 편을 예고해 줘.',
].join('\n');

const SHEET_VOICES = [
  { value: 'bright', label: '밝은 목소리' },
  { value: 'calm', label: '차분한 목소리' },
  { value: 'low', label: '낮은 목소리' },
  { value: 'warm', label: '따뜻한 목소리' },
];

const SHEET_LONG_VOICES = [
  ...SHEET_VOICES,
  { value: 'clear', label: '또렷한 목소리' },
  { value: 'soft', label: '부드러운 목소리' },
  { value: 'strong', label: '힘 있는 목소리' },
  { value: 'whisper', label: '속삭이는 목소리' },
  { value: 'fast', label: '빠른 목소리' },
  { value: 'slow', label: '느린 목소리' },
  { value: 'mid', label: '중간 목소리' },
  { value: 'deep', label: '아주 낮은 목소리' },
  { value: 'high', label: '아주 높은 목소리' },
  { value: 'bright-narration', label: '밝은 내레이션' },
  { value: 'calm-narration', label: '차분한 내레이션' },
  { value: 'deep-narration', label: '낮은 내레이션' },
];

const DIALOG_LONG_LINES = [
  '장면 1의 대사를 새로 씀',
  '장면 1의 목소리를 다시 만듦',
  '장면 1의 그림을 다시 그림',
  '장면 2의 대사를 새로 씀',
  '장면 2의 목소리를 다시 만듦',
  '장면 2의 그림을 다시 그림',
  '장면 3의 대사를 새로 씀',
  '장면 3의 목소리를 다시 만듦',
  '장면 3의 그림을 다시 그림',
  '장면 4의 대사를 새로 씀',
  '장면 4의 목소리를 다시 만듦',
  '장면 4의 그림을 다시 그림',
  '장면 5의 대사를 새로 씀',
  '장면 5의 목소리를 다시 만듦',
  '장면 5의 그림을 다시 그림',
  '장면 6의 대사를 새로 씀',
  '장면 6의 목소리를 다시 만듦',
  '장면 6의 그림을 다시 그림',
  '전체 자막을 다시 맞춤',
  '완성 영상을 다시 렌더함',
];

const RANGE_CHANGES = [
  { label: '분위기', before: '차분함', after: '유쾌함' },
  { label: '장면 수', before: '4개', after: '5개' },
];

const RANGE_SCOPE = [
  '대본을 처음부터 다시 씀',
  '장면 1, 2의 목소리와 렌더를 다시 만듦',
  '바뀌지 않은 장면 3, 4의 파일은 그대로 둠',
];

const STAGES = [
  { value: 'concept', label: '컨셉' },
  { value: 'script', label: '대본' },
  { value: 'edit', label: '편집' },
  { value: 'export', label: '내보내기' },
];

const REORDER_ITEMS = [
  { id: 'scene-1', label: '편의점 앞' },
  { id: 'scene-2', label: '재고 세기' },
  { id: 'scene-3', label: '점수판' },
];

const TOP_BAR_MENU: readonly MenuItemSpec[] = [
  { value: 'rename', label: '이름 바꾸기' },
  { value: 'settings', label: '영상 설정' },
  { value: 'copy', label: '영상 복제' },
];

const STATUS_DETAIL = (
  <>
    <span>마지막 저장: 2분 전</span>
    <span>저장하지 못한 값: 목소리, 배경 음악</span>
  </>
);

const STATUS_ACTIONS = (
  <>
    <Button variant="secondary">나중에</Button>
    <Button>다시 시도</Button>
  </>
);

const DIALOG_ACTIONS = (
  <>
    <DialogClose render={<Button variant="secondary">취소</Button>} />
    <DialogClose render={<Button>확인</Button>} />
  </>
);

const SCROLL_PARAGRAPHS = [
  '장면 1. 편의점 앞에서 주인공이 재고 목록을 접어 든다. 오늘의 목표를 차분하게 말한다.',
  '장면 2. 진열대를 한 칸씩 살피며 남은 수량을 센다. 계산대 너머로 손님이 지나간다.',
  '장면 3. 점수판에 오늘의 기록을 적는다. 숫자가 하나씩 올라가고 표정이 조금 밝아진다.',
  '장면 4. 냉장고 문을 닫고 다음 할 일을 정한다. 목소리가 조금 빨라진다.',
  '장면 5. 창밖으로 해가 진다. 가게 안 조명이 하나씩 켜진다.',
  '장면 6. 마지막 손님에게 인사를 건넨다. 문이 닫히고 안내 음악이 작게 흐른다.',
  '장면 7. 오늘 남은 일을 메모에 적는다. 내일 확인할 항목 세 가지를 표시한다.',
  '장면 8. 불을 끄고 가게를 나선다. 화면이 천천히 멀어진다.',
  '장면 9. 다음 날 아침, 같은 자리에서 문을 연다. 간판이 잠깐 깜빡인다.',
  '장면 10. 새 재고 상자를 풀어 놓는다. 목록과 실제 수량을 하나씩 맞춘다.',
  '장면 11. 손님이 오래 머문 자리를 정리한다. 바닥의 표시를 다시 붙인다.',
  '장면 12. 계산대 옆에 안내 문구를 세운다. 글자가 잘 보이는지 확인한다.',
  '장면 13. 점심때 손님이 몰린다. 줄이 길어지지 않게 동선을 바꾼다.',
  '장면 14. 잠깐 쉬며 오늘의 매출을 확인한다. 숫자를 메모에 옮긴다.',
  '장면 15. 오후에는 새 진열을 시험한다. 손님 반응을 보고 자리를 고친다.',
  '장면 16. 문을 닫기 전에 내일 쓸 물건을 챙긴다. 목록의 마지막 칸을 지운다.',
];

/** One home for the result card title: the visible heading also names the window. */
const RESULT_TITLE = '영상';
const RESULT_TITLE_ID = 'gallery-result-card-title';

function ScrollPaneCase({ atEnd, short }: { atEnd: boolean; short: boolean }) {
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!atEnd) return undefined;
    const element = viewport.current;
    if (element === null) return undefined;
    let stopped = false;
    const toEnd = () => {
      if (!stopped) element.scrollTop = element.scrollHeight;
    };
    toEnd();
    void element.ownerDocument.fonts.ready.then(toEnd);
    return () => {
      stopped = true;
    };
  }, [atEnd]);
  const paragraphs = short ? SCROLL_PARAGRAPHS.slice(0, 1) : SCROLL_PARAGRAPHS;
  return (
    <ScrollPane ref={viewport} label="대본" className="demo-scroll-pane">
      {paragraphs.map((paragraph) => (
        <p className="demo-scroll-pane__line" key={paragraph}>
          {paragraph}
        </p>
      ))}
    </ScrollPane>
  );
}


/** One case of a part. The label is drawn here so every screenshot carries it. */
export function renderCase(partId: string, entry: GalleryCase): ReactNode {
  const state = entry.state;

  switch (partId) {
    case 'button-primary':
      return (
        <Button
          variant="primary"
          forceState={state}
          running={state === 'loading'}
          stopLabel="만들기 멈추기"
        >
          영상 만들기
        </Button>
      );
    case 'button-secondary':
      return (
        <Button variant="secondary" forceState={state}>
          미리 보기
        </Button>
      );
    case 'button-ghost':
      return (
        <Button variant="ghost" size="sm" forceState={state}>
          모두 지우기
        </Button>
      );
    case 'button-icon':
      return (
        <IconButton label="설정" forceState={state} selected={state === 'selected'}>
          <Settings aria-hidden="true" />
        </IconButton>
      );
    case 'chip-remove':
      return (
        <div className="demo-row">
          <CloseButton label="창 닫기" size="md" forceState={state} />
          <CloseButton label="파일 지우기" size="sm" forceState={state} />
        </div>
      );
    case 'chip': {
      const element = entry.slug.startsWith('element');
      const noLead = entry.slug.startsWith('no-lead');
      const chipState = state === 'loading' || state === 'error' ? state : 'default';
      return (
        <Chip
          state={chipState}
          forceState={state}
          lead={noLead || element ? undefined : <FileText aria-hidden="true" />}
          remove={<CloseButton label="파일 지우기" size="sm" />}
        >
          {element ? <span>대본_최종_수정본.md</span> : '대본_최종_수정본.md'}
        </Chip>
      );
    }
    case 'tag': {
      const copy = TAG_COPY[entry.slug];
      return (
        <Tag variant={copy.variant} icon={tagIcon(copy.variant)}>
          {copy.label}
        </Tag>
      );
    }
    case 'tooltip':
      return (
        <Tooltip
          forceOpen={entry.slug === 'trigger' ? false : true}
          content={
            entry.slug === 'long'
              ? '아직 지원하지 않아요. 다음 단계에서 파일을 올릴 수 있어요.'
              : '곧 지원하는 기능이에요.'
          }
        >
          <IconButton label="이유 보기">
            <Info aria-hidden="true" />
          </IconButton>
        </Tooltip>
      );
    case 'notice': {
      const copy = NOTICE_COPY[entry.slug as keyof typeof NOTICE_COPY] ?? NOTICE_COPY.neutral;
      return (
        <Notice tone={copy.tone} title={copy.title}>
          {copy.body}
        </Notice>
      );
    }
    case 'tabs': {
      const latin = entry.slug.startsWith('latin');
      const items = (latin ? LATIN_TABS : TAB_ITEMS).map((item, index) =>
        index === 0 && state === 'disabled' ? { ...item, disabled: true } : item,
      );
      const defaultValue = latin
        ? entry.slug === 'latin-selected'
          ? 'bgm'
          : null
        : state === 'selected'
          ? 'script'
          : null;
      return (
        <Tabs label="영상 값" items={items} defaultValue={defaultValue} forceState={state} />
      );
    }
    case 'radio':
      return (
        <RadioGroup
          label="화면 비율"
          options={RADIO_OPTIONS.map((option, index) =>
            index === 0 && state === 'disabled' ? { ...option, disabled: true } : option,
          )}
          defaultValue={state === 'selected' ? 'vertical' : undefined}
          forceState={state}
        />
      );
    case 'switch': {
      const children = entry.slug === 'label-element' ? <span>자동 저장</span> : '자동 저장';
      return (
        <Switch
          label="자동 저장"
          defaultChecked={state === 'selected'}
          forceState={state}
          disabled={state === 'disabled'}
        >
          {children}
        </Switch>
      );
    }
    case 'menu': {
      const forced = forceItem(entry.slug);
      const isOpen = entry.portal;
      return (
        <MenuButton
          trigger={menuTrigger(isOpen ? undefined : state)}
          label="파일 넣기"
          heading="올릴 파일"
          items={menuItems(entry.slug)}
          defaultOpen={isOpen ? true : undefined}
          forceItemValue={forced?.value}
          forceItemState={forced?.state}
        />
      );
    }
    case 'value-field': {
      const isOpen = entry.slug.startsWith('open');
      const tight = entry.slug === 'open-tight';
      return (
        <ValueField
          label="목소리"
          items={tight ? TIGHT_VOICES : VOICES}
          placeholder="목소리 고르기"
          defaultValue={isOpen || entry.slug === 'hover' || entry.slug === 'focus-visible' || entry.slug === 'disabled' ? 'calm' : undefined}
          forceState={isOpen ? undefined : state}
          defaultOpen={isOpen ? true : undefined}
          disabled={state === 'disabled'}
        />
      );
    }
    case 'text-field': {
      const filled = entry.slug === 'filled';
      const errored = entry.slug === 'error';
      return (
        <TextField
          label="API key"
          placeholder="API key를 붙여넣어 주세요"
          defaultValue={filled || errored ? 'sk-synthetic-0000-0000' : undefined}
          error={errored ? 'API key를 찾을 수 없어요.' : undefined}
          forceState={state}
          disabled={state === 'disabled'}
        />
      );
    }
    case 'settings-row': {
      if (entry.slug === 'field') {
        return (
          <SettingsRow
            label="목소리"
            description="이 영상에서 쓸 목소리를 골라요."
            control={
              <div className="demo-control-field">
                <ValueField label="목소리" items={VOICES} defaultValue="calm" />
              </div>
            }
          />
        );
      }
      if (entry.slug === 'unavailable') {
        return (
          <SettingsRow
            label="배경 음악"
            description="장면마다 다른 음악을 붙여요."
            control={<Switch label="배경 음악" disabled />}
            note={
              <>
                {SOON_TAG}
                <span>다음 단계에서 열려요.</span>
              </>
            }
          />
        );
      }
      return (
        <SettingsRow
          label="자동 저장"
          description="편집하는 동안 바뀐 값을 저장해요."
          control={<Switch label="자동 저장" defaultChecked={entry.slug === 'on'} />}
        />
      );
    }
    case 'send-button':
      return <SendButton label="보내기" stopLabel="멈추기" forceState={state} loading={state === 'loading'} />;
    case 'composer': {
      const long = entry.slug === 'long';
      return (
        <Composer
          label="메시지 입력"
          stopLabel="멈추기"
          attachLabel="파일 넣기"
          placeholder={entry.slug === 'drop' ? '여기에 놓으면 올라가요' : '어떤 영상을 만들까요?'}
          defaultValue={long ? COMPOSER_LONG : entry.slug === 'filled' ? '차분한 다큐멘터리로 만들어 줘.' : undefined}
          dropActive={entry.slug === 'drop'}
          disabled={state === 'disabled'}
          forceState={state === 'focus-visible' ? 'focus-visible' : undefined}
          chips={
            entry.slug === 'chips' ? (
              <>
                <Button variant="ghost" size="sm" className="composer-chip">
                  한국어
                </Button>
                <Button variant="ghost" size="sm" className="composer-chip">
                  1분
                </Button>
              </>
            ) : undefined
          }
          attachments={
            entry.slug === 'attachments' ? (
              <FileChip
                name="참고_영상.mp4"
                detail="영상 · 0:12"
                remove={<CloseButton label="파일 지우기" size="sm" />}
              />
            ) : undefined
          }
        />
      );
    }
    case 'file-chip': {
      const errored = state === 'error';
      return (
        <FileChip
          name={state === 'loading' ? 'BGM_잔잔한.mp3' : '참고_영상.mp4'}
          detail={
            state === 'loading'
              ? 'BGM'
              : errored
                ? entry.slug === 'error-retry'
                  ? '형식이 맞지 않아요'
                  : '올리지 못했어요'
                : '영상 · 0:12'
          }
          state={state === 'loading' || errored ? state : 'default'}
          progress={0.45}
          forceState={state}
          remove={<CloseButton label="파일 지우기" size="sm" />}
          retry={
            errored ? (
              <Button variant="ghost" size="sm">
                다시
              </Button>
            ) : undefined
          }
        />
      );
    }
    case 'file-drop':
      return entry.slug === 'container' ? (
        <div className="demo-drop-container">
          <FileDropZone
            scope="container"
            open
            label="여기에 놓으면 올라가요"
            accept="참고 영상, BGM, 글 파일(.md, .txt)"
          />
        </div>
      ) : (
        <FileDropZone
          open
          label="여기에 놓으면 올라가요"
          accept={
            entry.slug === 'long'
              ? '참고 영상, BGM, 목소리 파일, 글 파일(.md, .txt)을 받아요'
              : '참고 영상, BGM, 글 파일(.md, .txt)'
          }
        />
      );
    case 'dialog':
      return entry.slug === 'long' ? (
        <Dialog
          defaultOpen
          title="다시 만들기 전에 확인해 주세요"
          description="고친 내용이 여러 장면에 걸쳐 있어요. 적용하면 아래 범위가 새로 만들어져요."
          actions={DIALOG_ACTIONS}
        >
          <Notice tone="warning" title="바뀌지 않은 장면은 그대로 둬요">
            장면 3과 4의 파일은 다시 만들지 않아요.
          </Notice>
          <ul className="demo-dialog-lines">
            {DIALOG_LONG_LINES.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Dialog>
      ) : (
        <Dialog
          defaultOpen
          title="이 영상을 만들까요?"
          description="만들면 편집 화면으로 넘어가요. 만드는 동안에도 다른 값을 고칠 수 있어요."
          actions={DIALOG_ACTIONS}
        />
      );
    case 'alert':
      return entry.slug === 'error' ? (
        <ConfirmDialog
          defaultOpen
          tone="danger"
          icon={<AlertCircle />}
          title="영상을 만들지 못했어요"
          confirmLabel="확인"
          cancelLabel={null}
        >
          연결을 확인한 뒤 다시 시도해 주세요. 만들던 내용은 저장돼 있어요.
        </ConfirmDialog>
      ) : (
        <ConfirmDialog
          defaultOpen
          tone="neutral"
          title="이 장면을 다시 만들까요?"
          confirmLabel="다시 만들기"
        >
          장면 3의 대사와 목소리만 새로 만들어요.
        </ConfirmDialog>
      );
    case 'confirm-delete':
      return (
        <ConfirmDialog
          defaultOpen
          title="파일을 지울까요?"
          confirmLabel="지우기"
          icon={<AlertCircle />}
        >
          지운 파일은 되돌릴 수 없어요. 다시 올리려면 파일을 새로 골라야 해요.
        </ConfirmDialog>
      );
    case 'confirm-range':
      return (
        <RangeDialog
          defaultOpen
          intro="여러 장면이 바뀌어서 적용 전에 확인해요."
          changes={RANGE_CHANGES}
          scope={RANGE_SCOPE}
          confirmLabel="적용"
        />
      );
    case 'toast':
      return entry.slug === 'action' ? (
        <GalleryToast open />
      ) : (
        <Toast open>
          {entry.slug === 'long'
            ? '장면 3을 다시 만들었어요. 목소리와 렌더를 새로 만들었어요.'
            : '대본을 저장했어요'}
        </Toast>
      );
    case 'bottom-sheet':
      return (
        <BottomSheet
          defaultOpen
          title="목소리 고르기"
          description={
            entry.slug === 'long'
              ? '이 영상에서 쓸 목소리를 골라요. 고른 목소리는 모든 장면에 적용돼요.'
              : '이 영상에서 쓸 목소리를 골라요.'
          }
          actions={
            <>
              <BottomSheetClose render={<Button variant="secondary">취소</Button>} />
              <Button>적용</Button>
            </>
          }
        >
          <RadioGroup
            label="목소리"
            className={entry.slug === 'long' ? 'demo-sheet-voices' : undefined}
            options={entry.slug === 'long' ? SHEET_LONG_VOICES : SHEET_VOICES}
            defaultValue="calm"
          />
        </BottomSheet>
      );
    case 'progress':
      if (entry.slug === 'bar') return <Progress value={40} labelText="만드는 중" />;
      if (entry.slug === 'complete') return <Progress value={100} label="영상 만들기" />;
      if (entry.slug === 'indeterminate') return <Progress value={null} label="만드는 중" />;
      if (entry.slug === 'count') {
        return <Progress value={3} max={5} label="영상 만드는 중" valueText="3 / 5" />;
      }
      return <Progress value={40} label="장면 3개 만드는 중" />;
    case 'skeleton':
      return <Skeleton shape={entry.slug === 'text' ? 'text' : (entry.slug as 'thumb' | 'script' | 'media')} />;
    case 'empty-state':
      return entry.slug === 'long' ? (
        <EmptyState
          title="아직 이 영상에 장면이 없어요"
          actions={<Button>장면 만들기</Button>}
        >
          대본을 확인하면 장면 그림과 목소리를 만들 수 있어요. 편집 화면에서 장면을 더할 수도 있어요.
        </EmptyState>
      ) : (
        <EmptyState
          title="아직 만든 영상이 없어요"
          actions={<Button>새 영상 만들기</Button>}
        >
          문장 하나로 첫 영상을 만들 수 있어요.
        </EmptyState>
      );
    case 'error-state':
      return (
        <EmptyState
          tone="error"
          icon={<AlertCircle />}
          title={entry.slug === 'long' ? '영상을 만들지 못했어요' : '영상 링크를 받지 못했어요'}
          actions={
            <>
              <Button>다시 시도</Button>
              <Button variant="secondary">파일로 올리기</Button>
            </>
          }
        >
          {entry.slug === 'long'
            ? '연결이 끊겨서 만들던 영상을 마치지 못했어요. 만들던 내용은 저장돼 있으니 다시 시도해 주세요. 계속 실패하면 앱을 다시 열어 주세요.'
            : '링크가 공개 상태인지 확인하고 다시 붙여넣어 주세요.'}
        </EmptyState>
      );
    case 'sidebar-item':
      if (entry.portal) {
        return (
          <Tooltip content="내 영상" side="right" forceOpen>
            <SidebarItem label="내 영상">
              <Library />
            </SidebarItem>
          </Tooltip>
        );
      }
      return (
        <SidebarItem
          label="새 영상"
          selected={state === 'selected'}
          forceState={state}
        >
          <Clapperboard />
        </SidebarItem>
      );
    case 'top-bar-item':
      if (entry.portal) {
        return (
          <MenuButton
            trigger={<TopBarItem label="영상 설정" />}
            label="영상 설정"
            items={TOP_BAR_MENU}
            defaultOpen
          />
        );
      }
      return <TopBarItem label="영상 설정" forceState={state} />;
    case 'top-bar-status': {
      if (entry.slug === 'working-open') {
        return (
          <TopBarStatus
            label="영상 만드는 중 3 / 5"
            tone="working"
            title="영상 만드는 중"
            description="장면을 만드는 동안에도 다른 값을 고칠 수 있어요. 끝나면 알려 드려요."
            detail={<Progress value={3} max={5} label="장면" valueText="3 / 5" />}
            defaultOpen
          />
        );
      }
      return (
        <TopBarStatus
          label="저장 실패"
          tone="error"
          title="저장하지 못했어요"
          description="연결이 끊겨 이 기기에 저장하지 못했어요. 다시 시도하면 이어서 저장해요."
          detail={STATUS_DETAIL}
          actions={STATUS_ACTIONS}
          defaultOpen={entry.portal}
          forceState={entry.portal ? undefined : state}
        />
      );
    }
    case 'stage-indicator':
      return (
        <StageIndicator
          label="단계"
          stages={STAGES}
          current="edit"
          forceState={state}
          forceStep="script"
        />
      );
    case 'card': {
      const format = entry.variant === 'format';
      const busy = entry.slug === 'scene-busy';
      return (
        <Card
          variant={format ? 'format' : 'scene'}
          label={format ? '세로 영상' : '편의점 앞'}
          description={format ? '9:16, 1분' : undefined}
          number={format ? undefined : 3}
          duration={format ? undefined : '약 3초'}
          selected={state === 'selected'}
          disabled={state === 'disabled'}
          busy={busy}
          forceState={state}
        />
      );
    }
    case 'reorder-list':
      return (
        <ReorderList
          label="장면 순서"
          items={REORDER_ITEMS}
          forceState={state}
          forceItem="scene-2"
        />
      );
    case 'playback-controls': {
      const progressCase = entry.slug.startsWith('progress');
      return (
        <PlaybackControls
          label="재생 조절"
          labels={{ play: '재생', pause: '일시정지', seek: '재생 위치', mute: '소리 끄기', unmute: '소리 켜기' }}
          playing={entry.slug === 'playing'}
          position={progressCase ? 40 : 0}
          current={progressCase ? '0:03' : '0:00'}
          duration="약 0:07"
          disabled={state === 'disabled'}
          forceState={progressCase ? undefined : state}
          forceProgressState={entry.slug === 'progress-focus-visible' ? 'focus-visible' : undefined}
        />
      );
    }
    case 'video-preview': {
      const previewState = entry.slug as 'empty' | 'loading' | 'ready';
      const note =
        previewState === 'empty' ? '장면 그림이 아직 없어요'
          : previewState === 'loading' ? '미리보기를 준비하는 중' : undefined;
      return (
        <VideoPreview
          placeholderLabel="완성된 영상 미리보기"
          state={previewState}
          note={note}
          duration={previewState === 'ready' ? '0:07' : undefined}
        />
      );
    }
    case 'scroll-pane':
      return <ScrollPaneCase atEnd={entry.slug === 'end'} short={entry.slug === 'short'} />;
    case 'result-card':
      return (
        <Dialog
          defaultOpen
          className="demo-result-dialog"
          labelledBy={RESULT_TITLE_ID}
        >
          <div className="demo-result">
            <div className="demo-result__player">
              <VideoPreview placeholderLabel="영상 미리보기" state="ready" duration="0:23" />
              <PlaybackControls
                label="영상 재생 조절"
                labels={{ play: '재생', pause: '일시정지', seek: '재생 위치', mute: '소리 끄기', unmute: '소리 켜기' }}
                position={0}
                current="0:00"
                duration="0:23"
              />
            </div>
            <div className="demo-result__side">
              <div className="demo-result__head">
                <h2 id={RESULT_TITLE_ID} className="demo-result__title">
                  {RESULT_TITLE}
                </h2>
                <DialogClose
                  render={<CloseButton label="결과 카드 닫기" className="focus-ring--inset" />}
                />
              </div>
              <p className="demo-result__description">
                처음부터 끝까지 이어서 보고, 괜찮으면 저장해요.
              </p>
              <dl className="demo-result__facts">
                <dt>길이</dt>
                <dd>23초</dd>
                <dt>형식</dt>
                <dd>mp4, 1080×1920, 30fps</dd>
                <dt>자막</dt>
                <dd>
                  한 문장씩{' '}
                  <Button variant="ghost" size="sm" className="demo-result__inline">
                    자막 저장
                  </Button>
                </dd>
                <dt>사용량</dt>
                <dd>
                  입력 1,240, 출력 680 토큰{' '}
                  <Button variant="ghost" size="sm" className="demo-result__inline">
                    사용량 보기
                  </Button>
                </dd>
              </dl>
              <div className="demo-result__actions">
                <DialogClose render={<Button variant="secondary">편집으로</Button>} />
                <Button>mp4 저장</Button>
              </div>
            </div>
          </div>
        </Dialog>
      );
    default:
      return null;
  }
}

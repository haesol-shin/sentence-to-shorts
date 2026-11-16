import type { ReactElement, ReactNode } from 'react';
import { AlertCircle, AlertTriangle, ChevronDown, FileText, Info, Settings, Sparkles } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { Chip } from '@/components/Chip/Chip';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { IconButton } from '@/components/IconButton/IconButton';
import { MenuButton, type MenuItemSpec } from '@/components/MenuButton/MenuButton';
import { Notice, type NoticeTone } from '@/components/Notice/Notice';
import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Switch } from '@/components/Switch/Switch';
import { Tabs } from '@/components/Tabs/Tabs';
import { Tag, type TagVariant } from '@/components/Tag/Tag';
import { TextField } from '@/components/TextField/TextField';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { ValueField, type ValueFieldItem } from '@/components/ValueField/ValueField';
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
  if (variant === 'new') return <Sparkles aria-hidden="true" />;
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

/** One case of a part. The label is drawn here so every screenshot carries it. */
export function renderCase(partId: string, entry: GalleryCase): ReactNode {
  const state = entry.state;

  switch (partId) {
    case 'button-primary':
      return (
        <Button variant="primary" forceState={state}>
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
      const noLead = entry.slug.startsWith('no-lead');
      const chipState = state === 'loading' || state === 'error' ? state : 'default';
      return (
        <Chip
          state={chipState}
          forceState={state}
          lead={noLead ? undefined : <FileText aria-hidden="true" />}
          remove={<CloseButton label="파일 지우기" size="sm" />}
        >
          대본_최종_수정본.md
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
            control={
              <Switch label="배경 음악" disabled>
                꺼짐
              </Switch>
            }
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
          control={
            <Switch label="자동 저장" defaultChecked={entry.slug === 'on'}>
              {entry.slug === 'on' ? '켜짐' : '꺼짐'}
            </Switch>
          }
        />
      );
    }
    default:
      return null;
  }
}

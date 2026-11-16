import { useState } from 'react';
import { ChevronDown, Info } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { MenuButton } from '@/components/MenuButton/MenuButton';
import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { Switch } from '@/components/Switch/Switch';
import { Tabs } from '@/components/Tabs/Tabs';
import { Tag } from '@/components/Tag/Tag';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { ValueField } from '@/components/ValueField/ValueField';

const SOON = (
  <Tag variant="neutral" icon={<Info aria-hidden="true" />}>
    곧 지원
  </Tag>
);

const MENU_ITEMS = [
  { value: 'upload', label: '참고 영상 올리기' },
  { value: 'link', label: '영상 링크 붙여넣기' },
  { value: 'image', label: '이미지 올리기', unavailable: true, tag: SOON },
];

const VOICES = [
  { value: 'bright', label: '밝은 목소리' },
  { value: 'calm', label: '차분한 목소리' },
  { value: 'low', label: '낮은 목소리' },
];

/**
 * The interactive probe for the gallery tests. It is a dev-only page, never
 * part of the app entry, and uses synthetic copy only.
 */
export function ProbePage() {
  const [log, setLog] = useState('none');

  return (
    <main className="probe">
      <section className="probe__section" data-probe="tooltip">
        <h2>tooltip</h2>
        <Tooltip content="곧 지원하는 기능이에요.">
          <Button variant="secondary">이유 보기</Button>
        </Tooltip>
      </section>
      <section className="probe__section" data-probe="menu">
        <h2>메뉴</h2>
        <MenuButton
          trigger={
            <Button variant="trigger" iconEnd={<ChevronDown aria-hidden="true" />}>
              파일 넣기
            </Button>
          }
          label="파일 넣기"
          items={MENU_ITEMS}
          onSelect={(value) => setLog(`menu:${value}`)}
        />
      </section>
      <section className="probe__section" data-probe="select">
        <h2>값 칸</h2>
        <ValueField
          label="목소리"
          items={VOICES}
          placeholder="목소리 고르기"
          onValueChange={(value) => setLog(`select:${value}`)}
        />
      </section>
      <section className="probe__section" data-probe="tabs">
        <h2>탭</h2>
        <Tabs
          label="영상 값"
          items={[
            { value: 'script', label: '대본' },
            { value: 'caption', label: '자막' },
            { value: 'voice', label: '목소리' },
          ]}
          onValueChange={(value) => setLog(`tab:${value}`)}
        />
      </section>
      <section className="probe__section" data-probe="radio">
        <h2>단일 선택</h2>
        <RadioGroup
          label="화면 비율"
          options={[
            { value: 'vertical', label: '세로' },
            { value: 'square', label: '정사각' },
            { value: 'wide', label: '가로' },
          ]}
          onValueChange={(value) => setLog(`radio:${value}`)}
        />
      </section>
      <section className="probe__section" data-probe="switch">
        <h2>켜기·끄기</h2>
        <Switch label="자동 저장" onCheckedChange={(checked) => setLog(`switch:${String(checked)}`)}>
          자동 저장
        </Switch>
      </section>
      <p className="probe__log" data-probe="log">
        {log}
      </p>
    </main>
  );
}

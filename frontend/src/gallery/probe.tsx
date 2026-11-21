import { useState } from 'react';
import { ChevronDown, Info } from 'lucide-react';

import { BottomSheet, BottomSheetClose } from '@/components/BottomSheet/BottomSheet';
import { Button } from '@/components/Button/Button';
import { Card } from '@/components/Card/Card';
import { Composer } from '@/components/Composer/Composer';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { MenuButton, type MenuItemSpec } from '@/components/MenuButton/MenuButton';
import { PlaybackControls } from '@/components/PlaybackControls/PlaybackControls';
import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { ReorderList, type ReorderItem } from '@/components/ReorderList/ReorderList';
import { StageIndicator } from '@/components/StageIndicator/StageIndicator';
import { Switch } from '@/components/Switch/Switch';
import { Tabs } from '@/components/Tabs/Tabs';
import { Tag } from '@/components/Tag/Tag';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { TopBarItem } from '@/components/TopBarItem/TopBarItem';
import { TopBarStatus } from '@/components/TopBarStatus/TopBarStatus';
import { ValueField } from '@/components/ValueField/ValueField';
import { GalleryToast } from './gallery-toast';

const SOON = (
  <Tag variant="neutral" icon={<Info aria-hidden="true" />}>
    곧 지원
  </Tag>
);

const SOON_NOTE = '곧 지원 항목은 다음 단계에서 열려요.';

const MENU_ITEMS: readonly MenuItemSpec[] = [
  { value: 'upload', label: '참고 영상 올리기' },
  { value: 'link', label: '영상 링크 붙여넣기' },
  { value: 'image', label: '이미지 올리기', unavailable: true, unavailableName: '이미지 올리기 곧 지원', tag: SOON },
];

const VOICES = [
  { value: 'bright', label: '밝은 목소리' },
  { value: 'calm', label: '차분한 목소리' },
  { value: 'low', label: '낮은 목소리' },
];

const STAGES = [
  { value: 'concept', label: '컨셉' },
  { value: 'script', label: '대본' },
  { value: 'edit', label: '편집' },
  { value: 'export', label: '내보내기' },
];

const REORDER_LABELS = {
  grip: (item: string) => `순서 바꾸기: ${item}`,
  up: (item: string) => `위로 이동: ${item}`,
  down: (item: string) => `아래로 이동: ${item}`,
};

const REORDER_START: readonly ReorderItem[] = [
  { id: 'scene-1', label: '첫 장면' },
  { id: 'scene-2', label: '둘째 장면' },
  { id: 'scene-3', label: '셋째 장면' },
];

/**
 * The interactive probe for the gallery tests. It is a dev-only page, never
 * part of the app entry, and uses synthetic copy only.
 */
export function ProbePage() {
  const [log, setLog] = useState('none');
  const [stage, setStage] = useState('edit');
  const [scene, setScene] = useState('scene-1');
  const [order, setOrder] = useState<readonly ReorderItem[]>(REORDER_START);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(20);
  const [muted, setMuted] = useState(false);
  const [toastOpen, setToastOpen] = useState(false);

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
          note={SOON_NOTE}
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
      <section className="probe__section" data-probe="dialog">
        <h2>창</h2>
        <Dialog
          title="이 영상을 만들까요?"
          description="만들면 편집 화면으로 넘어가요."
          trigger={<Button>영상 만들기</Button>}
          actions={
            <>
              <DialogClose render={<Button variant="secondary">취소</Button>} />
              <DialogClose render={<Button onClick={() => setLog('dialog:confirm')}>확인</Button>} />
            </>
          }
        />
      </section>
      <section className="probe__section" data-probe="dialog-nested">
        <h2>창 안 조작</h2>
        <Dialog
          title="중첩 조작"
          description="창 안에서 메뉴, 목소리, 도움말을 연다."
          trigger={<Button>중첩 창 열기</Button>}
          actions={<DialogClose render={<Button variant="secondary">닫기</Button>} />}
        >
          <div className="probe__stack">
            <MenuButton
              trigger={
                <Button variant="trigger" iconEnd={<ChevronDown aria-hidden="true" />}>
                  파일 넣기
                </Button>
              }
              label="파일 넣기"
              items={MENU_ITEMS}
              note={SOON_NOTE}
              onSelect={(value) => setLog(`nested-menu:${value}`)}
            />
            <ValueField
              label="목소리"
              items={VOICES}
              placeholder="목소리 고르기"
              onValueChange={(value) => setLog(`nested-select:${value}`)}
            />
            <Tooltip content="창 안 도움말이에요.">
              <Button variant="secondary">이유 보기</Button>
            </Tooltip>
          </div>
        </Dialog>
      </section>
      <section className="probe__section" data-probe="sheet">
        <h2>아래 판</h2>
        <BottomSheet
          closeLabel="닫기"
          title="목소리 고르기"
          description="이 영상에서 쓸 목소리를 골라요."
          trigger={<Button variant="secondary">목소리</Button>}
          actions={<BottomSheetClose render={<Button variant="secondary">닫기</Button>} />}
        >
          <RadioGroup
            label="목소리"
            options={[
              { value: 'bright', label: '밝은 목소리' },
              { value: 'calm', label: '차분한 목소리' },
            ]}
          />
        </BottomSheet>
      </section>
      <section className="probe__section" data-probe="composer">
        <h2>입력창</h2>
        <Composer
          label="메시지 입력"
          sendLabel="보내기"
          stopLabel="멈추기"
          attachLabel="파일 넣기"
          placeholder="어떤 영상을 만들까요?"
          onSend={() => setLog('composer:send')}
        />
      </section>
      <section className="probe__section" data-probe="top-bar-item">
        <h2>상단바 항목</h2>
        <MenuButton
          trigger={<TopBarItem label="영상 설정" />}
          label="영상 설정"
          items={[
            { value: 'rename', label: '이름 바꾸기' },
            { value: 'settings', label: '영상 설정' },
          ]}
          onSelect={(value) => setLog(`top-bar:${value}`)}
        />
      </section>
      <section className="probe__section" data-probe="status">
        <h2>상단바 상태</h2>
        <TopBarStatus
          label="저장 실패"
          tone="error"
          title="저장하지 못했어요"
          description="연결이 끊겨 이 기기에 저장하지 못했어요. 다시 시도하면 이어서 저장해요."
          detail={<span>마지막 저장: 2분 전</span>}
          actions={
            <>
              <Button variant="secondary" onClick={() => setLog('status:later')}>
                나중에
              </Button>
              <Button onClick={() => setLog('status:retry')}>다시 시도</Button>
            </>
          }
        />
      </section>
      <section className="probe__section" data-probe="stage">
        <h2>단계 표시</h2>
        <StageIndicator
          label="단계"
          stages={STAGES}
          current={stage}
          onSelect={(value) => {
            setStage(value);
            setLog(`stage:${value}`);
          }}
        />
      </section>
      <section className="probe__section" data-probe="card">
        <h2>카드</h2>
        <div className="probe__stack">
          <Card
            variant="format"
            label="세로 영상"
            description="9:16, 1분"
            selected={scene === 'format'}
            onClick={() => {
              setScene('format');
              setLog('card:format');
            }}
          />
          <Card
            variant="scene"
            label="편의점 앞"
            number={3}
            duration="약 3초"
            selected={scene === 'scene'}
            onClick={() => {
              setScene('scene');
              setLog('card:scene');
            }}
          />
        </div>
      </section>
      <section className="probe__section" data-probe="reorder">
        <h2>순서 바꾸는 목록</h2>
        <ReorderList
          label="장면 순서"
          labels={REORDER_LABELS}
          items={order}
          onReorder={(next) => {
            setOrder(next);
            setLog(`order:${next.map((item) => item.id).join(',')}`);
          }}
        />
      </section>
      <section className="probe__section" data-probe="playback">
        <h2>재생 제어</h2>
        <PlaybackControls
          label="재생 조절"
          labels={{ play: '재생', pause: '일시정지', seek: '재생 위치', mute: '소리 끄기', unmute: '소리 켜기' }}
          playing={playing}
          onToggle={() => {
            const next = !playing;
            setPlaying(next);
            setLog(`play:${String(next)}`);
          }}
          position={position}
          onSeek={(value) => {
            setPosition(value);
            setLog(`seek:${value}`);
          }}
          muted={muted}
          onToggleMute={() => {
            const next = !muted;
            setMuted(next);
            setLog(`mute:${String(next)}`);
          }}
        />
      </section>
      <section className="probe__section" data-probe="toast">
        <h2>알림 열림</h2>
        <Button variant="secondary" onClick={() => setToastOpen(true)}>
          알림 열기
        </Button>
        <GalleryToast open={toastOpen} onUndo={() => setToastOpen(false)} />
      </section>
      <p className="probe__log" data-probe="log">
        {log}
      </p>
    </main>
  );
}

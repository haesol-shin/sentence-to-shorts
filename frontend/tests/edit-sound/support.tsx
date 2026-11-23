import { fireEvent, render, screen } from '@testing-library/react';

import { PlaceholderComposer } from '@/app/shell/composer';
import { HistoryButtons } from '@/app/shell/history-buttons';
import { ShellViewProvider } from '@/app/shell/shell-view';
import { createMockEditApi, type EditApi } from '@/features/edit/api';
import { EditProvider } from '@/features/edit/edit-context';
import { EditScreen } from '@/features/edit/edit-screen';
import type { VideoView } from '@/features/edit/model';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { makeView } from '../edit/fixtures';

const DIGEST = '1'.repeat(64);

/** The edit fixture with the sound and caption values filled in the way a created video has them. */
export function soundView(): VideoView {
  const view = makeView();
  view.video.settings.audio = {
    voice: { id: 'fixed_wav', revision: DIGEST },
    bgm: {
      enabled: true,
      mood: 'curious',
      entry: { id: 'curious_stage_one', revision: DIGEST },
      gain_db_x10: -120,
      ducking: true,
    },
    sfx_enabled: true,
  };
  view.video.settings.caption = {
    mode: 'sentence',
    font_id: { id: 'galmuri11', revision: DIGEST },
    position: 'bottom',
    highlight: true,
  };
  return view;
}

/** Renders the edit screen over the mock API and waits for the first scene. */
export async function renderEdit(view: VideoView = soundView(), api: EditApi = createMockEditApi(view)) {
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={api}>
        <HistoryButtons view="edit" />
        <EditScreen />
        <ShellViewProvider value="edit">
          <PlaceholderComposer label="편집 요청" placeholder="편집 요청" sendLabel="보내기" deployment="hosted" />
        </ShellViewProvider>
      </EditProvider>
    </LocaleProvider>,
  );
  await screen.findByRole('heading', { name: '장면 1' });
  return api;
}

export async function openTab(name: '소리' | '자막' | '장면') {
  fireEvent.click(await screen.findByRole('tab', { name }));
}

/** Picks one option of an open value field the way a press does: down, up, then click. */
export function pickOption(option: HTMLElement) {
  fireEvent.pointerDown(option);
  fireEvent.pointerUp(option);
  fireEvent.mouseUp(option);
  fireEvent.click(option);
}

/** The value a section shows in its tag, for the voice and the BGM track. */
export function tagOf(slot: 'voice-section' | 'bgm-section'): string {
  const section = document.querySelector<HTMLElement>(`[data-slot="${slot}"]`) as HTMLElement;
  return section.querySelector('.tag__label')?.textContent ?? '';
}

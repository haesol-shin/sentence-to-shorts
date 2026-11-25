import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import { Composer } from '@/app/shell/composer';
import {
  linkPolicy,
  validateReferenceUrl,
  type Deployment,
} from '@/features/concept/attachments';
import type { Attachment } from '@/features/concept/types';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

afterEach(cleanup);

type Submit = (attachments: Attachment[]) => void | Promise<void>;

function textFile(name: string, text: string): File {
  return new File([text], name, { type: 'text/markdown' });
}

function mediaFile(name: string, type: string): File {
  return new File(['media'], name, { type });
}

function Harness({
  onSubmit,
  initial = '한 문장',
  deployment = 'local',
  ...props
}: {
  onSubmit: Submit;
  initial?: string;
  deployment?: Deployment;
  language?: 'ko' | 'en';
  duration?: number;
  onLanguageChange?: (language: 'ko' | 'en') => void;
  onDurationChange?: (duration: number) => void;
  card?: { label: string } | null;
}) {
  const [value, setValue] = useState(initial);
  return (
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <Composer
        label="요청"
        placeholder="요청"
        sendLabel="보내기"
        value={value}
        onChange={setValue}
        onSubmit={onSubmit}
        deployment={deployment}
        {...props}
      />
    </LocaleProvider>
  );
}

function renderComposer(onSubmit: Submit): HTMLTextAreaElement {
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <Composer
        label="요청"
        placeholder="요청"
        sendLabel="보내기"
        value="한 문장"
        onChange={() => undefined}
        onSubmit={onSubmit}
        deployment="local"
      />
    </LocaleProvider>,
  );
  return screen.getByRole('textbox', { name: '요청' }) as HTMLTextAreaElement;
}

function fileInput(kind: 'reference' | 'bgm' | 'text'): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>(
    `input[type="file"][data-kind="${kind}"]`,
  );
  if (input === null) {
    throw new Error(`missing ${kind} input`);
  }
  return input;
}

function chooseFiles(kind: 'reference' | 'bgm' | 'text', files: File[]): void {
  fireEvent.change(fileInput(kind), { target: { files } });
}

function attachmentCount(): number {
  return document.querySelectorAll('[data-slot="composer-attachment"]').length;
}

test('test_10a_enter_that_settles_a_composition_does_not_send', () => {
  const onSubmit = vi.fn();
  const box = renderComposer(onSubmit);

  fireEvent.keyDown(box, { key: 'Enter', isComposing: true });
  expect(onSubmit).not.toHaveBeenCalled();
  expect(box.value).toBe('한 문장');

  fireEvent.keyDown(box, { key: 'Enter' });
  expect(onSubmit).toHaveBeenCalledTimes(1);
});

test('test_10a_shift_enter_adds_a_line_instead_of_sending', () => {
  const onSubmit = vi.fn();
  const box = renderComposer(onSubmit);

  fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });

  expect(onSubmit).not.toHaveBeenCalled();
});

test('test_10a_materials_reach_the_boundary_before_the_box_clears', async () => {
  let releaseSend: () => void = () => undefined;
  const pendingSend = new Promise<void>((resolve) => {
    releaseSend = resolve;
  });
  const calls: Attachment[][] = [];
  render(
    <Harness
      initial="원두 이야기"
      onSubmit={(attachments) => {
        calls.push(attachments);
        return pendingSend;
      }}
    />,
  );

  chooseFiles('text', [
    textFile('notes.md', '원두는 신선도가 중요하다.'),
    new File(['첫 문장을 짧게.'], 'brief.txt', { type: 'text/plain' }),
  ]);
  await waitFor(() => expect(attachmentCount()).toBe(2));

  const textbox = screen.getByRole('textbox', { name: '요청' }) as HTMLTextAreaElement;
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0]).toHaveLength(2);
  expect(calls[0][0]).toMatchObject({
    kind: 'text',
    name: 'notes.md',
    text: '원두는 신선도가 중요하다.',
  });
  expect(calls[0][1]).toMatchObject({
    kind: 'text',
    name: 'brief.txt',
    text: '첫 문장을 짧게.',
  });
  expect(textbox.value).toBe('원두 이야기');
  expect(attachmentCount()).toBe(2);

  releaseSend();
  await waitFor(() => expect(attachmentCount()).toBe(0));
  expect(textbox.value).toBe('원두 이야기');
});

test('test_10a_a_failed_send_keeps_the_text_and_materials', async () => {
  render(<Harness onSubmit={() => Promise.reject(new Error('mock_failure'))} />);

  chooseFiles('text', [textFile('notes.md', '재료')]);
  await waitFor(() => expect(attachmentCount()).toBe(1));

  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  expect(await screen.findByRole('alert')).toBeTruthy();
  expect((screen.getByRole('textbox', { name: '요청' }) as HTMLTextAreaElement).value).toBe('한 문장');
  expect(attachmentCount()).toBe(1);
  expect(screen.getAllByText(/notes\.md/)[0]).toBeTruthy();
});

test('test_10a_attachments_alone_can_be_sent_and_media_keeps_its_file', async () => {
  const calls: Attachment[][] = [];
  render(
    <Harness
      initial=""
      onSubmit={(attachments) => {
        calls.push(attachments);
      }}
    />,
  );

  const bgm = mediaFile('theme.wav', 'audio/wav');
  chooseFiles('bgm', [bgm, mediaFile('second.wav', 'audio/wav')]);
  await waitFor(() => expect(attachmentCount()).toBe(2));

  const send = screen.getByRole('button', { name: '보내기' }) as HTMLButtonElement;
  expect(send.disabled).toBe(false);
  fireEvent.click(send);

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].map((attachment) => attachment.kind)).toEqual(['bgm', 'bgm']);
  expect(calls[0][0].file).toBe(bgm);
});

test('test_10a_video_material_is_a_reference_with_its_file', async () => {
  const calls: Attachment[][] = [];
  render(
    <Harness
      initial=""
      onSubmit={(attachments) => {
        calls.push(attachments);
      }}
    />,
  );

  const video = mediaFile('sample.mp4', 'video/mp4');
  chooseFiles('reference', [video]);
  await waitFor(() => expect(attachmentCount()).toBe(1));
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0][0]).toMatchObject({ kind: 'reference', name: 'sample.mp4', state: 'ready' });
  expect(calls[0][0].file).toBe(video);
});

test('test_10a_more_than_five_files_show_a_reason_instead_of_dropping_quietly', async () => {
  render(<Harness onSubmit={() => undefined} />);

  chooseFiles(
    'text',
    Array.from({ length: 6 }, (_, index) => textFile(`note-${index + 1}.md`, `자료 ${index + 1}`)),
  );

  await waitFor(() => expect(attachmentCount()).toBe(5));
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('최대 5개');
  expect(alert.textContent).toContain('note-6.md');
});

test('test_10a_a_local_link_needs_the_warning_consent_before_it_is_attached', async () => {
  render(<Harness onSubmit={() => undefined} />);

  fireEvent.click(screen.getByRole('button', { name: '파일이나 링크 더하기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '영상 링크 붙여넣기' }));

  const attach = screen.getByRole('button', { name: '링크 첨부' }) as HTMLButtonElement;
  expect(attach.disabled).toBe(true);
  fireEvent.change(screen.getByRole('textbox', { name: '참고 영상 링크' }), {
    target: { value: 'https://www.youtube.com/watch?v=abc123' },
  });
  expect(attach.disabled).toBe(true);
  expect(attachmentCount()).toBe(0);
  // The shut button's reason is on screen, not behind a hover.
  expect(screen.getByText('위 동의에 체크하면 링크를 붙일 수 있어요.')).toBeTruthy();

  fireEvent.click(screen.getByRole('checkbox'));
  expect(attach.disabled).toBe(false);
  expect(screen.queryByText('위 동의에 체크하면 링크를 붙일 수 있어요.')).toBeNull();
  fireEvent.click(attach);

  expect(attachmentCount()).toBe(1);
  expect(screen.getAllByText(/youtube\.com/)[0]).toBeTruthy();
  expect(screen.getAllByText(/받는 중/)[0]).toBeTruthy();
});

test('test_10a_a_failed_link_send_ends_receiving_and_keeps_the_chip', async () => {
  const sent: Attachment[][] = [];
  render(
    <Harness
      onSubmit={(attachments) => {
        sent.push(attachments);
        return Promise.reject(new Error('mock_failure'));
      }}
    />,
  );

  fireEvent.click(screen.getByRole('button', { name: '파일이나 링크 더하기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '영상 링크 붙여넣기' }));
  fireEvent.change(screen.getByRole('textbox', { name: '참고 영상 링크' }), {
    target: { value: 'https://www.youtube.com/watch?v=abc123' },
  });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: '링크 첨부' }));
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  expect(sent[0][0]).toMatchObject({
    kind: 'link',
    state: 'ready',
    url: 'https://www.youtube.com/watch?v=abc123',
  });
  expect(screen.queryAllByText(/받는 중/)).toHaveLength(0);
  expect(screen.getAllByText(/받지 못했어요/)[0]).toBeTruthy();
  expect(attachmentCount()).toBe(1);
});

test('test_10a_hosted_links_and_images_are_named_as_unavailable', async () => {
  render(<Harness onSubmit={() => undefined} deployment="hosted" />);

  fireEvent.click(screen.getByRole('button', { name: '파일이나 링크 더하기' }));
  const link = screen.getByRole('menuitem', { name: '영상 링크 붙여넣기' });
  expect(link.getAttribute('aria-disabled')).toBe('true');
  fireEvent.focus(link);
  expect(screen.getByRole('tooltip').textContent).toContain('서버 호스팅');

  const image = screen.getByRole('menuitem', { name: /이미지 올리기/ });
  expect(image.getAttribute('aria-disabled')).toBe('true');
  expect(image.textContent).toContain('곧 지원');
  fireEvent.blur(link);
  fireEvent.focus(image);
  expect(screen.getByRole('tooltip').textContent).toContain('이미지 입력');
});

function pickValue(field: string, option: string): void {
  fireEvent.click(screen.getByRole('combobox', { name: field }));
  const row = screen.getByRole('option', { name: option });
  fireEvent.pointerDown(row);
  fireEvent.pointerUp(row);
  fireEvent.mouseUp(row);
  fireEvent.click(row);
}

test('test_10a_language_and_duration_are_real_input_values', async () => {
  const onLanguageChange = vi.fn();
  const onDurationChange = vi.fn();
  render(
    <Harness
      initial=""
      onSubmit={() => undefined}
      language="ko"
      duration={60}
      onLanguageChange={onLanguageChange}
      onDurationChange={onDurationChange}
    />,
  );

  pickValue('영상 언어', 'English');
  await waitFor(() => expect(onLanguageChange).toHaveBeenCalledWith('en'));
  pickValue('영상 길이', '2분');
  await waitFor(() => expect(onDurationChange).toHaveBeenCalledWith(120));
});


test('test_10a_dropping_files_highlights_the_whole_box_and_adds_every_file', async () => {
  render(<Harness onSubmit={() => undefined} />);
  const composer = document.querySelector('[data-slot="composer"]') as HTMLElement;

  fireEvent.dragOver(composer);
  expect(composer.getAttribute('data-dragging')).toBe('true');

  const first = textFile('notes.md', '하나');
  const second = textFile('brief.txt', '둘');
  fireEvent.drop(composer, { dataTransfer: { files: [first, second] } });

  expect(composer.getAttribute('data-dragging')).toBeNull();
  await waitFor(() => expect(attachmentCount()).toBe(2));
  expect(screen.getAllByText(/notes\.md/)[0]).toBeTruthy();
  expect(screen.getAllByText(/brief\.txt/)[0]).toBeTruthy();
});

test('test_10a_an_image_file_is_refused_with_a_visible_reason', async () => {
  render(<Harness onSubmit={() => undefined} />);

  fireEvent.drop(document.querySelector('[data-slot="composer"]') as HTMLElement, {
    dataTransfer: { files: [new File(['pixels'], 'photo.png', { type: 'image/png' })] },
  });

  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('지원하지 않는 파일');
  expect(attachmentCount()).toBe(0);
});

test('test_10a_a_file_picked_through_another_kinds_row_is_refused_by_name', async () => {
  render(<Harness onSubmit={() => undefined} />);

  chooseFiles('reference', [new File(['slides'], '발표자료.pdf', { type: 'application/pdf' })]);

  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toBe('발표자료.pdf: 참고 영상 파일이 아니라서 붙이지 않았어요.');
  expect(attachmentCount()).toBe(0);
});

test('test_10a_reference_link_policy_is_one_shared_rule', () => {
  expect(linkPolicy('local')).toEqual({ enabled: true, consentRequired: true });
  expect(linkPolicy('hosted')).toEqual({ enabled: false, consentRequired: false });

  expect(validateReferenceUrl('https://www.youtube.com/watch?v=abc123')).toMatchObject({
    ok: true,
    platform: 'youtube',
  });
  expect(validateReferenceUrl('https://youtu.be/abc123')).toMatchObject({ ok: true });
  expect(validateReferenceUrl('https://www.instagram.com/reel/abc123')).toMatchObject({
    ok: true,
    platform: 'instagram',
  });
  expect(validateReferenceUrl('https://vm.tiktok.com/abc123')).toMatchObject({
    ok: true,
    platform: 'tiktok',
  });
  expect(validateReferenceUrl('http://www.youtube.com/watch?v=abc123')).toEqual({
    ok: false,
    reason: 'scheme',
  });
  expect(validateReferenceUrl('HTTPS://www.youtube.com/watch?v=abc123')).toEqual({
    ok: false,
    reason: 'scheme',
  });
  expect(validateReferenceUrl('https://example.invalid/video')).toEqual({
    ok: false,
    reason: 'host',
  });
  expect(validateReferenceUrl('https://www.youtube.com.evil.invalid/watch')).toEqual({
    ok: false,
    reason: 'host',
  });
  expect(validateReferenceUrl('https://user@www.youtube.com/watch')).toEqual({
    ok: false,
    reason: 'userinfo',
  });
  expect(validateReferenceUrl('https://www.youtube.com:443/watch')).toEqual({
    ok: false,
    reason: 'port',
  });
  expect(validateReferenceUrl('')).toEqual({ ok: false, reason: 'empty' });
  expect(validateReferenceUrl(`https://youtu.be/${'a'.repeat(500)}`)).toEqual({
    ok: false,
    reason: 'length',
  });
});

test('test_10a_adding_more_files_keeps_the_earlier_materials', async () => {
  const calls: Attachment[][] = [];
  render(
    <Harness
      initial=""
      onSubmit={(attachments) => {
        calls.push(attachments);
      }}
    />,
  );

  chooseFiles('text', [textFile('notes.md', '첫 재료')]);
  await waitFor(() => expect(attachmentCount()).toBe(1));
  chooseFiles('text', [textFile('brief.txt', '둘째 재료')]);
  await waitFor(() => expect(attachmentCount()).toBe(2));

  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].map((attachment) => [attachment.name, attachment.text])).toEqual([
    ['notes.md', '첫 재료'],
    ['brief.txt', '둘째 재료'],
  ]);
});

test('test_10a_files_dropped_while_sending_stay_after_the_send_finishes', async () => {
  let releaseSend: () => void = () => undefined;
  const pendingSend = new Promise<void>((resolve) => {
    releaseSend = resolve;
  });
  const calls: Attachment[][] = [];
  render(
    <Harness
      initial="원두 이야기"
      onSubmit={(attachments) => {
        calls.push(attachments);
        return pendingSend;
      }}
    />,
  );
  const composer = document.querySelector('[data-slot="composer"]') as HTMLElement;

  chooseFiles('text', [textFile('sent.md', '보낸 재료')]);
  await waitFor(() => expect(attachmentCount()).toBe(1));
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => expect(calls).toHaveLength(1));

  fireEvent.drop(composer, { dataTransfer: { files: [textFile('late.md', '늦게 놓은 재료')] } });
  await waitFor(() => expect(attachmentCount()).toBe(2));

  releaseSend();
  await waitFor(() => expect(screen.queryByText('sent.md')).toBeNull());
  expect(calls[0].map((attachment) => attachment.name)).toEqual(['sent.md']);
  expect(attachmentCount()).toBe(1);
  expect(screen.getAllByText(/late\.md/)[0]).toBeTruthy();
});

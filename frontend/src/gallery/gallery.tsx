import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from 'react';

import './gallery.css';
import {
  findCase,
  findPart,
  galleryParts,
  galleryRanges,
  inlineCases,
  portalCases,
  type GalleryCase,
  type GalleryPart,
} from './items';
import { renderCase } from './case-views';
import { ProbePage } from './probe';

const WIDTHS = [390, 1920] as const;
const BATCHES = [1, 2, 3] as const;

/**
 * Every part lists its states top to bottom in this one order, so the same state sits in the
 * same place in every part and at both widths.
 */
const STATE_ORDER = [
  'default',
  'hover',
  'pressed',
  'selected',
  'open',
  'disabled',
  'unavailable',
  'loading',
  'error',
  'focus-visible',
] as const;

function stateRank(state: string): number {
  const index = (STATE_ORDER as readonly string[]).indexOf(state);
  return index === -1 ? STATE_ORDER.length : index;
}

/**
 * The display position of each inline case. A part whose variants each carry several states
 * (the card) gets one block per variant. Otherwise the first case of each state follows the
 * state order, and the other cases (extra content, long text) follow in label order. Only the
 * CSS `order` changes; the DOM keeps label order.
 */
function displayOrder(part: GalleryPart): Map<string, number> {
  const cases = inlineCases(part);
  const order = new Map<string, number>();
  const variants = [...new Set(cases.map((entry) => entry.variant ?? ''))];
  const statesPerVariant = variants.map(
    (variant) =>
      new Set(cases.filter((entry) => (entry.variant ?? '') === variant).map((entry) => entry.state)).size,
  );
  if (variants.length > 1 && statesPerVariant.every((count) => count > 1)) {
    for (const entry of cases) {
      order.set(entry.label, variants.indexOf(entry.variant ?? '') * 100 + stateRank(entry.state));
    }
    return order;
  }
  const seen = new Set<string>();
  cases.forEach((entry, index) => {
    if (seen.has(entry.state)) {
      order.set(entry.label, 100 + index);
      return;
    }
    seen.add(entry.state);
    order.set(entry.label, stateRank(entry.state));
  });
  return order;
}

function CaseBody({ part, entry, order }: { part: GalleryPart; entry: GalleryCase; order?: number }) {
  const style = { '--case-width': `${entry.width ?? 420}px` } as CSSProperties;
  const surface = BARE_PARTS[part.id] === true ? 'bare' : entry.surface;
  return (
    <div
      className={`case case--${surface}`}
      data-case={entry.label}
      data-layout={entry.layout}
      data-portal={entry.portal ? '' : undefined}
      style={order === undefined ? undefined : { order }}
    >
      <span className="case__label">
        {entry.label}
        {entry.note === undefined ? null : <span className="case__note"> · {entry.note}</span>}
      </span>
      <div className="case__stage" style={style}>
        {renderCase(part.id, entry)}
      </div>
    </div>
  );
}

const BARE_PARTS: Record<string, true> = {
  dialog: true,
  alert: true,
  'confirm-delete': true,
  'confirm-range': true,
  toast: true,
  'file-drop': true,
  'bottom-sheet': true,
  'result-card': true,
};

function CaseFrame({ part, entry }: { part: GalleryPart; entry: GalleryCase }) {
  return (
    <div
      className="case-frame"
      data-layout={entry.layout}
      data-part-id={part.id}
      data-portal={entry.portal ? '' : undefined}
    >
      <CaseBody part={part} entry={entry} />
    </div>
  );
}

function GroupFrame({ part }: { part: GalleryPart }) {
  const order = displayOrder(part);
  return (
    <div className="case-group" data-group={part.id}>
      {inlineCases(part).map((entry) => (
        <CaseBody key={entry.label} part={part} entry={entry} order={order.get(entry.label)} />
      ))}
    </div>
  );
}

/** Every surface a part opens on top of the page (menus, tooltips, windows). */
const SURFACE_SELECTOR =
  '.menu-positioner, .field-positioner, .tooltip-positioner, .status-positioner, .dialog, .sheet-popup, .toast-surface, .file-drop';

/** Height and used width of one state list, read from inside its frame. */
type GroupSize = { height: number; used: number };

/**
 * Lines up the two state lists of one part. Each case gets the taller of its two heights, so a
 * state sits at the same height in the 390 list and in the 1920 list. Both frames are same
 * origin. Their nodes belong to the frame window, so `instanceof HTMLElement` is not used.
 */
function useAlignedGroups(frames: { current: (HTMLIFrameElement | null)[] }, partId: string): GroupSize[] {
  const [sizes, setSizes] = useState<GroupSize[]>([]);
  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const align = () => {
      if (stopped) return;
      const groups = frames.current.map((frame) => frame?.contentDocument?.querySelector('.case-group') ?? null);
      if (groups.length === 0 || groups.some((group) => group === null)) {
        timer = window.setTimeout(align, 200);
        return;
      }
      const cases = groups.map((group) => [...(group as Element).querySelectorAll<HTMLElement>('[data-case]')]);
      for (const list of cases) for (const element of list) element.style.minHeight = '';
      const tallest = new Map<string, number>();
      for (const list of cases) {
        for (const element of list) {
          const label = element.dataset.case ?? '';
          tallest.set(label, Math.max(tallest.get(label) ?? 0, element.getBoundingClientRect().height));
        }
      }
      for (const list of cases) {
        for (const element of list) {
          element.style.minHeight = `${Math.ceil(tallest.get(element.dataset.case ?? '') ?? 0)}px`;
        }
      }
      setSizes(
        groups.map((group, index) => {
          // Menus and tooltips opened by hand inside the list draw outside the cases.
          const surfaces = [...((group as Element).ownerDocument.querySelectorAll(SURFACE_SELECTOR) ?? [])];
          const right = Math.max(
            0,
            ...[...cases[index], ...surfaces].map((element) => element.getBoundingClientRect().right),
          );
          return { height: Math.ceil((group as Element).getBoundingClientRect().height), used: Math.ceil(right) };
        }),
      );
    };
    const settle = () => {
      window.clearTimeout(timer);
      const fonts = frames.current.map((frame) => frame?.contentDocument?.fonts.ready ?? Promise.resolve());
      void Promise.all(fonts).then(() => {
        align();
        // Late layout (Base UI measuring, images) settles once more.
        timer = window.setTimeout(align, 400);
      });
    };
    const list = frames.current.filter((frame): frame is HTMLIFrameElement => frame !== null);
    // A case can grow after the first pass (the composer grows with its text). Each frame
    // watches the content of its cases, not the cases, so the min-height set here does not
    // trigger the watch again. A fresh frame document gets a fresh watch.
    const watches: ResizeObserver[] = [];
    const mutationWatches: MutationObserver[] = [];
    let queued = 0;
    const realign = () => {
      if (queued !== 0) return;
      queued = window.requestAnimationFrame(() => {
        queued = 0;
        align();
      });
    };
    const watch = (frame: HTMLIFrameElement) => {
      const view = frame.contentWindow as (Window & { ResizeObserver?: typeof ResizeObserver }) | null;
      const content = frame.contentDocument?.querySelectorAll('.case-group [data-case] > *') ?? [];
      if (view?.ResizeObserver === undefined || content.length === 0) return false;
      const observer = new view.ResizeObserver(realign);
      for (const element of content) observer.observe(element);
      watches.push(observer);
      // Surfaces that open, close or move. The min-height this hook writes on a case is skipped.
      const body = frame.contentDocument?.body;
      const MutationWatch = (view as Window & { MutationObserver?: typeof MutationObserver }).MutationObserver;
      if (body != null && MutationWatch !== undefined) {
        const mutations = new MutationWatch((records) => {
          if (records.every((record) => (record.target as HTMLElement).dataset?.case !== undefined)) return;
          realign();
        });
        mutations.observe(body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class', 'data-open', 'data-closed', 'hidden'] });
        mutationWatches.push(mutations);
      }
      return true;
    };
    const settleAndWatch = () => {
      settle();
      for (const observer of watches.splice(0)) observer.disconnect();
      for (const observer of mutationWatches.splice(0)) observer.disconnect();
      const start = () => {
        if (stopped) return;
        if (!list.every((frame) => frame.contentDocument?.querySelector('.case-group [data-case]') != null)) {
          watchTimer = window.setTimeout(start, 200);
          return;
        }
        for (const frame of list) watch(frame);
      };
      window.clearTimeout(watchTimer);
      start();
    };
    let watchTimer = 0;
    for (const frame of list) frame.addEventListener('load', settleAndWatch);
    settleAndWatch();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.clearTimeout(watchTimer);
      window.cancelAnimationFrame(queued);
      for (const observer of watches) observer.disconnect();
      for (const observer of mutationWatches) observer.disconnect();
      for (const frame of list) frame.removeEventListener('load', settleAndWatch);
    };
  }, [frames, partId]);
  return sizes;
}

/** Room right of the widest case inside the 1920 frame, in CSS px. */
const USED_MARGIN = 24;

function StateFrames({ part, cropped }: { part: GalleryPart; cropped: boolean }) {
  const frames = useRef<(HTMLIFrameElement | null)[]>([]);
  const sizes = useAlignedGroups(frames, part.id);
  return (
    <div className="frames__row">
      {WIDTHS.map((width, index) => {
        const size = sizes[index];
        const height = size?.height ?? (width === 390 ? 844 : 1080);
        // The 1920 frame keeps its real viewport; the box shows the left side the cases use.
        const shown =
          width === 390 || !cropped ? width : Math.min(1920, Math.max(390, (size?.used ?? 616) + USED_MARGIN));
        return (
          <figure className="frame" data-width={width} key={width}>
            <figcaption>
              {width}px{shown < width ? ` · 왼쪽 ${shown}px만 보임, 오른쪽은 빈 화면` : ''}
            </figcaption>
            <div className="frame__box" style={{ width: shown, height }}>
              <iframe
                ref={(node) => {
                  frames.current[index] = node;
                }}
                title={`${part.title} 모든 상태 ${width}px`}
                width={width}
                height={height}
                src={`?group=${encodeURIComponent(part.id)}`}
                data-frame-part={part.id}
                data-frame-group={part.id}
              />
            </div>
          </figure>
        );
      })}
    </div>
  );
}

/** What a popup frame draws: the case and every open surface, read from inside the frame. */
const POPUP_SELECTOR = `[data-case], ${SURFACE_SELECTOR}`;

/** Room kept around the drawn area of a popup frame, in CSS px. */
const CROP_MARGIN = 24;

type Crop = { left: number; top: number; width: number; height: number };

/**
 * In the one-part view a popup frame shows only the area its case and open surface use, at
 * real size. The frame keeps its full viewport; the outside box cuts the empty rest. The 390
 * frame keeps its full width so the screen edges stay visible.
 */
function usePopupCrop(frame: { current: HTMLIFrameElement | null }, width: number, enabled: boolean): Crop | null {
  const [crop, setCrop] = useState<Crop | null>(null);
  useEffect(() => {
    const node = frame.current;
    if (!enabled || node === null) return undefined;
    let stopped = false;
    let timer = 0;
    const measure = () => {
      if (stopped) return;
      const doc = node.contentDocument;
      const boxes = [...(doc?.querySelectorAll(POPUP_SELECTOR) ?? [])]
        .map((element) => element.getBoundingClientRect())
        .filter((box) => box.width > 0 && box.height > 0);
      if (boxes.length < 2) {
        timer = window.setTimeout(measure, 200);
        return;
      }
      const viewportHeight = Number(node.height);
      const top = Math.max(0, Math.min(...boxes.map((box) => box.top)) - CROP_MARGIN);
      const bottom = Math.min(viewportHeight, Math.max(...boxes.map((box) => box.bottom)) + CROP_MARGIN);
      const left = width === 390 ? 0 : Math.max(0, Math.min(...boxes.map((box) => box.left)) - CROP_MARGIN);
      const right = width === 390 ? 390 : Math.min(width, Math.max(...boxes.map((box) => box.right)) + CROP_MARGIN);
      setCrop({ left, top, width: Math.ceil(right - left), height: Math.ceil(bottom - top) });
    };
    // Surfaces open, close and move after the first pass (a tooltip opens on hover), so any
    // change in the frame document measures again, at most once per animation frame.
    let queued = 0;
    let watch: MutationObserver | undefined;
    const remeasure = () => {
      if (queued !== 0) return;
      queued = window.requestAnimationFrame(() => {
        queued = 0;
        measure();
      });
    };
    const settle = () => {
      window.clearTimeout(timer);
      watch?.disconnect();
      watch = undefined;
      // Popups open after their first frame; measure once they have settled.
      timer = window.setTimeout(measure, 500);
      const view = node.contentWindow as (Window & { MutationObserver?: typeof MutationObserver }) | null;
      const body = node.contentDocument?.body;
      if (view?.MutationObserver === undefined || body == null) return;
      watch = new view.MutationObserver(remeasure);
      watch.observe(body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class', 'data-open', 'data-closed', 'hidden'] });
    };
    node.addEventListener('load', settle);
    if (node.contentDocument?.readyState === 'complete') settle();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.cancelAnimationFrame(queued);
      watch?.disconnect();
      node.removeEventListener('load', settle);
    };
  }, [frame, width, enabled]);
  return crop;
}

function PopupFrame({
  part,
  entry,
  width,
  cropped,
}: {
  part: GalleryPart;
  entry: GalleryCase;
  width: number;
  cropped: boolean;
}) {
  const ref = useRef<HTMLIFrameElement>(null);
  const height = width === 390 ? 844 : 1080;
  const crop = usePopupCrop(ref, width, cropped);
  const box = crop === null ? { width, height } : { width: crop.width, height: crop.height };
  const shift = crop === null ? undefined : { transform: `translate(${-crop.left}px, ${-crop.top}px)` };
  return (
    <figure className="frame" data-width={width}>
      <figcaption>
        {width}px
        {crop === null ? '' : ` · 그린 부분만 원래 크기로 보임 (왼쪽 ${Math.round(crop.left)}, 위 ${Math.round(crop.top)}부터)`}
      </figcaption>
      <div className="frame__box frame__box--line" style={box}>
        <iframe
          ref={ref}
          style={shift}
          title={`${part.title} ${entry.label} ${width}px`}
          width={width}
          height={height}
          // The one-part view loads popup frames as they scroll near; the full page loads all.
          loading={cropped ? 'lazy' : undefined}
          src={`?case=${encodeURIComponent(entry.label)}`}
          data-frame-part={part.id}
          data-frame-case={entry.label}
        />
      </div>
    </figure>
  );
}

function PopupFrames({ part, entry, scaled }: { part: GalleryPart; entry: GalleryCase; scaled: boolean }) {
  return (
    <div className="frames__portal" data-portal-case={entry.label}>
      <p className="frames__label">
        창을 연 사례 · {entry.label}
        {entry.note === undefined ? '' : ` · ${entry.note}`}
      </p>
      <div className="frames__row">
        {WIDTHS.map((width) => (
          <PopupFrame key={width} part={part} entry={entry} width={width} cropped={scaled} />
        ))}
      </div>
    </div>
  );
}

function PartSection({ part, scaled }: { part: GalleryPart; scaled: boolean }) {
  const skips = Object.entries(part.notApplicable);
  return (
    <section className="part" data-part={part.id}>
      <header className="part__head">
        <h2>
          {part.number}. {part.title}
        </h2>
        <code>{part.matrixPart}</code>
      </header>
      <p className="part__description">{part.description}</p>
      {skips.length === 0 ? null : (
        <p className="part__skip">
          해당 없음:{' '}
          {skips.map(([state, reason]) => `${state} (${reason})`).join(' · ')}
        </p>
      )}
      <div className="frames">
        {inlineCases(part).length === 0 ? null : (
          <>
            <p className="frames__label">
              상태 {inlineCases(part).length}개 · 위에서 아래로 기본, hover, 누름, 선택, 열림, 꺼짐, 곧 지원,
              불러옴, 오류, 포커스 순 · 같은 상태는 두 폭에서 같은 높이
            </p>
            <StateFrames part={part} cropped={scaled} />
          </>
        )}
        {portalCases(part).map((entry) => (
          <PopupFrames key={entry.label} part={part} entry={entry} scaled={scaled} />
        ))}
      </div>
    </section>
  );
}

function link(params: Record<string, string>): string {
  return `?${new URLSearchParams(params).toString()}`;
}

function PartNav({ batch, current }: { batch: number; current: string }) {
  return (
    <nav className="gallery__nav" aria-label="부품 목록">
      <div className="gallery__batches">
        {BATCHES.map((value) => (
          <a key={value} href={link({ batch: String(value) })} aria-current={value === batch ? 'page' : undefined}>
            묶음 {value}
          </a>
        ))}
      </div>
      <ol>
        {galleryParts
          .filter((part) => part.batch === batch)
          .map((part) => (
            <li key={part.id}>
              <a
                href={link({ batch: String(batch), part: part.id })}
                aria-current={part.id === current ? 'page' : undefined}
              >
                <span className="gallery__nav-number">{part.number}</span>
                <span className="gallery__nav-title">{part.title}</span>
                <span className="gallery__nav-count">{part.cases.length}</span>
              </a>
            </li>
          ))}
      </ol>
      <a className="gallery__all" href={link({ batch: String(batch), view: 'all' })}>
        묶음 전체 한 쪽에 보기 (느림)
      </a>
    </nav>
  );
}

/** One part at a time, chosen in the left list. Only that part's frames load. */
function PartPage({ batch, part }: { batch: number; part: GalleryPart }) {
  return (
    <div className="gallery-shell">
      <PartNav batch={batch} current={part.id} />
      <main className="gallery gallery--single">
        <PartSection key={part.id} part={part} scaled />
      </main>
    </div>
  );
}

/** Every part of the batch on one page, at real size, for the tests and the screenshot sheets. */
function AllPartsPage({ batch, parts }: { batch: number; parts: readonly GalleryPart[] }) {
  return (
    <main className="gallery">
      <header className="gallery__head">
        <h1>부품 갤러리 · 묶음 {batch}</h1>
        <p>
          숫자 라벨은 상태 목록에서 만든다. 부품과 사례는 뒤에만 붙이고, 한 사례는 자기 폭의 실제
          viewport 안에서 그린다.
        </p>
        <p>
          부품 {parts.length}개 · 사례 {parts.reduce((sum, part) => sum + part.cases.length, 0)}개 ·{' '}
          <a href={link({ batch: String(batch) })}>부품 하나씩 보기</a>
        </p>
      </header>
      {galleryRanges.map((range) => {
        const rangeParts = range.parts.filter((part) => parts.includes(part));
        if (rangeParts.length === 0) return null;
        return (
          <section className="range" key={range.id} data-range={range.id}>
            <h2 className="range__title">
              번호 {range.id} · {rangeParts.length}개 부품
            </h2>
            {rangeParts.map((part) => (
              <PartSection key={part.id} part={part} scaled={false} />
            ))}
          </section>
        );
      })}
    </main>
  );
}

function GalleryPage({ batch, partId, all }: { batch: number; partId: string | null; all: boolean }) {
  const batchParts = galleryParts.filter((part) => part.batch === batch);
  if (all) {
    return <AllPartsPage batch={batch} parts={batchParts.filter((part) => partId === null || part.id === partId)} />;
  }
  const part = batchParts.find((candidate) => candidate.id === partId) ?? batchParts[0];
  if (part === undefined) return <p className="gallery__error">그런 묶음이 없다: {batch}</p>;
  return <PartPage batch={batch} part={part} />;
}

function QueryPage({
  caseLabel,
  groupId,
  batch,
  partId,
  all,
}: {
  caseLabel: string | null;
  groupId: string | null;
  batch: number;
  partId: string | null;
  all: boolean;
}) {
  if (caseLabel !== null) {
    const found = findCase(caseLabel);
    if (found === undefined) return <p className="gallery__error">그런 사례가 없다: {caseLabel}</p>;
    return <CaseFrame part={found.part} entry={found.entry} />;
  }
  if (groupId !== null) {
    const part = findPart(groupId);
    if (part === undefined) return <p className="gallery__error">그런 부품이 없다: {groupId}</p>;
    return <GroupFrame part={part} />;
  }
  return <GalleryPage batch={batch} partId={partId} all={all} />;
}

function query(): ReactNode {
  const params = new URLSearchParams(window.location.search);
  if (params.get('probe') !== null) return <ProbePage />;
  const batchText = params.get('batch') ?? '1';
  const batch = Number.parseInt(batchText, 10);
  return (
    <QueryPage
      caseLabel={params.get('case')}
      groupId={params.get('group')}
      batch={Number.isNaN(batch) ? 1 : batch}
      partId={params.get('part')}
      all={params.get('view') === 'all'}
    />
  );
}

/** The dev gallery root. `main.tsx` mounts it outside the app entry. */
export function Gallery(): ReactNode {
  return query();
}

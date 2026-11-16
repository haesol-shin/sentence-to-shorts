import { type CSSProperties, type ReactNode } from 'react';

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

function CaseBody({ part, entry }: { part: GalleryPart; entry: GalleryCase }) {
  const style = { '--case-width': `${entry.width ?? 420}px` } as CSSProperties;
  return (
    <div
      className={`case case--${entry.surface}`}
      data-case={entry.label}
      data-layout={entry.layout}
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

function frameHeight(part: GalleryPart, width: number, portal: boolean): number {
  if (portal) return width === 390 ? 844 : 1080;
  const base = width === 390 ? 844 : 1080;
  return Math.max(base, 96 + inlineCases(part).length * 200);
}

function CaseFrame({ part, entry }: { part: GalleryPart; entry: GalleryCase }) {
  return (
    <div className="case-frame" data-layout={entry.layout} data-part-id={part.id}>
      <CaseBody part={part} entry={entry} />
    </div>
  );
}

function GroupFrame({ part }: { part: GalleryPart }) {
  return (
    <div className="case-group" data-group={part.id}>
      {inlineCases(part).map((entry) => (
        <CaseBody key={entry.label} part={part} entry={entry} />
      ))}
    </div>
  );
}

function Frame({ part, width, group, entry }: { part: GalleryPart; width: number; group?: boolean; entry?: GalleryCase }) {
  const source = group === true ? `?group=${encodeURIComponent(part.id)}` : `?case=${encodeURIComponent(entry?.label ?? '')}`;
  const height = frameHeight(part, width, group !== true);
  const caption = group === true ? '모든 상태' : entry?.label;
  return (
    <figure className="frame" data-width={width}>
      <figcaption>
        {width}px · {caption}
      </figcaption>
      <iframe
        title={`${part.title} ${caption ?? ''} ${width}px`}
        width={width}
        height={height}
        src={source}
        data-frame-part={part.id}
        data-frame-group={group === true ? part.id : undefined}
        data-frame-case={group === true ? undefined : entry?.label}
      />
    </figure>
  );
}

function PartSection({ part }: { part: GalleryPart }) {
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
            <p className="frames__label">상태 한 화면 · {inlineCases(part).length}개</p>
            <div className="frames__row">
              {WIDTHS.map((width) => (
                <Frame key={width} part={part} width={width} group />
              ))}
            </div>
          </>
        )}
        {portalCases(part).map((entry) => (
          <div className="frames__portal" key={entry.label} data-portal-case={entry.label}>
            <p className="frames__label">창을 연 사례 · {entry.label}</p>
            <div className="frames__row">
              {WIDTHS.map((width) => (
                <Frame key={width} part={part} width={width} entry={entry} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function GalleryPage({ batch, partId }: { batch: number; partId: string | null }) {
  const parts = galleryParts.filter(
    (part) => part.batch === batch && (partId === null || part.id === partId),
  );
  return (
    <main className="gallery">
      <header className="gallery__head">
        <h1>부품 갤러리 · 묶음 {batch}</h1>
        <p>
          숫자 라벨은 상태 목록에서 만든다. 부품과 사례는 뒤에만 붙이고, 한 사례는
          자기 폭의 실제 viewport 안에서 그린다.
        </p>
        <p>
          부품 {parts.length}개 · 사례 {parts.reduce((sum, part) => sum + part.cases.length, 0)}개
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
              <PartSection key={part.id} part={part} />
            ))}
          </section>
        );
      })}
    </main>
  );
}

function QueryPage({
  caseLabel,
  groupId,
  batch,
  partId,
}: {
  caseLabel: string | null;
  groupId: string | null;
  batch: number;
  partId: string | null;
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
  return <GalleryPage batch={batch} partId={partId} />;
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
    />
  );
}

/** The dev gallery root. `main.tsx` mounts it outside the app entry. */
export function Gallery(): ReactNode {
  return query();
}

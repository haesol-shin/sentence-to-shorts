/**
 * Runs inside the gallery case frame. Playwright serialises this function, so
 * it must stay self-contained.
 *
 * The probes around the visible box find the outermost box the browser still
 * delivers to the control. With `declaredRing`, the shared `.hit-area` design
 * size also counts, for the older design check; the delivered-area record
 * leaves it off so a clipped ring cannot pass.
 */
export type MeasureRequest = {
  fallbackCase: string;
  /** Add the shared `.hit-area` declaration to the probe, as the design check does. */
  declaredRing?: boolean;
};

export type MeasuredControl = {
  case: string;
  role: string;
  name: string;
  disabled: boolean;
  visible: { width: number; height: number };
  hit: { width: number; height: number };
  /** True when a point inside the visible box goes to something other than the control. */
  covered: boolean;
  box: { left: number; top: number; right: number; bottom: number };
  /** The same box in document coordinates, comparable after a scroll. */
  documentBox: { left: number; top: number; right: number; bottom: number };
  /** True when the control was scrolled into view before measuring. */
  scrolled?: boolean;
};

/** One row of the committed delivered-area record. */
export type HitAreaRow = {
  case: string;
  role: string;
  name: string;
  disabled: boolean;
  covered: boolean;
  visible: [number, number];
  hit: [number, number];
};

export type MeasuredOverlap = {
  a: string;
  b: string;
  overlap: { width: number; height: number };
};

export type FrameMeasurement = {
  controls: MeasuredControl[];
  overlaps: MeasuredOverlap[];
  /** Overlap in document coordinates, including controls found by scrolling. */
  overlapsAll: MeasuredOverlap[];
  clipped: number;
  viewport: { width: number; height: number };
};

export function measureFrame(input: string | MeasureRequest): FrameMeasurement {
  const fallbackCase = typeof input === 'string' ? input : input.fallbackCase;
  const declaredRing = typeof input === 'string' ? true : input.declaredRing === true;
  // Self-contained: Playwright serialises this function into the page.
  const selector =
    'button, input, textarea, select, a[href], [role=switch], [role=radio], [role=tab], [role=menuitem], [role=option], [role=combobox]';
  const round = (value: number) => Math.round(value * 2) / 2;
  // The accessible name, without the hidden copies LabelBox keeps for width.
  const nameOf = (el: Element) => {
    const label = el.getAttribute('aria-label');
    if (label !== null && label.trim() !== '') return label.trim();
    const text = el instanceof HTMLElement ? el.innerText : el.textContent;
    return (text ?? '').trim().replace(/\s+/g, ' ').slice(0, 60);
  };
  const rectOf = (el: Element) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
  };
  const controlAt = (x: number, y: number) => {
    const found = document.elementFromPoint(x, y);
    return found === null ? null : found.closest(selector);
  };
  const clipOf = (el: Element) => {
    let box = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    for (let node = el.parentElement; node !== null; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
      const r = node.getBoundingClientRect();
      box = {
        left: Math.max(box.left, r.left),
        top: Math.max(box.top, r.top),
        right: Math.min(box.right, r.right),
        bottom: Math.min(box.bottom, r.bottom),
      };
    }
    return box;
  };
  const documentOffsetOf = (el: Element) => {
    let left = window.scrollX;
    let top = window.scrollY;
    for (let node = el.parentElement; node !== null; node = node.parentElement) {
      left += node.scrollLeft;
      top += node.scrollTop;
    }
    return { left, top };
  };

  const controls = [...document.querySelectorAll(selector)].filter((el) => {
    if (el.tagName === 'INPUT') {
      const input = el as HTMLInputElement;
      if (input.type === 'hidden' || input.offsetWidth === 0) return false;
    }
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (el.closest('[aria-hidden="true"]') !== null) return false;
    return true;
  });

  const measured: MeasuredControl[] = [];
  let clipped = 0;

  for (const el of controls) {
    let visible = rectOf(el);
    if (visible.width === 0 || visible.height === 0) continue;
    let clip = clipOf(el);
    let isClipped =
      clip.left > visible.left + 0.5 ||
      clip.top > visible.top + 0.5 ||
      clip.right < visible.right - 0.5 ||
      clip.bottom < visible.bottom - 0.5;
    let scrolled = false;
    if (isClipped) {
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      visible = rectOf(el);
      clip = clipOf(el);
      scrolled = true;
      isClipped =
        clip.left > visible.left + 0.5 ||
        clip.top > visible.top + 0.5 ||
        clip.right < visible.right - 0.5 ||
        clip.bottom < visible.bottom - 0.5;
    }
    if (isClipped) {
      clipped += 1;
      const offset = documentOffsetOf(el);
      const container = el.closest('[data-case]');
      measured.push({
        case: container?.getAttribute('data-case') ?? fallbackCase,
        role: el.getAttribute('role') ?? el.tagName.toLowerCase(),
        name: nameOf(el),
        disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute('aria-disabled') === 'true',
        visible: { width: round(visible.width), height: round(visible.height) },
        hit: { width: 0, height: 0 },
        covered: true,
        box: {
          left: round(visible.left),
          top: round(visible.top),
          right: round(visible.right),
          bottom: round(visible.bottom),
        },
        documentBox: {
          left: round(visible.left + offset.left),
          top: round(visible.top + offset.top),
          right: round(visible.right + offset.left),
          bottom: round(visible.bottom + offset.top),
        },
        scrolled: scrolled ? true : undefined,
      });
      continue;
    }

    const probe = (dx: number, dy: number, x: number, y: number): number => {
      for (let d = 0.5; d <= 28; d += 0.5) {
        const px = x + dx * d;
        const py = y + dy * d;
        if (px < 0 || py < 0 || px >= window.innerWidth || py >= window.innerHeight) return d - 0.5;
        if (controlAt(px, py) !== el) return d - 0.5;
      }
      return 28;
    };
    const middleX = (visible.left + visible.right) / 2;
    const middleY = (visible.top + visible.bottom) / 2;
    const left = probe(-1, 0, visible.left, middleY);
    const right = probe(1, 0, visible.right, middleY);
    const top = probe(0, -1, middleX, visible.top);
    const bottom = probe(0, 1, middleX, visible.bottom);
    const hit = {
      left: visible.left - left,
      right: visible.right + right,
      top: visible.top - top,
      bottom: visible.bottom + bottom,
      width: visible.width + left + right,
      height: visible.height + top + bottom,
    };

    if (declaredRing && el.classList.contains('hit-area')) {
      const declared = getComputedStyle(el, '::after');
      const declaredWidth = Number.parseFloat(declared.width);
      const declaredHeight = Number.parseFloat(declared.height);
      if (Number.isFinite(declaredWidth) && declaredWidth >= 44) hit.width = Math.max(hit.width, declaredWidth);
      if (Number.isFinite(declaredHeight) && declaredHeight >= 44) hit.height = Math.max(hit.height, declaredHeight);
    }

    const centerX = (visible.left + visible.right) / 2;
    const centerY = (visible.top + visible.bottom) / 2;
    let box = {
      left: centerX - hit.width / 2,
      top: centerY - hit.height / 2,
      right: centerX + hit.width / 2,
      bottom: centerY + hit.height / 2,
    };
    let covered = false;
    if (!declaredRing) {
      // Judge the interior of the required 44x44 square at the visible center. The 1px
      // border is not a stable hit target, so the 2px grid runs just inside it; every
      // point must reach this control or a descendant. A covered center, a narrow
      // passage, and a full-width band all leave a point elsewhere, so none can pass.
      for (let x = centerX - 21; x <= centerX + 21 && !covered; x += 2) {
        for (let y = centerY - 21; y <= centerY + 21; y += 2) {
          const found = document.elementFromPoint(x, y);
          if (found === null || (found !== el && !el.contains(found))) {
            covered = true;
            break;
          }
        }
      }
      if (covered) {
        hit.width = 0;
        hit.height = 0;
        box = { left: centerX, top: centerY, right: centerX, bottom: centerY };
      }
    }
    const offset = documentOffsetOf(el);
    const documentBox = {
      left: box.left + offset.left,
      top: box.top + offset.top,
      right: box.right + offset.left,
      bottom: box.bottom + offset.top,
    };

    const container = el.closest('[data-case]');
    measured.push({
      case: container?.getAttribute('data-case') ?? fallbackCase,
      role: el.getAttribute('role') ?? el.tagName.toLowerCase(),
      name: nameOf(el),
      disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute('aria-disabled') === 'true',
      visible: { width: round(visible.width), height: round(visible.height) },
      hit: { width: round(hit.width), height: round(hit.height) },
      covered,
      box: {
        left: round(box.left),
        top: round(box.top),
        right: round(box.right),
        bottom: round(box.bottom),
      },
      documentBox: {
        left: round(documentBox.left),
        top: round(documentBox.top),
        right: round(documentBox.right),
        bottom: round(documentBox.bottom),
      },
      scrolled: scrolled ? true : undefined,
    });
  }

  const overlaps: MeasuredOverlap[] = [];
  for (let i = 0; i < measured.length; i += 1) {
    for (let j = i + 1; j < measured.length; j += 1) {
      const a = measured[i].box;
      const b = measured[j].box;
      if (measured[i].scrolled === true || measured[j].scrolled === true) continue;
      const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (width > 0.5 && height > 0.5) {
        overlaps.push({
          a: `${measured[i].case} ${measured[i].name}`,
          b: `${measured[j].case} ${measured[j].name}`,
          overlap: { width: round(width), height: round(height) },
        });
      }
    }
  }

  const overlapsAll: MeasuredOverlap[] = [];
  for (let i = 0; i < measured.length; i += 1) {
    for (let j = i + 1; j < measured.length; j += 1) {
      const a = measured[i].documentBox;
      const b = measured[j].documentBox;
      const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (width > 0.5 && height > 0.5) {
        overlapsAll.push({
          a: `${measured[i].case} ${measured[i].name}`,
          b: `${measured[j].case} ${measured[j].name}`,
          overlap: { width: round(width), height: round(height) },
        });
      }
    }
  }

  return {
    controls: measured,
    overlaps,
    overlapsAll,
    clipped,
    viewport: { width: window.innerWidth, height: window.innerHeight },
  };
}

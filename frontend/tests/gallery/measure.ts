/**
 * Runs inside the gallery case frame. Playwright serialises this function, so
 * it must stay self-contained.
 *
 * A control's designed hit area is the transparent ring drawn by the shared
 * `.hit-area` rule. The probes around the visible box confirm it reaches the
 * neighbouring controls without covering them; a half pixel boundary between
 * two touching rings is rounded by using the declared ring size.
 */
export type MeasuredControl = {
  case: string;
  role: string;
  name: string;
  visible: { width: number; height: number };
  hit: { width: number; height: number };
  box: { left: number; top: number; right: number; bottom: number };
  /** True when the control was scrolled into view before measuring. */
  scrolled?: boolean;
};

export type MeasuredOverlap = {
  a: string;
  b: string;
  overlap: { width: number; height: number };
};

export type FrameMeasurement = {
  controls: MeasuredControl[];
  overlaps: MeasuredOverlap[];
  clipped: number;
  viewport: { width: number; height: number };
};

export function measureFrame(fallbackCase: string): FrameMeasurement {
  const selector =
    'button, input, a[href], [role=switch], [role=radio], [role=tab], [role=menuitem], [role=option], [role=combobox]';
  const round = (value: number) => Math.round(value * 2) / 2;
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

    if (el.classList.contains('hit-area')) {
      const declared = getComputedStyle(el, '::after');
      const declaredWidth = Number.parseFloat(declared.width);
      const declaredHeight = Number.parseFloat(declared.height);
      if (Number.isFinite(declaredWidth) && declaredWidth >= 44) hit.width = Math.max(hit.width, declaredWidth);
      if (Number.isFinite(declaredHeight) && declaredHeight >= 44) hit.height = Math.max(hit.height, declaredHeight);
    }

    const centerX = (visible.left + visible.right) / 2;
    const centerY = (visible.top + visible.bottom) / 2;
    const box = {
      left: centerX - hit.width / 2,
      top: centerY - hit.height / 2,
      right: centerX + hit.width / 2,
      bottom: centerY + hit.height / 2,
    };

    const container = el.closest('[data-case]');
    measured.push({
      case: container?.getAttribute('data-case') ?? fallbackCase,
      role: el.getAttribute('role') ?? el.tagName.toLowerCase(),
      name: el.getAttribute('aria-label') ?? (el.textContent ?? '').trim().slice(0, 60),
      visible: { width: round(visible.width), height: round(visible.height) },
      hit: { width: round(hit.width), height: round(hit.height) },
      box: {
        left: round(box.left),
        top: round(box.top),
        right: round(box.right),
        bottom: round(box.bottom),
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

  return {
    controls: measured,
    overlaps,
    clipped,
    viewport: { width: window.innerWidth, height: window.innerHeight },
  };
}

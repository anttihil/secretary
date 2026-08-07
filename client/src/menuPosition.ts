const VIEWPORT_MARGIN = 8;

/**
 * Places a `position: fixed` menu at the cursor, flipping it above/left of the
 * cursor when it would overflow the viewport and clamping it as a last resort.
 */
export function positionMenu(el: HTMLElement, x: number, y: number): void {
  // Measure from the origin so shrink-to-fit sizing isn't squeezed by the
  // menu's previous position near an edge.
  el.style.left = "0px";
  el.style.top = "0px";
  const { width, height } = el.getBoundingClientRect();

  let left = x;
  if (left + width > window.innerWidth - VIEWPORT_MARGIN) {
    left = x - width;
  }
  let top = y;
  if (top + height > window.innerHeight - VIEWPORT_MARGIN) {
    top = y - height;
  }

  el.style.left = `${Math.max(VIEWPORT_MARGIN, left)}px`;
  el.style.top = `${Math.max(VIEWPORT_MARGIN, top)}px`;
}

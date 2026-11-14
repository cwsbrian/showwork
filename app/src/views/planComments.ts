import type { CommentAnchor, ReportComment } from '../api';

function button(label: string, className: string): HTMLButtonElement {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = label;
  element.className = className;
  return element;
}

// Report prose is rendered as one text node per target. Offsets refer to that immutable
// text, so a comment keeps pointing to the same words after reflow or reopening.
export function createPlanComments(
  root: HTMLElement,
  initial: ReportComment[],
  save: (anchor: CommentAnchor, body: string) => Promise<ReportComment>,
  remove: (commentId: string) => Promise<void>,
  onChange: () => void = () => {},
): { destroy(): void } {
  const comments = [...initial];
  const visualTargets = new Map<string, {node: Text; frame: HTMLIFrameElement}>();
  const frameListeners: Array<() => void> = [];
  let popover: HTMLElement | null = null;
  let backdrop: HTMLElement | null = null;
  let draftAnchor: CommentAnchor | null = null;
  let destroyed = false;

  function frameDocument(frame: HTMLIFrameElement): Document | null {
    try { return frame.contentDocument; } catch { return null; }
  }

  function codeSources(element: HTMLElement): HTMLElement[] {
    return [...element.querySelectorAll<HTMLElement>('.line > .src')];
  }

  function codeText(sources: HTMLElement[]): string {
    return sources.map((source) => source.textContent ?? '').join('\n');
  }

  function codePoint(source: HTMLElement, offset: number): {node: Node; offset: number} {
    const walker = source.ownerDocument.createTreeWalker(source, NodeFilter.SHOW_TEXT);
    let node: Node | null;
    let remaining = offset;
    let last: Node | null = null;
    while ((node = walker.nextNode())) {
      last = node;
      const length = node.nodeValue?.length ?? 0;
      if (remaining <= length) return {node, offset: remaining};
      remaining -= length;
    }
    return last ? {node: last, offset: last.nodeValue?.length ?? 0} : {node: source, offset: 0};
  }

  function offsetInCode(sources: HTMLElement[], source: HTMLElement, node: Node, offset: number): number {
    let total = 0;
    for (const item of sources) {
      if (item === source) {
        const prefix = item.ownerDocument.createRange();
        prefix.setStart(item, 0);
        prefix.setEnd(node, offset);
        return total + prefix.toString().length;
      }
      total += (item.textContent?.length ?? 0) + 1;
    }
    return -1;
  }

  function targetFor(anchor: CommentAnchor): {element: HTMLElement; node?: Text; frame?: HTMLIFrameElement; sources?: HTMLElement[]} | null {
    if (anchor.target.startsWith('file-')) {
      const element = [...root.querySelectorAll<HTMLElement>('.code[data-comment-target]')]
        .find((candidate) => candidate.dataset.commentTarget === anchor.target);
      if (!element) return null;
      const sources = codeSources(element);
      return codeText(sources).slice(anchor.start, anchor.end) === anchor.quote ? {element, sources} : null;
    }
    const visual = visualTargets.get(anchor.target);
    if (visual) {
      const element = visual.node.parentElement;
      return element && visual.node.nodeValue?.slice(anchor.start, anchor.end) === anchor.quote
        ? {element, node: visual.node, frame: visual.frame} : null;
    }
    const element = [...root.querySelectorAll<HTMLElement>('[data-comment-target]')]
      .find((candidate) => candidate.dataset.commentTarget === anchor.target);
    const value = element?.firstChild?.nodeValue;
    return value && value.slice(anchor.start, anchor.end) === anchor.quote
      ? {element: element!, node: element!.firstChild as Text} : null;
  }

  function rangeFor(node: Text, anchor: CommentAnchor): Range {
    const range = node.ownerDocument.createRange();
    range.setStart(node, anchor.start);
    range.setEnd(node, anchor.end);
    return range;
  }

  function outerRect(rect: DOMRect, frame?: HTMLIFrameElement): DOMRect {
    if (!frame) return rect;
    const frameRect = frame.getBoundingClientRect();
    return new DOMRect(frameRect.left + rect.left, frameRect.top + rect.top, rect.width, rect.height);
  }

  function closePopover() {
    popover?.remove();
    popover = null;
    backdrop?.remove();
    backdrop = null;
    document.removeEventListener('keydown', onKeyDown);
    document.removeEventListener('mousedown', onOutsideMouseDown, true);
    if (draftAnchor) {
      draftAnchor = null;
      if (!destroyed) draw();
    }
  }

  function onOutsideMouseDown(event: MouseEvent) {
    if (popover && !popover.contains(event.target as Node)) closePopover();
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      closePopover();
    }
  }

  function placePopover(element: HTMLElement, rect: DOMRect) {
    backdrop = document.createElement('div');
    backdrop.className = 'plan-comment-backdrop';
    backdrop.addEventListener('mousedown', closePopover);
    document.body.append(backdrop);
    document.body.append(element);
    const width = element.offsetWidth;
    const height = element.offsetHeight;
    element.style.left = `${Math.max(12, Math.min(rect.right - 24, window.innerWidth - width - 12))}px`;
    element.style.top = `${Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - height - 12))}px`;
    popover = element;
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onOutsideMouseDown, true);
  }

  function commentPopover(comment: ReportComment, rect: DOMRect) {
    closePopover();
    const box = document.createElement('aside');
    box.className = 'plan-comment-pop';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Plan comment');
    const header = document.createElement('div');
    header.className = 'plan-comment-pop-head';
    const title = document.createElement('strong');
    title.textContent = 'Comment';
    const close = button('×', 'plan-comment-close');
    close.setAttribute('aria-label', 'Close comment');
    close.onclick = closePopover;
    header.append(title, close);
    const quote = document.createElement('blockquote');
    quote.textContent = comment.anchor.quote;
    const body = document.createElement('p');
    body.textContent = comment.body;
    const actions = document.createElement('div');
    actions.className = 'plan-comment-actions';
    const deleteButton = button('Delete', 'plan-comment-delete');
    const status = document.createElement('p');
    status.className = 'plan-comment-status';
    status.setAttribute('role', 'status');
    deleteButton.onclick = async () => {
      if (deleteButton.dataset.confirm !== 'true') {
        deleteButton.dataset.confirm = 'true';
        deleteButton.textContent = 'Confirm delete';
        return;
      }
      deleteButton.disabled = true;
      status.textContent = 'Deleting…';
      try {
        await remove(comment.id);
        if (destroyed) return;
        const index = comments.findIndex((item) => item.id === comment.id);
        if (index >= 0) comments.splice(index, 1);
        closePopover();
        draw();
        onChange();
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : String(error);
        deleteButton.disabled = false;
      }
    };
    actions.append(deleteButton);
    box.append(header, quote, body, actions, status);
    placePopover(box, rect);
    close.focus();
  }

  function draw() {
    root.querySelectorAll('.plan-comment-mark, .plan-comment-pin').forEach((element) => element.remove());
    for (const {frame} of visualTargets.values()) {
      frameDocument(frame)?.querySelectorAll('.plan-comment-mark, .plan-comment-pin').forEach((element) => element.remove());
    }
    function markSelection(anchor: CommentAnchor, preview = false) {
      const target = targetFor(anchor);
      if (!target) return null;
      const {element, node, sources} = target;
      element.classList.add('plan-comment-target');
      const base = element.getBoundingClientRect();
      const rects: DOMRect[] = [];
      if (sources) {
        let cursor = 0;
        for (const source of sources) {
          const length = source.textContent?.length ?? 0;
          const start = Math.max(0, anchor.start - cursor);
          const end = Math.min(length, anchor.end - cursor);
          if (end > start) {
            const range = source.ownerDocument.createRange();
            const first = codePoint(source, start), last = codePoint(source, end);
            range.setStart(first.node, first.offset);
            range.setEnd(last.node, last.offset);
            rects.push(...[...range.getClientRects()].filter((rect) => rect.width && rect.height));
          }
          cursor += length + 1;
        }
      } else if (node) {
        rects.push(...[...rangeFor(node, anchor).getClientRects()].filter((rect) => rect.width && rect.height));
      }
      rects.forEach((rect) => {
        const mark = element.ownerDocument.createElement('span');
        mark.className = preview ? 'plan-comment-mark preview' : 'plan-comment-mark';
        mark.style.left = `${rect.left - base.left + (sources ? element.scrollLeft : 0)}px`;
        mark.style.top = `${rect.top - base.top + (sources ? element.scrollTop : 0)}px`;
        mark.style.width = `${rect.width}px`;
        mark.style.height = `${rect.height}px`;
        element.append(mark);
      });
      return {target, base, rects};
    }
    comments.forEach((comment, index) => {
      const marked = markSelection(comment.anchor);
      if (!marked) return;
      const {target: {element, frame, sources}, base, rects} = marked;
      const last = rects[rects.length - 1];
      if (!last) return;
      // WebKit does not run event handlers inside a sandboxed srcdoc. Keep the
      // highlight there, but put its clickable pin in the parent document.
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.textContent = String(index + 1);
      pin.className = 'plan-comment-pin';
      pin.setAttribute('aria-label', `Open comment ${index + 1}: ${comment.anchor.quote}`);
      if (frame) {
        root.classList.add('plan-comment-surface');
        const outer = outerRect(last, frame);
        const rootRect = root.getBoundingClientRect();
        pin.style.left = `${outer.right - rootRect.left + 5}px`;
        pin.style.top = `${outer.top - rootRect.top - 3}px`;
        root.append(pin);
      } else {
        pin.style.left = `${last.right - base.left + (sources ? element.scrollLeft : 0) + 5}px`;
        pin.style.top = `${last.top - base.top + (sources ? element.scrollTop : 0) - 3}px`;
        element.append(pin);
      }
      pin.onclick = () => commentPopover(comment, pin.getBoundingClientRect());
    });
    if (draftAnchor) markSelection(draftAnchor, true);
  }

  function compose(anchor: CommentAnchor, rect: DOMRect) {
    closePopover();
    draftAnchor = anchor;
    draw();
    const box = document.createElement('aside');
    box.className = 'plan-comment-pop';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Add plan comment');
    const title = document.createElement('strong');
    title.textContent = 'Comment on this text';
    const quote = document.createElement('blockquote');
    quote.textContent = anchor.quote;
    const input = document.createElement('textarea');
    input.placeholder = 'Write a comment…';
    input.setAttribute('aria-label', 'Comment');
    input.maxLength = 20000;
    const actions = document.createElement('div');
    actions.className = 'plan-comment-actions';
    const cancel = button('Cancel', 'plan-comment-cancel');
    cancel.onclick = closePopover;
    const submit = button('Add comment', 'plan-comment-submit');
    const status = document.createElement('p');
    status.className = 'plan-comment-status';
    status.setAttribute('role', 'status');
    submit.onclick = async () => {
      const body = input.value.trim();
      if (!body) { status.textContent = 'Write a comment first.'; input.focus(); return; }
      submit.disabled = true;
      status.textContent = 'Saving…';
      try {
        const comment = await save(anchor, body);
        if (destroyed) return;
        comments.push(comment);
        closePopover();
        draw();
        onChange();
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : String(error);
        submit.disabled = false;
      }
    };
    actions.append(cancel, submit);
    box.append(title, quote, input, actions, status);
    placePopover(box, rect);
    input.focus();
  }

  function onMouseUp(doc: Document, frame?: HTMLIFrameElement) {
    const selection = doc.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return;
    const range = selection.getRangeAt(0);
    if (!frame) {
      const startElement = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer as Element : range.startContainer.parentElement;
      const endElement = range.endContainer.nodeType === Node.ELEMENT_NODE ? range.endContainer as Element : range.endContainer.parentElement;
      const firstSource = startElement?.closest<HTMLElement>('.line > .src');
      const lastSource = endElement?.closest<HTMLElement>('.line > .src');
      const code = firstSource?.closest<HTMLElement>('.code[data-comment-target]');
      if (code && lastSource?.closest('.code') === code && root.contains(code)) {
        const sources = codeSources(code);
        const start = offsetInCode(sources, firstSource!, range.startContainer, range.startOffset);
        const end = offsetInCode(sources, lastSource, range.endContainer, range.endOffset);
        const quote = codeText(sources).slice(start, end);
        if (start >= 0 && end > start && quote.trim() && quote.length <= 10000) {
          const anchor = {target: code.dataset.commentTarget!, start, end, quote};
          const rect = range.getBoundingClientRect();
          selection.removeAllRanges();
          compose(anchor, rect);
        }
        return;
      }
    }
    if (range.startContainer !== range.endContainer || range.startContainer.nodeType !== Node.TEXT_NODE) return;
    let targetId: string | undefined;
    if (frame) {
      targetId = [...visualTargets].find(([, value]) => value.node === range.startContainer && value.frame === frame)?.[0];
    } else {
      const target = range.startContainer.parentElement?.closest<HTMLElement>('[data-comment-target]');
      if (target && root.contains(target) && target.firstChild === range.startContainer) targetId = target.dataset.commentTarget;
    }
    if (!targetId) return;
    const quote = range.toString();
    if (!quote.trim() || quote.length > 10000) return;
    const anchor = { target: targetId, start: range.startOffset, end: range.endOffset, quote };
    const rect = outerRect(range.getBoundingClientRect(), frame);
    selection.removeAllRanges();
    compose(anchor, rect);
  }

  const onDocumentMouseUp = () => {
    onMouseUp(document);
    for (const {frame} of visualTargets.values()) {
      const doc = frameDocument(frame);
      if (doc?.getSelection()?.toString()) { onMouseUp(doc, frame); break; }
    }
  };
  document.addEventListener('mouseup', onDocumentMouseUp);
  // srcdoc visuals live in a separate document. Their mouse events never reach the
  // report root, so each same-origin frame gets its own selection listener.
  const visualFrames = [...root.querySelectorAll<HTMLIFrameElement>('.section-grid iframe')];
  visualFrames.forEach((frame, sectionIndex) => {
    let activeDoc: Document | null = null;
    let handler: (() => void) | null = null;
    const attach = () => {
      if (activeDoc && handler) {
        activeDoc.removeEventListener('mouseup', handler);
        activeDoc.removeEventListener('mousedown', onOutsideMouseDown, true);
      }
      const prefix = `visual-${sectionIndex}-`;
      for (const key of visualTargets.keys()) if (key.startsWith(prefix)) visualTargets.delete(key);
      try {
        const doc = frameDocument(frame);
        if (!doc?.body) return;
        activeDoc = doc;
        const style = doc.createElement('style');
        style.textContent = '.plan-comment-target{position:relative}.plan-comment-mark{position:absolute;z-index:1;pointer-events:none;background:rgba(255,194,63,.35);border-bottom:2px solid #d48c13;border-radius:2px}.plan-comment-mark.preview{background:rgba(255,194,63,.56);border-bottom-color:#a45e07}.plan-comment-pin{position:absolute;z-index:2;display:grid;place-items:center;width:20px;height:20px;padding:0;border:2px solid #fff;border-radius:50%;background:#bb7510;color:#fff;font:700 11px system-ui;box-shadow:0 1px 5px #0004;cursor:pointer}';
        (doc.head || doc.documentElement).append(style);
        const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
        let node: Node | null;
        let ordinal = 0;
        while ((node = walker.nextNode())) {
          if (node.nodeValue?.trim() && node.parentElement && !node.parentElement.closest('script,style,template')) {
            visualTargets.set(prefix + ordinal++, {node: node as Text, frame});
          }
        }
        handler = () => onMouseUp(doc, frame);
        doc.addEventListener('mouseup', handler);
        doc.addEventListener('mousedown', onOutsideMouseDown, true);
        draw();
      } catch { /* A frame that navigated away is not commentable. */ }
    };
    frame.addEventListener('load', attach);
    frameListeners.push(() => {
      frame.removeEventListener('load', attach);
      if (activeDoc && handler) {
        activeDoc.removeEventListener('mouseup', handler);
        activeDoc.removeEventListener('mousedown', onOutsideMouseDown, true);
      }
    });
    if (frameDocument(frame)?.body) attach();
  });
  // WebKit can finish a native text drag in a sandboxed srcdoc without firing
  // a script-visible mouseup or selectionchange there. Poll the selected text
  // briefly while this plan is open and act once it has stopped changing.
  let lastSelection = '', selectedSince = 0, handledSelection = '';
  const selectionTimer = setInterval(() => {
    let active = '';
    for (const [index, frame] of visualFrames.entries()) {
      const doc = frameDocument(frame);
      const selected = doc?.getSelection()?.toString();
      if (!selected) continue;
      active = `${index}:${selected}`;
      if (active !== lastSelection) { lastSelection = active; selectedSince = Date.now(); }
      if (active !== handledSelection && Date.now() - selectedSince >= 300) {
        handledSelection = active;
        onMouseUp(doc!, frame);
      }
      break;
    }
    if (!active) { lastSelection = ''; handledSelection = ''; }
  }, 150);
  const observer = new ResizeObserver(draw);
  observer.observe(root);
  window.addEventListener('resize', draw);
  draw();
  return {
    destroy() {
      destroyed = true;
      closePopover();
      observer.disconnect();
      window.removeEventListener('resize', draw);
      document.removeEventListener('mouseup', onDocumentMouseUp);
      frameListeners.forEach((unsubscribe) => unsubscribe());
      clearInterval(selectionTimer);
    },
  };
}

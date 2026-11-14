import { renderReport } from '@report-view';
import type { ShowworkApi } from '../api';
import { typeLabel, type RunningItem } from '../model';
import { createPlanComments } from './planComments';
import { createPlanFeedback } from './planFeedback';

let paneCount = 0;

export function createReportPane(container: HTMLElement, api: ShowworkApi, onChosen: (reportId: string) => void = () => {}) {
  const prefix = `pane${paneCount++}-`;
  let current: { destroy(): void; refresh(): void } | null = null;
  let commentView: { destroy(): void } | null = null;
  let feedbackView: { destroy(): void; refresh(): Promise<void> } | null = null;
  let token = 0;
  let draftRunId = '';
  let shownText = '';
  let targetText = '';
  let draftNode: Text | null = null;
  let draftTimer: ReturnType<typeof setInterval> | undefined;
  let sessionTimer: ReturnType<typeof setInterval> | undefined;

  function stopSession() {
    clearInterval(sessionTimer);
    sessionTimer = undefined;
  }

  function stopDraft() {
    clearInterval(draftTimer);
    draftTimer = undefined;
    draftRunId = '';
    draftNode = null;
    shownText = '';
    targetText = '';
  }

  function placeholder(text: string) {
    stopSession();
    current?.destroy();
    commentView?.destroy();
    commentView = null;
    feedbackView?.destroy();
    feedbackView = null;
    current = null;
    stopDraft();
    container.replaceChildren();
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = text;
    container.append(p);
  }
  placeholder('Select a report');

  function header(meta: import('../model').ReportMeta): HTMLElement {
    const head = document.createElement('div');
    head.className = 'pane-head';
    const parts: Array<[string, string]> = [['type', typeLabel(meta.type)]];
    if (meta.branch) parts.push(['branch', meta.branch]);
    if (meta.commit) parts.push(['commit', meta.commit.slice(0, 7)]);
    parts.push(['agent', meta.agent], ['time', new Date(meta.createdAt).toLocaleString()]);
    for (const [cls, value] of parts) {
      const s = document.createElement('span');
      s.className = 'meta meta-' + cls;
      s.textContent = value;
      head.append(s);
    }
    if (meta.open && !meta.chosen) {
      const tag = document.createElement('span');
      tag.className = 'needs-choice';
      tag.textContent = 'Needs your choice';
      head.append(tag);
    }
    if (meta.type === 'plan' && meta.mode === 'handoff') {
      const hint = document.createElement('span');
      hint.className = 'plan-comment-hint';
      hint.textContent = 'Select text to comment';
      head.append(hint);
    }
    if (meta.agentSession || meta.type === 'plan') {
      const status = document.createElement('span');
      status.className = 'agent-session-status';
      status.setAttribute('role', 'status');
      status.textContent = meta.agentSession ? 'Checking session…' : 'No linked session';
      status.dataset.state = meta.agentSession ? 'checking' : 'unlinked';
      head.append(status);
    }
    return head;
  }

  return {
    clear() {
      token++;
      placeholder('Select a report');
    },
    showDraft(item: RunningItem) {
      const nextText = item.draftText ?? '';
      if (draftRunId !== item.id) {
        ++token;
        stopSession();
        current?.destroy();
        commentView?.destroy();
        commentView = null;
        feedbackView?.destroy();
        feedbackView = null;
        current = null;
        stopDraft();
        draftRunId = item.id;
        shownText = nextText;
        targetText = nextText;
        container.replaceChildren();
        const status = document.createElement('p');
        status.className = 'draft-status';
        status.textContent = `Writing ${typeLabel(item.type).toLowerCase()} report`;
        status.setAttribute('role', 'status');
        const sheet = container.ownerDocument.createElement('article');
        sheet.className = 'draft-document';
        const heading = container.ownerDocument.createElement('h1');
        heading.textContent = item.title || `${typeLabel(item.type)} report`;
        const copy = container.ownerDocument.createElement('div');
        copy.className = 'draft-copy';
        draftNode = container.ownerDocument.createTextNode(shownText);
        const cursor = container.ownerDocument.createElement('span');
        cursor.className = 'draft-cursor';
        cursor.setAttribute('aria-hidden', 'true');
        copy.append(draftNode, cursor);
        sheet.append(heading, copy);
        container.append(status, sheet);
        return;
      }
      if (nextText === targetText) return;
      if (!nextText.startsWith(shownText)) {
        clearInterval(draftTimer);
        draftTimer = undefined;
        shownText = nextText;
        targetText = nextText;
        if (draftNode) draftNode.nodeValue = shownText;
        return;
      }
      targetText = nextText;
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        clearInterval(draftTimer);
        draftTimer = undefined;
        shownText = targetText;
        if (draftNode) draftNode.nodeValue = shownText;
        return;
      }
      if (draftTimer) return;
      draftTimer = setInterval(() => {
        if (!draftNode || shownText.length >= targetText.length) {
          clearInterval(draftTimer);
          draftTimer = undefined;
          return;
        }
        const scroller = container.parentElement;
        const follow = !!scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
        const step = Math.max(1, Math.ceil((targetText.length - shownText.length) / 50));
        shownText = targetText.slice(0, shownText.length + step);
        draftNode.nodeValue = shownText;
        if (follow && scroller) scroller.scrollTop = scroller.scrollHeight;
      }, 20);
    },
    // Resolves true only when this report was rendered and is still the one shown.
    async show(projectId: string, reportId: string): Promise<boolean> {
      const mine = ++token;
      stopSession();
      stopDraft();
      let detail;
      try {
        detail = await api.getReport(projectId, reportId);
      } catch (e) {
        // Tauri rejects with a plain string.
        if (mine === token) placeholder('Could not open this report: ' + (e instanceof Error ? e.message : String(e)));
        return false;
      }
      if (mine !== token) return false;
      current?.destroy();
      commentView?.destroy();
      commentView = null;
      feedbackView?.destroy();
      feedbackView = null;
      container.replaceChildren();
      const head = header(detail.meta);
      const body = document.createElement('div');
      body.className = 'report-body';
      container.append(head, body);
      if (detail.meta.agentSession) {
        const badge = head.querySelector<HTMLElement>('.agent-session-status');
        let checking = false;
        const refreshSession = async () => {
          if (checking) return;
          checking = true;
          try {
            const status = await api.agentSessionStatus(projectId, reportId);
            if (mine !== token || !badge) return;
            badge.dataset.state = status.connected ? 'connected' : 'disconnected';
            badge.textContent = status.connected ? 'Session connected' : 'Session disconnected';
            badge.title = status.reason ?? 'Connected to the original agent session';
            if (feedbackView) void feedbackView.refresh();
          } catch (error) {
            if (mine !== token || !badge) return;
            badge.dataset.state = 'disconnected';
            badge.textContent = 'Session status unavailable';
            badge.title = error instanceof Error ? error.message : String(error);
          } finally {
            checking = false;
          }
        };
        void refreshSession();
        sessionTimer = setInterval(() => void refreshSession(), 5000);
      }
      current = renderReport(body, detail.page, {
        idPrefix: prefix,
        // A closed decision (a newer report exists) shows its options but cannot be chosen.
        connected: () => detail.meta.open,
        unavailableText: 'This question is closed. A newer report replaced it.',
        assetUrl: (rel) => api.assetUrl(detail.dir, rel),
        submitChoice: async (choice) => {
          let delivery;
          try {
            delivery = await api.submitChoice(projectId, reportId, detail.meta.version, choice);
          } catch (e) {
            // Tauri rejects with a plain string; the renderer shows error.message.
            throw e instanceof Error ? e : new Error(String(e));
          }
          head.querySelector('.needs-choice')?.remove();
          onChosen(reportId);
          return delivery;
        },
      });
      if (detail.meta.type === 'plan' && detail.meta.mode === 'handoff') {
        try {
          const comments = await api.listComments(projectId, reportId);
          if (mine === token) commentView = createPlanComments(body, comments,
            (anchor, text) => api.addComment(projectId, reportId, detail.meta.version, anchor, text),
            (commentId) => api.deleteComment(projectId, reportId, detail.meta.version, commentId),
            () => void feedbackView?.refresh());
        } catch (error) {
          if (mine === token) {
            const note = document.createElement('p');
            note.className = 'plan-comment-load-error';
            note.textContent = 'Could not load comments: ' + (error instanceof Error ? error.message : String(error));
            body.prepend(note);
          }
        }
        try {
          const [note, status] = await Promise.all([
            api.getPlanNote(projectId, reportId), api.feedbackStatus(projectId, reportId),
          ]);
          if (mine === token) feedbackView = createPlanFeedback(body, note, status, {
            saveNote: (text) => api.savePlanNote(projectId, reportId, detail.meta.version, text),
            status: () => api.feedbackStatus(projectId, reportId),
            submit: () => api.submitFeedback(projectId, reportId, detail.meta.version),
          });
        } catch (error) {
          if (mine === token) {
            const warning = document.createElement('p');
            warning.className = 'plan-comment-load-error';
            warning.textContent = 'Could not load the overall note: ' + (error instanceof Error ? error.message : String(error));
            body.append(warning);
          }
        }
      }
      if (mine !== token) return false;
      // The shared renderer sets the title to the page title; keep the app's own.
      document.title = 'Showwork · ' + detail.meta.title;
      return true;
    },
  };
}

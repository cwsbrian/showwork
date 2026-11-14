import type { FeedbackStatus, PlanNote } from '../api';

interface Actions {
  saveNote(body: string): Promise<PlanNote | null>;
  status(): Promise<FeedbackStatus>;
  submit(): Promise<void>;
}

export function createPlanFeedback(root: HTMLElement, note: PlanNote | null, initial: FeedbackStatus, actions: Actions, reportType: string) {
  let savedBody = note?.body ?? '';
  let state = initial;
  let busy = false;
  let destroyed = false;
  const section = document.createElement('section');
  section.className = 'plan-feedback';
  const heading = document.createElement('h2');
  heading.textContent = 'Overall note';
  const description = document.createElement('p');
  description.textContent = `Feedback about the whole ${reportType}`;
  const input = document.createElement('textarea');
  input.value = savedBody;
  input.maxLength = 20000;
  input.placeholder = `Write a note about the whole ${reportType}…`;
  input.setAttribute('aria-label', 'Overall note');
  const controls = document.createElement('div');
  controls.className = 'plan-feedback-controls';
  const saveButton = document.createElement('button');
  saveButton.type = 'button';
  saveButton.textContent = 'Save note';
  const submitButton = document.createElement('button');
  submitButton.type = 'button';
  submitButton.textContent = 'Submit feedback';
  const message = document.createElement('span');
  message.className = 'plan-feedback-status';
  message.setAttribute('role', 'status');
  controls.append(saveButton, submitButton, message);
  section.append(heading, description, input, controls);
  root.append(section);

  function sync() {
    const dirty = input.value.trim() !== savedBody;
    saveButton.disabled = busy || !dirty;
    submitButton.disabled = busy || !state.available || (!state.hasFeedback && !dirty) || (state.submitted && !dirty);
    if (!busy && !dirty && !message.dataset.error && !message.dataset.manual) {
      message.textContent = !state.available ? state.reason ?? 'Original agent session unavailable.'
        : state.submitted ? 'Sent to the original session.' : '';
    }
  }

  async function save() {
    const body = input.value.trim();
    const result = await actions.saveNote(body);
    if (destroyed) return;
    savedBody = result?.body ?? '';
    state = await actions.status();
  }

  input.addEventListener('input', () => { delete message.dataset.error; delete message.dataset.manual; message.textContent = ''; sync(); });
  saveButton.onclick = async () => {
    if (busy) return;
    busy = true;
    message.textContent = 'Saving…';
    sync();
    try {
      await save();
      if (destroyed) return;
      message.dataset.manual = 'true';
      message.textContent = 'Note saved.';
    } catch (error) {
      message.dataset.error = 'true';
      message.textContent = error instanceof Error ? error.message : String(error);
    } finally { busy = false; if (!destroyed) sync(); }
  };
  submitButton.onclick = async () => {
    if (busy || !state.available) return;
    busy = true;
    message.textContent = 'Submitting…';
    sync();
    try {
      if (input.value.trim() !== savedBody) await save();
      if (destroyed) return;
      await actions.submit();
      if (destroyed) return;
      state = await actions.status();
      message.dataset.manual = 'true';
      message.textContent = 'Sent to the original session.';
    } catch (error) {
      message.dataset.error = 'true';
      message.textContent = error instanceof Error ? error.message : String(error);
    } finally { busy = false; if (!destroyed) sync(); }
  };
  sync();
  return {
    async refresh() {
      try { state = await actions.status(); if (!destroyed) { delete message.dataset.manual; sync(); } }
      catch (error) {
        if (!destroyed) { message.dataset.error = 'true'; message.textContent = error instanceof Error ? error.message : String(error); }
      }
    },
    destroy() { destroyed = true; section.remove(); },
  };
}

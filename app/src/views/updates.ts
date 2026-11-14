import type { AppUpdate, ShowworkApi } from '../api';

const short = (revision: string) => revision.slice(0, 7);

export function createUpdates(host: HTMLElement, api: ShowworkApi) {
  const version = document.createElement('span');
  version.className = 'update-version';
  version.textContent = 'Showwork';

  const check = document.createElement('button');
  check.type = 'button';
  check.className = 'update-check';
  check.textContent = 'Check for updates';

  const install = document.createElement('button');
  install.type = 'button';
  install.className = 'update-install';
  install.textContent = 'Install update';
  install.hidden = true;

  const status = document.createElement('span');
  status.className = 'update-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  const notes = document.createElement('p');
  notes.className = 'update-notes';
  notes.hidden = true;

  const progress = document.createElement('progress');
  progress.className = 'update-progress';
  progress.max = 100;
  progress.hidden = true;

  const row = document.createElement('div');
  row.className = 'update-row';
  row.append(version, check, install);
  host.append(row, status, notes, progress);

  let available: AppUpdate | null = null;
  const busy = (value: boolean) => {
    check.disabled = value;
    install.disabled = value;
  };

  void Promise.all([api.getAppVersion(), api.getAppRevision()]).then(([current, revision]) => {
    version.textContent = `Showwork ${current} (${short(revision)})`;
  }).catch(() => {
    status.textContent = 'Could not read the app version.';
  });

  check.onclick = async () => {
    busy(true);
    install.hidden = true;
    notes.hidden = true;
    progress.hidden = true;
    status.textContent = 'Checking for updates…';
    try {
      available = null;
      const [current, installedRevision, repositoryRevision] = await Promise.all([
        api.getAppVersion(), api.getAppRevision(), api.getRepositoryRevision(),
      ]);
      version.textContent = `Showwork ${current} (${short(installedRevision)})`;
      if (installedRevision === repositoryRevision) {
        status.textContent = `Up to date with GitHub main (${short(repositoryRevision)}).`;
        return;
      }
      let candidate: AppUpdate | null;
      try {
        candidate = await api.checkAppUpdate();
      } catch (error) {
        status.textContent = `GitHub main: ${short(repositoryRevision)}. Installed: ${short(installedRevision)}. Could not check the signed app build: ${error instanceof Error ? error.message : String(error)}`;
        return;
      }
      if (candidate?.notes?.split(/\r?\n/).some((line) => line.trim() === `Source commit: ${repositoryRevision}`)) {
        available = candidate;
        status.textContent = `GitHub main: ${short(repositoryRevision)}. Installed: ${short(installedRevision)}. Update ${candidate.version} ready.`;
        install.hidden = false;
        if (available.notes?.trim()) {
          notes.textContent = available.notes;
          notes.hidden = false;
        }
      } else {
        candidate && await api.closeAppUpdate();
        status.textContent = `GitHub main: ${short(repositoryRevision)}. Installed: ${short(installedRevision)}. The matching signed app build is not published yet.`;
      }
    } catch (error) {
      available = null;
      status.textContent = `Could not check GitHub for updates: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      busy(false);
    }
  };

  install.onclick = async () => {
    if (!available) return;
    const targetVersion = available.version;
    busy(true);
    progress.hidden = false;
    progress.removeAttribute('value');
    status.textContent = `Downloading version ${targetVersion}…`;
    try {
      await api.installAppUpdate(({ downloaded, total }) => {
        if (total && total > 0) {
          const percent = Math.min(100, Math.round(downloaded / total * 100));
          progress.value = percent;
          status.textContent = `Downloading version ${targetVersion}… ${percent}%`;
        } else {
          status.textContent = `Downloading version ${targetVersion}…`;
        }
      });
      available = null;
      install.hidden = true;
      progress.hidden = true;
      status.textContent = 'Update installed. Restarting Showwork…';
    } catch (error) {
      progress.hidden = true;
      status.textContent = `Could not install the update: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      busy(false);
    }
  };
}

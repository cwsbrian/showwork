let open: HTMLElement | null = null;
let returnFocus: HTMLElement | null = null;

function close(restoreFocus = false) {
  open?.remove();
  open = null;
  if (restoreFocus && returnFocus?.isConnected) returnFocus.focus();
  returnFocus = null;
}

// An item with `confirm` needs two clicks: the first only changes its label to the confirm text.
export function showMenu(x: number, y: number, items: Array<{ label: string; run: () => void; confirm?: string }>, trigger?: HTMLElement) {
  close();
  returnFocus = trigger ?? null;
  const menu = document.createElement('div');
  menu.className = 'ctx-menu';
  menu.setAttribute('role', 'menu');
  for (const item of items) {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'menuitem');
    b.textContent = item.label;
    b.onclick = (e) => {
      if (item.confirm && !b.dataset.armed) {
        e.stopPropagation();
        b.dataset.armed = 'true';
        b.textContent = item.confirm;
        return;
      }
      close();
      item.run();
    };
    menu.append(b);
  }
  menu.style.left = Math.min(x, window.innerWidth - 180) + 'px';
  menu.style.top = Math.min(y, window.innerHeight - items.length * 36 - 8) + 'px';
  document.body.append(menu);
  open = menu;
  (menu.firstChild as HTMLElement | null)?.focus();
}

document.addEventListener('click', () => close());
document.addEventListener('keydown', (e) => e.key === 'Escape' && close(true));
window.addEventListener('blur', () => close());

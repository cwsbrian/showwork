export interface Cdp {
  mouse(type: 'mousePressed' | 'mouseReleased' | 'mouseMoved', x: number, y: number, clickCount: number): void;
  wheel(x: number, y: number, dx: number, dy: number): void;
  key(type: 'rawKeyDown' | 'keyUp', e: { key: string; code: string; keyCode: number }): void;
  text(s: string): void;
  navigate(url: string): void;
  resize(width: number, height: number): void;
  close(): void;
}

export function connect(ws: string, on: {
  frame(jpegBase64: string, deviceWidth: number, deviceHeight: number): void;
  url(url: string): void;
  closed(): void;
}): Promise<Cdp> {
  return new Promise((resolve, reject) => {
    let socket: WebSocket;
    try { socket = new WebSocket(ws); } catch (error) { reject(error); return; }
    let id = 0;
    let opened = false;
    let finished = false;
    const send = (method: string, params: Record<string, unknown> = {}) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ id: ++id, method, params }));
    };
    socket.onopen = () => {
      opened = true;
      send('Page.enable');
      send('Page.startScreencast', { format: 'jpeg', quality: 70, everyNthFrame: 1 });
      resolve({
        mouse: (type, x, y, clickCount) => send('Input.dispatchMouseEvent', { type, x, y, button: type === 'mouseMoved' ? 'none' : 'left', clickCount }),
        wheel: (x, y, dx, dy) => send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: dx, deltaY: dy }),
        key: (type, e) => send('Input.dispatchKeyEvent', { type, key: e.key, code: e.code, windowsVirtualKeyCode: e.keyCode, nativeVirtualKeyCode: e.keyCode }),
        text: (s) => send('Input.insertText', { text: s }),
        navigate: (url) => send('Page.navigate', { url }),
        resize: (width, height) => send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false }),
        close: () => { send('Page.stopScreencast'); socket.close(); },
      });
    };
    socket.onmessage = (event) => {
      let msg: any;
      try { msg = JSON.parse(event.data); } catch { return; }
      if (msg.method === 'Page.screencastFrame') {
        const data = msg.params;
        send('Page.screencastFrameAck', { sessionId: data.sessionId });
        on.frame(data.data, data.metadata?.deviceWidth ?? 0, data.metadata?.deviceHeight ?? 0);
      } else if (msg.method === 'Page.frameNavigated' && !msg.params?.frame?.parentId) {
        on.url(msg.params.frame.url);
      }
    };
    const ended = () => {
      if (finished) return;
      finished = true;
      if (!opened) reject(new Error('WebSocket connection failed'));
      on.closed();
    };
    socket.onerror = ended;
    socket.onclose = ended;
  });
}

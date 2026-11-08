"""Bounded Android Emulator screenshot and input relay."""
import argparse
import json
import math
import os
import re
import selectors
import signal
import struct
import subprocess
import threading
import time
import zlib
from device_relay import make_server

MAX_FRAME = 8 * 1024 * 1024
MAX_DECODED_FRAME = 64 * 1024 * 1024


def png_dimensions(png: bytes) -> tuple[int, int]:
    if (len(png) < 33 or len(png) > MAX_FRAME or
            png[:8] != b'\x89PNG\r\n\x1a\n' or
            png[8:16] != b'\x00\x00\x00\rIHDR' or
            zlib.crc32(png[12:29]) != int.from_bytes(png[29:33], 'big')):
        raise ValueError('Invalid PNG IHDR')
    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', png[16:29])
    # screencap emits non-interlaced 8-bit RGB/RGBA. Reject other formats
    # explicitly rather than claiming readiness for an unvalidated image.
    if (not 0 < width < 2**31 or not 0 < height < 2**31 or depth != 8 or
            color not in (2, 6) or compression or filtering or interlace):
        raise ValueError('Unsupported PNG format or dimensions')
    stride = 1 + width * (3 if color == 2 else 4)
    expected = stride * height
    if expected > MAX_DECODED_FRAME:
        raise ValueError('Decoded PNG exceeds 64 MiB')
    offset, idat_ended = 33, False
    image_data = bytearray()
    saw_idat = saw_end = False
    while offset < len(png):
        if offset + 12 > len(png): raise ValueError('Truncated PNG chunk')
        length = int.from_bytes(png[offset:offset+4], 'big')
        end = offset + 12 + length
        if end > len(png): raise ValueError('Truncated PNG chunk')
        kind = png[offset+4:offset+8]
        data = png[offset+8:end-4]
        if (not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind) or kind[2] & 32 or
                zlib.crc32(png[offset+4:end-4]) != int.from_bytes(png[end-4:end], 'big')):
            raise ValueError('Invalid PNG chunk')
        if kind == b'IDAT':
            if idat_ended: raise ValueError('Nonconsecutive PNG image data')
            saw_idat = True
            image_data.extend(data)
        elif kind == b'IEND':
            if length or not saw_idat or end != len(png): raise ValueError('Invalid PNG end')
            saw_end = True
        else:
            if saw_idat: idat_ended = True
            if kind == b'PLTE':
                if saw_idat or not length or length % 3 or length > 768:
                    raise ValueError('Invalid PNG palette')
            elif not kind[0] & 32:
                raise ValueError('Unknown or misplaced PNG critical chunk')
        offset = end
    if not saw_end: raise ValueError('Incomplete PNG')
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(image_data, expected + 1)
    except zlib.error:
        raise ValueError('Invalid PNG image data') from None
    if (len(pixels) != expected or not decoder.eof or decoder.unused_data or
            decoder.unconsumed_tail or any(pixels[i] > 4 for i in range(0, expected, stride))):
        raise ValueError('Invalid PNG scanlines')
    return width, height


def capture_png(adb_path: str, serial: str, stop: threading.Event) -> bytes:
    if stop.is_set(): raise RuntimeError('Relay stopped')
    child = subprocess.Popen([adb_path, '-s', serial, 'exec-out', 'screencap', '-p'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = bytearray()
    deadline = time.monotonic() + 5
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if stop.is_set(): raise RuntimeError('Relay stopped')
                if remaining <= 0: raise ValueError('Capture timed out')
                if not selector.select(min(.05, remaining)): continue
                chunk = os.read(child.stdout.fileno(), min(65536, MAX_FRAME + 1 - len(data)))
                if not chunk: break
                data.extend(chunk)
                if len(data) > MAX_FRAME: raise ValueError('PNG exceeds 8 MiB')
            while child.poll() is None:
                if stop.wait(.01): raise RuntimeError('Relay stopped')
                if time.monotonic() >= deadline: raise ValueError('Capture timed out')
            if child.returncode: raise ValueError('Capture failed')
        frame = bytes(data)
        png_dimensions(frame)
        return frame
    finally:
        # Kill directly: even an adb ignoring SIGTERM cannot extend the deadline.
        if child.poll() is None:
            try: child.kill()
            except ProcessLookupError: pass
        child.wait()
        child.stdout.close()


class AndroidRelayState:
    content_type = 'image/png'
    width_header = 'X-Pixels-Width'
    height_header = 'X-Pixels-Height'

    def __init__(self, serial: str, token: str, origins: set[str], adb_path: str):
        if not re.fullmatch(r'emulator-[0-9]+', serial) or not token:
            raise ValueError('Explicit emulator serial and token required')
        self.serial, self.token, self.origins, self.adb_path = serial, token, origins, adb_path
        self.condition = threading.Condition()
        self.input_lock = threading.Lock()
        self.input_child = None
        self.frame, self.seq, self.reason = None, 0, None
        self.pixels_width = self.pixels_height = 0

    def frame_dimensions(self) -> tuple[int, int]:
        return self.pixels_width, self.pixels_height

    def health_payload(self) -> dict:
        return {'ready': self.frame is not None and self.reason is None,
                'pixels_width': self.pixels_width, 'pixels_height': self.pixels_height}

    def publish_frame(self, png: bytes):
        width, height = png_dimensions(png)
        with self.condition:
            if self.reason is not None: return
            self.frame = png
            self.pixels_width, self.pixels_height = width, height
            self.seq += 1
            self.condition.notify_all()

    def finish(self, reason: str):
        with self.condition:
            if self.reason is None: self.reason = reason
            self.frame = None
            self.condition.notify_all()
            # The same condition guards input startup: after reason is set no
            # handler can create a child, and any already-created child is reaped.
            if self.input_child is not None:
                child = self.input_child
                if child.poll() is None:
                    try: child.kill()
                    except ProcessLookupError: pass
                child.wait()
                self.input_child = None

    def capture_loop(self, stop: threading.Event):
        failures = 0
        while not stop.is_set():
            try:
                self.publish_frame(capture_png(self.adb_path, self.serial, stop))
                failures = 0
            except (OSError, ValueError, RuntimeError):
                failures += 1
                if failures >= 3:
                    self.finish('Three consecutive capture failures')
                    return
            with self.condition:
                if self.reason is not None: return
            # Space completed captures too, so publication never exceeds four Hz.
            if stop.wait(.25): break
        self.finish('Relay stopped')

    def run_input(self, action: dict) -> None:
        with self.input_lock:
            if not isinstance(action, dict): raise ValueError('Action must be an object')
            with self.condition:
                if self.reason is not None or self.frame is None: raise RuntimeError('Stream unavailable')
                width, height = self.frame_dimensions()
            def coordinate(key, limit):
                value = action.get(key)
                if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                        (isinstance(value, float) and (not math.isfinite(value) or not value.is_integer())) or
                        not 0 <= value < limit):
                    raise ValueError('Invalid pixel coordinate')
                return str(int(value))
            kind = action.get('type')
            if kind == 'tap': args = ['tap', coordinate('x', width), coordinate('y', height)]
            elif kind == 'swipe':
                duration = action.get('duration')
                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not .05 <= duration <= 2:
                    raise ValueError('Invalid swipe duration')
                args = ['swipe', coordinate('x1', width), coordinate('y1', height),
                        coordinate('x2', width), coordinate('y2', height), str(round(duration * 1000))]
            else: raise ValueError('Unknown action')
            child = None
            try:
                with self.condition:
                    if self.reason is not None: raise RuntimeError('Stream unavailable')
                    child = subprocess.Popen([self.adb_path, '-s', self.serial, 'shell', 'input', *args],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.input_child = child
                if child.wait(timeout=5): raise RuntimeError('Input command failed')
                with self.condition:
                    if self.reason is not None: raise RuntimeError('Stream unavailable')
            except (OSError, subprocess.SubprocessError, RuntimeError):
                self.finish('Input command failed')
                raise RuntimeError('Input command failed') from None
            finally:
                with self.condition:
                    if child is not None:
                        if child.poll() is None:
                            try: child.kill()
                            except ProcessLookupError: pass
                        child.wait()
                        if self.input_child is child: self.input_child = None



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['serve'])
    for arg in ('serial', 'session', 'adb-path'): parser.add_argument('--' + arg, required=True)
    args = parser.parse_args()
    state = AndroidRelayState(args.serial, os.environ.get('SHOWWORK_ANDROID_TOKEN', ''),
                              set(os.environ.get('SHOWWORK_ANDROID_ORIGINS', 'tauri://localhost,http://localhost:1420').split(',')), args.adb_path)
    stop = threading.Event()
    def shutdown(*_):
        stop.set()
        state.finish('Relay stopped')
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server = make_server(state)
    worker = threading.Thread(target=state.capture_loop, args=(stop,), daemon=True)
    serving = None
    worker.start()
    try:
        with state.condition:
            state.condition.wait_for(lambda: state.frame is not None or state.reason is not None, timeout=20)
            if state.frame is None or state.reason is not None: return 1
            width, height = state.frame_dimensions()
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        print(json.dumps({'port': server.server_port, 'width': width, 'height': height}), flush=True)
        while not stop.wait(.1):
            if state.reason is not None:
                stop.wait(.2)
                break
    finally:
        stop.set()
        state.finish('Relay stopped')
        worker.join(timeout=6)
        if serving is not None: server.shutdown()
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

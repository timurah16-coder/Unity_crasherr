"""Unity Crasher: tray, automatic Unity detection and global Num Lock test crash."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import json
import os
from pathlib import Path
import threading
import time

import psutil
import pystray
from PIL import Image, ImageDraw

LOG = Path(__file__).with_name('unity_crasher.log')
logging.basicConfig(filename=LOG, level=logging.INFO, encoding='utf-8',
                    format='%(asctime)s %(levelname)s %(message)s')


def detect() -> list[tuple[int, float, str]]:
    found = []
    for process in psutil.process_iter(['pid', 'name', 'create_time', 'exe']):
        try:
            data = process.info
            executable = Path(data['exe'] or '')
            if (data['name'] or '').casefold() == 'unity.exe':
                found.append((data['pid'], data['create_time'], str(executable)))
        except (psutil.Error, OSError):
            continue
    return sorted(found)


def crash(target: tuple[int, float, str]) -> None:
    pid, created, expected_path = target
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    handle = kernel.OpenProcess(0x1FFFFF, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        stamps = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(stamp) for stamp in stamps)):
            raise ctypes.WinError(ctypes.get_last_error())
        started = ((stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime) / 10_000_000 - 11644473600
        if abs(started - created) > .01 or os.path.normcase(buffer.value) != os.path.normcase(expected_path):
            raise RuntimeError('Process changed since detection; refresh and try again.')
        folder = Path(os.environ['LOCALAPPDATA']) / 'UnityCrasher'
        ready = folder / f'{pid}.ready.json'
        if not ready.is_file() or time.time() - ready.stat().st_mtime > 10:
            raise RuntimeError('Unity crash bridge is not ready. Import UnityCrasherBridge.cs into Assets/Editor and let Unity compile it.')
        endpoint = json.loads(ready.read_text(encoding='utf-8-sig'))
        if endpoint.get('pid') != pid or abs(endpoint.get('started', 0) - created) > .01:
            raise RuntimeError('Stale Unity bridge identity; no request sent.')
        signal = folder / f'{pid}.request.json'
        temporary = signal.with_suffix('.tmp')
        temporary.write_text(json.dumps({'token': endpoint['token'], 'requested': time.time()}), encoding='utf-8')
        temporary.replace(signal)
        logging.info('Unity ForceCrash AccessViolation requested: PID %s', pid)
        status = kernel.WaitForSingleObject(handle, 5000)
        if status == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if status == 0:
            logging.info('Unity process exit confirmed: PID %s', pid)
        else:
            logging.warning('Unity process has not exited after 5 seconds: PID %s; editor may be busy or showing crash UI', pid)
    finally:
        kernel.CloseHandle(handle)


class App:
    def __init__(self):
        self.targets = []
        self.selected = None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.hotkey_thread_id = None
        self.hotkey_ready = threading.Event()
        self.hotkey_error = None
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill='#242833')
        draw.polygon([(35, 8), (18, 35), (30, 35), (25, 56), (48, 27), (35, 27)], fill='#ffb648')
        self.icon = pystray.Icon('unity_crasher', image, 'Unity Crasher — Num Lock',
                                 menu=pystray.Menu(self.menu))

    def target_item(self, target):
        def choose(icon, item):
            with self.lock:
                self.selected = target
            icon.update_menu()

        def checked(item):
            with self.lock:
                return self.selected == target

        return pystray.MenuItem(f'{Path(target[2]).name} — PID {target[0]}',
                                choose, checked=checked, radio=True)

    def menu(self):
        with self.lock:
            targets = self.targets[:]
            selected = self.selected
        yield pystray.MenuItem('Num Lock: crash selected Unity (unsaved work is lost)', None, enabled=False)
        if not targets:
            yield pystray.MenuItem('Waiting for Unity...', None, enabled=False)
        for target in targets:
            yield self.target_item(target)
        yield pystray.MenuItem('Crash now (Num Lock)', self.trigger, enabled=selected is not None)
        yield pystray.MenuItem('Exit', self.quit)

    def scan(self):
        while not self.stopped.is_set():
            try:
                targets = detect()
                with self.lock:
                    changed = targets != self.targets
                    self.targets = targets
                    if self.selected not in targets:
                        self.selected = targets[0] if len(targets) == 1 else None
                    selected = self.selected
                self.icon.title = f'Unity Crasher — {len(targets)} found — Num Lock' if selected else 'Unity Crasher — select a target'
                if changed:
                    self.icon.update_menu()
            except Exception:
                logging.exception('Detection failed')
            self.stopped.wait(2)

    def trigger(self, icon=None, item=None):
        with self.lock:
            target = self.selected
        if target is None:
            logging.info('Hotkey ignored: no single target selected')
            return
        try:
            crash(target)
        except Exception as error:
            logging.exception('Crash request failed')

    def hotkeys(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentThreadId.restype = wintypes.DWORD
        user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user.RegisterHotKey.restype = wintypes.BOOL
        user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user.GetMessageW.restype = wintypes.BOOL
        self.hotkey_thread_id = kernel.GetCurrentThreadId()
        if not user.RegisterHotKey(None, 1, 0x4000, 0x90):  # MOD_NOREPEAT, VK_NUMLOCK
            self.hotkey_error = ctypes.WinError(ctypes.get_last_error())
            self.hotkey_ready.set()
            return
        self.hotkey_ready.set()
        try:
            message = wintypes.MSG()
            while not self.stopped.is_set():
                result = user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == 0x0312:
                    self.trigger()
        finally:
            user.UnregisterHotKey(None, 1)

    def quit(self, icon=None, item=None):
        self.stopped.set()
        if self.hotkey_thread_id:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)
        self.icon.stop()

    def run(self):
        worker = threading.Thread(target=self.hotkeys, daemon=True)
        worker.start()
        self.hotkey_ready.wait(5)
        if self.hotkey_error or not self.hotkey_ready.is_set():
            raise RuntimeError(f'Cannot register Num Lock (another instance/app may own it): {self.hotkey_error}')
        def setup(icon):
            icon.visible = True
            threading.Thread(target=self.scan, daemon=True).start()
        try:
            self.icon.run(setup)
        finally:
            self.quit()
            worker.join(timeout=2)


def main():
    if os.name != 'nt':
        raise SystemExit('Windows only.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    mutex = kernel.CreateMutexW(None, False, 'Local\\Timur_UnityCrasher_Tray')
    error_code = ctypes.get_last_error()
    if not mutex:
        raise ctypes.WinError(error_code)
    if error_code == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle(mutex)
        logging.info('Already running; duplicate launch ignored')
        return
    try:
        logging.info('Starting tray with Num Lock hotkey')
        App().run()
    except Exception as error:
        logging.exception('Startup failed')
        ctypes.windll.user32.MessageBoxW(None, str(error), 'Unity Crasher', 0x10)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    main()

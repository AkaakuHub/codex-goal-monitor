import ctypes
import os
import struct
from collections.abc import Callable
from pathlib import Path


class Inotify:
    def __init__(self, callback: Callable[[Path, int], None]):
        self.lib = ctypes.CDLL('libc.so.6', use_errno=True)
        self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'inotify_init1')
        self.paths: dict[int, Path] = {}
        self.recursive: set[Path] = set()
        self.callback = callback

    def add(self, path: Path, recursive: bool = False) -> None:
        if not path.is_dir():
            return
        if recursive:
            self.recursive.add(path)
        if path not in self.paths.values():
            wd = self.lib.inotify_add_watch(self.fd, os.fsencode(path), 0x100 | 0x80 | 0x200 | 0x2 | 0x400 | 0x800)
            if wd < 0:
                if ctypes.get_errno() == 2:
                    return
                raise OSError(ctypes.get_errno(), str(path))
            self.paths[wd] = path
        if recursive:
            for parent, dirs, _ in os.walk(path):
                for name in dirs:
                    self.add(Path(parent) / name)

    def ready(self) -> None:
        try:
            data = os.read(self.fd, 1024 * 1024)
        except BlockingIOError:
            return
        pos = 0
        while pos < len(data):
            wd, mask, _, length = struct.unpack_from('iIII', data, pos)
            name = os.fsdecode(data[pos + 16:pos + 16 + length].split(b'\0', 1)[0])
            pos += 16 + length
            parent = self.paths.get(wd)
            if mask & 0x4000:
                self.callback(Path('/'), mask)
            elif parent:
                path = parent / name
                if mask & 0x40000000 and mask & (0x100 | 0x80) and any(parent == root or root in parent.parents for root in self.recursive):
                    self.add(path, recursive=True)
                self.callback(path, mask)
            if mask & 0x8000:
                self.paths.pop(wd, None)

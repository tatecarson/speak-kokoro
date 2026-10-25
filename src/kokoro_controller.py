"""Desktop client: background work and playback events, with no UI imports."""
import json
import queue
import socket
import subprocess
import threading

import kokoro_runtime as runtime
from kokoro_cli import start_daemon, validate_settings


class ReaderController:
    def __init__(self):
        self.events = queue.Queue()
        self.jobs = queue.Queue()
        self.closed = threading.Event()
        self.connected = threading.Event()
        self.cancel = threading.Event()
        self.connection = None
        self.children = []
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self.watcher = threading.Thread(target=self._watch, daemon=True)
        self.watcher.start()

    def _post(self, event, **fields):
        if not self.closed.is_set():
            self.events.put({"ev": event, **fields})

    def _work(self):
        while not self.closed.is_set():
            job = self.jobs.get()
            if job is None:
                return
            cancel, operation = job
            if cancel.is_set():
                continue
            try:
                operation(cancel)
            except InterruptedError:
                pass
            except Exception as exc:
                if not cancel.is_set():
                    self._post("client_error", message=str(exc))

    @staticmethod
    def _send(command):
        with runtime.connect(timeout=1) as connection:
            connection.sendall(command.encode("utf-8"))
            connection.shutdown(socket.SHUT_WR)

    def read(self, text, voice, speed):
        voice, speed = validate_settings(voice, speed)
        if not text.strip():
            raise ValueError("Paste or type some text first.")
        command = f"SAY {voice} {speed} {text}"
        if len(command.encode("utf-8")) > runtime.MAX_REQUEST - 128:
            raise ValueError("This text is too long. Please read it in smaller sections.")
        self.cancel.set()
        self.cancel = threading.Event()

        def begin(cancel):
            child = start_daemon(voice, cancel_event=cancel)
            if child is not None:
                self.children.append(child)
            # The WATCH acknowledgement ensures we see even a short utterance.
            # Older daemons do not acknowledge; their snapshots still work.
            self.connected.wait(timeout=3)
            if not cancel.is_set() and not self.closed.is_set():
                self._send(command)
        self.jobs.put((self.cancel, begin))

    def control(self, command):
        if command not in ("STOP", "TOGGLE", "NEXT", "PREV"):
            raise ValueError("Unknown playback control")
        if command == "STOP":
            self.cancel.set()
            # Stop must not wait behind a model that is still loading.
            def stop():
                try:
                    self._send("STOP")
                except (OSError, ValueError, KeyError):
                    pass
            threading.Thread(target=stop, daemon=True).start()
        else:
            self.jobs.put((self.cancel, lambda _: self._send(command)))

    def configure(self, voice, speed):
        voice, speed = validate_settings(voice, speed)
        self.jobs.put((self.cancel, lambda _: self._send(f"SET {voice} {speed}")))

    def _watch(self):
        while not self.closed.is_set():
            try:
                with runtime.connect(timeout=0.5) as connection:
                    self.connection = connection
                    connection.sendall(b"WATCH")
                    connection.shutdown(socket.SHUT_WR)
                    connection.settimeout(None)
                    with connection.makefile("rb") as stream:
                        for line in stream:
                            event = json.loads(line)
                            if event.get("ev") == "ready":
                                self.connected.set()
                            if not self.closed.is_set():
                                self.events.put(event)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            finally:
                if self.connected.is_set():
                    self._post("disconnected")
                self.connected.clear()
                self.connection = None
            self.closed.wait(0.5)

    def close(self):
        if self.closed.is_set():
            return
        self.cancel.set()
        self.closed.set()
        self.jobs.put(None)
        try:
            self._send("QUIT")
        except (OSError, ValueError, KeyError):
            pass
        connection = self.connection
        if connection:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # Let an in-flight cold start terminate its child before this process exits.
        self.worker.join(timeout=1)
        for child in self.children:
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=3)


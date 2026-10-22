"""MODEL — writing the PDFs in a separate process.

Writing a PDF full of notes keeps the PDF library busy for a while, and while it
works the rest of the Python program (the server answering the iPad) has to
wait for it, even in another thread. Writing in a separate process leaves the
server free: strokes and "undo" are answered at once even during a save.

The process is started at the first save and reused. If it cannot be used
(e.g. it was killed), the PDF is written in the server process, as before.
"""
import multiprocessing
import multiprocessing.connection
import os
import pickle
import signal
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from . import pdf_store

_lock = threading.Lock()
_executor = None
_disabled = False


def _start_writer():
    """Runs in the writer process when it starts."""
    # Ctrl+C on the server reaches the whole process group: the server shuts down
    # in order (and saves what is open); the writer just finishes its work.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # If the server ends abruptly (killed, crashed), the writer ends with it
    # instead of staying in memory: it waits for the server process to finish.
    parent = multiprocessing.parent_process()
    if parent is not None:
        def watch():
            multiprocessing.connection.wait([parent.sentinel])
            os._exit(0)
        threading.Thread(target=watch, daemon=True).start()


def _get_executor():
    global _executor
    with _lock:
        if _executor is None and not _disabled:
            # "spawn": the same on Linux and Windows, and safe with the server's threads.
            _executor = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                                            initializer=_start_writer)
        return _executor


def _reset(disable=False):
    global _executor, _disabled
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
        _disabled = _disabled or disable


def save_document(path: Path, layer: dict, base_revision: str, pagecache: Path,
                  pictures_dir: Path | None = None):
    """Same as pdf_store.save_document (same result and exceptions), written by
    the separate process."""
    for attempt in range(2):
        executor = _get_executor()
        if executor is None:
            break
        try:
            return executor.submit(pdf_store.save_document, path, layer, base_revision, pagecache,
                                   pictures_dir=pictures_dir).result()
        except (BrokenProcessPool, pickle.PicklingError):
            # Writer process lost (or unusable): a new one, then give up on it. The
            # errors of the writing itself (file changed, disk full…) arrive as they are.
            _reset(disable=attempt == 1)
    return pdf_store.save_document(path, layer, base_revision, pagecache, pictures_dir=pictures_dir)


def shutdown():
    _reset(disable=True)

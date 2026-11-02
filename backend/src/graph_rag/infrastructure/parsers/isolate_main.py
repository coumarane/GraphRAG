"""Subprocess entry for one native parser call.

The worker must not ``fork`` after PDFium or OpenMP is loaded. Those libraries
install ``pthread_atfork`` handlers that raise SIGILL (container exit 132) in
the parent. ``subprocess`` uses ``posix_spawn`` and keeps that signal in the
child.
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit(2)
    job_path, result_path = args
    fn, call_args, kwargs = pickle.loads(Path(job_path).read_bytes())  # noqa: S301
    try:
        payload = ("ok", fn(*call_args, **kwargs))
    except Exception as exc:
        payload = ("err", type(exc).__name__, str(exc))
    Path(result_path).write_bytes(pickle.dumps(payload))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""A stand-in ffmpeg that pretends to have a GPU, for testing fallbacks.

GPU commands (VA-API or NVENC) are rewritten into the equivalent CPU
command and run with the real ffmpeg, so they produce real video. The
environment decides how the "GPU" misbehaves:

  FAKE_GPU_BROKEN=1          every GPU command fails immediately
  FAKE_GPU_FAIL_MATCH=text   GPU runs of inputs whose path contains `text`
                             crash after FAKE_GPU_FAIL_AFTER_S seconds
  FAKE_GPU_LOG=path          one line per run: "gpu <input> <-ss>" or "cpu ..."
  REAL_FFMPEG=path           the real ffmpeg (default: ffmpeg)
"""

import os
import subprocess
import sys
import time

REMOVE_WITH_VALUE = {
    "-init_hw_device",
    "-filter_hw_device",
    "-hwaccel",
    "-hwaccel_device",
    "-rc_mode",
    "-rc",
    "-tune",
    "-forced-idr",
    "-gpu",
}


def main() -> int:
    args = sys.argv[1:]
    real = os.environ.get("REAL_FFMPEG", "ffmpeg")
    is_gpu = "h264_vaapi" in args or "h264_nvenc" in args
    source = args[args.index("-i") + 1] if "-i" in args else ""
    seek = args[args.index("-ss") + 1] if "-ss" in args else "0"
    log = os.environ.get("FAKE_GPU_LOG")
    if log and source and not source.startswith(("color=", "testsrc", "anullsrc")):
        with open(log, "a") as f:
            f.write(f"{'gpu' if is_gpu else 'cpu'} {source} {seek}\n")

    if not is_gpu:
        os.execvp(real, [real, *args])

    if os.environ.get("FAKE_GPU_BROKEN"):
        sys.stderr.write("Failed to initialise VAAPI connection: -1 (unknown libva error).\n")
        return 187

    out: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in REMOVE_WITH_VALUE:
            i += 2
            continue
        if a in ("h264_vaapi", "h264_nvenc"):
            out.append("libx264")
        elif a == "p4":
            out.append("veryfast")
        else:
            out.append(a.replace(",format=nv12,hwupload", ""))
        i += 1

    match = os.environ.get("FAKE_GPU_FAIL_MATCH")
    if not (match and match in source):
        os.execvp(real, [real, *out])

    proc = subprocess.Popen([real, *out])
    deadline = time.monotonic() + float(os.environ.get("FAKE_GPU_FAIL_AFTER_S", "3"))
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return proc.returncode
        time.sleep(0.05)
    proc.kill()
    proc.wait()
    sys.stderr.write(
        "Error while processing the decoded data for stream #0:0 (simulated GPU fault)\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

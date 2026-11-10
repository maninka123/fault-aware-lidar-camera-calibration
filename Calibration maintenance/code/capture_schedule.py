"""A cancellable capture sequence, with manual triggers or waits after completion."""
import math
import time


def run_sequence(capture, count, stop, progress, next_capture=None, interval=0):
    results = []
    for index in range(count):
        if stop.is_set():
            raise InterruptedError("Capture sequence stopped")
        if index and next_capture is not None:
            progress(dict(k=index, waiting=True))
            while not next_capture.wait(0.1):
                if stop.is_set():
                    raise InterruptedError("Capture sequence stopped")
            next_capture.clear()
        elif index and interval > 0:
            end = time.monotonic() + interval
            while time.monotonic() < end:
                remaining = end - time.monotonic()
                progress(dict(k=index, countdown=math.ceil(max(0, remaining))))
                if stop.wait(min(1.0, max(0, remaining))):
                    raise InterruptedError("Capture sequence stopped")
        if stop.is_set():
            raise InterruptedError("Capture sequence stopped")
        result = capture(index)
        if stop.is_set():
            raise InterruptedError("Capture sequence stopped")
        results.append(result)
        progress(dict(k=index, done=True, images=result["images"], clouds=result["lidar_frames"], image=None, summary=result))
    return results

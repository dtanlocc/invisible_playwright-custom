"""How much does answering the protocol IN PROCESS actually cost?

⛔ THE QUESTION IS NARROW ON PURPOSE. Not "is the Python path faster than the
Node driver" - that comparison is dominated by the browser and would answer a
different question. This measures ONLY the machinery this package adds between
`Channel.send` and the code that talks to Juggler: building the message dict,
the queue, the worker-thread hop, the reply, and `call_soon_threadsafe` back
onto the loop.

That is the thing the owner asked about on 2026-08-28: inside one process,
serialising to yourself looks like waste. Whether it IS waste depends on how it
compares to the round trip it wraps, and this project decides that kind of
question with a number.

⛔ NO BROWSER, and that is what makes this trustworthy. A fake server answers
instantly, so what is left in the measurement is the transport and nothing
else. It also means the result does not depend on the machine being quiet in
the way a browser measurement does - though a loaded machine still widens the
tail, which is why the median is reported next to the mean.

    python scripts/bench_transport.py
    python scripts/bench_transport.py --giri 20000
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: What a real Juggler round trip costs, measured on 2026-08-27 with the
#: shipped binary. It is the denominator: the transport's cost only means
#: something as a fraction of the work it wraps.
#: ⛔ `Runtime.evaluate("1")` and NOT `Heap.collectGarbage`, which was used once
#: as a "bare command" and actually collects garbage - 26,8 ms of browser work
#: attributed to the transport.
JUGGLER_ROUND_TRIP_MS = 2.4


class FakeServer:
    """Answers instantly, so only the transport is being timed."""

    def __init__(self) -> None:
        self.transport = None

    def attach(self, transport) -> None:
        self.transport = transport

    def shutdown(self) -> None:
        pass

    def handle(self, message):
        return {"value": message["params"].get("n")}


async def run(rounds: int) -> int:
    from invisible_playwright._juggler.transport import InProcessTransport

    loop = asyncio.get_running_loop()
    transport = InProcessTransport(loop, FakeServer())
    await transport.connect()

    pending = {}

    def on_message(message):
        future = pending.pop(message.get("id"), None)
        if future is not None and not future.done():
            future.set_result(message)

    transport.on_message = on_message

    async def one(index: int):
        future = loop.create_future()
        pending[index] = future
        transport.send({"id": index, "guid": "x", "method": "noop",
                        "params": {"n": index},
                        "metadata": {"apiName": "bench"}})
        return await future

    # ⛔ A warm-up that is DISCARDED: the first calls pay for thread start-up
    # and for the first allocation of every structure, and folding those into
    # the average is how a microbenchmark reports a number nobody can reproduce.
    for i in range(200):
        await one(i)

    samples = []
    for i in range(rounds):
        start = time.perf_counter()
        await one(200 + i)
        samples.append((time.perf_counter() - start) * 1000.0)

    transport.request_stop()
    await transport.wait_until_stopped()

    samples.sort()
    media = statistics.fmean(samples)
    mediana = samples[len(samples) // 2]
    p95 = samples[int(len(samples) * 0.95)]
    print("giri utili            %d" % len(samples))
    print("media                 %.4f ms" % media)
    print("mediana               %.4f ms" % mediana)
    print("p95                   %.4f ms" % p95)
    print("p99                   %.4f ms" % samples[int(len(samples) * 0.99)])
    print()
    print("un giro Juggler vero  %.2f ms  (misurato 2026-08-27)"
          % JUGGLER_ROUND_TRIP_MS)
    quota = 100.0 * mediana / JUGGLER_ROUND_TRIP_MS
    print("il transport pesa     %.1f%% di una chiamata vera" % quota)
    print()
    if quota < 10:
        print("VERDETTO: il transport NON e' il costo. Togliere thread e coda "
              "andrebbe fatto per semplicita', se mai, non per velocita'.")
    else:
        print("VERDETTO: il transport pesa abbastanza da giustificare il "
              "refactor asincrono.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--giri", type=int, default=5000)
    a = p.parse_args()
    return asyncio.run(run(a.giri))


if __name__ == "__main__":
    sys.exit(main())

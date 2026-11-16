# Launch kit

Every figure here was produced by this repository on a container with a 1-CPU
cgroup quota. Reproduce before publishing; do not publish a number you did not
measure on the machine you name.

## Repo description (GitHub, ~120 chars)

> Measure whether your Python should be serial, threaded, multi-process, or async — before you rewrite anything.

## Topics

`python` `gil` `benchmark` `concurrency` `asyncio` `multiprocessing` `performance` `threading` `amdahl` `developer-tools`

## LinkedIn post

> Everyone knows Python's GIL exists. Almost nobody knows whether *their* code is affected by it.
>
> So I stopped guessing and built a tool that answers it with numbers.
>
> `threadwise` runs the same task list four ways — serial, threads, processes, async — then checks that all four returned the same result. If they didn't, it refuses to rank them. A speedup that changes your answer is not a speedup.
>
> What the real runs showed:
>
> ▪ 96 tasks × 20 ms of waiting, 16 workers: **13.55× with threads** at 85% efficiency. Processes landed on 13.57× and async on 12.02×. For waiting, all three work — speed is not what picks the winner.
> ▪ That was on a machine with a **1-CPU quota**. A single core still finished 13× sooner. Concurrency is about waiting; parallelism is about cores.
> ▪ `os.cpu_count()` said `16` there while cgroups allowed **1.00**. So the tool reads the real budget and prints "no verdict — the ranking measures the machine, not your code."
> ▪ A process pool costs 46 ms to start. For a 20 ms job that is the entire budget, and the report says so instead of hiding it.
> ▪ New in 1.1: `threadwise sweep` measures the whole curve and fits Amdahl's law. When the curve hasn't bent yet it reports the ceiling as "≥, lower bound" — because inventing a tidy 87× out of five points is arithmetic, not evidence.
>
> The lesson isn't "use multiprocessing". It's that the right answer depends on where the time actually goes — and that's measurable in twenty seconds, not arguable on Twitter.
>
> Repo: https://github.com/seyyed-sajjad-fazeli/threadwise
>
> What's the worst GIL-related slowdown you've hit? 👇

**Rules for this post**

- Put the link in the **first comment**, not the post body. The first two lines must stand alone; LinkedIn truncates around 140 characters.
- Attach one image. The chart reads at thumbnail size; a terminal screenshot does not. Use `docs/io-latency.png`.
- Lead with the claim, not the tool. "Almost nobody knows whether their code is affected" is the hook; the repo link is not.
- Answer every comment in the first two hours. That is where most of the reach comes from.

## First comment

> Install: `pip install threadwise` → `threadwise bench ./your_script.py`
>
> Your file needs one function: `def run(seed): ...` — one independent chunk of work per call, ideally ≥10 ms. `KIND = "io"` and `async def arun(seed)` unlock the async column.
>
> `threadwise sweep ./job.py --sizes 1,2,4,8,16` draws the scaling curve and fits Amdahl's law. `--html report.html` writes a single self-contained report.
>
> Zero dependencies in the core package. Python 3.10+. MIT.

## Honest claims checklist

Confirm each still holds for the published commit:

- [ ] `python -m unittest discover -s tests` → 44 tests pass
- [ ] `threadwise bench io-latency -n 96 -w 16` reproduces ~13.5× and "identical results"
- [ ] `threadwise sweep io-latency --sizes 1,2,8,16 -n 96` reports the ceiling as "≥" on this host
- [ ] Every number in the post exists in a saved `bench.json` / `sweep.json` from that machine
- [ ] README claims no CPU speedup that was never measured (the 1-core host only proves I/O)

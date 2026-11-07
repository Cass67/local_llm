Final update: I tested the same Maya v1.1.55 build and TheRock HIP runtime on Linux 7.4-rc1, which includes AMD’s [gfx11 idle-usage workaround](https://github.com/torvalds/linux/commit/590e26626106533d15fed808ac92f7135b2c909b) and its [timer-interval correction](https://github.com/torvalds/linux/commit/a6ea3f9ec21eafcbdcd3534e79f3c93ca4e89038).

This makes a big difference on the four RX 7900 XT cards:

| Test | Idle power across all four cards | Reported activity |
| --- | --- | --- |
| 7.2.13, default stream priorities | 380 W | 100% on every card |
| 7.4-rc1, default stream priorities | 59 W before generation / 61 W afterward | 14–18% |
| 7.2.13, `DS4_STREAM_PRIO=0` | 44 W before generation / 49 W afterward | 0% on every card |

DS4 completed its automatic expert-share reload with TP4, reached ready and generated four tokens on the new kernel. Auto shares stayed enabled; `DS4_STREAM_PRIO` was left at its default. We observed 45 seconds of idle before the request and 30 seconds afterward. These are sums of per-card median power readings, not a throughput or long-context benchmark.

The small HIP reproducer improved too. Both the mixed-priority case and the eight-normal-stream control still retained nine compute queues, but the affected card settled around 15 W and 16–17% activity instead of roughly 97 W and 100%. So the kernel change addresses most of the excess idle power without removing the retained queues. It does **not** completely eliminate the reported activity.

This supports the MES oversubscription explanation: the priorities matter because HIP maintains separate queue pools for them. DS4’s reload grows those pools past the observed queue threshold; normal-priority streams alone can also trigger it when their queue limit is raised. Fixing the application stream teardown alone did not prevent it in our earlier tests.

For now, `DS4_STREAM_PRIO=0` remains the workaround we have actually verified returns full DS4 to 0% idle activity on the original kernel. The new kernel is a substantial improvement, but I would not call this fully resolved yet.

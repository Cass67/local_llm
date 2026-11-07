Here is the small standalone HIP reproducer. This version uses one GPU and destroys every first-pass stream before starting the second pass. It makes no GPU allocations, copies, kernel launches, event operations or device synchronization calls.

Save it as `queue-steps.cpp`, then build and run it with:

```sh
hipcc -O2 queue-steps.cpp -o queue-steps
./queue-steps 1 2 4
```

The arguments are complete first-pass cleanup (`1`), number of high-priority streams (`2`), and number of normal-priority streams (`4`). The pauses make it easier to watch utilization and power. Run each case in a fresh process with other GPU workloads stopped.

On my 7900 XT, the first pass stays idle. The second pass causes persistent 100% busy and about 95 W on the target card. Destroying all streams at the end does not clear it; exiting the process does.

These comparison runs stay at normal idle:

```sh
# Six normal-priority streams instead of mixed priorities
./queue-steps 1 0 6

# Keep mixed priorities but limit hardware queues
GPU_MAX_HW_QUEUES=1 ./queue-steps 1 2 4
```

One more useful check: normal priority can reproduce it too if I raise the queue limit:

```sh
GPU_MAX_HW_QUEUES=8 ./queue-steps 1 0 8
```

That hits 100% busy on the first pass when the ninth compute queue appears. With the default limit, the normal-priority case keeps five compute queues in total and stays idle; the mixed-priority case eventually reaches nine. So the queue count is the trigger here, rather than high priority being inherently broken.

I also counted the KFD queues during the failing run. After the first pass and complete stream teardown, six 1 MiB compute queues plus one 4 KiB auxiliary compute queue remained. During the second pass the total grew from eight to nine compute queues, and the card jumped to 100% busy. The queues remained after the final stream destroys too. That makes queue pooling and oversubscription a much stronger lead than a leftover model kernel. This closely matches AMD's [gfx11 idle-usage fix](https://github.com/torvalds/linux/commit/590e26626106533d15fed808ac92f7135b2c909b), which replaces the MES oversubscription timer with a KFD-side notifier. I haven't done a patched-kernel A/B on this host, so that part is still a diagnosis to verify.

```cpp
// Create idle HIP streams one at a time so KFD queues can be counted externally.
// No allocations, kernels, copies, events or synchronization calls.
#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <unistd.h>

static void ck(hipError_t e) {
    if (e != hipSuccess) {
        std::fprintf(stderr, "HIP error: %s\n", hipGetErrorString(e));
        std::exit(1);
    }
}

int main(int argc, char** argv) {
    int clean = argc > 1 ? std::atoi(argv[1]) : 0,
        high = argc > 2 ? std::atoi(argv[2]) : 2,
        normal = argc > 3 ? std::atoi(argv[3]) : 4;
    ck(hipSetDevice(0));
    int lo = 0, hi = 0;
    ck(hipDeviceGetStreamPriorityRange(&lo, &hi));
    std::printf("START pid=%d hi=%d normal=0 clean=%d high_streams=%d normal_streams=%d\n", getpid(), hi, clean, high, normal);
    std::fflush(stdout);
    sleep(3);

    std::vector<hipStream_t> streams;
    for (int pass = 0; pass < 2; ++pass) {
        for (int i = 0; i < high + normal; ++i) {
            hipStream_t s;
            int priority = i < high ? hi : 0;
            ck(hipStreamCreateWithPriority(&s, hipStreamNonBlocking, priority));
            streams.push_back(s);
            std::printf("CREATE pass=%d index=%d priority=%d held=%zu\n", pass, i, priority, streams.size());
            std::fflush(stdout);
            sleep(3);
        }
        if (pass == 0) {
            if (clean) {
                for (auto s : streams) ck(hipStreamDestroy(s));
                streams.clear();
            } else {
                ck(hipStreamDestroy(streams.front()));
                streams.erase(streams.begin());
            }
            std::puts("FIRST_TEARDOWN");
            std::fflush(stdout);
            sleep(6);
        }
    }
    std::puts("IDLE");
    std::fflush(stdout);
    sleep(9);
    for (auto s : streams) ck(hipStreamDestroy(s));
    std::puts("ALL_STREAMS_DESTROYED");
    std::fflush(stdout);
    sleep(6);
}
```

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

// Launch cost vs cross-card handoff, no model. Each "step" launches N empty kernels round-robin
// across the cards. async: launch all, then sync. chain: wait for the previous card before each
// launch, like ggml_backend_sched_compute_splits. Build: hipcc -O2 submit-cost.cpp -o submit-cost
#include <hip/hip_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

__global__ void empty_kernel() {}

static void ck(hipError_t e) {
    if (e != hipSuccess) {
        std::fprintf(stderr, "HIP error: %s\n", hipGetErrorString(e));
        std::exit(1);
    }
}

static double now_us() {
    using namespace std::chrono;
    return duration<double, std::micro>(steady_clock::now().time_since_epoch()).count();
}

static double pct(std::vector<double>& v, double p) {
    std::sort(v.begin(), v.end());
    return v[size_t(p * (v.size() - 1))];
}

int main(int argc, char** argv) {
    int steps = argc > 1 ? std::atoi(argv[1]) : 2000, count = 0;
    // SUBMIT_SCHED=spin|yield|block sets how the host waits in hipStreamSynchronize.
    const char* sched = std::getenv("SUBMIT_SCHED");
    unsigned flags = !sched                            ? hipDeviceScheduleAuto
                     : std::string(sched) == "spin"  ? hipDeviceScheduleSpin
                     : std::string(sched) == "yield" ? hipDeviceScheduleYield
                                                     : hipDeviceScheduleBlockingSync;
    ck(hipGetDeviceCount(&count));
    std::vector<hipStream_t> streams(count);
    for (int d = 0; d < count; ++d) {
        ck(hipSetDevice(d));
        if (sched) ck(hipSetDeviceFlags(flags));
        ck(hipStreamCreateWithFlags(&streams[d], hipStreamNonBlocking));
    }
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    for (int chain = 0; chain < 2; ++chain) {
        for (int cards = 1; cards <= count; ++cards) {
            for (int n : {1, 2, 4, 8, 16, 32}) {
                std::vector<double> total, launch, wait;
                for (int s = 0; s < steps + 100; ++s) {
                    double t0 = now_us(), l = 0, w = 0;
                    // A stream only accepts work while its device is current; without the
                    // hipSetDevice the launch fails and the "sync" returns at once.
                    for (int i = 0; i < n; ++i) {
                        if (chain && i) {
                            double a = now_us();
                            ck(hipSetDevice((i - 1) % cards));
                            ck(hipStreamSynchronize(streams[(i - 1) % cards]));
                            w += now_us() - a;
                        }
                        double a = now_us();
                        ck(hipSetDevice(i % cards));
                        hipLaunchKernelGGL(empty_kernel, dim3(1), dim3(1), 0, streams[i % cards]);
                        ck(hipGetLastError());
                        l += now_us() - a;
                    }
                    double a = now_us();
                    for (int c = 0; c < std::min(cards, n); ++c) {
                        ck(hipSetDevice(c));
                        ck(hipStreamSynchronize(streams[c]));
                    }
                    w += now_us() - a;
                    if (s >= 100) {  // first steps carry queue and code-object setup
                        total.push_back(now_us() - t0);
                        launch.push_back(l);
                        wait.push_back(w);
                    }
                }
                std::printf(
                    "{\"mode\":\"%s\",\"cards\":%d,\"kernels\":%d,\"step_us_p50\":%.1f,"
                    "\"step_us_p95\":%.1f,\"launch_us_p50\":%.1f,\"wait_us_p50\":%.1f}\n",
                    chain ? "chain" : "async", cards, n, pct(total, .5), pct(total, .95),
                    pct(launch, .5), pct(wait, .5));
            }
        }
    }
    for (auto s : streams) ck(hipStreamDestroy(s));
}

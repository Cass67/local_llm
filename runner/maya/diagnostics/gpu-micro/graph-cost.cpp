// GPU-side cost per kernel in a dependent chain: stream launches vs one captured HIP graph, one
// device. Kernels are empty or spin for SPIN_US, so the gap between kernels is what is measured.
// Build: hipcc -O2 graph-cost.cpp -o graph-cost    Run: ./graph-cost [device]
#include <hip/hip_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

__global__ void work_kernel(long long cycles) {
    long long t0 = wall_clock64();
    while (wall_clock64() - t0 < cycles) {
    }
}

static void ck(hipError_t e) {
    if (e != hipSuccess) {
        std::fprintf(stderr, "HIP error: %s\n", hipGetErrorString(e));
        std::exit(1);
    }
}

int main(int argc, char** argv) {
    int device = argc > 1 ? std::atoi(argv[1]) : 0, rate_khz = 0;
    ck(hipSetDevice(device));
    ck(hipDeviceGetAttribute(&rate_khz, hipDeviceAttributeWallClockRate, device));
    hipStream_t s;
    ck(hipStreamCreateWithFlags(&s, hipStreamNonBlocking));
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    for (int spin_us : {0, 20}) {
        long long cycles = (long long)spin_us * rate_khz / 1000;
        for (int n : {64, 512}) {
            hipGraph_t g;
            hipGraphExec_t ge;
            ck(hipStreamBeginCapture(s, hipStreamCaptureModeGlobal));
            for (int i = 0; i < n; ++i) hipLaunchKernelGGL(work_kernel, dim3(1), dim3(1), 0, s, cycles);
            ck(hipStreamEndCapture(s, &g));
            ck(hipGraphInstantiate(&ge, g, nullptr, nullptr, 0));
            for (int graph = 0; graph < 2; ++graph) {
                std::vector<double> per;
                for (int rep = 0; rep < 60; ++rep) {
                    auto t0 = std::chrono::steady_clock::now();
                    if (graph) {
                        ck(hipGraphLaunch(ge, s));
                    } else {
                        for (int i = 0; i < n; ++i)
                            hipLaunchKernelGGL(work_kernel, dim3(1), dim3(1), 0, s, cycles);
                        ck(hipGetLastError());
                    }
                    ck(hipStreamSynchronize(s));
                    double us = std::chrono::duration<double, std::micro>(
                                    std::chrono::steady_clock::now() - t0).count();
                    if (rep >= 10) per.push_back(us / n - spin_us);
                }
                std::sort(per.begin(), per.end());
                std::printf("{\"mode\":\"%s\",\"spin_us\":%d,\"kernels\":%d,"
                            "\"overhead_us_per_kernel_p50\":%.2f,\"min\":%.2f}\n",
                            graph ? "graph" : "stream", spin_us, n, per[per.size() / 2], per[0]);
            }
            ck(hipGraphExecDestroy(ge));
            ck(hipGraphDestroy(g));
        }
    }
    ck(hipStreamDestroy(s));
}

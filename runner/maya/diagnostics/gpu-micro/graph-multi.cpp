// Do HIP graphs keep their GPU-side gaps when several cards replay graphs at once, one host thread each?
// Each card runs DS4's segment pattern: SEGS x (a graph of N kernels of SPIN_US, then one stream kernel).
// Kernels stamp wall_clock64, so gaps inside a graph and at graph edges are measured on the GPU.
// Build: hipcc -O2 graph-multi.cpp -o graph-multi -lpthread   Run: ./graph-multi [spin_us=3] [n=16] [segs=8]
#include <hip/hip_runtime.h>
#include <algorithm>
#include <barrier>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>

__global__ void work(long long cycles, long long* ts, int i) {
    long long t0 = wall_clock64();
    while (wall_clock64() - t0 < cycles) {
    }
    ts[2 * i] = t0;
    ts[2 * i + 1] = wall_clock64();
}

static void ck(hipError_t e) {
    if (e != hipSuccess) {
        std::fprintf(stderr, "HIP error: %s\n", hipGetErrorString(e));
        std::exit(1);
    }
}

struct Res {
    double host_us_per_kernel, gap_in, gap_edge, gap_in_p90;
};

int main(int argc, char** argv) {
    const int spin_us = argc > 1 ? std::atoi(argv[1]) : 3, n = argc > 2 ? std::atoi(argv[2]) : 16,
              segs = argc > 3 ? std::atoi(argv[3]) : 8, total = segs * (n + 1), reps = 300;
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    for (int graph : {0, 1})
        for (int ndev : {1, 2, 4}) {
            std::vector<Res> res(ndev);
            std::barrier sync(ndev);
            auto body = [&](int d) {
                ck(hipSetDevice(d));
                int khz = 0;
                ck(hipDeviceGetAttribute(&khz, hipDeviceAttributeWallClockRate, d));
                const long long cycles = (long long)spin_us * khz / 1000;
                hipStream_t s;
                ck(hipStreamCreateWithFlags(&s, hipStreamNonBlocking));
                long long *ts, *h;
                ck(hipMalloc(&ts, total * 2 * sizeof(long long)));
                ck(hipHostMalloc(&h, total * 2 * sizeof(long long)));
                std::vector<hipGraphExec_t> ge(segs);
                for (int g = 0; g < segs; ++g) {
                    hipGraph_t gr;
                    ck(hipStreamBeginCapture(s, hipStreamCaptureModeThreadLocal));
                    for (int i = 0; i < n; ++i) work<<<1, 64, 0, s>>>(cycles, ts, g * (n + 1) + i);
                    ck(hipStreamEndCapture(s, &gr));
                    ck(hipGraphInstantiate(&ge[g], gr, nullptr, nullptr, 0));
                    ck(hipGraphDestroy(gr));
                }
                std::vector<double> host, in, edge;
                for (int r = 0; r < reps; ++r) {
                    sync.arrive_and_wait();
                    auto t0 = std::chrono::steady_clock::now();
                    for (int g = 0; g < segs; ++g) {
                        if (graph) ck(hipGraphLaunch(ge[g], s));
                        else
                            for (int i = 0; i < n; ++i) work<<<1, 64, 0, s>>>(cycles, ts, g * (n + 1) + i);
                        work<<<1, 64, 0, s>>>(cycles, ts, g * (n + 1) + n);
                    }
                    ck(hipStreamSynchronize(s));
                    double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
                    if (r < 20) continue;
                    host.push_back(us / total - spin_us);
                    ck(hipMemcpy(h, ts, total * 2 * sizeof(long long), hipMemcpyDeviceToHost));
                    for (int k = 1; k < total; ++k) {
                        double gap = (h[2 * k] - h[2 * k - 1]) * 1000.0 / khz;
                        int pos = k % (n + 1);
                        (pos == 0 || pos == n ? edge : in).push_back(gap);
                    }
                }
                auto med = [](std::vector<double>& v, double q) {
                    std::sort(v.begin(), v.end());
                    return v[(size_t)(q * (v.size() - 1))];
                };
                res[d] = {med(host, 0.5), med(in, 0.5), med(edge, 0.5), med(in, 0.9)};
                for (auto& e : ge) ck(hipGraphExecDestroy(e));
                ck(hipFree(ts));
                ck(hipHostFree(h));
                ck(hipStreamDestroy(s));
            };
            std::vector<std::thread> th;
            for (int d = 0; d < ndev; ++d) th.emplace_back(body, d);
            for (auto& t : th) t.join();
            for (int d = 0; d < ndev; ++d)
                std::printf("{\"mode\":\"%s\",\"ndev\":%d,\"dev\":%d,\"spin_us\":%d,\"n\":%d,\"wall_over_us_per_kernel\":%.2f,"
                            "\"gpu_gap_in_graph_p50\":%.2f,\"p90\":%.2f,\"gpu_gap_at_edge_p50\":%.2f}\n",
                            graph ? "graph" : "stream", ndev, d, spin_us, n, res[d].host_us_per_kernel, res[d].gap_in,
                            res[d].gap_in_p90, res[d].gap_edge);
        }
}

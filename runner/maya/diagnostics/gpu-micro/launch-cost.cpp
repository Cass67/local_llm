// Host cost of hipLaunchKernel vs kernel-argument size and number of launching threads (one
// thread per device, each with its device current), with empty kernels so the host is the limit.
// Build: hipcc -O2 -std=c++17 launch-cost.cpp -o launch-cost    Try with HIP_FORCE_DEV_KERNARG=0/1.
#include <hip/hip_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

template <int N>
struct Arg {
    char b[N];
};

template <int N>
__global__ void k(Arg<N> a) {
    if (a.b[0] == 123 && threadIdx.x == 999) a.b[1] = 0;  // keep the argument alive
}

static void ck(hipError_t e) {
    if (e != hipSuccess) {
        std::fprintf(stderr, "HIP error: %s\n", hipGetErrorString(e));
        std::exit(1);
    }
}

template <int N>
static double launch_us(int device, int launches) {
    ck(hipSetDevice(device));
    hipStream_t s;
    ck(hipStreamCreateWithFlags(&s, hipStreamNonBlocking));
    Arg<N> a{};
    std::vector<double> per;
    for (int rep = 0; rep < 12; ++rep) {
        auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < launches; ++i) hipLaunchKernelGGL(k<N>, dim3(1), dim3(64), 0, s, a);
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        ck(hipGetLastError());
        ck(hipStreamSynchronize(s));
        if (rep >= 2) per.push_back(us / launches);
    }
    ck(hipStreamDestroy(s));
    std::sort(per.begin(), per.end());
    return per[per.size() / 2];
}

// Host time of one hipGraphLaunch of a `nodes`-kernel graph, divided by nodes.
template <int N>
static double graph_us(int device, int nodes) {
    ck(hipSetDevice(device));
    hipStream_t s;
    ck(hipStreamCreateWithFlags(&s, hipStreamNonBlocking));
    Arg<N> a{};
    hipGraph_t g;
    hipGraphExec_t ge;
    ck(hipStreamBeginCapture(s, hipStreamCaptureModeThreadLocal));
    for (int i = 0; i < nodes; ++i) hipLaunchKernelGGL(k<N>, dim3(1), dim3(64), 0, s, a);
    ck(hipStreamEndCapture(s, &g));
    ck(hipGraphInstantiate(&ge, g, nullptr, nullptr, 0));
    std::vector<double> per;
    for (int rep = 0; rep < 12; ++rep) {
        auto t0 = std::chrono::steady_clock::now();
        ck(hipGraphLaunch(ge, s));
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        ck(hipStreamSynchronize(s));
        if (rep >= 2) per.push_back(us / nodes);
    }
    ck(hipGraphExecDestroy(ge));
    ck(hipGraphDestroy(g));
    ck(hipStreamDestroy(s));
    std::sort(per.begin(), per.end());
    return per[per.size() / 2];
}

// Per step: capture `nodes` kernels whose argument changes every step, hipGraphExecUpdate the
// executable graph from it, launch. Host time divided by nodes. No kernel needs to change.
template <int N>
static double recapture_us(int device, int nodes) {
    ck(hipSetDevice(device));
    hipStream_t s;
    ck(hipStreamCreateWithFlags(&s, hipStreamNonBlocking));
    Arg<N> a{};
    hipGraphExec_t ge = nullptr;
    std::vector<double> per;
    for (int rep = 0; rep < 12; ++rep) {
        auto t0 = std::chrono::steady_clock::now();
        hipGraph_t g;
        ck(hipStreamBeginCapture(s, hipStreamCaptureModeThreadLocal));
        for (int i = 0; i < nodes; ++i) {
            a.b[1] = (char) (rep + i);
            hipLaunchKernelGGL(k<N>, dim3(1), dim3(64), 0, s, a);
        }
        ck(hipStreamEndCapture(s, &g));
        if (!ge) {
            ck(hipGraphInstantiate(&ge, g, nullptr, nullptr, 0));
        } else {
            hipGraphNode_t bad;
            hipGraphExecUpdateResult res;
            ck(hipGraphExecUpdate(ge, g, &bad, &res));
        }
        ck(hipGraphLaunch(ge, s));
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        ck(hipGraphDestroy(g));
        ck(hipStreamSynchronize(s));
        if (rep >= 2) per.push_back(us / nodes);
    }
    ck(hipGraphExecDestroy(ge));
    ck(hipStreamDestroy(s));
    std::sort(per.begin(), per.end());
    return per[per.size() / 2];
}

// Per step: hipGraphExecKernelNodeSetParams on every node with a new argument, then launch the
// graph. Host time divided by nodes = the cost of one patched node (plus a share of the launch).
template <int N>
static double setparams_us(int device, int nodes) {
    ck(hipSetDevice(device));
    hipStream_t s;
    ck(hipStreamCreateWithFlags(&s, hipStreamNonBlocking));
    Arg<N> a{};
    hipGraph_t g;
    hipGraphExec_t ge;
    ck(hipStreamBeginCapture(s, hipStreamCaptureModeThreadLocal));
    for (int i = 0; i < nodes; ++i) hipLaunchKernelGGL(k<N>, dim3(1), dim3(64), 0, s, a);
    ck(hipStreamEndCapture(s, &g));
    ck(hipGraphInstantiate(&ge, g, nullptr, nullptr, 0));
    size_t n = 0;
    ck(hipGraphGetNodes(g, nullptr, &n));
    std::vector<hipGraphNode_t> nd(n);
    ck(hipGraphGetNodes(g, nd.data(), &n));
    const char* ev = std::getenv("UPD_EVERY");   // patch every k-th node (default every node)
    const size_t every = ev ? (size_t) std::max(1, std::atoi(ev)) : 1;
    std::vector<double> per;
    for (int rep = 0; rep < 12; ++rep) {
        auto t0 = std::chrono::steady_clock::now();
        for (size_t i = 0; i < n; i += every) {
            a.b[1] = (char) (rep + i);
            void* args[] = {&a};
            hipKernelNodeParams p{};
            p.func = reinterpret_cast<void*>(k<N>);
            p.gridDim = dim3(1);
            p.blockDim = dim3(64);
            p.kernelParams = args;
            ck(hipGraphExecKernelNodeSetParams(ge, nd[i], &p));
        }
        ck(hipGraphLaunch(ge, s));
        double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        ck(hipStreamSynchronize(s));
        if (rep >= 2) per.push_back(us / nodes);
    }
    ck(hipGraphExecDestroy(ge));
    ck(hipGraphDestroy(g));
    ck(hipStreamDestroy(s));
    std::sort(per.begin(), per.end());
    return per[per.size() / 2];
}

template <int N>
static void row(int threads, int mode) {
    static const char* names[] = {"stream", "graph", "recapture", "setparams"};
    std::vector<double> r(threads);
    std::vector<std::thread> ts;
    for (int t = 0; t < threads; ++t)
        ts.emplace_back([&r, t, mode] {
            r[t] = mode == 0   ? launch_us<N>(t, 1000)
                   : mode == 1 ? graph_us<N>(t, 200)
                   : mode == 2 ? recapture_us<N>(t, 400)
                               : setparams_us<N>(t, 400);
        });
    for (auto& t : ts) t.join();
    std::printf("{\"mode\":\"%s\",\"arg_bytes\":%d,\"threads\":%d,\"launch_us_p50\":[", names[mode], N,
                threads);
    for (int t = 0; t < threads; ++t) std::printf("%s%.2f", t ? "," : "", r[t]);
    std::printf("]}\n");
}

int main() {
    int count = 0;
    ck(hipGetDeviceCount(&count));
    for (int i = 0; i < count; ++i) {  // warm each device so setup is not timed
        ck(hipSetDevice(i));
        ck(hipFree(nullptr));
    }
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    // LAUNCH_MODES=0123 picks stream / graph / recapture / setparams (default all)
    const char* m = std::getenv("LAUNCH_MODES");
    for (int mode = 0; mode < 4; ++mode) {
        if (m && !std::strchr(m, '0' + mode)) continue;
        for (int threads : {1, count}) {
            row<8>(threads, mode);
            row<256>(threads, mode);
            row<1024>(threads, mode);
            row<2048>(threads, mode);
        }
    }
}

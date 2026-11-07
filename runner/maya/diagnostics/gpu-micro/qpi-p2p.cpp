// Cross-socket P2P cost: kernel peer write/read vs SDMA peer copy vs copy staged through pinned host RAM.
// Build: hipcc -O2 -o qpi-p2p qpi-p2p.cpp   Run: ./qpi-p2p 0:1 0:2 2:0 2:3   (src:dst HIP ids)
#include <hip/hip_runtime.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>

#define HIP(x)                                                                    \
    do {                                                                          \
        hipError_t e = (x);                                                       \
        if (e != hipSuccess) {                                                    \
            std::fprintf(stderr, "%s:%d %s\n", __FILE__, __LINE__, hipGetErrorString(e)); \
            std::exit(1);                                                         \
        }                                                                         \
    } while (0)

__global__ void copy(const uint4* src, uint4* dst, size_t n) {
    for (size_t i = blockIdx.x * blockDim.x + threadIdx.x; i < n; i += gridDim.x * blockDim.x) dst[i] = src[i];
}

static const size_t kBytes = 64ull << 20;

template <class F>
static double gbs(int dev, F f) {
    HIP(hipSetDevice(dev));
    f();
    HIP(hipDeviceSynchronize());
    double best = 1e30;
    for (int r = 0; r < 5; r++) {
        auto t = std::chrono::steady_clock::now();
        f();
        HIP(hipDeviceSynchronize());
        double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t).count();
        best = s < best ? s : best;
    }
    return kBytes / best / 1e9;
}

int main(int argc, char** argv) {
    const size_t n = kBytes / sizeof(uint4);
    for (int a = 1; a < argc; a++) {
        int s, d;
        std::sscanf(argv[a], "%d:%d", &s, &d);
        int can = 0;
        HIP(hipDeviceCanAccessPeer(&can, s, d));
        void *bs, *bd, *host;
        HIP(hipSetDevice(s));
        HIP(hipMalloc(&bs, kBytes));
        if (can) (void)hipDeviceEnablePeerAccess(d, 0);
        HIP(hipSetDevice(d));
        HIP(hipMalloc(&bd, kBytes));
        if (can) (void)hipDeviceEnablePeerAccess(s, 0);
        HIP(hipHostMalloc(&host, kBytes, hipHostMallocPortable));
        (void)hipGetLastError();
        auto k = [&](int dev, const void* from, void* to) {
            return gbs(dev, [&] { copy<<<1024, 256>>>((const uint4*)from, (uint4*)to, n); });
        };
        double kw = can ? k(s, bs, bd) : 0, kr = can ? k(d, bs, bd) : 0;
        double sd = can ? gbs(s, [&] { HIP(hipMemcpyPeerAsync(bd, d, bs, s, kBytes, 0)); }) : 0;
        double d2h = gbs(s, [&] { HIP(hipMemcpyAsync(host, bs, kBytes, hipMemcpyDeviceToHost, 0)); });
        double h2d = gbs(d, [&] { HIP(hipMemcpyAsync(bd, host, kBytes, hipMemcpyHostToDevice, 0)); });
        std::printf("%d->%d peer=%d kernel_write %.2f kernel_read %.2f sdma_peer %.2f | staged d2h %.2f h2d %.2f "
                    "(serial %.2f) GB/s\n",
                    s, d, can, kw, kr, sd, d2h, h2d, 1 / (1 / d2h + 1 / h2d));
        HIP(hipFree(bs));
        HIP(hipFree(bd));
        HIP(hipHostFree(host));
    }
}

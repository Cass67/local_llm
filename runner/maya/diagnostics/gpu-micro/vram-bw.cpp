// Effective VRAM read bandwidth from a compute kernel, no ggml. Threads in a block read adjacent
// words, so a wave issues one contiguous vector load, like a weight decode.
// Build: hipcc -O2 vram-bw.cpp -o vram-bw    Run: ./vram-bw [device] [max_gib]
#include <hip/hip_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

constexpr int kThreads = 64;

__global__ void read_kernel(const uint64_t* p, uint64_t block_words, uint64_t stride, uint64_t* out) {
    const uint64_t* base = p + blockIdx.x * block_words;
    uint64_t x = 0;
    for (uint64_t row = 0; (row + 1) * kThreads * stride <= block_words; ++row)
        x ^= base[(row * kThreads + threadIdx.x) * stride];
    out[blockIdx.x * kThreads + threadIdx.x] = x;  // keeps the loads alive
}

static void ck(hipError_t e) {
    if (e != hipSuccess) {
        std::fprintf(stderr, "HIP error: %s\n", hipGetErrorString(e));
        std::exit(1);
    }
}

int main(int argc, char** argv) {
    int device = argc > 1 ? std::atoi(argv[1]) : 0;
    uint64_t max_gib = argc > 2 ? std::atoll(argv[2]) : 16;
    constexpr uint64_t kGib = 1ull << 30, kBlockWords = (64ull << 10) / 8;  // 64 KiB per block
    ck(hipSetDevice(device));
    hipStream_t stream;
    ck(hipStreamCreateWithFlags(&stream, hipStreamNonBlocking));
    std::setvbuf(stdout, nullptr, _IOLBF, 0);

    std::vector<uint64_t> sizes{kGib / 4, 4 * kGib, max_gib * kGib};
    for (uint64_t bytes : sizes) {
        if (bytes > max_gib * kGib) continue;
        uint64_t blocks = bytes / (kBlockWords * 8);
        uint64_t* p = nullptr;
        uint64_t* out = nullptr;
        ck(hipMalloc(&p, bytes));
        ck(hipMalloc(&out, blocks * kThreads * 8));
        ck(hipMemsetAsync(p, 0x5a, bytes, stream));
        ck(hipStreamSynchronize(stream));
        // Stride in words. 1 reads everything, 8 touches one word per 64-byte line.
        for (uint64_t stride : {1, 2, 4, 8}) {
            uint64_t reads = (kBlockWords / (kThreads * stride)) * kThreads * blocks;
            std::vector<double> gbps;
            for (int rep = 0; rep < 25; ++rep) {
                auto t0 = std::chrono::steady_clock::now();
                hipLaunchKernelGGL(read_kernel, dim3(blocks), dim3(kThreads), 0, stream, p,
                                   kBlockWords, stride, out);
                ck(hipStreamSynchronize(stream));
                double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
                gbps.push_back(reads * std::min<uint64_t>(stride * 8, 64) / s / 1e9);
            }
            std::sort(gbps.begin(), gbps.end());
            std::printf(
                "{\"device\":%d,\"gib\":%.2f,\"stride_words\":%llu,\"line_gbps_p50\":%.1f,"
                "\"line_gbps_max\":%.1f,\"pct_of_800\":%.1f}\n",
                device, double(bytes) / kGib, (unsigned long long)stride, gbps[gbps.size() / 2],
                gbps.back(), gbps.back() / 8);
        }
        ck(hipFree(p));
        ck(hipFree(out));
    }
    ck(hipStreamDestroy(stream));
}

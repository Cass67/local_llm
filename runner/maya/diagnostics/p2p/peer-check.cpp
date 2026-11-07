// Query HIP peer support, or verify direct kernel loads/stores for one pair.
// Each pair runs as a separate process under an external timeout.
#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include <chrono>

#define HIP(call) do { hipError_t e = (call); if (e != hipSuccess) { \
    std::fprintf(stderr, "%s: %s\n", #call, hipGetErrorString(e)); std::exit(2); } } while (0)

__global__ void read_peer(const uint32_t* remote, uint32_t* local, size_t n) {
    size_t i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) local[i] = remote[i];
}
__global__ void write_peer(uint32_t* remote, const uint32_t* local, size_t n) {
    size_t i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) remote[i] = local[i];
}

int main(int argc, char** argv) {
    int count = 0;
    HIP(hipGetDeviceCount(&count));
    for (int i = 0; i < count; ++i) {
        char bus[32];
        HIP(hipDeviceGetPCIBusId(bus, sizeof(bus), i));
        std::printf("device %d %s\n", i, bus);
    }
    for (int i = 0; i < count; ++i) {
        for (int j = 0; j < count; ++j) {
            int access = 0;
            if (i != j) HIP(hipDeviceCanAccessPeer(&access, i, j));
            std::printf("peer %d %d %d\n", i, j, access);
        }
    }
    std::fflush(stdout);
    if (argc < 3) return 0;
    const int src = std::atoi(argv[1]), dst = std::atoi(argv[2]);
    if (src < 0 || dst < 0 || src >= count || dst >= count || src == dst) return 3;
    int access = 0;
    HIP(hipDeviceCanAccessPeer(&access, dst, src));
    if (!access) { std::puts("SKIP unsupported peer"); return 4; }
    const size_t n = 16 * 1024 * 1024, bytes = n * sizeof(uint32_t);
    uint32_t *a, *b;
    HIP(hipSetDevice(src));
    HIP(hipMalloc(&a, bytes));
    HIP(hipSetDevice(dst));
    HIP(hipMalloc(&b, bytes));
    HIP(hipDeviceEnablePeerAccess(src, 0));
    std::vector<uint32_t> pattern(n), got(n);
    for (int trial = 0; trial < 3; ++trial) {
        for (size_t i = 0; i < n; ++i)
            pattern[i] = uint32_t(i * 2654435761u) ^ (0xa5c39e71u + uint32_t(trial * 7919));
        HIP(hipSetDevice(src));
        HIP(hipMemcpy(a, pattern.data(), bytes, hipMemcpyHostToDevice));
        HIP(hipSetDevice(dst));
        HIP(hipMemset(b, 0, bytes));
        auto start = std::chrono::steady_clock::now();
        read_peer<<<(n + 255) / 256, 256>>>(a, b, n);
        HIP(hipGetLastError());
        HIP(hipDeviceSynchronize());
        double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        HIP(hipMemcpy(got.data(), b, bytes, hipMemcpyDeviceToHost));
        if (got != pattern) { std::puts("FAIL peer read corruption"); return 5; }
        for (size_t i = 0; i < n; ++i) pattern[i] = ~pattern[i];
        HIP(hipMemcpy(b, pattern.data(), bytes, hipMemcpyHostToDevice));
        start = std::chrono::steady_clock::now();
        write_peer<<<(n + 255) / 256, 256>>>(a, b, n);
        HIP(hipGetLastError());
        HIP(hipDeviceSynchronize());
        double write_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        HIP(hipSetDevice(src));
        HIP(hipMemcpy(got.data(), a, bytes, hipMemcpyDeviceToHost));
        if (got != pattern) { std::puts("FAIL peer write corruption"); return 6; }
        std::printf("PASS source=%d accessor=%d trial=%d bytes=%zu read_ms=%.3f write_ms=%.3f\n", src, dst, trial, bytes, ms, write_ms);
        std::fflush(stdout);
    }
    HIP(hipSetDevice(dst));
    HIP(hipFree(b));
    HIP(hipSetDevice(src));
    HIP(hipFree(a));
}

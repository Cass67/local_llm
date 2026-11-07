// cpu-bw: host read bandwidth on a 2-socket box, the DS4 CPU lane's shape.
// steady: T threads a node read their node's buffer over and over (both nodes at once).
// burst:  the lane's call: each node reads `mb` MB of a random spot in its buffer, split in `jobs` jobs taken from a
//         shared counter by its threads (spin-waiting between calls), all nodes together; time per call -> GB/s.
// build: gcc -O2 -mavx2 -pthread cpu-bw.c -o cpu-bw    run: ./cpu-bw [threads_per_node] [burst_mb] [jobs]
#define _GNU_SOURCE
#include <immintrin.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define NODES 2
#define CORES 22
#define BUF (8ull << 30)
static uint8_t* buf[NODES];
static int tpn;
static double burst_mb;
static int jobs;
static atomic_int phase, go_gen, done_n, next_job[NODES];
static size_t burst_off[NODES];
static atomic_long sink;

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}
static long rd(const uint8_t* p, size_t n) {
    __m256i a = _mm256_setzero_si256(), b = a, c = a, d = a;
    for (size_t i = 0; i < n; i += 128) {
        a = _mm256_xor_si256(a, _mm256_load_si256((const __m256i*) (p + i)));
        b = _mm256_xor_si256(b, _mm256_load_si256((const __m256i*) (p + i + 32)));
        c = _mm256_xor_si256(c, _mm256_load_si256((const __m256i*) (p + i + 64)));
        d = _mm256_xor_si256(d, _mm256_load_si256((const __m256i*) (p + i + 96)));
    }
    a = _mm256_xor_si256(_mm256_xor_si256(a, b), _mm256_xor_si256(c, d));
    return _mm256_extract_epi64(a, 0);
}
static void pin(int cpu) {
    cpu_set_t s;
    CPU_ZERO(&s);
    CPU_SET(cpu, &s);
    pthread_setaffinity_np(pthread_self(), sizeof s, &s);
}
typedef struct { int node, idx; double gb; } Arg;
static atomic_int steady_go;
static double steady_s = 2.0;
static void* worker(void* v) {
    Arg* a = v;
    pin(a->node * CORES + a->idx);
    const size_t part = BUF / tpn;
    uint8_t* mine = buf[a->node] + a->idx * part;
    if (a->idx == 0 && 0) {}
    memset(mine, a->idx + 1, part);   // first touch: node-local pages
    atomic_fetch_add(&done_n, 1);
    while (!atomic_load(&steady_go)) ;
    double t0 = now(), bytes = 0;
    while (now() - t0 < steady_s) {
        atomic_fetch_add(&sink, rd(mine, part));
        bytes += part;
    }
    a->gb = bytes / (now() - t0) / 1e9;
    atomic_fetch_add(&done_n, 1);
    // bursts
    int seen = 0;
    for (;;) {
        int g;
        while ((g = atomic_load(&go_gen)) == seen) ;
        if (g < 0) return NULL;
        seen = g;
        const size_t total = (size_t) (burst_mb * 1e6) & ~(size_t) 127;
        const size_t per = (total / jobs + 127) & ~(size_t) 127;
        for (;;) {
            int j = atomic_fetch_add(&next_job[a->node], 1);
            if (j >= jobs) break;
            size_t o = (size_t) j * per;
            if (o >= total) break;
            size_t n = o + per > total ? total - o : per;
            atomic_fetch_add(&sink, rd(buf[a->node] + burst_off[a->node] + o, n));
        }
        atomic_fetch_add(&done_n, 1);
    }
}
int main(int argc, char** argv) {
    tpn = argc > 1 ? atoi(argv[1]) : 22;
    burst_mb = argc > 2 ? atof(argv[2]) : 9.4;
    jobs = argc > 3 ? atoi(argv[3]) : 18;
    for (int n = 0; n < NODES; ++n) buf[n] = aligned_alloc(1 << 21, BUF);
    pthread_t th[NODES * CORES];
    Arg args[NODES * CORES];
    for (int n = 0; n < NODES; ++n)
        for (int i = 0; i < tpn; ++i) {
            args[n * tpn + i] = (Arg){n, i, 0};
            pthread_create(&th[n * tpn + i], NULL, worker, &args[n * tpn + i]);
        }
    while (atomic_load(&done_n) < NODES * tpn) ;
    atomic_store(&done_n, 0);
    atomic_store(&steady_go, 1);
    while (atomic_load(&done_n) < NODES * tpn) ;
    double tot[NODES] = {0};
    for (int i = 0; i < NODES * tpn; ++i) tot[args[i].node] += args[i].gb;
    printf("steady %d thr/node: node0 %.1f GB/s node1 %.1f GB/s total %.1f\n", tpn, tot[0], tot[1], tot[0] + tot[1]);
    srand(1);
    const int calls = 2000;
    double sum = 0, best = 1e9;
    for (int c = 1; c <= calls; ++c) {
        for (int n = 0; n < NODES; ++n) {
            burst_off[n] = ((size_t) rand() * 4096) % (BUF - (64 << 20));
            burst_off[n] &= ~(size_t) 4095;
            atomic_store(&next_job[n], 0);
        }
        atomic_store(&done_n, 0);
        double t0 = now();
        atomic_store(&go_gen, c);
        while (atomic_load(&done_n) < NODES * tpn) ;
        double dt = now() - t0;
        sum += dt;
        if (dt < best) best = dt;
        double t1 = now();
        while (now() - t1 < 300e-6) ;   // the GPU's part between calls
    }
    const double bytes = NODES * burst_mb * 1e6;
    printf("burst %.1f MB/node %d jobs: mean %.1f us (%.1f GB/s), best %.1f us (%.1f GB/s)\n", burst_mb, jobs,
           sum / calls * 1e6, bytes / (sum / calls) / 1e9, best * 1e6, bytes / best / 1e9);
    atomic_store(&go_gen, -1);
    for (int i = 0; i < NODES * tpn; ++i) pthread_join(th[i], NULL);
    return 0;
}

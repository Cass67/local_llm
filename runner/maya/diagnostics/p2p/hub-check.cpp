// Four GPUs publish partials into GPU0 VRAM, then reduce after device-side flags.
// This separately tests ordering/coherence, which bulk copies cannot establish.
#include <hip/hip_runtime.h>
#include <hip/hip_ext.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <chrono>

#define HIP(call) do { hipError_t e = (call); if (e != hipSuccess) { std::fprintf(stderr,"%s: %s\n",#call,hipGetErrorString(e)); std::exit(2); } } while(0)

__global__ void publish(float* rows, unsigned* flags, const float* x, int n, int rank, unsigned seq, int atomic_flags) {
    for (int i=threadIdx.x; i<n; i+=blockDim.x) rows[rank*n+i]=x[i]+float(seq);
    __threadfence_system();
    __syncthreads();
    if (threadIdx.x==0) { if(atomic_flags) __hip_atomic_store(flags+rank*32,seq,__ATOMIC_RELEASE,__HIP_MEMORY_SCOPE_SYSTEM); else reinterpret_cast<volatile unsigned*>(flags)[rank*32]=seq; __threadfence_system(); }
}
__global__ void reduce(const float* rows, const unsigned* flags, float* out, int n, unsigned seq, unsigned long long ticks, unsigned* error, int atomic_flags) {
    __shared__ int ready;
    if (threadIdx.x==0) {
        ready=1;
        auto start=wall_clock64();
        for (int r=0;r<4;++r) {
            unsigned observed;
            while ((observed=atomic_flags ? __hip_atomic_load(flags+r*32,__ATOMIC_ACQUIRE,__HIP_MEMORY_SCOPE_SYSTEM) : reinterpret_cast<const volatile unsigned*>(flags)[r*32])!=seq) {
                if (wall_clock64()-start > ticks) { error[0]=1;error[1]=r;error[2]=observed;error[3]=seq; ready=0; break; }
            }
            if (!ready) break;
        }
        __threadfence_system();
    }
    __syncthreads();
    if (!ready) return;
    for (int i=threadIdx.x;i<n;i+=blockDim.x) out[i]=rows[i]+rows[n+i]+rows[2*n+i]+rows[3*n+i];
}
int main(int argc,char** argv) {
    int count=0; HIP(hipGetDeviceCount(&count)); if(count!=4)return 3;
    int mode=argc>1 ? std::atoi(argv[1]) : 0;
    bool fine=mode!=0;
    int atomic_flags=argc>2 ? std::atoi(argv[2]) : 0;
    bool host_barrier=argc>3 && std::atoi(argv[3])!=0;
    unsigned rounds=argc>4 ? unsigned(std::atoi(argv[4])) : 20;
    constexpr int n=5120;
    float *rows,*input[4],*output[4]; unsigned *flags,*error[4]; hipStream_t streams[4]; int rate[4];
    HIP(hipSetDevice(0));
    if(fine) {
        HIP(hipExtMallocWithFlags((void**)&rows,4*n*sizeof(float),mode==2 ? hipDeviceMallocUncached : hipDeviceMallocFinegrained));
        HIP(hipExtMallocWithFlags((void**)&flags,4*32*sizeof(unsigned),mode==2 ? hipDeviceMallocUncached : hipDeviceMallocFinegrained));
    } else { HIP(hipMalloc(&rows,4*n*sizeof(float))); HIP(hipMalloc(&flags,4*32*sizeof(unsigned))); }
    HIP(hipMemset(rows,0,4*n*sizeof(float))); HIP(hipMemset(flags,0,4*32*sizeof(unsigned)));
    for(int r=0;r<4;++r) {
        HIP(hipSetDevice(r));
        HIP(hipDeviceGetAttribute(&rate[r],hipDeviceAttributeWallClockRate,r));
        HIP(hipStreamCreate(&streams[r])); HIP(hipMalloc(&input[r],n*sizeof(float))); HIP(hipMalloc(&output[r],n*sizeof(float))); HIP(hipMalloc(&error[r],4*sizeof(unsigned))); HIP(hipMemset(error[r],0,4*sizeof(unsigned)));
        std::vector<float> v(n); for(int i=0;i<n;++i)v[i]=float(i%13+r);
        HIP(hipMemcpy(input[r],v.data(),n*sizeof(float),hipMemcpyHostToDevice));
        HIP(hipDeviceSynchronize());
    }
    for(int r=1;r<4;++r) { int can=0; HIP(hipDeviceCanAccessPeer(&can,r,0)); if(!can){std::printf("SKIP GPU%d cannot reach GPU0\n",r);return 4;} HIP(hipSetDevice(r)); HIP(hipDeviceEnablePeerAccess(0,0)); }
    for(int r=0;r<4;++r) { HIP(hipSetDevice(r)); publish<<<1,256,0,streams[r]>>>(rows,flags,input[r],n,r,0,atomic_flags); HIP(hipGetLastError()); HIP(hipStreamSynchronize(streams[r])); }
    for(int r=0;r<4;++r) { HIP(hipSetDevice(r)); reduce<<<1,256,0,streams[r]>>>(rows,flags,output[r],n,0,(unsigned long long)rate[r]*1000,error[r],atomic_flags); HIP(hipGetLastError()); HIP(hipStreamSynchronize(streams[r])); }
    for(unsigned seq=1;seq<=rounds;++seq) {
        for(int r=0;r<4;++r) {
            auto before=std::chrono::steady_clock::now();
            HIP(hipSetDevice(r));
            publish<<<1,256,0,streams[r]>>>(rows,flags,input[r],n,r,seq,atomic_flags); HIP(hipGetLastError());
            if(!host_barrier) { reduce<<<1,256,0,streams[r]>>>(rows,flags,output[r],n,seq,(unsigned long long)rate[r]*1000,error[r],atomic_flags); HIP(hipGetLastError()); }
            double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before).count();
            if(elapsed>5) {std::printf("HOST_DELAY rank=%d round=%u ms=%.3f\n",r,seq,elapsed);std::fflush(stdout);}
        }
        if(host_barrier) {
            for(int r=0;r<4;++r){HIP(hipSetDevice(r));HIP(hipStreamSynchronize(streams[r]));}
            for(int r=0;r<4;++r){HIP(hipSetDevice(r));reduce<<<1,256,0,streams[r]>>>(rows,flags,output[r],n,seq,(unsigned long long)rate[r]*1000,error[r],atomic_flags);HIP(hipGetLastError());}
        }
        for(int r=0;r<4;++r){HIP(hipSetDevice(r));HIP(hipStreamSynchronize(streams[r]));}
        // Keep sequence reuse out of this experiment: all ranks finish before another round.
        for(int r=0;r<4;++r) {
            HIP(hipSetDevice(r)); HIP(hipStreamSynchronize(streams[r]));
            unsigned err[4]={};HIP(hipMemcpy(err,error[r],sizeof(err),hipMemcpyDeviceToHost));
            if(err[0]){unsigned f[128];HIP(hipSetDevice(0));HIP(hipMemcpy(f,flags,sizeof(f),hipMemcpyDeviceToHost));std::printf("FAIL timeout mode=%d atomic=%d barrier=%d rank=%d round=%u waiting=%u observed=%u expected=%u final_flags=%u,%u,%u,%u\n",mode,atomic_flags,host_barrier,r,seq,err[1],err[2],err[3],f[0],f[32],f[64],f[96]);return 5;}
            std::vector<float> v(n); HIP(hipMemcpy(v.data(),output[r],n*sizeof(float),hipMemcpyDeviceToHost));
            for(int i=0;i<n;++i)if(v[i]!=float(4*(i%13)+6+4*seq)){std::printf("FAIL data fine=%d rank=%d round=%u index=%d got=%g\n",fine,r,seq,i,v[i]);return 6;}
        }
    }
    std::printf("PASS four-card hub mode=%d atomic=%d barrier=%d rounds=%u floats=%d\n",mode,atomic_flags,host_barrier,rounds,n);
}

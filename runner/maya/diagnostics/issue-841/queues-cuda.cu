// CUDA equivalent of the HIP queue-lifecycle reproducer for mw00/project-maya#841.
// Modes: 0 = leak five first-pass streams; 1 = destroy all between passes;
// 3 = mode 0 without memset; 4 = mode 0 with default-priority streams only;
// 5 = mode 1 with default-priority streams only;
// 6 = stream creation/destruction only (no malloc, memset, or synchronize);
// 7 = mode 6 with complete teardown between passes.
// Run in a separate process with no model serving on these GPUs.
// CUDA version prepared for NVIDIA testing; no CUDA GPU was available here.
// Build: nvcc -O2 queues-cuda.cu -o queues-cuda
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <unistd.h>
#include <vector>
void check(cudaError_t r,const char* what){if(r!=cudaSuccess){fprintf(stderr,"%s: %s\n",what,cudaGetErrorString(r));exit(1);}}
int main(int argc,char**argv){
 int mode=argc>1?atoi(argv[1]):0, count=0;check(cudaGetDeviceCount(&count),"devices");
 printf("mode=%d devices=%d\n",mode,count);fflush(stdout);
 std::vector<std::vector<cudaStream_t>> held(count);
 for(int pass=0;pass<2;++pass){
  for(int d=0;d<count;++d){check(cudaSetDevice(d),"device");int lo=0,hi=0;check(cudaDeviceGetStreamPriorityRange(&lo,&hi),"priority");
   if(mode==4||mode==5)hi=0;
   void*p=nullptr;if(mode<6)check(cudaMalloc(&p,4096),"malloc");
   for(int i=0;i<6;++i){cudaStream_t s;check(cudaStreamCreateWithPriority(&s,cudaStreamNonBlocking,i<2?hi:0),"create");held[d].push_back(s);if(mode!=3 && mode<6)check(cudaMemsetAsync(p,0,4096,s),"memset");}
   if(mode<6){check(cudaDeviceSynchronize(),"sync");check(cudaFree(p),"free");}
  }
  printf("pass=%d created-and-synchronized\n",pass);fflush(stdout);sleep(8);
  if(pass==0){for(int d=0;d<count;++d){check(cudaSetDevice(d),"device");auto&v=held[d];if(mode==1||mode==5||mode==7){for(auto s:v)check(cudaStreamDestroy(s),"destroy-all");v.clear();}else{check(cudaStreamDestroy(v[0]),"destroy-main");v.erase(v.begin());}}printf("pass=0 teardown done\n");fflush(stdout);sleep(8);}
 }
 printf("all work synchronized; idle\n");fflush(stdout);sleep(15);
 for(int d=0;d<count;++d){check(cudaSetDevice(d),"device");for(auto s:held[d])check(cudaStreamDestroy(s),"final-destroy");}
 printf("all streams destroyed; idle\n");fflush(stdout);sleep(8);
}

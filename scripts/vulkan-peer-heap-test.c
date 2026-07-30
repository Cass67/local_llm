// Does the target memory heap decide peer-copy speed?
// My earlier p2p test used DEVICE_LOCAL|HOST_VISIBLE (large-BAR, memory type 3) and
// got 4.6 GB/s. ggml allocates weights/compute buffers in pure VRAM (type 0, not
// host-visible). If peer writes into pure VRAM are drastically slower, that explains
// why the V3 patch collapsed in llama.cpp while the standalone test looked fine.
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <vulkan/vulkan.h>

#define CK(x)                                                                  \
  do {                                                                         \
    VkResult r = (x);                                                          \
    if (r != VK_SUCCESS) { printf("FAIL %s -> %d (line %d)\n", #x, r, __LINE__); return 1; } \
  } while (0)

#define N (4u * 1024 * 1024)

static VkPhysicalDevice pd0, pd1;
static VkDevice d0, d1;
static VkQueue q0;

static int mem_index(VkPhysicalDevice pd, uint32_t bits, VkMemoryPropertyFlags want,
                     VkMemoryPropertyFlags avoid) {
  VkPhysicalDeviceMemoryProperties mp;
  vkGetPhysicalDeviceMemoryProperties(pd, &mp);
  for (uint32_t i = 0; i < mp.memoryTypeCount; i++) {
    if (!(bits & (1u << i))) continue;
    VkMemoryPropertyFlags f = mp.memoryTypes[i].propertyFlags;
    if ((f & want) != want) continue;
    if (avoid && (f & avoid)) continue;
    return (int)i;
  }
  return -1;
}

// allocate an exportable buffer on d1 with the given heap preference, import into d0,
// then time d0 pushing into it.
static int bench(const char *label, VkMemoryPropertyFlags want, VkMemoryPropertyFlags avoid,
                 VkBuffer local_src) {
  VkExternalMemoryBufferCreateInfo ext = {
      .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
      .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  VkBufferCreateInfo bci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                            .pNext = &ext,
                            .size = N,
                            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |
                                     VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                                     VK_BUFFER_USAGE_TRANSFER_DST_BIT};
  VkBuffer target;
  CK(vkCreateBuffer(d1, &bci, NULL, &target));
  VkMemoryRequirements mr;
  vkGetBufferMemoryRequirements(d1, target, &mr);
  int idx = mem_index(pd1, mr.memoryTypeBits, want, avoid);
  if (idx < 0) { printf("%-28s no such memory type\n", label); return 0; }

  VkExportMemoryAllocateInfo exp = {.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO,
                                    .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                              .pNext = &exp, .allocationSize = mr.size,
                              .memoryTypeIndex = (uint32_t)idx};
  VkDeviceMemory tmem;
  CK(vkAllocateMemory(d1, &mai, NULL, &tmem));
  CK(vkBindBufferMemory(d1, target, tmem, 0));

  PFN_vkGetMemoryFdKHR getFd = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(d1, "vkGetMemoryFdKHR");
  VkMemoryGetFdInfoKHR gfi = {.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR,
                              .memory = tmem,
                              .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  int fd = -1;
  CK(getFd(d1, &gfi, &fd));

  PFN_vkGetMemoryFdPropertiesKHR getFdProps =
      (PFN_vkGetMemoryFdPropertiesKHR)vkGetDeviceProcAddr(d0, "vkGetMemoryFdPropertiesKHR");
  VkMemoryFdPropertiesKHR fdp = {.sType = VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR};
  CK(getFdProps(d0, VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, fd, &fdp));
  VkBuffer peer;
  CK(vkCreateBuffer(d0, &bci, NULL, &peer));
  VkMemoryRequirements pmr;
  vkGetBufferMemoryRequirements(d0, peer, &pmr);
  int pidx = mem_index(pd0, pmr.memoryTypeBits & fdp.memoryTypeBits, 0, 0);
  if (pidx < 0) { printf("%-28s not importable (bits=0x%x)\n", label, fdp.memoryTypeBits); return 0; }
  VkImportMemoryFdInfoKHR imp = {.sType = VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR,
                                 .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT,
                                 .fd = fd};
  VkMemoryAllocateInfo pmai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                               .pNext = &imp, .allocationSize = mr.size,
                               .memoryTypeIndex = (uint32_t)pidx};
  VkDeviceMemory pmem;
  CK(vkAllocateMemory(d0, &pmai, NULL, &pmem));
  CK(vkBindBufferMemory(d0, peer, pmem, 0));

  VkCommandPoolCreateInfo cpi = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                 .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
                                 .queueFamilyIndex = 0};
  VkCommandPool pool;
  CK(vkCreateCommandPool(d0, &cpi, NULL, &pool));
  VkCommandBufferAllocateInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                     .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                     .commandBufferCount = 1};
  VkCommandBuffer cb;
  CK(vkAllocateCommandBuffers(d0, &cbi, &cb));
  VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
  vkBeginCommandBuffer(cb, &bi);
  VkBufferCopy rg = {.size = N};
  vkCmdCopyBuffer(cb, local_src, peer, 1, &rg);
  vkEndCommandBuffer(cb);
  VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  VkFence f;
  CK(vkCreateFence(d0, &fci, NULL, &f));
  VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb};

  vkQueueSubmit(q0, 1, &si, f);
  vkWaitForFences(d0, 1, &f, VK_TRUE, 20000000000ull);
  vkResetFences(d0, 1, &f);

  const int reps = 20;
  struct timespec t0, t1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  for (int i = 0; i < reps; i++) {
    vkQueueSubmit(q0, 1, &si, f);
    vkWaitForFences(d0, 1, &f, VK_TRUE, 20000000000ull);
    vkResetFences(d0, 1, &f);
  }
  clock_gettime(CLOCK_MONOTONIC, &t1);
  double sec = (t1.tv_sec - t0.tv_sec) + 1e-9 * (t1.tv_nsec - t0.tv_nsec);
  printf("%-28s target_type=%d import_type=%d  %.3f GB/s\n", label, idx, pidx,
         (double)reps * N / sec / 1e9);
  return 0;
}

int main(void) {
  VkInstance inst;
  VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_2};
  VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
  CK(vkCreateInstance(&ici, NULL, &inst));
  uint32_t n = 0;
  vkEnumeratePhysicalDevices(inst, &n, NULL);
  if (n < 2) { printf("need 2 devices\n"); return 1; }
  VkPhysicalDevice *pds = calloc(n, sizeof(*pds));
  vkEnumeratePhysicalDevices(inst, &n, pds);
  pd0 = pds[0]; pd1 = pds[1];

  const char *exts[] = {"VK_KHR_external_memory", "VK_KHR_external_memory_fd",
                        "VK_EXT_external_memory_dma_buf"};
  float prio = 1.0f;
  VkDeviceQueueCreateInfo qi = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &prio};
  VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                           .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi,
                           .enabledExtensionCount = 3, .ppEnabledExtensionNames = exts};
  CK(vkCreateDevice(pd0, &di, NULL, &d0));
  CK(vkCreateDevice(pd1, &di, NULL, &d1));
  vkGetDeviceQueue(d0, 0, 0, &q0);

  // local source on d0, pure VRAM
  VkBufferCreateInfo sbci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = N,
                             .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT};
  VkBuffer lsrc;
  CK(vkCreateBuffer(d0, &sbci, NULL, &lsrc));
  VkMemoryRequirements smr;
  vkGetBufferMemoryRequirements(d0, lsrc, &smr);
  int sidx = mem_index(pd0, smr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0);
  VkMemoryAllocateInfo smai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                               .allocationSize = smr.size, .memoryTypeIndex = (uint32_t)sidx};
  VkDeviceMemory smem;
  CK(vkAllocateMemory(d0, &smai, NULL, &smem));
  CK(vkBindBufferMemory(d0, lsrc, smem, 0));

  printf("peer push, 4 MB, dev0 -> dev1:\n");
  bench("target BAR-visible VRAM", VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, 0, lsrc);
  bench("target pure VRAM", VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, lsrc);
  return 0;
}

// Go/no-go test for GPU->GPU peer copies on two radv devices.
// dev0 allocates an exportable DEVICE_LOCAL buffer and fills it with a pattern.
// dev1 imports that memory as a dma-buf and copies it into its own buffer with
// vkCmdCopyBuffer. If the pattern survives, peer DMA works and ggml-vulkan can
// do cross-device copies without a host round-trip.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <vulkan/vulkan.h>

#define CK(x)                                                                  \
  do {                                                                         \
    VkResult r = (x);                                                          \
    if (r != VK_SUCCESS) {                                                     \
      printf("FAIL %s -> %d (line %d)\n", #x, r, __LINE__);                    \
      return 1;                                                                \
    }                                                                          \
  } while (0)

#define N (4 * 1024 * 1024)

static int find_mem(VkPhysicalDevice pd, uint32_t bits, VkMemoryPropertyFlags want) {
  VkPhysicalDeviceMemoryProperties mp;
  vkGetPhysicalDeviceMemoryProperties(pd, &mp);
  for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
    if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want)
      return (int)i;
  return -1;
}

int main(void) {
  VkInstance inst;
  VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                          .apiVersion = VK_API_VERSION_1_2};
  VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                              .pApplicationInfo = &ai};
  CK(vkCreateInstance(&ici, NULL, &inst));

  uint32_t n = 0;
  vkEnumeratePhysicalDevices(inst, &n, NULL);
  if (n < 2) { printf("FAIL need 2 devices, found %u\n", n); return 1; }
  VkPhysicalDevice *pds = calloc(n, sizeof(*pds));
  vkEnumeratePhysicalDevices(inst, &n, pds);

  VkPhysicalDeviceProperties p0, p1;
  vkGetPhysicalDeviceProperties(pds[0], &p0);
  vkGetPhysicalDeviceProperties(pds[1], &p1);
  printf("dev0=%s\ndev1=%s\n", p0.deviceName, p1.deviceName);

  const char *exts[] = {"VK_KHR_external_memory", "VK_KHR_external_memory_fd",
                        "VK_EXT_external_memory_dma_buf"};
  float prio = 1.0f;

  // --- logical devices, queue family 0 on each (graphics+transfer capable) ---
  VkDevice d[2];
  VkQueue q[2];
  for (int i = 0; i < 2; i++) {
    VkDeviceQueueCreateInfo qi = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                  .queueFamilyIndex = 0,
                                  .queueCount = 1,
                                  .pQueuePriorities = &prio};
    VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                             .queueCreateInfoCount = 1,
                             .pQueueCreateInfos = &qi,
                             .enabledExtensionCount = 3,
                             .ppEnabledExtensionNames = exts};
    CK(vkCreateDevice(pds[i], &di, NULL, &d[i]));
    vkGetDeviceQueue(d[i], 0, 0, &q[i]);
  }

  PFN_vkGetMemoryFdKHR getFd =
      (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(d[0], "vkGetMemoryFdKHR");
  PFN_vkGetMemoryFdPropertiesKHR getFdProps =
      (PFN_vkGetMemoryFdPropertiesKHR)vkGetDeviceProcAddr(d[1], "vkGetMemoryFdPropertiesKHR");
  if (!getFd || !getFdProps) { printf("FAIL missing fd entrypoints\n"); return 1; }

  // --- dev0: exportable buffer, host-visible so we can write the pattern ---
  VkExternalMemoryBufferCreateInfo ext_buf = {
      .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
      .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  VkBufferCreateInfo bci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                            .pNext = &ext_buf,
                            .size = N,
                            .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                                     VK_BUFFER_USAGE_TRANSFER_DST_BIT};
  VkBuffer src;
  CK(vkCreateBuffer(d[0], &bci, NULL, &src));
  VkMemoryRequirements mr;
  vkGetBufferMemoryRequirements(d[0], src, &mr);

  int mt = find_mem(pds[0], mr.memoryTypeBits,
                    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT |
                        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                        VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
  int host_visible_src = mt >= 0;
  if (mt < 0) mt = find_mem(pds[0], mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
  if (mt < 0) { printf("FAIL no memory type on dev0\n"); return 1; }
  printf("dev0 mem type %d (host_visible=%d, large-BAR path=%s)\n", mt,
         host_visible_src, host_visible_src ? "yes" : "no");

  VkExportMemoryAllocateInfo emai = {
      .sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO,
      .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                              .pNext = &emai,
                              .allocationSize = mr.size,
                              .memoryTypeIndex = (uint32_t)mt};
  VkDeviceMemory srcmem;
  CK(vkAllocateMemory(d[0], &mai, NULL, &srcmem));
  CK(vkBindBufferMemory(d[0], src, srcmem, 0));

  if (!host_visible_src) { printf("SKIP cannot seed pattern without host-visible VRAM\n"); return 2; }
  void *map = NULL;
  CK(vkMapMemory(d[0], srcmem, 0, N, 0, &map));
  for (int i = 0; i < N / 4; i++) ((uint32_t *)map)[i] = 0xA5A50000u + (uint32_t)(i & 0xFFFF);
  vkUnmapMemory(d[0], srcmem);

  // --- export fd ---
  VkMemoryGetFdInfoKHR gfi = {.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR,
                              .memory = srcmem,
                              .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  int fd = -1;
  CK(getFd(d[0], &gfi, &fd));
  printf("exported dma-buf fd=%d\n", fd);

  // --- dev1: import that fd, then copy peer -> local ---
  VkMemoryFdPropertiesKHR fdp = {.sType = VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR};
  CK(getFdProps(d[1], VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, fd, &fdp));
  printf("dev1 importable memoryTypeBits=0x%x\n", fdp.memoryTypeBits);
  if (!fdp.memoryTypeBits) { printf("FAIL dev1 cannot import peer memory\n"); return 1; }

  VkBuffer peer;
  CK(vkCreateBuffer(d[1], &bci, NULL, &peer));
  VkMemoryRequirements pmr;
  vkGetBufferMemoryRequirements(d[1], peer, &pmr);
  int pmt = find_mem(pds[1], pmr.memoryTypeBits & fdp.memoryTypeBits, 0);
  if (pmt < 0) { printf("FAIL no compatible import memory type on dev1\n"); return 1; }
  printf("dev1 import mem type %d\n", pmt);

  VkImportMemoryFdInfoKHR imp = {.sType = VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR,
                                 .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT,
                                 .fd = fd};
  VkMemoryAllocateInfo pmai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                               .pNext = &imp,
                               .allocationSize = pmr.size,
                               .memoryTypeIndex = (uint32_t)pmt};
  VkDeviceMemory peermem;
  CK(vkAllocateMemory(d[1], &pmai, NULL, &peermem));
  CK(vkBindBufferMemory(d[1], peer, peermem, 0));

  VkBufferCreateInfo dbci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                             .size = N,
                             .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
  VkBuffer dst;
  CK(vkCreateBuffer(d[1], &dbci, NULL, &dst));
  VkMemoryRequirements dmr;
  vkGetBufferMemoryRequirements(d[1], dst, &dmr);
  int dmt = find_mem(pds[1], dmr.memoryTypeBits,
                     VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
  if (dmt < 0) { printf("FAIL no host-visible dst on dev1\n"); return 1; }
  VkMemoryAllocateInfo dmai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                               .allocationSize = dmr.size,
                               .memoryTypeIndex = (uint32_t)dmt};
  VkDeviceMemory dstmem;
  CK(vkAllocateMemory(d[1], &dmai, NULL, &dstmem));
  CK(vkBindBufferMemory(d[1], dst, dstmem, 0));

  VkCommandPoolCreateInfo cpi = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                 .queueFamilyIndex = 0};
  VkCommandPool pool;
  CK(vkCreateCommandPool(d[1], &cpi, NULL, &pool));
  VkCommandBufferAllocateInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                     .commandPool = pool,
                                     .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                     .commandBufferCount = 1};
  VkCommandBuffer cb;
  CK(vkAllocateCommandBuffers(d[1], &cbi, &cb));
  VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
  CK(vkBeginCommandBuffer(cb, &bi));
  VkBufferCopy region = {.size = N};
  vkCmdCopyBuffer(cb, peer, dst, 1, &region);
  CK(vkEndCommandBuffer(cb));

  VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  VkFence fence;
  CK(vkCreateFence(d[1], &fci, NULL, &fence));
  VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                     .commandBufferCount = 1,
                     .pCommandBuffers = &cb};
  CK(vkQueueSubmit(q[1], 1, &si, fence));
  CK(vkWaitForFences(d[1], 1, &fence, VK_TRUE, 5000000000ull));

  // --- push direction: dev0 writes into dev1's imported buffer ---
  {
    // local src on dev0 (device-local), dst = the peer buffer we already imported
    // on dev1 is the wrong way round, so build the mirror: export on dev1, import on dev0.
    VkBuffer e1;
    CK(vkCreateBuffer(d[1], &bci, NULL, &e1));
    VkMemoryRequirements r1;
    vkGetBufferMemoryRequirements(d[1], e1, &r1);
    int t1i = find_mem(pds[1], r1.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    VkExportMemoryAllocateInfo e1x = {.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO,
                                      .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
    VkMemoryAllocateInfo a1 = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                               .pNext = &e1x, .allocationSize = r1.size,
                               .memoryTypeIndex = (uint32_t)t1i};
    VkDeviceMemory m1;
    CK(vkAllocateMemory(d[1], &a1, NULL, &m1));
    CK(vkBindBufferMemory(d[1], e1, m1, 0));
    PFN_vkGetMemoryFdKHR getFd1 = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(d[1], "vkGetMemoryFdKHR");
    VkMemoryGetFdInfoKHR g1 = {.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR,
                               .memory = m1,
                               .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
    int fd1 = -1;
    CK(getFd1(d[1], &g1, &fd1));

    PFN_vkGetMemoryFdPropertiesKHR gp0 =
        (PFN_vkGetMemoryFdPropertiesKHR)vkGetDeviceProcAddr(d[0], "vkGetMemoryFdPropertiesKHR");
    VkMemoryFdPropertiesKHR fp0 = {.sType = VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR};
    CK(gp0(d[0], VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, fd1, &fp0));
    VkBuffer p0;
    CK(vkCreateBuffer(d[0], &bci, NULL, &p0));
    VkMemoryRequirements pr0;
    vkGetBufferMemoryRequirements(d[0], p0, &pr0);
    int pi0 = find_mem(pds[0], pr0.memoryTypeBits & fp0.memoryTypeBits, 0);
    if (pi0 < 0) { printf("push: no import type on dev0\n"); }
    else {
      VkImportMemoryFdInfoKHR im0 = {.sType = VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR,
                                     .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT,
                                     .fd = fd1};
      VkMemoryAllocateInfo pa0 = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                                  .pNext = &im0, .allocationSize = r1.size,
                                  .memoryTypeIndex = (uint32_t)pi0};
      VkDeviceMemory pm0;
      CK(vkAllocateMemory(d[0], &pa0, NULL, &pm0));
      CK(vkBindBufferMemory(d[0], p0, pm0, 0));

      VkCommandPoolCreateInfo cp0 = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = 0};
      VkCommandPool pool0;
      CK(vkCreateCommandPool(d[0], &cp0, NULL, &pool0));
      VkCommandBufferAllocateInfo cb0i = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                          .commandPool = pool0, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                          .commandBufferCount = 1};
      VkCommandBuffer cb0;
      CK(vkAllocateCommandBuffers(d[0], &cb0i, &cb0));
      VkCommandBufferBeginInfo b0 = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
      CK(vkBeginCommandBuffer(cb0, &b0));
      VkBufferCopy rg = {.size = N};
      vkCmdCopyBuffer(cb0, src, p0, 1, &rg);   // dev0 local -> peer (write across PCIe)
      CK(vkEndCommandBuffer(cb0));
      VkFenceCreateInfo f0i = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
      VkFence f0;
      CK(vkCreateFence(d[0], &f0i, NULL, &f0));
      VkSubmitInfo s0 = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb0};
      const int reps2 = 40;
      struct timespec u0, u1;
      clock_gettime(CLOCK_MONOTONIC, &u0);
      for (int r = 0; r < reps2; r++) {
        CK(vkQueueSubmit(q[0], 1, &s0, f0));
        CK(vkWaitForFences(d[0], 1, &f0, VK_TRUE, 10000000000ull));
        CK(vkResetFences(d[0], 1, &f0));
      }
      clock_gettime(CLOCK_MONOTONIC, &u1);
      double s2 = (u1.tv_sec - u0.tv_sec) + 1e-9 * (u1.tv_nsec - u0.tv_nsec);
      printf("PUSH (src writes peer): %.2f GB/s\n", (double)reps2 * N / s2 / 1e9);
    }
  }

  // --- bandwidth: repeat the peer copy and time it ---
  {
    const int reps = 40;
    struct timespec t0, t1;
    CK(vkResetFences(d[1], 1, &fence));
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (int r = 0; r < reps; r++) {
      CK(vkQueueSubmit(q[1], 1, &si, fence));
      CK(vkWaitForFences(d[1], 1, &fence, VK_TRUE, 10000000000ull));
      CK(vkResetFences(d[1], 1, &fence));
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double sec = (t1.tv_sec - t0.tv_sec) + 1e-9 * (t1.tv_nsec - t0.tv_nsec);
    printf("PULL (dst reads peer): %d x %d MB in %.3f s -> %.2f GB/s\n", reps, N / (1024 * 1024),
           sec, (double)reps * N / sec / 1e9);
  }

  void *dmap = NULL;
  CK(vkMapMemory(d[1], dstmem, 0, N, 0, &dmap));
  long bad = 0;
  for (int i = 0; i < N / 4; i++)
    if (((uint32_t *)dmap)[i] != (0xA5A50000u + (uint32_t)(i & 0xFFFF))) bad++;
  vkUnmapMemory(d[1], dstmem);

  if (bad) { printf("FAIL %ld/%d words wrong after peer copy\n", bad, N / 4); return 1; }
  printf("PASS peer GPU->GPU copy verified (%d MB)\n", N / (1024 * 1024));
  return 0;
}

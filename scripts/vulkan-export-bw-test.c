// Is exportable DEVICE_LOCAL memory slower to access locally on radv?
// v1 of the peer-copy patch made every device-local allocation exportable and lost
// 2.5x prefill / 7x tg. If that was memory placement, local copy bandwidth inside
// exportable memory will be much worse than inside plain memory. If they match, the
// v1 regression had another cause and the destination buffer can be exported
// directly -- no staging buffer, no flow control.
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <vulkan/vulkan.h>

#define CK(x)                                                                  \
  do {                                                                         \
    VkResult r = (x);                                                          \
    if (r != VK_SUCCESS) { printf("FAIL %s -> %d (line %d)\n", #x, r, __LINE__); return 1; } \
  } while (0)

#define SZ (256u * 1024 * 1024)

static VkDevice dev;
static VkQueue q;
static VkPhysicalDevice pd;

static int mem_index(uint32_t bits, VkMemoryPropertyFlags want, VkMemoryPropertyFlags avoid) {
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

static int make_buf(int exportable, VkMemoryPropertyFlags want, VkMemoryPropertyFlags avoid,
                    VkBuffer *out_buf, VkDeviceMemory *out_mem, int *out_type) {
  VkExternalMemoryBufferCreateInfo ext = {
      .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
      .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  VkBufferCreateInfo bci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                            .pNext = exportable ? &ext : NULL,
                            .size = SZ,
                            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |
                                     VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                                     VK_BUFFER_USAGE_TRANSFER_DST_BIT};
  CK(vkCreateBuffer(dev, &bci, NULL, out_buf));
  VkMemoryRequirements mr;
  vkGetBufferMemoryRequirements(dev, *out_buf, &mr);
  int idx = mem_index(mr.memoryTypeBits, want, avoid);
  if (idx < 0) { printf("  (no memory type for want=0x%x avoid=0x%x)\n", want, avoid); return -1; }
  *out_type = idx;
  VkExportMemoryAllocateInfo exp = {.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO,
                                    .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
  VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                              .pNext = exportable ? &exp : NULL,
                              .allocationSize = mr.size,
                              .memoryTypeIndex = (uint32_t)idx};
  CK(vkAllocateMemory(dev, &mai, NULL, out_mem));
  CK(vkBindBufferMemory(dev, *out_buf, *out_mem, 0));
  return 0;
}

static double copy_bw(VkBuffer a, VkBuffer b, VkCommandBuffer cb, VkFence f) {
  VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
  vkBeginCommandBuffer(cb, &bi);
  VkBufferCopy r = {.size = SZ};
  vkCmdCopyBuffer(cb, a, b, 1, &r);
  vkEndCommandBuffer(cb);
  VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb};
  // warm up
  vkQueueSubmit(q, 1, &si, f);
  vkWaitForFences(dev, 1, &f, VK_TRUE, 10000000000ull);
  vkResetFences(dev, 1, &f);
  const int reps = 10;
  struct timespec t0, t1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  for (int i = 0; i < reps; i++) {
    vkQueueSubmit(q, 1, &si, f);
    vkWaitForFences(dev, 1, &f, VK_TRUE, 10000000000ull);
    vkResetFences(dev, 1, &f);
  }
  clock_gettime(CLOCK_MONOTONIC, &t1);
  double sec = (t1.tv_sec - t0.tv_sec) + 1e-9 * (t1.tv_nsec - t0.tv_nsec);
  // read + write per copy
  return 2.0 * reps * SZ / sec / 1e9;
}

int main(void) {
  VkInstance inst;
  VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_2};
  VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
  CK(vkCreateInstance(&ici, NULL, &inst));
  uint32_t n = 0;
  vkEnumeratePhysicalDevices(inst, &n, NULL);
  VkPhysicalDevice *pds = calloc(n, sizeof(*pds));
  vkEnumeratePhysicalDevices(inst, &n, pds);
  pd = pds[0];
  VkPhysicalDeviceProperties p;
  vkGetPhysicalDeviceProperties(pd, &p);
  printf("device: %s\n", p.deviceName);

  const char *exts[] = {"VK_KHR_external_memory", "VK_KHR_external_memory_fd",
                        "VK_EXT_external_memory_dma_buf"};
  float prio = 1.0f;
  VkDeviceQueueCreateInfo qi = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &prio};
  VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                           .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi,
                           .enabledExtensionCount = 3, .ppEnabledExtensionNames = exts};
  CK(vkCreateDevice(pd, &di, NULL, &dev));
  vkGetDeviceQueue(dev, 0, 0, &q);

  VkCommandPoolCreateInfo cpi = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                 .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
                                 .queueFamilyIndex = 0};
  VkCommandPool pool;
  CK(vkCreateCommandPool(dev, &cpi, NULL, &pool));
  VkCommandBufferAllocateInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                     .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                     .commandBufferCount = 1};
  VkCommandBuffer cb;
  CK(vkAllocateCommandBuffers(dev, &cbi, &cb));
  VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  VkFence f;
  CK(vkCreateFence(dev, &fci, NULL, &f));

  // Case 1: pure VRAM (device-local, NOT host-visible) — what weights should use
  printf("\n-- device-local, not host-visible (true VRAM) --\n");
  VkBuffer a1, b1; VkDeviceMemory ma1, mb1; int t1a = -1, t1b = -1;
  int ok1 = make_buf(0, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, &a1, &ma1, &t1a) == 0 &&
            make_buf(0, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, &b1, &mb1, &t1b) == 0;
  if (ok1) printf("  plain      types=%d,%d  %.1f GB/s\n", t1a, t1b, copy_bw(a1, b1, cb, f));

  VkBuffer a2, b2; VkDeviceMemory ma2, mb2; int t2a = -1, t2b = -1;
  int ok2 = make_buf(1, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, &a2, &ma2, &t2a) == 0 &&
            make_buf(1, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, &b2, &mb2, &t2b) == 0;
  if (ok2) printf("  EXPORTABLE types=%d,%d  %.1f GB/s\n", t2a, t2b, copy_bw(a2, b2, cb, f));

  // Case 2: device-local + host-visible (large-BAR heap) — what ggml picks first here
  printf("\n-- device-local + host-visible (large BAR) --\n");
  VkBuffer a3, b3; VkDeviceMemory ma3, mb3; int t3a = -1, t3b = -1;
  int ok3 = make_buf(0, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, 0, &a3, &ma3, &t3a) == 0 &&
            make_buf(0, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, 0, &b3, &mb3, &t3b) == 0;
  if (ok3) printf("  plain      types=%d,%d  %.1f GB/s\n", t3a, t3b, copy_bw(a3, b3, cb, f));

  VkBuffer a4, b4; VkDeviceMemory ma4, mb4; int t4a = -1, t4b = -1;
  int ok4 = make_buf(1, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, 0, &a4, &ma4, &t4a) == 0 &&
            make_buf(1, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT, 0, &b4, &mb4, &t4b) == 0;
  if (ok4) printf("  EXPORTABLE types=%d,%d  %.1f GB/s\n", t4a, t4b, copy_bw(a4, b4, cb, f));

  return 0;
}

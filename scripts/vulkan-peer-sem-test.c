// V3 go/no-go: can a timeline semaphore be shared between two radv devices?
// dev0 signals value 1 on a timeline semaphore exported as an opaque fd; dev1
// imports it and its queue waits for value 1 before running a copy. If this
// works, cross-device ordering needs no host drain -- which is what killed v2.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <vulkan/vulkan.h>

#define CK(x)                                                                  \
  do {                                                                         \
    VkResult r = (x);                                                          \
    if (r != VK_SUCCESS) {                                                      \
      printf("FAIL %s -> %d (line %d)\n", #x, r, __LINE__);                     \
      return 1;                                                                \
    }                                                                          \
  } while (0)

int main(void) {
  VkInstance inst;
  VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                          .apiVersion = VK_API_VERSION_1_2};
  VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                              .pApplicationInfo = &ai};
  CK(vkCreateInstance(&ici, NULL, &inst));

  uint32_t n = 0;
  vkEnumeratePhysicalDevices(inst, &n, NULL);
  if (n < 2) { printf("FAIL need 2 devices\n"); return 1; }
  VkPhysicalDevice *pds = calloc(n, sizeof(*pds));
  vkEnumeratePhysicalDevices(inst, &n, pds);

  // Can a timeline semaphore be exported/imported as an opaque fd?
  VkPhysicalDeviceExternalSemaphoreInfo esi = {
      .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_SEMAPHORE_INFO,
      .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT};
  VkSemaphoreTypeCreateInfo qtype = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO,
                                     .semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE};
  esi.pNext = &qtype;
  for (int i = 0; i < 2; i++) {
    VkExternalSemaphoreProperties props = {
        .sType = VK_STRUCTURE_TYPE_EXTERNAL_SEMAPHORE_PROPERTIES};
    vkGetPhysicalDeviceExternalSemaphoreProperties(pds[i], &esi, &props);
    printf("dev%d timeline+opaque_fd: export=%s import=%s\n", i,
           (props.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_EXPORTABLE_BIT) ? "yes" : "NO",
           (props.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT) ? "yes" : "NO");
    if (!(props.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_EXPORTABLE_BIT)) {
      printf("FAIL dev%d cannot export timeline semaphores\n", i);
      return 1;
    }
  }

  const char *exts[] = {"VK_KHR_external_semaphore", "VK_KHR_external_semaphore_fd",
                        "VK_KHR_timeline_semaphore"};
  float prio = 1.0f;
  VkPhysicalDeviceTimelineSemaphoreFeatures tsf = {
      .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES,
      .timelineSemaphore = VK_TRUE};
  VkDevice d[2];
  VkQueue q[2];
  for (int i = 0; i < 2; i++) {
    VkDeviceQueueCreateInfo qi = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                  .queueFamilyIndex = 0, .queueCount = 1,
                                  .pQueuePriorities = &prio};
    VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                             .pNext = &tsf,
                             .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi,
                             .enabledExtensionCount = 3, .ppEnabledExtensionNames = exts};
    CK(vkCreateDevice(pds[i], &di, NULL, &d[i]));
    vkGetDeviceQueue(d[i], 0, 0, &q[i]);
  }

  // --- timeline semaphore on dev0, exportable ---
  VkExportSemaphoreCreateInfo esci = {
      .sType = VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO,
      .handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT};
  VkSemaphoreTypeCreateInfo stci = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO,
                                    .semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE,
                                    .initialValue = 0, .pNext = &esci};
  VkSemaphoreCreateInfo sci = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext = &stci};
  VkSemaphore sem0;
  CK(vkCreateSemaphore(d[0], &sci, NULL, &sem0));

  PFN_vkGetSemaphoreFdKHR getSemFd =
      (PFN_vkGetSemaphoreFdKHR)vkGetDeviceProcAddr(d[0], "vkGetSemaphoreFdKHR");
  PFN_vkImportSemaphoreFdKHR importSemFd =
      (PFN_vkImportSemaphoreFdKHR)vkGetDeviceProcAddr(d[1], "vkImportSemaphoreFdKHR");
  if (!getSemFd || !importSemFd) { printf("FAIL missing semaphore fd entrypoints\n"); return 1; }

  VkSemaphoreGetFdInfoKHR gfi = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
                                 .semaphore = sem0,
                                 .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT};
  int fd = -1;
  CK(getSemFd(d[0], &gfi, &fd));
  printf("exported semaphore fd=%d\n", fd);

  // --- import into dev1 ---
  VkSemaphore sem1;
  CK(vkCreateSemaphore(d[1], &sci, NULL, &sem1));  // exportable+timeline, then import over it
  VkImportSemaphoreFdInfoKHR isi = {.sType = VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_FD_INFO_KHR,
                                    .semaphore = sem1,
                                    .flags = 0,
                                    .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT,
                                    .fd = fd};
  CK(importSemFd(d[1], &isi));
  printf("imported into dev1 OK\n");

  // --- dev1 waits for value 1; dev0 signals it. If ordering works across
  //     devices, the wait completes without any host synchronisation. ---
  uint64_t wait_val = 1, signal_val = 1;
  VkTimelineSemaphoreSubmitInfo w_tl = {
      .sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO,
      .waitSemaphoreValueCount = 1, .pWaitSemaphoreValues = &wait_val};
  VkPipelineStageFlags stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
  VkSubmitInfo w_si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                       .pNext = &w_tl,
                       .waitSemaphoreCount = 1,
                       .pWaitSemaphores = &sem1,
                       .pWaitDstStageMask = &stage};
  VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  VkFence done;
  CK(vkCreateFence(d[1], &fci, NULL, &done));
  CK(vkQueueSubmit(q[1], 1, &w_si, done));   // queued, blocked on the semaphore

  // it must NOT be signalled yet
  VkResult early = vkWaitForFences(d[1], 1, &done, VK_TRUE, 200000000ull);  // 200ms
  if (early != VK_TIMEOUT) {
    printf("FAIL dev1 work ran before dev0 signalled (res=%d)\n", early);
    return 1;
  }
  printf("dev1 correctly blocked waiting on peer semaphore\n");

  VkTimelineSemaphoreSubmitInfo s_tl = {
      .sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO,
      .signalSemaphoreValueCount = 1, .pSignalSemaphoreValues = &signal_val};
  VkSubmitInfo s_si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                       .pNext = &s_tl,
                       .signalSemaphoreCount = 1,
                       .pSignalSemaphores = &sem0};
  struct timespec t0, t1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  CK(vkQueueSubmit(q[0], 1, &s_si, VK_NULL_HANDLE));
  CK(vkWaitForFences(d[1], 1, &done, VK_TRUE, 5000000000ull));
  clock_gettime(CLOCK_MONOTONIC, &t1);
  double us = 1e6 * (t1.tv_sec - t0.tv_sec) + 1e-3 * (t1.tv_nsec - t0.tv_nsec);

  printf("PASS cross-device timeline semaphore works; signal->wake %.0f us\n", us);
  return 0;
}

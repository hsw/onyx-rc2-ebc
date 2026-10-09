/* SPDX-License-Identifier: MIT */
/*
 * fb_onyx.h -- reconstructed ONYX/Rockchip extension of framebuffer_device_t
 * (hardware/libhardware/include/hardware/fb.h) as used by the stock RC2
 * gralloc.rk30board.so and libsurfaceflinger.so (Android 4.2.2).
 *
 * RECONSTRUCTION: this header is not vendor source. It was reconstructed from the
 * stock binaries (gralloc.rk30board.so, libsurfaceflinger.so) by static analysis to
 * document the vendor ABI: field offsets, slot order and call signatures as observed
 * in the machine code. No vendor header was available.
 *
 * Evidence: see ebc-abi.md section 4.
 *  - gralloc framebuffer_device_open: malloc(0xd0); stores at 0xb8..0xcc.
 *  - libsurfaceflinger HWComposer::{setA2Region,setUpdateRegion,requestEpdMode,
 *    get_reagl,set_holddisp} load fbDev+0xb8/0xbc/0xc0/0xc4/0xc8.
 *  - 0xcc (set_autofull_max) is stored by gralloc but never called by SF.
 *
 * C++ only: android::Region is passed BY VALUE. Under the ARM EABI a class
 * with a non-trivial copy-ctor/dtor passed by value is passed as a pointer to
 * a caller-owned temporary (SF builds a Region copy on its stack and passes &copy
 * in r0). A C implementation may therefore declare these as
 *     int (*setA2Region)(const void *region /* android::Region* */);
 * The callee reads it via Region::getSize/flatten (4.2 libui ABI).
 */
#ifndef FB_ONYX_H
#define FB_ONYX_H

#include <hardware/hardware.h>

#ifdef __cplusplus
#include <ui/Region.h>
#endif

__BEGIN_DECLS

typedef struct framebuffer_device_t {
    struct hw_device_t common;                       /* 0x00..0x3f, tag 'HWDT', version 0 */

    const uint32_t  flags;                           /* 0x40 */
    const uint32_t  width;                           /* 0x44 */
    const uint32_t  height;                          /* 0x48 */
    const int       stride;                          /* 0x4c  line_length / (bpp/8) */
    const int       format;                          /* 0x50  = 5 (HAL_PIXEL_FORMAT_BGRA_8888) */
    const float     xdpi;                            /* 0x54 */
    const float     ydpi;                            /* 0x58 */
    const float     fps;                             /* 0x5c */
    const int       minSwapInterval;                 /* 0x60 = 1 */
    const int       maxSwapInterval;                 /* 0x64 = 1 */
    const int       numFramebuffers;                 /* 0x68 (0 in stock gralloc -> libui default) */
    int             reserved[7];                     /* 0x6c..0x87 */

    int (*setSwapInterval)(struct framebuffer_device_t* window, int interval);          /* 0x88 */
    int (*setUpdateRect)(struct framebuffer_device_t* window,
                         int left, int top, int width, int height);                      /* 0x8c = NULL */
    int (*post)(struct framebuffer_device_t* dev, buffer_handle_t buffer);               /* 0x90 fb_post -> EPD */
    int (*compositionComplete)(struct framebuffer_device_t* dev);                        /* 0x94 glFinish() */
    void (*dump)(struct framebuffer_device_t* dev, char *buff, int buff_len);           /* 0x98 = NULL */
    int (*enableScreen)(struct framebuffer_device_t* dev, int enable);                   /* 0x9c = NULL */
    void* reserved_proc[6];                          /* 0xa0..0xb7  -- end of AOSP 4.2/4.4 struct (0xb8) */

    /* ---- ONYX / Rockchip EPD extension (size grows 0xb8 -> 0xd0) ---- */
#ifdef __cplusplus
    /* 0xb8: gralloc fb_setA2Region(android::Region) -- flattens region (<=0x200 rects) into a
     *       static buffer consumed by the next post(); empty region = no A2. Returns 0. */
    int  (*setA2Region)(android::Region region);
    /* 0xbc: gralloc fb_setUpdateRegion(android::Region) -- same mechanism. Returns 0. */
    int  (*setUpdateRegion)(android::Region region);
#else
    int  (*setA2Region)(const void *region_cxx);
    int  (*setUpdateRegion)(const void *region_cxx);
#endif
    /* 0xc0: gralloc fb_requestEpdMode(framebuffer_device_t*, int mode) -- SF passes r0 = fbDev.
     *       mode = View$EINK_MODE value (-1..17), see epd-modes.tsv. Return value unused (void in gralloc). */
    void (*requestEpdMode)(struct framebuffer_device_t* dev, int mode);
    /* 0xc4: gralloc fb_get_reagl() -- no args used (SF passes fbDev in r0, ignored);
     *       returns 1 if ioctl 0x7004 returned non-zero (REAGL/holddisp capable). SF writes it to the reply parcel. */
    int  (*get_reagl)(void);
    /* 0xc8: gralloc fb_set_holddisp(int hold, int mode, int count) -- SF passes (val, mode, cnt) read
     *       from parcel of transaction 0x452 (mode forced to 3 when REGAL disabled). Returns 0. */
    int  (*set_holddisp)(int hold, int mode, int count);
    /* 0xcc: gralloc set_autofull_max(int) -- number of non-full updates before a forced EPD_FULL
     *       (default 400). Not called by stock SurfaceFlinger. */
    void (*set_autofull_max)(int max);
} framebuffer_device_t;                              /* sizeof == 0xd0 */

__END_DECLS

#endif /* FB_ONYX_H */

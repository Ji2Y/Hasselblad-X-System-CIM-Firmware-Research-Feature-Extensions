#ifndef X2D_MULTISHOT_RENDER_H
#define X2D_MULTISHOT_RENDER_H
#include "merge.h"
/* Streaming sRGB JPEG, quality 95, 4:4:4, no sharpening or enlargement.
 * Six-shot is already reduced to native-size RGB16 by merge.c.
 * Color conversion is matrix/WB based; not Hasselblad's proprietary rendering. */
/* jpeg may be NULL: generate only the small internal review preview. */
int ms_render(const char *dng,const MsFrame *metadata,const MsResult *geometry,
              const char *jpeg,const char *preview,MsProgress progress,void *context,char error[160]);
/* Bounded in-memory overview; never writes a JPEG or any photo sidecar. */
int ms_overview(const char *dng,unsigned width,unsigned height,
                unsigned char *rgb,size_t capacity,char error[160]);
int ms_roi(const char *dng,unsigned x,unsigned y,unsigned width,unsigned height,
           unsigned char *rgb,size_t capacity,char error[160]);
/* width=height=0 accepts only a small (<=2048 on both axes) complete preview. */
int ms_validate_jpeg(const char *path,unsigned width,unsigned height,
                     MsProgress progress,void *context,char error[160]);
/* Native codec sampling (including 4:2:0) is accepted; full decode is required.
 * With width=height=0 a vendor preview can be as large as the 400MP frame. */
int ms_validate_factory_jpeg(const char *path,unsigned width,unsigned height,
                     MsProgress progress,void *context,char error[160]);
#endif

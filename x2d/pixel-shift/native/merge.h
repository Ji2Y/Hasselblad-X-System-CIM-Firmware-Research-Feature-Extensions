#ifndef X2D_MULTISHOT_MERGE_H
#define X2D_MULTISHOT_MERGE_H
#include <stdint.h>
#include <stdio.h>
#include <sys/stat.h>
/* Coordinates and channel assembly derived from the MIT-licensed
 * Hasselblad-Feature-Extensions pixel_shift_rgb components (a75e55d).
 * Six-row kernel pinned at a4c7f5c0483346c686b9938ed87a48f32c5724f6.
 * Metadata validation, transactional IO and LinearRaw output are new code. */
typedef struct {
 FILE *file;
 unsigned char header[16384];
 unsigned count,index,black,white,main_ifd,raw_ifd,exif_ifd;
 unsigned sequence_aux[2],illuminant,orientation;
 double matrix[9],neutral[3];
 struct stat source_stat;
} MsFrame;
typedef struct {
 unsigned width,height,channels,frames;
 uint64_t bytes_written;
 char error[160];
} MsResult;
/* Return nonzero from progress to cancel. Sources are never modified. */
typedef int (*MsProgress)(void *,unsigned completed,unsigned total);
int ms_probe(const char *path,MsFrame *frame,char error[160]);
int ms_merged_metadata(const char *path,MsFrame *,MsResult *,char error[160]);
void ms_close(MsFrame *frame);
int ms_source_unchanged(const MsFrame *frame);
int ms_merge(const char *const *inputs,unsigned frames,const char *output,
             MsProgress progress,void *context,MsResult *result);
#endif

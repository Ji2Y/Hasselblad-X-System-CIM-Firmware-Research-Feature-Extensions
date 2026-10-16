/* Passive adapter core. Registration into the original stream is not provided. */
#ifndef PDAF425_STREAM_ADAPTER_H
#define PDAF425_STREAM_ADAPTER_H
#include "pdaf425_core.h"
typedef int (*p425_stock_calculate)(int,const void *,const void *);
struct p425_stream_adapter {
    p425_u8 *storage;
    p425_u64 capacity, verified_callsite;
    void *user;
    int (*readable)(void *,const void *,p425_u64);
    void (*snapshot_ready)(void *,const struct p425_frame *);
    struct p425_frame snapshot;
    unsigned int state; /* 0 idle, 1 armed, 2 copying, 3 snapshot retained */
    int capture_status;
};
int p425_stream_arm(struct p425_stream_adapter *);
int p425_stream_release(struct p425_stream_adapter *);
int p425_stream_calculate(struct p425_stream_adapter *,p425_stock_calculate,
                         p425_u64 caller_pc,int handle,const void *cfg,const void *input);
#endif

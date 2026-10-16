#include "pdaf425_stream_adapter.h"
struct lease { const p425_u8 *cfg; int held; };
static p425_u32 frame_number(const p425_u8 *cfg) {
    return (p425_u32)cfg[1]|((p425_u32)cfg[2]<<8)|((p425_u32)cfg[3]<<16)|((p425_u32)cfg[4]<<24);
}
static int lease_valid(void *owner,p425_u64 number) {
    struct lease *s=owner;
    return s->held && frame_number(s->cfg)==number;
}
int p425_stream_arm(struct p425_stream_adapter *s) {
    if (!s || !s->storage || s->capacity!=11776u*1248u*2u ||
        !s->verified_callsite || !s->readable || !s->snapshot_ready) return P425_INPUT;
    unsigned int expected=0;
    if (!__atomic_compare_exchange_n(&s->state,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
        return P425_INPUT;
    return P425_OK;
}
int p425_stream_release(struct p425_stream_adapter *s) {
    if (!s) return P425_INPUT;
    unsigned int expected=3;
    if (!__atomic_compare_exchange_n(&s->state,&expected,2,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
        return P425_INPUT;
    s->snapshot.raw=0; s->snapshot.bytes=0;
    __atomic_store_n(&s->state,0,__ATOMIC_RELEASE);
    return P425_OK;
}
int p425_stream_calculate(struct p425_stream_adapter *s,p425_stock_calculate original,
                         p425_u64 pc,int handle,const void *config,const void *input) {
    if (!original) return P425_BACKEND;
    int claimed=0, captured=P425_INPUT;
    /* The loader must byte-verify the original producer callsite, CPU-sync
     * sequence and original function before registering this adapter. */
    if (s && pc==s->verified_callsite && s->readable &&
        s->readable(s->user,config,P425_CFG_SIZE) &&
        s->readable(s->user,input,sizeof(void *))) {
        const p425_u8 *cfg=config;
        /* Segment 2 executes in another thread; it never owns this slot. */
        if (cfg[0]==1 && cfg[0xa8]==2 && cfg[0xa9]==1) {
            unsigned int expected=1;
            claimed=__atomic_compare_exchange_n(&s->state,&expected,2,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
            if (claimed) {
                const p425_u8 *raw;
                __builtin_memcpy(&raw,input,sizeof(raw));
                if (raw && s->readable(s->user,raw,s->capacity)) {
                    /* Scope is the synchronous original producer call. Its
                     * mapped/synced source stays held until original returns.
                     * This requires the audited producer registration; merely
                     * calling this API from arbitrary code proves no lease. */
                    struct lease scope={cfg,1};
                    captured=p425_capture_index2(raw,s->capacity,cfg,frame_number(cfg),
                                                s->storage,s->capacity,&scope,lease_valid,&s->snapshot);
                    scope.held=0;
                }
                s->capture_status=captured;
            }
        }
    }
    /* Exactly one original call, with the original pointers and return value. */
    int stock_status=original(handle,config,input);
    if (claimed) {
        if (captured==P425_OK && stock_status==0) {
            s->snapshot_ready(s->user,&s->snapshot);
            __atomic_store_n(&s->state,3,__ATOMIC_RELEASE);
        } else {
            s->snapshot.raw=0; s->snapshot.bytes=0;
            __atomic_store_n(&s->state,0,__ATOMIC_RELEASE);
        }
    }
    return stock_status;
}

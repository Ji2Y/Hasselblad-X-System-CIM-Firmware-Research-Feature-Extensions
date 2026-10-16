/* Copy the phase-bearing rows of the live-observed index-2 input layout.
 * Invoke only while the original stream producer holds an exclusive frame
 * lease. No device access, allocation, hook, or motor operation occurs here.
 */
#include "pdaf425_core.h"

static p425_u16 word16(const p425_u8 *p) { return (p425_u16)(p[0]|((p425_u16)p[1]<<8)); }
static p425_u32 word32(const p425_u8 *p) {
    return (p425_u32)p[0]|((p425_u32)p[1]<<8)|((p425_u32)p[2]<<16)|((p425_u32)p[3]<<24);
}
int p425_capture_index2(const p425_u8 *source, p425_u64 source_bytes,
                        const p425_u8 *cfg, p425_u64 frame_id,
                        p425_u8 *storage, p425_u64 storage_bytes,
                        void *owner, int (*lease_valid)(void *,p425_u64),
                        struct p425_frame *out) {
    const p425_u64 required=11776u*1248u*2u;
    if (!out) return P425_INPUT;
    out->raw=0; out->bytes=0; out->frame_id=0;
    if (!source || !cfg || !storage || !lease_valid ||
        source_bytes!=required || storage_bytes!=required ||
        cfg[0]!=1 || cfg[0xa8]!=2 || cfg[0xa9]!=1 ||
        word16(cfg+5)!=11664 || word16(cfg+7)!=1248 ||
        word32(cfg+1)!=frame_id || !word32(cfg+0x11)) return P425_INPUT;
    p425_u64 src=(p425_u64)(unsigned long)source;
    p425_u64 dst=(p425_u64)(unsigned long)storage;
    if (src+required<src || dst+required<dst ||
        (src<dst+required && dst<src+required)) return P425_INPUT;
    if (!lease_valid(owner,frame_id)) return P425_FRAME_CHANGED;
    p425_u8 config_copy[P425_CFG_SIZE];
    for (p425_u32 i=0;i<P425_CFG_SIZE;++i) config_copy[i]=cfg[i];
    for (p425_u64 i=0;i<required;++i) storage[i]=0;
    /* Mode 1 reads four channels, three offsets per group, spanning x=0..11.
     * 972 groups cover 11664 words. Padding and non-phase rows remain zero. */
    for (p425_u32 row=0;row<42;++row) {
        if (!lease_valid(owner,frame_id)) return P425_FRAME_CHANGED;
        p425_u64 offset=(7u+row*30u)*11776u*2u;
        for (p425_u32 i=0;i<11664u*2u;++i) storage[offset+i]=source[offset+i];
    }
    if (!lease_valid(owner,frame_id) || word32(cfg+1)!=frame_id) return P425_FRAME_CHANGED;
    for (p425_u32 i=0;i<P425_CFG_SIZE;++i) {
        if (config_copy[i]!=cfg[i]) return P425_FRAME_CHANGED;
        out->config[i]=config_copy[i];
    }
    out->raw=storage; out->bytes=required; out->frame_id=frame_id;
    return P425_OK;
}

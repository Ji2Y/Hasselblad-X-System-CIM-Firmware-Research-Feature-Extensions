/* X2D 4.2.0 measurement candidate. No lens-command or installation API. */
#ifndef PDAF425_CORE_H
#define PDAF425_CORE_H
typedef unsigned char p425_u8;
typedef unsigned short p425_u16;
typedef unsigned int p425_u32;
typedef unsigned long long p425_u64;
#define P425_COUNT 425u
#define P425_CFG_SIZE 0xaau
#define P425_NATIVE_SIZE 0x6ffu
enum { P425_OK=0, P425_INPUT=-1, P425_BACKEND=-2, P425_TIMEOUT=-3,
       P425_FRAME_CHANGED=-4 };
struct p425_roi { p425_u16 x, y, width, height; };
struct p425_frame {
    /* Caller-owned immutable copy, never a borrowed stream buffer. */
    const p425_u8 *raw;
    p425_u64 bytes, frame_id;
    p425_u8 config[P425_CFG_SIZE];
};
struct p425_record {
    struct p425_roi roi;
    /* Native local-result record, not translated to lens position/confidence. */
    p425_u8 native[13];
    p425_u8 usable;
};
struct p425_result {
    p425_u64 frame_id, elapsed_us;
    p425_u32 completed, usable, complete;
    struct p425_record records[P425_COUNT];
};
struct p425_backend {
    void *user;
    /* Exactly one ROI per call; output belongs exclusively to this worker. */
    int (*calculate)(void *, const struct p425_frame *, const p425_u8 *, p425_u8 *);
    p425_u64 (*clock_us)(void *);
    /* Verify the pinned immutable snapshot still has its original identity. */
    int (*same_frame)(void *, const struct p425_frame *);
};
int p425_plan(const struct p425_frame *, struct p425_roi [P425_COUNT]);
int p425_process(const struct p425_frame *, const struct p425_backend *,
                 p425_u64 budget_us, struct p425_result *);
/* ARM64-only native backend; isolated worker and producer-owned snapshot required. */
int p425_native_measure(const struct p425_frame *, p425_u64 budget_us,
                        struct p425_result *);
/* Producer-owned frame -> separate immutable snapshot. The lease adapter must
 * come from the real stream buffer owner; pointer equality is insufficient. */
int p425_capture_index2(const p425_u8 *source, p425_u64 source_bytes,
                        const p425_u8 *cfg, p425_u64 frame_id,
                        p425_u8 *storage, p425_u64 storage_bytes,
                        void *owner, int (*lease_valid)(void *,p425_u64),
                        struct p425_frame *out);
#endif

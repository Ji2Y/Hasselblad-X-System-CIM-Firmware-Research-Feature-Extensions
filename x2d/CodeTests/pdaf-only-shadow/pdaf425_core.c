#include "pdaf425_core.h"

struct geometry {
    p425_u16 width, stride, height, x, dx, y, dy, columns, rows;
};
/* Audited descriptors; mode-1 expansion remains inside the native algorithm.
 * Index 2 was observed in the live 4.2.0 / 55V AF-S producer on 2026-10-08. */
static const struct geometry geometries[3] = {
    {11760,11760,8842,57,12,147,210,970,42},
    {3888,3968,1248,3,4,7,30,970,42},
    {11664,11776,1248,0,12,7,30,972,42}
};
static void clear(void *p, unsigned long n) {
    p425_u8 *b=p; while (n--) *b++=0;
}
static void copy(void *d, const void *s, unsigned long n) {
    p425_u8 *a=d; const p425_u8 *b=s; while (n--) *a++=*b++;
}
static void put16(p425_u8 *p, p425_u16 v) { p[0]=(p425_u8)v; p[1]=(p425_u8)(v>>8); }
static p425_u16 get16(const p425_u8 *p) { return (p425_u16)(p[0]|((p425_u16)p[1]<<8)); }
static p425_u32 get32(const p425_u8 *p) {
    return (p425_u32)p[0]|((p425_u32)p[1]<<8)|((p425_u32)p[2]<<16)|((p425_u32)p[3]<<24);
}
static int finite32(const p425_u8 *p) { return (get32(p)&0x7f800000u)!=0x7f800000u; }

int p425_plan(const struct p425_frame *f, struct p425_roi rois[P425_COUNT]) {
    if (!f || !rois || !f->raw || f->config[0]!=1 || f->config[0xa8]>2 ||
        f->config[0xa9]!=1 || !get32(f->config+0x11)) return P425_INPUT;
    const struct geometry *g=&geometries[f->config[0xa8]];
    if (f->bytes!=(p425_u64)g->stride*g->height*2u ||
        get16(f->config+5)!=g->width || get16(f->config+7)!=g->height) return P425_INPUT;
    /* 25 x 17 is our experimental tiling, not the X2D II factory layout. */
    for (p425_u32 row=0; row<17; ++row) {
        p425_u32 y0=row*g->rows/17, y1=(row+1)*g->rows/17;
        for (p425_u32 col=0; col<25; ++col) {
            p425_u32 x0=col*g->columns/25, x1=(col+1)*g->columns/25;
            struct p425_roi *r=&rois[row*25+col];
            r->x=(p425_u16)(g->x+x0*g->dx);
            r->y=(p425_u16)(g->y+y0*g->dy);
            r->width=(p425_u16)((x1-x0)*g->dx);
            /* process_configuration uses height/dy + 1 rows. */
            r->height=(p425_u16)((y1-y0-1)*g->dy);
        }
    }
    return P425_OK;
}

int p425_process(const struct p425_frame *f, const struct p425_backend *b,
                 p425_u64 budget, struct p425_result *out) {
    struct p425_roi rois[P425_COUNT];
    p425_u8 cfg[P425_CFG_SIZE], native[P425_NATIVE_SIZE];
    if (!out) return P425_INPUT;
    clear(out,sizeof(*out));
    if (!b || !b->calculate || !b->clock_us || !b->same_frame || !budget ||
        p425_plan(f,rois)!=P425_OK) return P425_INPUT;
    const p425_u64 start=b->clock_us(b->user);
    if (!start) return P425_BACKEND;
    out->frame_id=f->frame_id;
    for (p425_u32 i=0; i<P425_COUNT; ++i) {
        p425_u64 now=b->clock_us(b->user);
        if (now<start || now-start>=budget) return P425_TIMEOUT;
        if (!b->same_frame(b->user,f)) return P425_FRAME_CHANGED;
        copy(cfg,f->config,sizeof(cfg));
        /* Preserve calibration/crop/lens/scene settings; replace only ROI slots. */
        clear(cfg+0x3b,10u*9u);
        cfg[0x3b]=1;
        put16(cfg+0x3c,rois[i].x); put16(cfg+0x3e,rois[i].y);
        put16(cfg+0x40,rois[i].width); put16(cfg+0x42,rois[i].height);
        clear(native,sizeof(native));
        if (b->calculate(b->user,f,cfg,native)!=0) return P425_BACKEND;
        if (!b->same_frame(b->user,f)) return P425_FRAME_CHANGED;
        now=b->clock_us(b->user);
        if (now<start || now-start>budget) return P425_TIMEOUT;
        out->records[i].roi=rois[i];
        copy(out->records[i].native,native+8,13);
        /* Conservative measurement filter; final AF acceptance is not defined. */
        out->records[i].usable=(get32(native)==1 && native[20]!=0 &&
                                finite32(native+8) && finite32(native+12));
        out->usable+=out->records[i].usable;
        out->completed=i+1;
        out->elapsed_us=now-start;
    }
    out->complete=1; /* Consumers must require complete AND status==P425_OK. */
    return P425_OK;
}

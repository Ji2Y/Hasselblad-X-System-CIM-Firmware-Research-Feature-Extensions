/* Synthetic host contract test. No stock firmware, camera or real frames. */
#include "pdaf425_stream_adapter.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
static unsigned int stock_calls, deliveries;
static int stock_return, permit_read=1;
static unsigned char *raw;
static const void *expected_config, *expected_input;
static int expected_handle;
static struct p425_stream_adapter *active;
static int readable(void *u,const void *p,p425_u64 n) {
    (void)u;return permit_read && p && n;
}
static int original(int h,const void *c,const void *i) {
    assert(h==expected_handle && c==expected_config && i==expected_input);
    ++stock_calls;
    /* Simulate reuse/change of original data after the pre-call copy. */
    raw[7*11776*2]=99;
    return stock_return;
}
static void delivered(void *u,const struct p425_frame *f) {
    (void)u;++deliveries;
    assert(f->frame_id==91 && f->raw[7*11776*2]==42);
    assert(p425_stream_release(active)==P425_INPUT); /* Notification still owns it. */
}
int main(void) {
    const size_t size=11776u*1248u*2u;
    raw=calloc(1,size);unsigned char *storage=calloc(1,size);assert(raw && storage);
    unsigned char cfg[170]={0};cfg[0]=1;cfg[1]=91;cfg[0x11]=1;
    cfg[5]=0x90;cfg[6]=0x2d;cfg[7]=0xe0;cfg[8]=4;cfg[0xa8]=2;cfg[0xa9]=1;
    const void *descriptor=raw;
    expected_config=cfg;expected_input=&descriptor;expected_handle=3;
    struct p425_stream_adapter s={0};active=&s;
    s.storage=storage;s.capacity=size;s.verified_callsite=0x1234;
    s.readable=readable;s.snapshot_ready=delivered;
    /* Disarmed pass-through. */
    stock_return=7;
    assert(p425_stream_calculate(&s,original,0x1234,3,cfg,&descriptor)==7);
    assert(stock_calls==1 && deliveries==0 && s.state==0);
    assert(p425_stream_arm(&s)==0);
    /* Wrong caller and secondary thread never consume the request. */
    assert(p425_stream_calculate(&s,original,0x8888,3,cfg,&descriptor)==7);
    cfg[0xa9]=2;
    assert(p425_stream_calculate(&s,original,0x1234,3,cfg,&descriptor)==7);
    cfg[0xa9]=1;assert(s.state==1 && deliveries==0 && stock_calls==3);
    /* Real adapter flow against synthetic input; unchanged return/pointers. */
    raw[7*11776*2]=42;stock_return=0;
    assert(p425_stream_calculate(&s,original,0x1234,3,cfg,&descriptor)==0);
    assert(s.state==3 && stock_calls==4 && deliveries==1);
    assert(p425_stream_arm(&s)==P425_INPUT);
    assert(p425_stream_calculate(&s,original,0x1234,3,cfg,&descriptor)==0);
    assert(stock_calls==5 && deliveries==1 && s.snapshot.raw[7*11776*2]==42);
    assert(p425_stream_release(&s)==0 && !s.snapshot.raw);
    /* Original failure cannot publish a snapshot. */
    assert(p425_stream_arm(&s)==0);raw[7*11776*2]=42;stock_return=-9;
    assert(p425_stream_calculate(&s,original,0x1234,3,cfg,&descriptor)==-9);
    assert(stock_calls==6 && deliveries==1 && s.state==0);
    /* A failed range check leaves original behavior and request intact. */
    assert(p425_stream_arm(&s)==0);permit_read=0;
    assert(p425_stream_calculate(&s,original,0x1234,3,cfg,&descriptor)==-9);
    assert(stock_calls==7 && deliveries==1 && s.state==1);
    free(raw);free(storage);
    puts("7 original calls preserved; single immutable snapshot; fallback/lifetime checks passed");
    return 0;
}

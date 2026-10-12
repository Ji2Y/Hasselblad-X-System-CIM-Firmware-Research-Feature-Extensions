#include "render.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>
#include <fcntl.h>
#include <unistd.h>
#include <jpeglib.h>
#ifdef MS_ANDROID
_Static_assert(JPEG_LIB_VERSION==62,"X2D jpeg ABI version");
_Static_assert(sizeof(struct jpeg_compress_struct)==520,"X2D jpeg ABI size");
_Static_assert(sizeof(struct jpeg_decompress_struct)==632,"X2D jpeg decode ABI size");
#endif
typedef struct {struct jpeg_error_mgr base;jmp_buf jump;char message[JMSG_LENGTH_MAX];} JpegError;
typedef struct {
 struct jpeg_compress_struct large,small;JpegError error;
 FILE *input,*output,*preview;
 int large_created,small_created;
 uint16_t *raw;unsigned char *rgb,*thumb,*transfer;
 uint64_t *sums;
 double transform[9];unsigned width,height,channels,scale,small_width,small_height;
} Render;
static void jpeg_failure(j_common_ptr c){JpegError *e=(void *)c->err;c->err->format_message(c,e->message);longjmp(e->jump,1);}
static int reflect(int n,int size){return n<0?-n:n>=size?2*size-2-n:n;}
static unsigned sample(Render *r,int x,int y){return r->raw[(y+1)*r->width+reflect(x,(int)r->width)];}
static void rgb_pixel(Render *r,unsigned x,unsigned y,double *out){
 if(r->channels==3){for(unsigned c=0;c<3;c++)out[c]=r->raw[x*3+c];return;}
 unsigned v=sample(r,x,0),left=sample(r,(int)x-1,0),right=sample(r,(int)x+1,0),up=sample(r,x,-1),down=sample(r,x,1);
 if(!(y&1)&&!(x&1)){out[0]=(left+right)/2.;out[1]=v;out[2]=(up+down)/2.;}
 else if((y&1)&&(x&1)){out[0]=(up+down)/2.;out[1]=v;out[2]=(left+right)/2.;}
 else{
  unsigned diagonal=sample(r,(int)x-1,-1)+sample(r,(int)x+1,-1)+sample(r,(int)x-1,1)+sample(r,(int)x+1,1);
  out[1]=(left+right+up+down)/4.;out[!(y&1)?0:2]=v;out[!(y&1)?2:0]=diagonal/4.;
 }
}
static int conversion(Render *r,const MsFrame *f){
 const double xyz[9]={.4124564,.3575761,.1804375,.2126729,.7151522,.0721750,.0193339,.1191920,.9503041};
 double a[9];for(unsigned i=0;i<3;i++){
  double sum=0;for(unsigned j=0;j<3;j++){a[3*i+j]=0;for(unsigned k=0;k<3;k++)a[3*i+j]+=f->matrix[3*i+k]*xyz[3*k+j];sum+=a[3*i+j];}
  if(!isfinite(sum)||fabs(sum)<1e-12)return 0;for(unsigned j=0;j<3;j++)a[3*i+j]/=sum;
 }
 double d=a[0]*(a[4]*a[8]-a[5]*a[7])-a[1]*(a[3]*a[8]-a[5]*a[6])+a[2]*(a[3]*a[7]-a[4]*a[6]);if(!isfinite(d)||fabs(d)<1e-12)return 0;
 double inv[9]={a[4]*a[8]-a[5]*a[7],a[2]*a[7]-a[1]*a[8],a[1]*a[5]-a[2]*a[4],a[5]*a[6]-a[3]*a[8],a[0]*a[8]-a[2]*a[6],a[2]*a[3]-a[0]*a[5],a[3]*a[7]-a[4]*a[6],a[1]*a[6]-a[0]*a[7],a[0]*a[4]-a[1]*a[3]};
 for(unsigned i=0;i<9;i++){r->transform[i]=inv[i]/d*f->neutral[1]/f->neutral[i%3]/(f->white-f->black);if(!isfinite(r->transform[i]))return 0;}
 return 1;
}
static FILE *exclusive(const char *path){int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return NULL;FILE *f=fdopen(fd,"wb");if(!f)close(fd);return f;}
static void start_jpeg(struct jpeg_compress_struct *c,FILE *out,unsigned w,unsigned h,unsigned orientation){
 jpeg_stdio_dest(c,out);c->image_width=w;c->image_height=h;c->input_components=3;c->in_color_space=JCS_RGB;
 jpeg_set_defaults(c);jpeg_set_quality(c,95,TRUE);c->optimize_coding=FALSE;
 for(int i=0;i<3;i++){c->comp_info[i].h_samp_factor=1;c->comp_info[i].v_samp_factor=1;}
 jpeg_start_compress(c,TRUE);
 /* EXIF identity, source orientation and sRGB ColorSpace. */
 unsigned char exif[]={
  'E','x','i','f',0,0,'I','I',42,0,8,0,0,0,4,0,
  15,1,2,0,11,0,0,0,62,0,0,0,
  16,1,2,0,9,0,0,0,73,0,0,0,
  18,1,3,0,1,0,0,0,1,0,0,0,
  105,135,4,0,1,0,0,0,82,0,0,0,
  0,0,0,0,'H','a','s','s','e','l','b','l','a','d',0,'X','2','D',' ','1','0','0','C',0,
  1,0,1,160,3,0,1,0,0,0,1,0,0,0,0,0,0,0};
 exif[48]=(unsigned char)orientation;
 jpeg_write_marker(c,JPEG_APP0+1,exif,sizeof(exif));
}
int ms_render(const char *dng,const MsFrame *f,const MsResult *g,const char *jpeg,const char *preview,MsProgress progress,void *context,char error[160]){
 int ok=0;Render *r=calloc(1,sizeof(*r));if(!r){snprintf(error,160,"render allocation failed");return 0;}
 snprintf(error,160,"render failed; sources and partial outputs retained");
 r->width=g->width;r->height=g->height;r->channels=g->channels;
 if(r->width<2||r->height<2||r->width>23326||r->height>17498||(r->channels!=1&&r->channels!=3)||f->white<=f->black)goto done;
 r->scale=(r->width+1279)/1280;r->small_width=(r->width+r->scale-1)/r->scale;r->small_height=(r->height+r->scale-1)/r->scale;
 if(!conversion(r,f))goto done;
 r->raw=malloc((size_t)r->width*3*2);r->rgb=malloc((size_t)r->width*3);r->thumb=malloc(r->small_width*3);r->sums=calloc(r->small_width*3,sizeof(uint64_t));r->transfer=malloc(65536);
 if(!r->raw||!r->rgb||!r->thumb||!r->sums||!r->transfer)goto done;
 for(unsigned i=0;i<65536;i++){double v=i/65535.;double s=v<=.0031308?12.92*v:1.055*pow(v,1/2.4)-.055;r->transfer[i]=(unsigned char)(s*255+.5);}
 r->input=fopen(dng,"rb");if(!r->input||fseek(r->input,0,SEEK_END)||ftell(r->input)!=(long)(4096+(uint64_t)r->width*r->height*r->channels*2))goto done;
 r->output=jpeg?exclusive(jpeg):NULL;r->preview=exclusive(preview);if((jpeg&&!r->output)||!r->preview)goto done;
 r->large.err=jpeg_std_error(&r->error.base);r->error.base.error_exit=jpeg_failure;r->small.err=&r->error.base;
 if(setjmp(r->error.jump))goto done;
 if(jpeg){jpeg_create_compress(&r->large);r->large_created=1;}jpeg_create_compress(&r->small);r->small_created=1;
 if(jpeg)start_jpeg(&r->large,r->output,r->width,r->height,f->orientation);start_jpeg(&r->small,r->preview,r->small_width,r->small_height,f->orientation);
 unsigned accumulated=0;
 for(unsigned y=0;y<r->height;y++){
  if(progress&&progress(context,y,r->height)){snprintf(error,160,"render cancelled; source RAWs preserved");goto done;}
  if(r->channels==3){if(fseek(r->input,4096+(long)y*r->width*6,SEEK_SET)||fread(r->raw,2,r->width*3,r->input)!=r->width*3)goto done;}
  else for(int dy=-1;dy<=1;dy++){
   unsigned sy=reflect((int)y+dy,(int)r->height);
   if(fseek(r->input,4096+(long)sy*r->width*2,SEEK_SET)||fread(r->raw+(dy+1)*r->width,2,r->width,r->input)!=r->width)goto done;
  }
  for(unsigned x=0;x<r->width;x++){
   double camera[3];rgb_pixel(r,x,y,camera);for(unsigned c=0;c<3;c++)camera[c]-=f->black;
   for(unsigned c=0;c<3;c++){
    double v=0;for(unsigned k=0;k<3;k++)v+=r->transform[c*3+k]*camera[k];if(v<0)v=0;if(v>1)v=1;
    unsigned char b=r->transfer[(unsigned)(v*65535+.5)];r->rgb[x*3+c]=b;r->sums[(x/r->scale)*3+c]+=b;
   }
  }
  JSAMPROW row=r->rgb;if(jpeg&&jpeg_write_scanlines(&r->large,&row,1)!=1)goto done;
  accumulated++;
  if(accumulated==r->scale||y+1==r->height){
   for(unsigned x=0;x<r->small_width;x++){
    unsigned columns=r->width-x*r->scale;if(columns>r->scale)columns=r->scale;unsigned n=columns*accumulated;
    for(unsigned c=0;c<3;c++){unsigned i=x*3+c;r->thumb[i]=(unsigned char)((r->sums[i]+n/2)/n);r->sums[i]=0;}
   }
   row=r->thumb;if(jpeg_write_scanlines(&r->small,&row,1)!=1)goto done;accumulated=0;
  }
 }
 if(jpeg)jpeg_finish_compress(&r->large);jpeg_finish_compress(&r->small);
 if((r->output&&(fflush(r->output)||fsync(fileno(r->output))))||fflush(r->preview)||fsync(fileno(r->preview)))goto done;
 if(progress)progress(context,r->height,r->height);error[0]=0;ok=1;
done:
 if(r->large_created)jpeg_destroy_compress(&r->large);if(r->small_created)jpeg_destroy_compress(&r->small);
 if(r->input)fclose(r->input);if(r->output&&fclose(r->output))ok=0;if(r->preview&&fclose(r->preview))ok=0;
 free(r->raw);free(r->rgb);free(r->thumb);free(r->sums);free(r->transfer);free(r);return ok;
}
int ms_roi(const char *dng,unsigned x0,unsigned y0,unsigned w,unsigned h,unsigned char *rgb,size_t capacity,char error[160]){
 if(!w||!h||w>1024||h>768||capacity<(size_t)w*h*3){snprintf(error,160,"ROI bounds invalid");return 0;}
 MsFrame f;MsResult g;if(!ms_merged_metadata(dng,&f,&g,error))return 0;
 if(x0>=g.width||y0>=g.height||w>g.width-x0||h>g.height-y0){ms_close(&f);return 0;}
 Render r={0};r.width=g.width;r.height=g.height;r.channels=g.channels;r.raw=malloc((size_t)r.width*6);r.transfer=malloc(65536);int ok=0;
 if(!r.raw||!r.transfer||!conversion(&r,&f))goto done;
 for(unsigned i=0;i<65536;i++){double v=i/65535.,s=v<=.0031308?12.92*v:1.055*pow(v,1/2.4)-.055;r.transfer[i]=(unsigned char)(s*255+.5);}
 for(unsigned y=y0;y<y0+h;y++){
  if(r.channels==3){if(fseek(f.file,4096+(long)y*r.width*6,SEEK_SET)||fread(r.raw,2,r.width*3,f.file)!=r.width*3)goto done;}
  else for(int dy=-1;dy<=1;dy++){unsigned sy=reflect((int)y+dy,r.height);if(fseek(f.file,4096+(long)sy*r.width*2,SEEK_SET)||fread(r.raw+(dy+1)*r.width,2,r.width,f.file)!=r.width)goto done;}
  for(unsigned x=x0;x<x0+w;x++){
   double c[3];rgb_pixel(&r,x,y,c);for(unsigned i=0;i<3;i++)c[i]-=f.black;
   for(unsigned i=0;i<3;i++){double v=0;for(unsigned k=0;k<3;k++)v+=r.transform[i*3+k]*c[k];if(v<0)v=0;if(v>1)v=1;rgb[((size_t)(y-y0)*w+x-x0)*3+i]=r.transfer[(unsigned)(v*65535+.5)];}
  }
 }
 ok=1;
done:ms_close(&f);free(r.raw);free(r.transfer);return ok;
}
/* Sample an overview directly from the verified RAW, using bounded row buffers.
 * Display only: the saved linear RAW is not modified by this rendering. */
int ms_overview(const char *dng,unsigned w,unsigned h,unsigned char *rgb,size_t capacity,char error[160]){
 if(!w||!h||w>1024||h>768||capacity<(size_t)w*h*3){snprintf(error,160,"Overview bounds invalid");return 0;}
 MsFrame f;MsResult g;if(!ms_merged_metadata(dng,&f,&g,error))return 0;
 Render r={0};r.width=g.width;r.height=g.height;r.channels=g.channels;r.raw=malloc((size_t)r.width*6);r.transfer=malloc(65536);int ok=0;
 if(!r.raw||!r.transfer||!conversion(&r,&f))goto done;
 for(unsigned i=0;i<65536;i++){double v=i/65535.,z=v<=.0031308?12.92*v:1.055*pow(v,1/2.4)-.055;r.transfer[i]=(unsigned char)(z*255+.5);}
 for(unsigned oy=0;oy<h;oy++){
  unsigned y=(unsigned)(((uint64_t)oy*2+1)*r.height/(2*h));
  if(r.channels==3){if(fseek(f.file,4096+(long)y*r.width*6,SEEK_SET)||fread(r.raw,2,r.width*3,f.file)!=r.width*3)goto done;}
  else for(int dy=-1;dy<=1;dy++){unsigned sy=reflect((int)y+dy,r.height);if(fseek(f.file,4096+(long)sy*r.width*2,SEEK_SET)||fread(r.raw+(dy+1)*r.width,2,r.width,f.file)!=r.width)goto done;}
  for(unsigned ox=0;ox<w;ox++){
   unsigned x=(unsigned)(((uint64_t)ox*2+1)*r.width/(2*w));double c[3];rgb_pixel(&r,x,y,c);for(unsigned i=0;i<3;i++)c[i]-=f.black;
   for(unsigned i=0;i<3;i++){double v=0;for(unsigned k=0;k<3;k++)v+=r.transform[i*3+k]*c[k];if(v<0)v=0;if(v>1)v=1;rgb[((size_t)oy*w+ox)*3+i]=r.transfer[(unsigned)(v*65535+.5)];}
  }
 }
 ok=1;
done:ms_close(&f);free(r.raw);free(r.transfer);return ok;
}
/* Scanline validation is deliberately bounded even for a 408 MP result.
 * Treat libjpeg warnings (including an inserted EOI on truncation) as failure. */
typedef struct {struct jpeg_decompress_struct jpeg;JpegError error;FILE *file;unsigned char *row;int created;} CheckJpeg;
static void jpeg_warning(j_common_ptr c,int level){if(level<0)jpeg_failure(c);}
static int validate_jpeg(const char *path,unsigned w,unsigned h,int require444,MsProgress cb,void *context,char error[160]){
 int ok=0;CheckJpeg *c=calloc(1,sizeof(*c));if(!c)return 0;
 snprintf(error,160,"JPEG verification failed; partial output retained");
 c->file=fopen(path,"rb");if(!c->file)goto done;
 c->jpeg.err=jpeg_std_error(&c->error.base);c->error.base.error_exit=jpeg_failure;c->error.base.emit_message=jpeg_warning;
 if(setjmp(c->error.jump))goto done;
 jpeg_create_decompress(&c->jpeg);c->created=1;jpeg_stdio_src(&c->jpeg,c->file);
 if(jpeg_read_header(&c->jpeg,TRUE)!=JPEG_HEADER_OK||c->jpeg.num_components!=3||c->jpeg.progressive_mode)goto done;
 if(w||h){if(c->jpeg.image_width!=w||c->jpeg.image_height!=h)goto done;}
 else if(!c->jpeg.image_width||!c->jpeg.image_height||
         c->jpeg.image_width>(require444?2048u:23326u)||c->jpeg.image_height>(require444?2048u:17498u))goto done;
 if(require444)for(unsigned i=0;i<3;i++)if(c->jpeg.comp_info[i].h_samp_factor!=1||c->jpeg.comp_info[i].v_samp_factor!=1)goto done;
 w=c->jpeg.image_width;h=c->jpeg.image_height;
 c->jpeg.out_color_space=JCS_RGB;c->jpeg.buffered_image=FALSE;
 if(!jpeg_start_decompress(&c->jpeg)||c->jpeg.output_components!=3)goto done;
 c->row=malloc((size_t)w*3);if(!c->row)goto done;
 while(c->jpeg.output_scanline<h){
  if(cb&&cb(context,c->jpeg.output_scanline,h))goto done;
  JSAMPROW row=c->row;if(jpeg_read_scanlines(&c->jpeg,&row,1)!=1)goto done;
 }
 if(!jpeg_finish_decompress(&c->jpeg))goto done;
 ok=1;error[0]=0;
done:if(!ok&&c->error.message[0])snprintf(error,160,"Preview JPEG verification: %.125s",c->error.message);
 if(c->created)jpeg_destroy_decompress(&c->jpeg);if(c->file)fclose(c->file);free(c->row);free(c);return ok;
}
int ms_validate_jpeg(const char *path,unsigned w,unsigned h,MsProgress cb,void *context,char error[160]){
 return validate_jpeg(path,w,h,1,cb,context,error);
}
int ms_validate_factory_jpeg(const char *path,unsigned w,unsigned h,MsProgress cb,void *context,char error[160]){
 return validate_jpeg(path,w,h,0,cb,context,error);
}

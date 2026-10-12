/* X2D 4.2.0: four/six inputs -> native-size linear RGB16. No camera calls.
 * Six-shot reduction is our experimental processing, not a Phocus algorithm. */
#include "merge.h"
#include "vendor/six_row_kernel.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>
#ifndef MS_WIDTH
#define MS_WIDTH 11663u
#define MS_HEIGHT 8749u
#endif
#define RAW_WIDTH 11904u
#define RAW_HEIGHT 8842u
#define RAW_BYTES ((uint64_t)RAW_WIDTH*RAW_HEIGHT*2)
#define HEADER_BYTES 16384u
static unsigned u16(const unsigned char *p){return p[0]|((unsigned)p[1]<<8);}
static uint32_t u32(const unsigned char *p){return u16(p)|((uint32_t)u16(p+2)<<16);}
static void p16(unsigned char *p,unsigned n){p[0]=n;p[1]=n>>8;}
static void p32(unsigned char *p,uint32_t n){p16(p,n);p16(p+2,n>>16);}
static int err(char *out,const char *message){snprintf(out,160,"%s",message);return 0;}
static unsigned size_type(unsigned type){
 switch(type){case 1:case 2:case 7:return 1;case 3:return 2;case 4:case 9:return 4;case 5:case 10:return 8;default:return 0;}
}
/* Never return unchecked TIFF pointers, including duplicate/overflow cases. */
static const unsigned char *tag(const MsFrame *f,unsigned ifd,unsigned id){
 if(ifd<8||ifd>HEADER_BYTES-6)return NULL;
 unsigned count=u16(f->header+ifd);if(count>256||ifd+2+12*count+4>HEADER_BYTES)return NULL;
 const unsigned char *found=NULL;
 for(unsigned i=0;i<count;i++){
  const unsigned char *p=f->header+ifd+2+12*i;
  if(u16(p)==id){if(found)return NULL;found=p;}
 }
 return found;
}
static const unsigned char *value(const MsFrame *f,const unsigned char *t,unsigned type,unsigned count){
 if(!t||u16(t+2)!=type||u32(t+4)!=count||!size_type(type)||count>HEADER_BYTES/size_type(type))return NULL;
 unsigned bytes=count*size_type(type);if(bytes<=4)return t+8;
 unsigned offset=u32(t+8);if(offset>HEADER_BYTES||bytes>HEADER_BYTES-offset)return NULL;
 return f->header+offset;
}
static int scalar(const MsFrame *f,unsigned ifd,unsigned id,unsigned *v){
 const unsigned char *t=tag(f,ifd,id);if(!t)return 0;unsigned type=u16(t+2);
 if(type!=3&&type!=4)return 0;
 const unsigned char *p=value(f,t,type,1);if(!p)return 0;*v=type==3?u16(p):u32(p);return 1;
}
static int equal_scalar(const MsFrame *f,unsigned ifd,unsigned id,unsigned expected){unsigned v;return scalar(f,ifd,id,&v)&&v==expected;}
static int ratios(const MsFrame *f,unsigned ifd,unsigned id,unsigned type,unsigned count,double *out){
 const unsigned char *p=value(f,tag(f,ifd,id),type,count);if(!p)return 0;
 for(unsigned i=0;i<count;i++){
  double n=type==10?(double)(int32_t)u32(p+8*i):u32(p+8*i);
  double d=type==10?(double)(int32_t)u32(p+8*i+4):u32(p+8*i+4);
  if(!d)return 0;out[i]=n/d;if(!isfinite(out[i]))return 0;
 }
 return 1;
}
static int ascii_equal(const MsFrame *f,unsigned ifd,unsigned id,const char *s){
 const unsigned char *t=tag(f,ifd,id);unsigned n=(unsigned)strlen(s)+1;
 const unsigned char *v=value(f,t,2,n);return v&&!memcmp(v,s,n);
}
void ms_close(MsFrame *f){if(f&&f->file){fclose(f->file);f->file=NULL;}}
int ms_source_unchanged(const MsFrame *f){
 struct stat now;
 if(!f->file||fstat(fileno(f->file),&now))return 0;
#ifdef __APPLE__
 if(now.st_mtimespec.tv_nsec!=f->source_stat.st_mtimespec.tv_nsec||now.st_ctimespec.tv_nsec!=f->source_stat.st_ctimespec.tv_nsec)return 0;
#else
 if(now.st_mtim.tv_nsec!=f->source_stat.st_mtim.tv_nsec||now.st_ctim.tv_nsec!=f->source_stat.st_ctim.tv_nsec)return 0;
#endif
 return now.st_dev==f->source_stat.st_dev&&now.st_ino==f->source_stat.st_ino&&
  now.st_size==f->source_stat.st_size&&now.st_mtime==f->source_stat.st_mtime&&now.st_ctime==f->source_stat.st_ctime;
}
int ms_probe(const char *path,MsFrame *f,char error[160]){
 memset(f,0,sizeof(*f));int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
 if(fd<0)return err(error,"cannot open source RAW");
 if(fstat(fd,&f->source_stat)||!S_ISREG(f->source_stat.st_mode)){close(fd);return err(error,"source must be a regular RAW file");}
 f->file=fdopen(fd,"rb");if(!f->file){close(fd);return err(error,"source stream failed");}
 if(fseek(f->file,0,SEEK_END)||ftell(f->file)<(long)(HEADER_BYTES+RAW_BYTES)||fseek(f->file,0,SEEK_SET))goto truncated;
 if(fread(f->header,1,HEADER_BYTES,f->file)!=HEADER_BYTES)goto truncated;
 if(memcmp(f->header,"II\052\000",4))goto layout;
 f->main_ifd=u32(f->header+4);
 f->orientation=1;
 if(tag(f,f->main_ifd,274)&&(!scalar(f,f->main_ifd,274,&f->orientation)||f->orientation<1||f->orientation>8))goto layout;
 if(!scalar(f,f->main_ifd,330,&f->raw_ifd)||!scalar(f,f->main_ifd,34665,&f->exif_ifd))goto layout;
 if(!ascii_equal(f,f->main_ifd,271,"Hasselblad")||
    !(ascii_equal(f,f->main_ifd,272,"X2D 100C")||ascii_equal(f,f->main_ifd,272,"Hasselblad X2D 100C")))goto layout;
 unsigned raw=f->raw_ifd;
 const unsigned ids[]={256,257,258,259,262,277,273,279,50717};
 const unsigned expected[]={RAW_WIDTH,RAW_HEIGHT,16,1,32803,1,HEADER_BYTES,(unsigned)RAW_BYTES,65535};
 for(unsigned i=0;i<sizeof(ids)/sizeof(ids[0]);i++){
  unsigned got;if(!scalar(f,raw,ids[i],&got)){ms_close(f);snprintf(error,160,"missing or non-scalar RAW tag %u",ids[i]);return 0;}
  if(got!=expected[i]){ms_close(f);snprintf(error,160,"RAW tag %u is %u; expected %u",ids[i],got,expected[i]);return 0;}
 }
 /* Native X2D 3FR omits both DNG CFA tags (verified on the previously captured four-frame sequence).
  * The exact X2D identity and uncompressed sensor layout above select the
  * fixed RGGB reader. If CFA tags are present, require the complete matching
  * pair; never treat malformed, duplicate or conflicting tags as absent. */
 unsigned cfa_entries=0;
 for(unsigned i=0;i<u16(f->header+raw);i++){
  unsigned id=u16(f->header+raw+2+12*i);
  if(id==33421||id==33422)cfa_entries++;
 }
 if(cfa_entries){
  const unsigned char *cfa=value(f,tag(f,raw,33422),1,4),*dim=value(f,tag(f,raw,33421),3,2);
  if(cfa_entries!=2||!cfa||memcmp(cfa,"\000\001\001\002",4)||!dim||u16(dim)!=2||u16(dim+2)!=2){
   ms_close(f);return err(error,"incomplete, malformed or unsupported RAW CFA tags");
  }
 }
 /* The source reader is intentionally restricted to this exact sensor layout. */
 const unsigned char *area=tag(f,raw,50829);
 if(area){const unsigned char *a=value(f,area,4,4);if(!a||u32(a)!=92||u32(a+4)!=124||u32(a+8)<92+MS_HEIGHT+1||u32(a+12)<124+MS_WIDTH+1)goto layout;}
 const unsigned char *maker=tag(f,f->exif_ifd,37500);
 if(!maker||u16(maker+2)!=7||u32(maker+4)<6)goto layout;
 unsigned maker_ifd=u32(maker+8);
 const unsigned char *group=value(f,tag(f,maker_ifd,33),9,4);
 if(!group)goto layout;
 f->count=u32(group);f->index=u32(group+4);f->sequence_aux[0]=u32(group+8);f->sequence_aux[1]=u32(group+12);
 if((f->count!=4&&f->count!=6)||f->index>=f->count)goto layout;
 double black;if(!ratios(f,raw,50714,5,1,&black)||black<0||black>8192||black!=(unsigned)black)goto layout;
 f->black=(unsigned)black;f->white=65535;
 if(!ratios(f,f->main_ifd,50721,10,9,f->matrix)||!ratios(f,f->main_ifd,50728,5,3,f->neutral))goto layout;
 for(unsigned i=0;i<3;i++)if(f->neutral[i]<=0)goto layout;
 double *m=f->matrix;double det=m[0]*(m[4]*m[8]-m[5]*m[7])-m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6]);
 if(fabs(det)<1e-12)goto layout;
 /* No invented D65 calibration. Preserve a supplied illuminant, or unknown. */
 f->illuminant=0;scalar(f,f->main_ifd,50778,&f->illuminant);
 double exposure,aperture;unsigned iso;
 if(!ratios(f,f->exif_ifd,33434,5,1,&exposure)||exposure<=0||!ratios(f,f->exif_ifd,33437,5,1,&aperture)||aperture<=0||!scalar(f,f->exif_ifd,34855,&iso)||!iso)goto layout;
 return 1;
truncated:ms_close(f);return err(error,"truncated/unreadable RAW or compressed input; uncompressed 16-bit RAW required");
layout:ms_close(f);return err(error,"unsupported RAW layout, identity or metadata");
}
static int same_tag(const MsFrame *a,unsigned ai,const MsFrame *b,unsigned bi,unsigned id){
 const unsigned char *x=tag(a,ai,id),*y=tag(b,bi,id);if(!x||!y)return 0;
 unsigned type=u16(x+2),other=u16(y+2),count=u32(x+4);
 if(!count||count>64||count!=u32(y+4))return 0;
 const unsigned char *p=value(a,x,type,count),*q=value(b,y,other,count);if(!p||!q)return 0;
 /* TIFF numeric values can have different but equivalent encodings. */
 if((type==3||type==4)&&(other==3||other==4)){
  for(unsigned i=0;i<count;i++)if((type==3?u16(p+2*i):u32(p+4*i))!=(other==3?u16(q+2*i):u32(q+4*i)))return 0;
  return 1;
 }
 if(type!=other)return 0;
 if(type==5||type==10){
  for(unsigned i=0;i<count;i++){
   if(type==5){uint64_t an=u32(p+8*i),ad=u32(p+8*i+4),bn=u32(q+8*i),bd=u32(q+8*i+4);if(!ad||!bd||an*bd!=bn*ad)return 0;}
   else{int64_t an=(int32_t)u32(p+8*i),ad=(int32_t)u32(p+8*i+4),bn=(int32_t)u32(q+8*i),bd=(int32_t)u32(q+8*i+4);if(!ad||!bd||an*bd!=bn*ad)return 0;}
  }
  return 1;
 }
 return !memcmp(p,q,count*size_type(type));
}
int ms_merged_metadata(const char *path,MsFrame *f,MsResult *r,char error[160]){
 memset(f,0,sizeof(*f));memset(r,0,sizeof(*r));int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return err(error,"review unavailable");
 f->file=fdopen(fd,"rb");if(!f->file){close(fd);return err(error,"review open failed");}
 if(fread(f->header,1,4096,f->file)!=4096||memcmp(f->header,"II\052\000",4))goto bad;
 f->main_ifd=u32(f->header+4);unsigned ifd=f->main_ifd,photometric;
 if(!scalar(f,ifd,256,&r->width)||!scalar(f,ifd,257,&r->height)||!scalar(f,ifd,277,&r->channels)||!scalar(f,ifd,262,&photometric)||
    !equal_scalar(f,ifd,273,4096)||!equal_scalar(f,ifd,259,1)||!ascii_equal(f,ifd,305,"X2D experimental multishot")||
    r->width<2||r->width>23326||r->height<2||r->height>17498)return ms_close(f),err(error,"unsupported review image");
 if(r->channels!=3||photometric!=34892||r->width!=MS_WIDTH||r->height!=MS_HEIGHT)goto bad;
 const char *four="X2D multi-shot source frames: 4",*six="X2D multi-shot source frames: 6";
 if(ascii_equal(f,ifd,270,four))r->frames=4;
 else if(ascii_equal(f,ifd,270,six))r->frames=6;
 else goto bad;
 if(!scalar(f,ifd,274,&f->orientation)||f->orientation<1||f->orientation>8)goto bad;
 const unsigned char *bits=value(f,tag(f,ifd,258),3,r->channels),*black=value(f,tag(f,ifd,50714),4,r->channels),*white=value(f,tag(f,ifd,50717),4,r->channels);
 if(!bits||!black||!white)goto bad;f->black=u32(black);f->white=u32(white);
 for(unsigned c=0;c<r->channels;c++)if(u16(bits+2*c)!=16||u32(black+4*c)!=f->black||u32(white+4*c)!=f->white)goto bad;
 if(f->white!=65535||f->black>8192||!ratios(f,ifd,50721,10,9,f->matrix)||!ratios(f,ifd,50728,5,3,f->neutral))goto bad;
 for(unsigned c=0;c<3;c++)if(f->neutral[c]<=0)goto bad;
 r->bytes_written=4096+(uint64_t)r->width*r->height*r->channels*2;
 if(!equal_scalar(f,ifd,279,(unsigned)(r->bytes_written-4096))||fseek(f->file,0,SEEK_END)||ftell(f->file)!=(long)r->bytes_written)goto bad;
 return 1;
bad:ms_close(f);return err(error,"review metadata or pixels invalid");
}
typedef struct {unsigned char data[4096];unsigned n,extra;} Writer;
static int entry(Writer *w,unsigned id,unsigned type,unsigned count,const void *data){
 unsigned bytes=count*size_type(type);if(!bytes||w->n>=40||w->extra+bytes>4096)return 0;
 unsigned char *t=w->data+10+12*w->n++;p16(t,id);p16(t+2,type);p32(t+4,count);
 if(bytes<=4)memcpy(t+8,data,bytes);else{p32(t+8,w->extra);memcpy(w->data+w->extra,data,bytes);w->extra=(w->extra+bytes+3)&~3u;}
 return 1;
}
static int number(Writer *w,unsigned id,unsigned type,unsigned v){unsigned char b[4];p32(b,v);return entry(w,id,type,1,b);}
static int header(Writer *w,MsFrame *f,unsigned count,unsigned width,unsigned height){
 memset(w,0,sizeof(*w));w->extra=1024;memcpy(w->data,"II\052\000",4);p32(w->data+4,8);
 unsigned channels=3;unsigned char bits[6]={16,0,16,0,16,0};
 if(!number(w,256,4,width)||!number(w,257,4,height)||!entry(w,258,3,channels,bits)||!number(w,259,3,1)||!number(w,262,3,34892))return 0;
 const char make[]="Hasselblad",model[]="X2D 100C",unique[]="Hasselblad X2D 100C",software[]="X2D experimental multishot";
 entry(w,271,2,sizeof(make),make);entry(w,272,2,sizeof(model),model);
 number(w,273,4,4096);number(w,274,3,f->orientation);number(w,277,3,channels);number(w,278,4,height);number(w,279,4,width*height*channels*2);number(w,284,3,1);entry(w,305,2,sizeof(software),software);
 const unsigned char version[]={1,4,0,0},back[]={1,1,0,0};
 const char *description=count==4?"X2D multi-shot source frames: 4":"X2D multi-shot source frames: 6";
 entry(w,270,2,(unsigned)strlen(description)+1,description);
 entry(w,50706,1,4,version);entry(w,50707,1,4,back);entry(w,50708,2,sizeof(unique),unique);
 unsigned char black[12],white[12];for(unsigned i=0;i<channels;i++){p32(black+4*i,f->black);p32(white+4*i,f->white);}
 entry(w,50714,4,channels,black);entry(w,50717,4,channels,white);
 const unsigned char *matrix=value(f,tag(f,f->main_ifd,50721),10,9),*wb=value(f,tag(f,f->main_ifd,50728),5,3);
 entry(w,50721,10,9,matrix);entry(w,50728,5,3,wb);number(w,50778,3,f->illuminant);
 /* Copy exposure information to a separate sorted EXIF IFD. */
 number(w,34665,4,768);unsigned exif_n=0;
 for(unsigned k=0;k<3;k++){
  unsigned id=k==0?33434:k==1?33437:34855;const unsigned char *t=tag(f,f->exif_ifd,id);
  unsigned type=u16(t+2),n=u32(t+4),bytes=n*size_type(type);const unsigned char *p=value(f,t,type,n);
  if(!p||bytes>32||w->extra+bytes>4096)return 0;
  unsigned char *o=w->data+770+12*exif_n++;p16(o,id);p16(o+2,type);p32(o+4,n);
  if(bytes<=4)memcpy(o+8,p,bytes);else{p32(o+8,w->extra);memcpy(w->data+w->extra,p,bytes);w->extra=(w->extra+bytes+3)&~3u;}
 }
 p16(w->data+768,exif_n);
 for(unsigned i=0;i<w->n;i++)for(unsigned j=i+1;j<w->n;j++)if(u16(w->data+10+12*i)>u16(w->data+10+12*j)){
  unsigned char t[12];memcpy(t,w->data+10+12*i,12);memcpy(w->data+10+12*i,w->data+10+12*j,12);memcpy(w->data+10+12*j,t,12);
 }
 p16(w->data+8,w->n);return 1;
}
static int input_row(MsFrame *f,unsigned y,uint16_t *row){return !fseek(f->file,HEADER_BYTES+(long)y*RAW_WIDTH*2,SEEK_SET)&&fread(row,2,RAW_WIDTH,f->file)==RAW_WIDTH;}
static int four_row(MsFrame *f,unsigned y,uint16_t (*out)[4],uint16_t *raw){
 static const unsigned cfa[2][2]={{0,1},{3,2}};
 for(unsigned i=0;i<4;i++){
  unsigned sy=y+1-(i&1),sx=i>>1;
  if(!input_row(f+i,sy+92,raw))return 0;
  for(unsigned x=0;x<MS_WIDTH;x++)out[x][cfa[sy&1][(sx+x)&1]]=raw[124+sx+x];
 }
 return 1;
}
static int half_row(MsFrame *f,unsigned y,uint16_t (*out)[3],uint8_t *valid,uint16_t *raw){
 static const unsigned cfa[2][2]={{0,1},{1,2}};memset(valid,0,MS_WIDTH);memset(out,0,MS_WIDTH*6);
 for(unsigned i=4;i<6;i++){
  unsigned sy=y+(i==4);if(!input_row(f+i,sy+92,raw))return 0;
  for(unsigned x=0;x<MS_WIDTH;x++){unsigned c=cfa[sy&1][(x+1)&1];if(valid[x]&(1u<<c))return 0;out[x][c]=raw[125+x];valid[x]|=1u<<c;}
 }
 for(unsigned x=0;x<MS_WIDTH;x++)if(valid[x]!=3&&valid[x]!=6)return 0;
 return 1;
}
/* Generate two high-grid GRBG rows without writing a 400 MP intermediate. */
static int six_pair(MsFrame *f,unsigned y,uint16_t (*planes[2])[4],
                    uint16_t (*halves[2])[3],uint8_t *valid[2],
                    uint16_t *raw,uint16_t *pair){
 uint16_t (*a)[4]=planes[y%2],(*b)[4]=planes[(y+1)%2];
 if(y+1<MS_HEIGHT){if(!four_row(f,y+1,b,raw))return 0;}else memcpy(b,a,MS_WIDTH*8);
 unsigned cur=y%2,prev=y?1-cur:cur;
 if(!half_row(f,y,halves[cur],valid[cur],raw))return 0;
 SixNativeRow task={MS_WIDTH,(const uint16_t(*)[4])a,(const uint16_t(*)[4])b,
  (const uint16_t(*)[3])halves[cur],(const uint16_t(*)[3])halves[prev],
  valid[cur],valid[prev],pair};
 six_native_range(0,MS_WIDTH,&task);return 1;
}
static unsigned reflected_x(int x){return (unsigned)(x<0?-x:x>=(int)(2*MS_WIDTH)?4*(int)MS_WIDTH-2-x:x);}
static double high_sample(const uint16_t *row,int x){return row[reflected_x(x)];}
static void high_rgb(const uint16_t *up,const uint16_t *row,const uint16_t *down,
                     unsigned y,int x,double rgb[3]){
 double value=high_sample(row,x);
 if((y&1)==((unsigned)x&1)){
  rgb[1]=value;
  rgb[y&1?2:0]=(high_sample(row,x-1)+high_sample(row,x+1))*.5;
  rgb[y&1?0:2]=(high_sample(up,x)+high_sample(down,x))*.5;
 }else{
  rgb[y&1?2:0]=value;
  rgb[1]=(high_sample(row,x-1)+high_sample(row,x+1)+high_sample(up,x)+high_sample(down,x))*.25;
  rgb[y&1?0:2]=(high_sample(up,x-1)+high_sample(up,x+1)+high_sample(down,x-1)+high_sample(down,x+1))*.25;
 }
}
static void reduce_six(const uint16_t *previous,const uint16_t *current,
                       const uint16_t *next,unsigned y,uint16_t *rgb){
 const uint16_t *top=current,*bottom=current+2*MS_WIDTH;
 for(unsigned x=0;x<MS_WIDTH;x++){
  double sum[3]={0,0,0},sample[3];
  for(unsigned dx=0;dx<2;dx++){
   high_rgb(previous,top,bottom,2*y,(int)(2*x+dx),sample);
   for(unsigned c=0;c<3;c++)sum[c]+=sample[c];
   high_rgb(top,bottom,next,2*y+1,(int)(2*x+dx),sample);
   for(unsigned c=0;c<3;c++)sum[c]+=sample[c];
  }
  for(unsigned c=0;c<3;c++)rgb[3*x+c]=(uint16_t)floor(sum[c]*.25+.5);
 }
}
int ms_merge(const char *const *inputs,unsigned frames,const char *output,MsProgress progress,void *context,MsResult *result){
 memset(result,0,sizeof(*result));if(frames!=4&&frames!=6)return err(result->error,"expected four or six frames");
 MsFrame *f=calloc(frames,sizeof(*f));FILE *out=NULL;int ok=0;void *allocation=NULL;if(!f)return err(result->error,"out of memory");
 for(unsigned i=0;i<frames;i++){
  if(!ms_probe(inputs[i],f+i,result->error))goto done;
  if(f[i].count!=frames||f[i].index!=i){err(result->error,"frame count or order mismatch");goto done;}
  if(i){
   for(unsigned j=0;j<i;j++)if(!strcmp(inputs[i],inputs[j])||
       (f[i].source_stat.st_dev==f[j].source_stat.st_dev&&f[i].source_stat.st_ino==f[j].source_stat.st_ino)){
    err(result->error,"duplicate source");goto done;
   }
   const char *mismatch=NULL;
   if(f[i].black!=f[0].black)mismatch="black level";
   else if(f[i].white!=f[0].white)mismatch="white level";
   else if(f[i].illuminant!=f[0].illuminant)mismatch="calibration illuminant";
   /* MakerNote's remaining two values have no confirmed session-ID meaning.
    * Group ownership comes from the worker's new-file baseline and ordering. */
   else if(!same_tag(f,f[0].main_ifd,f+i,f[i].main_ifd,50721))mismatch="color matrix";
   /* AsShotNeutral is a rendering preference, not baked into sensor samples.
    * Auto WB can drift within one burst. Preserve frame zero in the DNG. */
   else if(!same_tag(f,f[0].exif_ifd,f+i,f[i].exif_ifd,33434))mismatch="exposure time";
   else if(!same_tag(f,f[0].exif_ifd,f+i,f[i].exif_ifd,33437))mismatch="aperture";
   else if(!same_tag(f,f[0].exif_ifd,f+i,f[i].exif_ifd,34855))mismatch="ISO";
   if(mismatch){snprintf(result->error,160,"Frame %u %s mismatch; source RAWs retained",i+1,mismatch);goto done;}
  }
 }
 if(progress&&progress(context,0,MS_HEIGHT)){err(result->error,"cancelled");goto done;}
 /* Below 1 MiB for full geometry, independent of image height. */
 size_t bytes=MS_WIDTH*56+RAW_WIDTH*2;allocation=calloc(1,bytes);if(!allocation){err(result->error,"out of memory");goto done;}
 unsigned char *p=allocation;uint16_t (*planes[2])[4];uint16_t (*halves[2])[3];uint8_t *valid[2];
 for(unsigned i=0;i<2;i++){planes[i]=(void *)p;p+=MS_WIDTH*8;halves[i]=(void *)p;p+=MS_WIDTH*6;}
 uint16_t *rows=(void *)p;p+=MS_WIDTH*6;uint16_t *raw=(void *)p;p+=RAW_WIDTH*2;
 for(unsigned i=0;i<2;i++){valid[i]=p;p+=MS_WIDTH;}
 uint16_t *pairs[2],*previous;
 for(unsigned i=0;i<2;i++){pairs[i]=(void *)p;p+=MS_WIDTH*8;}
 previous=(void *)p;
 unsigned width=MS_WIDTH,height=MS_HEIGHT,channels=3;
 Writer w;if(!header(&w,f,frames,width,height)){err(result->error,"output metadata invalid");goto done;}
 int fd=open(output,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0){err(result->error,"output exists or is not writable");goto done;}
 out=fdopen(fd,"wb");if(!out){close(fd);err(result->error,"output stream failed");goto done;}
 if(fwrite(w.data,1,4096,out)!=4096)goto write_error;
 if(!four_row(f,0,planes[0],raw))goto read_error;
 if(frames==6){
  if(!six_pair(f,0,planes,halves,valid,raw,pairs[0]))goto read_error;
  memcpy(previous,pairs[0]+2*MS_WIDTH,MS_WIDTH*4);
 }
 for(unsigned y=0;y<MS_HEIGHT;y++){
  if(progress&&progress(context,y,MS_HEIGHT)){err(result->error,"cancelled; source RAWs preserved");goto done;}
  uint16_t (*a)[4]=planes[y%2],(*b)[4]=planes[(y+1)%2];
  if(frames==4){
   for(unsigned x=0;x<MS_WIDTH;x++){rows[3*x]=a[x][0];rows[3*x+1]=((unsigned)a[x][1]+a[x][3]+1)/2;rows[3*x+2]=a[x][2];}
   if(fwrite(rows,2,MS_WIDTH*3,out)!=MS_WIDTH*3)goto write_error;
   if(y+1<MS_HEIGHT&&!four_row(f,y+1,b,raw))goto read_error;
  }else{
   uint16_t *pair=pairs[y%2],*next=pairs[(y+1)%2];
   if(y+1<MS_HEIGHT){if(!six_pair(f,y+1,planes,halves,valid,raw,next))goto read_error;}else next=pair;
   reduce_six(previous,pair,next,y,rows);
   if(fwrite(rows,2,MS_WIDTH*3,out)!=MS_WIDTH*3)goto write_error;
   memcpy(previous,pair+2*MS_WIDTH,MS_WIDTH*4);
  }
 }
 for(unsigned i=0;i<frames;i++){
  if(!ms_source_unchanged(f+i)){err(result->error,"source changed during merge; RAWs retained");goto done;}
 }
 if(fflush(out)||fsync(fileno(out)))goto write_error;
 if(fclose(out)){out=NULL;goto write_error;}out=NULL;
 result->width=width;result->height=height;result->channels=channels;result->frames=frames;result->bytes_written=4096+(uint64_t)width*height*channels*2;
 if(progress)progress(context,MS_HEIGHT,MS_HEIGHT);ok=1;goto done;
read_error:err(result->error,"source changed or became unreadable");goto done;
write_error:err(result->error,"output write or sync failed; source RAWs preserved");
done:if(out)fclose(out);if(f){for(unsigned i=0;i<frames;i++)ms_close(f+i);free(f);}free(allocation);return ok;
}

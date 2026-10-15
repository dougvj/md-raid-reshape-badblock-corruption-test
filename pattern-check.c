#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
static void fill(unsigned char *p, uint64_t sector) {
 uint64_t x=sector+0x9e3779b97f4a7c15ULL;
 for(int i=0;i<512;i++){x^=x>>12;x^=x<<25;x^=x>>27;p[i]=(x*2685821657736338717ULL)>>56;}
}
int main(int argc,char **argv){
 FILE *cmdline=fopen("/proc/cmdline","r");char bootargs[8192]={0};
 if(!cmdline||!fgets(bootargs,sizeof(bootargs),cmdline)||!strstr(bootargs,"disposable_md_repro=1")){fprintf(stderr,"Guest fixture flag missing\n");return 99;}
 fclose(cmdline);
 if(argc!=4)return 2;
 uint64_t sectors=strtoull(argv[3],0,10), errors=0,bad=0,checked=0,good_before_bad=0;
 unsigned char *buf,*expected; if(posix_memalign((void**)&buf,4096,65536)||posix_memalign((void**)&expected,4096,65536))return 3;
 int write_mode=!strcmp(argv[1],"write");
 int fd=open(argv[2],(write_mode?O_WRONLY:O_RDONLY)|O_DIRECT);if(fd<0){perror("open");return 4;}
 int mapfd=-1;unsigned char *map=NULL;
 if(!write_mode){map=calloc(sectors,1);mapfd=open("pre-readable.map",!strcmp(argv[1],"pre")?O_CREAT|O_TRUNC|O_WRONLY:O_RDONLY,0600);if(mapfd<0)return 5;if(strcmp(argv[1],"pre")&&read(mapfd,map,sectors)!=(ssize_t)sectors)return 6;}
 for(uint64_t s=0;s<sectors;){
  size_t n=sectors-s<128?sectors-s:128;
  for(size_t j=0;j<n;j++)fill(expected+j*512,s+j);
  if(write_mode){if(pwrite(fd,expected,n*512,s*512)!=(ssize_t)(n*512)){perror("write");return 7;}}
  else {
   ssize_t rc=pread(fd,buf,n*512,s*512);
   for(size_t j=0;j<n;j++){
    ssize_t one=rc==(ssize_t)(n*512)?512:pread(fd,buf+j*512,512,(s+j)*512);
    if(one!=512){errors++;continue;}
    checked++;
    if(!strcmp(argv[1],"pre"))map[s+j]=1;
    if(memcmp(buf+j*512,expected+j*512,512)){
     bad++;if(map[s+j])good_before_bad++;
     if(bad<=20)printf("READABLE_MISMATCH phase=%s sector=%llu pre_readable=%d\n",argv[1],(unsigned long long)(s+j),map[s+j]);
    }
   }
  }
  s+=n;
 }
 if(write_mode)fsync(fd);
 if(!write_mode&&!strcmp(argv[1],"pre")&&write(mapfd,map,sectors)!=(ssize_t)sectors)return 8;
 printf("VERIFY phase=%s checked=%llu eio=%llu readable_mismatch=%llu previously_readable_mismatch=%llu\n",argv[1],(unsigned long long)checked,(unsigned long long)errors,(unsigned long long)bad,(unsigned long long)good_before_bad);
 return bad ? 10 : 0;
}

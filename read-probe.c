#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <signal.h>
static void fill(unsigned char *p, uint64_t sector) {
 uint64_t x=sector+0x9e3779b97f4a7c15ULL;
 for(int i=0;i<512;i++){x^=x>>12;x^=x<<25;x^=x>>27;p[i]=(x*2685821657736338717ULL)>>56;}
}
int main(int argc,char **argv){
 FILE *cmdline=fopen("/proc/cmdline","r");char bootargs[8192]={0};
 if(!cmdline||!fgets(bootargs,sizeof(bootargs),cmdline)||!strstr(bootargs,"disposable_md_repro=1")){fprintf(stderr,"Guest fixture flag missing\n");return 99;}
 fclose(cmdline);
 if(argc!=3)return 2;
 size_t sectors=strtoull(argv[2],0,10);
 unsigned char *pre=calloc(sectors,1);
 int m=open("pre-readable.map",O_RDONLY);
 if(m<0||read(m,pre,sectors)!=(ssize_t)sectors)return 3;
 close(m);
 volatile unsigned char *state=mmap(NULL,sectors,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0);
 if(state==MAP_FAILED)return 4;
 pid_t workers[64];
 for(int w=0;w<64;w++){
  workers[w]=fork();
  if(workers[w]<0)return 5;
  if(!workers[w]){
   unsigned char *buf,*expected;
   if(posix_memalign((void**)&buf,4096,4096)||posix_memalign((void**)&expected,4096,4096))_exit(6);
   int fd=open(argv[1],O_RDONLY|O_DIRECT);if(fd<0)_exit(7);
   size_t span=((sectors+63)/64+7)/8*8;
   size_t limit=(w+1)*span<sectors?(w+1)*span:sectors;
   for(size_t s=w*span;s<limit;s+=8){
    size_t n=sectors-s<8?sectors-s:8;
    for(size_t j=0;j<n;j++){state[s+j]=4;fill(expected+j*512,s+j);}
    ssize_t rc=pread(fd,buf,n*512,s*512);
    for(size_t j=0;j<n;j++){
     ssize_t one=rc==(ssize_t)(n*512)?512:pread(fd,buf+j*512,512,(s+j)*512);
     state[s+j]=one!=512?2:memcmp(buf+j*512,expected+j*512,512)?3:1;
     if(state[s+j]==3){
      char line[1200];
      int used=snprintf(line,sizeof(line),"SECTOR_BYTES logical=%zu hex=",s+j);
      for(int k=0;k<512;k++)used+=snprintf(line+used,sizeof(line)-used,"%02x",buf[j*512+k]);
      line[used++]='\n';
      if(write(STDOUT_FILENO,line,used)!=used)_exit(8);
     }
    }
   }
   _exit(0);
  }
 }
 for(int t=0;t<20;t++){
  sleep(1);int alive=0;
  for(int w=0;w<64;w++)if(workers[w]>0){int st;pid_t p=waitpid(workers[w],&st,WNOHANG);if(p==workers[w]){if(st)printf("WORKER_ERROR=%d\n",st);workers[w]=0;}else alive++;}
  if(!alive)break;
 }
 unsigned long counts[5]={0},was_good=0,shown=0;
 for(size_t s=0;s<sectors;s++){
  unsigned char st=state[s];counts[st]++;
  if(st==3){if(pre[s])was_good++;if(shown++<30)printf("READ_MISMATCH sector=%zu pre_readable=%d\n",s,pre[s]);}
 }
 printf("READ_SUMMARY correct=%lu read_error=%lu wrong=%lu previously_correct_now_wrong=%lu in_flight=%lu untested=%lu\n",counts[1],counts[2],counts[3],was_good,counts[4],counts[0]);
 fflush(stdout);
 for(int w=0;w<64;w++)if(workers[w]>0)kill(workers[w],SIGKILL);
 return 0;
}

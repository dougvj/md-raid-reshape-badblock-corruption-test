#include <sys/reboot.h>
int main(void) { return reboot(RB_POWER_OFF); }

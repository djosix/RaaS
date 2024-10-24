#!/usr/bin/env python3

import sys
import glob
import os
import socket
import threading
import datetime
import subprocess
import signal
import argparse
import termios
import tty
import shlex
import re


def main():
    parser = argparse.ArgumentParser(description='Remote session management tool')
    parser.add_argument('-d', '--work-dir', default=os.path.expanduser('~/.rsm'), help='Working directory')

    subparsers = parser.add_subparsers(dest='command', required=True)

    # tmux command
    parser_tmux = subparsers.add_parser('tmux', help='Start or attach to tmux session')
    parser_tmux.add_argument('-t', '--tty', action='store_true', help='Use TTY mode')
    parser_tmux.add_argument('port', type=int, help='Port number')
    parser_tmux.add_argument('-D', '--detached', action='store_true', help='Start in detached mode (do not attach)')

    # list command
    parser_list = subparsers.add_parser('list', help='List all open ports')

    # kill command
    parser_kill = subparsers.add_parser('kill', help='Kill tmux session by port or all sessions')
    parser_kill.add_argument('port', type=int, nargs='?', help='Port number to kill')

    # serve command (internal use only)
    parser_serve = subparsers.add_parser('serve', help='Start server (internal use only)')
    parser_serve.add_argument('-t', '--tty', action='store_true', help='Use TTY mode')
    parser_serve.add_argument('port', type=int, help='Port number')
    parser_serve.add_argument('session_name', help='Tmux session name')

    # interact command (internal use only)
    parser_interact = subparsers.add_parser('interact', help='Interact with socket (internal use only)')
    parser_interact.add_argument('-t', '--tty', action='store_true', help='Use TTY mode')
    parser_interact.add_argument('socket_path', help='Unix domain socket path')

    args = parser.parse_args()

    global work_dir
    work_dir = os.path.abspath(args.work_dir)

    # Ensure the working directory exists (mkdir -p effect)
    if not os.path.exists(work_dir):
        os.makedirs(work_dir, exist_ok=True)

    if args.command == 'tmux':
        tmux_command(args)
    elif args.command == 'list':
        list_command()
    elif args.command == 'kill':
        kill_command(args)
    elif args.command == 'serve':
        serve_command(args)
    elif args.command == 'interact':
        interact_command(args)
    else:
        print("Unknown command:", args.command)
        sys.exit(1)


def tmux_command(args):
    port = args.port
    session_name = f"rsm/{port}"
    use_tty = args.tty
    detached_mode = args.detached

    tmux_socket = os.path.join(work_dir, 'tmux.sock')

    # Check if the session already exists
    result = subprocess.run(
        ['tmux', '-S', tmux_socket, 'has-session', '-t', session_name],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        # Session exists, directly attach unless detached mode is requested
        if not detached_mode:
            subprocess.run(['tmux', '-S', tmux_socket, 'attach-session', '-t', session_name])
        return

    # Start a new tmux session with the given name and socket
    subprocess.run(['tmux', '-S', tmux_socket, 'new-session', '-d', '-s', session_name])

    # Rename the first window to 'server'
    subprocess.run(['tmux', '-S', tmux_socket, 'rename-window', '-t', '0', 'server'])

    # Construct the command to run
    serve_cmd = [sys.executable, os.path.abspath(__file__), '-d', work_dir]
    serve_cmd.extend(['serve', str(port), session_name])
    if use_tty:
        serve_cmd.append('-t')
    serve_cmd_str = ' '.join(shlex.quote(arg) for arg in serve_cmd)

    command = f"clear; {serve_cmd_str}; exit"

    # Send the command to the first window
    subprocess.run(['tmux', '-S', tmux_socket, 'send-keys', '-t', f'{session_name}:0', command, 'Enter'])

    # Attach to the tmux session if not in detached mode
    if not detached_mode:
        subprocess.run(['tmux', '-S', tmux_socket, 'attach-session', '-t', session_name])


def list_command():
    tmux_socket = os.path.join(work_dir, 'tmux.sock')

    # List all tmux sessions and filter for those with "rsm/<port>" format
    result = subprocess.run(['tmux', '-S', tmux_socket, 'list-sessions'], capture_output=True, text=True)
    sessions = result.stdout.splitlines()
    open_ports = []

    for session in sessions:
        match = re.match(r"rsm/(\d+)", session)
        if match:
            port = match.group(1)
            open_ports.append(port)

    if open_ports:
        print("Open ports:", ', '.join(open_ports))
        for port in open_ports:
            for info_path in glob.glob(os.path.join(work_dir, f"client_{port}_*.txt")):
                print(port, open(info_path).read())
    else:
        print("No open ports found.")


def kill_command(args):
    tmux_socket = os.path.join(work_dir, 'tmux.sock')
    port = args.port

    if port:
        # Kill specific session by port
        session_name = f"rsm/{port}"
        result = subprocess.run(
            ['tmux', '-S', tmux_socket, 'kill-session', '-t', session_name],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"Session for port {port} killed.")
        else:
            print(f"No session found for port {port}.")
    else:
        # Kill all sessions matching "rsm/<port>" format
        result = subprocess.run(
            ['tmux', '-S', tmux_socket, 'list-sessions'],
            capture_output=True,
            text=True,
        )
        sessions = result.stdout.splitlines()

        for session in sessions:
            match = re.match(r"rsm/(\d+)", session)
            if match:
                session_name = match.group(0)
                subprocess.run(['tmux', '-S', tmux_socket, 'kill-session', '-t', session_name])
                print(f"Killed session: {session_name}")


def serve_command(args):
    port = args.port
    session_name = args.session_name
    use_tty = args.tty

    tmux_socket = os.path.join(work_dir, 'tmux.sock')

    # Start a TCP server
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(
        socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Enable port reuse
    server_socket.bind(('', port))
    server_socket.listen()

    connection_count = 0

    print(f"Server listening on port {port}")

    try:
        while True:
            client_socket, client_address = server_socket.accept()
            print(f"Accepted connection from {client_address}")

            connection_count += 1
            base_name = f"client_{port:05d}_{connection_count%1000000:06d}"
            window_name = f"{client_address[0]}/{connection_count%100:02d}"

            # Create Unix Domain Socket
            socket_path = os.path.join(work_dir, f"{base_name}.sock")
            info_path = os.path.join(work_dir, f"{base_name}.txt")

            # Create a Unix domain socket listener
            uds_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            uds_server.bind(socket_path)
            uds_server.listen(1)

            # Construct the command to run
            interact_cmd = [sys.executable, os.path.abspath(__file__), '-d', work_dir]
            interact_cmd.extend(['interact', socket_path])
            if use_tty:
                interact_cmd.append('-t')

            # Info line to show in the new tmux window
            info_line = str(datetime.datetime.now()).split('.')[0] + " " + ":".join(map(str, client_address))

            script = ";".join((
                f"echo {shlex.quote(info_line)} | tee -a {shlex.quote(info_path)}",
                " ".join(shlex.quote(arg) for arg in interact_cmd),
                f"rm -rf {shlex.quote(socket_path)} {shlex.quote(info_path)}",
            ))

            # Open a new tmux window in the given session, running 'interact <socket path>'
            subprocess.run(['tmux', '-S', tmux_socket, 'new-window', '-t', session_name, '-n', window_name, script])

            # Accept connection from interact process
            uds_client, _ = uds_server.accept()

            # Start threads to bridge TCP socket and Unix domain socket
            threading.Thread(target=socket_bridge, args=(client_socket, uds_client), daemon=True).start()

            # Close the server side of Unix domain socket
            uds_server.close()

    except KeyboardInterrupt:
        print("Server shutting down...")
    finally:
        server_socket.close()


def socket_bridge(client_socket, uds_client):
    try:
        # Start threads to forward data between sockets
        threading.Thread(target=forward_data, args=(
            client_socket, uds_client), daemon=True).start()
        threading.Thread(target=forward_data, args=(
            uds_client, client_socket), daemon=True).start()
    except Exception as e:
        print(f"socket_bridge exception: {e}")
    finally:
        pass  # Sockets will be closed by the threads


def forward_data(source_socket, destination_socket):
    try:
        while True:
            data = source_socket.recv(4096)
            if not data:
                break
            destination_socket.sendall(data)
    except Exception as e:
        pass
    finally:
        source_socket.close()
        destination_socket.close()


def interact_command(args):
    socket_path = args.socket_path
    use_tty = args.tty

    # Handle Ctrl+C signal
    def signal_handler(sig, frame):
        print("interact: Caught SIGINT, exiting...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Connect to the Unix domain socket
    try:
        uds = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        uds.connect(socket_path)
    except Exception as e:
        print(f"Failed to connect to Unix domain socket: {e}")
        return

    # Remove the socket file after connecting
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    try:
        if use_tty:
            # Use TTY mode
            tty_name = os.ttyname(sys.stdin.fileno())
            tty_fd = os.open(tty_name, os.O_RDWR | os.O_NOCTTY)
            old_tty_attrs = termios.tcgetattr(tty_fd)
            try:
                tty.setraw(tty_fd)
                new_tty_attrs = termios.tcgetattr(tty_fd)
                new_tty_attrs[3] = new_tty_attrs[3] & ~(termios.ECHO | termios.ICANON)
                termios.tcsetattr(tty_fd, termios.TCSANOW, new_tty_attrs)

                t1 = threading.Thread(target=tty_to_socket, args=(tty_fd, uds))
                t2 = threading.Thread(target=socket_to_tty, args=(uds, tty_fd))
                t1.start()
                t2.start()
                t1.join()
                t2.join()
            finally:
                termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_tty_attrs)
                os.close(tty_fd)
        else:
            # Use standard mode
            t1 = threading.Thread(target=socket_to_stdout, args=(uds,))
            t2 = threading.Thread(target=stdin_to_socket, args=(uds,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
    except KeyboardInterrupt:
        print("interact: KeyboardInterrupt caught, exiting...")
    finally:
        uds.close()


def socket_to_stdout(uds):
    try:
        while True:
            data = uds.recv(4096)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.flush()
    except Exception as e:
        pass
    finally:
        uds.close()


def stdin_to_socket(uds):
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)  # Use cbreak mode to allow Ctrl+C
        while True:
            data = os.read(fd, 1024)
            if not data:
                break
            uds.sendall(data)
            # Echo the input back to the terminal
            sys.stdout.buffer.write(data)
            sys.stdout.flush()
    except Exception as e:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        uds.close()


def tty_to_socket(tty_fd, uds):
    try:
        while True:
            data = os.read(tty_fd, 1024)
            if not data:
                break
            uds.sendall(data)
    except Exception as e:
        pass
    finally:
        uds.close()


def socket_to_tty(uds, tty_fd):
    try:
        while True:
            data = uds.recv(4096)
            if not data:
                break
            os.write(tty_fd, data)
    except Exception as e:
        pass
    finally:
        uds.close()


if __name__ == '__main__':
    main()

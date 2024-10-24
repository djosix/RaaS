# RaaS

Self-hosted reverse shell as a service.

<img width="843" alt="Screenshot 2024-10-25 at 04 57 59" src="https://github.com/user-attachments/assets/4dbc4fc9-0610-4b2d-954c-7aa3a9281972">

## Setup

Compile the reverse shell:

```bash
# Bad idea
gcc -o reverse reverse.c

# Good idea
gcc -static -O3 -o reverse reverse.c

# Complex idea
gcc -static -O3 -s -fno-stack-protector -fomit-frame-pointer -mpreferred-stack-boundary=2 -z norelro -fno-exceptions -fno-asynchronous-unwind-tables -o reverse reverse.c
strip -s reverse
upx --best --ultra-brute reverse
```

Host this directory with a web server:

```bash
python3 -m http.server
```

## Usage

1. Open `index.html` in a browser
2. Run the command from the "Wait For Reverse Shell" section on your host
3. Run the command from the "Launch Reverse Shell" section on the target machine
4. Enjoy your TTY shell

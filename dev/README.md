# Development environment

A Frappe v16 + ERPNext v16 bench in Docker, for building and testing the `ai_munimji` app. It is Frappe's official dev-container example
(`frappe_docker`, `devcontainer-example`), run from the command line with two changes for Windows (see the comments in `compose.yml`).
It is its own compose project, `munimji-dev`; it does not touch other Docker projects.

You need Docker Desktop (about 6 GB for its virtual machine; 8 recommended) and about 10 GB of free disk. Nothing else is installed on Windows.

## The commands you run

From `C:\ERP\AI-Munimji` in PowerShell:

```
.\dev\up.ps1        # pull the images (about 0.9 GB the first time) and start 4 containers, 2 volumes, 1 network
```

Then, once (about 45 to 70 minutes the first time, mostly downloads and the asset build):

```
.\dev\exec.ps1 bash /workspace/ai_munimji/dev/bootstrap.sh
```

Every step's duration is appended to `dev/timings.log`.

Day to day:

```
.\dev\shell.ps1                       # a shell in the bench directory inside the container
.\dev\exec.ps1 bench start            # web on http://development.localhost:8000 (Administrator / admin), realtime on 9000
.\dev\down.ps1                        # stop the containers, keep the data
.\dev\destroy.ps1                     # remove containers, network and the two volumes of this project (asks first)
```

`development.localhost` resolves to your own machine in current browsers; no hosts-file change is needed. The ports are published on 127.0.0.1 only.

## What is in it

| | |
|---|---|
| `compose.yml` | MariaDB 11.8, two Redis, and the `frappe/bench` image (Python 3.14, Node 24, bench 5.x), pinned by digest |
| `up.ps1`, `down.ps1`, `destroy.ps1`, `shell.ps1`, `exec.ps1` | the commands above |
| `lib.sh`, `bootstrap.sh` | run inside the container; `bootstrap.sh` builds the bench and installs ERPNext and, once it exists, this app |
| `images.lock` | the image digests that were really used (written by `up.ps1`) |
| `timings.log` | how long each step took (not in git) |

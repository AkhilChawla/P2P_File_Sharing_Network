## P2P File Sharing with Central Index

Centralized index server plus peer client/upload server for the CSC/ECE 573 P2P project. Run everything locally to simulate multiple peers exchanging RFC files.

### What's here

- Central index server (`server/server.py`) that tracks which peers host which RFCs.
- Peer upload server that serves RFC content over TCP (`GET RFC <num>`).
- Peer client that talks to the index (ADD, LOOKUP, LIST) and manages local storage.
- Shared protocol helpers (`shared/protocol.py`) so both sides format messages consistently.
- Sample RFCs and separate stores for running a few peers on one machine.

### Layout

```
shared/protocol.py      # Message formatting/parsing helpers (P2S + P2P)
peer/config.py          # Runtime configuration dataclass
peer/logging_utils.py   # Stdout logger setup
peer/storage.py         # RFC file I/O helpers
peer/upload_server.py   # Threaded GET RFC upload server
peer/client.py          # Central-server client + PeerNode orchestration
peer/cli.py             # Interactive shell entry point
sample_rfc/             # Example RFC files for seeding peers
peer1_store/, peer2_store/, peer3_store/  # Example local stores for peers
server/server.py        # Centralized index server
```

### Quick start (Makefile)

Requires Python 3.9+.

```
# Terminal 1: start the central server
make server

# Terminal 2: launch peer on port 6001 using the provided store
make peer1 SERVER_HOST=127.0.0.1 SERVER_PORT=7734

# Terminal 3: launch a second peer on port 6002
make peer2 SERVER_HOST=127.0.0.1 SERVER_PORT=7734
```

`make peer` starts the shell with your own `PEER_PORT`/`RFC_STORE` values. Run `make help` to see all targets and defaults.

### End-to-end test guide (all flows)

Open separate terminals.

1) Start the central index
```
make server SERVER_HOST=127.0.0.1 SERVER_PORT=7734
```

2) Launch peer #1 (uploads + client shell)
```
make peer1 SERVER_HOST=127.0.0.1 SERVER_PORT=7734
```
At `peer>` check registration:
```
list          # should show RFC 1/2 on localhost:6001
```

3) Launch peer #2
```
make peer2 SERVER_HOST=127.0.0.1 SERVER_PORT=7734
```
Check index visibility:
```
list
lookup 1
```

4) Add a new RFC from peer1
```
add 42 sample_rfc/rfc_1.txt "Test RFC 42"
list          # RFC 42 now at localhost:6001
```

5) Download from peer2 (peer-to-peer GET)
```
lookup 42
get 42 localhost 6001
list          # RFC 42 listed for both peers
```

6) Optional: trigger a version mismatch (expect 505) against a peer upload server
```
printf 'GET RFC 1 P2P-CI/2.0\r\nHost: localhost\r\nOS: test\r\n\r\n' \
  | nc localhost 6001
```

7) Optional: trigger a 400 Bad Request (missing OS header) against a peer upload server
```
printf 'GET RFC 1 P2P-CI/1.0\r\nHost: localhost\r\n\r\n' | nc localhost 6001
```

### Manual run (without Makefile)

Start server:
```
python -m server.server --host 0.0.0.0 --port 7734
```

Start a peer shell (new terminal):
```
python -m peer.cli --server-host 127.0.0.1 --server-port 7734 --peer-port 6001 --rfc-store ./peer1_store
```

### Shell commands (at the `peer>` prompt)

| Command | Description |
| --- | --- |
| `help` | Show command summary. |
| `sync` | Register all local RFCs with the central server (also runs on startup). |
| `seed [dir]` | Copy sample RFCs from `sample_rfc/` (or a custom dir) into the local store and register them. |
| `list` | Run `LIST ALL` against the central server and print the raw response. |
| `lookup <rfc>` | Execute `LOOKUP RFC <num>` and print the raw response. |
| `add <rfc> <path> "Title"` | Copy a file into the local store, register it with the server, and print the raw `ADD` response. |
| `get <rfc>` | Find peers via the central server, download the RFC via P2P `GET`, store it locally, and re-register it. |
| `exit` | Quit the shell (upload server thread stops automatically on process exit). |

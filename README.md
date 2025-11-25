## P2P File Sharing with Central Index

We built this for CSC/ECE 573 Project #1. The repository includes both parts we needed: a centralized index server and a peer client with an upload server. You can run everything locally and use the CLI shell to simulate multiple peers trading RFC files.

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

### Running the peer shell

```
python -m peer.cli \
  --server-host <central-server-host> \
  --server-port 7734 \
  --peer-host $(hostname) \
  --peer-port 6000
```

The CLI starts the upload server and scans the chosen RFC directory on startup, automatically registering any files it finds with the central server. Point each peer at its own store to keep downloads separated.

#### Example workflow

Terminal 1 - start the central server:

```
python3 -m server.server
```

Terminal 2 - launch peer #1 on port 6001 with its own store:

```
python3 -m peer.cli --server-host 127.0.0.1 --server-port 7734 --peer-port 6001 --rfc-store ./peer1_store
```

Terminal 3 - launch peer #2 on port 6002 with a separate store:

```
python3 -m peer.cli --server-host 127.0.0.1 --server-port 7734 --peer-port 6002 --rfc-store ./peer2_store
```

Drop RFC files into a peer's store before launching and they'll be registered automatically. You can still add more after startup:

```
add 1 peer1_store/rfc_1.txt "My First RFC"
add 2 peer1_store/rfc_2.txt "My Second RFC"
```

On any peer, the `list` and `lookup` commands print the raw responses from the server:

```
list                 # prints the raw LIST response from the server
lookup 1             # prints the raw LOOKUP response for RFC 1
get 1 localhost 6001 # downloads RFC 1 from the peer on port 6001
```

#### Offline testing mode

If you want to try the peer logic without the central server running:

```
python -m peer.cli --offline --offline-index /tmp/p2p_index.json --peer-port 6001
```

ADD/LIST/LOOKUP read and write that JSON file so multiple peers on the same machine can coordinate without opening sockets.

### Running the central server

```
python -m server.server
```

The server listens on `0.0.0.0:7734`, logs to stdout, and serves the live index used by peers. Start it before launching peers (skip `--offline`) so all requests hit the real implementation.

### Message formats (per the project spec)

- All requests and responses use the `P2P-CI/1.0` version string.
- Peer-to-peer `GET RFC <number>` requests include `Host` (hostname of the peer serving the RFC) and `OS` headers. The upload server replies with status `200`, `400`, `404`, or `505` plus `Date`, `OS`, `Last-Modified`, `Content-Length`, and `Content-Type` headers. For this project `Content-Type` is always `text/plain`. Example:

```
GET RFC 1234 P2P-CI/1.0\r\n
Host: somehost.csc.ncsu.edu\r\n
OS: Mac OS 10.4.1\r\n
\r\n
```

Response:

```
P2P-CI/1.0 200 OK\r\n
Date: Wed, 12 Feb 2009 15:12:05 GMT\r\n
OS: Mac OS 10.2.1\r\n
Last-Modified: Thu, 21 Jan 2001 09:23:46 GMT\r\n
Content-Length: 12345\r\n
Content-Type: text/plain\r\n
\r\n
(contents of the RFC)
```

- Peer-to-server requests (`ADD`, `LOOKUP`, `LIST`) include `Host`, `Port`, and (for `ADD`) `Title`. The client prints raw server responses and handles results like `200 OK`, `400 Bad Request`, `404 Not Found`, and `505 P2P Version Not Supported`. Examples:

ADD RFC:

```
ADD RFC 123 P2P-CI/1.0\r\n
Host: thishost.csc.ncsu.edu\r\n
Port: 5678\r\n
Title: A Proferred Official ICP\r\n
\r\n
P2P-CI/1.0 200 OK\r\n
\r\n
RFC 123 A Proferred Official ICP thishost.csc.ncsu.edu 5678
```

LOOKUP RFC:

```
LOOKUP RFC 3457 P2P-CI/1.0\r\n
Host: thishost.csc.ncsu.edu\r\n
Port: 5678\r\n
Title: Requirements for IPsec Remote Access Scenarios\r\n
\r\n
P2P-CI/1.0 200 OK\r\n
\r\n
RFC 3457 Requirements for IPsec Remote Access Scenarios peerA.example.com 6001\r\n
RFC 3457 Requirements for IPsec Remote Access Scenarios peerB.example.com 6002
```

LIST ALL:

```
LIST ALL P2P-CI/1.0\r\n
Host: thishost.csc.ncsu.edu\r\n
Port: 5678\r\n
\r\n
P2P-CI/1.0 200 OK\r\n
\r\n
RFC 1 First RFC peerA.example.com 6001\r\n
RFC 2 Second RFC peerB.example.com 6002
```

### Shell commands

Once the `peer>` prompt appears, you can run:

| Command | Description |
| --- | --- |
| `help` | Show command summary. |
| `sync` | Register all local RFCs with the central server (also runs on startup). |
| `seed [dir]` | Copy sample RFCs from `sample_rfc/` (or a custom dir) into the local store and register them. |
| `list` | Run `LIST ALL` against the central server and print the raw response. |
| `local` | Show RFC files stored locally. |
| `lookup <rfc>` | Execute `LOOKUP RFC <num>` and print the raw response. |
| `add <rfc> <path> "Title"` | Copy a file into the local store, register it with the server, and print the raw `ADD` response. |
| `get <rfc>` | Find peers via the central server, download the RFC via P2P `GET`, store it locally, and re-register it. |
| `exit` | Quit the shell (upload server thread stops automatically on process exit). |

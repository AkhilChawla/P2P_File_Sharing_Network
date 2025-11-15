## Peer Client & Upload Server (Person B)

This repository contains a Python implementation for the peer-side responsibilities of CSC/ECE 573 Project #1 – P2P System with a Centralized Index. It covers:

- Peer upload server (TCP listener that responds to `GET RFC <num>`).
- Peer client logic that talks to the central server (ADD, LOOKUP, LIST).
- RFC download workflow plus local file storage.
- Shared protocol helpers so Person A’s centralized server can interoperate.
- CLI shell for manual testing with multiple peers.

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
rfc_store/              # Local store where downloaded RFCs are saved
server/server.py        # Centralized index server (Person A component)
```

### Running the peer shell

```
python -m peer.cli \
  --server-host <central-server-host> \
  --server-port 7734 \
  --peer-host $(hostname) \
  --peer-port 6000
```

Command‑line flags let you pick the advertised host, upload port and directories.  When the shell starts it brings up the upload server **and scans the configured `rfc_store/` directory, automatically registering any RFC files found there with the central server**.  This satisfies the requirement that a peer advertise all of its RFCs when it joins the system.

#### Example workflow

Terminal 1 – start the centralized server:

```
python3 -m server.server
```

Terminal 2 – launch peer #1 on port 6001 with its own store:

```
python3 -m peer.cli --server-host 127.0.0.1 --server-port 7734 --peer-port 6001 --rfc-store ./peer1_store
```

Terminal 3 – launch peer #2 on port 6002 with a separate store:

```
python3 -m peer.cli --server-host 127.0.0.1 --server-port 7734 --peer-port 6002 --rfc-store ./peer2_store
```

When you place RFC files into a peer’s `rfc_store` directory before launching the peer, those RFCs are automatically registered with the central server on startup.  You can still register additional RFCs explicitly using the `add` command if you add files after startup.  For example:

```
add 1 peer1_store/rfc_1.txt "My First RFC"
add 2 peer1_store/rfc_2.txt "My Second RFC"
```

On either peer you can interact with the server and request files via the CLI.  The `list` and `lookup` commands print the raw server responses:

```
list                 # prints the raw LIST response from the server
lookup 1             # prints the raw LOOKUP response for RFC 1
get 1 localhost 6001   # downloads RFC 1 from the peer on port 6001
```

#### Offline testing mode

When Person A’s server is unavailable, run:

```
python -m peer.cli --offline --offline-index /tmp/p2p_index.json --peer-port 6001
```

All ADD/LIST/LOOKUP commands now read/write the shared JSON file instead of opening a socket, so multiple peer instances on the same machine can coordinate using that file.

### Running the centralized server

```
python -m server.server
```

By default the server listens on `0.0.0.0:7734`, logs requests to stdout, and serves the live index used by peers. Launch it before starting peers (omit `--offline` in the peer CLI) so ADD/LIST/LOOKUP traffic hits the real implementation.

### Message formats (per the project spec)

- All requests and responses use the `P2P-CI/1.0` version string.
* **Peer‑to‑peer (P2P)** `GET RFC <number>` requests include two headers:
  * `Host` – the hostname of the peer **serving** the RFC.  When peer A requests an RFC from peer B, the `Host` header in A’s request must equal B’s hostname, matching the example in the project specification.
  * `OS` – the operating system of the requesting host.

  A typical GET looks like:

  ```
  GET RFC 1234 P2P‑CI/1.0\r\n
  Host: somehost.csc.ncsu.edu\r\n
  OS: Mac OS 10.4.1\r\n
  \r\n
  ```

  The upload server replies with one of the status codes `200`, `400`, `404` or `505` and with five headers: `Date`, `OS`, `Last‑Modified`, `Content‑Length`, and `Content‑Type`.  For this project the `Content‑Type` is always **`text/plain`**, and the body contains the text of the RFC.  An example response is:

  ```
  P2P‑CI/1.0 200 OK\r\n
  Date: Wed, 12 Feb 2009 15:12:05 GMT\r\n
  OS: Mac OS 10.2.1\r\n
  Last‑Modified: Thu, 21 Jan 2001 09:23:46 GMT\r\n
  Content‑Length: 12345\r\n
  Content‑Type: text/plain\r\n
  \r\n
  (contents of the RFC)
  ```

* **Peer‑to‑server (P2S)** requests (`ADD`, `LOOKUP`, `LIST`) include `Host`, `Port`, and (for `ADD`) `Title` headers identifying the requesting peer and the RFC being advertised or queried.  The client prints the raw server responses exactly as they are received.  For example:

  - **ADD RFC** – registers a new RFC with the server and echoes back the added record:

    ```
    ADD RFC 123 P2P‑CI/1.0\r\n
    Host: thishost.csc.ncsu.edu\r\n
    Port: 5678\r\n
    Title: A Proferred Official ICP\r\n
    \r\n
    P2P‑CI/1.0 200 OK\r\n
    \r\n
    RFC 123 A Proferred Official ICP thishost.csc.ncsu.edu 5678
    ```

  - **LOOKUP RFC** – returns zero or more lines, one for each peer hosting the RFC:

    ```
    LOOKUP RFC 3457 P2P‑CI/1.0\r\n
    Host: thishost.csc.ncsu.edu\r\n
    Port: 5678\r\n
    Title: Requirements for IPsec Remote Access Scenarios\r\n
    \r\n
    P2P‑CI/1.0 200 OK\r\n
    \r\n
    RFC 3457 Requirements for IPsec Remote Access Scenarios peerA.example.com 6001\r\n
    RFC 3457 Requirements for IPsec Remote Access Scenarios peerB.example.com 6002
    ```

  - **LIST ALL** – lists every RFC known to the server:

    ```
    LIST ALL P2P‑CI/1.0\r\n
    Host: thishost.csc.ncsu.edu\r\n
    Port: 5678\r\n
    \r\n
    P2P‑CI/1.0 200 OK\r\n
    \r\n
    RFC 1 First RFC peerA.example.com 6001\r\n
    RFC 2 Second RFC peerB.example.com 6002\r\n
    …
    ```

### Shell commands

Once `peer>` prompt appears, the following commands are supported:

| Command | Description |
| --- | --- |
| `help` | Show command summary. |
| `sync` | Register all local RFCs with the central server (runs on startup too). |
| `seed [dir]` | Copy sample RFCs from `sample_rfc/` (or a custom dir) into the local store and register them. |
| `list` | Run `LIST ALL` against the central server and print the raw server response (status line, blank line and data). |
| `local` | Show RFC files stored locally in `rfc_store/`. |
| `lookup <rfc>` | Execute `LOOKUP RFC <num>` and print the raw `LOOKUP` response returned by the server. |
| `add <rfc> <path> "Title"` | Copy a file into the local store, register it with the server and print the raw `ADD` response. |
| `get <rfc>` | Finds peers via the central server, downloads the RFC via P2P `GET`, stores it locally, and re-registers it. |
| `exit` | Quit the shell (upload server thread stops automatically on process exit). |

### Integration points with Person A

1. **Protocol format** – Both client and upload server use `shared/protocol.py`, so Person A can rely on the same helpers (or the textual format) for parsing P2S and P2P messages. Requests and responses follow the `P2P-CI/1.0` spec (`METHOD resource VERSION`, headers terminated by blank line, CRLF line endings).
2. **Server responses** – The peer expects central server responses such as `200 OK`, `400 Bad Request`, `404 Not Found`, `505 P2P Version Not Supported`, and response bodies containing lines like `RFC <num> <host> <port> <title>`.
3. **Peer upload server** – Runs on the provided `--peer-port` and serves RFC files from `rfc_store/`. Person A’s peers should connect via TCP, send `GET RFC <num> P2P-CI/1.0`, and parse the `Content-Length` header.
4. **Logging** – Everything logs to stdout so combined server/peer traces are easy to follow.

### Future enhancements

- Automated tests with pytest for protocol helpers and CLI routines.
- Persistence for peer registration meta data (currently done at runtime).
- Richer CLI UX (history, autocompletion) and scripted scenarios for multi-peer testing.

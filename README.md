# Secure LAN File Transfer and Monitoring Dashboard

This project is a computer-networks focused LAN transfer system built with Flask, Socket.IO, and Python sockets. It combines a real-time dashboard with a custom file transfer protocol that supports resumable chunk delivery, parallel streams, per-chunk integrity checks, and optional AES-GCM encryption.

## Core Features

- Real-time dashboard for bandwidth, device discovery, alerts, and transfer telemetry
- Custom control-plane handshake for transfer negotiation
- Chunk-based file transfer over TCP data channels
- Parallel multi-socket upload mode and normal sequential mode
- Resume support using receiver-side metadata and partial file state
- Per-chunk SHA-256 checksum validation
- Retransmission when a chunk fails
- Optional compression using `zlib`
- Optional AES-GCM encryption using a pre-shared secret
- Transfer metrics:
  - throughput
  - average RTT
  - retry count
  - estimated chunk-loss percentage
  - wire-to-logical byte ratio

## Architecture

### 1. Control Channel

The sender first connects to the receiver on TCP port `9092`.

The control channel performs:
- transfer initialization
- metadata exchange
- resume negotiation
- final file verification and commit

The sender sends:
- filename
- file size
- full file SHA-256
- chunk size
- total chunk count
- selected mode
- compression and encryption flags

The receiver checks its stored metadata and responds with:
- transfer ID
- list of missing chunks
- whether the file is already complete

### 2. Data Channel

Actual chunk delivery happens on TCP port `9093`.

Each chunk is sent on its own socket connection with:
- transfer ID
- chunk index
- byte offset
- original size
- payload size
- SHA-256 checksum of plaintext chunk
- compression flag
- encryption flag
- AES-GCM nonce when encryption is enabled

The receiver:
- decrypts the payload if needed
- decompresses it if needed
- verifies the chunk checksum
- writes the chunk to the correct offset in a partial file
- updates persistent resume metadata
- sends an acknowledgement containing chunk status and RTT estimate

### 3. Finalization

After all missing chunks are acknowledged, the sender asks the receiver to finalize the transfer over the control channel.

The receiver then:
- verifies that all chunks arrived
- computes the SHA-256 of the reconstructed file
- compares it with the sender-provided file hash
- promotes the partial file to the final received file if verification succeeds

## Resume Logic

Receiver-side metadata is stored in `shared_files/.transfer_meta/`.

For each transfer, the receiver stores:
- file metadata
- chunk size
- total chunk count
- list of received chunk indexes
- partial file contents

If a transfer is interrupted, the next sender handshake receives only the missing chunk list, so already received chunks are not sent again.

## Security Model

Encryption uses AES-GCM from the `cryptography` package.

- The system derives a session key from the pre-shared environment variable `TRANSFER_SECRET`
- Each chunk uses a fresh random nonce
- AES-GCM provides both confidentiality and tamper detection

If `cryptography` is not installed, the application still runs, but encrypted transfers are rejected with a clear error message.

## Dashboard Features

The dashboard includes:
- outgoing and incoming transfer cards
- live progress bars
- mode indicator: normal vs parallel
- retry and RTT statistics
- compression ratio / wire usage metric
- transfer duration and throughput
- historical average comparison between normal and parallel mode

## Requirements

Install dependencies:

```bash
pip install -r requirements.txt
```

For encrypted transfers, make sure `cryptography` installs successfully.

## Running

Start the server:

```bash
python3 run.py
```

Open:

```text
http://localhost:5000
```

Login:

```text
admin / netshield
```

## Recommended Demo

To demonstrate the project:

1. Run the application on two LAN machines.
2. Start one instance on each machine.
3. Transfer the same large file in `normal` mode and note throughput and duration.
4. Transfer it again in `parallel` mode and compare the dashboard averages.
5. Interrupt a transfer midway and restart it to show resume support.
6. Enable compression and encryption to discuss protocol overhead versus security.

## Files of Interest

- `server/file_transfer.py`: custom transfer protocol, resume logic, metrics, encryption, retransmission
- `server/app.py`: API integration and dashboard broadcast payload
- `templates/index.html`: transfer controls and comparison panel
- `static/script.js`: live transfer rendering and form submission
- `static/style.css`: UI layout for the transfer dashboard

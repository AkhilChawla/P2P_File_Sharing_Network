PYTHON ?= python3

SERVER_HOST ?= 127.0.0.1
SERVER_PORT ?= 7734
PEER_HOST ?= localhost
PEER_PORT ?= 6000
RFC_STORE ?= rfc_store
SAMPLE_DIR ?= sample_rfc

.PHONY: help server peer peer1 peer2 peer3

help:
	@echo "P2P File Sharing shortcuts"
	@echo "  make server               Start the central index server (blocking)"
	@echo "  make peer                 Launch a peer shell; override PEER_PORT/RFC_STORE as needed"
	@echo "  make peer1|peer2|peer3    Quick peers bound to ports 6001/6002/6003 with matching stores"
	@echo "Variables:"
	@echo "  SERVER_HOST=$(SERVER_HOST) SERVER_PORT=$(SERVER_PORT) PEER_HOST=$(PEER_HOST) PEER_PORT=$(PEER_PORT)"
	@echo "  RFC_STORE=$(RFC_STORE) SAMPLE_DIR=$(SAMPLE_DIR)"

server:
	$(PYTHON) -m server.server --host $(SERVER_HOST) --port $(SERVER_PORT)

peer:
	$(PYTHON) -m peer.cli --server-host $(SERVER_HOST) --server-port $(SERVER_PORT) --peer-host $(PEER_HOST) --peer-port $(PEER_PORT) --rfc-store $(RFC_STORE) --sample-dir $(SAMPLE_DIR)

peer1:
	$(MAKE) peer PEER_PORT=6001 RFC_STORE=peer1_store

peer2:
	$(MAKE) peer PEER_PORT=6002 RFC_STORE=peer2_store

peer3:
	$(MAKE) peer PEER_PORT=6003 RFC_STORE=peer3_store

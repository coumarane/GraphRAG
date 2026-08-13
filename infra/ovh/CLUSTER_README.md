# OVH Servers for RAG Graph Cluster

This document contains only the OVH dedicated server information and the recommended disk layout for the RAG Graph infrastructure.

## Target layout

Use a dedicated data partition mounted on `/data` on every node.

Recommended usage for `/data`:

- `/data/postgres`
- `/data/minio`
- `/data/neo4j`
- `/data/uploads`
- `/data/app-data`

This keeps application data, uploaded documents, graph storage, object storage, and large temporary files away from the root filesystem.

## Recommended partition scheme

The OVH nodes in this cluster have `1 x 120 GB SSD SATA`, so the partitioning should match that size instead of a generic multi-terabyte example.

```text
Mount point   Size      Filesystem   Purpose
/boot/efi     512 MB    FAT32        UEFI boot
/boot         1 GB      ext4         Kernel and boot files
/             35 GB     ext4         Ubuntu OS, packages, /etc, binaries
/var          20 GB     ext4         Journals, apt cache, system logs
/data         ~60 GB    ext4/xfs     PostgreSQL, MinIO, Neo4j, uploads, app data
swap          4 GB      swap         Optional safety margin
```

Notes:

- Keep `/` below `40 GB` so system packages and logs do not consume the full disk.
- Keep `/var` separate because `journald`, package cache, and system logs can grow during upgrades and incidents.
- Mount `/data` with `defaults,noatime`.
- For XFS, use `ftype=1`.

## Node inventory

### Master

- Name: `ns3063017.ip-193-70-35.eu`
- IPv4: `193.70.35.121`
- CPU: `Intel Xeon E5-1620v2 - 4c/8t - 3.7 GHz/3.9 GHz`
- RAM: `32 GB`
- Disk: `1 x 120 GB SSD SATA`
- Role: master node

Recommended use on `/data`:

- `/data/postgres`
- `/data/minio`
- `/data/neo4j`
- `/data/uploads`
- `/data/app-data`

### Worker 1

- Name: `ns3063022.ip-193-70-35.eu`
- IPv4: `193.70.35.122`
- CPU: `Intel Xeon E5-1620v2 - 4c/8t - 3.7 GHz/3.9 GHz`
- RAM: `32 GB`
- Disk: `1 x 120 GB SSD SATA`
- Role: general workload node

### Worker 2

- Name: `ns3086111.ip-145-239-68.eu`
- IPv4: `145.239.68.200`
- CPU: `Intel Xeon E5-1620v2 - 4c/8t - 3.7 GHz/3.9 GHz`
- RAM: `32 GB`
- Disk: `1 x 120 GB SSD SATA`
- Role: general workload node

## Manual preparation on each node

After installing Ubuntu, create and mount the data partition.

Example validation:

```bash
lsblk -f
findmnt /data
df -h / /var /data
```

Expected result:

- `/data` is a dedicated mountpoint
- `/data` has the majority of free space
- `/` and `/var` are separate and healthy

Create the application directories:

```bash
sudo mkdir -p /data/postgres /data/minio /data/neo4j /data/uploads /data/app-data
sudo chmod 755 /data/postgres /data/minio /data/neo4j /data/uploads /data/app-data
```

## Why this layout fits a RAG Graph workload

RAG Graph applications usually combine:

- frontend for document upload and chat
- API and worker containers
- vector database or PostgreSQL
- graph database such as Neo4j
- object storage such as MinIO
- background ingestion and embedding jobs

Those workloads generate large caches, temporary files, indexes, and persistent data. Putting application data on `/data` reduces the risk of:

- failed upgrades due to a full root partition
- PostgreSQL, MinIO, Neo4j, or uploaded documents competing with OS files
- graph indexes and object storage consuming the system partition

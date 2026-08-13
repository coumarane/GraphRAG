# Ansible Infrastructure Setup

This folder contains the Ansible playbooks used to provision:

- a Kubernetes cluster
- a Harbor registry
- a PostgreSQL server with optional pgAdmin

The versions below were checked against upstream stable releases on August 12, 2026.

## Current defaults

- Kubernetes: `1.36.2`
- Kubernetes APT channel: `v1.36`
- Helm: `v4.2.3`
- Harbor: `2.15.2`
- PostgreSQL major version: `18`
- PostgreSQL current stable minor on August 12, 2026: `18.4`
- pgAdmin container fallback image: `dpage/pgadmin4:9.17`

## Prerequisites

- Control machine with Python 3 and Ansible installed
- SSH access to all target hosts
- Sudo privileges on the target hosts
- Debian or Ubuntu targets for the current playbooks

Install Ansible and the required collection on the control machine:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install "ansible>=10,<11"
ansible-galaxy collection install community.postgresql
```

If you use SSH keys, see [README_SSH_KEY.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/README_SSH_KEY.md).

## Layout

- `kubernetes/playbook.yml`: bootstrap master and worker nodes
- `kubernetes/install_packages_playbook.yml`: install Helm on the Kubernetes master
- `harbor/playbook.yml`: install Harbor on a dedicated host
- `postgresql/playbook.yml`: install PostgreSQL and optionally pgAdmin

## Kubernetes setup

Edit [kubernetes/inventory.ini](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/kubernetes/inventory.ini) with your master and worker IPs and SSH user.

Example:

```ini
[master]
193.70.35.121

[worker]
193.70.35.122

[all:vars]
ansible_user=ubuntu
ansible_become=yes
```

Run the cluster bootstrap:

```bash
ansible-playbook infra/ansible/kubernetes/playbook.yml \
  -i infra/ansible/kubernetes/inventory.ini
```

Install Helm on the master:

```bash
ansible-playbook infra/ansible/kubernetes/install_packages_playbook.yml \
  -i infra/ansible/kubernetes/inventory.ini
```

What the playbook does:

- prepares the nodes
- installs `containerd`
- installs `kubelet`, `kubeadm`, and `kubectl` for Kubernetes `1.36.2`
- initializes the control plane on the master
- generates a join command
- joins worker nodes to the cluster

## Harbor setup

Edit [harbor/inventory.ini](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/harbor/inventory.ini) and [harbor/group_vars/harbor.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/harbor/group_vars/harbor.yml).

Required secrets:

- `HARBOR_ADMIN_PASSWORD`
- `HARBOR_DB_PASSWORD`

Run:

```bash
export HARBOR_ADMIN_PASSWORD='change-me'
export HARBOR_DB_PASSWORD='change-me-too'

ansible-playbook infra/ansible/harbor/playbook.yml \
  -i infra/ansible/harbor/inventory.ini
```

Notes:

- Harbor defaults to version `2.15.2`.
- Let’s Encrypt is enabled by default, so `harbor_hostname` must resolve publicly before the run.
- Harbor upgrades are in-place only. Harbor does not support downgrades after schema changes.

## PostgreSQL setup

Edit [postgresql/inventory.ini](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/postgresql/inventory.ini).

Required variables:

- `POSTGRES_ADMIN_PASSWORD`
- `POSTGRES_APP_DB`
- `POSTGRES_APP_USER`
- `POSTGRES_APP_PASSWORD`

If `pgadmin_setup=true`, also set:

- `PGADMIN_EMAIL`
- `PGADMIN_PASSWORD`

Run:

```bash
export POSTGRES_ADMIN_PASSWORD='change-me'
export POSTGRES_APP_DB='chatwithdocs_db'
export POSTGRES_APP_USER='chatwithdocs'
export POSTGRES_APP_PASSWORD='change-me-too'
export PGADMIN_EMAIL='admin@chatwithdocs.org'
export PGADMIN_PASSWORD='change-me-again'

ansible-playbook infra/ansible/postgresql/playbook.yml \
  -i infra/ansible/postgresql/inventory.ini
```

Notes:

- PostgreSQL defaults to major version `18`; the PGDG repo will install the latest `18.x` package available for the target OS.
- On August 12, 2026, the current stable PostgreSQL 18 minor release is `18.4`.
- pgAdmin repository packages are available for Ubuntu `noble`, so the default `auto` mode now resolves to `repo`.
- The container fallback remains available and uses `dpage/pgadmin4:9.17`.

## Common checks

Verify Ansible can reach a host:

```bash
ansible all -i infra/ansible/kubernetes/inventory.ini -m ping
```

Check the Kubernetes cluster after bootstrap:

```bash
ssh ubuntu@193.70.35.121 'kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes -o wide'
```

Check Harbor:

```bash
curl -I https://harbor.chatwithdocs.org
```

Check PostgreSQL:

```bash
psql "postgresql://chatwithdocs:password@database.chatwithdocs.org:5432/chatwithdocs_db"
```

## Upgrade guidance

- Kubernetes: update `common_kubernetes_version` and `common_kubernetes_apt_repo_version` together.
- Helm: update `helm_version`.
- Harbor: update `harbor_version` only to a supported release and back up Harbor before upgrading.
- PostgreSQL: changing `postgres_version` is a major upgrade and should be treated as a migration, not a routine package bump.

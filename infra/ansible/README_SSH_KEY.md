# SSH Key Setup for Ansible

This guide shows how to configure SSH key access for the hosts used by the Ansible playbooks in `infra/ansible/`.

The current Kubernetes inventory expects:

- master: `193.70.35.121`
- worker: `193.70.35.122`
- SSH user: `ubuntu`

## Recommended approach

Use one SSH key for all infrastructure hosts unless you have a reason to isolate keys per server. It is simpler to manage and works well with Ansible.

Generate a key:

```bash
ssh-keygen -t ed25519 -C "infra-ansible" -f ~/.ssh/id_ed25519_infra
```

Copy the public key to each server:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_infra.pub ubuntu@193.70.35.121
ssh-copy-id -i ~/.ssh/id_ed25519_infra.pub ubuntu@193.70.35.122
```

## Optional approach: one key per host

If you want separate keys:

```bash
ssh-keygen -t ed25519 -C "k8s-master" -f ~/.ssh/id_ed25519_k8s_master
ssh-keygen -t ed25519 -C "k8s-worker" -f ~/.ssh/id_ed25519_k8s_worker
```

Then install them on the matching hosts:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_k8s_master.pub ubuntu@193.70.35.121
ssh-copy-id -i ~/.ssh/id_ed25519_k8s_worker.pub ubuntu@193.70.35.122
```

## SSH config

Add entries to `~/.ssh/config`.

Using one shared key:

```sshconfig
Host k8s-master
  HostName 193.70.35.121
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519_infra
  IdentitiesOnly yes

Host k8s-worker
  HostName 193.70.35.122
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519_infra
  IdentitiesOnly yes
```

Using one key per host:

```sshconfig
Host k8s-master
  HostName 193.70.35.121
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519_k8s_master
  IdentitiesOnly yes

Host k8s-worker
  HostName 193.70.35.122
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519_k8s_worker
  IdentitiesOnly yes
```

## Use ssh-agent

Start the agent if needed:

```bash
eval "$(ssh-agent -s)"
```

Add your key:

```bash
ssh-add ~/.ssh/id_ed25519_infra
```

Or, if using separate keys:

```bash
ssh-add ~/.ssh/id_ed25519_k8s_master
ssh-add ~/.ssh/id_ed25519_k8s_worker
```

Check loaded keys:

```bash
ssh-add -l
```

## Test connectivity

Test direct SSH:

```bash
ssh k8s-master
ssh k8s-worker
```

Test with Ansible:

```bash
ansible all -i infra/ansible/kubernetes/inventory.ini -m ping
```

If you want Ansible to use your SSH config aliases, you can also point the inventory at hostnames instead of raw IPs.

Example:

```ini
[master]
k8s-master

[worker]
k8s-worker

[all:vars]
ansible_user=ubuntu
ansible_become=yes
```

## Troubleshooting

### Permission denied (publickey)

Check that:

- the correct private key is loaded in `ssh-agent`
- the matching public key exists in `~/.ssh/authorized_keys` on the server
- the server user in inventory matches the SSH user

Useful debug command:

```bash
ssh -vvv k8s-master
```

### Remote host identification has changed

If the server was rebuilt or its host key changed, remove the old entry from `known_hosts`:

```bash
ssh-keygen -R k8s-master
ssh-keygen -R 193.70.35.121

ssh-keygen -R k8s-worker
ssh-keygen -R 193.70.35.122
```

Then reconnect:

```bash
ssh k8s-master
ssh k8s-worker
```

### Ansible works over SSH but sudo fails

The current inventory uses:

```ini
[all:vars]
ansible_user=ubuntu
ansible_become=yes
```

Make sure:

- the `ubuntu` user exists on the host
- that user can run `sudo`
- you provide `--ask-become-pass` if the host requires a sudo password

Example:

```bash
ansible-playbook infra/ansible/kubernetes/playbook.yml \
  -i infra/ansible/kubernetes/inventory.ini \
  --ask-become-pass
```

## Security notes

- Prefer `ed25519` over older RSA keys unless you need RSA for compatibility.
- Use a passphrase on private keys.
- Do not commit private keys into the repository.
- Rotate keys if a laptop or workstation is lost.

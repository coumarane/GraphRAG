# PostgreSQL Ansible Role

Provision PostgreSQL (default v18) on the dedicated database host and bootstrap an application database/user, with optional pgAdmin install.

## Inventory

Update `infra/ansible/postgresql/inventory.ini` with your host(s). Example:
```
[postgresql]
postgres-node ansible_host=167.86.88.114 ansible_user=root ansible_python_interpreter=/usr/bin/python3 ansible_ssh_common_args='-o StrictHostKeyChecking=no'

[all:vars]
ansible_connection=ssh
```

## Required variables

Pass via extra-vars or environment (GitHub Secrets in the workflow):
- `postgres_admin_password` (>=8 chars) – superuser password
- `postgres_app_db` – application database name
- `postgres_app_user` – application user
- `postgres_app_password` (>=8 chars) – application user password

Optional:
- `postgres_rebuild` (default `false`) – destructive reset: purge existing PostgreSQL packages and wipe data/config directories before reinstall
- `pgadmin_setup` (default `true` in defaults) – set to `false` to skip pgAdmin
- `pgadmin_email`, `pgadmin_password` (>=8 chars) – required when pgAdmin enabled
- `postgres_version` – defaults to `18`
- `pgadmin_install_method` – `auto` (default; uses container on Noble), `repo`, or `container`
- For container method: `pgadmin_container_port` (default 8080), `pgadmin_container_image`, `pgadmin_container_data_dir`

## Run locally

```
ansible-playbook infra/ansible/postgresql/playbook.yml \
  -i infra/ansible/postgresql/inventory.ini \
  --extra-vars "ansible_password=<root_pw> postgres_admin_password=<admin_pw> postgres_app_db=<db> postgres_app_user=<user> postgres_app_password=<user_pw>"
```

Run a destructive rebuild from scratch:
```
ansible-playbook infra/ansible/postgresql/playbook.yml \
  -i infra/ansible/postgresql/inventory.ini \
  --extra-vars "ansible_password=<root_pw> postgres_admin_password=<admin_pw> postgres_app_db=<db> postgres_app_user=<user> postgres_app_password=<user_pw> postgres_rebuild=true"
```

Enable pgAdmin on supported codenames (e.g., jammy):
```
--extra-vars "pgadmin_setup=true pgadmin_email=<email> pgadmin_password=<pw> pgadmin_distribution=jammy"
```

Enable pgAdmin in container mode (default on Noble) on port 8080:
```
--extra-vars "pgadmin_setup=true pgadmin_install_method=container pgadmin_email=<email> pgadmin_password=<pw> pgadmin_container_port=8080"
```

## GitHub Actions workflow

`.github/workflows/run-postgresql-deploy.yml` installs Ansible, required collections, and runs the playbook. Set these secrets:
- `CONTABO_VM2_ROOT_PASSWORD`
- `POSTGRES_ADMIN_PASSWORD`
- `POSTGRES_APP_DB`
- `POSTGRES_APP_USER`
- `POSTGRES_APP_PASSWORD`
- (optional) `PGADMIN_EMAIL`, `PGADMIN_PASSWORD` if enabling pgAdmin via extra-vars.

Trigger manually via the “Run PostgreSQL Deploy” workflow dispatch.

Recommended dedicated-host run for this repository:
- `target_host=database.safranys.com`
- `postgres_rebuild=true` for a clean reinstall from scratch
- `postgres_version=18`

Warning:
- `postgres_rebuild=true` is destructive.
- It purges installed PostgreSQL packages and removes existing PostgreSQL data/config directories on the target host.
- Use it only when you explicitly want a fresh rebuild.

## Accessing pgAdmin (optional)

If pgAdmin is enabled:
- Repo mode: served as `pgadmin4-web` at `http://<host>/pgadmin4`.
- Container mode: served from the container on `http://<host>:<pgadmin_container_port>` (default 8080).

Log in with `pgadmin_email`/`pgadmin_password`, then add your PostgreSQL server using the app user credentials. Secure access with firewall rules or VPN.

## Pgadmin 
Here’s what to fill in on that pgAdmin “Register Server” form:

Server Name: any label you like (e.g., Prod Postgres).
Host name/address: `database.safranys.com` (or the host you set in inventory).
Port: 5432 (unless you changed it).
Maintenance database: postgres (or your app DB if you prefer).
Username: your app DB user (the value you set for postgres_app_user).
Password: your app DB user password (postgres_app_password).
SSL: leave default Prefer unless you’ve set up PostgreSQL TLS.

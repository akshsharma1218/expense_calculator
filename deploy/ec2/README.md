# EC2 deployment

For the simple single-instance Docker deployment, use [MICRO-QUICKSTART.md](MICRO-QUICKSTART.md). It targets a 1 GiB x86_64 EC2 micro instance, omits optional receipt OCR dependencies, and runs the Django app, PostgreSQL, and Caddy in Compose.

The sections below describe the older native systemd/Nginx installation and the larger full-dependency Compose profile. For a new micro deployment, follow the quickstart above instead.

## Native deployment (larger instance)

This setup runs Django/Daphne and PostgreSQL directly on one EC2 instance. Nginx serves collected static files and uploaded receipts, proxies HTTP/WebSockets, and Certbot provisions HTTPS certificates. It assumes Ubuntu 22.04 x86_64, the default `ubuntu` account, and the existing `imaksh.in` / `www.imaksh.in` hostnames.

## Instance and network

Use an x86_64 instance with at least 2 vCPUs, 8 GiB RAM, and a 30 GiB gp3 root volume. `requirements-prod.txt` includes PaddleOCR/PaddlePaddle, which dominates disk and memory use; Docker itself adds little runtime overhead. A smaller instance may work if OCR is unused, but test OCR and uploads under realistic load before sizing down.

Assign an Elastic IP and point both DNS A records to it. In the EC2 security group, allow SSH only from your IP and allow inbound TCP 80/443. Do not expose PostgreSQL port 5432 publicly.

## Install packages

SSH into the instance, then run:

```sh
sudo apt update
sudo apt install -y git python3 python3-venv python3-dev build-essential \
  libpq-dev libgomp1 libglib2.0-0 libgl1 nginx postgresql \
  certbot python3-certbot-nginx curl
```

## Create the database

The app connects over loopback and uses the `expense` schema. Create a password without putting it in a shell command or source file:

```sh
sudo -u postgres psql
```

At the `psql` prompt:

```sql
CREATE USER expense_calculator_user WITH LOGIN;
\password expense_calculator_user
CREATE DATABASE expense_calculator_db OWNER expense_calculator_user;
\connect expense_calculator_db
CREATE SCHEMA expense AUTHORIZATION expense_calculator_user;
ALTER ROLE expense_calculator_user SET search_path TO expense;
\q
```

Enter the same password twice at the hidden `\password` prompt. PostgreSQL should remain local; Ubuntu's default configuration does not expose it to the network.

## Clone and configure

Clone the application repository to the path used by the supplied service unit:

```sh
sudo -u ubuntu git clone --branch main <YOUR_GIT_REPOSITORY_URL> /home/ubuntu/expense_calculator
cd /home/ubuntu/expense_calculator
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-prod.txt
mkdir -p staticfiles media logs
```

Generate a Django key and a PostgreSQL password using `python3 -c 'import secrets; print(secrets.token_urlsafe(50))'` and `openssl rand -hex 32`. Put the generated Django key and the database password you set above in the environment file; do not put real secrets in Git.

```sh
sudo install -o root -g ubuntu -m 0640 /dev/null /etc/expense-calculator.env
sudoedit /etc/expense-calculator.env
```

Use these values, replacing the secret values as indicated:

```dotenv
ENVIRONMENT=production
SECRET_KEY=REPLACE_WITH_GENERATED_DJANGO_KEY
ALLOWED_HOSTS=imaksh.in,www.imaksh.in,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://imaksh.in,https://www.imaksh.in
CORS_ALLOWED_ORIGINS=https://imaksh.in,https://www.imaksh.in
POSTGRES_DB=expense_calculator_db
POSTGRES_USER=expense_calculator_user
POSTGRES_PASSWORD=REPLACE_WITH_DATABASE_PASSWORD
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
DB_HOST=localhost
DB_PORT=5432
DATABASE_CONN_MAX_AGE=60
STATIC_ROOT=/home/ubuntu/expense_calculator/staticfiles
MEDIA_ROOT=/home/ubuntu/expense_calculator/media
SECURE_HSTS_SECONDS=31536000
LOG_LEVEL=INFO
```

Keep values shell-compatible because the deploy script sources this file. The generated key/password formats above are safe. `REDIS_URL` can remain unset for one Daphne process; Channels uses its in-memory layer. Set it only if you install Redis and need notifications shared across multiple processes.

Load the environment and initialize Django:

```sh
set -a
. /etc/expense-calculator.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

## Start Daphne and Nginx

Install the supplied systemd unit and Nginx site:

```sh
sudo install -m 0644 deploy/ec2/expense-calculator.service /etc/systemd/system/expense-calculator.service
sudo systemctl daemon-reload
sudo systemctl enable --now expense-calculator

sudo install -m 0644 deploy/ec2/nginx-expense-calculator.conf /etc/nginx/sites-available/expense-calculator
sudo ln -s /etc/nginx/sites-available/expense-calculator /etc/nginx/sites-enabled/expense-calculator
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

The service binds Daphne to `127.0.0.1:8000`; only Nginx is exposed publicly. The Nginx site proxies `/ws/notifications/` with WebSocket upgrade headers, serves `/static/` and `/media/` from the configured paths, and forwards the original HTTPS scheme to Django.

## Enable HTTPS

After DNS points to the instance and port 80 is reachable:

```sh
sudo certbot --nginx --redirect -d imaksh.in -d www.imaksh.in
sudo certbot renew --dry-run
```

Certbot updates the Nginx site with the certificate and HTTP-to-HTTPS redirect. Renewals are handled by the system timer installed with Certbot. Check `sudo nginx -t` and `sudo systemctl status certbot.timer` if renewal fails.

## Deploy updates

Push application changes to the branch configured above, then SSH into EC2 and run:

```sh
cd /home/ubuntu/expense_calculator
sh deploy/ec2/deploy.sh
```

The script fast-forwards Git, installs pinned production requirements, runs migrations and `collectstatic`, restarts systemd, and checks `/health/`. It stops on a failed migration or install; inspect `sudo journalctl -u expense-calculator -n 100` for service errors.

## Persistence and recovery

A reboot or EC2 stop/start does not require rerunning the `psql` setup: PostgreSQL starts again and its database files remain on the attached EBS volume. If PostgreSQL crashed, it performs its normal WAL recovery on startup. The setup SQL is only for a new, empty database. Before terminating/replacing an instance, make sure its EBS volume is retained or restore from backups; a new empty volume needs the database/user/schema created and the data restored.

Make regular database and upload backups, and copy them off the instance (for example, to a private S3 bucket). A backup stored only on the same EBS volume will not protect against losing that volume:

```sh
umask 077
mkdir -p "$HOME/backups"
sudo -u postgres pg_dump -Fc expense_calculator > "$HOME/backups/expense-$(date +%F).dump"
tar -C /home/ubuntu/expense_calculator -czf "$HOME/backups/media-$(date +%F).tar.gz" media
```

After creating the database/user/schema on a replacement host, restore a dump with:

```sh
sudo -u postgres pg_restore --clean --if-exists --dbname=expense_calculator /path/to/expense.dump
```

Restore the matching `media/` archive as well. Restrict access to backups because uploaded receipts and database contents may be sensitive.

## Docker Compose deployment

The Compose option is in addition to the native systemd/Nginx setup above. Use an x86_64 Ubuntu EC2 instance with at least 2 vCPUs, 8 GiB RAM, and 30 GiB of EBS storage; the pinned PaddleOCR/PaddlePaddle packages make ARM images and small instances unsuitable without separately validating those dependencies.

Point DNS A records for your domain and `www` to the instance's Elastic IP. Allow inbound TCP 80/443 and SSH only from your IP. Do not open PostgreSQL port 5432. Make sure the native Nginx service is stopped before starting Compose because Caddy binds those public ports.

Install Docker Engine and the Compose plugin, then add the deployment settings:

```sh
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu
```

Log out and back in so the `ubuntu` account receives Docker group access. From the repository root:

```sh
cp deploy/ec2/docker.env.example deploy/ec2/.env.docker
python3 -c 'import secrets; print(secrets.token_hex(48))'
openssl rand -hex 32
chmod 600 deploy/ec2/.env.docker
sudo systemctl disable --now nginx || true
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml up -d --build
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml ps
```

Use the Python output for `DJANGO_SECRET_KEY` and the OpenSSL output for `POSTGRES_PASSWORD`; set `DOMAIN` to the DNS name. The environment file is ignored by Git. Caddy obtains and renews HTTPS certificates automatically once both DNS names resolve to the EC2 instance and ports 80/443 are reachable.

On first start, Compose creates the PostgreSQL `expense` schema, applies Django migrations, collects static files, and starts Daphne. PostgreSQL is reachable only on the Compose network. Named volumes persist the database, static files, uploads, logs, and Caddy certificates across container replacement. Do not use `docker compose down -v` unless you intentionally want to delete all persisted data.

For subsequent code deployments, pull the desired revision and rebuild without deleting volumes:

```sh
git pull --ff-only
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml up -d --build
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml logs --tail=100 web
```

This creates a fresh Compose-managed PostgreSQL volume; it does not automatically import an existing native EC2 or Kubernetes database. Back up and restore existing database/media data before switching production traffic.

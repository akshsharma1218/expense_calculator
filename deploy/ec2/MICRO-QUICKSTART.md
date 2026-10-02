# EC2 Micro Docker Deployment

This runs FinFlow on one x86_64 EC2 micro instance with Docker Compose: Django/Daphne, PostgreSQL, and Caddy HTTPS. The micro image excludes optional PaddleOCR; transactions, CSV import/export, and notifications remain available. Receipt OCR is not available on this profile.

## 1. Create the instance

Use Ubuntu 22.04/24.04 x86_64, a `t3.micro` (1 GiB RAM), and at least a 20 GiB gp3 EBS volume. Attach an Elastic IP and point DNS A records for your domain and `www` to it. In the security group, allow SSH from your IP and TCP 80/443 from the internet. Do not open port 5432.

## 2. Install Docker

SSH into the instance:

```sh
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git openssl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and reconnect so the Docker group takes effect.

## 3. Configure secrets

Clone the repository, then from its root:

```sh
cp deploy/ec2/docker.env.example deploy/ec2/.env.docker
openssl rand -hex 48
openssl rand -hex 32
chmod 600 deploy/ec2/.env.docker
nano deploy/ec2/.env.docker
```

Use the first generated value for `DJANGO_SECRET_KEY`, the second for `POSTGRES_PASSWORD`, and set `DOMAIN` to your real domain. Keep `.env.docker` private. Email and Gemini settings are optional.

## 4. Start the app

From the repository root:

```sh
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml up -d --build
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml ps
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml exec web python manage.py createsuperuser
```

Open `https://your-domain`. Caddy obtains and renews certificates automatically after DNS points to the instance and ports 80/443 are reachable. Migrations and static collection run when the web container starts.

## Update and backup

```sh
git pull --ff-only
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml up -d --build
docker compose --env-file deploy/ec2/.env.docker -f deploy/ec2/docker-compose.yml logs --tail=100 web
```

Compose named volumes preserve PostgreSQL data, uploads, static files, logs, and TLS certificates. Never run `docker compose down -v` unless deleting all application data is intended. Back up the PostgreSQL volume and `mediafiles` volume regularly to storage outside this instance.

The `t3.micro` profile is for light, low-concurrency use. OCR is omitted to fit the memory budget; use a larger instance for receipt OCR or heavier traffic.

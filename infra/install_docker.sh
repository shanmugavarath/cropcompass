#!/usr/bin/env bash
# Install Docker Engine on WSL2 (Ubuntu/Debian)
set -euo pipefail

echo "==> Updating apt..."
sudo apt-get update -y

echo "==> Installing prerequisites..."
sudo apt-get install -y ca-certificates curl gnupg lsb-release

echo "==> Adding Docker GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "==> Adding Docker apt repository..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "==> Installing Docker Engine + Compose plugin..."
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Adding current user to docker group..."
sudo usermod -aG docker "$USER"

echo "==> Starting Docker daemon..."
sudo service docker start || sudo dockerd &

echo ""
echo "Docker installed successfully."
echo "Run: newgrp docker   (or log out and back in) to use docker without sudo."
docker --version
docker compose version

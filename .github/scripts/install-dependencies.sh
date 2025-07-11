#!/bin/bash

# Install Dependencies for Frappe Bench
# This script sets up the dependencies for running tests in CI

set -e

echo "Installing system dependencies..."

# Update system packages
sudo apt-get update -y

# Install required system packages
sudo apt-get install -y \
    python3-dev \
    python3-pip \
    python3-venv \
    redis-server \
    software-properties-common \
    build-essential \
    git \
    curl \
    wget \
    nginx \
    supervisor \
    fontconfig \
    libfontconfig1 \
    xvfb

# Install Node.js and npm (if not already installed)
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

# Install yarn
if ! command -v yarn &> /dev/null; then
    npm install -g yarn
fi

# Install wkhtmltopdf (required for Frappe)
if ! command -v wkhtmltopdf &> /dev/null; then
    wget -q https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.jammy_amd64.deb
    sudo dpkg -i wkhtmltox_0.12.6.1-2.jammy_amd64.deb || true
    sudo apt-get install -f -y
fi

# Install Python dependencies
pip3 install --upgrade pip
pip3 install frappe-bench

# Set up Redis (start service)
sudo systemctl start redis-server
sudo systemctl enable redis-server

echo "Dependencies installed successfully!"

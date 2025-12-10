#!/bin/bash

# Install script for Verenigingen CI
# Follows ERPNext/Frappe pattern for GitHub Actions

set -e

cd ~ || exit

echo "::group::Install System Dependencies"
sudo apt-get update
sudo apt-get remove -y mysql-server mysql-client || true
sudo apt-get install -y \
    libcups2-dev \
    redis-server \
    mariadb-client \
    libmariadb-dev \
    wkhtmltopdf

pip install frappe-bench
echo "::endgroup::"

# Determine branch to use
githubbranch=${GITHUB_BASE_REF:-${GITHUB_REF##*/}}

# Frappe configuration
frappeuser=${FRAPPE_USER:-"frappe"}
frappecommitish=${FRAPPE_BRANCH:-"version-15"}

# ERPNext configuration
erpnextuser=${ERPNEXT_USER:-"frappe"}
erpnextcommitish=${ERPNEXT_BRANCH:-"version-15"}

echo "::group::Clone Frappe"
echo "Cloning Frappe from ${frappeuser}/frappe @ ${frappecommitish}"
mkdir frappe
pushd frappe
git init
git remote add origin "https://github.com/${frappeuser}/frappe"
git fetch origin "${frappecommitish}" --depth 1
git checkout FETCH_HEAD
popd
echo "::endgroup::"

echo "::group::Initialize Bench"
bench init --skip-assets --frappe-path ~/frappe --python "$(which python)" frappe-bench
echo "::endgroup::"

echo "::group::Configure Test Site"
mkdir -p ~/frappe-bench/sites/test_site

DB=${DB:-mariadb}
if [ "$DB" == "mariadb" ]; then
    cp -r "${GITHUB_WORKSPACE}/.github/helper/db/mariadb.json" ~/frappe-bench/sites/test_site/site_config.json
    echo "Configured MariaDB"
else
    echo "Error: Only MariaDB is currently supported"
    exit 1
fi
echo "::endgroup::"

echo "::group::Configure MariaDB"
mariadb --host 127.0.0.1 --port 3306 -u root -pdb_root -e "SET GLOBAL character_set_server = 'utf8mb4'";
mariadb --host 127.0.0.1 --port 3306 -u root -pdb_root -e "SET GLOBAL collation_server = 'utf8mb4_unicode_ci'";
mariadb --host 127.0.0.1 --port 3306 -u root -pdb_root -e "CREATE DATABASE IF NOT EXISTS test_frappe";
mariadb --host 127.0.0.1 --port 3306 -u root -pdb_root -e "CREATE USER IF NOT EXISTS 'test_frappe'@'localhost' IDENTIFIED BY 'test_frappe'";
mariadb --host 127.0.0.1 --port 3306 -u root -pdb_root -e "GRANT ALL PRIVILEGES ON \`test_frappe\`.* TO 'test_frappe'@'localhost'";
mariadb --host 127.0.0.1 --port 3306 -u root -pdb_root -e "FLUSH PRIVILEGES";
echo "::endgroup::"

echo "::group::Get ERPNext"
cd ~/frappe-bench
echo "Getting ERPNext from ${erpnextuser}/erpnext @ ${erpnextcommitish}"
bench get-app --branch "${erpnextcommitish}" "https://github.com/${erpnextuser}/erpnext"
echo "::endgroup::"

echo "::group::Get Verenigingen"
cd ~/frappe-bench
# Link the checked out verenigingen app
ln -s "${GITHUB_WORKSPACE}" apps/verenigingen
echo "verenigingen" >> sites/apps.txt
echo "::endgroup::"

echo "::group::Install Python Dependencies"
cd ~/frappe-bench
if [ "$TYPE" == "server" ]; then
    bench setup requirements --dev
fi

# Install verenigingen Python dependencies
pip install -e "apps/verenigingen[dev,test]" || pip install -e "apps/verenigingen"
echo "::endgroup::"

echo "::group::Start Bench & Build"
cd ~/frappe-bench
bench start &>> ~/frappe-bench/bench_start.log &

# Build assets in parallel with site reinstall
CI=Yes bench build --app frappe &
build_pid=$!

bench --site test_site reinstall --yes

# Install apps on site
bench --site test_site install-app erpnext
bench --site test_site install-app verenigingen

wait $build_pid
echo "::endgroup::"

echo "Setup complete!"

#!/bin/bash

# Assumes a clean Ubuntu 24.04 install with no other packages installed,
# the steps below will get you to a functioning instance.

# Install Python 3.11
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt install -y python3.11 python3.11-dev python3.11-venv

# Install Memcached to support quick data access and sessions
sudo apt install -y memcached
sudo sed -i 's|-m 64|-m 4096|g' /etc/memcached.conf
sudo service memcached restart
sudo service memcached status

# Install requirements for the various pip installs that will
# occuring during startup
sudo apt install -y pkg-config build-essential libmysqlclient-dev

# Install MySQL database to store sanic authentication information
sudo apt install -y mysql-server

# Fix TimeZones in MySQL
mysql_tzinfo_to_sql /usr/share/zoneinfo | sudo mysql -u root mysql

# Update MySQL Configuration
echo 'sql_mode = "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"' | sudo tee -a /etc/mysql/mysql.conf.d/mysqld.cnf
echo "default-time-zone='America/New_York'" | sudo tee -a /etc/mysql/mysql.conf.d/mysqld.cnf

# Update MySQL Configuration
sudo sed -i 's|\t| |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|  | |g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|#max_allowed_packet = 64M|max_allowed_packet = 96M|g' /etc/mysql/mysql.conf.d/mysqld.cnf
sudo sed -i 's|query_cache_size = 16M|query_cache_size = 64M|g' /etc/mysql/mysql.conf.d/mysqld.cnf
echo "default-storage-engine = InnoDB" | sudo tee -a /etc/mysql/mysql.conf.d/mysqld.cnf
echo "innodb_checksum_algorithm = crc32" | sudo tee -a /etc/mysql/mysql.conf.d/mysqld.cnf
echo "log_bin_trust_function_creators = 1" | sudo tee -a /etc/mysql/mysql.conf.d/mysqld.cnf

# Restart MySQL
sudo service mysql restart

# Get a username and password for mysql
read -p "Enter the username of MySQL sanic user to create: " myuser
read -p "Enter the password for this user: " mypass
read -p "Enter the database name that will be used for sanic: " mydb

# Set Admin User credentials - changeme
sudo mysql -u root mysql -e "CREATE USER '$myuser'@'%' IDENTIFIED BY '$mypass';"
sudo mysql -u root mysql -e "CREATE DATABASE $mydb;"
sudo mysql -u root mysql -e "GRANT ALL PRIVILEGES ON $mydb.* TO '$myuser'@'%' WITH GRANT OPTION;"

# Load empty sanic tables
sudo mysql -u root $mydb < auth_tables.sql

# If you want to use pam authentication (log on via local username/password combinations)
# You will need to add the user that sanic will be running as to the shadow group
sudo usermod -aG shadow $(whoami)

# If you had used the default values in the default config.py where the MySQL
# username=username, password=password, and database=dbname then you can test to
# see if everything is working by simply running the startup.sh script with
# the default repo.

#!/bin/bash
set -e

echo "=== Configuring Redis ==="

# Configure Redis
systemctl enable redis-server
echo 'maxmemory 512mb' >> /etc/redis/redis.conf
echo 'maxmemory-policy allkeys-lru' >> /etc/redis/redis.conf

echo "=== Redis configuration completed ==="

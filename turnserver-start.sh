#!/bin/bash

# Substitute environment variables
sed -i 's|__STATIC_AUTH_SECRET__|'${STATIC_AUTH_SECRET}'|g' /etc/turnserver.conf
sed -i 's|__REALM__|'${REALM}'|g' /etc/turnserver.conf

# Start the Coturn server
turnserver -c /etc/turnserver.conf
#!/bin/bash

# Generate SSL certificates for local development
mkdir -p ssl_certs

# Create a private key
openssl genrsa -out ssl_certs/localhost.key 2048

# Create a certificate signing request
openssl req -new -key ssl_certs/localhost.key -out ssl_certs/localhost.csr -subj "/C=US/ST=Development/L=Development/O=CUPCAKE/OU=Development/CN=localhost"

# Create the certificate
openssl x509 -req -days 365 -in ssl_certs/localhost.csr -signkey ssl_certs/localhost.key -out ssl_certs/localhost.crt

# Create a combined certificate file for Django
cat ssl_certs/localhost.crt ssl_certs/localhost.key > ssl_certs/localhost.pem

echo "SSL certificates generated in ssl_certs/ directory"
echo "Django can use: ssl_certs/localhost.crt and ssl_certs/localhost.key"
echo "Angular can use: ssl_certs/localhost.crt and ssl_certs/localhost.key"

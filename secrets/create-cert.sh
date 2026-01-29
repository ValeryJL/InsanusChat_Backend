#!/bin/bash
# Script to create X.509 certificate for MongoDB authentication
# Based on MongoDB X.509 documentation

set -e

CERT_DIR="."
CERT_FILE="mongodb-cert.pem"
KEY_FILE="mongodb-key.pem"
CA_CERT_FILE="mongodb-ca.pem"
CA_KEY_FILE="mongodb-ca-key.pem"

# Generate CA private key
openssl genrsa -out "$CA_KEY_FILE" 4096

# Generate CA certificate (self-signed)
openssl req -new -x509 -days 3650 -key "$CA_KEY_FILE" -out "$CA_CERT_FILE" \
  -subj "/C=AR/ST=BuenosAires/L=BuenosAires/O=InsanusTech/OU=Development/CN=InsanusTechCA"

# Generate private key for client certificate
openssl genrsa -out "$KEY_FILE" 4096

# Generate certificate signing request
openssl req -new -key "$KEY_FILE" -out mongodb-cert.csr \
  -subj "/C=AR/ST=BuenosAires/L=BuenosAires/O=InsanusTech/OU=Development/CN=insanuschat-client"

# Sign the certificate with CA
openssl x509 -req -in mongodb-cert.csr -CA "$CA_CERT_FILE" -CAkey "$CA_KEY_FILE" \
  -CAcreateserial -out mongodb-cert-only.pem -days 3650

# Combine certificate and key into single PEM file (required by MongoDB)
cat mongodb-cert-only.pem "$KEY_FILE" > "$CERT_FILE"

# Clean up temporary files
rm mongodb-cert.csr mongodb-cert-only.pem

echo "Certificate created successfully: $CERT_FILE"
echo "CA Certificate: $CA_CERT_FILE"
echo ""
echo "To use with MongoDB, set MONGO_X509_CERT_PATH=$CERT_DIR/$CERT_FILE"

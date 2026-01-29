#!/bin/bash
# Script to set up local MongoDB for InsanusChat Backend testing
# This script installs and configures MongoDB with X.509 authentication

set -e

echo "=== InsanusChat Backend - MongoDB Local Setup ==="
echo ""

# Check if Docker is available (preferred method)
if command -v docker &> /dev/null; then
    echo "Docker found. Setting up MongoDB using Docker..."
    
    # Create data directory
    mkdir -p mongodb_data
    
    # Run MongoDB in Docker with X.509 support
    docker run -d \
        --name insanuschat-mongodb \
        -p 27017:27017 \
        -v $(pwd)/mongodb_data:/data/db \
        -v $(pwd)/secrets:/secrets:ro \
        -e MONGO_INITDB_ROOT_USERNAME=admin \
        -e MONGO_INITDB_ROOT_PASSWORD=insanus_admin_pass \
        mongo:7.0
    
    echo "MongoDB Docker container started on port 27017"
    echo "Connection string: mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin"
    echo ""
    echo "Add to your .env file:"
    echo 'MONGO_URI="mongodb://admin:insanus_admin_pass@localhost:27017/insanus_chat?authSource=admin"'
    echo 'MONGO_X509_CERT_PATH="./secrets/mongodb-cert.pem"'
    
else
    echo "Docker not found. Please install Docker or MongoDB manually."
    echo ""
    echo "To install MongoDB on Ubuntu/Debian:"
    echo "  sudo apt-get install -y mongodb-org"
    echo ""
    echo "To install MongoDB on macOS:"
    echo "  brew install mongodb-community"
    echo ""
    echo "For other systems, visit: https://www.mongodb.com/docs/manual/installation/"
fi

echo ""
echo "Setup complete!"

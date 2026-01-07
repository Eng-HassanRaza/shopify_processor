#!/bin/bash
# Startup script for Shopify Review Processor

cd "$(dirname "$0")/.."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r shopify_processor/requirements.txt

# Install Playwright browsers if needed
if ! command -v playwright &> /dev/null || [ ! -d "$HOME/.cache/ms-playwright" ]; then
    echo "Installing Playwright browsers..."
    playwright install chromium
fi

# Start the application
echo "Starting Shopify Review Processor..."
cd shopify_processor
python app.py





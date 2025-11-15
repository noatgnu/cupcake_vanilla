#!/bin/bash

set -e

MODELS_DIR="/app/whisper.cpp/models"
cd "$MODELS_DIR"

echo "Checking and downloading Whisper.cpp models..."
echo "Models directory: $MODELS_DIR"

download_model_if_missing() {
    local model_name=$1
    local model_file="ggml-${model_name}.bin"

    if [ -f "$MODELS_DIR/$model_file" ]; then
        echo "✓ Model $model_file already exists ($(du -h "$MODELS_DIR/$model_file" | cut -f1))"
    else
        echo "⬇ Downloading $model_file..."
        ./download-ggml-model.sh "$model_name"
        if [ -f "$MODELS_DIR/$model_file" ]; then
            echo "✓ Downloaded $model_file ($(du -h "$MODELS_DIR/$model_file" | cut -f1))"
        else
            echo "✗ Failed to download $model_file"
        fi
    fi
}

echo ""
echo "Default models to download: base.en, base, small.en, small, medium.en, medium"
echo ""

download_model_if_missing "base.en"
download_model_if_missing "base"
download_model_if_missing "small.en"
download_model_if_missing "small"
download_model_if_missing "medium.en"
download_model_if_missing "medium"

echo ""
echo "Model check complete!"
echo "Available models:"
ls -lh "$MODELS_DIR"/ggml-*.bin 2>/dev/null || echo "No models found"
echo ""

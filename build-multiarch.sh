#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

if [ -f "$PROJECT_ROOT/.env.build" ]; then
    echo "Loading configuration from .env.build"
    source "$PROJECT_ROOT/.env.build"
else
    echo "Warning: .env.build not found, using defaults"
    echo "Consider creating .env.build from .env.build.example"
    echo ""
fi

REGISTRY=${REGISTRY:-""}
TAG=${TAG:-"latest"}
PLATFORMS=${PLATFORMS:-"linux/amd64,linux/arm64"}
APP_IMAGE_NAME=${APP_IMAGE_NAME:-"cupcake-vanilla"}
TRANSCRIBE_IMAGE_NAME=${TRANSCRIBE_IMAGE_NAME:-"cupcake-vanilla-transcribe"}
FRONTEND_IMAGE_NAME=${FRONTEND_IMAGE_NAME:-"cupcake-vanilla-frontend"}
APP_DOCKERFILE=${APP_DOCKERFILE:-"dockerfiles/Dockerfile"}
TRANSCRIBE_DOCKERFILE=${TRANSCRIBE_DOCKERFILE:-"dockerfiles/Dockerfile-transcribe-worker"}
FRONTEND_DOCKERFILE=${FRONTEND_DOCKERFILE:-"dockerfiles/Dockerfile-frontend"}
APP_BUILD_CONTEXT=${APP_BUILD_CONTEXT:-"."}
TRANSCRIBE_BUILD_CONTEXT=${TRANSCRIBE_BUILD_CONTEXT:-"."}
FRONTEND_BUILD_CONTEXT=${FRONTEND_BUILD_CONTEXT:-"../cupcake-vanilla-ng"}
BUILDER_NAME=${BUILDER_NAME:-"cupcake-builder"}

echo "=========================================="
echo "Building Multi-Architecture Docker Images"
echo "=========================================="
echo "Registry:   ${REGISTRY:-"(local only)"}"
echo "Tag:        ${TAG}"
echo "Platforms:  ${PLATFORMS}"
echo "Builder:    ${BUILDER_NAME}"
echo ""

if [ -z "$REGISTRY" ]; then
    echo "⚠️  Warning: REGISTRY not set. Images will only be built locally."
    echo "   To push to a registry, set REGISTRY in .env.build or environment:"
    echo "   export REGISTRY=docker.io/yourname"
    echo ""
    PUSH_FLAG=""
else
    echo "✓ Registry configured. Images will be pushed after build."
    echo ""
    PUSH_FLAG="--push"
fi

echo "Ensuring buildx builder exists..."
if ! docker buildx ls | grep -q "$BUILDER_NAME"; then
    echo "Creating buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --use
else
    echo "Using existing builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
fi

echo ""

build_cache_flags=""
if [ "$ENABLE_CACHE" = "1" ]; then
    [ -n "$CACHE_FROM" ] && build_cache_flags="$build_cache_flags --cache-from=$CACHE_FROM"
    [ -n "$CACHE_TO" ] && build_cache_flags="$build_cache_flags --cache-to=$CACHE_TO"
fi

build_args_flags=""
if [ -n "$BUILD_ARGS" ]; then
    for arg in $BUILD_ARGS; do
        build_args_flags="$build_args_flags --build-arg $arg"
    done
fi

echo "=========================================="
echo "Building Main Application Image"
echo "=========================================="
echo "Dockerfile: $APP_DOCKERFILE"
echo "Context:    $APP_BUILD_CONTEXT"
if [ -n "$REGISTRY" ]; then
    echo "Image:      ${REGISTRY}/${APP_IMAGE_NAME}:${TAG}"
else
    echo "Image:      ${APP_IMAGE_NAME}:${TAG}"
fi
echo ""

docker buildx build \
    --platform "$PLATFORMS" \
    $PUSH_FLAG \
    -f "$APP_DOCKERFILE" \
    ${REGISTRY:+-t ${REGISTRY}/${APP_IMAGE_NAME}:${TAG}} \
    ${REGISTRY:--t ${APP_IMAGE_NAME}:${TAG}} \
    $build_cache_flags \
    $build_args_flags \
    "$APP_BUILD_CONTEXT"

echo ""
echo "=========================================="
echo "Building Transcribe Worker Image"
echo "=========================================="
echo "Dockerfile: $TRANSCRIBE_DOCKERFILE"
echo "Context:    $TRANSCRIBE_BUILD_CONTEXT"
if [ -n "$REGISTRY" ]; then
    echo "Image:      ${REGISTRY}/${TRANSCRIBE_IMAGE_NAME}:${TAG}"
else
    echo "Image:      ${TRANSCRIBE_IMAGE_NAME}:${TAG}"
fi
echo ""

docker buildx build \
    --platform "$PLATFORMS" \
    $PUSH_FLAG \
    -f "$TRANSCRIBE_DOCKERFILE" \
    ${REGISTRY:+-t ${REGISTRY}/${TRANSCRIBE_IMAGE_NAME}:${TAG}} \
    ${REGISTRY:--t ${TRANSCRIBE_IMAGE_NAME}:${TAG}} \
    $build_cache_flags \
    $build_args_flags \
    "$TRANSCRIBE_BUILD_CONTEXT"

echo ""
echo "=========================================="
echo "Building Frontend Image"
echo "=========================================="
echo "Dockerfile: $FRONTEND_DOCKERFILE"
echo "Context:    $FRONTEND_BUILD_CONTEXT"
if [ -n "$REGISTRY" ]; then
    echo "Image:      ${REGISTRY}/${FRONTEND_IMAGE_NAME}:${TAG}"
else
    echo "Image:      ${FRONTEND_IMAGE_NAME}:${TAG}"
fi
echo ""

if [ ! -d "$FRONTEND_BUILD_CONTEXT" ]; then
    echo "⚠️  Warning: Frontend build context not found: $FRONTEND_BUILD_CONTEXT"
    echo "   Skipping frontend image build."
    echo "   Update FRONTEND_BUILD_CONTEXT in .env.build if needed."
else
    docker buildx build \
        --platform "$PLATFORMS" \
        $PUSH_FLAG \
        -f "$FRONTEND_DOCKERFILE" \
        ${REGISTRY:+-t ${REGISTRY}/${FRONTEND_IMAGE_NAME}:${TAG}} \
        ${REGISTRY:--t ${FRONTEND_IMAGE_NAME}:${TAG}} \
        $build_cache_flags \
        $build_args_flags \
        "$FRONTEND_BUILD_CONTEXT"
fi

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="

if [ -n "$PUSH_FLAG" ]; then
    echo ""
    echo "✓ Images built and pushed to registry:"
    echo "  ${REGISTRY}/${APP_IMAGE_NAME}:${TAG}"
    echo "  ${REGISTRY}/${TRANSCRIBE_IMAGE_NAME}:${TAG}"
    [ -d "$FRONTEND_BUILD_CONTEXT" ] && echo "  ${REGISTRY}/${FRONTEND_IMAGE_NAME}:${TAG}"
    echo ""
    echo "To use these images, update your docker-compose.yml:"
    echo "  app:"
    echo "    image: ${REGISTRY}/${APP_IMAGE_NAME}:${TAG}"
    echo "  transcribe-worker:"
    echo "    image: ${REGISTRY}/${TRANSCRIBE_IMAGE_NAME}:${TAG}"
    [ -d "$FRONTEND_BUILD_CONTEXT" ] && echo "  frontend:"
    [ -d "$FRONTEND_BUILD_CONTEXT" ] && echo "    image: ${REGISTRY}/${FRONTEND_IMAGE_NAME}:${TAG}"
else
    echo ""
    echo "✓ Images built locally for testing:"
    echo "  ${APP_IMAGE_NAME}:${TAG}"
    echo "  ${TRANSCRIBE_IMAGE_NAME}:${TAG}"
    [ -d "$FRONTEND_BUILD_CONTEXT" ] && echo "  ${FRONTEND_IMAGE_NAME}:${TAG}"
    echo ""
    echo "To build and push to a registry:"
    echo "  1. Edit .env.build and set REGISTRY=docker.io/yourname"
    echo "  2. Run: ./build-multiarch.sh"
    echo ""
    echo "Or use environment variables:"
    echo "  REGISTRY=docker.io/yourname TAG=v1.0.0 ./build-multiarch.sh"
fi

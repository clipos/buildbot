#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright © 2019 ANSSI. All rights reserved.

set -e -u -o pipefail

# Be verbose for CI debugging/explicitness purpose:
set -x

# Check declaration in the environment of mandatory variables by this script:
: "${produce_sdks_artifacts:?}"
: "${reuse_sdks_artifacts:?}"
: "${produce_cache_artifacts:?}"
: "${reuse_cache_artifacts:?}"
: "${produce_build_artifacts:?}"


reuse-or-bootstrap_sdk() {
    local product_name="${1%/*}"
    local recipe_name="${1#*/}"
    local artifact_name="sdk:${product_name:?}.${recipe_name:?}.tar"

    if [[ "${reuse_sdks_artifacts:-0}" -eq 0 ]]; then
        cosmk bootstrap "${product_name:?}/${recipe_name:?}"
        if [[ "${produce_sdks_artifacts:-0}" -ne 0 ]]; then
            mkdir -p artifacts/sdks
            sudo bsdtar -cvpf "artifacts/sdks/${artifact_name}" \
                "cache/${product_name?}/"*"/${recipe_name?}"
            sudo chown "$UID:${GROUPS[0]}" "artifacts/sdks/${artifact_name}"
        fi
    else
        sudo rm -rf "cache/${product_name?}/"*"/${recipe_name?}"
        bsdtar -xvf "${artifact_name}"
    fi
}

build-image-configure_recipe() {
    local product_name="${1%/*}"
    local recipe_name="${1#*/}"
    local artifact_name="cache:${product_name:?}.${recipe_name:?}.tar"

    if [[ "${reuse_cache_artifacts:-0}" -ne 0 ]]; then
        sudo rm -rf "cache/${product_name?}/"*"/${recipe_name?}"
        if [[ -f "${artifact_name}" ]]; then
            bsdtar -xvf "${artifact_name}"
        else
            echo >&2 "Could not use cache artifact because could not find \"${artifact_name}\" file. Proceeding..."
        fi
    fi

    cosmk build "${product_name:?}/${recipe_name:?}"

    if [[ "${produce_cache_artifacts:-0}" -ne 0 ]]; then
        mkdir -p artifacts/cache
        sudo bsdtar -cvpf "artifacts/cache/${artifact_name}" \
            "cache/${product_name?}/"*"/${recipe_name?}"
        sudo chown "$UID:${GROUPS[0]}" "artifacts/cache/${artifact_name}"
    fi

    cosmk image "${product_name:?}/${recipe_name:?}"
    cosmk configure "${product_name:?}/${recipe_name:?}"
}

bundle_recipe() {
    local product_name="${1%/*}"
    local recipe_name="${1#*/}"
    local artifact_name="build:${product_name:?}.${recipe_name:?}.tar"

    cosmk bundle "${product_name:?}/${recipe_name:?}"

    if [[ "${produce_build_artifacts:-0}" -ne 0 ]]; then
        mkdir -p artifacts/build
        sudo bsdtar -cvpf "artifacts/build/${artifact_name}" \
            "out/${product_name?}/"*"/${recipe_name?}/bundle"
        sudo chown "$UID:${GROUPS[0]}" "artifacts/build/${artifact_name}"
    fi
}

build-image-configure-bundle_recipe() {
    build-image-configure_recipe "${1:?}"
    bundle_recipe "${1:?}"
}

# Avoid leaving build results of previous run in out/:
rm -rf out

reuse-or-bootstrap_sdk clipos/sdk
reuse-or-bootstrap_sdk clipos/sdk_debian
build-image-configure-bundle_recipe clipos/core
build-image-configure-bundle_recipe clipos/efiboot
bundle_recipe clipos/qemu

# vim: set ts=4 sts=4 sw=4 et ft=sh:

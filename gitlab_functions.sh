#!/usr/bin/env bash

dk_login() {
    if [ -n "${HUB_USER}" ]; then
        echo "${HUB_TOKEN}" | docker login -u "${HUB_USER}" --password-stdin
    else
        echo >&2 "Error: missing 'HUB_...' protected variables."
        false
    fi
}

dk_logout() {
    docker logout
}

dk_build() {
    local context="$1"
    local dockerfile="$2"
    local one_image="$3"
    shift 3
    # rest: VAR1=value1 VAR2=value2
    context="${context%/}"
    local args=(-f "$context/$dockerfile" --pull -t "$one_image")
    for arg; do
        args[${#args[@]}]="--build-arg=$arg"
    done
    ( set -ex;
      docker build "${args[@]}" "$context" )
}

dk_push() {
    local hub_repo="$1"
    local one_image="$2"
    shift 2
    # rest: tag1 tag2
    for tag; do
        ( set -ex;
          docker tag "$one_image" "$hub_repo:$tag";
          docker push "$hub_repo:$tag" )
    done
}

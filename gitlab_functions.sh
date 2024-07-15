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

dk_curl() {
    local slug="$1"
    local gitlab_token="$2"
    local gitlab_domain="$3"
    local gitlab_project="$4"
    local cron_mode="$5"
    local item="$6"
    date -u -R
    if [ -n "$gitlab_token" ]; then
        echo >&2 "For child repo $slug:"
        if [ -z "$item" ]; then
            curl -X POST -F token="$gitlab_token" -F ref=master -F "variables[CRON_MODE]=$cron_mode" "https://$gitlab_domain/api/v4/projects/$gitlab_project/trigger/pipeline"
        else
            curl -X POST -F token="$gitlab_token" -F ref=master -F "variables[CRON_MODE]=$cron_mode"  -F "variables[ITEM]=$item" "https://$gitlab_domain/api/v4/projects/$gitlab_project/trigger/pipeline"
        fi
    else
        echo >&2 "Error: cannot read api_token_env_var for '$slug'"
        false
    fi
}

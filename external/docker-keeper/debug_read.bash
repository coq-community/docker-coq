#!/bin/bash
# Author: Erik Martin-Dorel, 2024, MIT license
# Script written for debugging purposes and just kept for the record.

message="chore(docker-keeper): nightly; propagate: ()
chore: Update images.yml; docker-keeper: rebuild-all; propagate: mathcomp: rebuild-all
chore: docker-keeper: rebuild-keyword: dev,8.20
Some more text!"

readarray -t lines < <(grep "\(^\|(\| \|;\)docker-keeper)\?:" <<< "$message")
declare -a DOCKER_KEEPER_CMDS

for line in "${lines[@]}"; do
    cmd=$(sed -e 's/^.*docker-keeper)\?: *//g' <<< "$line")
    readarray -t cmds < <(sed -e 's/; \?/\n/g' <<< "$cmd")
    for cmd in "${cmds[@]}"; do
        DOCKER_KEEPER_CMDS[${#DOCKER_KEEPER_CMDS[@]}]="$(sed -e 's/: \?/=/' <<< "$cmd")"
    done
done

printf "'%s' " "${DOCKER_KEEPER_CMDS[@]/#/--}"

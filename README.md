# docker-keeper

This python script is devised to help maintain Docker Hub repositories
of stable and dev (nightly build) Docker images from a YAML-specified,
single-branch GitLab repository - typically created as a fork of the
following repo: <https://gitlab.com/erikmd/docker-keeper-template>.

This script is meant to be run by GitLab CI.

## Syntax

```
keeper.py write-artifacts [OPTION]
    Generate artifacts in the 'generated' directory.
    This requires having file 'images.yml' in the current working directory.
    OPTION can be:
        --minimal (default option, can be omitted)
        --nightly (same as --minimal + nightly-build images)
        --rebuild-all (rebuild all images)
        --rebuild-files FILE (rebuild images with Dockerfile mentioned in FILE)
        --rebuild-tags FILE (rebuild images with tag mentioned in FILE)
        --rebuild-keywords FILE (rebuild images with keyword mentioned in FILE)
        --rebuild-keyword KEYWORD (rebuild images with specified keyword)

keeper.py generate-config
    Print a GitLab CI YAML config to standard output.
    This requires files:
      - generated/build_data_chosen.json
      - generated/remote_tags_to_rm.json

keeper.py --version
    Print the script version.

keeper.py --upstream-version
    Print the upstream version from https://gitlab.com/erikmd/docker-keeper

keeper.py --help
    Print this documentation.
```

## Usage

* Fork <https://gitlab.com/erikmd/docker-keeper-template>.

* Follow the instructions from the [docker-keeper wiki](https://gitlab.com/erikmd/docker-keeper/-/wikis/home#initial-setup).

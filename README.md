# docker-keeper

This python script is devised to help maintain Docker Hub repositories
of stable and dev (nightly build) Docker images from a YAML-specified,
single-branch GitLab repository - typically created as a fork of the
following repo: <https://gitlab.com/erikmd/docker-keeper-template>.

This script is meant to be run by GitLab CI.

This repository is thus [hosted on GitLab](https://gitlab.com/erikmd/docker-keeper), and [mirrored on GitHub](https://github.com/erikmd/docker-keeper) for more visibility.

## Syntax

```
usage: keeper.py [-h] [--version] [--upstream-version]
                 {generate-config,write-artifacts} ...

§ docker-keeper

This python3 script is devised to help maintain Docker Hub repositories of
stable and dev (from webhooks or for nightly builds) Docker images from a
YAML-specified, single-branch Git repository - typically created as a fork of
the following GitLab repo: <https://gitlab.com/erikmd/docker-keeper-template>.
For more details, follow the instructions of the README.md in your own fork.
Note: this script is meant to be run by GitLab CI.

docker-keeper offers customizable propagate strategies (declarative cURL calls)

It supports both single modes given in variable CRON_MODE (and optionally ITEM)
and multiple modes, from CLI as well as from HEAD's commit message, typically:
$ git commit --allow-empty -m "…" -m "docker-keeper: rebuild-all"
$ git commit -m "docker-keeper: propagate: I1: minimal; propagate: I2: nightly"
$ git commit -m "docker-keeper: propagate: ID: rebuild-all"
$ git commit -m "docker-keeper: propagate: ID: rebuild-keyword: KW1,KW2"
$ git commit -m "docker-keeper: propagate: ()"
If the commit message (or equivalently, the CLI) contains propagate…,
then it overrides the automatic default propagation.
If the commit is rebuilt with the same SHA1 in a given branch,
then it switches to the default behavior (automatic propagate strategy).

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --upstream-version    show program's upstream version from
                        https://gitlab.com/erikmd/docker-keeper and exit

subcommands:
  {generate-config,write-artifacts}
    generate-config     Print a GitLab CI YAML config to standard output. This
                        requires files: {generated/build_data_chosen.json,
                        generated/remote_tags_to_rm.json}
    write-artifacts     Generate artifacts in the 'generated' directory. This
                        requires having file 'images.yml' in the current
                        working directory.
```
&
```
usage: keeper.py write-artifacts [-h] [--debug] [--minimal] [--nightly]
                                 [--rebuild-all] [--rebuild-files FILE]
                                 [--rebuild-tags FILE]
                                 [--rebuild-keywords FILE]
                                 [--rebuild-file NAME1,NAME2]
                                 [--rebuild-tag TAG1,TAG2]
                                 [--rebuild-keyword KW1,KW2]
                                 [--propagate 'CHILD-REPO: COMMAND']

Generate artifacts in the 'generated' directory. This requires having file
'images.yml' in the current working directory.

options:
  -h, --help            show this help message and exit
  --debug               help debugging by printing more info (especially
                        regarding argparse)
  --minimal             default option, can be omitted, kept for backward
                        compatibility
  --nightly             trigger builds that have the 'nightly: true' flag
  --rebuild-all         rebuild all images
  --rebuild-files FILE  (deprecated) rebuild images with Dockerfile mentioned
                        in FILE (can be supplied several times)
  --rebuild-tags FILE   (deprecated) rebuild images with tag mentioned in FILE
                        (can be supplied several times)
  --rebuild-keywords FILE
                        (deprecated) rebuild images with keyword mentioned in
                        FILE (can be supplied several times)
  --rebuild-file NAME1,NAME2
                        rebuild images with Dockerfile mentioned in CLI comma-
                        separated list (can be supplied several times)
  --rebuild-tag TAG1,TAG2
                        rebuild images with tag mentioned in CLI comma-
                        separated list (can be supplied several times)
  --rebuild-keyword KW1,KW2
                        rebuild images with keyword mentioned in CLI comma-
                        separated list (can be supplied several times)
  --propagate 'CHILD-REPO: COMMAND'
                        manually specify to propagate 'minimal', 'nightly',
                        'rebuild-all', or 'rebuild-keyword: KW1,KW2' commands
                        to children docker-keeper repositories; note that you
                        can use '--propagate=()' to disable propagation fully,
                        independently of the other occurrences of this option;
                        if there is no occurrence of this option (in CLI nor
                        in HEAD's commit message), docker-keeper will apply
                        the propagate strategy defined in the images.yml file
                        (can be supplied several times)
```
&
```
usage: keeper.py generate-config [-h]

Print a GitLab CI YAML config to standard output. This requires files:
{generated/build_data_chosen.json, generated/remote_tags_to_rm.json}

options:
  -h, --help  show this help message and exit
```

## Usage

* Fork <https://gitlab.com/erikmd/docker-keeper-template>.

* Follow the instructions from the [docker-keeper wiki](https://gitlab.com/erikmd/docker-keeper/-/wikis/home#initial-setup).

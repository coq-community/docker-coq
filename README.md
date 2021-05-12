# coqorg/coq

[![tags](https://img.shields.io/badge/tags%20on-docker%20hub-blue.svg)](https://hub.docker.com/r/coqorg/coq#supported-tags "Supported tags on Docker Hub")
[![pipeline status](https://gitlab.com/coq-community/docker-coq/badges/master/pipeline.svg)](https://gitlab.com/coq-community/docker-coq/-/pipelines)
[![dev image](https://img.shields.io/badge/coqorg%2Fcoq-dev-blue.svg)](https://hub.docker.com/r/coqorg/coq/tags?page=1&name=dev "See dev image on Docker Hub")
[![pulls](https://img.shields.io/docker/pulls/coqorg/coq.svg)](https://hub.docker.com/r/coqorg/coq "Number of pulls from Docker Hub")
[![stars](https://img.shields.io/docker/stars/coqorg/coq.svg)](https://hub.docker.com/r/coqorg/coq "Star the image on Docker Hub")  
[![dockerfile](https://img.shields.io/badge/dockerfile%20on-github-blue.svg)](https://github.com/coq-community/docker-coq "Dockerfile source repository")
[![base](https://img.shields.io/badge/depends%20on-coqorg%2Fbase-blue.svg)](https://hub.docker.com/r/coqorg/base "Docker base image for Coq")

This repository provides [Docker](https://www.docker.com/) images of the [Coq](https://github.com/coq/coq) proof assistant.

These images are based on [this parent image](https://hub.docker.com/r/coqorg/base/), itself based on [Debian 10 Slim](https://hub.docker.com/_/debian/) and relying on [opam 2.0](https://opam.ocaml.org/doc/Manual.html):

|   | GitHub repo                                                             | Type          | Docker Hub                                             |
|---|-------------------------------------------------------------------------|---------------|--------------------------------------------------------|
|   | [docker-coq-action](https://github.com/coq-community/docker-coq-action) | GitHub action | N/A                                                    |
| x | [docker-coq](https://github.com/coq-community/docker-coq)               | Dockerfile    | [`coqorg/coq`](https://hub.docker.com/r/coqorg/coq/)   |
| ↳ | [docker-base](https://github.com/coq-community/docker-base)             | Dockerfile    | [`coqorg/base`](https://hub.docker.com/r/coqorg/base/) |
| ↳ | Debian                                                                  | Linux distro  | [`debian`](https://hub.docker.com/_/debian/)           |

See also the [docker-coq wiki](https://github.com/coq-community/docker-coq/wiki) for details about how to use these images.

This Dockerfile repository is [mirrored on GitLab](https://gitlab.com/coq-community/docker-coq), but [issues](https://github.com/coq-community/docker-coq/issues) and [pull requests](https://github.com/coq-community/docker-coq/pulls) are tracked on GitHub.

<!-- tags -->

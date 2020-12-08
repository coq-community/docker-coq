#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020  Érik Martin-Dorel
#
# Contributed under the terms of the MIT license,
# cf. <https://spdx.org/licenses/MIT.html>

from bash_formatter import BashLike
from datetime import datetime
import base64
import copy
import json
import requests
import os
import sys
import time
import yaml

debug = False
output_directory = 'generated'
images_filename = 'images.yml'
json_indent = 2
upstream_project = 'erikmd/docker-keeper'
upstream_url = 'https://gitlab.com/%s' % upstream_project


def print_stderr(message):
    print(message, file=sys.stderr, flush=True)


def dump(data):
    """Debug"""
    print_stderr(json.dumps(data, indent=json_indent))


# def error(msg, flush=True):
#     print(msg, file=sys.stderr, flush=flush)
#     exit(1)

class Error(Exception):
    """Base class for exceptions in this module."""
    pass


def error(msg):
    raise Error(msg)


def uniqify(s):
    """Remove duplicates and sort the result list."""
    return sorted(set(s))


def diff_list(l1, l2):
    """Compute the set-difference (l1 - l2), preserving duplicates."""
    return list(filter(lambda e: e not in l2, l1))


def meet_list(l1, l2):
    """Return the sublist of l1, intersecting l2."""
    return list(filter(lambda e: e in l2, l1))


def subset_list(l1, l2):
    """Check if l1 is included in l2."""
    return not diff_list(l1, l2)


def is_unique(s):
    """Check if the list s has no duplicate."""
    return len(s) == len(set(s))


def merge_dict(a, b):
    """Merge the fields of a and b, the latter overriding the former."""
    res = copy.deepcopy(a) if a else {}
    copyb = copy.deepcopy(b) if b else {}
    for key in copyb:
        res[key] = copyb[key]
    return res


def check_string(value, ident=None):
    if not isinstance(value, str):
        if ident:
            error("Error: expecting a string value, but was given '%s: %s'."
                  % (ident, value))
        else:
            error("Error: expecting a string value, but was given '%s'."
                  % value)


def check_list(value, text=None):
    if not isinstance(value, list):
        if not text:
            text = str(value)
        error("Error: not (JSON) list\nText: %s"
              % text)


def eval_bashlike(template, matrix, defaults=None):
    b = BashLike()
    return b.format(template, matrix=matrix, defaults=defaults)


def get_build_date():
    """ISO 8601 UTC timestamp"""
    return datetime.utcnow().strftime("%FT%TZ")


def naive_url_encode(name):
    """https://gitlab.com/help/api/README.md#namespaced-path-encoding"""
    check_string(name)
    return name.replace('/', '%2F')


def gitlab_lambda_query_sha1(response):
    """Return the "commit.id" field from 'response.json()'."""
    return response.json()['commit']['id']


def lambda_query_text(response):
    return response.text


def get_url(url, headers=None, params=None, lambda_query=(lambda r: r)):
    """Some examples of lambda_query:

        - gitlab_lambda_query_sha1
        - lambda_query_text
    """
    print_stderr('GET %s\n' % url)
    response = requests.get(url, headers=headers, params=params)
    if not response:
        error("Error!\nCode: %d\nText: %s"
              % (response.status_code, response.text))
    return lambda_query(response)


def get_commit(commit_api):
    """Get GitHub or GitLab SHA1 of a given branch."""
    fetcher = commit_api['fetcher']
    repo = commit_api['repo']
    branch = commit_api['branch']
    if fetcher == 'github':
        url = 'https://api.github.com/repos/%s/commits/%s' % (repo, branch)
        headers = {"Accept": "application/vnd.github.v3.sha"}
        lambda_query = lambda_query_text
    elif fetcher == 'gitlab':
        # https://gitlab.com/help/api/branches.md#get-single-repository-branch
        url = ('https://gitlab.com/api/v4/projects/%s/repository/branches/%s'
               % (naive_url_encode(repo), naive_url_encode(branch)))
        headers = None
        lambda_query = gitlab_lambda_query_sha1
    else:
        error("Error: do not support 'fetcher: %s'" % fetcher)
    return get_url(url, headers, None, lambda_query)


def load_spec():
    """Parse the YAML file and return a dict."""
    print_stderr("Loading '%s'..." % images_filename)
    with open(images_filename) as f:
        j = yaml.safe_load(f)
    if 'active' not in j or not j['active']:
        print_stderr("""
WARNING: the 'docker-keeper' tasks are not yet active.
Please update your %s specification and Dockerfile templates.
Then, set the option 'active: true' in the %s file."""
                     % (images_filename, images_filename))
        exit(1)
    return j


def product_build_matrix(matrix):
    """Get the list of dicts grouping 1 item per list mapped to matrix keys."""
    assert matrix
    old = [{}]
    res = []
    for key in matrix:
        for value in matrix[key]:
            for e in old:
                enew = copy.deepcopy(e)
                enew[key] = value
                res.append(enew)
        old = res
        res = []
    return old


def check_trim_relative_path(path):
    """Fail if path is absolute and remove leading './'."""
    check_string(path)
    if path[0] == '/':
        error("Error: expecting a relative path, but was given '%s'." % path)
    elif path[:2] == './':
        return path[2:]
    else:
        return path


def check_filename(filename):
    check_string(filename)
    if '/' in filename:
        error("Error: expecting a filename, but was given '%s'." % filename)


def eval_if(raw_condition, matrix):
    """Evaluate YAML condition.

    Supported forms:
        '{matrix[key]} == "string"'
        '{matrix[key]} != "string"'
        '"{matrix[key]}" == "string"'
        '"{matrix[key]}" != "string"'
    """
    # Conjunction
    if isinstance(raw_condition, list):
        for item_condition in raw_condition:
            e = eval_if(item_condition, matrix)
            if not e:
                return False
        return True
    elif raw_condition is None:
        return True

    check_string(raw_condition)
    equality = (raw_condition.find("==") > -1)
    inequality = (raw_condition.find("!=") > -1)
    if equality:
        args = raw_condition.split("==")
    elif inequality:
        args = raw_condition.split("!=")
    else:
        error("Unsupported condition: '%s'." % raw_condition)
    if len(args) != 2:
        error("Wrong number of arguments: '%s'." % raw_condition)
    a = eval_bashlike(args[0].strip().replace('"', ''), matrix)
    b = eval_bashlike(args[1].strip().replace('"', ''), matrix)
    if equality:
        return a == b
    else:
        return a != b


def get_list_dict_dockerfile_matrix_tags_args(json):
    """Get list of dicts containing the following keys:
       - "context": "…"
       - "dockerfile": "…/Dockerfile"
       - "path": "…/…/Dockerfile"
       - "matrix": […]
       - "tags": […]
       - "args": […]
       - "keywords": […]
       - "after_deploy_script": […]
    """
    # TODO later-on: fix (dockerfile / path) semantics
    res = []
    images = json['images']
    for item in images:
        list_matrix = product_build_matrix(item['matrix'])
        if 'dockerfile' in item['build']:
            dfile = check_trim_relative_path(item['build']['dockerfile'])
        else:
            dfile = 'Dockerfile'
        context = check_trim_relative_path(item['build']['context'])
        path = '%s/%s' % (context, dfile)
        raw_tags = item['build']['tags']
        args1 = json['args'] if 'args' in json else {}
        args2 = item['build']['args'] if 'args' in item['build'] else {}
        raw_args = merge_dict(args1, args2)
        if 'keywords' in item['build']:
            raw_keywords = item['build']['keywords']
        else:
            raw_keywords = []
        if 'after_deploy' in item['build']:
            raw_after_deploy = item['build']['after_deploy']
            # support both
            #   after_deploy: 'code'
            # and
            #   after_deploy:
            #     - 'code'
            # as well as
            #   after_deploy:
            #     - script: 'code'
            #       if: '{matrix[base]} == 4.07.1-flambda'
            if isinstance(raw_after_deploy, str):
                raw_after_deploy = [raw_after_deploy]
        else:
            raw_after_deploy = []
        for matrix in list_matrix:
            tags = []
            for tag_item in raw_tags:
                tag_template = tag_item['tag']
                tag_cond = tag_item['if'] if 'if' in tag_item else None
                if eval_if(tag_cond, matrix):
                    # otherwise skip the tag synonym
                    tag = eval_bashlike(tag_template, matrix)  # & defaults ?
                    tags.append(tag)
            defaults = {"build_date": get_build_date()}
            if 'commit_api' in item['build']:
                commit_api = item['build']['commit_api']
                defaults['commit'] = get_commit(commit_api)
            args = {}
            for arg_key in raw_args:
                arg_template = raw_args[arg_key]
                args[arg_key] = eval_bashlike(arg_template, matrix, defaults)
            keywords = list(map(lambda k: eval_bashlike(k, matrix, defaults),
                                raw_keywords))
            after_deploy_script = []
            for ad_item in raw_after_deploy:
                if isinstance(ad_item, str):
                    after_deploy_script.append(ad_item)  # no { } interpolation
                    # otherwise sth like ${BASH_VARIABLE} would raise an error
                else:
                    script_item = ad_item['script']
                    script_cond = ad_item['if'] if 'if' in ad_item else None
                    if eval_if(script_cond, matrix):
                        # otherwise skip the script item
                        after_deploy_script.append(script_item)
            newitem = {"context": context, "dockerfile": dfile,
                       "path": path,
                       "matrix": matrix, "tags": tags, "args": args,
                       "keywords": keywords,
                       "after_deploy_script": after_deploy_script}
            res.append(newitem)
    if debug:
        dump(res)
    return res


def gitlab_build_params_pagination(page, per_page):
    """https://docs.gitlab.com/ce/api/README.html#pagination"""
    return {
        'page': str(page),
        'per_page': str(per_page)
    }


def hub_build_params_pagination(page, per_page):
    return {
        'page': str(page),
        'page_size': str(per_page)
    }


def hub_lambda_list(j):
    """https://registry.hub.docker.com/v2/repositories/library/debian/tags"""
    return list(map(lambda e: e['name'], j['results']))


def get_list_paginated(url, headers, params, lambda_list, max_per_sec=5):
    """Generic wrapper to handle GET requests with pagination.

    If the response is a JSON list, use lambda_list=(lambda l: l).

    REM: for https://registry.hub.docker.com/v2/repositories/_/_/tags,
    one could use the "next" field to guess the following page."""
    assert isinstance(max_per_sec, int)
    assert max_per_sec > 0
    assert max_per_sec <= 10
    per_page = 50  # max allowed (by gitlab.com & hub.docker.com): 100
    page = 0
    allj = []
    while(True):
        page += 1
        if page % max_per_sec == 0:
            time.sleep(1.1)
        page_params = hub_build_params_pagination(page, per_page)
        all_params = merge_dict(params, page_params)
        print("GET %s\n  # page: %d"
              % (url, page), file=sys.stderr, flush=True)
        response = requests.get(url, headers=headers, params=all_params)
        if not response:
            error("Error!\nCode: %d\nText: %s"
                  % (response.status_code, response.text))
        j = lambda_list(response.json())
        check_list(j, text=response.text)
        if j:
            allj += j
        else:
            break
    return allj


def get_remote_tags(spec):
    repo = spec['docker_repo']
    check_string(repo)
    return get_list_paginated(
        'https://registry.hub.docker.com/v2/repositories/%s/tags' % repo,
        None, None, hub_lambda_list)


def minimal_rebuild(build_tags, remote_tags):
    def pred(item):
        return not subset_list(item['tags'], remote_tags)
    return list(filter(pred, build_tags))


def to_rm(all_tags, remote_tags):
    return diff_list(remote_tags, all_tags)


def get_script_directory():
    """$(cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd) in Python."""
    return os.path.dirname(__file__)


def mkdir_dirname(filename):
    """Python3 equivalent to 'mkdir -p $(dirname $filename)"'."""
    os.makedirs(os.path.dirname(filename), mode=0o755, exist_ok=True)


def fullpath(filename):
    """Get path of filename in output_directory/."""
    return os.path.join(output_directory, filename)


def write_json_artifact(j, basename):
    filename = fullpath(basename)
    print_stderr("Generating '%s'..." % filename)
    mkdir_dirname(filename)
    with open(filename, 'w') as f:
        json.dump(j, f, indent=json_indent)


def write_text_artifact(text, basename):
    filename = fullpath(basename)
    print_stderr("Generating '%s'..." % filename)
    mkdir_dirname(filename)
    with open(filename, 'w') as f:
        f.write(text)


def write_list_text_artifact(seq, basename):
    check_list(seq)
    write_text_artifact('\n'.join(seq) + '\n', basename)


def write_build_data_all(build_data_all):
    write_json_artifact(build_data_all, 'build_data_all.json')


def write_build_data_chosen(build_data):
    write_json_artifact(build_data, 'build_data_chosen.json')


def write_build_data_min(build_data_min):
    write_json_artifact(build_data_min, 'build_data_min.json')


def write_remote_tags(remote_tags):
    write_list_text_artifact(remote_tags, 'remote_tags.txt')


def write_remote_tags_to_rm(remote_tags_to_rm):
    write_json_artifact(remote_tags_to_rm, 'remote_tags_to_rm.json')


def write_list_dockerfile(seq):
    """To be used on the value of get_list_dict_dockerfile_matrix_tags_args."""
    dockerfiles = uniqify(map(lambda e: e['path'], seq))
    write_list_text_artifact(dockerfiles, 'Dockerfiles.txt')


def write_docker_repo(spec):
    repo = spec['docker_repo'] + '\n'
    write_text_artifact(repo, 'docker_repo.txt')


def read_json_artifact(basename):
    filename = fullpath(basename)
    print_stderr("Reading '%s'..." % filename)
    with open(filename, 'r') as json_data:
        j = json.load(json_data)
    return j


def read_build_data_chosen():
    return read_json_artifact('build_data_chosen.json')


def write_readme(base_url, build_data):
    """Read README.md and replace <!-- tags --> with a list of images

    with https://gitlab.com/foo/bar/blob/master/Dockerfile hyperlinks.
    """
    pattern = '<!-- tags -->'
    check_string(base_url)
    if base_url[-1] == '/':
        base_url = base_url[:-1]

    def readme_image(item):
        return '-	[`{tags}`]({url})'.format(
            tags=('`, `'.join(item['tags'])),
            url=('%s/blob/master/%s' % (base_url, item['path'])))

    print_stderr("Reading the template 'README.md'...")
    with open('README.md', 'r') as f:
        template = f.read()

    tags = ('# <a name="supported-tags"></a>'
            'Supported tags and respective `Dockerfile` links\n\n%s'
            % '\n'.join(map(readme_image, build_data)))

    readme = template.replace(pattern, tags)

    filename = fullpath('README.md')
    print_stderr("Generating '%s'..." % filename)
    mkdir_dirname(filename)
    with open(filename, 'w') as f:
        f.write(readme)


def get_check_tags(seq):
    """To be used on the value of get_list_dict_dockerfile_matrix_tags_args."""
    res = []
    for e in seq:
        res.extend(e['tags'])
    if is_unique(res):
        print_stderr("OK: no duplicate tag found.")
    else:
        error("Error: there are some tags duplicates.")
    return res


def merge_data(l1, l2):
    """Append to l1 the elements of l2 that do not belong to l1."""
    extra = diff_list(l2, l1)
    return l1 + extra


def get_nightly_only(spec):
    spec2 = copy.deepcopy(spec)
    images = spec2.pop('images')

    def nightly(item):
        return 'nightly' in item['build'] and item['build']['nightly']

    images2 = list(filter(nightly, images))
    spec2['images'] = images2
    return get_list_dict_dockerfile_matrix_tags_args(spec2)


def print_list(title, seq):
    print(title + ':' + ''.join(map(lambda e: '\n- ' + e, seq)))


def get_files_only(build_data_all, items_filename):
    with open(items_filename, 'r') as fh:
        dockerfiles = [item.strip() for item in fh.readlines()]

    print_list('Specified Dockerfiles:', dockerfiles)

    # TODO later-on: fix (dockerfile / path) semantics
    def matching(item):
        return item['path'] in dockerfiles

    return list(filter(matching, build_data_all))


def get_tags_only(build_data_all, items_filename):
    with open(items_filename, 'r') as fh:
        tags = [item.strip() for item in fh.readlines()]

    print_list('Specified tags:', tags)

    def matching(item):
        return meet_list(item['tags'], tags)

    return list(filter(matching, build_data_all))


def get_keywords_only(build_data_all, items_filename):
    with open(items_filename, 'r') as fh:
        tags = [item.strip() for item in fh.readlines()]

    print_list('Specified keywords:', tags)

    def matching(item):
        return meet_list(item['keywords'], tags)

    return list(filter(matching, build_data_all))


def get_keyword_only(build_data_all, keyword):
    print('Specified keyword: %s' % keyword)

    def matching(item):
        return keyword in item['keywords']

    return list(filter(matching, build_data_all))


def get_version():
    with open(os.path.join(get_script_directory(), 'VERSION'), 'r') as f:
        version = f.read().strip()
    return version


def get_upstream_version():
    url = ('https://gitlab.com/api/v4/projects/%s/repository/files/VERSION'
           % naive_url_encode(upstream_project))

    def lambda_query_content(response):
        return (base64.b64decode(response.json()['content'])
                .decode('UTF-8').rstrip())

    return get_url(url, None, {"ref": "master"}, lambda_query_content)


def equalize_args(record):
    """{"VAR1": "value1", "VAR2": "value2"} → ['VAR1=value1', 'VAR2=value2']"""
    res = []
    for key in record:
        res.append("%s=%s" % (key, record[key]))
    return res


def first_shortest_tag(list_tags):
    return sorted(list_tags, key=(lambda s: (len(s), s)))[0]


def indent_script(list_after_deploy, indent_level, start=False):
    check_list(list_after_deploy)
    if list_after_deploy:
        indent = " " * indent_level
        if start:
            return indent + ('\n' + indent).join(list_after_deploy)
        else:
            return ('\n' + indent).join(list_after_deploy)
    else:
        return ""


def escape_single_quotes(script):
    return script.replace("'", "'\\''")


def generate_config(docker_repo):
    data = read_build_data_chosen()

    if not data:
        return """---
# GitLab CI config automatically generated by docker-keeper; do not edit.
# yamllint disable rule:line-length rule:empty-lines

stages:
  - build

noop:
  stage: build
  image: alpine:latest
  variables:
    GIT_STRATEGY: none
  script:
    - echo "No image to rebuild."
  only:
    - master
"""

    yamlstr_init = """---
# GitLab CI config automatically generated by docker-keeper; do not edit.
# yamllint disable rule:line-length rule:empty-lines

stages:
  - deploy
  - remove

# Changes below (or jobs extending .docker-deploy) should be carefully
# reviewed to avoid leaks of HUB_TOKEN
.docker-deploy:
  stage: deploy
  only:
    - master
  variables:
    HUB_REPO: "{var_hub_repo}"
    # HUB_USER: # protected variable
    # HUB_TOKEN: # protected variable
    # FOO_TOKEN: # other, user-defined tokens for after_deploy_script
  image: docker:latest
  services:
    - docker:dind
  before_script:
    - cat /proc/cpuinfo /proc/meminfo
    - echo $0
    - apk add --no-cache bash
    - /usr/bin/env bash --version
    - apk add --no-cache curl
    - curl --version
    - pwd

{var_jobs}"""

    yamlstr_jobs = ''
    job_id = 0
    for item in data:
        job_id += 1
        yamlstr_jobs += """
deploy_{var_job_id}_{var_some_real_tag}:
  extends: .docker-deploy
  script: |
    /usr/bin/env bash -e -c '
      echo $0
      . "{var_keeper_subtree}/gitlab_functions.sh"
      dk_login
      dk_build "{var_context}" "{var_dockerfile}" "{var_one_tag}" {vars_args}
      dk_push "{var_hub_repo}" "{var_one_tag}" {vars_tags}
      dk_logout
      {var_after_deploy}' bash
""".format(var_context=item['context'],
           var_dockerfile=item['dockerfile'],
           vars_args=('"%s"' % '" "'.join(equalize_args(item['args']))),
           vars_tags=('"%s"' % '" "'.join(item['tags'])),
           var_keeper_subtree=get_script_directory(),
           var_hub_repo=docker_repo,
           var_one_tag=("image_%d" % job_id),
           var_job_id=job_id,
           var_some_real_tag=first_shortest_tag(item['tags']),
           var_after_deploy=escape_single_quotes(
               indent_script(item['after_deploy_script'], 6)))

    return yamlstr_init.format(var_hub_repo=docker_repo,
                               var_jobs=yamlstr_jobs)


def usage():
    print("""# docker-keeper

This python script is devised to help maintain Docker Hub repositories
of stable and dev (nightly build) Docker images from a YAML-specified,
single-branch GitLab repository - typically created as a fork of the
following repo: <https://gitlab.com/erikmd/docker-keeper-template>.

This script is meant to be run by GitLab CI.

## Syntax

```
keeper.py write-artifacts [OPTION]
    Generate artifacts in the '%s' directory.
    This requires having file '%s' in the current working directory.
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
    Print the upstream version from %s

keeper.py --help
    Print this documentation.
```

## Usage

* Fork <https://gitlab.com/erikmd/docker-keeper-template>.

* Follow the instructions of the README.md in your fork."""
          % (output_directory, images_filename, upstream_url))


def main(args):
    if args == ['--version']:
        print(get_version())
        exit(0)
    elif args == ['--upstream-version']:
        print(get_upstream_version())
    elif args == ['generate-config']:
        spec = load_spec()  # could be avoided by writing yet another .json…
        print(generate_config(spec['docker_repo']))
    elif args == ['--help'] or args == []:
        usage()
    elif args[0] == 'write-artifacts':
        spec = load_spec()
        build_data_all = get_list_dict_dockerfile_matrix_tags_args(spec)
        all_tags = get_check_tags(build_data_all)
        remote_tags = get_remote_tags(spec)
        build_data_min = minimal_rebuild(build_data_all, remote_tags)
        remote_tags_to_rm = to_rm(all_tags, remote_tags)
        if args[1:] == [] or args[1:] == ['--minimal']:
            write_build_data_chosen(build_data_min)
        elif args[1:] == ['--rebuild-all']:
            write_build_data_chosen(build_data_all)
        elif args[1:] == ['--nightly']:
            nightly_only = get_nightly_only(spec)
            build_data_nightly = merge_data(build_data_min, nightly_only)
            write_build_data_chosen(build_data_nightly)
        elif args[1] == '--rebuild-files':
            if len(args) != 3:
                print_stderr("Error: "
                             "--rebuild-files expects one argument exactly."
                             "\nWas: %s" % args)
                usage()
                exit(1)
            rebuild_files_only = get_files_only(build_data_all, args[2])
            build_data_files = merge_data(build_data_min, rebuild_files_only)
            write_build_data_chosen(build_data_files)
        elif args[1] == '--rebuild-tags':
            if len(args) != 3:
                print_stderr("Error: "
                             "--rebuild-files expects one argument exactly."
                             "\nWas: %s" % args)
                usage()
                exit(1)
            rebuild_tags_only = get_tags_only(build_data_all, args[2])
            build_data_tags = merge_data(build_data_min, rebuild_tags_only)
            write_build_data_chosen(build_data_tags)
        elif args[1] == '--rebuild-keywords':
            if len(args) != 3:
                print_stderr("Error: "
                             "--rebuild-keywords expects one argument exactly."
                             "\nWas: %s" % args)
                usage()
                exit(1)
            rebuild_keywords_only = get_keywords_only(build_data_all, args[2])
            build_data_tags = merge_data(build_data_min, rebuild_keywords_only)
            write_build_data_chosen(build_data_tags)
        elif args[1] == '--rebuild-keyword':
            if len(args) != 3:
                print_stderr("Error: "
                             "--rebuild-keyword expects one argument exactly."
                             "\nWas: %s" % args)
                usage()
                exit(1)
            rebuild_keywords_only = get_keyword_only(build_data_all, args[2])
            build_data_tags = merge_data(build_data_min, rebuild_keywords_only)
            write_build_data_chosen(build_data_tags)
        else:
            print_stderr("Error: wrong arguments.\nWas: %s" % args)
            usage()
            exit(1)
        write_build_data_all(build_data_all)
        write_build_data_min(build_data_min)
        write_remote_tags(remote_tags)
        write_remote_tags_to_rm(remote_tags_to_rm)
        write_list_dockerfile(build_data_all)
        write_readme(spec['base_url'], build_data_all)
        write_docker_repo(spec)
    else:
        print_stderr("Error: wrong arguments.\nWas: %s" % args)
        usage()
        exit(1)


###############################################################################
# Test suite, cf. <https://docs.python-guide.org/writing/tests/>
# $ pip3 install pytest
# $ py.test bash_formatter.py

def test_get_commit():
    github = {"fetcher": "github", "repo": "coq/coq", "branch": "v8.0"}
    github_expected = "6aecb9a1fe3f9b027dfd702931298bc61d40b6d3"
    github_actual = get_commit(github)
    assert github_actual == github_expected
    gitlab = {"fetcher": "gitlab", "repo": "coq/coq", "branch": "v8.0"}
    gitlab_expected = "6aecb9a1fe3f9b027dfd702931298bc61d40b6d3"
    gitlab_actual = get_commit(gitlab)
    assert gitlab_actual == gitlab_expected


def shouldfail(lam):
    try:
        res = lam()
        print_stderr("Wrong outcome: '%s'" % res)
        assert False
    except Error:
        print_stderr('OK')


def test_check_trim_relative_path():
    assert check_trim_relative_path('.') == '.'
    assert check_trim_relative_path('./foo/bar') == 'foo/bar'
    assert check_trim_relative_path('bar/baz') == 'bar/baz'
    shouldfail(lambda: check_trim_relative_path('/etc'))


def test_eval_if():
    matrix1 = {"base": "latest", "coq": "dev"}
    matrix2 = {"base": "4.09.0-flambda", "coq": "dev"}
    assert eval_if('{matrix[base]}=="latest"', matrix1)
    assert eval_if('{matrix[base]} == "latest"', matrix1)
    assert eval_if(' "{matrix[base]}" == "latest"', matrix1)
    assert eval_if('{matrix[base]}!="latest"', matrix2)
    assert eval_if('{matrix[base]} != "latest"', matrix2)
    assert eval_if(' "{matrix[base]}" != "latest"', matrix2)


def test_is_unique():
    s = [1, 2, 4, 0, 4]
    assert not is_unique(s)
    s = uniqify(s)
    assert is_unique(s)


def test_uniqify():
    assert uniqify([1, 2, 4, 0, 4]) == [0, 1, 2, 4]


def test_merge_dict():
    foo = {'a': 1, 'c': 2}
    bar = {'b': 3, 'c': 4}
    foobar = merge_dict(foo, bar)
    assert foobar == {'a': 1, 'b': 3, 'c': 4}


def test_diff_list():
    l1 = [1, 2, 4, 2, 5, 4]
    l2 = [3, 1, 2]
    assert diff_list(l1, l2) == [4, 5, 4]


def test_subset_list():
    l2 = [2, 3]
    l1 = [2]
    l0 = [3, 4, 5]
    l3 = [2, 3, 5]
    assert subset_list(l2, l3)
    assert not subset_list(l2, l1)
    assert not subset_list(l2, l0)


def test_equalize_args():
    assert (equalize_args({"VAR1": "value1", "VAR2": "value2"}) ==
            ['VAR1=value1', 'VAR2=value2'])


def test_merge_data():
    l1 = [{"i": 1, "s": "a"}, {"i": 2, "s": "b"}, {"i": 1, "s": "a"}]
    l2 = [{"i": 2, "s": "b"}, {"i": 2, "s": "b"}, {"i": 3, "s": "c"}]
    res1 = merge_data(l1, l2)
    assert res1 == [{"i": 1, "s": "a"}, {"i": 2, "s": "b"}, {"i": 1, "s": "a"},
                    {"i": 3, "s": "c"}]
    res2 = merge_data(l2, l1)
    assert res2 == [{"i": 2, "s": "b"}, {"i": 2, "s": "b"}, {"i": 3, "s": "c"},
                    {"i": 1, "s": "a"}, {"i": 1, "s": "a"}]


def test_meet_list():
    assert not meet_list([1, 2], [])
    assert not meet_list([], [2, 3])
    assert not meet_list([1, 2], [3])
    assert meet_list([1, 2], [2, 3])


def test_first_shortest_tag():
    assert first_shortest_tag(['BB', 'AA', 'z', 'y']) == 'y'


def test_indent_script():
    assert indent_script(['echo ok', 'echo "The End"'], 6, True) == \
        '      echo ok\n      echo "The End"'
    assert indent_script(['echo ok', 'echo "The End"'], 6) == \
        'echo ok\n      echo "The End"'


if __name__ == "__main__":
    main(sys.argv[1:])

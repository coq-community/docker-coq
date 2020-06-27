#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020  Érik Martin-Dorel
#
# Contributed under the terms of the MIT license,
# cf. <https://spdx.org/licenses/MIT.html>

from bash_formatter import BashLike
from datetime import datetime
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
    """Remove duplicates, without preserving the elements order."""
    return list(set(s))


def diff_list(l1, l2):
    """Compute the set-difference (l1 - l2), preserving duplicates."""
    return list(filter(lambda e: e not in l2, l1))


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


def get_url(url, headers=None, query=None):
    """Argument query can be 'commit.id'."""
    print_stderr('GET %s\n' % url)
    response = requests.get(url, headers=headers, params=None)
    if not response:
        error("Error!\nCode: %d\nText: %s"
              % (response.status_code, response.text))
    if not query:
        return response.text
    else:
        response = response.json()
        jpath = query.split('.')
        for step in jpath:
            response = response[step]
        return response


def get_commit(commit_api):
    """Get GitHub or GitLab SHA1 of a given branch."""
    fetcher = commit_api['fetcher']
    repo = commit_api['repo']
    branch = commit_api['branch']
    if fetcher == 'github':
        url = 'https://api.github.com/repos/%s/commits/%s' % (repo, branch)
        headers = {"Accept": "application/vnd.github.v3.sha"}
        query = None
    elif fetcher == 'gitlab':
        # https://gitlab.com/help/api/branches.md#get-single-repository-branch
        url = ('https://gitlab.com/api/v4/projects/%s/repository/branches/%s'
               % (naive_url_encode(repo), naive_url_encode(branch)))
        headers = None
        query = 'commit.id'
    else:
        error("Error: do not support 'fetcher: %s'" % fetcher)
    return get_url(url, headers, query)


def load_spec():
    """Parse the YAML file and return a dict."""
    print_stderr("Loading '%s'..." % images_filename)
    with open(images_filename) as f:
        j = yaml.safe_load(f)
    if not 'active' in j or not j['active']:
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
    """Get [{"path": "Dockerfile", "matrix": …, "tags": …, "args": …}, …]."""
    res = []
    images = json['images']
    for item in images:
        list_matrix = product_build_matrix(item['matrix'])
        if 'dockerfile' in item['build']:
            dfile = check_trim_relative_path(item['build']['dockerfile'])
        else:
            dfile = 'Dockerfile'
        ctxt = check_trim_relative_path(item['build']['context'])
        dockerfile = '%s/%s' % (ctxt, dfile)
        raw_tags = item['build']['tags']
        raw_args = merge_dict(json['args'], item['build']['args'])
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
            newitem = {"path": dockerfile, "matrix": matrix,
                       "tags": tags, "args": args}
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
        if not isinstance(j, list):
            error("Error: not JSON list\nText: %s"
                  % response.text)
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


def write_build_data(build_data):
    write_json_artifact(build_data, 'build_data.json')


def write_build_data_min(build_data_min):
    write_json_artifact(build_data_min, 'build_data_min.json')


def write_remote_tags(remote_tags):
    write_json_artifact(remote_tags, 'remote_tags.json')


def write_remote_tags_to_rm(remote_tags_to_rm):
    write_json_artifact(remote_tags_to_rm, 'remote_tags_to_rm.json')


def write_list_dockerfile(seq):
    """To be used on the value of get_list_dict_dockerfile_matrix_tags_args."""
    dockerfiles = uniqify(map(lambda e: e['path'], seq))
    write_json_artifact(dockerfiles, 'Dockerfiles.json')


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

    tags = ('# Supported tags and respective `Dockerfile` links\n\n%s'
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


def usage():
    print("""# docker-keeper

This python script is devised to help maintain Docker Hub repositories
of stable and dev (nightly build) Docker images from a YAML-specified,
single-branch GitLab repository - typically created as a fork of the
following repo: <https://gitlab.com/erikmd/docker-keeper-template>.

This script is meant to be run by GitLab CI.

## Syntax

```
keeper.py write-artifacts
    Generate artifacts in the '%s' directory.
    This requires having file '%s' in the current working directory.

keeper.py --version
    Print the script version.

keeper.py --help
    Print this documentation.
```

## Usage

* Fork <https://gitlab.com/erikmd/docker-keeper-template>.

* Follow the instructions of the README.md in your fork."""
          % (output_directory, images_filename))


def main(args):
    if args == ['--version']:
        filedir = os.path.dirname(__file__)
        with open(os.path.join(filedir, 'VERSION'), 'r') as f:
            version = f.read().strip()
        print(version)
        exit(0)
    # elif args == ['--remote-version']:
    elif args == ['write-artifacts']:
        spec = load_spec()
        build_data = get_list_dict_dockerfile_matrix_tags_args(spec)
        all_tags = get_check_tags(build_data)
        remote_tags = get_remote_tags(spec)
        build_data_min = minimal_rebuild(build_data, remote_tags)
        remote_tags_to_rm = to_rm(all_tags, remote_tags)
        write_build_data(build_data)
        write_build_data_min(build_data_min)
        write_remote_tags(remote_tags)
        write_remote_tags_to_rm(remote_tags_to_rm)
        write_list_dockerfile(build_data)
        write_readme(spec['base_url'], build_data)
    else:
        usage()


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


if __name__ == "__main__":
    main(sys.argv[1:])

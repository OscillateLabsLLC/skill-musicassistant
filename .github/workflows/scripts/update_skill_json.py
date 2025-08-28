# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import json
from os.path import expanduser, isdir, isfile, join
from pprint import pprint
from sys import argv


def get_skill_json(skill_dir: str):
    print(f"skill_dir={skill_dir}")
    skill_json = join(skill_dir, "skill.json")
    skill_spec = get_uv_skill_data(skill_dir)
    pprint(skill_spec)
    try:
        with open(skill_json) as f:
            current = json.load(f)
    except Exception as e:
        print(e)
        current = None
    if current != skill_spec:
        print("Skill Updated. Writing skill.json")
        with open(skill_json, "w+") as f:
            json.dump(skill_spec, f, indent=4)
    else:
        print("No changes to skill.json")


def get_uv_skill_data(skill_dir: str):
    skill_data = {
        "skill_id": "skill-musicassistant",
        "source": "https://github.com/oscillatelabsllc/skill-musicassistant",
        "package_name": "skill-musicassistant",
        "pip_spec": "",
        "license": "Apache-2.0",
        "author": "Mike Gray/Oscillate Labs",
        "extra_plugins": {},
        "icon": "",
        "images": [],
        "name": "skill-musicassistant",
        "description": "",
        "examples": [],
        "tags": [],
        "version": "1.0.0",
    }
    from toml import load

    skill_dir = expanduser(skill_dir)
    if not isdir(skill_dir):
        raise FileNotFoundError(f"Not a Directory: {skill_dir}")
    pyproject = join(skill_dir, "pyproject.toml")
    if not isfile(pyproject):
        raise FileNotFoundError(f"Not a Directory: {pyproject}")
    with open(pyproject) as f:
        data = load(f)
    skill_data["package_name"] = data["project"].get("name", "Unknown")
    skill_data["name"] = data["project"].get("name", "Unknown")
    skill_data["description"] = data["project"].get("name", "description")
    skill_data["pip_spec"] = data["project"].get("name", "Unknown")
    skill_data["license"] = data["project"].get("license", "Unknown")
    skill_data["author"] = data["project"].get("authors", [""])
    skill_data["tags"] = data["project"].get("keywords", ["ovos", "neon", "mycroft"])
    skill_data["version"] = data["project"].get("version", [""])
    return skill_data


if __name__ == "__main__":
    get_skill_json(argv[1])

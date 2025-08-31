# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2025 Neongecko.com Inc. and Oscillate Labs LLC
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# Mike Gray
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
from shutil import copy, move
from sys import argv


def get_skill_json(skill_dir: str, lang_code: str = "en-us"):
    print(f"skill_dir={skill_dir}")
    skill_json = join(skill_dir, f"skill_musicassistant/locale/{lang_code}/skill.json")
    skill_spec = get_poetry_skill_data(skill_dir, lang_code)
    pprint(skill_spec)
    try:
        with open(skill_json, encoding="utf-8") as f:
            current = json.load(f)
    except Exception as e:
        print(e)
        current = None
    if current != skill_spec:
        print("Skill updated. Writing skill.json")
        with open(skill_json, "w+", encoding="utf-8") as f:
            json.dump(skill_spec, f, indent=4, ensure_ascii=False)
    else:
        print("No changes to skill.json")
    move(skill_json, skill_json)


def get_poetry_skill_data(skill_dir: str, lang_code: str = "en-us"):
    skill_data = {
        "skill_id": "skill-musicassistant",
        "source": "https://github.com/oscillatelabsllc/skill-musicassistant",
        "package_name": "skill-musicassistant",
        "pip_spec": "git+https://github.com/oscillatelabsllc/skill-musicassistant",
        "license": "Apache-2.0",
        "author": "Mike Gray/Oscillate Labs",
        "extra_plugins": {},
        "icon": "https://www.music-assistant.io/assets/transparent-logo.png",
        "images": [],
        "name": "skill-musicassistant",
        "description": "A skill to control media through Music Assistant. Not compatible with OCP.",
        "examples": [
            "play the artist David Bowie on Living Room speaker",
            "play the track Bohemian Rhapsody on Living Room speaker",
            "play the playlist Party Jams on Living Room speaker",
            "play the playlist Work Jams on Living Room speaker",
            "play the album The Dark Side of the Moon on Living Room speaker",
            "play the album The Wall on Living Room speaker",
            "play the album Abbey Road on Living Room speaker",
            "play the album Thriller on Living Room speaker",
            "play the album Back in Black on Living Room speaker",
            "play the album The Bodyguard on Living Room speaker",
        ],
        "tags": ["ovos", "neon", "musicassistant"],
        "version": "1.0.0",
    }
    from toml import load

    skill_dir = expanduser(skill_dir)
    if not isdir(skill_dir):
        raise FileNotFoundError(f"Not a Directory: {skill_dir}")
    pyproject = join(skill_dir, "pyproject.toml")
    if not isfile(pyproject):
        raise FileNotFoundError(f"Not a Directory: {pyproject}")
    with open(pyproject, encoding="utf-8") as f:
        data = load(f)
    skill_data["package_name"] = data["project"].get("name", "Unknown")
    skill_data["name"] = data["project"].get("name", "Unknown")
    skill_data["description"] = data["project"].get("name", "description")
    skill_data["pip_spec"] = data["project"].get("name", "Unknown")
    skill_data["license"] = data["project"].get("license", "Unknown")
    skill_data["author"] = data["project"].get("authors", [""])
    skill_data["tags"] = data["project"].get("keywords", ["ovos", "neon", "musicassistant"])
    # Instead, read __version__ from skill_musicassistant/version.py
    with open(join(skill_dir, "skill_musicassistant/version.py"), encoding="utf-8") as f:
        data = load(f)
    skill_data["version"] = data["__version__"]
    with open(join(skill_dir, f"skill_musicassistant/locale/{lang_code}/skill.json"), encoding="utf-8") as f:
        skill_json = json.load(f)
        skill_data["examples"] = skill_json.get("examples", [])
    return skill_data


if __name__ == "__main__":
    supported_langs = ["en-us"]
    for lang in supported_langs:
        get_skill_json(argv[1], lang_code=lang)
    copy(f"{argv[1]}/skill_musicassistant/locale/en-us/skill.json", f"{argv[1]}/skill.json")

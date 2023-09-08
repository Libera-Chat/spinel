from dataclasses import dataclass
from os.path     import expanduser
from typing      import List, Tuple

import yaml

@dataclass
class Config(object):
    server:   str
    nickname: str
    username: str
    realname: str
    password: str
    channels: List[str]

    sasl: Tuple[str, str]
    oper: Tuple[str, str]

    banchan_prefix: str
    banchan_count:  int
    banchan_max:    int

    log: str

def load(filepath: str):
    with open(filepath) as file:
        config_yaml = yaml.safe_load(file.read())

    nickname = config_yaml["nickname"]
    oper_name = config_yaml["oper"]["name"]
    oper_file = expanduser(config_yaml["oper"]["file"])
    oper_pass = config_yaml["oper"]["pass"]

    return Config(
        config_yaml["server"],
        nickname,
        config_yaml.get("username", nickname),
        config_yaml.get("realname", nickname),
        config_yaml["password"],
        config_yaml["channels"],
        (config_yaml["sasl"]["username"], config_yaml["sasl"]["password"]),
        (oper_name, oper_file, oper_pass),
        config_yaml["banchan-prefix"],
        config_yaml["banchan-count"],
        config_yaml["banchan-max"],
        config_yaml["log"]
    )

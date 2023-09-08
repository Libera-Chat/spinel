import asyncio
from argparse import ArgumentParser

from ircrobots import ConnectionParams, SASLUserPass

from .       import Bot
from .config import Config, load as config_load

async def async_main(config: Config):
    bot = Bot(config)

    sasl_user, sasl_pass = config.sasl

    autojoin = config.channels.copy()
    for i in range(config.banchan_count):
        num = str(i).zfill(2)
        autojoin.append(f"{config.banchan_prefix}{num}")

    params = ConnectionParams.from_hoststring(config.nickname, config.server)
    params.password = config.password
    params.username = config.username
    params.realname = config.realname
    params.sasl = SASLUserPass(sasl_user, sasl_pass)
    params.autojoin = autojoin

    await bot.add_server("irc", params)
    await bot.run()

def main():
    parser = ArgumentParser()
    parser.add_argument("config")
    args   = parser.parse_args()

    config = config_load(args.config)
    asyncio.run(async_main(config))

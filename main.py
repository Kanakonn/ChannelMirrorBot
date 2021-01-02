import sys

from discord.ext import commands

from mirror_bot import MirrorBot

import utils

# Mappings layout:
# [
#   {"source_channel": "id", "source_guild": "id", "destination_channel": "id", "destination_webhook": "url"}
# ]

DEFAULT_CONFIG = {
    "mappings": [],
    "bot_token": "INSERT_BOT_TOKEN_HERE",
    "prefix": "mb!",
}

if __name__ == '__main__':
    try:
        config = utils.load_config()
    except FileNotFoundError:
        config = DEFAULT_CONFIG.copy()
        utils.save_config(config)

    if 'bot_token' not in config.keys() or config['bot_token'] in ["", "INSERT_BOT_TOKEN_HERE"]:
        config['bot_token'] = "INSERT_BOT_TOKEN_HERE"
        utils.save_config(config)
        print("Please configure the bot_token by modifying the 'config.json' file!", flush=True)
        sys.exit(1)
    bot_token = config['bot_token']

    if 'prefix' not in config.keys() or config['prefix'] == "":
        config['prefix'] = "mb!"
        utils.save_config(config)

    prefix = config['prefix']
    print(f"Bot prefix is '{prefix}'", flush=True)

    client = commands.Bot(command_prefix=commands.when_mentioned_or(prefix))
    client.add_cog(MirrorBot(client=client, config=config))
    client.run(bot_token)

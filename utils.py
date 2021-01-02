import json

import discord


def load_config():
    with open("config.json", "r") as f:
        return json.loads(f.read())


def save_config(config):
    with open("config.json", "w") as f:
        f.write(json.dumps(config, indent=2))


def has_reply():
    # Check if the version of discordpy has the message.reply feature
    v = discord.version_info
    return (v[0] == 1 and v[1] >= 6) or v[0] > 1


def has_manage_server(ctx):
    # Check if the user has manage server permissions.
    return ctx
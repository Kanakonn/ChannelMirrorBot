from datetime import datetime, timedelta
from io import BytesIO
from typing import List

import aiohttp
import discord
from discord.ext import commands, tasks

import utils


class MirrorBot(commands.Cog):
    def __init__(self, client, config, *args, **kwargs):
        super(MirrorBot, self).__init__(*args, **kwargs)
        self.client = client
        self.mirror_config = config
        self.message_cache = {}

    @tasks.loop(minutes=10)
    async def clean_messages(self):
        print("Cleaning message cache...")
        removed = 0
        for msg_id, message in self.message_cache.items():
            if message[0] is not None and (datetime.utcnow() - message[0]) > timedelta(hours=1):
                removed += 1
                del self.message_cache[msg_id]
        print(f"Removed {removed} messages from cache.")

    @commands.Cog.listener()
    async def on_connect(self):
        print(f"Connected, preparing...")

    @commands.Cog.listener()
    async def on_disconnect(self):
        print(f"Bot has disconnected from discord.")

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Bot has logged in as {self.client.user} and is ready!")
        await self.client.change_presence(activity=discord.CustomActivity(name=f"Watching {self.client.command_prefix}"))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.id in self.message_cache:
            for webhook_msg in self.message_cache[message.id][1]:
                try:
                    await webhook_msg.delete()
                except discord.Forbidden:
                    pass
                except AttributeError:
                    pass
            del self.message_cache[message.id]

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        for message in messages:
            if message.id in self.message_cache:
                for webhook_msg in self.message_cache[message.id][1]:
                    try:
                        await webhook_msg.delete()
                    except discord.Forbidden:
                        pass
                    except AttributeError:
                        pass
                del self.message_cache[message.id]

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.id in self.message_cache:
            for webhook_msg in self.message_cache[before.id][1]:
                try:
                    await webhook_msg.edit(content=after.content, embeds=after.embeds)
                except discord.Forbidden:
                    pass
                except AttributeError:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.client.user:
            return

        forwards = list(filter(lambda x: x['source_channel'] == message.channel.id, self.mirror_config['mappings']))
        async with aiohttp.ClientSession() as session:
            for forward in forwards:
                forward_channel = message.guild.get_channel(forward['destination_channel'])
                print(f"Forwarding message from {message.guild} in {message.channel} to {forward_channel}")
                try:
                    try:
                        webhook = list(filter(lambda x: x.url == forward['destination_webhook'], await forward_channel.webhooks()))[0]
                    except IndexError:
                        webhook = discord.Webhook.from_url(forward['destination_webhook'],
                                                           adapter=discord.AsyncWebhookAdapter(session))

                    if message.attachments:
                        files = [
                            discord.File(fp=BytesIO(await a.read()), filename=a.filename, spoiler=a.is_spoiler())
                            for a in message.attachments
                        ]
                    else:
                        files = None

                    msg = await webhook.send(content=message.content,
                                             username=f"{message.author.display_name} (via #{message.channel})",
                                             avatar_url=message.author.avatar_url,
                                             files=files,
                                             embeds=message.embeds,
                                             wait=True
                                             )
                    if message.id in self.message_cache:
                        self.message_cache[message.id][1].append(msg)
                    else:
                        self.message_cache[message.id] = (message.created_at, [msg])

                except (discord.InvalidArgument, discord.NotFound, discord.Forbidden):
                    # URL invalid (probably webhook removed)
                    try:
                        if utils.has_reply():
                            await message.reply(f"Failed to forward this message to {forward_channel.mention}. "
                                                f"Please ask an administrator to re-create this mirror.")
                        else:
                            await message.channel.send(f"Failed to forward this message to {forward_channel.mention}. "
                                                       f"Please ask an administrator to re-create this mirror.")
                    except (discord.HTTPException, discord.InvalidArgument):
                        pass
                except discord.HTTPException as e:
                    # Sending the message failed.
                    try:
                        if utils.has_reply():
                            await message.reply(f"Failed to forward this message to {forward_channel.mention}. "
                                                f"Reason: {e}. "
                                                f"Please ask an administrator to check.")
                        else:
                            await message.channel.send(f"Failed to forward this message to {forward_channel.mention}. "
                                                       f"Reason: {e}. "
                                                       f"Please ask an administrator to check.")
                    except (discord.HTTPException, discord.InvalidArgument):
                        pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        start_len = len(self.mirror_config['mappings'])
        to_remove = list(filter(lambda x: (x['source_channel'] == channel.id), self.mirror_config['mappings']))
        for x in to_remove:
            # Remove webhook
            try:
                async with aiohttp.ClientSession() as session:
                    w = discord.Webhook.from_url(x['destination_webhook'], adapter=discord.AsyncWebhookAdapter(session))
                    source_channel = channel.guild.get_channel(x['source_channel'])
                    destination_channel = channel.guild.get_channel(x['destination_channel'])
                    await w.delete(
                        reason=f"Removed mirror from {source_channel} to {destination_channel} (source channel deleted)")
            except (discord.InvalidArgument, discord.NotFound, discord.Forbidden, discord.HTTPException):
                # URL invalid, Webhook not found, 'Manage webhooks', permission missing, or Discord error
                pass

        self.mirror_config['mappings'] = list(filter(
            lambda x: not (x['source_channel'] == channel.id or x['destination_channel'] == channel.id),
            self.mirror_config['mappings']
        ))
        utils.save_config(self.mirror_config)
        end_len = len(self.mirror_config['mappings'])
        num_removed = start_len - end_len
        print(f"Channel {channel} deleted. Removed {num_removed} mappings.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        print(f"Joined guild {guild} ({guild.id})")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        start_len = len(self.mirror_config['mappings'])
        self.mirror_config['mappings'] = list(filter(
            lambda x: x['source_guild'] != guild.id,
            self.mirror_config['mappings']
        ))
        utils.save_config(self.mirror_config)
        end_len = len(self.mirror_config['mappings'])
        num_removed = start_len - end_len
        # No need to remove webhooks, because we already left the guild.
        print(f"Left guild {guild}. Removed {num_removed} mappings.")

    # Commands
    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def add(self, ctx, source_channel: discord.TextChannel, destination_channel: discord.TextChannel):
        """
        Add a mirror between the source_channel and the destination_channel.
        """
        if ctx.guild is None:
            await ctx.send(f"This command cannot be used in private messages.")
            raise commands.CommandError("Command cannot be used in private messages.")

        if source_channel.id == destination_channel.id:
            await ctx.send(f"Cannot add a mirror with the same source and destination channel!")
            raise commands.CommandError("Cannot create mirror with same source and destination.")

        # Check if we have create webhook permissions in the destination channel
        if not destination_channel.permissions_for(ctx.me).manage_webhooks:
            await ctx.send(f"Missing 'Manage webhooks' permission for the destination channel.")
            raise commands.CommandError("Missing 'Manage webhooks' permission for the destination channel.")

        # Check if this mapping already exists
        existing = list(filter(lambda x: x['source_channel'] == source_channel.id, self.mirror_config['mappings']))
        if any([x['destination_channel'] == destination_channel.id for x in existing]):
            await ctx.send("Mirror already exists, if it is broken, remove it first.")
            raise commands.CommandError(
                f"Mapping in {ctx.guild} from {source_channel} to {destination_channel} already exists.")

        # Add webhook
        try:
            webhook = await destination_channel.create_webhook(
                name=f"ChannelMirrorBot",
                reason=f"Added mirror from {source_channel} to {destination_channel}"
            )
        except discord.Forbidden:
            await ctx.send(f"Could not create webhook, 'Manage webhooks' permission missing.")
            raise commands.CommandError("Could not create webhook, 'Manage webhooks' permission missing.")
        except discord.HTTPException:
            await ctx.send("Failed to create webhook. Try again later.")
            raise commands.CommandError(f"Failed to create webhook.")

        # Add mapping
        self.mirror_config['mappings'].append({
            "source_channel": source_channel.id,
            "source_guild": source_channel.guild.id,
            "destination_channel": destination_channel.id,
            "destination_webhook": webhook.url,
        })
        utils.save_config(self.mirror_config)

        await ctx.send("Mirror created!")
        print(f"Mapping added for guild {source_channel.guild}: {source_channel} to {destination_channel}")

    @add.error
    async def add_error(self, ctx, error):
        await ctx.send("You need the 'manage server' permission to add new mirrors.")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def remove(self, ctx, source_channel: discord.TextChannel, destination_channel: discord.TextChannel):
        """
        Remove the mirror between the source_channel and the destination_channel (if it existed)
        """
        if ctx.guild is None:
            await ctx.send(f"This command cannot be used in private messages.")
            raise commands.CommandError("Command cannot be used in private messages.")

        to_remove = list(filter(
            lambda x: (x['source_channel'] == source_channel.id and x['destination_channel'] == destination_channel.id),
            self.mirror_config['mappings'])
        )
        for x in to_remove:
            # Remove webhook
            try:
                async with aiohttp.ClientSession() as session:
                    w = discord.Webhook.from_url(x['destination_webhook'], adapter=discord.AsyncWebhookAdapter(session))
                    await w.delete(reason=f"Removed mirror from {source_channel} to {destination_channel}")
            except (discord.InvalidArgument, discord.NotFound):
                # URL invalid, or webhook not found (probably already removed)
                pass
            except discord.Forbidden:
                await ctx.send(f"Could not remove webhook, 'Manage webhooks' permission missing.")
                raise commands.CommandError("Could not remove webhook, 'Manage webhooks' permission missing.")
            except discord.HTTPException:
                await ctx.send("Failed to remove webhook. Please remove manually.")
                raise commands.CommandError(f"Failed to remove webhook.")

        start_len = len(self.mirror_config['mappings'])
        self.mirror_config['mappings'] = list(filter(
            lambda x: not (x['source_channel'] == source_channel.id and x[
                'destination_channel'] == destination_channel.id),
            self.mirror_config['mappings'])
        )
        end_len = len(self.mirror_config['mappings'])
        num_removed = start_len - end_len
        utils.save_config(self.mirror_config)

        await ctx.send(f"{num_removed} mirror{'s' if num_removed != 1 else ''} removed.")
        print(f"Mapping removed for guild {source_channel.guild}: {source_channel} to {destination_channel}")

    @remove.error
    async def remove_error(self, ctx, error):
        await ctx.send("You need the 'manage server' permission to remove mirrors.")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def list(self, ctx):
        """
        List all mirrors in the current guild.
        """
        if ctx.guild is None:
            await ctx.send(f"This command cannot be used in private messages.")
            raise commands.CommandError("Command cannot be used in private messages.")

        # Get mappings in this guild
        mappings = list(filter(lambda x: x['source_guild'] == ctx.guild.id, self.mirror_config['mappings']))
        if mappings:
            mappings_channels = [
                (ctx.guild.get_channel(m['source_channel']), ctx.guild.get_channel(m['destination_channel'])) for m in
                mappings]
            mappings_str = "\n".join(f"- {src.mention} to {dst.mention}" for src, dst in mappings_channels)
            await ctx.send(f"The mirrors for guild '{ctx.guild}' are:\n{mappings_str}")
        else:
            await ctx.send("No mirrors found for this guild.")

        print(f"Listed mirrors in guild {ctx.guild}")

    @list.error
    async def list_error(self, ctx, error):
        await ctx.send("You need the 'manage server' permission to list all mirrors.")

    @commands.command()
    async def ping(self, ctx):
        """
        Test the connection of the bot.
        """
        msg_time = ctx.message.created_at
        cur_time = datetime.utcnow()
        delay = (cur_time - msg_time) / timedelta(milliseconds=1)
        await ctx.send(f"Pong! ({str(delay)} ms)")

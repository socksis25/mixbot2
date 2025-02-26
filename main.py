import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from threading import Thread
from flask import Flask
import sqlite3
import random
import datetime
from datetime import datetime, timedelta
import json
import asyncio

# Constants
VIP_ROLE_ID = 1344356733866479687
ADMIN_ROLE_ID = 1342389265216311329
ROLE_DATA_FILE = 'role_data.json'

class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        # Setup credits table
        conn = sqlite3.connect('accounts.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS credits
                    (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)''')
        conn.commit()
        conn.close()

        # Load VIP role data
        self.role_data = self.load_role_data()

    def load_role_data(self):
        if os.path.exists(ROLE_DATA_FILE):
            with open(ROLE_DATA_FILE, 'r') as f:
                return json.load(f)
        return {}

    def save_role_data(self):
        with open(ROLE_DATA_FILE, 'w') as f:
            json.dump(self.role_data, f)

    async def setup_hook(self):
        try:
            await self.tree.sync()
        except Exception as e:
            print(f"Failed to sync commands: {e}")

client = Bot()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Image-only channel handling
    image_only_channels = [1334751722702114817, 1342384110534131784]
    if message.channel.id in image_only_channels:
        has_image = len(message.attachments) > 0 and any(att.content_type.startswith('image/') for att in message.attachments)

        if has_image:
            try:
                await message.add_reaction('✅')
            except:
                pass
        else:
            try:
                await message.delete()
                warning = await message.channel.send(
                    f"{message.author.mention} Only image messages are allowed in this channel!",
                    delete_after=5
                )
            except:
                pass

@client.event
async def on_voice_state_update(member, before, after):
    orders_channel_id = 1342383711685050419

    if member.bot:
        return

    try:
        guild = member.guild
        channel = guild.get_channel(orders_channel_id)
        if not channel:
            return

        # Check if someone is in the orders channel
        orders_channel = guild.get_channel(orders_channel_id)
        real_members = [m for m in orders_channel.members if not m.bot]
        current_count = len(real_members)

        # Update channel name based on member count
        desired_name = "🟢TAKING ORDERS🟢" if current_count > 0 else "🔴TAKING ORDERS🔴"

        if channel.name != desired_name:
            await channel.edit(name=desired_name)

    except Exception as e:
        print(f"Voice channel update error: {e}")

def is_admin(interaction: discord.Interaction) -> bool:
    return any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)

@client.tree.command(name="credits", description="Check credit balance")
async def credits(interaction: discord.Interaction, user: discord.User = None):
    target_user = user if user else interaction.user
    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('SELECT balance FROM credits WHERE user_id = ?', (target_user.id,))
    result = c.fetchone()
    balance = result[0] if result else 0
    conn.close()

    meals = balance // 15
    embed = discord.Embed(title="💳 Credit Balance", color=discord.Color.blue())
    embed.add_field(name="User", value=target_user.mention, inline=False)
    embed.add_field(name="Balance", value=f"{balance} credits", inline=False)
    embed.add_field(name="Meal Orders", value=f"Can order {meals} meals at $42 each (15 credits per meal)", inline=False)
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="topup", description="Add credits to a user")
async def topup(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction):
        embed = discord.Embed(title="❌ Error", description="You don't have permission to use this command!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO credits (user_id, balance) VALUES (?, COALESCE((SELECT balance + ? FROM credits WHERE user_id = ?), ?))',
              (user.id, amount, user.id, amount))
    conn.commit()

    c.execute('SELECT balance FROM credits WHERE user_id = ?', (user.id,))
    new_balance = c.fetchone()[0]
    conn.close()

    embed = discord.Embed(title="💰 Credits Added", color=discord.Color.green())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Amount Added", value=f"+{amount} credits", inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance} credits", inline=False)
    embed.set_footer(text=f"Added by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="deduct", description="Remove credits from a user")
async def deduct(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction):
        embed = discord.Embed(title="❌ Error", description="You don't have permission to use this command!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    conn = sqlite3.connect('accounts.db')
    c = conn.cursor()
    c.execute('SELECT balance FROM credits WHERE user_id = ?', (user.id,))
    result = c.fetchone()
    current_balance = result[0] if result else 0

    if current_balance < amount:
        embed = discord.Embed(title="❌ Error", description=f"User only has {current_balance} credits!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        conn.close()
        return

    c.execute('UPDATE credits SET balance = balance - ? WHERE user_id = ?', (amount, user.id))
    conn.commit()

    c.execute('SELECT balance FROM credits WHERE user_id = ?', (user.id,))
    new_balance = c.fetchone()[0]
    conn.close()

    embed = discord.Embed(title="💸 Credits Deducted", color=discord.Color.orange())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Amount Deducted", value=f"-{amount} credits", inline=True)
    embed.add_field(name="New Balance", value=f"{new_balance} credits", inline=False)
    embed.set_footer(text=f"Deducted by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="givevip", description="Give VIP role to a user")
async def givevip(interaction: discord.Interaction, member: discord.Member, days: int):
    if not is_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
        return

    if days <= 0:
        await interaction.response.send_message("Days must be positive!", ephemeral=True)
        return

    vip_role = interaction.guild.get_role(VIP_ROLE_ID)
    if not vip_role:
        await interaction.response.send_message("VIP role not found!", ephemeral=True)
        return

    await member.add_roles(vip_role)
    expiration = (datetime.now() + timedelta(days=days)).timestamp()
    client.role_data[str(member.id)] = expiration
    client.save_role_data()

    await interaction.response.send_message(f"Gave {member.mention} VIP role for {days} days!")

@client.tree.command(name="revokevip", description="Revoke VIP role from a user")
async def revokevip(interaction: discord.Interaction, member: discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command!", ephemeral=True)
        return

    vip_role = interaction.guild.get_role(VIP_ROLE_ID)
    if not vip_role:
        await interaction.response.send_message("VIP role not found!", ephemeral=True)
        return

    await member.remove_roles(vip_role)
    if str(member.id) in client.role_data:
        del client.role_data[str(member.id)]
        client.save_role_data()

    await interaction.response.send_message(f"Removed VIP role from {member.mention}!")

@client.tree.command(name="vipstatus", description="Check your VIP status")
async def vipstatus(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in client.role_data:
        await interaction.response.send_message("You don't have VIP status!", ephemeral=True)
        return

    expiration = datetime.fromtimestamp(client.role_data[user_id])
    days_left = (expiration - datetime.now()).days
    await interaction.response.send_message(f"You have {days_left} days of VIP remaining!")

last_draw_timestamp = 0

@client.tree.command(name="draw", description="Draw a random winner from messages")
async def draw(interaction: discord.Interaction, prize: str):
    if not is_admin(interaction):
        embed = discord.Embed(title="❌ Error", description="You don't have permission to use this command!", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    global last_draw_timestamp
    channel_id = 1342384110534131784
    channel = client.get_channel(channel_id)

    if not channel:
        await interaction.response.send_message("Cannot find the specified channel!", ephemeral=True)
        return

    messages = []
    if last_draw_timestamp == 0:
        async for message in channel.history(limit=500):
            if message.attachments and any(att.content_type.startswith('image/') for att in message.attachments):
                messages.append(message)
    else:
        after_time = datetime.fromtimestamp(last_draw_timestamp, datetime.timezone.utc)
        async for message in channel.history(limit=500, after=after_time):
            if message.attachments and any(att.content_type.startswith('image/') for att in message.attachments):
                messages.append(message)

    if not messages:
        await interaction.response.send_message("No eligible entries found since the last draw!", ephemeral=True)
        return

    winner_message = random.choice(messages)
    last_draw_timestamp = int(winner_message.created_at.timestamp())

    embed = discord.Embed(title="🎉 Draw Winner!", color=discord.Color.gold())
    embed.add_field(name="Winner", value=winner_message.author.mention, inline=False)
    embed.add_field(name="Prize", value=prize, inline=False)

    if winner_message.attachments:
        embed.set_image(url=winner_message.attachments[0].url)

    embed.add_field(name="Winning Entry", value=f"[Jump to message]({winner_message.jump_url})", inline=False)
    embed.set_footer(text=f"Draw conducted by {interaction.user.name}")

    class RerollView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.timeout = None

        @discord.ui.button(label="Reroll", style=discord.ButtonStyle.primary, emoji="🎲")
        async def reroll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not is_admin(interaction):
                await interaction.response.send_message("You don't have permission to reroll!", ephemeral=True)
                return

            new_winner = random.choice(messages)
            global last_draw_timestamp
            last_draw_timestamp = int(new_winner.created_at.timestamp())

            new_embed = discord.Embed(title="🎲 Reroll Winner!", color=discord.Color.gold())
            new_embed.add_field(name="Winner", value=new_winner.author.mention, inline=False)
            new_embed.add_field(name="Prize", value=prize, inline=False)
            if new_winner.attachments:
                new_embed.set_image(url=new_winner.attachments[0].url)
            new_embed.add_field(name="Winning Entry", value=f"[Jump to message]({new_winner.jump_url})", inline=False)
            new_embed.set_footer(text=f"Rerolled by {interaction.user.name}")

            await interaction.response.send_message(embed=new_embed, view=RerollView())

    await interaction.response.send_message(embed=embed, view=RerollView())

async def check_expired_roles():
    while True:
        current_time = datetime.now().timestamp()
        expired_users = []

        for user_id, expiration in client.role_data.items():
            if expiration <= current_time:
                expired_users.append(user_id)

        if expired_users:
            for guild in client.guilds:
                vip_role = guild.get_role(VIP_ROLE_ID)
                if vip_role:
                    for user_id in expired_users:
                        try:
                            member = await guild.fetch_member(int(user_id))
                            if member:
                                await member.remove_roles(vip_role)
                                del client.role_data[user_id]
                        except:
                            pass
            client.save_role_data()

        await asyncio.sleep(300)  # Check every 5 minutes

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="BIGMIX.STORE"))
    client.loop.create_task(check_expired_roles())

app = Flask('')

@app.route('/')
def home():
    try:
        vip_count = len(client.role_data) if hasattr(client, 'role_data') else 0
        return f"""
<!DOCTYPE html>
<html>
    <head>
        <title>Discord Bot Status</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 40px;
            }}
            .status {{
                padding: 20px;
                background: #e8f5e9;
                border-radius: 8px;
            }}
        </style>
    </head>
    <body>
        <h1>Discord Bot Status</h1>
        <div class="status">
            <p>Bot is running!</p>
            <p>Current VIP users: {vip_count}</p>
        </div>
    </body>
</html>
"""
    except Exception as e:
        return f"Bot status: Running (Error displaying VIP count: {str(e)})"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN:
    try:
        client.run(TOKEN)
    except Exception as e:
        print(f"Error running bot: {e}")
else:
    print("Please set the DISCORD_TOKEN environment variable")

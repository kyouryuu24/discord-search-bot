import os
import threading
from flask import Flask
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands
from dotenv import load_dotenv

# --- Renderで常時稼働させるためのWebサーバー(Keep-Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# スレッドでWebサーバーを並行起動
threading.Thread(target=run_flask).start()

# --- ここから下は既存のBotコード ---
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 検索対象とするルールサイトの各ページURLリスト
RULE_PAGES = [
    "https://null404-rules.pages.dev/01-support.html",
    "https://null404-rules.pages.dev/05-crime.html",
    "https://null404-rules.pages.dev/02-general.html",
]

def search_rules_site(query):
    matches = []
    for url in RULE_PAGES:
        try:
            res = requests.get(url, timeout=5)
            if res.status_code != 200:
                continue
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            for element in soup.find_all(['tr', 'p', 'li', 'h1', 'h2', 'h3']):
                text = element.get_text(separator=' | ').strip()
                text = " ".join(text.split())
                if query.lower() in text.lower():
                    matches.append(text)
                    if len(matches) >= 3:
                        return matches
        except Exception:
            continue
    return matches

def search_spreadsheet(query):
    sheet_id = "1gLWYyOXIPj5Zn-OZqHDy0R7juRwSg6Qpv-0FRU8nHkE"
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        res = requests.get(url, timeout=5)
        res.encoding = 'utf-8'
        lines = res.text.splitlines()
        matches = []
        for line in lines:
            if query.lower() in line.lower():
                formatted_line = " | ".join([cell.strip() for cell in line.split(',') if cell.strip()])
                matches.append(formatted_line)
                if len(matches) >= 3:
                    break
        return matches
    except Exception:
        return []

@bot.event
async def on_ready():
    print(f'ログイン成功: {bot.user.name}')

@bot.command(name='検索')
async def search(ctx, *, query: str):
    await ctx.send(f"🔍 『{query}』 を検索中...")
    rule_results = search_rules_site(query)
    sheet_results = search_spreadsheet(query)
    
    embed = discord.Embed(
        title=f"「{query}」の検索結果",
        color=discord.Color.green()
    )
    
    if rule_results:
        embed.add_field(
            name="📜 ルールサイトからの結果",
            value="\n".join([f"・{r}" for r in rule_results])[:1024],
            inline=False
        )
    
    if sheet_results:
        embed.add_field(
            name="📊 車両価格スプレッドシートからの結果",
            value="\n".join([f"・{s}" for s in sheet_results])[:1024],
            inline=False
        )
        
    if not rule_results and not sheet_results:
        embed.description = "該当する情報が見つかりませんでした。"
        
    await ctx.send(embed=embed)

bot.run(TOKEN)
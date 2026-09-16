import os
import threading
import csv
import io
from flask import Flask
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands
from dotenv import load_dotenv

# --- Keep-Alive Webサーバー ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is active!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# --- Discord Bot設定 ---
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

RULE_PAGES = [
    "https://null404-rules.pages.dev/01-support.html",
    "https://null404-rules.pages.dev/02-general.html",
    "https://null404-rules.pages.dev/03-vehicle.html",
    "https://null404-rules.pages.dev/04-job.html",
    "https://null404-rules.pages.dev/05-crime.html",
    "https://null404-rules.pages.dev/06-gang.html",
]

# 表記揺れ（エイリアス）辞書
ALIAS_MAP = {
    "デベステ": "Deveste",
    "デベステエイト": "Deveste Eight",
    # 必要に応じてここに追加可能です
}

# ブラウザ偽装用セッション
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
})

def search_rules_site(query):
    matches = []
    for url in RULE_PAGES:
        try:
            res = session.get(url, timeout=5)
            if res.status_code != 200 or "cf-error-details" in res.text:
                continue
            
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for element in soup.find_all(['tr', 'p', 'li', 'h1', 'h2', 'h3']):
                text = element.get_text(separator=' | ').strip()
                text = " ".join(text.split())
                if text and query.lower() in text.lower():
                    if text not in matches:
                        matches.append(text)
                        if len(matches) >= 3:
                            return matches
        except Exception:
            continue
    return matches

def search_spreadsheet(query):
    # Webに公開されたCSV URLから直接取得
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSERXdms_ZOSdihgcdlJNm-NneQRlydiThyBxmRbqyhUkIA8PYzE9lYuFVfFZV85wKn921LR0L47bPG/pub?output=csv"
    
    try:
        res = session.get(url, timeout=5)
        if res.status_code != 200:
            return []
            
        res.encoding = 'utf-8'
        csv_file = io.StringIO(res.text)
        reader = csv.reader(csv_file)
        
        matches = []
        for row in reader:
            row_text = " | ".join([cell.strip() for cell in row if cell.strip()])
            if query.lower() in row_text.lower():
                if row_text not in matches:
                    matches.append(row_text)
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
    search_query = query.strip()
    for alias, official_name in ALIAS_MAP.items():
        if alias.lower() in search_query.lower():
            search_query = search_query.replace(alias, official_name)
    
    if search_query != query.strip():
        await ctx.send(f"🔍 『{query}』 (⇒ {search_query}) で検索中...")
    else:
        await ctx.send(f"🔍 『{search_query}』 で検索中...")
    
    rule_results = search_rules_site(search_query)
    sheet_results = search_spreadsheet(search_query)
    
    embed = discord.Embed(
        title=f"「{query}」の検索結果",
        color=discord.Color.green()
    )
    
    if rule_results:
        formatted_rule = "\n".join([f"・{r}" for r in rule_results])
        if len(formatted_rule) > 1000:
            formatted_rule = formatted_rule[:1000] + "..."
        embed.add_field(name="📜 ルールサイトからの結果", value=formatted_rule, inline=False)
    
    if sheet_results:
        formatted_sheet = "\n".join([f"・{s}" for s in sheet_results])
        if len(formatted_sheet) > 1000:
            formatted_sheet = formatted_sheet[:1000] + "..."
        embed.add_field(name="📊 車両価格スプレッドシートからの結果", value=formatted_sheet, inline=False)
        
    if not rule_results and not sheet_results:
        embed.description = "該当する情報が見つかりませんでした。"
        
    await ctx.send(embed=embed)

if TOKEN:
    bot.run(TOKEN)

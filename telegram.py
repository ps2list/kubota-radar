import os, urllib.parse, urllib.request

def send_message(text):
    token=os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id=os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram secrets ontbreken; melding overgeslagen.")
        return False
    url=f"https://api.telegram.org/bot{token}/sendMessage"
    data=urllib.parse.urlencode({"chat_id":chat_id,"text":text,"disable_web_page_preview":"true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=data),timeout=20) as r:
            return r.status == 200
    except Exception as e:
        print("Telegram-fout:",e)
        return False

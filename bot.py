from flask import Flask, request
import requests
app = Flask(__name__)
TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/" 
@app.route('/webhook', methods=['POST']) 
def webhook(): update = request.get_json() 
    chat_id = update['message']['chat']['id'] 
    text = update['message']['text'] 

    send_message(chat_id, "Привет!") 
    return "OK", 200 
def send_message(chat_id, text): 
    payload = { "chat_id": chat_id, 
               "text": text 
    }
  requests.post(f"{TELEGRAM_URL}sendMessage", json=payload) 
  if __name__ == "__main__": 
    app.run(host="0.0.0.0", port=5000)

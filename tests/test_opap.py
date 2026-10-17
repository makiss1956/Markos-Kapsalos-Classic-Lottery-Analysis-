import requests
import json
from datetime import datetime

GAME_ID = 5104
url = f"https://api.opap.gr/games/v1.0/games/{GAME_ID}/last-results"

print("=" * 60)
print(f"Δοκιμαστική κλήση στο επίσημο API του ΟΠΑΠ...")
print(f"URL: {url}")
print("=" * 60)

try:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "el-GR,el;q=0.9,en;q=0.8,en-US;q=0.7",
        "Referer": "https://www.opap.gr/",
        "Origin": "https://www.opap.gr",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="8", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Η σύνδεση ΠΕΤΥΧΕ! (Status Code: 200)")
        
        if isinstance(data, list) and len(data) > 0:
            latest_draw = data[0]
        elif isinstance(data, dict) and "content" in data and len(data["content"]) > 0:
            latest_draw = data["content"][0]
        else:
            latest_draw = data
            
        print("\n--- ΤΕΛΕΥΤΑΙΑ ΚΛΗΡΩΣΗ ---")
        print(f"ID Κλήρωσης: {latest_draw.get('drawId')}")
        
        draw_time = latest_draw.get('drawTime')
        if draw_time:
            date_str = datetime.fromtimestamp(draw_time / 1000).strftime('%Y-%m-%d %H:%M')
            print(f"Ημερομηνία:  {date_str}")
            
        wn = latest_draw.get('winningNumbers', {})
        main_nums = wn.get('list', [])
        euro_nums = wn.get('sideClassNum', []) or wn.get('sideClassNumbers', {}).get('list', [])
        
        print(f"Βασικοί Αριθμοί (5): {sorted(main_nums)}")
        print(f"Euro Αριθμοί (2):    {sorted(euro_nums)}")
        print("-" * 35)
        
    else:
        print(f"❌ Απέτυχε η σύνδεση. Κωδικός σφάλματος: {response.status_code}")
        print(response.text[:200])

except Exception as e:
    print(f"❌ Προέκυψε σφάλμα κατά την εκτέλεση: {e}")

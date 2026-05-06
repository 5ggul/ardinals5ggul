import os
import json
import time
import requests
from pathlib import Path

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

ARDINALS_API = 'https://api.ardinals.com'
STATE_FILE = Path('state.json')

ELEMENT_MAP = {0: '?', 1: 'metal', 2: 'wood', 3: 'water', 4: 'fire', 5: 'earth', 6: 'special'}
LANGUAGE_MAP = {0: 'en', 1: 'zh', 2: 'ja', 3: 'ko', 4: 'fr', 5: 'de'}

FRIENDLY_ELEMENTS = {1, 4, 5}
HOSTILE_ELEMENTS = {2, 3}

TIER1_ETH_PER_POWER = 0.00050
TIER2_ETH_PER_POWER = 0.00060
TIER3_LEGENDARY_POWER = 85
TIER3_PREMIUM_POWER = 80
PRICE_DROP_THRESHOLD = 0.10


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return {'listings': {}}
    return {'listings': {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


def fetch_listings():
    r = requests.get(f'{ARDINALS_API}/v1/market/listings', timeout=30)
    r.raise_for_status()
    return r.json()['rows']


def fetch_metadata(token_id):
    r = requests.get(f'{ARDINALS_API}/v1/ardinals/{token_id}', timeout=30)
    r.raise_for_status()
    return r.json()


def get_rarity(power):
    if power >= 85:
        return 'legendary'
    if power >= 60:
        return 'rare'
    if power >= 35:
        return 'uncommon'
    return 'common'


def evaluate(meta, price_eth, prev_price):
    power = meta['power']
    eth_per_power = price_eth / power
    rarity = get_rarity(power)
    max_dur = meta.get('maxDurability', 0)

    if prev_price and price_eth < prev_price * (1 - PRICE_DROP_THRESHOLD):
        drop = (1 - price_eth / prev_price) * 100
        return ('3-DROP', f'price -{drop:.1f}% (prev {prev_price:.4f})')

    if prev_price is not None and prev_price == price_eth:
        return (None, None)

    if power >= TIER3_LEGENDARY_POWER:
        return ('3-LEG', f'Legendary (power {power})')

    if power >= TIER3_PREMIUM_POWER and rarity == 'rare' and max_dur >= 2:
        return ('3-PREMIUM', f'Power {power} rare, maxDur {max_dur}')

    if eth_per_power < TIER1_ETH_PER_POWER:
        return ('1', f'ETH/Power {eth_per_power:.6f}')

    if eth_per_power < TIER2_ETH_PER_POWER and rarity in ('rare', 'legendary'):
        return ('2', f'ETH/Power {eth_per_power:.6f}')

    return (None, None)


def format_msg(token_id, meta, price_eth, tier, reason):
    power = meta['power']
    word = meta.get('word', '?')
    element_id = meta.get('element', 0)
    element = ELEMENT_MAP.get(element_id, str(element_id))
    lang = LANGUAGE_MAP.get(meta.get('languageId', 0), '?')
    rarity = get_rarity(power)
    max_dur = meta.get('maxDurability', '?')

    if element_id in FRIENDLY_ELEMENTS:
        elem_tag = f'🟢 {element}'
    elif element_id in HOSTILE_ELEMENTS:
        elem_tag = f'🔴 {element} (king 상극)'
    else:
        elem_tag = f'⚪ {element}'

    tier_label = {
        '1': '🔥🔥🔥 Tier 1 — 즉시 매수',
        '2': '🔥 Tier 2 — 검토',
        '3-LEG': '⭐ LEGENDARY 등장',
        '3-PREMIUM': '⭐ PREMIUM (Power 80+ rare)',
        '3-DROP': '📉 가격 인하',
    }.get(tier, tier)

    eth_per_power = price_eth / power

    return (
        f'{tier_label}\n\n'
        f'#{token_id} {word} ({rarity}, {lang})\n'
        f'Power {power} | maxDur {max_dur} | {elem_tag}\n\n'
        f'💰 {price_eth:.4f} ETH\n'
        f'📊 ETH/Power: {eth_per_power:.6f}\n\n'
        f'📌 {reason}\n\n'
        f'🔗 https://www.ardinals.com/market'
    )


def send_telegram(msg):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    try:
        r = requests.post(url, json={'chat_id': CHAT_ID, 'text': msg}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f'Telegram error: {e}')


def main():
    state = load_state()
    listings = fetch_listings()

    new_listings_state = {}
    alerts = []

    for listing in listings:
        token_id = listing['tokenId']
        price_eth = int(listing['priceWei']) / 1e18

        new_listings_state[token_id] = {'price': price_eth}

        prev = state['listings'].get(token_id)
        prev_price = prev['price'] if prev else None

        if prev_price is not None and prev_price == price_eth:
            continue

        try:
            meta = fetch_metadata(token_id)
        except Exception as e:
            print(f'Metadata fail #{token_id}: {e}')
            continue

        if meta.get('maxDurability', 0) == 0:
            continue

        tier, reason = evaluate(meta, price_eth, prev_price)

        if tier:
            alerts.append(format_msg(token_id, meta, price_eth, tier, reason))

        time.sleep(0.2)

    print(f'Checked {len(listings)} listings, prepared {len(alerts)} alerts')

    for msg in alerts:
        send_telegram(msg)
        time.sleep(1)

    save_state({'listings': new_listings_state})
    print('State saved')


if __name__ == '__main__':
    main()

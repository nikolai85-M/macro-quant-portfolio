# news_engine.py — Двухуровневый анализатор (макро + стратегия)
"""
УРОВЕНЬ 1: Общий анализ рынка → macro_context.json
УРОВЕНЬ 2: LLM выбирает стратегию и тикеры → final_strategy.json
"""

import os
import sys
import json
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(SCRIPT_DIR, '.env')
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')

sys.path.append(ROOT_DIR)
load_dotenv(ENV_PATH)

# ==============================================================================
# НАСТРОЙКИ
# ==============================================================================

AITUNNEL_API_KEY = os.getenv("AITUNNEL_API_KEY")
AITUNNEL_BASE_URL = "https://api.aitunnel.ru/v1/"
AITUNNEL_MODEL = "deepseek-v4.1-flash"

if not AITUNNEL_API_KEY:
    raise ValueError("❌ AITUNNEL_API_KEY не найден в .env")

client = OpenAI(base_url=AITUNNEL_BASE_URL, api_key=AITUNNEL_API_KEY)

MACRO_OUTPUT = os.path.join(DATA_DIR, 'macro_context.json')
STRATEGY_OUTPUT = os.path.join(DATA_DIR, 'final_strategy.json')

# Сектора
SECTOR_TICKERS = {
    'oil_gas': ['GAZP', 'LKOH', 'ROSN', 'TATN', 'SNGS', 'NVTK', 'TATNP', 'SNGSP'],
    'metals': ['GMKN', 'PLZL', 'RUAL', 'ALRS', 'CHMF', 'NLMK', 'MAGN', 'VSMO', 'MTLR', 'MTLRP', 'ENPG'],
    'finance': ['SBER', 'VTBR', 'CBOM', 'BSPB', 'MOEX', 'SBERP', 'T', 'SVCB', 'MBNK'],
    'consumer': ['MGNT', 'FIVE', 'LENT', 'MVID', 'BELU', 'SOFL', 'X5', 'SELG'],
    'tech': ['YNDX', 'OZON', 'VKCO', 'HEAD', 'DATA', 'POSI', 'RENI', 'WUSH'],
    'energy': ['HYDR', 'IRAO', 'FEES', 'MSNG', 'UPRO', 'ELFV', 'TGKA', 'MRKP', 'MRKV', 'MRKU', 'FEES'],
    'developers': ['PIKK', 'SMLT', 'LSRG', 'RAGR', 'LEAS'],
    'transport': ['AFLT', 'FLOT', 'NMTP'],
    'telecom': ['MTSS', 'RTKM', 'RTKMP'],
    'chemicals': ['PHOR', 'AKRN', 'NKNC', 'NKNCP'],
}

# Индекс секторов
TICKER_TO_SECTOR = {}
for sector, tickers in SECTOR_TICKERS.items():
    for t in tickers:
        TICKER_TO_SECTOR[t] = sector


# ==============================================================================
# ЗАГРУЗКА
# ==============================================================================

def load_json(filename, subdir=None):
    if subdir:
        filepath = os.path.join(DATA_DIR, subdir, filename)
    else:
        filepath = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"   ⚠️ Ошибка чтения {filename}: {e}")
        return None


def load_ticker_news(ticker):
    return load_json(f'{ticker}.json', subdir='ticker_news')


# ==============================================================================
# ФОРМАТИРОВАНИЕ
# ==============================================================================

def format_macro_current(macro):
    if not macro:
        return "Макро-данные недоступны."
    
    lines = ["📊 ТЕКУЩИЕ МАКРО-ДАННЫЕ:"]
    if macro.get('brent'):
        lines.append(f"• Brent: ${macro['brent']:.2f}")
    if macro.get('gold'):
        lines.append(f"• Золото: {macro['gold']:.2f}₽")
    if macro.get('imoex'):
        lines.append(f"• IMOEX: {macro['imoex']:.2f}")
    if macro.get('rvi'):
        lines.append(f"• RVI: {macro['rvi']:.2f}")
    if macro.get('usd_rub'):
        lines.append(f"• USD/RUB: {macro['usd_rub']:.2f}₽")
    if macro.get('cny_rub'):
        lines.append(f"• CNY/RUB: {macro['cny_rub']:.4f}₽")
    if macro.get('cbr_rate'):
        lines.append(f"• Ставка ЦБ: {macro['cbr_rate']}%")
    if macro.get('inflation'):
        lines.append(f"• Инфляция: {macro['inflation']}%")
    
    return '\n'.join(lines)


def format_macro_history(history, current):
    if not history:
        return ""
    
    lines = ["📊 ИСТОРИЯ (2 ГОДА):"]
    
    def make_summary(name, history_data, current_value):
        if not history_data:
            return None
        values = [h['value'] for h in history_data if h['value'] is not None]
        if not values:
            return None
        
        min_v, max_v = min(values), max(values)
        cur = current_value if current_value else values[-1]
        position = ((cur - min_v) / (max_v - min_v) * 100) if max_v > min_v else 50
        
        trend = "SIDEWAYS"
        change_30d = 0
        if len(values) >= 30:
            recent = values[-30:]
            change_30d = (recent[-1] - recent[0]) / recent[0] * 100
            if change_30d > 5: trend = "UP"
            elif change_30d < -5: trend = "DOWN"
        
        return f"  • {name}: {cur:.2f} | диапазон {min_v:.2f}-{max_v:.2f} | поз. {position:.0f}% | тренд 30д: {trend} ({change_30d:+.1f}%)"
    
    if history.get('brent', {}).get('history'):
        s = make_summary('Brent', history['brent']['history'], current.get('brent'))
        if s: lines.append(s)
    if history.get('imoex', {}).get('history'):
        s = make_summary('IMOEX', history['imoex']['history'], current.get('imoex'))
        if s: lines.append(s)
    if history.get('gold', {}).get('history'):
        s = make_summary('Золото', history['gold']['history'], current.get('gold'))
        if s: lines.append(s)
    if history.get('usd_rub', {}).get('history'):
        s = make_summary('USD/RUB', history['usd_rub']['history'], current.get('usd_rub'))
        if s: lines.append(s)
    
    return '\n'.join(lines)


def format_news_summary(news_feed):
    if not news_feed:
        return "Новости недоступны."
    
    news = news_feed.get('news', [])[:30]
    lines = [f"📰 НОВОСТИ (топ-30 из {len(news_feed.get('news', []))}):"]
    for n in news:
        lines.append(f"  • [{n.get('source', '?')}] {n.get('title', '')[:120]}")
    
    return '\n'.join(lines)


def format_calendar(calendar_data):
    if not calendar_data:
        return "Календарь недоступен."
    
    events = calendar_data.get('all_events', [])
    if not events:
        return "Событий нет."
    
    lines = ["📅 КАЛЕНДАРЬ (7 дней):"]
    by_date = {}
    for e in events:
        date = e.get('date', '')
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(e)
    
    for date in sorted(by_date.keys()):
        lines.append(f"\n  📅 {date}:")
        for e in by_date[date]:
            impact = e.get('impact', 'LOW')
            emoji = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(impact, '⚪')
            lines.append(f"    {emoji} {e.get('event', '')}")
    
    return '\n'.join(lines)


def format_scanner_signals(signals):
    """Форматирует сигналы сканера"""
    if not signals:
        return "  (нет сигналов)"
    
    lines = []
    for s in signals:
        lines.append(
            f"  {s['ticker']:8} | {s['direction']:6} | "
            f"цена {s['price']:8.2f} | Stoch {s['stoch']:5.1f} | "
            f"R:R {s['risk_reward']:5.2f} | кач {s['quality']}/100"
        )
    return '\n'.join(lines)


def format_all_tickers_brief(scanner_signals):
    """
    Форматирует ВСЕ 97 тикеров кратко.
    Показывает: тикер, направление (из сканера), Stoch.
    """
    # Собираем данные сканера
    scanner_data = {}
    for s in scanner_signals:
        scanner_data[s['ticker']] = {
            'direction': s['direction'],
            'stoch': s['stoch'],
            'r_r': s.get('risk_reward', 0),
        }
    
    # Все тикеры из all_assets.json
    all_assets = load_json('../all_assets.json') or load_json('all_assets.json')
    
    lines = ["📊 ВСЕ ТИКЕРЫ (97):"]
    
    if all_assets and 'assets' in all_assets:
        for ticker, info in all_assets['assets'].items():
            sector = TICKER_TO_SECTOR.get(ticker, '?')
            
            if ticker in scanner_data:
                d = scanner_data[ticker]
                lines.append(
                    f"  {ticker:8} | {sector:12} | {d['direction']:6} | "
                    f"Stoch {d['stoch']:5.1f} | R:R {d['r_r']:5.2f}"
                )
            else:
                # Тикер без сигнала — только сектор
                lines.append(f"  {ticker:8} | {sector:12} | нет сигнала")
    
    return '\n'.join(lines)


def summarize_news(ticker_news):
    """Краткая сводка новостей для промпта"""
    if not ticker_news:
        return "нет новостей"
    
    total = len(ticker_news.get('news', [])) + len(ticker_news.get('forum_news', []))
    divs = len(ticker_news.get('dividends', []))
    
    parts = []
    if total > 0:
        parts.append(f"новостей: {total}")
    if divs > 0:
        parts.append(f"дивидендов: {divs}")
    
    return ', '.join(parts) if parts else "нет новостей"


# ==============================================================================
# УРОВЕНЬ 1: ОБЩИЙ АНАЛИЗ РЫНКА
# ==============================================================================

def analyze_macro_context():
    print("="*70)
    print("🧠 УРОВЕНЬ 1: ОБЩИЙ АНАЛИЗ РЫНКА")
    print("="*70)
    print()
    
    print("📂 Загрузка данных...")
    macro_current = load_json('macro_data.json')
    macro_history = load_json('macro_history.json')
    news_feed = load_json('news_feed.json')
    calendar_data = load_json('calendar.json')
    
    if not all([macro_current, macro_history, news_feed, calendar_data]):
        print("❌ Не все данные доступны")
        return None
    
    print("   ✅ Все 4 источника загружены")
    print()
    
    system_prompt = """Ты — профессиональный аналитик российского фондового рынка.
Оцени общий макро-фон рынка РФ.

Отвечай СТРОГО в формате JSON (без markdown):
{
    "date": "YYYY-MM-DD",
    "market_phase": "UP/DOWN/CORRECTION/SIDEWAYS",
    "macro_score": -10..+10,
    "risk_level": "LOW/MEDIUM/HIGH",
    "priority": "LONG/SHORT/NEUTRAL",
    "imoex_position": 0-100,
    "imoex_overbought": true/false,
    "imoex_oversold": true/false,
    "macro_summary": "краткое описание",
    "key_risks": ["риск 1", "риск 2"],
    "focus_sectors": {
        "oil_gas": "LONG/SHORT/NEUTRAL",
        "finance": "LONG/SHORT/NEUTRAL",
        "metals": "LONG/SHORT/NEUTRAL",
        "developers": "LONG/SHORT/NEUTRAL"
    },
    "news_tone": {
        "overall": "POSITIVE/NEUTRAL/NEGATIVE",
        "score": -1.0..+1.0,
        "by_layer": {
            "macro": {"score": -1.0..+1.0, "label": "POSITIVE/NEUTRAL/NEGATIVE"},
            "general": {"score": -1.0..+1.0, "label": "POSITIVE/NEUTRAL/NEGATIVE"},
            "sectors": {
                "oil_gas": {"score": -1.0..+1.0, "label": "..."},
                "finance": {"score": -1.0..+1.0, "label": "..."},
                "metals": {"score": -1.0..+1.0, "label": "..."},
                "developers": {"score": -1.0..+1.0, "label": "..."},
                "energy": {"score": -1.0..+1.0, "label": "..."},
                "tech": {"score": -1.0..+1.0, "label": "..."}
            }
        }
    },
    "critical_events": [
        {
            "date": "YYYY-MM-DD",
            "event": "описание",
            "impact": "HIGH/MEDIUM/LOW",
            "affected_sectors": ["oil_gas", "finance"]
        }
    ],
    "news_summary": "краткая сводка новостей (2-3 предложения)"
}

ПРАВИЛА:
- market_phase: общее состояние
- imoex_position: 0-100% (0=у минимума, 100=у максимума)
- imoex_overbought: true если рынок перекуплен (риск коррекции)
- imoex_oversold: true если рынок перепродан (риск отскока)
- priority: направление для торговли
- news_tone.score: -1.0 (очень негативно) до +1.0 (очень позитивно)
- news_tone.by_layer.macro: тональность макро-новостей (ставка, Brent, геополитика)
- news_tone.by_layer.general: тональность общих рыночных новостей
- news_tone.by_layer.sectors: тональность новостей по секторам
- critical_events: только события, которые МОГУТ резко повернуть рынок (санкции, ставка, дефолт, крупные отчёты)
- news_summary: краткая сводка для быстрого чтения
"""
    
    user_prompt = f"""Проанализируй рынок РФ на {datetime.now().strftime('%Y-%m-%d')}.

{format_macro_current(macro_current)}

{format_macro_history(macro_history, macro_current)}

{format_news_summary(news_feed)}

{format_calendar(calendar_data)}

Верни ТОЛЬКО JSON.
"""
    
    print("🤖 Отправка в DeepSeek...")
    
    try:
        response = client.chat.completions.create(
            model=AITUNNEL_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4000,
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        
        result = json.loads(content)
        
        with open(MACRO_OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print()
        print(f"📅 Фаза рынка: {result.get('market_phase', '?')}")
        print(f"🎯 Макро-скор: {result.get('macro_score', 0):+d}")
        print(f"⚠️ Риск: {result.get('risk_level', '?')}")
        print(f"🎯 Приоритет: {result.get('priority', '?')}")
        print(f"📊 IMOEX позиция: {result.get('imoex_position', '?')}%")
        if result.get('imoex_overbought'):
            print(f"⚠️ Рынок ПЕРЕКУПЛЕН")
        if result.get('imoex_oversold'):
            print(f"⚠️ Рынок ПЕРЕПРОДАН")
        print(f"📝 {result.get('macro_summary', '')[:200]}")

        # Тональность новостей
        news_tone = result.get('news_tone', {})
        if news_tone:
            print(f"\n📰 Тональность новостей: {news_tone.get('overall', '?')} "
                  f"(score: {news_tone.get('score', 0):+.2f})")
            by_layer = news_tone.get('by_layer', {})
            for layer_name, layer_data in by_layer.items():
                if layer_name == 'sectors':
                    continue
                score = layer_data.get('score', 0) if isinstance(layer_data, dict) else 0
                label = layer_data.get('label', '?') if isinstance(layer_data, dict) else '?'
                print(f"   - {layer_name}: {label} ({score:+.2f})")
        
        # Критические события
        critical = result.get('critical_events', [])
        if critical:
            print(f"\n⚠️ КРИТИЧЕСКИЕ СОБЫТИЯ ({len(critical)}):")
            for ev in critical[:5]:
                print(f"   - {ev.get('date', '?')}: {ev.get('event', '?')[:80]} "
                      f"[{ev.get('impact', '?')}]")
        
        focus = result.get('focus_sectors', {})
        if focus:
            print(f"\n🏭 Фокусные сектора:")
            for sector, direction in focus.items():
                emoji = {'LONG': '🟢', 'SHORT': '🔴', 'NEUTRAL': '⚪'}.get(direction, '⚪')
                print(f"   {emoji} {sector}: {direction}")
        
        print(f"\n💾 Сохранено: {MACRO_OUTPUT}")
        print()
        
        return result
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


# ==============================================================================
# УРОВЕНЬ 2: СТРАТЕГИЯ
# ==============================================================================

def analyze_strategy(scanner_signals, macro_context, macro_current, 
                     macro_history, calendar_data):
    """
    LLM выбирает стратегию и тикеры.
    Видит ВСЕ 97 тикеров + сигналы сканера + макро + новости + календарь.
    """
    
    # Разделяем сигналы по направлению
    short_signals = [s for s in scanner_signals if s['direction'] == 'SHORT']
    long_signals = [s for s in scanner_signals if s['direction'] == 'LONG']
    
    # Форматируем макро
    macro_text = f"""📊 МАКРО-КОНТЕКСТ:
  • Фаза рынка: {macro_context.get('market_phase', '?')}
  • Приоритет: {macro_context.get('priority', '?')}
  • Макро-скор: {macro_context.get('macro_score', 0):+d}
  • IMOEX позиция: {macro_context.get('imoex_position', 50)}% диапазона
  • IMOEX перекуплен: {macro_context.get('imoex_overbought', False)}
  • IMOEX перепродан: {macro_context.get('imoex_oversold', False)}
  • Риск: {macro_context.get('risk_level', '?')}
  • Brent: ${macro_current.get('brent', 0):.2f}
  • Ставка ЦБ: {macro_current.get('cbr_rate', 0)}%
  • RVI: {macro_current.get('rvi', 0):.2f}
  
  📝 Видение: {macro_context.get('macro_summary', '')}
  
  🏭 Фокусные сектора:"""
        
    # Тональность новостей
    news_tone = macro_context.get('news_tone', {})
    if news_tone:
        macro_text += f"\n\n  📰 ТОНАЛЬНОСТЬ НОВОСТЕЙ:"
        macro_text += f"\n    Общая: {news_tone.get('overall', '?')} ({news_tone.get('score', 0):+.2f})"
        by_layer = news_tone.get('by_layer', {})
        macro_layer = by_layer.get('macro', {})
        general_layer = by_layer.get('general', {})
        if macro_layer:
            macro_text += f"\n    Макро: {macro_layer.get('label', '?')} ({macro_layer.get('score', 0):+.2f})"
        if general_layer:
            macro_text += f"\n    Общие: {general_layer.get('label', '?')} ({general_layer.get('score', 0):+.2f})"
        sectors_layer = by_layer.get('sectors', {})
        if sectors_layer:
            macro_text += f"\n    По секторам:"
            for sector_name, sector_data in sectors_layer.items():
                macro_text += f"\n      - {sector_name}: {sector_data.get('label', '?')} ({sector_data.get('score', 0):+.2f})"
    
    # Критические события
    critical = macro_context.get('critical_events', [])
    if critical:
        macro_text += f"\n\n  ⚠️ КРИТИЧЕСКИЕ СОБЫТИЯ:"
        for ev in critical[:5]:
            macro_text += f"\n    - {ev.get('date', '?')}: {ev.get('event', '?')[:60]} [{ev.get('impact', '?')}]"
    
    focus = macro_context.get('focus_sectors', {})
    for sector, direction in focus.items():
        macro_text += f"\n    - {sector}: {direction}"
    
    system_prompt = """Ты — старший трейдер российского фондового рынка.
На основе макро-контекста, сигналов сканера и новостей определи ОПТИМАЛЬНУЮ стратегию.

Отвечай СТРОГО в формате JSON (без markdown):
{
    "strategy": "SINGLE_LONG/SINGLE_SHORT/PAIR/NEUTRAL",
    "market_view": "твоё видение рынка (2-3 предложения)",
    "selected": [
        {
            "ticker": "...",
            "direction": "LONG/SHORT",
            "size": 0.0-1.0,
            "entry": 100.0,
            "stop": 98.0,
            "target": 105.0,
            "reason": "обоснование",
            "trigger": "при какой цене/событии входить"
        }
    ],
    "capital_allocation": {
        "long": 0.0-1.0,
        "short": 0.0-1.0,
        "cash": 0.0-1.0
    },
    "alternative_tickers": {
        "LONG": ["..."],
        "SHORT": ["..."]
    },
    "reasoning": "полное обоснование стратегии"
}

СТРАТЕГИИ:
- SINGLE_LONG: только LONG (если уверен в росте)
- SINGLE_SHORT: только SHORT (если уверен в падении)
- PAIR: LONG + SHORT (дельта-нейтрально)
- NEUTRAL: кэш 100% (если не уверен)

ПРАВИЛА:
- Выбирай 2-5 тикеров
- size: 0.0-1.0 (доля капитала на сделку)
- Обязательно указывай entry, stop, target, trigger
- Учитывай макро, новости, календарь
"""
    
    user_prompt = f"""{macro_text}

🔴 SHORT-СИГНАЛЫ СКАНЕРА ({len(short_signals)}):
{format_scanner_signals(short_signals)}

🟢 LONG-СИГНАЛЫ СКАНЕРА ({len(long_signals)}):
{format_scanner_signals(long_signals)}

📊 ВСЕ ТИКЕРЫ РЫНКА РФ (97):
{format_all_tickers_brief(scanner_signals)}

📅 КАЛЕНДАРЬ (7 дней):
{format_calendar(calendar_data)}

ЗАДАЧА:
Определи оптимальную стратегию на сегодня.

Верни ТОЛЬКО JSON.
"""
    
    print("🤖 Отправка в DeepSeek...")
    print(f"   Размер промпта: ~{len(system_prompt + user_prompt)} символов")
    
    try:
        response = client.chat.completions.create(
            model=AITUNNEL_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=6000,
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        
        result = json.loads(content)
        return result
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")
        return None


# ==============================================================================
# ВЫВОД СТРАТЕГИИ
# ==============================================================================

def print_final_strategy(strategy, macro_context):
    """Красивый вывод стратегии"""
    print()
    print("="*70)
    print("🎯 ФИНАЛЬНАЯ СТРАТЕГИЯ")
    print("="*70)
    print()
    
    if not strategy:
        print("❌ Не удалось получить стратегию")
        return
    
    print(f"📊 Рынок: {macro_context.get('market_phase', '?')}")
    print(f"🎯 Стратегия: {strategy.get('strategy', '?')}")
    print(f"💡 Видение: {strategy.get('market_view', '')}")
    print()
    
    selected = strategy.get('selected', [])
    
    if not selected:
        print("⛔ Сделок нет — кэш 100%")
        print(f"📝 {strategy.get('reasoning', '')}")
        return
    
    print("═"*70)
    print("📋 ВЫБРАННЫЕ СДЕЛКИ:")
    print("═"*70)
    
    for i, s in enumerate(selected, 1):
        emoji = '🟢' if s.get('direction') == 'LONG' else '🔴'
        print(f"\n{i}. {emoji} {s.get('ticker', '?')} — {s.get('direction', '?')}")
        print(f"   Размер: {s.get('size', 0)*100:.0f}%")
        print(f"   📍 Вход: {s.get('entry', '?')}₽")
        print(f"   🛑 Стоп: {s.get('stop', '?')}₽")
        print(f"   🎯 Цель: {s.get('target', '?')}₽")
        print(f"   ⚡ Триггер: {s.get('trigger', '')}")
        print(f"   📝 {s.get('reason', '')}")
    
    # Распределение
    alloc = strategy.get('capital_allocation', {})
    print()
    print("═"*70)
    print("💰 РАСПРЕДЕЛЕНИЕ КАПИТАЛА:")
    print("═"*70)
    print(f"   🟢 LONG:  {alloc.get('long', 0)*100:.0f}%")
    print(f"   🔴 SHORT: {alloc.get('short', 0)*100:.0f}%")
    print(f"   💵 Кэш:   {alloc.get('cash', 0)*100:.0f}%")
    
    # Альтернативы
    alt = strategy.get('alternative_tickers', {})
    if alt.get('LONG') or alt.get('SHORT'):
        print()
        print("═"*70)
        print("🎯 АЛЬТЕРНАТИВЫ:")
        print("═"*70)
        if alt.get('LONG'):
            print(f"   🟢 LONG:  {', '.join(alt['LONG'])}")
        if alt.get('SHORT'):
            print(f"   🔴 SHORT: {', '.join(alt['SHORT'])}")
    
    # Обоснование
    print()
    print("═"*70)
    print("📝 ОБОСНОВАНИЕ:")
    print("═"*70)
    print(f"{strategy.get('reasoning', '')}")
    
    print()
    print("="*70)


# ==============================================================================
# ЗАПУСК
# ==============================================================================

def main():
    # УРОВЕНЬ 1: Общий фон
    macro_context = analyze_macro_context()
    
    if not macro_context:
        print("❌ Не удалось получить макро-контекст")
        sys.exit(1)
    
    # Загружаем сигналы сканера
    print("="*70)
    print("🧠 УРОВЕНЬ 2: ВЫБОР СТРАТЕГИИ")
    print("="*70)
    print()
    
    print("📂 Загрузка сигналов сканера...")
    scanner_data = load_json('scanner_signals.json')
    
    if not scanner_data or not scanner_data.get('signals'):
        print("⚠️ Нет сигналов сканера — работаем только по макро")
        scanner_signals = []
    else:
        scanner_signals = scanner_data['signals']
        print(f"   ✅ Сигналов: {len(scanner_signals)}")
    
    print()
    
    # Загружаем остальной контекст
    macro_current = load_json('macro_data.json')
    macro_history = load_json('macro_history.json')
    calendar_data = load_json('calendar.json')
    
    # УРОВЕНЬ 2: Стратегия
    strategy = analyze_strategy(
        scanner_signals, macro_context, macro_current,
        macro_history, calendar_data
    )
    
    if not strategy:
        print("❌ Не удалось получить стратегию")
        sys.exit(1)
    
    # Сохраняем
    output = {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'macro_context': macro_context,
        'strategy': strategy,
    }
    
    with open(STRATEGY_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # Выводим
    print_final_strategy(strategy, macro_context)
    
    print(f"💾 Сохранено: {STRATEGY_OUTPUT}")


if __name__ == "__main__":
    main()
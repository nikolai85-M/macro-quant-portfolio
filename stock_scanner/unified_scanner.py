# UNIFIED_BLOCK_SYSTEM.py
# Единая система торговли по ордер-блокам с вероятностью, Stochastic RSI (TV), объёмами и трекингом
# Версия 2.0 — с обновлённым макроанализом, логированием, конфигурацией

import sys
import os
import json
import time
import logging
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import yaml
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

# ================== ЗАГРУЗКА КОНФИГУРАЦИИ ==================
def load_config(config_path="config.yaml"):
    """Загружает конфигурацию из YAML-файла с поиском в текущей папке и на уровень выше."""
    # Сначала ищем в текущей папке
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    # Пробуем на уровень выше
    parent_config = os.path.join(os.path.dirname(__file__), '..', config_path)
    if os.path.exists(parent_config):
        with open(parent_config, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    raise FileNotFoundError(f"config.yaml не найден! Искали в:\n  - {os.path.abspath(config_path)}\n  - {os.path.abspath(parent_config)}")

# Загружаем конфиг
CONFIG = load_config()

# ================== НАСТРОЙКА ЛОГИРОВАНИЯ ==================
def setup_logging():
    """Настраивает систему логирования"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_format = CONFIG.get('logging', {}).get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    date_format = '%Y-%m-%d %H:%M:%S'
    log_level = getattr(logging, CONFIG.get('logging', {}).get('level', 'INFO'))
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.FileHandler(log_dir / "block_scanner.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Подавляем излишние логи от библиотек
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

logger = setup_logging()

# ================== RETRY-ДЕКОРАТОР ==================
def retry(max_attempts=3, delay=1, backoff=2):
    """Декоратор для повторных попыток при сбоях API"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(f"Попытка {attempt+1}/{max_attempts} для {func.__name__} не удалась: {e}. Повтор через {current_delay}с...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"Функция {func.__name__} не удалась после {max_attempts} попыток: {e}")
            raise last_exception
        return wrapper
    return decorator

# Устанавливаем кодировку для вывода в Windows
if sys.platform == 'win32':
    import locale
    locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')

# Добавляем путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Импортируем базовые компоненты (старые файлы, их не трогаем)
from ORDER_BLOCK_020326 import (
    OrderBlockScanner,
    SIGNALS_DIR, CHARTS_DIR, DATA_DIR, LOGS_DIR,
    EndOfDayAnalyzer,
    timedelta, pd, np
)
from fundamental_filter import FundamentalFilterDynamic
from watchlist_manager import WatchlistManager
from watchlist_history import WatchlistHistory
from block_tracker import BlockDemoTracker
from sector_mapping import get_sector
from tinkoff.invest import Client, CandleInterval

logger.info("🚀 ЕДИНЫЙ БЛОЧНЫЙ СКАНЕР v2.0 (Stoch RSI TV + ОБЪЁМЫ + ТРЕКИНГ)")

# ==============================================================================
# УПРАВЛЕНИЕ ДАВНОСТЬЮ ДАННЫХ
# ==============================================================================

class DataFreshnessChecker:
    """Проверяет давность данных и уведомляет о необходимости обновления"""
    
    def __init__(self):
        self.meta_file = "data_metadata.json"
        self.load_metadata()
    
    def load_metadata(self):
        if os.path.exists(self.meta_file):
            with open(self.meta_file, 'r', encoding='utf-8') as f:
                self.meta = json.load(f)
        else:
            self.meta = {
                "last_update": {},
                "next_update": {},
                "sources": {}
            }
    
    def save_metadata(self):
        with open(self.meta_file, 'w', encoding='utf-8') as f:
            json.dump(self.meta, f, indent=2, ensure_ascii=False)
    
    def check_and_notify(self):
        """Проверяет все данные и возвращает, что нужно обновить"""
        today = datetime.now().date()
        needs_update = {
            'macro': False,
            'sector_ratings': False,
            'fundamentals': False
        }
        notifications = []
        
        # 1. Макро (раз в 2 недели)
        last_macro = self.meta.get('last_update', {}).get('macro')
        if last_macro:
            last_date = datetime.strptime(last_macro, '%Y-%m-%d').date()
            if today - last_date > timedelta(days=14):
                needs_update['macro'] = True
                notifications.append("📊 МАКРОДАННЫЕ — пора обновить (раз в 2 недели)")
        else:
            needs_update['macro'] = True
        
        # 2. Секторальные рейтинги (раз в квартал)
        last_sector = self.meta.get('last_update', {}).get('sector_ratings')
        if last_sector:
            last_date = datetime.strptime(last_sector, '%Y-%m-%d').date()
            if today - last_date > timedelta(days=90):
                needs_update['sector_ratings'] = True
                notifications.append("📁 СЕКТОРАЛЬНЫЕ РЕЙТИНГИ — обновите файл sector_ratings.json")
        
        # 3. Фундаментал компаний (раз в месяц)
        last_fund = self.meta.get('last_update', {}).get('fundamentals')
        if last_fund:
            last_date = datetime.strptime(last_fund, '%Y-%m-%d').date()
            if today - last_date > timedelta(days=30):
                needs_update['fundamentals'] = True
                notifications.append("📊 ФУНДАМЕНТАЛ КОМПАНИЙ — обновите файл dohod_fundamentals.json")
        
        if notifications:
            logger.warning("ТРЕБУЕТСЯ ОБНОВЛЕНИЕ ДАННЫХ:")
            for n in notifications:
                logger.warning(f"  • {n}")
        
        return needs_update
    
    def update_macro(self):
        self.meta['last_update']['macro'] = datetime.now().strftime('%Y-%m-%d')
        self.save_metadata()
        logger.info("Дата макроданных обновлена")
    
    def update_sector_ratings(self):
        self.meta['last_update']['sector_ratings'] = datetime.now().strftime('%Y-%m-%d')
        self.save_metadata()
        logger.info("Дата секторальных рейтингов обновлена")
    
    def update_fundamentals(self):
        self.meta['last_update']['fundamentals'] = datetime.now().strftime('%Y-%m-%d')
        self.save_metadata()
        logger.info("Дата фундаментальных данных обновлена")


# ==============================================================================
# РУЧНОЙ ВВОД МАКРОДАННЫХ
# ==============================================================================

def input_all_macro_data():
    """Расширенный ввод макро и глобальных данных"""
    logger.info("ВВОД МАКРОДАННЫХ")
    
    data = {}
    
    print("\n" + "="*80)
    print("📊 ВВЕДИТЕ КЛЮЧЕВЫЕ МАКРОПОКАЗАТЕЛИ")
    print("="*80)
    
    print("\n📍 ВНУТРЕННИЕ ФАКТОРЫ РФ:")
    data['cbr_rate'] = float(input("  • Ставка ЦБ РФ (%): ") or 21)
    data['inflation'] = float(input("  • Инфляция РФ (%, годовые): ") or 8)
    data['brent'] = float(input("  • Нефть Brent ($): ") or 65)
    data['cnyrub'] = float(input("  • Курс CNY/RUB (Юань): ") or 12.8)
    data['rvi'] = float(input("  • RVI (Индекс волатильности MOEX): ") or 28)
    
    print("\n🌍 ГЕОПОЛИТИЧЕСКАЯ НАПРЯЖЕННОСТЬ:")
    print("   (1-2: спокойно, 3-4: риски, 5-6: напряжённо, 7-8: высоко, 9-10: кризис)")
    data['geopolitics'] = int(input("  • Оценка (1-10): ") or 6)
    
    print("\n🌐 ГЛОБАЛЬНЫЕ ФАКТОРЫ:")
    data['dxy'] = float(input("  • DXY (Индекс доллара): ") or 104)
    data['ust10y'] = float(input("  • UST10Y (Доходность 10-летних трежерис, %): ") or 4.3)
    data['gold'] = float(input("  • GOLD (Золото, $/унц): ") or 2400)
    data['fed_rate'] = float(input("  • Ставка ФРС (%): ") or 4.5)
    
    return data


# ==============================================================================
# АНАЛИЗАТОР РЫНКА
# ==============================================================================

class MarketAnalyzer:
    """Анализ рыночного контекста с учётом санкционной изоляции"""
    
    def __init__(self, macro_data):
        self.data = macro_data
        self.cbr_thresholds = CONFIG['market']['cbr_thresholds']
        self.rvi_thresholds = CONFIG['market']['rvi_thresholds']
        self.cny_thresholds = CONFIG['market']['cny_thresholds']
        self.brent_thresholds = CONFIG['market']['brent_thresholds']
        self.dxy_thresholds = CONFIG['market']['dxy_thresholds']
        self.geopolitics_max = CONFIG['market']['geopolitics_max']

    def analyze(self):
        score = 50
        reasons = []

        # Ставка ЦБ
        rate = self.data.get('cbr_rate', 20)
        if rate <= 15:
            score += 15
            reasons.append(f"✅ Ставка ЦБ низкая ({rate}%)")
        elif rate >= 20:
            score -= 20
            reasons.append(f"❌ Ставка ЦБ высокая ({rate}%)")
        else:
            reasons.append(f"🟡 Ставка ЦБ умеренная ({rate}%)")

        # Инфляция
        inf = self.data.get('inflation', 7)
        if inf <= 6:
            score += 10
            reasons.append(f"✅ Инфляция низкая ({inf}%)")
        elif inf >= 9:
            score -= 15
            reasons.append(f"❌ Инфляция высокая ({inf}%)")

        # Нефть
        oil = self.data.get('brent', 70)
        if oil >= self.brent_thresholds['high']:
            score += 10
            reasons.append(f"✅ Нефть дорогая (${oil})")
        elif oil <= self.brent_thresholds['low']:
            score -= 10
            reasons.append(f"❌ Нефть дешёвая (${oil})")

        # Курс юаня
        cny = self.data.get('cnyrub', 12.8)
        if cny >= self.cny_thresholds['strong']:
            score += 15
            reasons.append(f"✅ Юань дорогой ({cny} ₽)")
        elif cny <= self.cny_thresholds['weak']:
            score -= 15
            reasons.append(f"❌ Юань дешёвый ({cny} ₽)")
        else:
            reasons.append(f"🟡 Курс юаня нейтральный ({cny} ₽)")

        # Волатильность RVI
        rvi = self.data.get('rvi', 25)
        if rvi <= 20:
            score += 5
            reasons.append(f"✅ Волатильность низкая (RVI {rvi})")
        elif rvi >= self.rvi_thresholds['emergency']:
            score -= 20
            reasons.append(f"❌ Волатильность высокая (RVI {rvi})")

        # Золото
        gold = self.data.get('gold', 2400)
        if gold >= 2600:
            score -= 10
            reasons.append(f"⚠️ Золото >$2600")

        # DXY и ФРС
        dxy = self.data.get('dxy', 104)
        fed = self.data.get('fed_rate', 4.5)
        if dxy >= 106 or fed >= 5.0:
            score -= 10
            reasons.append(f"⚠️ Сильный доллар / высокая ставка ФРС")

        # Геополитика
        geo = self.data.get('geopolitics', 5)
        if geo >= self.geopolitics_max:
            score -= 15
            reasons.append(f"❌ Геополитика напряжённая ({geo}/10)")

        score = max(0, min(100, score))
        
        if score >= 60:
            trend = 'UP'
        elif score <= 40:
            trend = 'DOWN'
        else:
            trend = 'NEUTRAL'

        return {
            'trend': trend,
            'market_score': score,
            'reasons': reasons,
            'cbr_rate': rate,
            'inflation': inf,
            'brent': oil,
            'cnyrub': cny,
            'geopolitics': geo,
            'rvi': rvi
        }


# ==============================================================================
# АНАЛИЗАТОР ДИВИДЕНДОВ
# ==============================================================================

class DividendAnalyzer:
    """Анализирует влияние дивидендов на позицию"""
    
    def __init__(self, token):
        self.token = token
    
    @retry(max_attempts=2, delay=1)
    def get_dividend_info(self, figi):
        """Получает информацию о предстоящих дивидендах"""
        try:
            with Client(self.token) as client:
                dividends = client.instruments.get_dividends(figi=figi)
                
                if dividends.dividends:
                    latest = dividends.dividends[0]
                    div_amount = latest.dividend_net.units + latest.dividend_net.nano / 1e9
                    
                    if hasattr(latest.record_date, 'date'):
                        record_date = latest.record_date.date()
                    else:
                        record_date = latest.record_date
                    
                    today = datetime.now().date()
                    days_to_record = max(0, (record_date - today).days)
                    
                    return {
                        'amount': div_amount,
                        'record_date': record_date,
                        'days_to_record': days_to_record,
                        'payment_date': latest.payment_date
                    }
            return None
        except Exception as e:
            logger.warning(f"Не удалось получить дивиденды для {figi}: {e}")
            return None
    
    def analyze_impact(self, current_price, block_low, block_high, dividend_yield, direction):
        """Анализирует влияние дивидендного гэпа на позицию"""
        price_after_gap = current_price * (1 - dividend_yield / 100)
        
        if direction == 'LONG':
            if price_after_gap >= block_low:
                return 'help', "Гэп помогает — цена войдёт в блок", 1.3
            elif price_after_gap >= block_low * 0.98:
                return 'neutral', "Гэп не мешает — цена у границы блока", 1.0
            else:
                return 'harm', "Гэп мешает — цена уйдёт ниже блока", 0.5
        else:
            if price_after_gap <= block_high:
                return 'help', "Гэп помогает — цена останется в блоке", 1.3
            elif price_after_gap <= block_high * 1.02:
                return 'neutral', "Гэп не мешает — цена у границы блока", 1.0
            else:
                return 'harm', "Гэп мешает — цена уйдёт выше блока", 0.5

# ==============================================================================
# STOCHASTIC RSI (КАК В TRADINGVIEW)
# ==============================================================================

def calculate_stoch_rsi_tv(series, rsi_length=None, stoch_length=None, smooth_k=None, smooth_d=None):
    """
    Stochastic RSI как в TradingView
    """
    # Берём параметры из конфига, если не переданы явно
    indicators = CONFIG['indicators']
    if rsi_length is None:
        rsi_length = indicators['rsi_length']
    if stoch_length is None:
        stoch_length = indicators['stoch_length']
    if smooth_k is None:
        smooth_k = indicators['smooth_k']
    if smooth_d is None:
        smooth_d = indicators['smooth_d']
    
    # 1. RSI
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    
    avg_gain = gain.ewm(alpha=1/rsi_length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/rsi_length, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    # 2. Stochastic от RSI
    lowest_rsi = rsi.rolling(window=stoch_length, min_periods=stoch_length).min()
    highest_rsi = rsi.rolling(window=stoch_length, min_periods=stoch_length).max()
    
    denom = highest_rsi - lowest_rsi
    stoch = np.where(
        denom != 0,
        (rsi - lowest_rsi) / denom * 100,
        50.0
    )
    stoch = pd.Series(stoch, index=rsi.index)
    
    # 3. SMA для K и D
    k = stoch.rolling(window=smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(window=smooth_d, min_periods=smooth_d).mean()
    
    return k, d


# ==============================================================================
# КЛАСС ДЛЯ ОЦЕНКИ ВЕРОЯТНОСТИ
# ==============================================================================

class BlockProbabilityAnalyzer:
    """Анализирует ордер-блоки и рассчитывает вероятность направления"""
    
    def __init__(self, market_context=None, sector_scores=None, fundamentals=None):
        self.market_context = market_context or {}
        self.sector_scores = sector_scores or {}
        self.fundamentals = fundamentals or {}
        # Берём пороги из конфига
        self.geopolitics_max = CONFIG['market'].get('geopolitics_max', 7)
        self.sector_strong = CONFIG.get('scoring', {}).get('sector_alignment', {}).get('strong_threshold', 60)
        self.sector_weak = CONFIG.get('scoring', {}).get('sector_alignment', {}).get('weak_threshold', 40)
    
    def _safe_value(self, val, default=0):
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            try:
                clean = val.replace('+', '').replace('-', '').strip()
                return float(clean) if clean else default
            except:
                return default
        return default
    
    def analyze_block(self, block, ticker, sector_code, current_price):
        probability = 50
        reasons = []
    
        # 1. ТИП БЛОКА
        if block['type'] == 'bull':
            probability += 15
            reasons.append(f"Бычий блок (+15)")
            direction = 'UP'
        else:
            probability -= 15
            reasons.append(f"Медвежий блок (-15)")
            direction = 'DOWN'
    
        # 2. СИЛА БЛОКА (метод)
        method = block.get('method', 'unknown')
        if method == 'both':
            probability += 10 if direction == 'UP' else -10
            reasons.append(f"Совпадение методов (+10)")
        elif method in ['our', 'luxalgo']:
            probability += 5 if direction == 'UP' else -5
            reasons.append(f"Один метод (+5)")
    
        # 3. ВОЗРАСТ БЛОКА
        age = block.get('age', 30)
        if age is None:
            age = 30
        if age < 10:
            probability += 10 if direction == 'UP' else -10
            reasons.append(f"Свежий блок ({age} дн.) (+10)")
        elif age > 30:
            probability -= 10 if direction == 'UP' else -10
            reasons.append(f"Старый блок ({age} дн.) (-10)")
    
        # 4. РЫНОЧНЫЙ ТРЕНД
        market_trend = self.market_context.get('trend', 'neutral')
        market_score = self.market_context.get('market_score', 50)
    
        if market_trend == 'UP':
            if direction == 'UP':
                bonus = min(25, int(market_score / 100 * 25))
                probability += bonus
                reasons.append(f"Рынок растет (балл {market_score}) (+{bonus})")
            else:
                probability -= 15
                reasons.append(f"Рынок растет, SHORT против тренда (-15)")
        elif market_trend == 'DOWN':
            if direction == 'DOWN':
                bonus = min(25, int((100 - market_score) / 100 * 25))
                probability += bonus
                reasons.append(f"Рынок падает (балл {market_score}) (+{bonus})")
            else:
                probability -= 15
                reasons.append(f"Рынок падает, LONG против тренда (-15)")
    
        # 5. ГЕОПОЛИТИКА
        geopolitics = self.market_context.get('geopolitics', 5)
        if geopolitics > self.geopolitics_max and direction == 'DOWN':
            probability += 10
            reasons.append(f"Высокая геополитика (+10)")
        elif geopolitics > self.geopolitics_max and direction == 'UP':
            probability -= 10
            reasons.append(f"Геополитика давит на рост (-10)")
    
        # 6. СЕКТОРАЛЬНЫЙ ФОН
        sector_score = self.sector_scores.get(sector_code, {}).get('score', 50)
        if sector_score is None:
            sector_score = 50
    
        if sector_score >= self.sector_strong:
            if direction == 'UP':
                probability += 10
                reasons.append(f"Сектор сильный ({sector_score}) (+10)")
            else:
                probability -= 10
                reasons.append(f"SHORT в сильном секторе (-10)")
        elif sector_score <= self.sector_weak:
            if direction == 'DOWN':
                probability += 10
                reasons.append(f"Сектор слабый ({sector_score}) (+10)")
            else:
                probability -= 10
                reasons.append(f"LONG в слабом секторе (-10)")
    
        # 7. ФУНДАМЕНТАЛ
        fund = self.fundamentals.get(ticker, {})
        dcf = self._safe_value(fund.get('dcf_potential', 0))
        if dcf > 15 and direction == 'UP':
            probability += 10
            reasons.append(f"DCF={dcf} 🔥 (+10)")
        elif dcf < 5 and direction == 'DOWN':
            probability += 10
            reasons.append(f"DCF низкий ({dcf}) (+10)")
    
        div = self._safe_value(fund.get('dividend_strategy', 0))
        if div > 0.7 and direction == 'UP':
            probability += 5
            reasons.append(f"Дивиденды {div} (+5)")
    
        # 8. ТЕКУЩАЯ ПОЗИЦИЯ
        block_low = self._safe_value(block.get('low', 0))
        block_high = self._safe_value(block.get('high', 0))
    
        if direction == 'UP':
            if block_low > 0:
                distance = (current_price - block_low) / current_price * 100
                if 0 < distance < 3:
                    probability += 10
                    reasons.append(f"Цена у блока ({distance:.1f}%) (+10)")
                elif distance < 0:
                    probability -= 20
                    reasons.append(f"Цена ниже блока (-20)")
        else:
            if block_high > 0:
                distance = (block_high - current_price) / current_price * 100
                if 0 < distance < 3:
                    probability += 10
                    reasons.append(f"Цена у блока ({distance:.1f}%) (+10)")
                elif distance < 0:
                    probability -= 20
                    reasons.append(f"Цена выше блока (-20)")
    
        probability = max(0, min(100, probability))
    
        # Определение типа сигнала
        if probability >= 60:
            signal_type = 'BOUNCE'
        elif probability <= 40:
            signal_type = 'BREAKOUT'
        else:
            signal_type = None
    
        return {
            'direction': direction,
            'probability': int(probability),
            'signal_type': signal_type,
            'reasons': reasons,
            'block_type': block['type'],
            'block_age': age,
            'block_method': method,
            'block_low': block_low,
            'block_high': block_high
        }


# ==============================================================================
# РАСЧЁТ ПОТЕНЦИАЛА
# ==============================================================================

def calculate_potential(current_price, next_block_low, next_block_high, direction, dcf, div_strategy, sector_score):
    if direction == 'UP':
        if next_block_low and next_block_low > current_price:
            tech_potential = (next_block_low - current_price) / current_price * 100
        else:
            tech_potential = 0
    else:
        if next_block_high and next_block_high < current_price:
            tech_potential = (current_price - next_block_high) / current_price * 100
        else:
            tech_potential = 0
    
    fund_potential = (dcf or 0) + (div_strategy or 0) + (sector_score - 50) / 10
    total_potential = (tech_potential * 0.6) + (fund_potential * 0.4)
    
    return round(total_potential, 2), tech_potential, fund_potential


def get_position_size(potential):
    """Возвращает размер позиции и эмодзи на основе потенциала"""
    if potential >= 15:
        return 2.0, "🔥🔥🔥"
    elif potential >= 10:
        return 1.5, "🔥🔥"
    elif potential >= 5:
        return 1.0, "🔥"
    else:
        return 0.5, "📊"


# ==============================================================================
# АНАЛИЗАТОР СЕКТОРОВ
# ==============================================================================

class SectorAnalyzer:
    def __init__(self, macro_data=None):
        self.filter = FundamentalFilterDynamic()
        self.macro_data = macro_data or {}
        self.sectors = CONFIG.get('sectors', {
            'oil_gas': 'Нефть и газ', 'metals': 'Металлы', 'finance': 'Финансы',
            'consumer': 'Потребление', 'tech': 'Технологии', 'energy': 'Энергетика',
            'chemicals': 'Химия', 'developers': 'Застройщики', 'transport': 'Транспорт',
            'telecom': 'Телеком'
        })
        
        # Маппинг из конфига, если есть, иначе пустой
        self.ticker_to_sector = {
            'GAZP': 'oil_gas', 'LKOH': 'oil_gas', 'ROSN': 'oil_gas',
            'TATN': 'oil_gas', 'SNGS': 'oil_gas', 'NVTK': 'oil_gas',
            'SBER': 'finance', 'VTBR': 'finance', 'MOEX': 'finance',
            'CBOM': 'finance', 'BSPB': 'finance', 'SBERP': 'finance',
            'MGNT': 'consumer', 'FIVE': 'consumer', 'LENT': 'consumer',
            'YNDX': 'tech', 'OZON': 'tech', 'VKCO': 'tech',
            'HYDR': 'energy', 'IRAO': 'energy', 'FEES': 'energy',
            'PHOR': 'chemicals', 'AKRN': 'chemicals',
            'PIKK': 'developers', 'LSRG': 'developers', 'SMLT': 'developers',
            'AFLT': 'transport', 'FLOT': 'transport', 'NMTP': 'transport',
            'MTSS': 'telecom', 'RTKM': 'telecom',
            'GMKN': 'metals', 'PLZL': 'metals', 'RUAL': 'metals',
            'ALRS': 'metals', 'CHMF': 'metals', 'NLMK': 'metals',
            'MAGN': 'metals', 'X5': 'consumer', 'HEAD': 'tech',
            'POSI': 'tech', 'T': 'finance',
        }
    
    def get_sector_code(self, ticker):
        return self.ticker_to_sector.get(ticker, 'unknown')
    
    def get_sector_name(self, sector_code):
        return self.sectors.get(sector_code, sector_code)
    
    def get_sector_factors(self, sector_code):
        """Возвращает факторы, повлиявшие на оценку сектора"""
        factors = []
        cbr_thresholds = CONFIG['market']['cbr_thresholds']
        brent_thresholds = CONFIG['market']['brent_thresholds']
        
        if sector_code == 'oil_gas':
            brent = self.macro_data.get('brent', 70)
            usdrub = self.macro_data.get('usdrub', 85)
            if brent > brent_thresholds['high']:
                factors.append(f"🛢️ Нефть ${brent} (+10)")
            elif brent < brent_thresholds['low']:
                factors.append(f"🛢️ Нефть ${brent} (-10)")
        elif sector_code == 'finance':
            rate = self.macro_data.get('cbr_rate', 15)
            if rate <= cbr_thresholds['tmos_exit']:
                factors.append(f"🏦 Ставка ЦБ {rate}% (+15)")
            elif rate >= cbr_thresholds['emergency']:
                factors.append(f"🏦 Ставка ЦБ {rate}% (-20)")
            else:
                factors.append(f"🏦 Ставка ЦБ {rate}% (0)")
        elif sector_code == 'metals':
            gold = self.macro_data.get('gold', 2400)
            if gold > 2600:
                factors.append(f"🥇 Золото ${gold} (+10)")
        elif sector_code == 'energy':
            factors.append("⚡ Стабильный спрос")
        elif sector_code == 'telecom':
            factors.append("📱 Защитный сектор")
        
        return factors
    
    def analyze_all_sectors(self):
        sector_scores = {}
        for sector_code, sector_name in self.sectors.items():
            try:
                score = self.filter.get_sector_score(sector_code)
                bias = self.filter.get_sector_bias(sector_code)
                factors = self.get_sector_factors(sector_code)
                
                sector_scores[sector_code] = {
                    'name': sector_name,
                    'score': score,
                    'bias': bias,
                    'factors': factors
                }
            except Exception as e:
                logger.warning(f"Ошибка анализа сектора {sector_name}: {e}")
                sector_scores[sector_code] = {
                    'name': sector_name, 
                    'score': 50, 
                    'bias': 'NEUTRAL',
                    'factors': []
                }
        return sector_scores


# ==============================================================================
# ОСНОВНОЙ СКАНЕР
# ==============================================================================

class UnifiedBlockScanner(OrderBlockScanner):
    def __init__(self, tickers_to_scan=None, max_tickers=150, fundamentals=None, macro_data=None):
        super().__init__(tickers_to_scan, max_tickers)
        
        self.fundamentals = fundamentals or {}
        self.macro_data = macro_data or {}
        
        self.sector_analyzer = SectorAnalyzer(macro_data=self.macro_data)
        self.market_analyzer = MarketAnalyzer(macro_data)
        self.dividend_analyzer = DividendAnalyzer(os.getenv('TINKOFF_TOKEN'))
        
        self.sector_scores = {}
        self.market_context = {}
        
        # Настройки из конфига
        self.min_potential = CONFIG.get('scoring', {}).get('potential_high', 0.5)
        self.multipliers = CONFIG['position_multipliers']
        
        # Инициализация трекеров
        try:
            self.block_tracker = BlockDemoTracker()
            self.watchlist_manager = WatchlistManager()
            self.watchlist_history = WatchlistHistory()
            self.enable_tracking = True
            self.enable_watchlist = True
        except Exception as e:
            logger.warning(f"Ошибка инициализации трекеров: {e}")
            self.block_tracker = None
            self.watchlist_manager = None
            self.watchlist_history = None
            self.enable_tracking = False
            self.enable_watchlist = False
        
        # Кэш для индекса
        self._cached_imoex = None
        self._cached_phase = None
        
        logger.info("🚀 ЕДИНЫЙ БЛОЧНЫЙ СКАНЕР v2.0")
        logger.info(f"📊 Трекинг позиций: {'ВКЛЮЧЕН' if self.enable_tracking else 'ВЫКЛЮЧЕН'}")
        logger.info(f"📋 Вотчлист: {'ВКЛЮЧЕН' if self.enable_watchlist else 'ВЫКЛЮЧЕН'}")
        if self.macro_data:
            logger.info(f"📈 Макро: ставка={self.macro_data.get('cbr_rate')}%, юань={self.macro_data.get('cnyrub')}, нефть={self.macro_data.get('brent')}$")
        logger.info(f"🌍 Геополитика: {self.macro_data.get('geopolitics', 5)}/10")
        if self.fundamentals:
            logger.info(f"📊 Загружено фундаментальных данных по {len(self.fundamentals)} компаниям")
    
    def calculate_stoch_rsi_for_df(self, df, rsi_length=None, stoch_length=None, smooth_k=None, smooth_d=None):
        """Рассчитывает Stochastic RSI для DataFrame"""
        k, d = calculate_stoch_rsi_tv(df['close'], rsi_length, stoch_length, smooth_k, smooth_d)
        df['StochRSI_K'] = k
        df['StochRSI_D'] = d
        return df
    
    def get_block_strength_by_position(self, df, start_pos, end_pos):
        """Рассчитывает силу блока на основе объёмов"""
        if start_pos is None or end_pos is None:
            return 'unknown', 1.0, "объём не определён"
    
        if 'volume' not in df.columns:
            return 'unknown', 1.0, "нет данных об объёме"
    
        try:
            block_volume = df['volume'].iloc[start_pos:end_pos+1].sum()
            candles_count = end_pos - start_pos + 1
        
            avg_volume = df['volume'].rolling(20, min_periods=1).mean().iloc[end_pos]
        
            if avg_volume == 0:
                return 'unknown', 1.0, "нулевой объём"
        
            volume_ratio = block_volume / (avg_volume * candles_count)
        
            if volume_ratio > 2.0:
                return 'very_strong', self.multipliers.get('strong_block', 1.4), f"💪🔥 объём x{volume_ratio:.1f} (очень сильный)"
            elif volume_ratio > 1.2:
                return 'strong', self.multipliers.get('strong_block', 1.2), f"💪📈 объём x{volume_ratio:.1f} (сильный)"
            elif volume_ratio > 0.8:
                return 'normal', self.multipliers.get('normal_block', 1.0), f"📊 объём x{volume_ratio:.1f} (норма)"
            else:
                return 'weak', self.multipliers.get('weak_block', 0.7), f"⚠️ объём x{volume_ratio:.1f} (слабый)"
            
        except Exception as e:
            logger.debug(f"Ошибка расчёта силы блока: {e}")
            return 'unknown', 1.0, "ошибка расчёта"
    
    def find_order_blocks_with_strength(self, df, blocks_dict):
        """Добавляет к блокам информацию о силе по объёмам"""
        enhanced_blocks = {'bull': [], 'bear': []}
        
        for block_type in ['bull', 'bear']:
            for block in blocks_dict[block_type]:
                block_low = block.get('low')
                block_high = block.get('high')
                block_date = block.get('date')
                
                end_pos = len(df) - 1
                
                if block_date and 'date' in df.columns:
                    try:
                        date_mask = df['date'] == block_date
                        if date_mask.any():
                            idx = df[date_mask].index[0]
                            end_pos = df.index.get_loc(idx)
                    except:
                        pass
                
                if end_pos == len(df) - 1:
                    try:
                        price_mask = (df['low'] <= block_high) & (df['high'] >= block_low)
                        if price_mask.any():
                            idx = df[price_mask].index[-1]
                            end_pos = df.index.get_loc(idx)
                    except:
                        pass
                
                start_pos = max(0, end_pos - 4)
                
                strength, multiplier, desc = self.get_block_strength_by_position(df, start_pos, end_pos)
                
                enhanced_block = block.copy()
                enhanced_block['strength'] = strength
                enhanced_block['strength_multiplier'] = multiplier
                enhanced_block['strength_desc'] = desc
                
                if 'volume' in df.columns:
                    try:
                        block_vol = df['volume'].iloc[start_pos:end_pos+1].sum()
                        avg_vol = df['volume'].rolling(20, min_periods=1).mean().iloc[end_pos]
                        candles = end_pos - start_pos + 1
                        enhanced_block['volume_ratio'] = block_vol / (avg_vol * candles) if avg_vol > 0 else 0
                    except:
                        enhanced_block['volume_ratio'] = 0
                else:
                    enhanced_block['volume_ratio'] = 0
                
                enhanced_blocks[block_type].append(enhanced_block)
        
        return enhanced_blocks
    
    def deduplicate_blocks(self, blocks, threshold=0.02):
        unique = []
        for block in blocks:
            is_duplicate = False
            for ub in unique:
                if abs(block.get('low', 0) - ub.get('low', 0)) / max(ub.get('low', 1), 1) < threshold:
                    if block.get('strength_multiplier', 1.0) > ub.get('strength_multiplier', 1.0):
                        ub.update(block)
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique.append(block)
        return unique
    
    def get_next_blocks(self, blocks, current_price, direction):
        next_blocks = []
        for b in blocks:
            if direction == 'UP':
                if b.get('low', 0) > current_price:
                    next_blocks.append(b)
            else:
                if b.get('high', 0) < current_price:
                    next_blocks.append(b)
        
        next_blocks.sort(key=lambda x: x['low'] if direction == 'UP' else -x['high'])
        
        tp1 = next_blocks[0] if len(next_blocks) > 0 else None
        tp2 = next_blocks[1] if len(next_blocks) > 1 else None
        tp3 = next_blocks[2] if len(next_blocks) > 2 else None
        
        return tp1, tp2, tp3
    
    def is_block_actual(self, block, current_price, df=None, signal_type='BOUNCE'):
        """Проверяет актуальность блока для входа"""
        if signal_type == 'BOUNCE':
            if block['type'] == 'bull':
                return block['low'] * 0.99 <= current_price <= block['high'] * 1.01
            else:
                return block['low'] * 0.99 <= current_price <= block['high'] * 1.01
        
        elif signal_type == 'BREAKOUT':
            if df is None or len(df) < 20:
                return False
            
            block_low = block['low']
            block_high = block['high']
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            
            if block['type'] == 'bull':
                last_10 = df.iloc[-10:]
                breakout_candles = last_10[last_10['close'] < block_low]
                
                if len(breakout_candles) < 2:
                    return False
                
                breakout_vol = breakout_candles['volume'].mean()
                if breakout_vol < avg_volume * 1.2:
                    return False
                
                distance = abs(current_price - block_low) / current_price
                if distance > 0.02:
                    return False
                
                retest_vol = df['volume'].iloc[-1]
                if retest_vol > avg_volume * 0.8:
                    return False
                
                last_candle = df.iloc[-1]
                if last_candle['close'] > last_candle['open']:
                    return False
                
                return current_price <= block_low * 1.01
                
            else:
                last_10 = df.iloc[-10:]
                breakout_candles = last_10[last_10['close'] > block_high]
                
                if len(breakout_candles) < 2:
                    return False
                
                breakout_vol = breakout_candles['volume'].mean()
                if breakout_vol < avg_volume * 1.2:
                    return False
                
                distance = abs(current_price - block_high) / current_price
                if distance > 0.02:
                    return False
                
                retest_vol = df['volume'].iloc[-1]
                if retest_vol > avg_volume * 0.8:
                    return False
                
                last_candle = df.iloc[-1]
                if last_candle['close'] < last_candle['open']:
                    return False
                
                return current_price >= block_high * 0.99
        
        return False
    
    def check_dividend_block(self, ticker, direction, dividend_info, current_price, block_low, block_high):
        """Проверяет дивиденды и возвращает (warning_message, multiplier)"""
        if dividend_info is None:
            return None, 1.0
        
        days_to_record = dividend_info.get('days_to_record')
        record_date = dividend_info.get('record_date')
        
        if days_to_record is None or record_date is None:
            return None, 1.0
        
        from datetime import date
        today = date.today()
        
        if hasattr(record_date, 'date'):
            record_date = record_date.date()
        
        days_passed = (today - record_date).days
        
        if days_passed > 3:
            if direction == 'LONG':
                if current_price < block_low:
                    return f"⚠️ Блок пробит гэпом ({days_passed} дн. назад)", self.multipliers.get('weak_block', 0.7)
                else:
                    return f"✅ Гэп пройден, блок устоял", 1.0
        
        if direction == 'SHORT':
            return None, 1.0
        
        if direction == 'LONG':
            if 0 <= days_to_record <= 7:
                return f"⚠️ Отсечка через {days_to_record} дн. (риск гэпа)", 0.5
            elif days_to_record == 0:
                if record_date == today:
                    return f"⚠️ Отсечка сегодня (риск гэпа)", 0.5
        
        return None, 1.0

    @retry(max_attempts=2, delay=1)
    def get_calibrated_imoex(self):
        """Собирает синтетический IMOEX из ТОП-20 акций"""
        if self._cached_imoex is not None:
            df, multiplier, figi = self._cached_imoex
            logger.info(f"IMOEX (из кэша): {df['close'].iloc[-1]:.0f}")
            return df, multiplier, figi
        
        try:
            tickers_weights = [
                ('LKOH', 16.05), ('SBER', 12.91), ('GAZP', 9.97), ('YNDX', 5.85),
                ('TATN', 4.82), ('T', 4.69), ('NVTK', 4.31), ('VTBR', 3.73),
                ('GMKN', 3.66), ('PLZL', 3.55), ('ROSN', 3.00), ('X5', 2.65),
                ('OZON', 2.53), ('SBERP', 2.49), ('SNGS', 1.78), ('SNGSP', 1.63),
                ('RUAL', 1.15), ('IRAO', 1.04), ('MOEX', 1.04), ('MTSS', 1.01),
            ]
            
            logger.info(f"Расчёт синтетического IMOEX из ТОП-20 акций")
            
            all_data = []
            base_df = None
            loaded_tickers = []
            failed_tickers = []
            
            for ticker, weight in tickers_weights:
                figi = self.figi_loader.get_figi(ticker)
                if not figi:
                    failed_tickers.append(ticker)
                    continue
                    
                df = self.tinkoff.get_historical_candles(figi, days=90)
                if df is not None and len(df) >= 50:
                    if base_df is None:
                        base_df = df.copy()
                        base_df['synthetic_close'] = 0.0
                    
                    norm_price = df['close'] / df['close'].iloc[-50]
                    all_data.append((norm_price, weight))
                    loaded_tickers.append(ticker)
                    logger.debug(f"{ticker}: загружено {len(df)} свечей (вес {weight}%)")
                else:
                    failed_tickers.append(ticker)
            
            if len(all_data) < 10:
                logger.error(f"Недостаточно данных для расчёта индекса (загружено {len(all_data)} из 20)")
                return None, None, None
            
            synthetic_norm = pd.Series(0, index=base_df.index)
            total_loaded_weight = 0
            
            for norm_series, weight in all_data:
                aligned_norm = norm_series.reindex(base_df.index).fillna(method='ffill').fillna(1.0)
                synthetic_norm = synthetic_norm.add(aligned_norm * weight, fill_value=0)
                total_loaded_weight += weight
            
            synthetic_norm = synthetic_norm / total_loaded_weight
            synthetic_close = synthetic_norm * 2750
            
            result_df = base_df.copy()
            result_df['close'] = synthetic_close
            result_df['high'] = synthetic_close * 1.005
            result_df['low'] = synthetic_close * 0.995
            result_df['open'] = synthetic_close.shift(1).fillna(synthetic_close)
            
            current = result_df['close'].iloc[-1]
            
            logger.info(f"Синтетический IMOEX рассчитан: {current:.0f} (загружено {len(loaded_tickers)}/20, охват {total_loaded_weight:.1f}%)")
            
            self._cached_imoex = (result_df, 1.0, "SYNTHETIC_IMOEX_TOP20")
            return result_df, 1.0, "SYNTHETIC_IMOEX_TOP20"
            
        except Exception as e:
            logger.error(f"Ошибка расчёта IMOEX: {e}")
            return None, None, None
    
    def get_market_phase(self):
        """Определяет техническую фазу рынка по IMOEX"""
        if self._cached_phase is not None:
            return self._cached_phase
        
        df, multiplier, figi = self.get_calibrated_imoex()
        
        if df is None or len(df) < 50:
            return 'unknown', 0
        
        df['MA50'] = df['close'].rolling(50).mean()
        df['MA200'] = df['close'].rolling(200).mean()
        
        current = df['close'].iloc[-1]
        ma50 = df['MA50'].iloc[-1]
        ma200 = df['MA200'].iloc[-1] if not pd.isna(df['MA200'].iloc[-1]) else ma50
        
        high_20 = df['high'].rolling(20).max().iloc[-1]
        drawdown = (high_20 - current) / high_20 * 100
        
        if current > ma50 and ma50 > ma200 and drawdown < 3:
            phase = 'UP'
        elif current < ma50 and drawdown > 5:
            phase = 'CORRECTION'
        elif current < ma50 and current < ma200:
            phase = 'DOWN'
        else:
            phase = 'NEUTRAL'
        
        logger.info(f"IMOEX: {current:.0f} | MA50: {ma50:.0f} | Просадка: {drawdown:.1f}% | Фаза: {phase}")
        
        self._cached_phase = (phase, drawdown)
        return phase, drawdown
    
    def plot_market_context(self):
        """Визуализация индекса IMOEX с ключевыми уровнями и MA"""
        try:
            df, multiplier, figi = self.get_calibrated_imoex()
            
            if df is None or len(df) < 20:
                logger.warning("Нет данных по IMOEX для построения графика")
                return
            
            df['MA50'] = df['close'].rolling(50).mean()
            df['MA200'] = df['close'].rolling(200).mean()
            
            high_20 = df['high'].rolling(20).max().iloc[-1]
            current = df['close'].iloc[-1]
            drawdown = (high_20 - current) / high_20 * 100
            phase, _ = self.get_market_phase()
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={'height_ratios': [3, 1]})
            
            ax1.plot(df.index, df['close'], label='IMOEX', color='black', linewidth=1.8)
            ax1.plot(df.index, df['MA50'], label='MA50', color='blue', linestyle='--', alpha=0.8, linewidth=1.5)
            if not df['MA200'].isna().all():
                ax1.plot(df.index, df['MA200'], label='MA200', color='red', linestyle='--', alpha=0.8, linewidth=1.5)
            
            ax1.axhline(y=high_20, color='green', linestyle=':', linewidth=1.5, label=f'Max 20d ({high_20:.0f})')
            
            if current < high_20:
                ax1.fill_between(df.index[-20:], high_20, current, color='red', alpha=0.15, label=f'Коррекция ↓{drawdown:.1f}%')
            
            ax1.scatter(df.index[-1], current, color='black', s=150, zorder=5, edgecolors='white', linewidth=2)
            
            market_trend = self.market_context.get('trend', 'NEUTRAL')
            market_score = self.market_context.get('market_score', 50)
            
            trend_color = 'green' if market_trend == 'UP' else 'red' if market_trend == 'DOWN' else 'orange'
            ax1.set_title(f'IMOEX — Фунд. тренд: {market_trend} ({market_score} б.) | Тех. фаза: {phase} | Просадка: {drawdown:.1f}%', 
                         fontsize=14, fontweight='bold', color=trend_color)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            ax1.set_ylabel('Цена (пункты)', fontsize=11)
            
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
            
            ax2.bar(df.index, df['volume'], color='steelblue', alpha=0.6, label='Объём торгов')
            ax2.set_ylabel('Объём', fontsize=11)
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.2)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
            
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.13)
            
            chart_file = os.path.join(CHARTS_DIR, f"IMOEX_context_{datetime.now().strftime('%Y%m%d_%H%M')}.png")
            os.makedirs(CHARTS_DIR, exist_ok=True)
            plt.savefig(chart_file, dpi=150, bbox_inches='tight')
            logger.info(f"График IMOEX сохранён: {chart_file}")
            plt.close()
            
        except Exception as e:
            logger.error(f"Ошибка построения графика IMOEX: {e}")
    
    def filter_breakout_by_trend(self, signal_type, direction, phase):
        """Возвращает: (trend_alignment, warning_message, multiplier)"""
        if signal_type != 'BREAKOUT':
            if direction == 'UP':
                if phase == 'UP':
                    return 'with', None, 1.0
                elif phase == 'DOWN':
                    return 'against', "⚠️ LONG против DOWN-тренда", self.multipliers.get('against_trend', 0.7)
                else:
                    return 'neutral', None, self.multipliers.get('correction', 0.85)
            else:
                if phase == 'DOWN':
                    return 'with', None, 1.0
                elif phase == 'UP':
                    return 'against', "⚠️ SHORT против UP-тренда", self.multipliers.get('against_trend', 0.7)
                else:
                    return 'neutral', None, self.multipliers.get('correction', 0.85)
        
        if phase == 'UP':
            if direction == 'UP':
                return 'with', "✅ UP-тренд — LONG BREAKOUT", 1.0
            else:
                return 'against', "⚠️ UP-тренд — SHORT BREAKOUT рискован", 0.5
        elif phase == 'DOWN':
            if direction == 'DOWN':
                return 'with', "✅ DOWN-тренд — SHORT BREAKOUT", 1.0
            else:
                return 'against', "⚠️ DOWN-тренд — LONG BREAKOUT рискован", 0.5
        elif phase == 'CORRECTION':
            return 'neutral', "⚠️ Коррекция — BREAKOUT с осторожностью", self.multipliers.get('correction', 0.6)
        else:
            return 'neutral', None, 0.75

    def analyze_volume_pressure(self, df, direction, signal_type):
        """Анализирует давление объема за последние 5 свечей"""
        if df is None or len(df) < 5:
            return 6, 4, "недостаточно данных"
    
        last_5 = df.iloc[-5:]
    
        green_vol = last_5[last_5['close'] >= last_5['open']]['volume'].sum()
        red_vol = last_5[last_5['close'] < last_5['open']]['volume'].sum()
    
        total_vol = green_vol + red_vol
        if total_vol == 0:
            return 6, 4, "нулевой объем"
    
        green_ratio = green_vol / total_vol
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        current_vol = last_5['volume'].iloc[-1]
        vol_ratio = current_vol / avg_volume if avg_volume > 0 else 1.0
    
        pressure_score = 6
        delta_score = 4
    
        if signal_type == 'BOUNCE':
            if direction == 'UP':
                if green_ratio > 0.6 and vol_ratio < 1.5:
                    pressure_score = 12
                    delta_score = 8
                    desc = f"накопление (green {green_ratio:.0%})"
                elif green_ratio > 0.5:
                    pressure_score = 9
                    delta_score = 6
                    desc = f"слабое накопление (green {green_ratio:.0%})"
                elif green_ratio < 0.4:
                    pressure_score = 3
                    delta_score = 2
                    desc = f"продажи (red {1-green_ratio:.0%})"
                else:
                    desc = f"нейтрально (green {green_ratio:.0%})"
            else:
                if green_ratio < 0.4 and vol_ratio < 1.5:
                    pressure_score = 12
                    delta_score = 8
                    desc = f"распределение (red {1-green_ratio:.0%})"
                elif green_ratio < 0.5:
                    pressure_score = 9
                    delta_score = 6
                    desc = f"слабое распределение (red {1-green_ratio:.0%})"
                elif green_ratio > 0.6:
                    pressure_score = 3
                    delta_score = 2
                    desc = f"покупки (green {green_ratio:.0%})"
                else:
                    desc = f"нейтрально (green {green_ratio:.0%})"
        else:
            if direction == 'UP':
                if vol_ratio > 1.5 and green_ratio > 0.6:
                    pressure_score = 12
                    delta_score = 8
                    desc = f"импульс вверх (vol x{vol_ratio:.1f})"
                elif vol_ratio > 1.2 and green_ratio > 0.5:
                    pressure_score = 9
                    delta_score = 6
                    desc = f"слабый импульс вверх"
                elif vol_ratio < 0.8:
                    pressure_score = 3
                    delta_score = 2
                    desc = f"пробой без объема"
                else:
                    desc = f"нейтрально"
            else:
                if vol_ratio > 1.5 and green_ratio < 0.4:
                    pressure_score = 12
                    delta_score = 8
                    desc = f"импульс вниз (vol x{vol_ratio:.1f})"
                elif vol_ratio > 1.2 and green_ratio < 0.5:
                    pressure_score = 9
                    delta_score = 6
                    desc = f"слабый импульс вниз"
                elif vol_ratio < 0.8:
                    pressure_score = 3
                    delta_score = 2
                    desc = f"пробой без объема"
                else:
                    desc = f"нейтрально"
    
        return pressure_score, delta_score, desc

    def calculate_signal_score(self, analysis, phase, trend_alignment, volume_pressure_score, delta_score):
        """Рассчитывает итоговый рейтинг сигнала (0-100)"""
        scoring = CONFIG.get('scoring', {})
        
        score = 0
    
        # ГРУППА 1: Статика блока (20%)
        strength = analysis.get('block_strength', 'normal')
        if strength == 'very_strong':
            score += scoring.get('block_strength_max', 10)
        elif strength == 'strong':
            score += int(scoring.get('block_strength_max', 10) * 0.7)
        elif strength == 'normal':
            score += 5
        else:
            score += 2
        
        age = analysis.get('block_age', 30)
        if age < 10:
            score += scoring.get('block_age_fresh', 6)
        elif age < 30:
            score += 4
        else:
            score += 1
        
        method = analysis.get('block_method', 'unknown')
        if method == 'both':
            score += scoring.get('block_method_both', 4)
        else:
            score += 2

        # ГРУППА 2: Технический контекст (30%)
        distance_to_entry = abs(analysis.get('current_price', 0) - analysis.get('block_low', 0)) / analysis.get('current_price', 1) * 100
        if distance_to_entry <= 1:
            score += scoring.get('distance_entry', 12)
        elif distance_to_entry <= 2:
            score += 10
        elif distance_to_entry <= 3:
            score += 5
        
        stoch_rsi = analysis.get('stoch_rsi', 50)
        signal_type = analysis.get('signal_type', 'BOUNCE')
        direction = analysis.get('direction', 'UP')
    
        if signal_type == 'BOUNCE':
            if direction == 'UP':
                if stoch_rsi < 20:
                    score += scoring.get('stoch_extreme', 12)
                elif stoch_rsi < 30:
                    score += 6
            else:
                if stoch_rsi > 80:
                    score += scoring.get('stoch_extreme', 12)
                elif stoch_rsi > 70:
                    score += 6
        else:
            if direction == 'UP':
                if stoch_rsi > 80:
                    score += scoring.get('stoch_extreme', 12)
                elif stoch_rsi > 70:
                    score += 6
            else:
                if stoch_rsi < 20:
                    score += scoring.get('stoch_extreme', 12)
                elif stoch_rsi < 30:
                    score += 6
                
        potential = analysis.get('potential', 0)
        if potential >= 5:
            score += scoring.get('potential_high', 6)
        elif potential >= 3:
            score += 4
        elif potential >= 1:
            score += 2

        # ГРУППА 3: Рыночный контекст (30%)
        if trend_alignment == 'with':
            score += scoring.get('trend_alignment', 15)
        elif trend_alignment == 'neutral':
            score += 8
    
        sector_score_val = analysis.get('sector_score', 50)
        if direction == 'UP':
            if sector_score_val >= 60:
                score += scoring.get('sector_alignment', 9)
            elif sector_score_val >= 40:
                score += 5
            else:
                score += 2
        else:
            if sector_score_val <= 40:
                score += scoring.get('sector_alignment', 9)
            elif sector_score_val <= 60:
                score += 5
            else:
                score += 2
            
        rvi = self.macro_data.get('rvi', 25)
        geo = self.macro_data.get('geopolitics', 5)
        if rvi <= 25 and geo <= 5:
            score += scoring.get('low_volatility', 6)
        elif rvi <= 35 and geo <= 7:
            score += 3

        # ГРУППА 4: Динамика объема (20%)
        score += volume_pressure_score
        score += delta_score

        return round(score, 1)

    def analyze_all_blocks(self):
        logger.info("=" * 100)
        logger.info("АНАЛИЗ БЛОКОВ")
        logger.info("=" * 100)

        self.sector_scores = self.sector_analyzer.analyze_all_sectors()
        self.market_context = self.market_analyzer.analyze()
    
        phase, drawdown = self.get_market_phase()
    
        print("\n" + "=" * 100)
        print("🔍 АНАЛИЗ БЛОКОВ")
        print("=" * 100)
        print(f"\n📊 РЫНОЧНЫЙ КОНТЕКСТ:")
        print(f"   Фундаментальный тренд: {self.market_context['trend']} (балл: {self.market_context['market_score']})")
        print(f"   Техническая фаза: {phase} (просадка от хая: {drawdown:.1f}%)")
        print(f"   Ставка ЦБ: {self.market_context['cbr_rate']}% | CNY/RUB: {self.market_context.get('cnyrub', '?')}")
        print(f"   Инфляция: {self.market_context['inflation']}% | Brent: {self.market_context['brent']}$")
        print(f"   RVI: {self.market_context.get('rvi', '?')} | Геополитика: {self.market_context['geopolitics']}/10")
        
        if self.market_context.get('reasons'):
            print(f"\n📋 ФАКТОРЫ ВЛИЯНИЯ:")
            for r in self.market_context['reasons'][:5]:
                print(f"   {r}")
    
        print(f"\n⏰ Время: {datetime.now().strftime('%H:%M:%S')}")
        print(f"📊 Всего тикеров для сканирования: {len(self.tickers)}")
        print(f"📊 Мин. потенциал для сигнала: {self.min_potential}%")
        print("-" * 100)
        
        self.plot_market_context()
    
        all_signals = []
    
        for i, ticker in enumerate(self.tickers, 1):
            print(f"\n[{i}/{len(self.tickers)}] 🔍 {ticker}...")
        
            figi = self.figi_loader.get_figi(ticker)
            if not figi:
                print(f"  ⚠️ Нет FIGI")
                continue
        
            df = self.tinkoff.get_historical_candles(figi, days=90)
            if df is None or len(df) < 20:
                print(f"  ⚠️ Недостаточно данных")
                continue
            
            if 'date' not in df.columns:
                df['date'] = df.index
            
            df = self.calculate_stoch_rsi_for_df(df)
            stoch_rsi = df['StochRSI_K'].iloc[-1] if not pd.isna(df['StochRSI_K'].iloc[-1]) else 50
        
            print(f"  📊 Stochastic RSI: {stoch_rsi:.1f}")
        
            blocks_our = self.find_order_blocks_our_method(df)
            blocks_luxalgo = self.find_order_blocks_luxalgo(df)
            
            blocks_our = self.find_order_blocks_with_strength(df, blocks_our)
            blocks_luxalgo = self.find_order_blocks_with_strength(df, blocks_luxalgo)
        
            all_blocks_ticker = []
        
            for block in blocks_our['bull']:
                block['method'] = 'our'
                block['type'] = 'bull'
                all_blocks_ticker.append(block)
            for block in blocks_our['bear']:
                block['method'] = 'our'
                block['type'] = 'bear'
                all_blocks_ticker.append(block)
            for block in blocks_luxalgo['bull']:
                block['method'] = 'luxalgo'
                block['type'] = 'bull'
                all_blocks_ticker.append(block)
            for block in blocks_luxalgo['bear']:
                block['method'] = 'luxalgo'
                block['type'] = 'bear'
                all_blocks_ticker.append(block)
        
            all_blocks_ticker = self.deduplicate_blocks(all_blocks_ticker)
        
            if not all_blocks_ticker:
                print(f"  📭 Блоков не найдено")
                continue
        
            sector_code = self.sector_analyzer.get_sector_code(ticker)
            sector_name = self.sector_analyzer.get_sector_name(sector_code)
            sector_score = self.sector_scores.get(sector_code, {}).get('score', 50)
            current_price = df['close'].iloc[-1]
        
            analyzer = BlockProbabilityAnalyzer(
                market_context=self.market_context,
                sector_scores=self.sector_scores,
                fundamentals=self.fundamentals
            )
        
            dividend_info = self.dividend_analyzer.get_dividend_info(figi)
        
            for block in all_blocks_ticker:
                analysis = analyzer.analyze_block(block, ticker, sector_code, current_price)
                signal_type = analysis.get('signal_type')
                
                if signal_type is None:
                    continue
                
                if not self.is_block_actual(block, current_price, df, signal_type):
                    strength_info = f" [{block.get('strength_desc', '')}]" if 'strength_desc' in block else ""
                    print(f"  ⏳ {ticker}: {block['type']} блок {block['low']:.2f}-{block['high']:.2f}{strength_info} не актуален для {signal_type}")
                    continue
                
                trend_alignment, trend_warning, trend_multiplier = self.filter_breakout_by_trend(
                    signal_type, analysis['direction'], phase
                )
                
                analysis['trend_alignment'] = trend_alignment
                if trend_warning:
                    analysis['reasons'].append(trend_warning)
                
                if 'position_multiplier' not in analysis:
                    analysis['position_multiplier'] = 1.0
                analysis['position_multiplier'] *= trend_multiplier
                
                if dividend_info:
                    div_warning, div_multiplier = self.check_dividend_block(
                        ticker,
                        'LONG' if analysis['direction'] == 'UP' else 'SHORT',
                        dividend_info,
                        current_price,
                        block['low'],
                        block['high']
                    )
                    
                    if div_warning:
                        analysis['reasons'].append(div_warning)
                    
                    analysis['position_multiplier'] *= div_multiplier
                    
                    if dividend_info.get('days_to_record') is not None and dividend_info['days_to_record'] < 30:
                        div_yield = (dividend_info['amount'] / current_price) * 100
                        impact, impact_msg, multiplier = self.dividend_analyzer.analyze_impact(
                            current_price, block['low'], block['high'], div_yield,
                            'LONG' if analysis['direction'] == 'UP' else 'SHORT'
                        )
                        analysis['dividend_impact'] = impact_msg
                        analysis['position_multiplier'] *= multiplier
                
                strength_mult = block.get('strength_multiplier', 1.0)
                strength_desc = block.get('strength_desc', '')
                
                if strength_mult > 1.0:
                    old_prob = analysis['probability']
                    analysis['probability'] = min(100, int(analysis['probability'] * strength_mult))
                    if 'reasons' in analysis:
                        analysis['reasons'].append(f"💪 Сильный объём (+{analysis['probability'] - old_prob}%)")
                elif strength_mult < 1.0:
                    old_prob = analysis['probability']
                    analysis['probability'] = int(analysis['probability'] * strength_mult)
                    if 'reasons' in analysis:
                        analysis['reasons'].append(f"⚠️ Слабый объём (-{old_prob - analysis['probability']}%)")
                
                if analysis['direction'] == 'UP' and phase in ['CORRECTION', 'DOWN']:
                    old_prob = analysis['probability']
                    analysis['probability'] = int(analysis['probability'] * self.multipliers.get('correction', 0.7))
                    if 'reasons' in analysis:
                        analysis['reasons'].append(f"⚠️ Рынок в коррекции (-{old_prob - analysis['probability']}%)")
                
                stoch_multiplier = 1.0
                if analysis['direction'] == 'UP':
                    if stoch_rsi < 20:
                        stoch_multiplier = 1.2
                        stoch_note = "усиление (перепродан)"
                    elif stoch_rsi > 80:
                        stoch_multiplier = 0.5
                        stoch_note = "ослабление (перекуплен)"
                    else:
                        stoch_note = "нейтрально"
                else:
                    if stoch_rsi > 80:
                        stoch_multiplier = 1.2
                        stoch_note = "усиление (перекуплен)"
                    elif stoch_rsi < 20:
                        stoch_multiplier = 0.5
                        stoch_note = "ослабление (перепродан)"
                    else:
                        stoch_note = "нейтрально"
                
                analysis['probability'] = min(100, int(analysis['probability'] * stoch_multiplier))
                analysis['stoch_note'] = stoch_note
                analysis['block_strength'] = block.get('strength', 'unknown')
                analysis['block_strength_desc'] = strength_desc
                
                if analysis['probability'] >= 60:
                    analysis['ticker'] = ticker
                    analysis['sector'] = sector_name
                    analysis['sector_code'] = sector_code
                    analysis['sector_score'] = sector_score
                    analysis['current_price'] = current_price
                    analysis['stoch_rsi'] = stoch_rsi
                    analysis['block'] = block
                    analysis['dividend_info'] = dividend_info
                    
                    tp1, tp2, tp3 = self.get_next_blocks(all_blocks_ticker, current_price, analysis['direction'])
                    analysis['tp1'] = tp1
                    analysis['tp2'] = tp2
                    analysis['tp3'] = tp3
                    
                    fund = self.fundamentals.get(ticker, {})
                    dcf = fund.get('dcf_potential', 0)
                    div_strategy = fund.get('dividend_strategy', 0)
                    
                    total_potential, tech_pot, fund_pot = calculate_potential(
                        current_price, tp1['low'] if tp1 else None, tp1['high'] if tp1 else None,
                        analysis['direction'], dcf, div_strategy, sector_score
                    )
                    analysis['potential'] = total_potential
                    analysis['tech_potential'] = tech_pot
                    
                    if analysis['potential'] >= self.min_potential:
                        pressure_score, delta_score, volume_desc = self.analyze_volume_pressure(
                            df, analysis['direction'], signal_type
                        )
                        
                        if pressure_score >= 9:
                            analysis['reasons'].append(f"📊 Объем: {volume_desc}")
                        elif pressure_score <= 3:
                            analysis['reasons'].append(f"📉 Объем: {volume_desc}")
                        
                        analysis['score'] = self.calculate_signal_score(
                            analysis, phase, analysis.get('trend_alignment', 'neutral'),
                            pressure_score, delta_score
                        )
                        
                        all_signals.append(analysis)
                        self.print_signal(analysis)
                        
                        is_confirmed = (analysis['direction'] == 'UP' and stoch_rsi < 20) or \
                                      (analysis['direction'] == 'DOWN' and stoch_rsi > 80)
                        if is_confirmed:
                            self.plot_block_signal(analysis, df, ticker, phase, drawdown)
        
        # ===== ИНТЕГРАЦИЯ С ТРЕКЕРОМ И ВОТЧЛИСТОМ =====
        if self.enable_tracking or self.enable_watchlist:
            if self.block_tracker is None:
                self.enable_tracking = False
            if self.watchlist_manager is None:
                self.enable_watchlist = False
                
            if self.enable_tracking or self.enable_watchlist:
                print("\n" + "="*100)
                print("💾 СОХРАНЕНИЕ ДАННЫХ В ТРЕКЕР И ВОТЧЛИСТ")
                print("="*100)
                
                confirmed = []
                watchlist = []
                
                for s in all_signals:
                    if s['direction'] == 'UP':
                        is_confirmed = s['stoch_rsi'] < 20
                    else:
                        is_confirmed = s['stoch_rsi'] > 80
                    
                    if is_confirmed:
                        confirmed.append(s)
                    else:
                        watchlist.append(s)
                
                if self.enable_tracking and confirmed:
                    print(f"\n📈 ОТКРЫТИЕ ДЕМО-ПОЗИЦИЙ ({len(confirmed)} сигналов):")
                    print("-" * 100)
                    
                    for s in confirmed[:10]:
                        try:
                            position = self.block_tracker.add_block_position(
                                analysis=s,
                                entry_price=s['current_price'],
                                entry_date=datetime.now().strftime('%Y-%m-%d %H:%M')
                            )
                            
                            if position:
                                print(f"  ✅ {s['ticker']} {position['direction']} | Вход: {s['current_price']:.2f} | Потенциал: {s['potential']:.1f}% | Стоп: {position['stop_loss']:.2f}")
                            
                        except Exception as e:
                            print(f"  ❌ Ошибка открытия позиции {s['ticker']}: {e}")
                
                if self.enable_watchlist and watchlist:
                    print(f"\n📋 ДОБАВЛЕНИЕ В ВОТЧЛИСТ ({len(watchlist)} сигналов):")
                    print("-" * 100)
                    
                    watchlist_items = []
                    watchlist_by_ticker = {}
                    for s in watchlist[:30]:
                        ticker = s['ticker']
                        if ticker not in watchlist_by_ticker:
                            watchlist_by_ticker[ticker] = s
                    
                    for ticker, s in list(watchlist_by_ticker.items())[:20]:
                        direction = 'LONG' if s['direction'] == 'UP' else 'SHORT'
                        wait_condition = 'Stoch RSI < 20' if direction == 'LONG' else 'Stoch RSI > 80'
                        
                        watchlist_item = {
                            'ticker': ticker,
                            'sector': s.get('sector', 'unknown'),
                            'direction': direction,
                            'current_price': s['current_price'],
                            'block_low': s['block_low'],
                            'block_high': s['block_high'],
                            'stoch_rsi': s['stoch_rsi'],
                            'potential': s['potential'],
                            'probability': s['probability'],
                            'wait_condition': wait_condition,
                            'strength_desc': s.get('block_strength_desc', ''),
                            'added_date': datetime.now().strftime('%Y-%m-%d %H:%M')
                        }
                        
                        watchlist_items.append(watchlist_item)
                        print(f"  📌 {ticker} {direction} | Цена: {s['current_price']:.2f} | Stoch RSI: {s['stoch_rsi']:.1f} | {wait_condition}")
                        
                        try:
                            self.watchlist_history.add_record({
                                'ticker': ticker,
                                'direction': direction,
                                'added_date': watchlist_item['added_date'],
                                'block_low': s['block_low'],
                                'block_high': s['block_high'],
                                'current_price': s['current_price'],
                                'stoch_rsi': s['stoch_rsi'],
                                'potential': s['potential'],
                                'probability': s['probability'],
                                'outcome': 'pending'
                            })
                        except:
                            pass
                        
                        try:
                            watchlist_file = os.path.join(SIGNALS_DIR, f'watchlist_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
                            os.makedirs(SIGNALS_DIR, exist_ok=True)
                            with open(watchlist_file, 'w', encoding='utf-8') as f:
                                json.dump(watchlist_items, f, indent=2, ensure_ascii=False)
                            print(f"  ✅ Вотчлист сохранён: {watchlist_file}")
                        except Exception as e:
                            print(f"  ⚠️ Ошибка сохранения вотчлиста: {e}")
                
                print(f"\n💾 СОХРАНЕНИЕ В ФАЙЛЫ:")
                print("-" * 100)
                
                try:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    
                    signals_file = os.path.join(SIGNALS_DIR, f'signals_{timestamp}.json')
                    os.makedirs(SIGNALS_DIR, exist_ok=True)
                    
                    signals_json = []
                    for s in all_signals:
                        s_copy = {}
                        for k, v in s.items():
                            if k in ['block', 'tp1', 'tp2', 'tp3']:
                                continue
                            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                                s_copy[k] = v
                        s_copy['block_low'] = s.get('block_low', 0)
                        s_copy['block_high'] = s.get('block_high', 0)
                        signals_json.append(s_copy)
                    
                    with open(signals_file, 'w', encoding='utf-8') as f:
                        json.dump(signals_json, f, indent=2, ensure_ascii=False, default=str)
                    print(f"  ✅ Сигналы сохранены: {signals_file}")
                    
                    if hasattr(self.block_tracker, 'save_positions'):
                        self.block_tracker.save_positions()
                        print(f"  ✅ Позиции трекера сохранены")
                    
                except Exception as e:
                    print(f"  ❌ Ошибка сохранения: {e}")
        
        all_signals.sort(key=lambda x: x.get('score', 0), reverse=True)
        return all_signals
    
    def print_signal(self, signal):
        direction_emoji = "🟢" if signal['direction'] == 'UP' else "🔴"
        prob = signal['probability']
        stoch_rsi = signal['stoch_rsi']
        potential = signal.get('potential', 0)
        block_strength_desc = signal.get('block_strength_desc', '')
        
        phase, drawdown = self.get_market_phase()
        trend_warning = ""
        if signal['direction'] == 'UP' and phase in ['DOWN', 'CORRECTION']:
            trend_warning = " ⚠️ ПРОТИВ ТРЕНДА!"
        
        if prob >= 80:
            prob_emoji = "🔥🔥🔥"
        elif prob >= 70:
            prob_emoji = "🔥🔥"
        elif prob >= 60:
            prob_emoji = "🔥"
        else:
            prob_emoji = "📊"
        
        size, size_emoji = get_position_size(potential)
        
        print(f"\n  {direction_emoji} {signal['direction']} {signal['ticker']} ({signal['sector']}) | {signal['block_type']} блок | Вероятность: {prob}% {prob_emoji}{trend_warning}")
        
        if block_strength_desc:
            print(f"  💪 {block_strength_desc}")
        
        market_score = self.market_context.get('market_score', 50)
        market_trend = self.market_context.get('trend', 'NEUTRAL')
        
        trend_emoji = "↗️" if market_trend == 'UP' else "↘️" if market_trend == 'DOWN' else "➡️"
        phase_emoji = "🟢" if phase == 'UP' else "🔴" if phase == 'DOWN' else "🟡" if phase == 'CORRECTION' else "⚪"
        
        print(f"\n      📊 РЫНОК (IMOEX):")
        print(f"         Фунд. тренд: {trend_emoji} {market_trend} (балл: {market_score})")
        print(f"         Тех. фаза: {phase_emoji} {phase} (просадка: {drawdown:.1f}%)")
        
        if signal['direction'] == 'UP' and phase in ['DOWN', 'CORRECTION']:
            print(f"         ⚠️ Вход ПРОТИВ технического тренда!")
        elif signal['direction'] == 'DOWN' and phase in ['UP']:
            print(f"         ⚠️ Вход ПРОТИВ технического тренда!")
        
        sector_code = signal.get('sector_code', 'unknown')
        sector_data = self.sector_scores.get(sector_code, {})
        sector_score = sector_data.get('score', 50)
        sector_bias = sector_data.get('bias', 'NEUTRAL')
        sector_factors = sector_data.get('factors', [])
        
        bias_emoji = "↗️" if sector_bias == 'BULLISH' else "↘️" if sector_bias == 'BEARISH' else "➡️"
        
        if sector_score >= 60:
            sector_strength = "💪 СИЛЬНЫЙ"
        elif sector_score <= 40:
            sector_strength = "👎 СЛАБЫЙ"
        else:
            sector_strength = "📊 НЕЙТРАЛЬНЫЙ"
        
        print(f"\n      🏭 ОТРАСЛЬ: {signal['sector']}")
        print(f"         Оценка: {sector_score}/100 {bias_emoji} {sector_bias} ({sector_strength})")
        
        if sector_factors:
            print(f"         Факторы: {', '.join(sector_factors[:3])}")
        
        if sector_score >= 60 and signal['direction'] == 'UP':
            print(f"         ✅ Сектор поддерживает LONG (+10%)")
        elif sector_score <= 40 and signal['direction'] == 'DOWN':
            print(f"         ✅ Сектор поддерживает SHORT (+10%)")
        elif sector_score >= 60 and signal['direction'] == 'DOWN':
            print(f"         ⚠️ SHORT против сильного сектора (-10%)")
        elif sector_score <= 40 and signal['direction'] == 'UP':
            print(f"         ⚠️ LONG против слабого сектора (-10%)")
        
        current_price = signal.get('current_price', 0)
        print(f"\n      🎯 ТОРГОВЫЙ ПЛАН:")
        print(f"         Блок: {signal['block_low']:.2f} - {signal['block_high']:.2f}")
        print(f"         Текущая цена: {current_price:.2f}")
        print(f"         Stochastic RSI: {stoch_rsi:.1f} ({signal.get('stoch_note', '')})")
        print(f"         Потенциал: {potential:.1f}% {size_emoji}")
        
        if signal['direction'] == 'UP':
            distance = (current_price - signal['block_high']) / current_price * 100
            if distance < 0:
                print(f"         ⚠️ Цена ВЫШЕ блока — ждать снижения")
            elif distance < 1:
                print(f"         🔥 ВХОД СЕЙЧАС! ({distance:.1f}% до низа блока)")
            else:
                print(f"         ↓{distance:.1f}% до входа в блок")
        else:
            distance = (signal['block_low'] - current_price) / current_price * 100
            if distance < 0:
                print(f"         ⚠️ Цена НИЖЕ блока — ждать роста")
            elif distance < 1:
                print(f"         🔥 ВХОД СЕЙЧАС! ({distance:.1f}% до верха блока)")
            else:
                print(f"         ↑{distance:.1f}% до входа в блок")
        
        if signal.get('tp1'):
            if signal['direction'] == 'UP':
                tp_gain = (signal['tp1']['low'] - current_price) / current_price * 100
                print(f"         TP1: {signal['tp1']['low']:.2f} - {signal['tp1']['high']:.2f} (+{tp_gain:.1f}%)")
            else:
                tp_gain = (current_price - signal['tp1']['high']) / current_price * 100
                print(f"         TP1: {signal['tp1']['low']:.2f} - {signal['tp1']['high']:.2f} (+{tp_gain:.1f}%)")
        
        div_info = signal.get('dividend_info')
        if div_info and div_info.get('days_to_record') is not None and 0 <= div_info['days_to_record'] < 30:
            div_yield = (div_info['amount'] / current_price) * 100
            print(f"\n      💰 ДИВИДЕНД: {div_info['amount']:.2f} ({div_yield:.1f}%) | Отсечка через {div_info['days_to_record']} дн.")
            if signal.get('dividend_impact'):
                print(f"         {signal['dividend_impact']}")
        
        print(f"\n      📊 ФАКТОРЫ ВЕРОЯТНОСТИ:")
        if signal.get('reasons'):
            for reason in signal['reasons'][:5]:
                print(f"         {reason}")
    
    def plot_block_signal(self, signal, df, ticker, phase, drawdown):
        try:
            plt.style.use('seaborn-v0_8-darkgrid')
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})
            
            ax1.plot(df.index, df['close'], label='Close', color='black', linewidth=1.5)
            ax1.axhspan(signal['block_low'], signal['block_high'], color='gray', alpha=0.3, label=f"Order Block ({signal['block_type']})")
            
            current_price = signal['current_price']
            ax1.axhline(y=current_price, color='blue', linestyle='--', linewidth=1, label=f'Current: {current_price:.2f}')
            
            if signal['direction'] == 'UP':
                stop_loss = signal['block_low'] * 0.98
                tp1 = signal['tp1']['low'] if signal.get('tp1') else current_price * 1.05
                ax1.axhline(y=stop_loss, color='red', linestyle=':', linewidth=1, label=f'SL: {stop_loss:.2f}')
                ax1.axhline(y=tp1, color='green', linestyle=':', linewidth=1, label=f'TP1: {tp1:.2f}')
            else:
                stop_loss = signal['block_high'] * 1.02
                tp1 = signal['tp1']['high'] if signal.get('tp1') else current_price * 0.95
                ax1.axhline(y=stop_loss, color='red', linestyle=':', linewidth=1, label=f'SL: {stop_loss:.2f}')
                ax1.axhline(y=tp1, color='green', linestyle=':', linewidth=1, label=f'TP1: {tp1:.2f}')
                
            signal_type = signal.get('signal_type', 'BOUNCE')
            title = f'{ticker} - {signal["direction"]} {signal_type} (Prob: {signal["probability"]}%, Pot: {signal["potential"]:.1f}%)'
            ax1.set_title(title, fontsize=12, fontweight='bold')
            ax1.set_ylabel('Price (₽)')
            ax1.legend(loc='upper left')
            ax1.grid(True, alpha=0.3)
            
            k_line = df['StochRSI_K']
            d_line = df['StochRSI_D']
            
            ax2.plot(df.index, k_line, label='StochRSI K', color='blue', linewidth=1)
            ax2.plot(df.index, d_line, label='StochRSI D', color='orange', linewidth=1)
            
            ax2.axhline(y=80, color='red', linestyle='--', alpha=0.5)
            ax2.axhline(y=20, color='green', linestyle='--', alpha=0.5)
            ax2.fill_between(df.index, 80, 100, color='red', alpha=0.1)
            ax2.fill_between(df.index, 0, 20, color='green', alpha=0.1)
            
            current_k = signal['stoch_rsi']
            ax2.scatter(df.index[-1], current_k, color='black', s=50, zorder=5)
            ax2.text(df.index[-1], current_k, f'  {current_k:.1f}', fontweight='bold')
            
            ax2.set_ylabel('Stochastic RSI')
            ax2.set_xlabel('Date')
            ax2.legend(loc='upper left')
            ax2.grid(True, alpha=0.3)
            
            market_trend = self.market_context.get('trend', 'NEUTRAL')
            
            info_text = (
                f"Ticker: {ticker}\n"
                f"Sector: {signal['sector']}\n"
                f"Direction: {signal['direction']}\n"
                f"Signal: {signal_type}\n"
                f"Probability: {signal['probability']}%\n"
                f"Potential: {signal['potential']:.1f}%\n"
                f"StochRSI: {signal['stoch_rsi']:.1f}\n"
                f"Strength: {signal.get('block_strength_desc', 'N/A')}\n"
                f"Market: {market_trend} | {phase} ({drawdown:.1f}%)"
            )
            plt.figtext(0.82, 0.5, info_text, fontsize=9, family='monospace',
                       bbox=dict(facecolor='white', alpha=0.9, edgecolor='gray', boxstyle='round,pad=0.5'),
                       verticalalignment='center')
            
            plt.tight_layout()
            plt.subplots_adjust(right=0.8)
            
            os.makedirs(CHARTS_DIR, exist_ok=True)
            filename = f"{ticker}_{signal['direction']}_{signal_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(CHARTS_DIR, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"  📈 График сохранён: {filepath}")
            
        except Exception as e:
            print(f"  ⚠️ Ошибка построения графика для {ticker}: {e}")

    def print_summary(self, signals):
        if not signals:
            print("\n❌ Сигналов не найдено")
            return
        
        high_priority = [s for s in signals if s.get('score', 0) >= 70]
        medium_priority = [s for s in signals if 40 <= s.get('score', 0) < 70]
        low_priority = [s for s in signals if s.get('score', 0) < 40]
        
        if high_priority:
            print("\n" + "="*100)
            print("🔥 ВЫСОКИЙ ПРИОРИТЕТ (Score ≥ 70)")
            print("="*100)
            self._print_signal_group(high_priority)
        
        if medium_priority:
            print("\n" + "="*100)
            print("📊 СРЕДНИЙ ПРИОРИТЕТ (Score 40-69)")
            print("="*100)
            self._print_signal_group(medium_priority)
        
        if low_priority:
            print("\n" + "="*100)
            print("⏳ НИЗКИЙ ПРИОРИТЕТ (Score < 40)")
            print("="*100)
            self._print_signal_group(low_priority)
        
        up_count = len([s for s in signals if s['direction'] == 'UP'])
        down_count = len([s for s in signals if s['direction'] == 'DOWN'])
        unique_tickers = len(set(s['ticker'] for s in signals))
        strong_blocks = len([s for s in signals if s.get('block_strength') in ['strong', 'very_strong']])
        
        phase, drawdown = self.get_market_phase()
        market_score = self.market_context.get('market_score', 50)
        market_trend = self.market_context.get('trend', 'NEUTRAL')
        
        print("\n" + "="*100)
        print("📊 СТАТИСТИКА:")
        print("="*100)
        print(f"   Всего сигналов: {len(signals)}")
        print(f"   Уникальных тикеров: {unique_tickers}")
        print(f"   🔥 Высокий приоритет: {len(high_priority)}")
        print(f"   📊 Средний приоритет: {len(medium_priority)}")
        print(f"   ⏳ Низкий приоритет: {len(low_priority)}")
        print(f"   LONG: {up_count} | SHORT: {down_count}")
        print(f"   💪 Сильных блоков: {strong_blocks}")
        
        trend_emoji = "↗️" if market_trend == 'UP' else "↘️" if market_trend == 'DOWN' else "➡️"
        phase_emoji = "🟢" if phase == 'UP' else "🔴" if phase == 'DOWN' else "🟡" if phase == 'CORRECTION' else "⚪"
        
        print(f"\n📊 РЫНОЧНЫЙ КОНТЕКСТ:")
        print(f"   Фунд. тренд: {trend_emoji} {market_trend} (балл: {market_score})")
        print(f"   Тех. фаза: {phase_emoji} {phase} (просадка: {drawdown:.1f}%)")
        
        if up_count > down_count and phase in ['DOWN', 'CORRECTION']:
            print(f"   ⚠️ Преобладают LONG, но рынок в {phase} — осторожно!")
        elif down_count > up_count and phase == 'UP':
            print(f"   ⚠️ Преобладают SHORT, но рынок в UP — осторожно!")
        
        print("\n" + "="*100)
        print("💾 ДАННЫЕ ТРЕКЕРА:")
        print("="*100)
        try:
            if hasattr(self, 'block_tracker') and self.block_tracker is not None:
                active = len(self.block_tracker.positions) if hasattr(self.block_tracker, 'positions') else 0
                closed = len(self.block_tracker.closed_positions) if hasattr(self.block_tracker, 'closed_positions') else 0
                print(f"   Активных демо-позиций: {active}")
                print(f"   Закрытых позиций: {closed}")
            
            if hasattr(self, 'watchlist_history') and self.watchlist_history is not None:
                stats = self.watchlist_history.get_statistics()
                if stats:
                    print(f"   История блоков: {stats.get('total', 0)} записей")
        except:
            pass
        print("="*100)
    
    def _print_signal_group(self, signals):
        signals = sorted(signals, key=lambda x: x.get('score', 0), reverse=True)
        
        by_ticker = {}
        for s in signals:
            ticker = s['ticker']
            if ticker not in by_ticker:
                by_ticker[ticker] = []
            by_ticker[ticker].append(s)
        
        for ticker in sorted(by_ticker.keys(), key=lambda t: by_ticker[t][0].get('score', 0), reverse=True):
            blocks = by_ticker[ticker]
            s = blocks[0]
            
            score = s.get('score', 0)
            direction_emoji = "🟢" if s['direction'] == 'UP' else "🔴"
            direction_text = "LONG" if s['direction'] == 'UP' else "SHORT"
            potential = s.get('potential', 0)
            prob = s['probability']
            stoch_rsi = s['stoch_rsi']
            
            pot_emoji = "🔥🔥🔥" if potential >= 15 else "🔥🔥" if potential >= 10 else "🔥" if potential >= 5 else "📊"
            
            if score >= 70:
                color = "🟢"
            elif score >= 40:
                color = "🟡"
            else:
                color = "⚪"
            
            block_word = "блок" if len(blocks) == 1 else "блока" if 2 <= len(blocks) <= 4 else "блоков"
            
            print(f"\n📌 {ticker} ({s['sector']}) — Score: {score} {color} | {len(blocks)} {block_word}")
            print(f"   {direction_emoji} {direction_text} | Вероятность: {prob}% | Потенциал: {potential:.1f}% {pot_emoji}")
            
            trend_alignment = s.get('trend_alignment', 'neutral')
            if trend_alignment == 'with':
                print(f"   📈 Тренд: совпадает ✅")
            elif trend_alignment == 'against':
                print(f"   📉 Тренд: против ⚠️")
            else:
                print(f"   📊 Тренд: нейтрально")
            
            strength_desc = s.get('block_strength_desc', '')
            if strength_desc:
                print(f"   💪 {strength_desc}")
            
            is_confirmed = (s['direction'] == 'UP' and stoch_rsi < 20) or (s['direction'] == 'DOWN' and stoch_rsi > 80)
            if is_confirmed:
                print(f"   ✅ Stoch RSI: {stoch_rsi:.1f} (в зоне)")
            else:
                print(f"   ⏳ Stoch RSI: {stoch_rsi:.1f} (ждём)")
            
            block_low = s['block_low']
            block_high = s['block_high']
            current_price = s['current_price']
            
            if s['direction'] == 'UP':
                if current_price > block_high:
                    dist = (current_price - block_high) / current_price * 100
                    distance_str = f"⚠️ цена ВЫШЕ блока на {dist:.1f}%"
                elif current_price < block_low:
                    dist = (block_low - current_price) / current_price * 100
                    distance_str = f"⚠️ цена НИЖЕ блока на {dist:.1f}%"
                else:
                    position_pct = (current_price - block_low) / (block_high - block_low) * 100
                    if position_pct < 20:
                        distance_str = f"🔥 В БЛОКЕ у нижней границы ({position_pct:.0f}%)"
                    elif position_pct > 80:
                        distance_str = f"📍 В БЛОКЕ у верхней границы ({position_pct:.0f}%)"
                    else:
                        distance_str = f"✅ В БЛОКЕ ({position_pct:.0f}%)"
            else:
                if current_price < block_low:
                    dist = (block_low - current_price) / current_price * 100
                    distance_str = f"⚠️ цена НИЖЕ блока на {dist:.1f}%"
                elif current_price > block_high:
                    dist = (current_price - block_high) / current_price * 100
                    distance_str = f"⚠️ цена ВЫШЕ блока на {dist:.1f}%"
                else:
                    position_pct = (block_high - current_price) / (block_high - block_low) * 100
                    if position_pct < 20:
                        distance_str = f"🔥 В БЛОКЕ у верхней границы ({position_pct:.0f}%)"
                    elif position_pct > 80:
                        distance_str = f"📍 В БЛОКЕ у нижней границы ({position_pct:.0f}%)"
                    else:
                        distance_str = f"✅ В БЛОКЕ ({position_pct:.0f}%)"
            
            print(f"   📍 Блок: {block_low:.2f} - {block_high:.2f} ({distance_str})")
            
            if s.get('tp1'):
                if s['direction'] == 'UP':
                    tp_gain = (s['tp1']['low'] - s['current_price']) / s['current_price'] * 100
                else:
                    tp_gain = (s['current_price'] - s['tp1']['high']) / s['current_price'] * 100
                print(f"   🎯 TP1: {s['tp1']['low']:.2f} - {s['tp1']['high']:.2f} (+{tp_gain:.1f}%)")
            
            div_info = s.get('dividend_info')
            if div_info and div_info.get('days_to_record') is not None and 0 <= div_info['days_to_record'] < 30:
                div_yield = (div_info['amount'] / s['current_price']) * 100
                print(f"   💰 Див: {div_info['amount']:.2f} ({div_yield:.1f}%) | Отсечка: {div_info['days_to_record']} дн.")
            
            sector_code = s.get('sector_code', 'unknown')
            sector_data = self.sector_scores.get(sector_code, {})
            sector_score_val = sector_data.get('score', 50)
            sector_bias = sector_data.get('bias', 'NEUTRAL')
            bias_emoji = "↗️" if sector_bias == 'BULLISH' else "↘️" if sector_bias == 'BEARISH' else "➡️"
            print(f"   🏭 Отрасль: {sector_score_val}/100 {bias_emoji}")
            
            for i, block in enumerate(blocks[1:3], 2):
                pot = block.get('potential', 0)
                if block['direction'] == 'UP':
                    dist = (block['current_price'] - block['block_high']) / block['current_price'] * 100
                    dist_str = f"↓{dist:.1f}%"
                else:
                    dist = (block['block_low'] - block['current_price']) / block['current_price'] * 100
                    dist_str = f"↑{dist:.1f}%"
                print(f"   ▸ Блок {i}: {block['block_low']:.2f}-{block['block_high']:.2f} ({dist_str}, пот. {pot:.1f}%)")

# ==============================================================================
# ЧЕК-ЛИСТ ДОРАБОТОК
# ==============================================================================

def print_todo_list():
    print("\n" + "="*80)
    print("📋 ПЛАНИРУЕМЫЕ ДОРАБОТКИ СИСТЕМЫ")
    print("="*80)
    
    todos = [
        ("✅ Обновлённый макроанализ", "Юань, золото, RVI, глобальные индикаторы"),
        ("✅ Визуализация IMOEX", "График с MA50/MA200 и просадкой"),
        ("✅ Учёт технической фазы рынка", "Штраф LONG при коррекции"),
        ("🧠 Обучаемая модель вероятности", "Калибровка весов на основе истории"),
        ("🔔 Telegram-уведомления", "О новых сигналах"),
        ("📉 Учёт ликвидности", "Объёмы торгов, глубина стакана"),
    ]
    
    for i, (task, desc) in enumerate(todos, 1):
        print(f"{i}. {task}")
        print(f"   └── {desc}")
    
    print("="*80)

# ==============================================================================
# ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    if not os.path.exists('.env'):
        print("❌ Файл .env не найден!")
        sys.exit(1)
    
    print("\n" + "="*80)
    print("🚀 ЕДИНЫЙ БЛОЧНЫЙ СКАНЕР v2.0")
    print("="*80)
    
    checker = DataFreshnessChecker()
    needs_update = checker.check_and_notify()
    
    macro_data = input_all_macro_data()
    checker.update_macro()
    with open('macro_data.json', 'w', encoding='utf-8') as f:
        json.dump(macro_data, f, indent=2, ensure_ascii=False)
    print(f"📊 Макроданные сохранены")
    
    if needs_update['sector_ratings']:
        print("\n⚠️ Обновите файл sector_ratings.json, затем нажмите Enter")
        input()
        checker.update_sector_ratings()
    
    fundamentals = {}
    fund_file = "dohod_fundamentals_20260328.json"
    if os.path.exists(fund_file):
        try:
            with open(fund_file, 'r', encoding='utf-8') as f:
                fund_list = json.load(f)
                fundamentals = {item['ticker']: item for item in fund_list}
            print(f"📊 Загружено фундаментальных данных по {len(fundamentals)} компаниям")
        except Exception as e:
            print(f"⚠️ Ошибка загрузки: {e}")
    else:
        print(f"⚠️ Файл {fund_file} не найден")
    
    scanner = UnifiedBlockScanner(
        tickers_to_scan=None,
        max_tickers=100,
        fundamentals=fundamentals,
        macro_data=macro_data
    )
    
    signals = scanner.analyze_all_blocks()
    scanner.print_summary(signals)
    
    input("\nНажмите Enter для выхода...")
# 1.ORDER_BLOCK_3.py
from tradingview_ta import TradingView, Interval
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import sys
import io
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import warnings
import requests
import os
import json
from dotenv import load_dotenv
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import now

warnings.filterwarnings('ignore')

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка кодировки для русского текста
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'DejaVu Sans', 'Liberation Sans']

#==============================================================================
# СОЗДАНИЕ СТРУКТУРЫ ПАПОК
#==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_DIR = os.path.join(BASE_DIR, 'signals')
CHARTS_DIR = os.path.join(BASE_DIR, 'charts')
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Создаем папки при запуске
for dir_path in [SIGNALS_DIR, CHARTS_DIR, DATA_DIR, LOGS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# ❌ ЗАКОММЕНТИРОВАТЬ ИЛИ УДАЛИТЬ:
# print("Структура папок создана:")
# print(f"   signals: {SIGNALS_DIR}")
# print(f"   charts: {CHARTS_DIR}")
# print(f"   data: {DATA_DIR}")
# print(f"   logs: {LOGS_DIR}")

#==============================================================================
# LUXALGO ORDER BLOCK DETECTOR
#==============================================================================

class LuxAlgoOrderBlockDetector:
    """
    Реализация Order Block Detector от LuxAlgo на Python
    Оригинальный код: https://www.tradingview.com/script/DPexNAFN-Order-Block-Detector-LuxAlgo/
    """
    
    def __init__(self, length=5, bull_ext_last=3, bear_ext_last=3, 
                 mitigation_method='Wick'):
        """
        Параметры:
        length: период для Volume Pivot (по умолчанию 5)
        bull_ext_last: количество отображаемых бычьих блоков (по умолчанию 3)
        bear_ext_last: количество отображаемых медвежьих блоков (по умолчанию 3)
        mitigation_method: метод митигации ('Wick' или 'Close')
        """
        self.length = length
        self.bull_ext_last = bull_ext_last
        self.bear_ext_last = bear_ext_last
        self.mitigation_method = mitigation_method
        
    def find_volume_pivots(self, df):
        """
        Находит Volume Pivot Points
        В оригинале: ta.pivothigh(volume, length, length)
        """
        volume = df['volume'].values
        length = self.length
        
        pivot_indices = []
        
        for i in range(length, len(volume) - length):
            left = volume[i-length:i]
            right = volume[i+1:i+length+1]
            current = volume[i]
            
            # Проверяем, является ли текущий объем локальным максимумом
            if current > np.max(left) and current > np.max(right):
                pivot_indices.append(i)
        
        return pivot_indices
    
    def calculate_oscillator(self, df):
        """
        Рассчитывает осциллятор для определения структуры тренда
        В оригинале: os := high[length] > upper ? 0 : low[length] < lower ? 1 : os[1]
        """
        high = df['high'].values
        low = df['low'].values
        length = self.length
        
        # upper = highest(high, length)
        upper = pd.Series(high).rolling(window=length, min_periods=1).max().values
        # lower = lowest(low, length)
        lower = pd.Series(low).rolling(window=length, min_periods=1).min().values
        
        os_values = np.zeros(len(df))
        
        for i in range(length, len(df)):
            if high[i - length] > upper[i]:
                os_values[i] = 0
            elif low[i - length] < lower[i]:
                os_values[i] = 1
            else:
                os_values[i] = os_values[i-1] if i > 0 else 0
        
        return os_values
    
    def detect_blocks(self, df):
        """
        Детектит бычьи и медвежьи ордер блоки по методу LuxAlgo
        """
        bull_blocks = []
        bear_blocks = []
        
        # Получаем объемные пивоты
        pivot_indices = self.find_volume_pivots(df)
        
        # Получаем значения осциллятора
        os_values = self.calculate_oscillator(df)
        
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        time_values = df.index.values
        length = self.length
        
        # Определяем цели для митигации
        if self.mitigation_method == 'Close':
            target_bull = pd.Series(close).rolling(window=length).min().values
            target_bear = pd.Series(close).rolling(window=length).max().values
        else:  # Wick
            target_bull = pd.Series(low).rolling(window=length).min().values
            target_bear = pd.Series(high).rolling(window=length).max().values
        
        for idx in pivot_indices:
            if idx < length or idx >= len(df):
                continue
                
            # Бычий блок: phv and os == 1
            if os_values[idx] == 1:
                block = {
                    'type': 'bull',
                    'top': (high[idx - length] + low[idx - length]) / 2,  # hl2
                    'bottom': low[idx - length],
                    'avg': (high[idx - length] + low[idx - length]) / 2,
                    'time': time_values[idx - length],
                    'index': idx - length,
                    'pivot_idx': idx,
                    'target': target_bull[idx],
                    'mitigated': False,
                    'source': 'LuxAlgo'
                }
                bull_blocks.append(block)
            
            # Медвежий блок: phv and os == 0
            elif os_values[idx] == 0:
                block = {
                    'type': 'bear',
                    'top': high[idx - length],
                    'bottom': (high[idx - length] + low[idx - length]) / 2,  # hl2
                    'avg': (high[idx - length] + low[idx - length]) / 2,
                    'time': time_values[idx - length],
                    'index': idx - length,
                    'pivot_idx': idx,
                    'target': target_bear[idx],
                    'mitigated': False,
                    'source': 'LuxAlgo'
                }
                bear_blocks.append(block)
        
        # Применяем митигацию (блоки "сгорают" при пробое)
        current_price = df['close'].iloc[-1]
        
        for block in bull_blocks:
            if current_price < block['bottom']:  # Цена ниже блока - он сработал
                block['mitigated'] = True
        
        for block in bear_blocks:
            if current_price > block['top']:  # Цена выше блока - он сработал
                block['mitigated'] = True
        
        # Сортируем по свежести и берем последние N
        bull_blocks.sort(key=lambda x: x['index'], reverse=True)
        bear_blocks.sort(key=lambda x: x['index'], reverse=True)
        
        bull_blocks = bull_blocks[:self.bull_ext_last]
        bear_blocks = bear_blocks[:self.bear_ext_last]
        
        return bull_blocks, bear_blocks

#==============================================================================
# FIGI LOADER
#==============================================================================

class FigiLoader:
    def __init__(self, json_file='all_assets.json'):
        """
        Загружает FIGI из JSON файла
        """
        self.json_file = json_file
        self.figi_map = {}
        self.assets_info = {}
        self.load_figi()
    
    def load_figi(self):
        """
        Загружает FIGI из JSON файла
        """
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Загружаем основную информацию
            self.timestamp = data.get('timestamp', '')
            self.period_verified = data.get('period_verified', '')
            self.total_assets = data.get('total_assets', 0)
            
            # Загружаем активы
            assets = data.get('assets', {})
            for ticker, info in assets.items():
                self.figi_map[ticker] = info.get('figi', '')
                self.assets_info[ticker] = {
                    'name': info.get('name', ticker),
                    'figi': info.get('figi', ''),
                    'type': info.get('type', 'share'),
                    'verified': info.get('verified_2022_2025', False)
                }
            
            print(f"📁 Загружено FIGI из {self.json_file}")
            print(f"📊 Всего активов: {self.total_assets}")
            print(f"📅 Период верификации: {self.period_verified}")
            print(f"✅ Загружено FIGI: {len(self.figi_map)}")
            
        except FileNotFoundError:
            print(f"❌ Файл {self.json_file} не найден!")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"❌ Ошибка парсинга JSON файла {self.json_file}")
            sys.exit(1)
    
    def get_figi(self, ticker):
        """
        Возвращает FIGI для тикера
        """
        return self.figi_map.get(ticker, '')
    
    def get_asset_info(self, ticker):
        """
        Возвращает информацию об активе
        """
        return self.assets_info.get(ticker, {})
    
    def get_all_tickers(self):
        """
        Возвращает все доступные тикеры
        """
        return list(self.figi_map.keys())

#==============================================================================
# TINKOFF DATA LOADER
#==============================================================================

class TinkoffDataLoader:
    def __init__(self, token):
        self.token = token
        self.client = Client(token)
    
    def get_historical_candles(self, figi, days=None, from_date=None, to_date=None):
        """Загружает исторические свечи"""
        try:
            from tinkoff.invest import Client, CandleInterval
            
            with Client(os.getenv('TINKOFF_TOKEN')) as client:
                if from_date and to_date:
                    # Загрузка за конкретный период
                    from_dt = datetime.strptime(from_date, '%Y-%m-%d')
                    to_dt = datetime.strptime(to_date, '%Y-%m-%d')
                elif days:
                    # Загрузка за последние N дней
                    to_dt = datetime.now()
                    from_dt = to_dt - timedelta(days=days)
                else:
                    # По умолчанию 90 дней
                    to_dt = datetime.now()
                    from_dt = to_dt - timedelta(days=90)
                
                candles = client.market_data.get_candles(
                    figi=figi,
                    from_=from_dt,
                    to=to_dt,
                    interval=CandleInterval.CANDLE_INTERVAL_DAY
                )
                
                if candles.candles:
                    df = pd.DataFrame([{
                        'date': c.time,
                        'open': c.open.units + c.open.nano / 1e9,
                        'high': c.high.units + c.high.nano / 1e9,
                        'low': c.low.units + c.low.nano / 1e9,
                        'close': c.close.units + c.close.nano / 1e9,
                        'volume': c.volume
                    } for c in candles.candles])
                    return df
                else:
                    return None
        except Exception as e:
            print(f"  ❌ Ошибка получения свечей: {e}")
            return None
    
    def _to_float(self, money_value):
        """
        Конвертирует MoneyValue в float
        """
        return float(money_value.units) + float(money_value.nano) / 1e9

#==============================================================================
# РЫНОЧНЫЙ КОНТЕКСТ (Market Context)
#==============================================================================

class MarketContext:
    """
    Анализ рыночного контекста для выбора направления
    """
    def __init__(self, tinkoff_token):
        self.tinkoff = TinkoffDataLoader(tinkoff_token)
        
        # РАБОЧИЕ FIGI для индексов (акции как прокси)
        self.indexes = {
            'IMOEX': 'BBG004730N88',        # Индекс Мосбиржи (Сбер)
            'MOEXMM': 'BBG004S68B31',       # АЛРОСА (металлы)
            'MOEXFN': 'BBG004730N88',       # Сбер (финансы)
            'MOEXOG': 'BBG004730RP0',       # Газпром (нефть/газ)
            'MOEXCN': 'BBG004RVFFC0',       # Татнефть (потребление)
        }
        
        # Реальные тикеры для отображения
        self.index_names = {
            'IMOEX': 'Индекс Мосбиржи (IMOEX)',
            'MOEXMM': 'АЛРОСА (металлы)',
            'MOEXFN': 'Сбер (финансы)',
            'MOEXOG': 'Газпром (нефть/газ)',
            'MOEXCN': 'Татнефть (потребление)',
        }
        
        # Маппинг тикеров к секторам
        self.sector_map = {
            # Нефть и газ
            'GAZP': 'MOEXOG', 'LKOH': 'MOEXOG', 'ROSN': 'MOEXOG', 
            'TATN': 'MOEXOG', 'SNGS': 'MOEXOG', 'NVTK': 'MOEXOG',
            
            # Металлы
            'CHMF': 'MOEXMM', 'GMKN': 'MOEXMM', 'PLZL': 'MOEXMM', 
            'RUAL': 'MOEXMM', 'ALRS': 'MOEXMM', 'VSMO': 'MOEXMM',
            
            # Финансы
            'SBER': 'MOEXFN', 'VTBR': 'MOEXFN', 'CBOM': 'MOEXFN', 
            'BSPB': 'MOEXFN', 'SBERP': 'MOEXFN',
            
            # Потребление
            'MGNT': 'MOEXCN', 'FIVE': 'MOEXCN', 'LENT': 'MOEXCN', 
            'MVID': 'MOEXCN', 'BELU': 'MOEXCN', 'SOFL': 'MOEXCN',
        }
        
        self.market_data = {}
        self.load_market_data()
    
    def load_market_data(self, days=30):
        """
        Загружает данные по индексам
        """
        print("\n📊 Загрузка рыночных данных...")
        
        working_indexes = {}
        
        for name, figi in self.indexes.items():
            try:
                print(f"  ⏳ Загрузка {self.index_names.get(name, name)}...")
                df = self.tinkoff.get_historical_candles(figi, days=days)
                if df is not None and len(df) > 5:
                    self.market_data[name] = df
                    working_indexes[name] = figi
                    print(f"  ✅ {self.index_names.get(name, name)}: загружено ({len(df)} свечей)")
                else:
                    print(f"  ⚠️ {self.index_names.get(name, name)}: нет данных")
            except Exception as e:
                print(f"  ❌ {self.index_names.get(name, name)}: ошибка - {str(e)[:50]}")
                continue
        
        print(f"  ✅ Загружено индексов: {len(working_indexes)} из {len(self.indexes)}")
    
    def analyze_market(self):
        """
        Комплексный анализ рынка
        """
        if 'IMOEX' not in self.market_data:
            print("  ⚠️ Нет данных по индексу IMOEX")
            return None
        
        imoex = self.market_data['IMOEX']
        current_price = imoex['close'].iloc[-1]
        ema_50 = self.calculate_ema(imoex, 50).iloc[-1]
        ema_200 = self.calculate_ema(imoex, 200).iloc[-1] if len(imoex) > 200 else current_price
        
        # Тренд индекса
        if current_price > ema_50 * 1.01:
            trend = "ВОСХОДЯЩИЙ"
            trend_score = 1
        elif current_price < ema_50 * 0.99:
            trend = "НИСХОДЯЩИЙ"
            trend_score = -1
        else:
            trend = "БОКОВОЙ"
            trend_score = 0
        
        # RSI индекса
        rsi = self.calculate_rsi(imoex)
        
        # Объемный анализ
        volume_sma = imoex['volume'].rolling(20).mean().iloc[-1]
        current_volume = imoex['volume'].iloc[-1]
        volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1
        
        result = {
            'imoex_price': current_price,
            'imoex_ema_50': ema_50,
            'imoex_ema_200': ema_200,
            'trend': trend,
            'trend_score': trend_score,
            'rsi': rsi,
            'volume_ratio': volume_ratio,
            'market_state': self.get_market_state(trend_score, rsi, volume_ratio)
        }
        
        # Выводим информацию
        print(f"\n🌍 РЫНОЧНЫЙ КОНТЕКСТ:")
        print(f"  📊 IMOEX: {current_price:.0f} | EMA50: {ema_50:.0f} | EMA200: {ema_200:.0f}")
        print(f"  📈 Тренд: {trend} | RSI: {rsi:.1f} | Объем: {volume_ratio:.1f}x")
        print(f"  🔄 Состояние: {result['market_state']}")
        
        return result
    
    def calculate_ema(self, df, period=50):
        """Рассчитывает EMA"""
        return df['close'].ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, df, period=14):
        """Расчет RSI"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
    
    def get_market_state(self, trend_score, rsi, volume_ratio):
        """Определение состояния рынка"""
        if trend_score > 0 and rsi < 60 and volume_ratio > 1.2:
            return "ЗДОРОВЫЙ РОСТ"
        elif trend_score > 0 and rsi > 70:
            return "ПЕРЕКУПЛЕННОСТЬ"
        elif trend_score < 0 and rsi > 40 and volume_ratio > 1.2:
            return "ЗДОРОВОЕ ПАДЕНИЕ"
        elif trend_score < 0 and rsi < 30:
            return "ПЕРЕПРОДАННОСТЬ"
        elif abs(trend_score) < 0.1:
            return "БОКОВИК"
        else:
            return "НЕОПРЕДЕЛЕННОСТЬ"
    
    def get_sector_strength(self, ticker):
        """
        Анализ силы сектора относительно рынка
        """
        sector_figi = self.sector_map.get(ticker)
        if not sector_figi or sector_figi not in self.market_data:
            return 0
        
        sector = self.market_data[sector_figi]
        
        # Если есть IMOEX, используем его как рынок
        if 'IMOEX' in self.market_data:
            market = self.market_data['IMOEX']
        else:
            return 0
        
        # Сравниваем динамику за последние 10 дней
        sector_return = (sector['close'].iloc[-1] / sector['close'].iloc[-10] - 1) * 100
        market_return = (market['close'].iloc[-1] / market['close'].iloc[-10] - 1) * 100
        
        relative_strength = sector_return - market_return
        
        if relative_strength > 3:
            return 2
        elif relative_strength > 1:
            return 1
        elif relative_strength > -1:
            return 0
        elif relative_strength > -3:
            return -1
        else:
            return -2
    
    def get_sector_name(self, sector_figi):
        """Возвращает название сектора"""
        sector_names = {
            'MOEXOG': 'Нефть и газ',
            'MOEXMM': 'Металлы',
            'MOEXFN': 'Финансы',
            'MOEXCN': 'Потребление',
        }
        return sector_names.get(sector_figi, 'Неизвестно')
    
    def adjust_signal_for_market(self, signal, market_analysis):
        """
        Корректирует сигнал с учетом рыночного контекста
        """
        if not market_analysis:
            return signal
        
        adjusted = signal.copy()
        original_quality = signal.get('Качество', 0)
        market_notes = []
        
        # 1. Тренд индекса (вес ±15)
        if 'LONG' in signal['Сигнал']:
            if market_analysis['trend_score'] > 0:
                adjusted['Качество'] = original_quality + 15
                market_notes.append('✅ тренд поддерживает LONG')
            elif market_analysis['trend_score'] < 0:
                adjusted['Качество'] = original_quality - 15
                market_notes.append('⚠️ тренд против LONG')
        elif 'SHORT' in signal['Сигнал']:
            if market_analysis['trend_score'] < 0:
                adjusted['Качество'] = original_quality + 15
                market_notes.append('✅ тренд поддерживает SHORT')
            elif market_analysis['trend_score'] > 0:
                adjusted['Качество'] = original_quality - 15
                market_notes.append('⚠️ тренд против SHORT')
        
        # 2. ЭКСТРЕМАЛЬНЫЕ СОСТОЯНИЯ РЫНКА
        rsi = market_analysis.get('rsi', 50)
        
        # Экстремальная перекупленность (RSI > 90)
        if rsi > 90:
            if 'SHORT' in signal['Сигнал']:
                adjusted['Качество'] += 20
                market_notes.append('🔥 рынок сильно перекуплен')
            elif 'LONG' in signal['Сигнал']:
                adjusted['Качество'] -= 30
                market_notes.append('⚠️ ОПАСНО: рынок перекуплен')
        
        # Экстремальная перепроданность (RSI < 10)
        elif rsi < 10:
            if 'LONG' in signal['Сигнал']:
                adjusted['Качество'] += 20
                market_notes.append('🔥 рынок сильно перепродан')
            elif 'SHORT' in signal['Сигнал']:
                adjusted['Качество'] -= 30
                market_notes.append('⚠️ ОПАСНО: рынок перепродан')
        
        # Умеренная перекупленность (70 < RSI <= 90)
        elif rsi > 70:
            if 'SHORT' in signal['Сигнал']:
                adjusted['Качество'] += 10
                market_notes.append('📈 рынок перекуплен')
            elif 'LONG' in signal['Сигнал']:
                adjusted['Качество'] -= 10
                market_notes.append('⚠️ рынок перекуплен')
        
        # Умеренная перепроданность (10 <= RSI < 30)
        elif rsi < 30:
            if 'LONG' in signal['Сигнал']:
                adjusted['Качество'] += 10
                market_notes.append('📉 рынок перепродан')
            elif 'SHORT' in signal['Сигнал']:
                adjusted['Качество'] -= 10
                market_notes.append('⚠️ рынок перепродан')
        
        # 3. Секторный анализ (вес ±10)
        sector_strength = self.get_sector_strength(signal['Тикер'])
        sector_figi = self.sector_map.get(signal['Тикер'])
        sector_name = self.get_sector_name(sector_figi) if sector_figi else 'Неизвестно'
        
        if sector_strength != 0:
            if 'LONG' in signal['Сигнал'] and sector_strength > 0:
                adjusted['Качество'] += 10
                market_notes.append(f'🏭 сектор {sector_name} сильнее рынка')
            elif 'SHORT' in signal['Сигнал'] and sector_strength < 0:
                adjusted['Качество'] += 10
                market_notes.append(f'🏭 сектор {sector_name} слабее рынка')
            elif 'LONG' in signal['Сигнал'] and sector_strength < 0:
                adjusted['Качество'] -= 5
                market_notes.append(f'⚠️ сектор {sector_name} слабее рынка')
            elif 'SHORT' in signal['Сигнал'] and sector_strength > 0:
                adjusted['Качество'] -= 5
                market_notes.append(f'⚠️ сектор {sector_name} сильнее рынка')
        
        # Не даем качеству уйти ниже 0 или выше 100
        adjusted['Качество'] = max(0, min(100, adjusted['Качество']))
        adjusted['market_note'] = ' | '.join(market_notes) if market_notes else 'нейтральный контекст'
        
        return adjusted

#==============================================================================
# СИСТЕМА ПОДТВЕРЖДЕНИЯ ВХОДА (Entry Confirmation) - ИСПРАВЛЕННАЯ ВЕРСИЯ
#==============================================================================

class EntryConfirmation:
    """
    Логика подтверждения входа на основе свечных паттернов и объема
    """
    def __init__(self):
        self.confirmation_score = 0
        self.signals = []
        
    def analyze_candle(self, df, signal_type, use_closed_only=True):
        """
        Анализирует свечи для подтверждения сигнала
        Если use_closed_only=True - использует только закрытые свечи (вчера и раньше)
        Возвращает score от 0 до 100 и детали
        """
        if len(df) < 3:
            return 0, ["Недостаточно данных"], False
        
        score = 0
        details = []
        requires_today_close = False
        
        # Определяем, какие свечи использовать
        if use_closed_only:
            # Используем ТОЛЬКО закрытые свечи (все кроме сегодняшней)
            # Индекс -1 - сегодня (не закрыта), -2 - вчера (закрыта), -3 - позавчера и т.д.
            if len(df) < 3:
                return 0, ["Недостаточно закрытых свечей"], True
            
            # Берем вчерашнюю и позавчерашнюю свечи (обе закрыты)
            yesterday = df.iloc[-2]
            day_before = df.iloc[-3]
            
            # Сегодняшняя свеча (незакрытая) - только для информации
            today = df.iloc[-1]
            today_open = today['open']
            today_high = today['high']
            today_low = today['low']
            today_close = today['close']
        else:
            # Используем все свечи, включая сегодняшнюю (для предварительного анализа)
            yesterday = df.iloc[-2]
            day_before = df.iloc[-3]
            today = df.iloc[-1]
            today_open = today['open']
            today_high = today['high']
            today_low = today['low']
            today_close = today['close']
        
        #======================================================================
        # АНАЛИЗ ПО ЗАКРЫТЫМ СВЕЧАМ (вчера и позавчера)
        #======================================================================
        
        # Считаем закрытые свечи за последние дни
        closed_red_count = 0
        closed_green_count = 0
        
        for i in range(2, min(6, len(df))):  # Смотрим до 4 закрытых свечей
            candle = df.iloc[-i]
            if candle['close'] < candle['open']:
                closed_red_count += 1
            else:
                closed_green_count += 1
        
        if signal_type == 'SHORT':
            # ШОРТ: нужны красные свечи
            if closed_red_count >= 2:
                score += 30
                details.append(f"📊 {closed_red_count} закрытых красных свечи (+30)")
            elif closed_red_count == 1:
                score += 15
                details.append(f"📊 1 закрытая красная свеча (+15)")
                requires_today_close = True
            
            # Проверка на необновление хая (вчера vs позавчера)
            if yesterday['high'] <= day_before['high']:
                score += 20
                details.append(f"📉 вчера не обновила хай (+20)")
            
            # Проверка закрытия в нижней части
            candle_range = yesterday['high'] - yesterday['low']
            if candle_range > 0:
                close_position = (yesterday['close'] - yesterday['low']) / candle_range
                if close_position < 0.3:
                    score += 15
                    details.append(f"⬇️ вчера закрылась внизу (+15)")
        
        else:  # LONG
            # ЛОНГ: нужны зеленые свечи
            if closed_green_count >= 2:
                score += 30
                details.append(f"📊 {closed_green_count} закрытых зеленых свечи (+30)")
            elif closed_green_count == 1:
                score += 15
                details.append(f"📊 1 закрытая зеленая свеча (+15)")
                requires_today_close = True
            
            # Проверка на необновление лоя (вчера vs позавчера)
            if yesterday['low'] >= day_before['low']:
                score += 20
                details.append(f"📈 вчера не обновила лой (+20)")
            
            # Проверка закрытия в верхней части
            candle_range = yesterday['high'] - yesterday['low']
            if candle_range > 0:
                close_position = (yesterday['close'] - yesterday['low']) / candle_range
                if close_position > 0.7:
                    score += 15
                    details.append(f"⬆️ вчера закрылась вверху (+15)")
        
        #======================================================================
        # ИНФОРМАЦИЯ О СЕГОДНЯШНЕЙ СВЕЧЕ (не влияет на решение, только для информации)
        #======================================================================
        
        if not use_closed_only:
            if signal_type == 'SHORT':
                if today_close < today_open:
                    details.append(f"🔄 сегодня идет красная (незакрыта)")
                elif today_high > yesterday['high']:
                    details.append(f"🔄 сегодня обновляет хай (незакрыта)")
            else:
                if today_close > today_open:
                    details.append(f"🔄 сегодня идет зеленая (незакрыта)")
                elif today_low < yesterday['low']:
                    details.append(f"🔄 сегодня обновляет лой (незакрыта)")
        
        return score, details, requires_today_close

#==============================================================================
# EOD АНАЛИЗ - ДНЕВНЫЕ СНИМКИ
#==============================================================================

class DailySnapshot:
    """
    Фиксация состояния 1 раз в день в 19:00 МСК
    """
    def __init__(self):
        self.snapshot_file = os.path.join(DATA_DIR, 'daily_signals.json')
        self.load_snapshots()
    
    def load_snapshots(self):
        if os.path.exists(self.snapshot_file):
            with open(self.snapshot_file, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        else:
            self.data = {'snapshots': []}
    
    def save_snapshot(self, signals, market_context):
        """
        Сохраняет дневной снимок (только если еще не сохраняли сегодня)
        """
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Проверяем, есть ли уже снимок за сегодня
        for snap in self.data['snapshots']:
            if snap['date'] == today:
                print(f"📅 Снимок за {today} уже существует")
                return False
        
        # Группируем сигналы по группам
        group_a = [s for s in signals if s.get('group') == 'A']
        group_b = [s for s in signals if s.get('group') == 'B']
        group_c = [s for s in signals if s.get('group') == 'C']
        
        # Создаем новый снимок
        snapshot = {
            'date': today,
            'timestamp': datetime.now().strftime('%H:%M'),
            'market': {
                'imoex': market_context.get('imoex_price', 0),
                'trend': market_context.get('trend', ''),
                'rsi': market_context.get('rsi', 50),
                'state': market_context.get('market_state', '')
            },
            'total_signals': len(signals),
            'group_a': len(group_a),
            'group_b': len(group_b),
            'group_c': len(group_c),
            'signals': [
                {
                    'ticker': s['Тикер'],
                    'signal': s['Сигнал'],
                    'type': 'LONG' if 'LONG' in s['Сигнал'] else 'SHORT',
                    'price': s['Цена'],
                    'stoch': s['Stoch'],
                    'quality': s.get('Качество', 0),
                    'group': s.get('group', 'C'),
                    'closed_score': s.get('closed_score', 0)
                }
                for s in signals
            ]
        }
        
        self.data['snapshots'].append(snapshot)
        self.cleanup_old_snapshots(keep_days=30)
        self.save()
        print(f"✅ Дневной снимок за {today} сохранен")
        return True
    
    def cleanup_old_snapshots(self, keep_days=30):
        """Оставляет только последние 30 дней"""
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime('%Y-%m-%d')
        self.data['snapshots'] = [
            snap for snap in self.data['snapshots'] 
            if snap['date'] >= cutoff
        ]
    
    def save(self):
        with open(self.snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def print_statistics(self):
        """
        Вывод статистики по дням
        """
        if len(self.data['snapshots']) < 2:
            print("\n📭 Недостаточно данных (нужно минимум 2 дня)")
            return
        
        print("\n" + "="*100)
        print("📊 СТАТИСТИКА ПО ДНЯМ")
        print("="*100)
        
        # Последние 7 дней
        recent = self.data['snapshots'][-7:]
        
        # Таблица
        print(f"\n{'Дата':<12} {'Всего':<8} {'A':<6} {'B':<6} {'C':<6} {'Рынок':<20}")
        print("-"*70)
        
        for snap in recent:
            print(f"{snap['date']:<12} {snap['total_signals']:<8} "
                  f"{snap['group_a']:<6} {snap['group_b']:<6} {snap['group_c']:<6} "
                  f"{snap['market']['state'][:20]:<20}")
        
        # Динамика
        if len(recent) >= 2:
            last = recent[-1]
            prev = recent[-2]
            
            delta_a = last['group_a'] - prev['group_a']
            delta_b = last['group_b'] - prev['group_b']
            
            print(f"\n📈 Динамика за день:")
            if delta_a > 0:
                print(f"   Группа A: +{delta_a} 🔼")
            elif delta_a < 0:
                print(f"   Группа A: {delta_a} 🔽")
            else:
                print(f"   Группа A: 0 ⏺️")
    
    def get_best_days(self):
        """
        Показывает дни с наибольшим количеством сигналов группы А
        """
        if not self.data['snapshots']:
            return
        
        sorted_days = sorted(self.data['snapshots'], 
                           key=lambda x: x['group_a'], 
                           reverse=True)
        
        print("\n" + "="*100)
        print("🏆 ЛУЧШИЕ ДНИ ПО КОЛИЧЕСТВУ СИГНАЛОВ ГРУППЫ А")
        print("="*100)
        
        for i, day in enumerate(sorted_days[:5], 1):
            print(f"\n{i}. {day['date']} - {day['group_a']} сигналов")
            print(f"   Рынок: {day['market']['state']}")
            if day['group_a'] > 0:
                top = [s['ticker'] for s in day['signals'] if s['group'] == 'A'][:3]
                print(f"   Топ: {', '.join(top)}")

class EndOfDayAnalyzer:
    """
    Анализатор для EOD данных
    """
    def __init__(self):
        self.snapshot = DailySnapshot()
    
    def should_take_snapshot(self):
        """
        Проверяет, пора ли делать снимок (19:00 МСК)
        """
        now = datetime.now()
        # С 18:30 до 19:30 считаем концом дня
        if now.hour == 19 or (now.hour == 18 and now.minute >= 30):
            return True
        return False
    
    def process_end_of_day(self, scanner):
        """
        Обработка конца торгового дня
        """
        if not self.should_take_snapshot():
            return False
        
        print("\n" + "="*100)
        print("📅 КОНЕЦ ТОРГОВОГО ДНЯ - ФИКСАЦИЯ ДАННЫХ")
        print("="*100)
        
        if scanner.signals and scanner.market_analysis:
            saved = self.snapshot.save_snapshot(scanner.signals, scanner.market_analysis)
            
            if saved:
                # Показываем статистику
                self.snapshot.print_statistics()
                self.snapshot.get_best_days()
                return True
        return False

#==============================================================================
# СИСТЕМА ГРУППИРОВКИ СИГНАЛОВ - ИСПРАВЛЕННАЯ ВЕРСИЯ
#==============================================================================

class SignalGrouper:
    """
    Группирует сигналы по готовности к входу
    Группа А: можно входить (подтверждение на закрытых свечах)
    Группа Б: ждем закрытия сегодня (нужно подтверждение текущей свечой)
    Группа В: наблюдение (недостаточно данных)
    """
    
    @staticmethod
    def classify_signal(signal, df, market_analysis):
        """
        Классифицирует сигнал по группам А/Б/В на основе ТОЛЬКО закрытых свечей
        и с ФИКСАЦИЕЙ на вчерашние данные
        """
        signal_type = 'LONG' if 'LONG' in signal['Сигнал'] else 'SHORT'
        
        # ===== ВАЖНО! Фиксируем данные на ВЧЕРА =====
        yesterday_close = df.iloc[-2]['close']  # цена закрытия вчера
        yesterday_high = df.iloc[-2]['high']    # максимум вчера
        yesterday_low = df.iloc[-2]['low']      # минимум вчера
        yesterday_volume = df.iloc[-2]['volume'] # объем вчера
        
        # Получаем подтверждение ТОЛЬКО по закрытым свечам (вчера и раньше)
        confirmer = EntryConfirmation()
        closed_score, closed_details, requires_today = confirmer.analyze_candle(
            df, signal_type, use_closed_only=True
        )
        
        # Проверяем рыночный контекст (он тоже должен быть вчерашним!)
        market_ok = True
        market_note = ""
        if market_analysis:
            # Используем вчерашние данные рынка
            if signal_type == 'LONG' and market_analysis.get('trend_score', 0) < 0:
                market_ok = False
                market_note = "тренд против (вчера)"
            elif signal_type == 'SHORT' and market_analysis.get('trend_score', 0) > 0:
                market_ok = False
                market_note = "тренд против (вчера)"
        
        # Определяем группу
        group = None
        group_reason = []
        
        # ГРУППА А: Решение готово (по вчерашним данным)
        if closed_score >= 50 and market_ok:
            group = 'A'
            group_reason = ["✅ решение по вчерашним данным"]
            if closed_score >= 70:
                group_reason.append("🔥 сильный сигнал")
        
        # ГРУППА Б: Ждем закрытия сегодня
        elif requires_today and market_ok:
            group = 'B'
            group_reason = ["⏳ нужно подтверждение сегодняшней свечой"]
            if closed_score > 0:
                group_reason.append(f"уже есть {closed_score} баллов")
        
        # ГРУППА В: Наблюдение
        else:
            group = 'C'
            group_reason = ["👀 наблюдение"]
            if not market_ok:
                group_reason.append(market_note)
            elif closed_score < 30:
                group_reason.append("недостаточно данных")
        
        return {
            'group': group,
            'closed_score': closed_score,
            'closed_details': closed_details,
            'requires_today': requires_today,
            'group_reason': group_reason,
            'market_ok': market_ok,
            # Добавляем зафиксированные вчерашние данные
            'yesterday_close': yesterday_close,
            'yesterday_high': yesterday_high,
            'yesterday_low': yesterday_low,
            'yesterday_volume': yesterday_volume
        }
    
#==============================================================================
# ORDER BLOCK SCANNER (ОСНОВНОЙ КЛАСС)
#==============================================================================

class OrderBlockScanner:
    def __init__(self, tickers_to_scan=None, max_tickers=100):
        # НАСТРОЙКИ (можно менять)
        self.stoch_oversold = 25
        self.stoch_overbought = 75
        
        # Настройки для нашего метода поиска блоков
        self.consolidation_range_percent = 3.5
        self.impulse_min_percent = 2.5
        self.max_block_age = 50
        self.max_blocks_to_show = 3
        
        # Порог качества сигнала (0-100)
        self.quality_threshold = 60
        
        # Инициализируем LuxAlgo детектор
        self.luxalgo_detector = LuxAlgoOrderBlockDetector(
            length=5,
            bull_ext_last=3,
            bear_ext_last=3,
            mitigation_method='Wick'
        )
        
        # Tinkoff API токен из .env
        self.tinkoff_token = os.getenv('TINKOFF_TOKEN', '')
        if not self.tinkoff_token:
            print("❌ ОШИБКА: Не найден TINKOFF_TOKEN в .env файле")
            print("Добавьте строку: TINKOFF_TOKEN=ваш_токен")
            sys.exit(1)
        
        # Загружаем FIGI из JSON
        print("\n📁 Загрузка FIGI из файла...")
        self.figi_loader = FigiLoader('all_assets.json')
        
        # Определяем тикеры для сканирования
        if tickers_to_scan:
            self.tickers = [t for t in tickers_to_scan if t in self.figi_loader.figi_map]
            print(f"📊 Используем указанные тикеры: {len(self.tickers)}")
        else:
            # Берем ВСЕ верифицированные тикеры
            all_tickers = self.figi_loader.get_all_tickers()
            self.tickers = all_tickers[:max_tickers]
            print(f"📊 Используем {len(self.tickers)} тикеров из {len(all_tickers)}")
        
        # Инициализируем загрузчик данных Tinkoff
        self.tinkoff = TinkoffDataLoader(self.tinkoff_token)
        
        # Инициализируем рыночный контекст
        print("\n📊 Загрузка рыночного контекста...")
        self.market_context = MarketContext(self.tinkoff_token)
        self.market_analysis = self.market_context.analyze_market()
        
        self.signals = []
        self.all_data = {}
        
        # Инициализируем группировщик сигналов
        self.signal_grouper = SignalGrouper()
        
        # Показываем пример тикеров
        print(f"\n📈 Будем сканировать:")
        for i, ticker in enumerate(self.tickers[:10], 1):
            info = self.figi_loader.get_asset_info(ticker)
            name = info.get('name', '')[:30] if info.get('name') else ''
            print(f"  {i}. {ticker} - {name}")
        if len(self.tickers) > 10:
            print(f"  ... и еще {len(self.tickers) - 10}")
    
    def calculate_stochastic(self, df, k_period=14, d_period=3):
        """
        Рассчитывает стохастик для DataFrame
        """
        low_min = df['low'].rolling(window=k_period).min()
        high_max = df['high'].rolling(window=k_period).max()
        
        df['Stoch_K'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
        df['Stoch_D'] = df['Stoch_K'].rolling(window=d_period).mean()
        
        return df
    
    def calculate_adx(self, df, period=14):
        """
        Рассчитывает ADX (Average Directional Index)
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift())
        ], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(window=period).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm).rolling(window=period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 25
    
    def check_divergence(self, df, lookback=10):
        """
        Поиск дивергенций между ценой и стохастиком - ИСПРАВЛЕННАЯ ВЕРСИЯ
        """
        if len(df) < lookback:
            return None
        
        # Берем numpy массивы вместо pandas Series
        price = df['close'].values[-lookback:]
        stoch = df['Stoch_K'].values[-lookback:]
        
        # Бычья дивергенция: цена делает новый минимум, стохастик - нет
        if price[-1] < np.min(price[:-1]) and stoch[-1] > np.min(stoch[:-1]):
            return 'bullish'
        
        # Медвежья дивергенция: цена делает новый максимум, стохастик - нет
        if price[-1] > np.max(price[:-1]) and stoch[-1] < np.max(stoch[:-1]):
            return 'bearish'
        
        return None
    
    def calculate_signal_quality(self, df, signal_type, blocks_our, blocks_luxalgo, price_to_blocks):
        """
        Оценка качества сигнала по множеству факторов
        """
        score = 0
        details = []
        
        current_stoch = df['Stoch_K'].iloc[-1] if not pd.isna(df['Stoch_K'].iloc[-1]) else 50
        
        # 1. ADX
        try:
            adx = self.calculate_adx(df)
            if adx > 30:
                score += 15
                details.append(f"ADX={adx:.1f} >30 (+15)")
            elif adx > 25:
                score += 10
                details.append(f"ADX={adx:.1f} >25 (+10)")
            elif adx > 20:
                score += 5
                details.append(f"ADX={adx:.1f} >20 (+5)")
        except:
            pass
        
        # 2. Объем
        try:
            volume_sma = df['volume'].rolling(20).mean().iloc[-1]
            current_volume = df['volume'].iloc[-1]
            volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1
            
            if volume_ratio > 2.0:
                score += 15
                details.append(f"Объем x{volume_ratio:.1f} (+15)")
            elif volume_ratio > 1.5:
                score += 10
                details.append(f"Объем x{volume_ratio:.1f} (+10)")
            elif volume_ratio > 1.2:
                score += 5
                details.append(f"Объем x{volume_ratio:.1f} (+5)")
        except:
            pass
        
        # 3. Дивергенция
        divergence = self.check_divergence(df)
        if divergence:
            if (signal_type == 'LONG' and divergence == 'bullish') or \
               (signal_type == 'SHORT' and divergence == 'bearish'):
                score += 20
                details.append(f"{divergence.capitalize()} дивергенция (+20)")
        
        # 4. Блоки
        if signal_type == 'LONG':
            if price_to_blocks['combined']['near_bull']:
                methods = []
                if price_to_blocks['our_method']['near_bull']:
                    methods.append('наш')
                if price_to_blocks['luxalgo']['near_bull']:
                    methods.append('LuxAlgo')
                
                method_score = len(methods) * 10
                score += method_score
                details.append(f"Блоки: {', '.join(methods)} (+{method_score})")
        else:
            if price_to_blocks['combined']['near_bear']:
                methods = []
                if price_to_blocks['our_method']['near_bear']:
                    methods.append('наш')
                if price_to_blocks['luxalgo']['near_bear']:
                    methods.append('LuxAlgo')
                
                method_score = len(methods) * 10
                score += method_score
                details.append(f"Блоки: {', '.join(methods)} (+{method_score})")
        
        # 5. Экстремальность стохастика
        if signal_type == 'LONG':
            if current_stoch < 10:
                score += 15
                details.append(f"Stoch={current_stoch:.1f} (<10) (+15)")
            elif current_stoch < 15:
                score += 10
                details.append(f"Stoch={current_stoch:.1f} (<15) (+10)")
            elif current_stoch < 20:
                score += 5
                details.append(f"Stoch={current_stoch:.1f} (<20) (+5)")
        else:
            if current_stoch > 90:
                score += 15
                details.append(f"Stoch={current_stoch:.1f} (>90) (+15)")
            elif current_stoch > 85:
                score += 10
                details.append(f"Stoch={current_stoch:.1f} (>85) (+10)")
            elif current_stoch > 80:
                score += 5
                details.append(f"Stoch={current_stoch:.1f} (>80) (+5)")
        
        return score, details
    
    def find_order_blocks_our_method(self, df):
        """
        Наш метод поиска ордер блоков (консолидация + импульс)
        """
        blocks = {'bull': [], 'bear': []}
        
        df['is_bull_block'] = False
        df['is_bear_block'] = False
        
        start_idx = max(10, len(df) - self.max_block_age)
        
        for i in range(start_idx, len(df) - 5):
            cons_length = min(6, i - max(0, i-10))
            cons_start = max(0, i - cons_length)
            cons_end = i
            
            cons_df = df.iloc[cons_start:cons_end]
            
            cons_range = cons_df['high'].max() - cons_df['low'].min()
            cons_range_percent = cons_range / cons_df['close'].mean() * 100
            
            up_candles = sum(cons_df['close'] >= cons_df['open'])
            down_candles = len(cons_df) - up_candles
            is_mixed = up_candles > 0 and down_candles > 0
            
            if cons_range_percent < self.consolidation_range_percent and is_mixed:
                if i + 3 < len(df):
                    future_df = df.iloc[i:i+3]
                    price_change = (future_df['close'].iloc[-1] - cons_df['close'].iloc[-1]) / cons_df['close'].iloc[-1] * 100
                    
                    if price_change > self.impulse_min_percent:
                        block_info = {
                            'type': 'bull',
                            'method': 'our',
                            'high': cons_df['high'].max(),
                            'low': cons_df['low'].min(),
                            'start_idx': cons_start,
                            'end_idx': cons_end,
                            'start_date': cons_df.index[0],
                            'end_date': cons_df.index[-1],
                            'strength': price_change,
                            'impulse_idx': i,
                            'age': len(df) - i,
                            'mitigated': False
                        }
                        blocks['bull'].append(block_info)
                        df.loc[cons_df.index, 'is_bull_block'] = True
                    
                    elif price_change < -self.impulse_min_percent:
                        block_info = {
                            'type': 'bear',
                            'method': 'our',
                            'high': cons_df['high'].max(),
                            'low': cons_df['low'].min(),
                            'start_idx': cons_start,
                            'end_idx': cons_end,
                            'start_date': cons_df.index[0],
                            'end_date': cons_df.index[-1],
                            'strength': abs(price_change),
                            'impulse_idx': i,
                            'age': len(df) - i,
                            'mitigated': False
                        }
                        blocks['bear'].append(block_info)
                        df.loc[cons_df.index, 'is_bear_block'] = True
        
        blocks['bull'].sort(key=lambda x: x['age'])
        blocks['bear'].sort(key=lambda x: x['age'])
        
        return blocks
    
    def find_order_blocks_luxalgo(self, df):
        """
        Метод LuxAlgo для поиска ордер блоков
        """
        try:
            bull_blocks, bear_blocks = self.luxalgo_detector.detect_blocks(df)
        except Exception as e:
            print(f"    Ошибка в LuxAlgo detect_blocks: {e}")
            return {'bull': [], 'bear': []}
        
        blocks = {'bull': [], 'bear': []}
        
        for block in bull_blocks:
            try:
                start_date = block['time']
                
                if isinstance(start_date, (int, float, np.integer, np.floating)):
                    try:
                        if start_date > 1e15:
                            start_date = pd.to_datetime(start_date / 1000, unit='ns')
                        elif start_date > 1e12:
                            start_date = pd.to_datetime(start_date, unit='ns')
                        elif start_date > 1e9:
                            start_date = pd.to_datetime(start_date, unit='us')
                        else:
                            start_date = pd.to_datetime(start_date, unit='s')
                    except:
                        start_date = datetime.now() - timedelta(days=30)
                
                if not isinstance(start_date, (pd.Timestamp, datetime)):
                    start_date = datetime.now() - timedelta(days=30)
                
                blocks['bull'].append({
                    'type': 'bull',
                    'method': 'luxalgo',
                    'high': float(block['top']),
                    'low': float(block['bottom']),
                    'avg': float(block['avg']),
                    'start_idx': max(0, int(block['index']) - 2),
                    'end_idx': min(len(df)-1, int(block['index']) + 2),
                    'start_date': start_date,
                    'end_date': start_date,
                    'strength': None,
                    'age': len(df) - int(block['index']),
                    'mitigated': bool(block['mitigated']),
                    'pivot_idx': int(block['pivot_idx'])
                })
            except Exception as e:
                continue
        
        for block in bear_blocks:
            try:
                start_date = block['time']
                
                if isinstance(start_date, (int, float, np.integer, np.floating)):
                    try:
                        if start_date > 1e15:
                            start_date = pd.to_datetime(start_date / 1000, unit='ns')
                        elif start_date > 1e12:
                            start_date = pd.to_datetime(start_date, unit='ns')
                        elif start_date > 1e9:
                            start_date = pd.to_datetime(start_date, unit='us')
                        else:
                            start_date = pd.to_datetime(start_date, unit='s')
                    except:
                        start_date = datetime.now() - timedelta(days=30)
                
                if not isinstance(start_date, (pd.Timestamp, datetime)):
                    start_date = datetime.now() - timedelta(days=30)
                
                blocks['bear'].append({
                    'type': 'bear',
                    'method': 'luxalgo',
                    'high': float(block['top']),
                    'low': float(block['bottom']),
                    'avg': float(block['avg']),
                    'start_idx': max(0, int(block['index']) - 2),
                    'end_idx': min(len(df)-1, int(block['index']) + 2),
                    'start_date': start_date,
                    'end_date': start_date,
                    'strength': None,
                    'age': len(df) - int(block['index']),
                    'mitigated': bool(block['mitigated']),
                    'pivot_idx': int(block['pivot_idx'])
                })
            except Exception as e:
                continue
        
        return blocks
    
    def check_price_to_blocks(self, price, blocks_our, blocks_luxalgo):
        """
        Проверяет положение цены относительно блоков
        """
        result = {
            'our_method': {
                'near_bull': False,
                'near_bear': False,
                'distance_bull': None,
                'distance_bear': None
            },
            'luxalgo': {
                'near_bull': False,
                'near_bear': False,
                'distance_bull': None,
                'distance_bear': None
            },
            'combined': {
                'near_bull': False,
                'near_bear': False
            }
        }
        
        for block in blocks_our['bull']:
            if block['mitigated']:
                continue
            if block['low'] <= price <= block['high']:
                result['our_method']['near_bull'] = True
                result['combined']['near_bull'] = True
                result['our_method']['distance_bull'] = 0
                break
            else:
                distance = min(abs(price - block['low']), abs(price - block['high'])) / price * 100
                if distance < 3:
                    result['our_method']['near_bull'] = True
                    result['combined']['near_bull'] = True
                    result['our_method']['distance_bull'] = round(distance, 2)
        
        for block in blocks_our['bear']:
            if block['mitigated']:
                continue
            if block['low'] <= price <= block['high']:
                result['our_method']['near_bear'] = True
                result['combined']['near_bear'] = True
                result['our_method']['distance_bear'] = 0
                break
            else:
                distance = min(abs(price - block['low']), abs(price - block['high'])) / price * 100
                if distance < 3:
                    result['our_method']['near_bear'] = True
                    result['combined']['near_bear'] = True
                    result['our_method']['distance_bear'] = round(distance, 2)
        
        for block in blocks_luxalgo['bull']:
            if block['mitigated']:
                continue
            if block['low'] <= price <= block['high']:
                result['luxalgo']['near_bull'] = True
                result['combined']['near_bull'] = True
                result['luxalgo']['distance_bull'] = 0
                break
            else:
                distance = min(abs(price - block['low']), abs(price - block['high'])) / price * 100
                if distance < 3:
                    result['luxalgo']['near_bull'] = True
                    result['combined']['near_bull'] = True
                    result['luxalgo']['distance_bull'] = round(distance, 2)
        
        for block in blocks_luxalgo['bear']:
            if block['mitigated']:
                continue
            if block['low'] <= price <= block['high']:
                result['luxalgo']['near_bear'] = True
                result['combined']['near_bear'] = True
                result['luxalgo']['distance_bear'] = 0
                break
            else:
                distance = min(abs(price - block['low']), abs(price - block['high'])) / price * 100
                if distance < 3:
                    result['luxalgo']['near_bear'] = True
                    result['combined']['near_bear'] = True
                    result['luxalgo']['distance_bear'] = round(distance, 2)
        
        return result
    
    def plot_chart(self, df, ticker, signal_info=None, quality_score=None, 
                   quality_details=None, blocks_our=None, blocks_luxalgo=None):
        """
        Рисует график с ордер блоками, продленными до конца
        """
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 11), 
                                            gridspec_kw={'height_ratios': [3, 1, 1]})
        
        last_idx = len(df) - 1  # индекс последней свечи
        
        # 1. ГРАФИК ЦЕНЫ - Рисуем свечи
        for i, (idx, row) in enumerate(df.iterrows()):
            color = 'green' if row['close'] >= row['open'] else 'red'
            
            # Тень свечи
            ax1.plot([i, i], [row['low'], row['high']], 
                    color=color, linewidth=1, alpha=0.5)
            
            # Тело свечи
            body_bottom = min(row['open'], row['close'])
            body_top = max(row['open'], row['close'])
            rect = Rectangle((i - 0.4, body_bottom), 0.8, body_top - body_bottom,
                           facecolor=color, alpha=0.8, edgecolor=color)
            ax1.add_patch(rect)
        
        # =====================================================================
        # РИСУЕМ БЛОКИ ОТ НАШЕГО МЕТОДА (сплошные, продленные)
        # =====================================================================
        if blocks_our:
            # Бычьи блоки
            for block in blocks_our['bull']:
                if block['mitigated']:
                    # Митигированные - серые, бледные
                    facecolor = 'gray'
                    edgecolor = 'darkgray'
                    alpha = 0.1
                    linewidth = 1
                else:
                    # Активные - зеленые
                    facecolor = 'green'
                    edgecolor = 'green'
                    age = block.get('age', 30)
                    alpha = max(0.15, 0.4 - (age / 100))
                    linewidth = 2
                
                rect = Rectangle((block['start_idx'] - 0.5, block['low']), 
                               last_idx - block['start_idx'] + 1,  # продлеваем до конца
                               block['high'] - block['low'],
                               facecolor=facecolor, alpha=alpha, edgecolor=edgecolor, 
                               linewidth=linewidth, linestyle='-')
                ax1.add_patch(rect)
                
                # Вертикальная черта в начале блока
                ax1.axvline(x=block['start_idx'] - 0.5, color=edgecolor, 
                           linewidth=1, linestyle=':', alpha=0.5)
            
            # Медвежьи блоки
            for block in blocks_our['bear']:
                if block['mitigated']:
                    facecolor = 'gray'
                    edgecolor = 'darkgray'
                    alpha = 0.1
                    linewidth = 1
                else:
                    facecolor = 'red'
                    edgecolor = 'red'
                    age = block.get('age', 30)
                    alpha = max(0.15, 0.4 - (age / 100))
                    linewidth = 2
                
                rect = Rectangle((block['start_idx'] - 0.5, block['low']), 
                               last_idx - block['start_idx'] + 1,
                               block['high'] - block['low'],
                               facecolor=facecolor, alpha=alpha, edgecolor=edgecolor, 
                               linewidth=linewidth, linestyle='-')
                ax1.add_patch(rect)
                
                ax1.axvline(x=block['start_idx'] - 0.5, color=edgecolor, 
                           linewidth=1, linestyle=':', alpha=0.5)
        
        # =====================================================================
        # РИСУЕМ БЛОКИ ОТ LUXALGO (пунктирные, продленные)
        # =====================================================================
        if blocks_luxalgo:
            # Бычьи блоки LuxAlgo
            for i, block in enumerate(blocks_luxalgo['bull']):
                if block['mitigated']:
                    edgecolor = 'gray'
                    alpha = 0.1
                else:
                    edgecolor = 'lime'
                    alpha = 0.3
                
                start_x = block['start_idx'] - 0.5
                rect = Rectangle((start_x, block['low']), 
                               last_idx - block['start_idx'] + 1,
                               block['high'] - block['low'],
                               facecolor='none', alpha=alpha, edgecolor=edgecolor, 
                               linewidth=2, linestyle='--')
                ax1.add_patch(rect)
                
                # Подпись LuxAlgo только у первого активного блока
                if i == 0 and not block['mitigated']:
                    ax1.text(start_x + 2, block['high'] * 1.02, 'LuxAlgo', 
                            color=edgecolor, fontsize=8, fontweight='bold',
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
                
                # Вертикальная черта в начале
                ax1.axvline(x=start_x, color=edgecolor, 
                           linewidth=1, linestyle=':', alpha=0.5)
            
            # Медвежьи блоки LuxAlgo
            for i, block in enumerate(blocks_luxalgo['bear']):
                if block['mitigated']:
                    edgecolor = 'gray'
                    alpha = 0.1
                else:
                    edgecolor = 'orange'
                    alpha = 0.3
                
                start_x = block['start_idx'] - 0.5
                rect = Rectangle((start_x, block['low']), 
                               last_idx - block['start_idx'] + 1,
                               block['high'] - block['low'],
                               facecolor='none', alpha=alpha, edgecolor=edgecolor, 
                               linewidth=2, linestyle='--')
                ax1.add_patch(rect)
                
                if i == 0 and not block['mitigated']:
                    ax1.text(start_x + 2, block['high'] * 1.02, 'LuxAlgo', 
                            color=edgecolor, fontsize=8, fontweight='bold',
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
                
                ax1.axvline(x=start_x, color=edgecolor, 
                           linewidth=1, linestyle=':', alpha=0.5)
        
        # =====================================================================
        # ТЕКУЩАЯ ЦЕНА И ЛЕГЕНДА
        # =====================================================================
        current_price = df['close'].iloc[-1]
        ax1.axhline(y=current_price, color='blue', linestyle='-', alpha=0.5, linewidth=1)
        ax1.text(len(df)-1, current_price, f'  {current_price:.1f}', 
                verticalalignment='bottom', color='blue', fontsize=10, fontweight='bold')
        
        # Легенда
        ax1.text(0.02, 0.92, '🟢 Наш метод (активный)', transform=ax1.transAxes, 
                fontsize=8, color='green', verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
        ax1.text(0.02, 0.88, '🔴 Наш метод (медвежий)', transform=ax1.transAxes, 
                fontsize=8, color='red', verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
        ax1.text(0.02, 0.84, '⚪ Митигирован', transform=ax1.transAxes, 
                fontsize=8, color='gray', verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
        ax1.text(0.02, 0.80, '🟡 LuxAlgo (пунктир)', transform=ax1.transAxes, 
                fontsize=8, color='orange', verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
        
        # Информация об активе
        asset_info = self.figi_loader.get_asset_info(ticker)
        title = f"{ticker} - {asset_info.get('name', ticker)}"
        ax1.set_title(title, fontsize=14, fontweight='bold')
        ax1.set_ylabel('Цена')
        ax1.grid(True, alpha=0.3)
        ax1.set_xticks(range(0, len(df), 5))
        ax1.set_xticklabels([idx.strftime('%d.%m') for idx in df.index[::5]], rotation=45)
        
        # 2. СТОХАСТИК
        ax2.plot(range(len(df)), df['Stoch_K'], color='blue', linewidth=1.5, label='%K')
        ax2.plot(range(len(df)), df['Stoch_D'], color='orange', linewidth=1.5, label='%D')
        
        ax2.axhline(y=20, color='green', linestyle='--', alpha=0.5, label='Oversold (20)')
        ax2.axhline(y=80, color='red', linestyle='--', alpha=0.5, label='Overbought (80)')
        
        current_stoch = df['Stoch_K'].iloc[-1] if not pd.isna(df['Stoch_K'].iloc[-1]) else 50
        ax2.axhline(y=current_stoch, color='purple', linestyle='-', alpha=0.3)
        ax2.text(len(df)-1, current_stoch, f'  {current_stoch:.1f}', 
                verticalalignment='bottom', color='purple', fontsize=9)
        
        ax2.fill_between(range(len(df)), 0, 20, color='green', alpha=0.1)
        ax2.fill_between(range(len(df)), 80, 100, color='red', alpha=0.1)
        
        ax2.set_ylabel('Стохастик')
        ax2.set_ylim(0, 100)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper left')
        ax2.set_xticks(range(0, len(df), 5))
        ax2.set_xticklabels([idx.strftime('%d.%m') for idx in df.index[::5]], rotation=45)
        
        # 3. ОБЪЕМ
        colors = ['green' if row['close'] >= row['open'] else 'red' for _, row in df.iterrows()]
        ax3.bar(range(len(df)), df['volume'], color=colors, alpha=0.6)
        ax3.set_ylabel('Объем')
        ax3.grid(True, alpha=0.3)
        ax3.set_xticks(range(0, len(df), 5))
        ax3.set_xticklabels([idx.strftime('%d.%m') for idx in df.index[::5]], rotation=45)
        
        # Информация о сигнале
        if signal_info or quality_score:
            title_text = ""
            if signal_info:
                title_text += f"{signal_info}"
            if quality_score:
                title_text += f" | Качество: {quality_score}/100"
            fig.suptitle(title_text, fontsize=12, 
                        color='red' if 'SHORT' in signal_info else 'green')
        
        plt.tight_layout()
        
        # Сохраняем в папку charts
        filename = os.path.join(CHARTS_DIR, f'chart_{ticker}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"💾 График сохранен: {filename}")
        plt.show()
    
    def scan_ticker(self, ticker):
        """
        Сканирует один тикер - РАБОЧАЯ ВЕРСИЯ С СИГНАЛАМИ
        """
        try:
            # Получаем FIGI для тикера
            figi = self.figi_loader.get_figi(ticker)
            if not figi:
                print(f"  ⚠️ {ticker}: Нет FIGI")
                return None
            
            print(f"  🔑 FIGI: {figi}")
            
            # Получаем исторические данные через Tinkoff
            df = self.tinkoff.get_historical_candles(figi, days=90)
            if df is None or len(df) < 20:
                print(f"  ⚠️ {ticker}: Недостаточно данных")
                return None
            
            # Рассчитываем стохастик
            df = self.calculate_stochastic(df)
            
            # Находим ордер блоки обоими методами
            blocks_our = self.find_order_blocks_our_method(df)
            blocks_luxalgo = self.find_order_blocks_luxalgo(df)
            
            # Объединяем блоки для хранения
            df.attrs['blocks_our'] = blocks_our
            df.attrs['blocks_luxalgo'] = blocks_luxalgo
            
            # ===== ИСПРАВЛЕННЫЙ ОТЛАДОЧНЫЙ КОД =====
            # Для отладки MVID - показываем детальную информацию о блоках LuxAlgo
            if ticker == 'MVID':
                print(f"\n🔍 ОТЛАДКА MVID (БЛОКИ LUXALGO):")
                print(f"   Всего бычьих блоков: {len(blocks_luxalgo['bull'])}")
                print(f"   Всего медвежьих блоков: {len(blocks_luxalgo['bear'])}")
                
                # Показываем ВСЕ доступные ключи в первом блоке для понимания структуры
                if blocks_luxalgo['bull']:
                    print(f"\n   📊 СТРУКТУРА ПЕРВОГО БЛОКА:")
                    first_block = blocks_luxalgo['bull'][0]
                    for key, value in first_block.items():
                        print(f"     - {key}: {value}")
                
                if blocks_luxalgo['bull']:
                    print(f"\n   📊 БЫЧЬИ БЛОКИ:")
                    for i, block in enumerate(blocks_luxalgo['bull']):
                        print(f"   Блок {i+1}:")
                        # Безопасно получаем значения
                        idx = block.get('index', block.get('start_idx', 'N/A'))
                        low = block.get('low', block.get('bottom', 'N/A'))
                        high = block.get('high', block.get('top', 'N/A'))
                        age = block.get('age', block.get('days', 'N/A'))
                        mitigated = block.get('mitigated', False)
                        
                        print(f"     - Индекс: {idx}")
                        print(f"     - Диапазон: {low} - {high}")
                        print(f"     - Возраст: {age} дней")
                        print(f"     - Митигирован: {mitigated}")
                
                if blocks_luxalgo['bear']:
                    print(f"\n   📉 МЕДВЕЖЬИ БЛОКИ:")
                    for i, block in enumerate(blocks_luxalgo['bear']):
                        print(f"   Блок {i+1}:")
                        idx = block.get('index', block.get('start_idx', 'N/A'))
                        low = block.get('low', block.get('bottom', 'N/A'))
                        high = block.get('high', block.get('top', 'N/A'))
                        age = block.get('age', block.get('days', 'N/A'))
                        mitigated = block.get('mitigated', False)
                        
                        print(f"     - Индекс: {idx}")
                        print(f"     - Диапазон: {low} - {high}")
                        print(f"     - Возраст: {age} дней")
                        print(f"     - Митигирован: {mitigated}")
                
                # Сравниваем с нашим методом
                print(f"\n   📊 НАШ МЕТОД:")
                print(f"   Бычьих блоков: {len(blocks_our['bull'])}")
                print(f"   Медвежьих блоков: {len(blocks_our['bear'])}")
                
                if blocks_our['bull']:
                    first = blocks_our['bull'][0]
                    print(f"   Первый бычий блок: {first.get('low', 'N/A')} - {first.get('high', 'N/A')}")
            # ===== КОНЕЦ ОТЛАДОЧНОГО КОДА =====

            # Получаем текущие значения
            current_price = df['close'].iloc[-1]
            current_stoch = df['Stoch_K'].iloc[-1] if not pd.isna(df['Stoch_K'].iloc[-1]) else 50
            
            # Проверяем положение цены относительно блоков
            price_to_blocks = self.check_price_to_blocks(current_price, blocks_our, blocks_luxalgo)
            df.attrs['price_to_blocks'] = price_to_blocks
            
            # Сохраняем данные для визуализации
            self.all_data[ticker] = df
            
            print(f"  📊 Цена: {current_price:.2f}, Stoch: {current_stoch:.1f}")
            print(f"    Наш метод: бычьих {len(blocks_our['bull'])}, медвежьих {len(blocks_our['bear'])}")
            print(f"    LuxAlgo: бычьих {len(blocks_luxalgo['bull'])}, медвежьих {len(blocks_luxalgo['bear'])}")
            
            # ========== ОСНОВНАЯ ПРОВЕРКА ПАТТЕРНА ==========
            signal = self.check_pattern(
                ticker, current_price, current_stoch, price_to_blocks
            )
            
                        # Если есть сигнал - добавляем информацию
            if signal:
                print(f"    ✅ СИГНАЛ: {signal['Сигнал']}")
                
                # Добавляем качество сигнала
                quality_score, quality_details = self.calculate_signal_quality(
                    df, 
                    'LONG' if 'LONG' in signal['Сигнал'] else 'SHORT',
                    blocks_our, 
                    blocks_luxalgo, 
                    price_to_blocks
                )
                signal['Качество'] = quality_score
                signal['Детали'] = ' | '.join(quality_details)
                
                # Добавляем рыночный контекст
                if hasattr(self, 'market_analysis') and self.market_analysis:
                    adjusted_signal = self.market_context.adjust_signal_for_market(
                        signal, self.market_analysis
                    )
                    signal['Качество'] = adjusted_signal['Качество']
                    signal['market_note'] = adjusted_signal.get('market_note', '')
                
                # ГРУППИРОВКА - определяем группу по вчерашним данным
                group_info = self.signal_grouper.classify_signal(
                    signal, df, self.market_analysis
                )
                signal['group'] = group_info['group']
                signal['closed_score'] = group_info['closed_score']
                signal['group_reason'] = group_info['group_reason']
                
                return signal
            
            return None
            
        except Exception as e:
            print(f"  ❌ {ticker}: Ошибка - {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def check_pattern(self, ticker, price, stoch, price_to_blocks):
        """
        Проверка паттернов с учетом блоков - РАБОЧАЯ ВЕРСИЯ
        """
        # ЛОНГ
        if stoch < self.stoch_oversold:
            if price_to_blocks['combined']['near_bull']:
                methods = []
                if price_to_blocks['our_method']['near_bull']:
                    methods.append('наш')
                if price_to_blocks['luxalgo']['near_bull']:
                    methods.append('LuxAlgo')
                
                return {
                    'Тикер': ticker,
                    'Сигнал': '🟢 LONG СИГНАЛ',
                    'Цена': round(price, 2),
                    'Stoch': round(stoch, 1),
                    'Тип': 'БЛОК + ПЕРЕПРОДАННОСТЬ',
                    'Методы': '+'.join(methods),
                    'Причина': f'Stoch {stoch:.1f} < {self.stoch_oversold}, блоки: {", ".join(methods)}'
                }
            else:
                return {
                    'Тикер': ticker,
                    'Сигнал': '🟡 LONG (нет блока)',
                    'Цена': round(price, 2),
                    'Stoch': round(stoch, 1),
                    'Тип': 'ТОЛЬКО ПЕРЕПРОДАННОСТЬ',
                    'Методы': 'нет',
                    'Причина': f'Stoch {stoch:.1f} < {self.stoch_oversold}, но нет блоков'
                }
        
        # ШОРТ
        elif stoch > self.stoch_overbought:
            if price_to_blocks['combined']['near_bear']:
                methods = []
                if price_to_blocks['our_method']['near_bear']:
                    methods.append('наш')
                if price_to_blocks['luxalgo']['near_bear']:
                    methods.append('LuxAlgo')
                
                return {
                    'Тикер': ticker,
                    'Сигнал': '🔴 SHORT СИГНАЛ',
                    'Цена': round(price, 2),
                    'Stoch': round(stoch, 1),
                    'Тип': 'БЛОК + ПЕРЕКУПЛЕННОСТЬ',
                    'Методы': '+'.join(methods),
                    'Причина': f'Stoch {stoch:.1f} > {self.stoch_overbought}, блоки: {", ".join(methods)}'
                }
            else:
                return {
                    'Тикер': ticker,
                    'Сигнал': '🟡 SHORT (нет блока)',
                    'Цена': round(price, 2),
                    'Stoch': round(stoch, 1),
                    'Тип': 'ТОЛЬКО ПЕРЕКУПЛЕННОСТЬ',
                    'Методы': 'нет',
                    'Причина': f'Stoch {stoch:.1f} > {self.stoch_overbought}, но нет блоков'
                }
        
        return None
    
    def check_entry_confirmation(self, ticker, signal_type):
        """
        Проверяет подтверждение для входа в сделку на основе ТОЛЬКО закрытых свечей
        """
        if ticker not in self.all_data:
            return 0, [], "❌ НЕТ ДАННЫХ", "нет данных для анализа"
        
        df = self.all_data[ticker]
        confirmer = EntryConfirmation()
        
        # Используем ТОЛЬКО закрытые свечи для принятия решения
        score, details, requires_today = confirmer.analyze_candle(df, signal_type, use_closed_only=True)
        
        if score >= 70:
            recommendation = "🚀 СРОЧНЫЙ ВХОД"
            reason = "экстремально сильное подтверждение по вчерашним данным"
        elif score >= 50:
            recommendation = "✅ МОЖНО ВХОДИТЬ"
            reason = "хорошее подтверждение по вчерашним данным"
        elif score >= 30:
            recommendation = "⏳ ЖДАТЬ"
            reason = "слабое подтверждение, ждем сегодня"
        else:
            recommendation = "❌ НЕ ВХОДИТЬ"
            reason = "недостаточно данных"
        
        if requires_today and score < 50:
            reason += " (нужно подтверждение сегодняшней свечой)"
        
        return score, details, recommendation, reason
    
    def scan_all(self):
        """
        Сканирует все тикеры
        """
        print("\n" + "=" * 100)
        print("🚀 СКАНЕР ОРДЕР БЛОКОВ (НАШ МЕТОД + LUXALGO)")
        print("=" * 100)
        print(f"📊 Всего тикеров: {len(self.tickers)}")
        print(f"⏰ Время запуска: {datetime.now().strftime('%H:%M:%S')}")
        print(f"⚙️ Stoch LONG < {self.stoch_oversold}, SHORT > {self.stoch_overbought}")
        print(f"📊 Наш метод: консолидация < {self.consolidation_range_percent}%, импульс > {self.impulse_min_percent}%")
        print(f"📊 LuxAlgo: length=5, mitigation=Wick")
        print(f"📊 Порог качества: {self.quality_threshold}")
        print("-" * 100)
        
        signals_found = []
        
        for i, ticker in enumerate(self.tickers, 1):
            print(f"\n[{i}/{len(self.tickers)}] 🔍 Сканирую {ticker}...")
            signal = self.scan_ticker(ticker)
            if signal:
                signals_found.append(signal)
                self.print_signal(signal)
        
        self.signals = signals_found
        self.save_results()

        # ===== ДОБАВИТЬ ЭТО =====
        # EOD анализ
        eod = EndOfDayAnalyzer()
        if eod.should_take_snapshot():
            eod.process_end_of_day(self)
        # ===== КОНЕЦ ДОБАВЛЕНИЯ =====
        
        self.print_final_recommendations()
        
        return signals_found
    
    def print_signal(self, signal):
        """
        Вывод сигнала с качеством - УПРОЩЕННАЯ ВЕРСИЯ
        """
        emoji = signal.get('Сигнал', '📊')
        methods = signal.get('Методы', '')
        quality = signal.get('Качество', 50)
        
        # ВРЕМЕННО убираем confirmation_score
        print(f"  {emoji} {signal['Тикер']} | "
              f"Цена: {signal['Цена']} | "
              f"Stoch: {signal['Stoch']} | "
              f"Кач-во: {quality} | "
              f"Методы: {methods}")
        if signal.get('Детали'):
            print(f"      📈 {signal['Детали']}")
    
    def save_results(self):
        """
        Сохраняет результаты - УПРОЩЕННАЯ ВЕРСИЯ
        """
        if hasattr(self, 'market_analysis') and self.market_analysis:
            print("\n" + "=" * 100)
            print("🌍 РЫНОЧНЫЙ КОНТЕКСТ")
            print("=" * 100)
            print(f"📊 Индекс Мосбиржи: {self.market_analysis['imoex_price']:.0f}")
            print(f"📈 Тренд: {self.market_analysis['trend']}")
            print(f"🔄 Состояние: {self.market_analysis['market_state']}")
            print(f"📉 RSI индекса: {self.market_analysis['rsi']:.1f}")
            print(f"📊 Объем: {'выше' if self.market_analysis['volume_ratio'] > 1 else 'ниже'} среднего")
        
        if not self.signals:
            print("\n" + "=" * 100)
            print("📊 РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ")
            print("=" * 100)
            print("\n❌ Сигналов не найдено")
            print(f"📈 Проверено тикеров: {len(self.tickers)}")
            return
        
        # Упрощенная версия без confirmation_score
        enhanced_signals = []
        for signal in self.signals:
            signal_copy = signal.copy()
            signal_copy['confirmation_score'] = 0  # заглушка
            enhanced_signals.append(signal_copy)
        
        df = pd.DataFrame(enhanced_signals)
        
        # Сохраняем в папку signals
        filename = os.path.join(SIGNALS_DIR, f'signals_{datetime.now().strftime("%Y%m%d_%H%M")}.csv')
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        
        print("\n" + "=" * 100)
        print("📊 ИТОГОВЫЕ РЕЗУЛЬТАТЫ")
        print("=" * 100)
        print(f"✅ Всего сигналов: {len(df)}")
        
        # Простая статистика
        long_count = len([s for s in self.signals if 'LONG' in s['Сигнал']])
        short_count = len([s for s in self.signals if 'SHORT' in s['Сигнал']])
        
        print(f"🟢 LONG сигналы: {long_count}")
        print(f"🔴 SHORT сигналы: {short_count}")
        
        print("\n📋 СПИСОК СИГНАЛОВ:")
        for s in self.signals:
            quality = s.get('Качество', 50)
            print(f"  {s['Сигнал']} {s['Тикер']} | Цена: {s['Цена']} | Stoch: {s['Stoch']} | Кач-во: {quality}")
        
        print(f"\n💾 Результаты сохранены в {filename}")
    
    def print_final_recommendations(self):
        """
        Красивый структурированный вывод финальных лидеров по группам
        """
        if not self.signals:
            return
        
        print("\n" + "="*90)
        print("🎯 ФИНАЛЬНЫЙ ТОРГОВЫЙ ПЛАН")
        print("="*90)
        print("📌 Данные ЗАФИКСИРОВАНЫ на ВЧЕРАШНЕЕ закрытие!")
        
        # Группируем сигналы
        group_a = [s for s in self.signals if s.get('group') == 'A']
        group_b = [s for s in self.signals if s.get('group') == 'B']
        group_c = [s for s in self.signals if s.get('group') == 'C']
        
        # ГРУППА А - МОЖНО ВХОДИТЬ
        if group_a:
            print(f"\n{'✅'*20}")
            print(f"✅✅ ГРУППА А - МОЖНО ВХОДИТЬ (по вчерашним данным)")
            print(f"{'✅'*20}")
            
            for s in group_a[:5]:  # Топ-5
                signal_type = '🟢' if 'LONG' in s['Сигнал'] else '🔴'
                block = "С БЛОКОМ" if "СИГНАЛ" in s['Сигнал'] else "БЕЗ БЛОКА"
                print(f"\n{signal_type} {s['Тикер']} | Цена: {s['Цена']} | Stoch: {s['Stoch']} | {block}")
                if s.get('closed_score'):
                    print(f"   └── Подтверждение: {s['closed_score']} баллов")
        
        # ГРУППА Б - ЖДЕМ ЗАКРЫТИЯ
        if group_b:
            print(f"\n{'⏳'*20}")
            print(f"⏳⏳ ГРУППА Б - ЖДЕМ ЗАКРЫТИЯ СЕГОДНЯ")
            print(f"{'⏳'*20}")
            
            for s in group_b[:5]:
                signal_type = '🟢' if 'LONG' in s['Сигнал'] else '🔴'
                print(f"\n{signal_type} {s['Тикер']} | Цена: {s['Цена']} | Stoch: {s['Stoch']}")
                if s.get('closed_score'):
                    print(f"   └── Уже есть: {s['closed_score']} баллов, ждем сегодня")
        
        # ГРУППА В - НАБЛЮДЕНИЕ
        if group_c:
            print(f"\n{'👀'*20}")
            print(f"👀👀 ГРУППА В - НАБЛЮДЕНИЕ")
            print(f"{'👀'*20}")
            
            for s in group_c[:3]:
                signal_type = '🟢' if 'LONG' in s['Сигнал'] else '🔴'
                print(f"\n{signal_type} {s['Тикер']} | Stoch: {s['Stoch']}")
        
        # Распределение капитала
        self.print_capital_allocation(group_a, group_b)
    
    
    def print_timing_for_ticker(self, ticker, signal_type, is_favorite=True):
        """
        Вывод точного тайминга для тикера
        """
        if ticker not in self.all_data:
            return
        
        df = self.all_data[ticker]
        current_price = df['close'].iloc[-1]
        
        print(f"\n   ⏰ ТОРГОВЫЙ ПЛАН:")
        
        if 'SHORT' in signal_type:
            stop = current_price * 1.02
            tp1 = current_price * 0.98
            tp2 = current_price * 0.96
            tp3 = current_price * 0.92
        else:
            stop = current_price * 0.98
            tp1 = current_price * 1.02
            tp2 = current_price * 1.04
            tp3 = current_price * 1.08
        
        print(f"      Размер: {'1.5%' if is_favorite else '1.0%'} от капитала")
        print(f"      Вход: {current_price:.2f}")
        print(f"      Стоп-лосс: {stop:.2f} ({'+' if 'SHORT' in signal_type else '-'}{abs(stop-current_price)/current_price*100:.1f}%)")
        print(f"      Тейк-профит 1: {tp1:.2f} ({'-' if 'SHORT' in signal_type else '+'}2.0%) - закрыть 30%")
        print(f"      Тейк-профит 2: {tp2:.2f} ({'-' if 'SHORT' in signal_type else '+'}4.0%) - закрыть 30%")
        print(f"      Тейк-профит 3: {tp3:.2f} ({'-' if 'SHORT' in signal_type else '+'}8.0%) - трейлинг-стоп")
    
    def print_waiting_conditions(self, ticker, signal_type):
        """
        Вывод условий для входа
        """
        if ticker not in self.all_data:
            return
        
        df = self.all_data[ticker]
        current_price = df['close'].iloc[-1]
        
        print(f"\n   ⏳ УСЛОВИЯ ДЛЯ ВХОДА:")
        print(f"      Текущая цена: {current_price:.2f}")
        print(f"      Ждем подтверждения на закрытии сегодня")
    
    def print_capital_allocation(self, group_a, group_b):
        """
        Вывод распределения капитала
        """
        print(f"\n{'='*90}")
        print("📊 РАСПРЕДЕЛЕНИЕ КАПИТАЛА")
        print(f"{'='*90}")
        
        # Берем только сигналы с блоками из группы А
        ready = [s for s in group_a if "СИГНАЛ" in s['Сигнал']][:3]
        
        if ready:
            print("\n✅ АКТИВНЫЕ ПОЗИЦИИ (ГРУППА А):")
            total_risk = 0
            for s in ready:
                risk = 1.5 if s.get('closed_score', 0) >= 70 else 1.0
                total_risk += risk
                print(f"   {s['Тикер']}: {risk}% ({s['Сигнал']})")
            
            print(f"\n   Всего под риском: {total_risk}%")
            print(f"   КЭШ: {100 - total_risk}%")
        else:
            print("\n⏳ НЕТ АКТИВНЫХ ПОЗИЦИЙ В ГРУППЕ А")
            print("   КЭШ: 100% (ждем сигналов группы А)")
        
        if group_b:
            print(f"\n⏳ В ОЖИДАНИИ (ГРУППА Б, {len(group_b)}):")
            for s in group_b[:3]:
                print(f"   {s['Тикер']} (ждем закрытия сегодня)")
        
        print(f"\n⚠️ КЛЮЧЕВЫЕ МОМЕНТЫ:")
        print("   - Группа А: решение по ВЧЕРАШНИМ данным - можно входить СЕГОДНЯ")
        print("   - Группа Б: ждем закрытия СЕГОДНЯШНЕЙ свечи")
        print("   - Группа В: недостаточно данных, наблюдаем")
        print("   - Стопы ставим жестко, без вариантов")
    
    def show_visualization(self, tickers_to_show=None):
        """
        Показывает графики для указанных тикеров
        """
        if not self.all_data:
            print("\n❌ Нет данных для визуализации")
            return
        
        print("\n" + "=" * 100)
        print("📈 ВИЗУАЛИЗАЦИЯ ГРАФИКОВ (НАШ МЕТОД + LUXALGO)")
        print("=" * 100)
        
        if tickers_to_show is None:
            if self.signals:
                sorted_signals = sorted(self.signals, key=lambda x: (x.get('group', 'C'), -x.get('Качество', 0)))
                tickers_to_show = [s['Тикер'] for s in sorted_signals][:5]
            else:
                tickers_to_show = list(self.all_data.keys())[:2]
            print(f"📊 Показываем {len(tickers_to_show)} графиков")
        
        for ticker in tickers_to_show:
            if ticker not in self.all_data:
                print(f"⚠️ Нет данных для {ticker}")
                continue
                
            print(f"\n📊 Строим график для {ticker}...")
            
            signal_info = None
            quality_score = None
            quality_details = None
            
            for s in self.signals:
                if s['Тикер'] == ticker:
                    signal_info = f"{s['Сигнал']} | {s.get('Причина', '')}"
                    quality_score = s.get('Качество')
                    quality_details = s.get('Детали')
                    break
            
            df = self.all_data[ticker]
            self.plot_chart(
                df, ticker, signal_info, quality_score, quality_details,
                blocks_our=df.attrs.get('blocks_our'),
                blocks_luxalgo=df.attrs.get('blocks_luxalgo')
            )

#==============================================================================
# ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ СТРАТЕГИЙ
#==============================================================================

class ProfessionalTradingSystem:
    def __init__(self, signals, capital=1_000_000):
        self.signals = signals
        self.capital = capital
        self.longs = [s for s in signals if 'LONG' in s['Сигнал']]
        self.shorts = [s for s in signals if 'SHORT' in s['Сигнал']]
        
    def analyze(self):
        """
        Полный анализ и рекомендации
        """
        results = {}
        results['pairs'] = self.find_best_pairs()
        results['market_neutral'] = self.create_market_neutral_portfolio()
        results['quality_analysis'] = self.analyze_quality()
        results['risk'] = self.calculate_risk_metrics()
        results['recommendation'] = self.generate_recommendation()
        return results
    
    def find_best_pairs(self):
        """
        Поиск лучших пар для парного трейдинга
        """
        pairs = []
        
        sectors = {
            'Нефть и газ': ['GAZP', 'LKOH', 'ROSN', 'TATN', 'SNGS', 'NVTK'],
            'Металлы': ['CHMF', 'GMKN', 'PLZL', 'RUAL', 'ALRS', 'VSMO'],
            'Финансы': ['SBER', 'VTBR', 'CBOM', 'BSPB', 'SBERP'],
            'Потребление': ['MGNT', 'FIVE', 'LENT', 'MVID', 'BELU', 'SOFL'],
        }
        
        for sector, tickers in sectors.items():
            sector_longs = [s for s in self.longs if s['Тикер'] in tickers]
            sector_shorts = [s for s in self.shorts if s['Тикер'] in tickers]
            
            for long in sector_longs[:2]:
                for short in sector_shorts[:2]:
                    price_ratio = long['Цена'] / short['Цена'] if short['Цена'] > 0 else 1
                    
                    pairs.append({
                        'сектор': sector,
                        'покупка': long['Тикер'],
                        'продажа': short['Тикер'],
                        'цена_покупки': long['Цена'],
                        'цена_продажи': short['Цена'],
                        'качество_покупки': long.get('Качество', 0),
                        'качество_продажи': short.get('Качество', 0),
                        'качество_пары': (long.get('Качество', 0) + short.get('Качество', 0)) / 2,
                        'соотношение': f"1 : {price_ratio:.2f}"
                    })
        
        return sorted(pairs, key=lambda x: x['качество_пары'], reverse=True)
    
    def create_market_neutral_portfolio(self):
        """
        Создание рыночно-нейтрального портфеля
        """
        if not self.longs or not self.shorts:
            return None
        
        top_longs = sorted(self.longs, key=lambda x: x.get('Качество', 0), reverse=True)[:3]
        top_shorts = sorted(self.shorts, key=lambda x: x.get('Качество', 0), reverse=True)[:3]
        
        portfolio = {
            'long_positions': [],
            'short_positions': [],
            'total_capital': self.capital,
            'capital_per_leg': self.capital * 0.5,
        }
        
        for signal in top_longs:
            position_size = int((self.capital * 0.5) / len(top_longs) / signal['Цена'])
            portfolio['long_positions'].append({
                'ticker': signal['Тикер'],
                'price': signal['Цена'],
                'size': position_size,
                'capital': position_size * signal['Цена'],
                'quality': signal.get('Качество', 0)
            })
        
        for signal in top_shorts:
            position_size = int((self.capital * 0.5) / len(top_shorts) / signal['Цена'])
            portfolio['short_positions'].append({
                'ticker': signal['Тикер'],
                'price': signal['Цена'],
                'size': position_size,
                'capital': position_size * signal['Цена'],
                'quality': signal.get('Качество', 0)
            })
        
        return portfolio
    
    def analyze_quality(self):
        """
        Анализ качества сигналов
        """
        return {
            'total_signals': len(self.signals),
            'long_signals': len(self.longs),
            'short_signals': len(self.shorts),
            'avg_long_quality': np.mean([s.get('Качество', 0) for s in self.longs]) if self.longs else 0,
            'avg_short_quality': np.mean([s.get('Качество', 0) for s in self.shorts]) if self.shorts else 0,
            'best_long': max(self.longs, key=lambda x: x.get('Качество', 0)) if self.longs else None,
            'best_short': max(self.shorts, key=lambda x: x.get('Качество', 0)) if self.shorts else None,
        }
    
    def calculate_risk_metrics(self):
        """
        Расчет рисков
        """
        long_risk = sum(1 - s.get('Качество', 0)/100 for s in self.longs) / len(self.longs) if self.longs else 0
        short_risk = sum(1 - s.get('Качество', 0)/100 for s in self.shorts) / len(self.shorts) if self.shorts else 0
        
        return {
            'long_portfolio_risk': f"{long_risk*100:.1f}%",
            'short_portfolio_risk': f"{short_risk*100:.1f}%",
            'correlation_risk': 'Низкий' if self.longs and self.shorts else 'Высокий',
            'recommended_leverage': '1x',
            'stop_loss_level': '5-7% от входа'
        }
    
    def generate_recommendation(self):
        """
        Итоговая рекомендация
        """
        if len(self.longs) >= 2 and len(self.shorts) >= 2:
            return {
                'стратегия': 'ПАРНЫЙ ТРЕЙДИНГ',
                'обоснование': 'Достаточно сигналов в обе стороны',
                'действия': 'Открыть 2-3 пары с лучшим качеством',
                'ожидаемая_доходность': '12-15% годовых',
                'максимальная_просадка': '5-7%'
            }
        elif len(self.longs) >= 3:
            return {
                'стратегия': 'LONG ONLY С ХЕДЖЕМ',
                'обоснование': 'Преобладают LONG сигналы',
                'действия': 'Купить топ-3 LONG, продать фьючерс на индекс',
                'ожидаемая_доходность': '10-12% годовых',
                'максимальная_просадка': '8-10%'
            }
        elif len(self.shorts) >= 3:
            return {
                'стратегия': 'SHORT ONLY С ХЕДЖЕМ',
                'обоснование': 'Преобладают SHORT сигналы',
                'действия': 'Продать топ-3 SHORT, купить фьючерс на индекс',
                'ожидаемая_доходность': '10-12% годовых',
                'максимальная_просадка': '8-10%'
            }
        else:
            return {
                'стратегия': 'НАБЛЮДЕНИЕ',
                'обоснование': 'Недостаточно качественных сигналов',
                'действия': 'Дождаться большего количества сигналов',
                'ожидаемая_доходность': '0% (кеш)',
                'максимальная_просадка': '0%'
            }
    
    def print_recommendations(self):
        """
        Вывод рекомендаций
        """
        results = self.analyze()
        
        print("\n" + "="*80)
        print("📊 ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ РЫНКА")
        print("="*80)
        
        q = results['quality_analysis']
        print(f"\n📈 Качество сигналов:")
        print(f"   Всего: {q['total_signals']} (LONG: {q['long_signals']}, SHORT: {q['short_signals']})")
        print(f"   Среднее качество LONG: {q['avg_long_quality']:.1f}")
        print(f"   Среднее качество SHORT: {q['avg_short_quality']:.1f}")
        
        if q['best_long']:
            print(f"   Лучший LONG: {q['best_long']['Тикер']} (кач-во: {q['best_long'].get('Качество', 0)})")
        if q['best_short']:
            print(f"   Лучший SHORT: {q['best_short']['Тикер']} (кач-во: {q['best_short'].get('Качество', 0)})")
        
        pairs = results['pairs']
        if pairs:
            print(f"\n🤝 Лучшие пары для парного трейдинга:")
            for i, pair in enumerate(pairs[:3], 1):
                print(f"   {i}. {pair['покупка']} → {pair['продажа']} | "
                      f"Качество: {pair['качество_пары']:.0f} | {pair['сектор']}")
        
        if results['market_neutral']:
            mn = results['market_neutral']
            print(f"\n📊 Рыночно-нейтральный портфель:")
            print(f"   Капитал: {mn['total_capital']:,.0f} ₽")
            print(f"   LONG позиции ({len(mn['long_positions'])}):")
            for pos in mn['long_positions']:
                print(f"     • {pos['ticker']}: {pos['size']} шт @ {pos['price']} ₽ (кач-во: {pos['quality']})")
            print(f"   SHORT позиции ({len(mn['short_positions'])}):")
            for pos in mn['short_positions']:
                print(f"     • {pos['ticker']}: {pos['size']} шт @ {pos['price']} ₽ (кач-во: {pos['quality']})")
        
        r = results['risk']
        print(f"\n⚠️ Риск-метрики:")
        print(f"   Риск LONG портфеля: {r['long_portfolio_risk']}")
        print(f"   Риск SHORT портфеля: {r['short_portfolio_risk']}")
        print(f"   Корреляционный риск: {r['correlation_risk']}")
        
        rec = results['recommendation']
        print(f"\n🎯 ИТОГОВАЯ РЕКОМЕНДАЦИЯ:")
        print(f"   {rec['стратегия']}")
        print(f"   {rec['обоснование']}")
        print(f"   {rec['действия']}")
        print(f"   Ожидаемая доходность: {rec['ожидаемая_доходность']}")
        print(f"   Максимальная просадка: {rec['максимальная_просадка']}")
        
        print("\n" + "="*80)

#==============================================================================
# ЗАПУСК
#==============================================================================

if __name__ == "__main__":
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("""# Tinkoff API Token
TINKOFF_TOKEN=your_tinkoff_token_here
""")
        print("📝 Создан файл .env. Добавьте в него свой Tinkoff API токен.")
        sys.exit(1)
    
    scanner = OrderBlockScanner(
        tickers_to_scan=None,
        max_tickers=100
    )
    
    scanner.scan_all()
    
    if scanner.signals:
        # Берем ТОЛЬКО сигналы из группы А
        group_a = [s for s in scanner.signals if s.get('group') == 'A']
    
        if group_a:
            # ВАЖНО: берем ПЕРВЫЕ 5 ТАК, КАК ОНИ УЖЕ ОТСОРТИРОВАНЫ
            signal_tickers = [s['Тикер'] for s in group_a[:5]]
            print(f"\n📊 Показываем графики для топ-5 группы А: {signal_tickers}")
            scanner.show_visualization(signal_tickers)
        else:
            print("\n📊 Нет сигналов в группе А для визуализации")
        
        print("\n" + "="*80)
        print("🚀 ЗАПУСК ПРОФЕССИОНАЛЬНОГО АНАЛИЗА")
        print("="*80)
        
        pro_system = ProfessionalTradingSystem(scanner.signals, capital=1_000_000)
        pro_system.print_recommendations()
        
        # ===== ДЕМО-ТРЕКЕР С УЛУЧШЕННОЙ ОБРАБОТКОЙ ОШИБОК =====
        print("\n" + "="*80)
        print("🎯 ЗАПУСК ДЕМО-ТРЕКЕРА")
        print("="*80)
        print("Хотите добавить сигналы в демо-режим?")
        print("1. Да, добавить все сигналы группы А")
        print("2. Да, добавить все сигналы с качеством >=50")
        print("3. Да, добавить все сигналы с качеством >=60")
        print("4. Нет, только посмотреть")
        
        choice = input("Выберите (1/2/3/4): ")
        
        if choice in ['1', '2', '3']:
            try:
                # Пробуем импортировать разными способами
                try:
                    from position_tracker import DemoMode
                except ImportError:
                    # Если не находит, пробуем с полным путем
                    import sys
                    import os
                    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                    from position_tracker import DemoMode
                
                demo = DemoMode(scanner)
                
                if choice == '1':
                    # Только группа А (без доп. проверок)
                    added = 0
                    group_a = [s for s in scanner.signals if s.get('group') == 'A']
                    for signal in group_a:
                        demo.tracker.add_position(signal)
                        added += 1
                    print(f"\n✅ Добавлено {added} позиций из группы А")
                
                elif choice == '2':
                    min_quality = 50
                    added = demo.add_signals_as_positions(min_quality=min_quality, min_confirmation=30)
                    print(f"\n✅ Добавлено {added} позиций с качеством >=50")
                
                elif choice == '3':
                    min_quality = 60
                    added = demo.add_signals_as_positions(min_quality=min_quality, min_confirmation=30)
                    print(f"\n✅ Добавлено {added} позиций с качеством >=60")
                
                if added > 0:
                    print(f"\n✅ Добавлено {added} позиций в демо-трекер")
                    print(f"📁 Данные сохранены")
                else:
                    print("\n❌ Нет сигналов, удовлетворяющих условиям")
                    
            except ImportError as e:
                print(f"\n⚠️ Файл position_tracker.py не найден")
                print(f"   Ошибка: {e}")
                print(f"   Текущая папка: {os.getcwd()}")
            except AttributeError as e:
                print(f"\n⚠️ Ошибка в трекере: {e}")
                print("   Возможно, не все методы реализованы")
            except Exception as e:
                print(f"\n⚠️ Ошибка при добавлении в демо-трекер: {e}")
                import traceback
                traceback.print_exc()
    else:
        print("\n❌ Нет сигналов для визуализации")
    
    input("\nНажмите Enter для выхода...")
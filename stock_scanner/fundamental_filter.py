# fundamental_filter_dynamic.py
from fundamental_loader import FundamentalDataLoader
import pandas as pd
from datetime import datetime, timedelta
import numpy as np

class FundamentalFilterDynamic:
    """
    Фильтр с учетом динамики (абсолют + тренд + скорость)
    """
    def __init__(self):
        self.loader = FundamentalDataLoader()
        
        # Веса для разных аспектов оценки
        self.weights = {
            'absolute': 0.4,   # где мы сейчас
            'trend': 0.3,       # куда идем (неделя)
            'velocity': 0.2,    # как быстро (3 дня)
            'news': 0.1         # новостной фон
        }
        
        # Специализированные веса для секторов
        self.sector_weights = {
            # ========== СУЩЕСТВУЮЩИЕ ==========
            'oil_gas': {
                'brent': 0.35,
                'usdrub': 0.25,
                'geopolitics': 0.25,
                'global_demand': 0.15
            },
            'metals': {
                'copper': 0.25,
                'gold': 0.2,
                'usdrub': 0.2,
                'pmi_china': 0.2,
                'geopolitics': 0.15
            },
            'finance': {
                'cbr_rate': 0.35,
                'inflation': 0.3,
                'usdrub': 0.2,
                'geopolitics': 0.15
            },
            'consumer': {
                'inflation': 0.35,
                'cbr_rate': 0.3,
                'usdrub': 0.2,
                'geopolitics': 0.15
            },
            'tech': {
                'usdrub': 0.3,
                'sp500': 0.3,
                'geopolitics': 0.2,
                'global_demand': 0.2
            },
    
            # ========== НОВЫЕ СЕКТОРА ==========
            'energy': {           # Энергетика
                'brent': 0.40,    # Цена нефти
                'usdrub': 0.30,   # Курс рубля
                'geopolitics': 0.20,
                'global_demand': 0.10
            },
            'chemicals': {        # Химия и удобрения
                'brent': 0.30,    # Сырье
                'usdrub': 0.25,
                'global_demand': 0.25,  # Экспорт
                'geopolitics': 0.20
            },
            'developers': {       # Застройщики
                'cbr_rate': 0.45, # Ключевая ставка (главный фактор!)
                'inflation': 0.35,
                'usdrub': 0.20
            },
            'transport': {        # Транспорт
                'brent': 0.35,    # Топливо
                'usdrub': 0.30,
                'global_demand': 0.20,
                'geopolitics': 0.15
            },
            'telecom': {          # Телеком
                'usdrub': 0.35,
                'sp500': 0.35,    # Технологический сектор США
                'geopolitics': 0.30
            }
        }
    
    def get_absolute_score(self, indicator, source='auto'):
        """
        Оценка абсолютного значения (где мы сейчас)
        """
        df = self.loader.get_macro_data(indicator, source)
        if df is None or len(df) == 0:
            return 50
        
        last_value = df.iloc[-1]['value']
        
        # Исторические средние для разных индикаторов
        benchmarks = {
            'brent': {'low': 60, 'high': 100},      # нефть
            'usdrub': {'low': 70, 'high': 110},     # доллар
            'gold': {'low': 4000, 'high': 6000},    # золото
            'copper': {'low': 4, 'high': 8},        # медь
            'sp500': {'low': 500, 'high': 800}      # S&P 500
        }
        
        if indicator in benchmarks:
            b = benchmarks[indicator]
            if last_value <= b['low']:
                return 20
            elif last_value >= b['high']:
                return 80
            else:
                # Линейная интерполяция между low и high
                ratio = (last_value - b['low']) / (b['high'] - b['low'])
                return 20 + ratio * 60
        else:
            return 50
    
    def get_trend_score(self, indicator, source='auto', days=7):
        """
        Оценка тренда (куда идем за последние days дней)
        """
        df = self.loader.get_macro_data(indicator, source)
        if df is None or len(df) < 2:
            return 50
        
        # Берем данные за нужный период
        cutoff = datetime.now() - timedelta(days=days)
        recent = df[df['date'] >= cutoff]
        
        if len(recent) < 2:
            return 50
        
        first = recent.iloc[0]['value']
        last = recent.iloc[-1]['value']
        
        if first == 0:
            return 50
        
        change_pct = (last - first) / first * 100
        
        # Конвертируем процент изменения в оценку
        if change_pct > 10:
            return 90
        elif change_pct > 5:
            return 80
        elif change_pct > 2:
            return 70
        elif change_pct > 0:
            return 60
        elif change_pct > -2:
            return 40
        elif change_pct > -5:
            return 30
        elif change_pct > -10:
            return 20
        else:
            return 10
    
    def get_velocity_score(self, indicator, source='auto'):
        """
        Оценка скорости изменения (сравнение 3 дня vs 7 дней)
        """
        slow_trend = self.get_trend_score(indicator, source, 7)
        fast_trend = self.get_trend_score(indicator, source, 3)
        
        # Если быстрое движение сильнее медленного - это ускорение
        if fast_trend > slow_trend + 20:
            return min(100, fast_trend + 10)  # ускорение вверх
        elif fast_trend < slow_trend - 20:
            return max(0, fast_trend - 10)    # ускорение вниз
        else:
            return (slow_trend + fast_trend) / 2  # стабильно
    
    def get_geopolitics_score(self):
        """
        Оценка геополитики с учетом веса событий
        """
        geo = self.loader.get_macro_data('geopolitics', 'manual')
        if geo is None or len(geo) == 0:
            return {}
        
        sector_impact = {}
        
        for _, row in geo.iterrows():
            sectors = str(row['affected_sectors']).split(',')
            impact = row['impact']
            description = row.get('description', '')
            
            # Масштабируем влияние в зависимости от описания
            if 'Ормузский' in description or 'пролив' in description:
                impact *= 3
            elif 'СПГ' in description or 'завод' in description:
                impact *= 2
            elif 'санкции' in description.lower():
                impact *= 1.5
            
            for sector in sectors:
                sector = sector.strip()
                if sector not in sector_impact:
                    sector_impact[sector] = 0
                sector_impact[sector] += impact
        
        # Нормализуем
        for sector in sector_impact:
            sector_impact[sector] = max(-15, min(15, sector_impact[sector]))
        
        return sector_impact
    
    def get_composite_score(self, indicator, source='auto'):
        """
        Композитная оценка (абсолют + тренд + скорость)
        """
        abs_score = self.get_absolute_score(indicator, source)
        trend_score = self.get_trend_score(indicator, source, 7)
        vel_score = self.get_velocity_score(indicator, source)
        
        composite = (abs_score * self.weights['absolute'] + 
                    trend_score * self.weights['trend'] + 
                    vel_score * self.weights['velocity'])
        
        return round(composite)
    
    def get_sector_score(self, sector):
        """
        Полная оценка сектора с учетом динамики
        """
        if sector not in self.sector_weights:
            return 50
        
        weights = self.sector_weights[sector]
        score = 0
        total_weight = 0
        
        # Макро-факторы с динамикой
        macro_factors = {
            'brent': 'auto',
            'usdrub': 'auto',
            'copper': 'auto',
            'gold': 'auto',
            'sp500': 'auto'
        }
        
        for factor, source in macro_factors.items():
            if factor in weights:
                factor_score = self.get_composite_score(factor, source)
                score += factor_score * weights[factor]
                total_weight += weights[factor]
        
        # Ручные данные (пока без динамики)
        manual_factors = {
            'cbr_rate': self.get_cbr_score,
            'inflation': self.get_inflation_score,
            'pmi_china': self.get_pmi_score
        }
        
        for factor, func in manual_factors.items():
            if factor in weights:
                factor_score = func()
                score += factor_score * weights[factor]
                total_weight += weights[factor]
        
        # Геополитика
        if 'geopolitics' in weights:
            geo_impact = self.get_geopolitics_score()
            impact = geo_impact.get(sector, 0)
            # Конвертируем -15..15 в 0..100
            geo_score = 50 + impact * 2.5
            geo_score = max(0, min(100, geo_score))
            score += geo_score * weights['geopolitics']
            total_weight += weights['geopolitics']
        
        if total_weight > 0:
            final_score = score / total_weight
        else:
            final_score = 50
        
        return round(final_score)
    
    def get_cbr_score(self):
        """Оценка ставки ЦБ"""
        df = self.loader.get_macro_data('cbr_rate', 'manual')
        if df is None or len(df) == 0:
            return 50
        
        rate = df.iloc[-1]['rate']
        
        if rate > 20:
            return 90
        elif rate > 15:
            return 80
        elif rate > 10:
            return 60
        elif rate > 5:
            return 40
        else:
            return 20
    
    def get_inflation_score(self):
        """Оценка инфляции"""
        df = self.loader.get_macro_data('inflation', 'manual')
        if df is None or len(df) == 0:
            return 50
        
        cpi = df.iloc[-1]['cpi_yoy']
        
        if 4 <= cpi <= 5:
            return 80
        elif 5 < cpi <= 6:
            return 70
        elif 6 < cpi <= 8:
            return 50
        elif cpi > 8:
            return 30
        else:
            return 40
    
    def get_pmi_score(self):
        """Оценка PMI Китая"""
        df = self.loader.get_macro_data('pmi_china', 'manual')
        if df is None or len(df) == 0:
            return 50
        
        pmi = df.iloc[-1]['pmi']
        
        if pmi > 52:
            return 90
        elif pmi > 50:
            return 80
        elif pmi > 48:
            return 50
        else:
            return 30
    
    def get_sector_bias(self, sector):
        """
        Определение предпочтительного направления
        """
        score = self.get_sector_score(sector)
        
        if score >= 65:
            return 'LONG'
        elif score <= 40:
            return 'SHORT'
        else:
            return 'NEUTRAL'
    
    def print_detailed_sector_analysis(self):
        """
        Детальный вывод по секторам с расшифровкой
        """
        print("\n" + "="*70)
        print("📊 ДЕТАЛЬНЫЙ АНАЛИЗ СЕКТОРОВ (с динамикой)")
        print("="*70)
        
        sectors = ['oil_gas', 'metals', 'finance', 'consumer', 'tech']
        sector_names = {
            'oil_gas': 'Нефть и газ',
            'metals': 'Металлы',
            'finance': 'Финансы',
            'consumer': 'Потребление',
            'tech': 'Технологии'
        }
        
        for sector in sectors:
            score = self.get_sector_score(sector)
            bias = self.get_sector_bias(sector)
            
            # Эмодзи в зависимости от оценки
            if score >= 70:
                emoji = "🔥🔥"
            elif score >= 60:
                emoji = "🔥"
            elif score >= 50:
                emoji = "📊"
            elif score >= 40:
                emoji = "⚪"
            else:
                emoji = "❄️"
            
            print(f"\n{emoji} {sector_names[sector]}: {score} ({bias})")
            
            # Показываем ключевые факторы
            weights = self.sector_weights[sector]
            
            print(f"   📈 Ключевые факторы:")
            for factor in weights.keys():
                if factor in ['brent', 'usdrub', 'copper', 'gold', 'sp500']:
                    comp = self.get_composite_score(factor)
                    abs_s = self.get_absolute_score(factor)
                    trend = self.get_trend_score(factor, days=7)
                    vel = self.get_velocity_score(factor)
                    print(f"      {factor}: композит {comp} (абс:{abs_s}, тренд:{trend}, скор:{vel})")
            
            # Показываем геополитику
            geo = self.get_geopolitics_score()
            if sector in geo:
                print(f"      🌍 Геополитика: {geo[sector]:+d}")
    def analyze_signal(self, signal):
        """
        Анализирует конкретный сигнал с учетом фундамента
        Возвращает рекомендацию и скорректированное качество
        """
        ticker = signal['Тикер']
        signal_type = 'LONG' if 'LONG' in signal['Сигнал'] else 'SHORT'
        
        # Определяем сектор
        sector = self.get_sector_for_ticker(ticker)
        if not sector:
            return {
                'ticker': ticker,
                'signal': signal_type,
                'sector': 'unknown',
                'sector_score': 50,
                'sector_bias': 'NEUTRAL',
                'recommendation': '❓ Сектор не определен',
                'quality_adjustment': 0
            }
        
        # Получаем оценку сектора
        sector_score = self.get_sector_score(sector)
        sector_bias = self.get_sector_bias(sector)
        
        # Базовая рекомендация
        if sector_bias == 'NEUTRAL':
            recommendation = "✅ Любой сигнал подходит"
            quality_adj = 0
        elif signal_type == sector_bias:
            recommendation = "🎯 ИДЕАЛЬНО! Сигнал совпадает с сектором"
            quality_adj = +15  # увеличиваем качество
        else:
            recommendation = "⚠️ Сигнал ПРОТИВ сектора - осторожно"
            quality_adj = -15  # уменьшаем качество
        
        # Дополнительные подсказки по блокам
        block_hint = ""
        if sector_bias == 'LONG':
            block_hint = "Ищите БЫЧЬИ блоки (зеленые) как поддержку"
        elif sector_bias == 'SHORT':
            block_hint = "Ищите МЕДВЕЖЬИ блоки (красные) как сопротивление"
        else:
            block_hint = "Можно использовать любые блоки"
        
        return {
            'ticker': ticker,
            'signal': signal_type,
            'sector': sector,
            'sector_score': sector_score,
            'sector_bias': sector_bias,
            'recommendation': recommendation,
            'block_hint': block_hint,
            'quality_adjustment': quality_adj
        }
    
    def get_sector_for_ticker(self, ticker):
        """
        Определяет сектор по тикеру
        """
        sector_map = {
            # Нефть и газ
            'GAZP': 'oil_gas', 'LKOH': 'oil_gas', 'ROSN': 'oil_gas',
            'TATN': 'oil_gas', 'SNGS': 'oil_gas', 'NVTK': 'oil_gas',
            
            # Металлы
            'CHMF': 'metals', 'GMKN': 'metals', 'PLZL': 'metals',
            'RUAL': 'metals', 'ALRS': 'metals', 'VSMO': 'metals',
            
            # Финансы
            'SBER': 'finance', 'VTBR': 'finance', 'CBOM': 'finance',
            'BSPB': 'finance', 'SBERP': 'finance',
            
            # Потребление
            'MGNT': 'consumer', 'FIVE': 'consumer', 'LENT': 'consumer',
            'MVID': 'consumer', 'BELU': 'consumer', 'SOFL': 'consumer',
            
            # Технологии
            'YNDX': 'tech', 'OZON': 'tech', 'VKCO': 'tech',
            'HEAD': 'tech', 'CNRU': 'tech',
            
            # Энергетика
            'HYDR': 'energy', 'IRAO': 'energy', 'FEES': 'energy',
        }
        return sector_map.get(ticker)

if __name__ == "__main__":
    filter = FundamentalFilterDynamic()
    filter.print_detailed_sector_analysis()
    
    print("\n" + "="*70)
    print("🎯 ТЕСТОВЫЙ АНАЛИЗ СИГНАЛОВ")
    print("="*70)
    
    # Тестовые сигналы из наших позиций
    test_signals = [
        {'Тикер': 'SOFL', 'Сигнал': '🟢 LONG СИГНАЛ'},
        {'Тикер': 'VKCO', 'Сигнал': '🟢 LONG СИГНАЛ'},
        {'Тикер': 'CHMF', 'Сигнал': '🟢 LONG СИГНАЛ'},
        {'Тикер': 'SBER', 'Сигнал': '🟢 LONG СИГНАЛ'},
    ]
    
    for signal in test_signals:
        result = filter.analyze_signal(signal)
        print(f"\n{result['ticker']} ({result['signal']})")
        print(f"   Сектор: {result['sector']} (оценка: {result['sector_score']}, bias: {result['sector_bias']})")
        print(f"   {result['recommendation']}")
        print(f"   💡 {result['block_hint']}")
        if result['quality_adjustment'] != 0:
            print(f"   📊 Корректировка качества: {result['quality_adjustment']:+d}")
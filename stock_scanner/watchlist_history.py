# watchlist_history.py
import json
import os
from datetime import datetime

class WatchlistHistory:
    def __init__(self, filename="watchlist_history.json"):
        self.filename = filename
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"blocks": []}

    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_record(self, record):
        """Добавляет запись о блоке, который был удалён из watchlist"""
        self.data["blocks"].append(record)
        self.save()

    def get_statistics(self):
        """Возвращает статистику по всем обработанным блокам"""
        total = len(self.data["blocks"])
        if total == 0:
            return None

        entered = [b for b in self.data["blocks"] if b.get("outcome") == "entered"]
        missed = [b for b in self.data["blocks"] if b.get("outcome") == "block_missed"]
        would_have_won = [b for b in self.data["blocks"] if b.get("outcome") == "would_have_been_win"]
        would_have_lost = [b for b in self.data["blocks"] if b.get("outcome") == "would_have_been_loss"]
        direction_correct = [b for b in self.data["blocks"] if b.get("direction_correct", False)]

        return {
            "total": total,
            "entered": len(entered),
            "missed": len(missed),
            "would_have_won": len(would_have_won),
            "would_have_lost": len(would_have_lost),
            "direction_correct": len(direction_correct),
            "accuracy": len(direction_correct) / total * 100 if total > 0 else 0
        }

    def print_statistics(self):
        stats = self.get_statistics()
        if not stats:
            print("\n📭 Нет данных в истории")
            return

        print("\n" + "="*100)
        print("📊 СТАТИСТИКА ПО WATCHLIST (исторические блоки)")
        print("="*100)
        print(f"\n📋 ВСЕГО БЛОКОВ: {stats['total']}")
        print(f"   ✅ Вошли: {stats['entered']} ({stats['entered']/stats['total']*100:.1f}%)")
        print(f"   ⏳ Не дошли (удалены): {stats['missed']} ({stats['missed']/stats['total']*100:.1f}%)")
        print(f"   📈 Без входа, но были бы в плюсе: {stats['would_have_won']}")
        print(f"   📉 Без входа, были бы в минусе: {stats['would_have_lost']}")
        print(f"\n🎯 ТОЧНОСТЬ ПРОГНОЗА (направление): {stats['direction_correct']}/{stats['total']} ({stats['accuracy']:.1f}%)")
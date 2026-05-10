# backend/app/services/automation_engine.py
import asyncio
from datetime import datetime
from typing import Callable, Awaitable
from .connector_manager import device_manager

class AutomationRule:
    """Định nghĩa một kịch bản Tự động hóa"""
    def __init__(self, name: str, condition: Callable[[], bool], action: Callable[[], Awaitable[None]]):
        self.name = name
        self.condition = condition  # Hàm kiểm tra điều kiện (IF)
        self.action = action        # Hàm thực thi lệnh (THEN)
        self.is_active = True       # Trạng thái bật/tắt kịch bản
        self.last_triggered_second = -1 # Biến cờ để tránh việc gọi liên tục trong cùng 1 giây

class AutomationEngine:
    def __init__(self):
        self.rules: list[AutomationRule] = []

    def add_rule(self, rule: AutomationRule):
        self.rules.append(rule)
        print(f"Tự động hóa: Đã đăng ký kịch bản '{rule.name}'")

    async def start_engine(self):
        """Vòng lặp vô hạn chạy ngầm để kiểm tra các kịch bản"""
        print("⏳ Automation Engine đã bắt đầu chạy ngầm...")
        while True:
            current_time = datetime.now()
            
            for rule in self.rules:
                if not rule.is_active:
                    continue
                    
                try:
                    # Kiểm tra xem IF (điều kiện) có đúng không?
                    if rule.condition():
                        # Đảm bảo lệnh chỉ chạy 1 lần trong cái giây đó
                        if current_time.second != rule.last_triggered_second:
                            rule.last_triggered_second = current_time.second
                            
                            # Thực thi THEN (hành động)
                            print(f"\n[{current_time.strftime('%H:%M:%S')}] ⚡ TỰ ĐỘNG HÓA KÍCH HOẠT: {rule.name}")
                            await rule.action()
                except Exception as e:
                    print(f"Lỗi khi chạy kịch bản '{rule.name}': {e}")
            
            # Nghỉ 0.5 giây trước khi kiểm tra lại để không làm treo CPU
            await asyncio.sleep(0.5)

# Khởi tạo instance duy nhất
automation_engine = AutomationEngine()
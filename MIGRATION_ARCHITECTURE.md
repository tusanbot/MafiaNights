# معماری مهاجرت MafiaNights

## هدف
انتقال تدریجی منطق پایدار بازی از Global/In-Memory State و فایل‌های JSON به PostgreSQL/Supabase، بدون شکستن نسخه عملیاتی فعلی.

## لایه‌ها

Telegram handlers -> services -> repositories -> PostgreSQL/Supabase

- `player_repository.py`: هویت و پروفایل بازیکن
- `repositories/game_repository.py`: بازی و بازیکنان بازی
- `repositories/turn_repository.py`: نوبت‌ها
- `repositories/challenge_repository.py`: چالش‌ها
- `repositories/scenario_repository.py`: سناریوها
- `services/`: قوانین و orchestration؛ بدون SQL در Handlerها
- `core/game_access.py`: سیاست دسترسی به state عمومی/خصوصی
- `identity_middleware.py` و `player_runtime_bridge.py`: سازگاری با Runtime فعلی

## مرز مهم امنیتی
Role، کارت/نقش مخفی و هر داده خصوصی بازی نباید از مسیر state عمومی به بازیکن برگردد. Handlerهای بازیکن فقط public state و داده خصوصی متعلق به همان بازیکن را می‌گیرند؛ عملیات مدیریت بازی و private state برای moderator محدود می‌شود.

## ترتیب مهاجرت
1. Profile/Identity
2. Game + GamePlayer/Lobby
3. Turn
4. Challenge
5. Scenario
6. حذف تدریجی Global State
7. فعال‌سازی RLS/least-privilege و audit
8. تست بازی کامل و سپس انتقال به main

## اصل سازگاری
`main.py` فعلی تا پایان تست نگه داشته می‌شود. زیرساخت جدید نباید منبع دوم State فعال ایجاد کند؛ هر مهاجرت باید پس از تأیید تست، مالکیت آن بخش را از Runtime قدیمی به Repository منتقل کند.

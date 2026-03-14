#!/bin/bash
# ═══════════════════════════════════════════════════════
#  Пуш Марвела на GitHub — автоматическое определение username
# ═══════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════"
echo "  🦁 Марвел → GitHub"
echo "════════════════════════════════════════"
echo ""

# Удаляем lock-файлы
rm -f .git/HEAD.lock .git/objects/maintenance.lock 2>/dev/null

# ── Пытаемся автоматически найти GitHub username ──────
GH_USER=""

# Способ 1: macOS Keychain
if command -v security &>/dev/null; then
    GH_USER=$(security find-internet-password -s github.com 2>/dev/null | grep "acct" | sed 's/.*"acct"<blob>="\(.*\)"/\1/')
fi

# Способ 2: git global config
if [ -z "$GH_USER" ]; then
    GH_USER=$(git config --global github.user 2>/dev/null)
fi

# Способ 3: из уже сохранённых credentials
if [ -z "$GH_USER" ]; then
    GH_USER=$(git config --global credential.username 2>/dev/null)
fi

# Способ 4: git config user.email → ищем по email через API
if [ -z "$GH_USER" ]; then
    EMAIL=$(git config --global user.email 2>/dev/null)
    if [ -n "$EMAIL" ]; then
        GH_USER=$(curl -s "https://api.github.com/search/users?q=${EMAIL}+in:email" 2>/dev/null \
            | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['items'][0]['login'])" 2>/dev/null)
    fi
fi

# Способ 5: имя из macOS system preferences
if [ -z "$GH_USER" ]; then
    GH_USER=$(id -un 2>/dev/null)
fi

if [ -z "$GH_USER" ]; then
    echo "❌ Не удалось определить GitHub username автоматически."
    exit 1
fi

echo "👤 GitHub username: $GH_USER"
echo ""

# Обновляем remote
git remote set-url origin "https://github.com/${GH_USER}/marvel-bot.git"

# Проверяем существует ли репо
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://github.com/${GH_USER}/marvel-bot")
if [ "$HTTP_CODE" = "404" ]; then
    echo "⚠️  Репо не найдено. Создай его сейчас:"
    echo "   → https://github.com/new"
    echo "   → Repository name: marvel-bot"
    echo "   → Private, без README и .gitignore"
    echo ""
    open "https://github.com/new" 2>/dev/null  # открывает браузер на Mac
    read -p "Создал репо? Нажми Enter..." _
fi

echo "🚀 Пушим на github.com/${GH_USER}/marvel-bot ..."
echo ""

# Пушим — macOS Keychain автоматически подставит токен/пароль
git push -u origin main 2>&1

CODE=$?
echo ""
if [ $CODE -eq 0 ]; then
    echo "✅ Готово! https://github.com/${GH_USER}/marvel-bot"
    open "https://github.com/${GH_USER}/marvel-bot" 2>/dev/null
else
    echo "❌ Ошибка пуша."
    echo ""
    echo "Попробуй вручную:"
    echo "  git remote set-url origin https://ТВОЙ_ТОКЕН@github.com/${GH_USER}/marvel-bot.git"
    echo "  git push -u origin main"
fi

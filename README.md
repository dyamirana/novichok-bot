# novichok-bot

Telegram bot (built with [Aiogram](https://docs.aiogram.dev)) that greets
new members in a specific group. The greeting (text, voice or video) and a
follow-up question with selectable answers are configured by an admin via
an inline menu in a private chat with the bot. The question and its
buttons appear beneath the greeting that new members see.

## Configuration

Environment variables:

- `BOT_TOKEN` – Telegram bot token
- `ADMIN_ID` – Telegram user id of the admin
- `GROUP_ID` – chat id of the group
- `DEEPSEEK_API_KEY` – token for DeepSeek API

All configuration is stored in a SQLite database located at
`data/bot.db`.

## Админ-меню

В личном чате с ботом админ отправляет `/start` и получает меню на
русском языке. Из него можно:

- Задать или изменить приветствие (текст, голос или видео)
- Установить вопрос и ответы-кнопки, а также редактировать и удалять
  существующие кнопки
- Управлять списком пользователей, которым доступна команда `/kuplinov`
- Посмотреть предпросмотр текущего приветствия

Заполнители `{user}` в приветствии, вопросе или ответах кнопок будут
заменены на упоминание нового участника.

## Команда `/kuplinov`

В указанной группе команда генерирует непристойную шутку на основе
последних сообщений через DeepSeek. Пользоваться командой могут только
админ и пользователи из разрешённого списка. Для обычных пользователей
действует ограничение — не чаще одного раза в минуту.

## Run with docker-compose

```bash
docker-compose up --build
```

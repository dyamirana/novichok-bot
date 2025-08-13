# novichok-bot

Telegram bot (built with [Aiogram](https://docs.aiogram.dev)) that greets
new members in a specific group. The greeting (text, voice or video) and a
follow-up question with selectable answers are configured by an admin via
an inline menu in a private chat with the bot. The question and its
buttons appear beneath the greeting that new members see.

## Configuration

Environment variables:

- `BOT_TOKEN` – Telegram bot token
- `BOT_TOKENS` – comma-separated list of `Personality:token` pairs. The bot with
  personality `JoePeach` acts as the admin bot and sends greetings. All
  containers should receive the full list so a random personality can reply.
- `PERSONALITY` – run only a single personality in the current container
- `ADMIN_ID` – Telegram user id of the admin
- `GROUP_ID` – chat id of the group
- `DEEPSEEK_API_KEY` – token for DeepSeek API

Prompts for personalities are loaded from files in `data/prompts/NAME.txt`
and can be changed at runtime. After every 10 messages in the group there is
a 50% chance of a random personality replying, synchronised across
containers via Redis.

All configuration is stored in a SQLite database located at `data/bot.db`.

## Админ-меню

В личном чате с ботом админ отправляет `/start` и получает меню на
русском языке. Из него можно:

- Задать или изменить приветствие (текст, голос или видео)
- Установить вопрос и ответы-кнопки, а также редактировать и удалять
  существующие кнопки
- Управлять списком пользователей, которым доступны команды `/kuplinov` и `/joepeach`
- Посмотреть предпросмотр текущего приветствия

Заполнители `{user}` в приветствии, вопросе или ответах кнопок будут
заменены на упоминание нового участника.

## Команды `/kuplinov` и `/joepeach`

В указанной группе команда `/kuplinov` генерирует непристойную шутку на
основе последних сообщений через DeepSeek. Для контекста используются до 10
последних реплик чата, включая ответы бота. Если команду вызвать в ответ на
сообщение или с пересланным сообщением, текст этого сообщения считается
приоритетным при генерации шутки.

Команда `/joepeach` отвечает в стиле Ильи Мэддисона (JoePeach), сохраняя его
постироничный, местами грубый и саркастический тон. Для обеих команд
используется общий список разрешённых пользователей. Для остальных действует
ограничение — не чаще одного раза в минуту.

## Run with docker-compose

```bash
docker-compose up --build
```

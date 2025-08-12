# novichok-bot

Telegram bot (built with [Aiogram](https://docs.aiogram.dev)) that greets
new members in a specific group. The greeting (text, voice or video) and
a follow-up question with selectable answers are configured by an admin
via a private chat with the bot using a finite-state machine.

## Configuration

Environment variables:

- `BOT_TOKEN` – Telegram bot token
- `ADMIN_ID` – Telegram user id of the admin
- `GROUP_ID` – chat id of the group
- `DEEPSEEK_API_KEY` – token for DeepSeek API

In a private chat, the admin can run commands to configure behavior:

- `/set_greeting` – bot asks for a text, voice or video to use for the greeting
- `/set_question` – set the question text
- `/add_button` – interactive addition of a button and its reply
- `/clear_buttons` – remove all buttons

Placeholder `{user}` in the greeting, question or responses will be
replaced with the new member mention.

In the configured group chat:

- `/kuplinov` – generate an uncensored joke based on recent messages using DeepSeek

## Run with docker-compose

```bash
docker-compose up --build
```
